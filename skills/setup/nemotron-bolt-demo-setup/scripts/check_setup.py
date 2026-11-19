"""Verify the Nemotron 3.5 Bolt demo setup, phase by phase.

    python check_setup.py --phase all|hermes|python|model|paths|config [--verify-sha]
            [--hermes-root DIR] [--profile NAME] [--runtime DIR] [--llama DIR] [--repo DIR]

Prints PASS/FAIL/WARN lines and exits 1 if any FAIL. Read-only except for one short request to
the model server. --verify-sha hashes the 22 GB model file (a minute or two on NVMe).
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_DEFAULT = HERE.parents[3]

MODELS = {
    "NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB.gguf": (22018326528, "91d63363e782c8a3d5f4be42816eba8e0d42dd2530bd07a7d0d2dc440599af75"),
    "NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB-LiLiCorr.gguf": (998242560, "080e1ea41c9562a7804dbf30c6fbd4d17e216c6b8ff666f88e6edb1816010194"),
}
EXPECTED_ALIAS = "nemotron-3.5-bolt"
EXPECTED_CTX = 65536

results = []


def report(status, phase, msg):
    results.append(status)
    print(f"{status:4} [{phase}] {msg}")


def ok(cond, phase, msg_ok, msg_fail, warn=False):
    report("PASS" if cond else ("WARN" if warn else "FAIL"), phase, msg_ok if cond else msg_fail)
    return cond


def http_json(url, data=None, timeout=20):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data else None,
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def phase_hermes(a, profile):
    ok(Path(a.hermes_root).is_dir(), "hermes", f"Hermes channel-build home exists: {a.hermes_root}",
       f"Hermes home missing: {a.hermes_root} (install the NVIDIA local-offer channel build of Hermes Desktop)")
    ok(shutil.which("hermes-nvidia-local-offer.exe") or shutil.which("hermes-nvidia-local-offer"), "hermes",
       "hermes-nvidia-local-offer CLI on PATH", "hermes-nvidia-local-offer.exe not on PATH", warn=True)
    ok(profile.is_dir(), "hermes", f"profile exists: {profile}", f"profile missing: {profile} (run install.py --hermes-home)")
    ok((profile / "skills" / "productivity" / "chief-of-staff" / "SKILL.md").is_file(), "hermes",
       "chief-of-staff skill installed in profile", "chief-of-staff skill not in profile (install.py)")
    ok((profile / "SOUL.md").is_file(), "hermes", "SOUL.md present", "SOUL.md missing from profile")
    ok((profile / "google_token.json").is_file(), "hermes", "Google token present (not read)",
       "google_token.json missing: connect the demo Google account (QUICKSTART step 3)")
    ws = Path(a.repo) / "CoS_Workspace"
    ok(ws.is_dir(), "hermes", "CoS_Workspace present in repo", "CoS_Workspace missing (seed the workspace, QUICKSTART step 4)", warn=True)
    state = profile / "chief-of-staff-workspace-state.json"
    ok(state.is_file(), "hermes", "workspace state file present (demo data seeded)",
       "workspace state file missing: run demo\\seed_workspace.py", warn=True)


def phase_python(a, profile):
    py = profile / "hermes-agent" / "venv" / "Scripts" / "python.exe"
    if not ok(py.is_file(), "python", f"skill Python exists: {py}", f"skill Python missing: {py} (junction to <runtime>\\python)"):
        return
    pth = list(py.parent.glob("python3*._pth"))
    ok(bool(pth), "python", f"isolation file present: {pth[0].name}" if pth else "", "no python3xx._pth next to python.exe: PYTHONPATH from Hermes Desktop will leak in")
    env = dict(os.environ, PYTHONPATH=r"C:\definitely\not\here", PYTHONUTF8="1")
    r = subprocess.run([str(py), "-c", "import sys, googleapiclient, cryptography, google.auth; print(sys.version.split()[0])"],
                       capture_output=True, text=True, env=env)
    ok(r.returncode == 0, "python", f"imports OK with a hostile PYTHONPATH set (Python {r.stdout.strip()})",
       f"imports failed: {(r.stderr or r.stdout).strip()[-300:]}")
    ok((profile / "shell-init.sh").is_file(), "python", "shell-init.sh in profile", "shell-init.sh missing from profile", warn=True)


def phase_model(a, profile):
    llama = Path(a.llama)
    srv = llama / "bin" / "llama-server.exe"
    if ok(srv.is_file(), "model", f"llama-server present: {srv}", f"llama-server.exe missing in {llama / 'bin'}"):
        r = subprocess.run([str(srv), "--version"], capture_output=True, text=True)
        ver = (r.stdout + r.stderr)
        m = re.search(r"build (\d{4,6})", ver) or re.search(r"\bb(\d{4,6})\b", ver)
        build = m.group(1) if m else None
        ok(build == "12445", "model", f"llama.cpp build b{build}",
           f"llama.cpp build is {('b' + build) if build else 'unknown'}, reference is b12445", warn=True)
    for name, (size, sha) in MODELS.items():
        f = llama / "models" / name
        if not ok(f.is_file(), "model", f"model file present: {name}", f"model file missing: {f}"):
            continue
        ok(f.stat().st_size == size, "model", f"size matches ({size:,} bytes)", f"size {f.stat().st_size:,} != expected {size:,}: incomplete download")
        if a.verify_sha:
            h = hashlib.sha256()
            with open(f, "rb") as fh:
                for chunk in iter(lambda: fh.read(64 << 20), b""):
                    h.update(chunk)
            ok(h.hexdigest() == sha, "model", f"SHA-256 matches for {name}", f"SHA-256 mismatch for {name}: {h.hexdigest()}")
    for s in ("Start-Bolt.ps1", "Switch-Model.ps1"):
        ok((llama / s).is_file(), "model", f"{s} in {llama}", f"{s} missing from {llama} (copy from demo\\nemotron-bolt)", warn=True)
    try:
        models = http_json("http://127.0.0.1:8080/v1/models")
        alias = models["models"][0]["name"] if "models" in models else models["data"][0]["id"]
        ok(alias == EXPECTED_ALIAS, "model", f"server is serving {alias}", f"server is serving {alias}, expected {EXPECTED_ALIAS}")
        props = http_json("http://127.0.0.1:8080/props")
        n_ctx = props.get("default_generation_settings", {}).get("n_ctx") or props.get("n_ctx")
        ok(n_ctx == EXPECTED_CTX, "model", f"n_ctx = {n_ctx}", f"n_ctx = {n_ctx}, expected {EXPECTED_CTX}")
        resp = http_json("http://127.0.0.1:8080/v1/chat/completions",
                         {"messages": [{"role": "user", "content": "Reply with the single word ready."}], "max_tokens": 40}, timeout=120)
        t = resp.get("timings", {})
        tps = t.get("predicted_per_second")
        ok(tps is not None, "model", f"generation works: {tps:.0f} tokens/s on {t.get('predicted_n')} tokens (reference ~80 on mains; ~35 on battery)" if tps else "",
           "no timings in response")
    except Exception as e:  # noqa: BLE001
        report("FAIL", "model", f"model server not reachable on 127.0.0.1:8080: {e} (start Start-Bolt.ps1)")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Battery).BatteryStatus"],
                             capture_output=True, text=True).stdout.strip()
        if out:
            ok(out == "2", "model", "on mains power", f"battery status {out}: on battery the GPU is throttled; plug in before measuring", warn=True)
    except Exception:  # noqa: BLE001
        pass


def phase_paths(a, profile):
    repo_skill = Path(a.repo) / "skills" / "productivity" / "chief-of-staff"
    prof_skill = profile / "skills" / "productivity" / "chief-of-staff"
    for label, root in (("repo", repo_skill), ("profile", prof_skill)):
        if not root.is_dir():
            report("FAIL", "paths", f"{label} skill folder missing: {root}")
            continue
        texts = {p: p.read_text(encoding="utf-8", errors="replace") for p in root.rglob("*.md")}
        # The reference machine's paths are only wrong if this machine's profile is somewhere else.
        ref = "hermes-channel-build-nvidia-local-offer/profiles/chief-of-staff"
        foreign = str(profile).replace("\\", "/").lower() != f"c:/users/nvidia/appdata/local/{ref}"
        leftovers = [p.name for p, t in texts.items()
                     if "SKILL_ROOT" in t or (foreign and ("Users\\NVIDIA" in t or "Users/NVIDIA" in t))]
        ok(not leftovers, "paths", f"{label} skill has no SKILL_ROOT / foreign-machine paths",
           f"{label} skill still has SKILL_ROOT or another machine's paths in {leftovers} (run configure_paths.py, then re-copy the skill)")
        skill_md = texts.get(root / "SKILL.md", "")
        for var in ("HERMES_HOME", "PYTHON"):
            m = re.search(rf'^(?:export )?{var}="([^"$]+)"', skill_md, re.M)
            if m:
                ok(Path(m.group(1)).exists(), "paths", f"{label} SKILL.md {var} path exists", f"{label} SKILL.md {var} path does not exist: {m.group(1)}")
        m = re.search(r"bash '([^']+run-actions\.sh)'", skill_md)
        if m:
            ok(Path(m.group(1)).is_file(), "paths", f"{label} launcher path exists", f"{label} launcher path missing: {m.group(1)}")
    if repo_skill.is_dir() and prof_skill.is_dir():
        same = (repo_skill / "SKILL.md").read_bytes() == (prof_skill / "SKILL.md").read_bytes()
        ok(same, "paths", "profile SKILL.md matches repo SKILL.md", "profile SKILL.md differs from repo (copy the skill into the profile)", warn=True)
    rt = Path(a.runtime)
    for s in ("Reset-Demo.cmd", "Reset-Demo-KeepEmails.cmd", "Next-Run.cmd", "reset_keep_emails.py", "snapshot_tracker.py"):
        ok((rt / s).is_file(), "paths", f"{s} in runtime folder", f"{s} missing from {rt}", warn=True)


def phase_config(a, profile):
    cfg_path = profile / "config.yaml"
    if not ok(cfg_path.is_file(), "config", "config.yaml present", "config.yaml missing"):
        return
    cfg = cfg_path.read_text(encoding="utf-8")
    checks = [
        (rf"default:\s*{re.escape(EXPECTED_ALIAS)}", f"model.default is {EXPECTED_ALIAS}", f"model.default is not {EXPECTED_ALIAS}"),
        (r"base_url:\s*http://127\.0\.0\.1:8080/v1", "base_url points at the local server", "base_url is not http://127.0.0.1:8080/v1"),
        (r"context_length:\s*65536", "context_length 65536", "context_length is not 65536"),
        (r"temperature:\s*0\.6", "temperature 0.6", "temperature is not 0.6 (reference value)"),
        (r"shell_init_files:\s*\n\s*-\s*\S+shell-init\.sh", "shell_init_files set", "terminal.shell_init_files does not name shell-init.sh"),
        (r"auto_load:\s*\n\s*-\s*chief-of-staff", "skills.auto_load has chief-of-staff", "skills.auto_load lacks chief-of-staff"),
        (r"memory_enabled:\s*false", "memory off", "memory not disabled"),
        (r"title_generation:\s*\n\s*enabled:\s*false", "title generation off", "auxiliary title generation not disabled"),
    ]
    for pat, good, bad in checks:
        ok(re.search(pat, cfg) is not None, "config", good, bad)
    m = re.search(r"shell_init_files:\s*\n\s*-\s*(\S.*)", cfg)
    if m:
        ok(Path(m.group(1).strip()).is_file(), "config", "shell-init.sh path in config exists", f"shell-init.sh path in config missing: {m.group(1).strip()}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase", default="all", choices=["all", "hermes", "python", "model", "paths", "config"])
    ap.add_argument("--hermes-root", default=os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes-channel-build-nvidia-local-offer"))
    ap.add_argument("--profile", default="chief-of-staff")
    ap.add_argument("--repo", default=str(REPO_DEFAULT))
    ap.add_argument("--runtime", default=str(REPO_DEFAULT.parent / "chief-of-staff-runtime"))
    ap.add_argument("--llama", default=str(Path(os.environ.get("USERPROFILE", str(Path.home()))) / "llama.cpp"))
    ap.add_argument("--verify-sha", action="store_true")
    a = ap.parse_args()
    profile = Path(a.hermes_root) / "profiles" / a.profile
    phases = {"hermes": phase_hermes, "python": phase_python, "model": phase_model, "paths": phase_paths, "config": phase_config}
    for name, fn in phases.items():
        if a.phase in ("all", name):
            fn(a, profile)
    fails = results.count("FAIL")
    print(f"\n{results.count('PASS')} pass, {results.count('WARN')} warn, {fails} fail")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
