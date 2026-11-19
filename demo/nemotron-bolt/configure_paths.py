"""Rewrite the machine-specific paths in this branch for the machine you are on.

The skill text, the Hermes profile config, the shell init file, the reset scripts and the
evaluation scripts on this branch carry literal paths from the laptop they were built on
(user NVIDIA). Run this once after cloning, before `install.py`:

    python demo\\nemotron-bolt\\configure_paths.py --check      # show what would change
    python demo\\nemotron-bolt\\configure_paths.py              # rewrite in place

Options (all default to the layout the guide recommends):
    --hermes-root   Hermes home folder that holds `profiles\\`  (default: %LOCALAPPDATA%\\hermes-channel-build-nvidia-local-offer)
    --profile       profile name                               (default: chief-of-staff)
    --repo          this repository's folder                   (default: the folder containing this file's grandparent)
    --runtime       folder for the isolated Python and reset helpers (default: <repo parent>\\chief-of-staff-runtime)
    --llama         llama.cpp folder                           (default: <user profile>\\llama.cpp)

Only literal occurrences of the original laptop paths are replaced, in both path spellings
(C:\\... and C:/..., plus the Git Bash /c/... form for the runtime Python).
"""
import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_DEFAULT = HERE.parent.parent

ORIG = {
    "profile": r"C:\Users\NVIDIA\AppData\Local\hermes-channel-build-nvidia-local-offer\profiles\chief-of-staff",
    "hermes_root": r"C:\Users\NVIDIA\AppData\Local\hermes-channel-build-nvidia-local-offer",
    "runtime": r"C:\Users\NVIDIA\chief-of-staff-runtime",
    "repo": r"C:\Users\NVIDIA\chief-of-staff-agent",
    "llama": r"C:\Users\NVIDIA\llama.cpp",
}

FILES = [
    "skills/productivity/chief-of-staff/SKILL.md",
    "skills/productivity/chief-of-staff/references/command-reference.md",
    "skills/productivity/chief-of-staff/references/updating-project-tracker.md",
    "demo/nemotron-bolt/config.chief-of-staff.yaml",
    "demo/nemotron-bolt/shell-init.sh",
    "demo/nemotron-bolt/Reset-Demo.cmd",
    "demo/nemotron-bolt/Reset-Demo-KeepEmails.cmd",
    "demo/nemotron-bolt/Next-Run.cmd",
    "demo/nemotron-bolt/reset_keep_emails.py",
    "demo/nemotron-bolt/snapshot_tracker.py",
    "demo/nemotron-bolt/eval/collect_golden.py",
    "demo/nemotron-bolt/eval/desktop_sessions.py",
    "demo/nemotron-bolt/eval/bolt_facts.py",
]


def spellings(win_path: str):
    """All the ways a Windows path is written in these files."""
    fwd = win_path.replace("\\", "/")
    out = [win_path, fwd, win_path.replace("\\", "\\\\")]
    if len(fwd) > 2 and fwd[1] == ":":
        out.append("/" + fwd[0].lower() + fwd[2:])  # Git Bash /c/Users/...
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hermes-root", default=os.path.join(os.environ.get("LOCALAPPDATA", r"C:\Users\%USERNAME%\AppData\Local"),
                                                          "hermes-channel-build-nvidia-local-offer"))
    ap.add_argument("--profile", default="chief-of-staff")
    ap.add_argument("--repo", default=str(REPO_DEFAULT))
    ap.add_argument("--runtime", default=str(REPO_DEFAULT.parent / "chief-of-staff-runtime"))
    ap.add_argument("--llama", default=str(Path(os.environ.get("USERPROFILE", str(Path.home()))) / "llama.cpp"))
    ap.add_argument("--check", action="store_true", help="report changes without writing")
    a = ap.parse_args()

    new = {
        "profile": str(Path(a.hermes_root) / "profiles" / a.profile),
        "hermes_root": str(Path(a.hermes_root)),
        "runtime": str(Path(a.runtime)),
        "repo": str(Path(a.repo)),
        "llama": str(Path(a.llama)),
    }
    # longest originals first so the profile path is replaced before its parent
    order = sorted(ORIG, key=lambda k: -len(ORIG[k]))
    repo = Path(a.repo)
    total = 0
    for rel in FILES:
        f = repo / rel
        if not f.exists():
            print(f"skip (missing) {rel}")
            continue
        text = f.read_text(encoding="utf-8")
        count = 0
        for key in order:
            for old_sp, new_sp in zip(spellings(ORIG[key]), spellings(new[key])):
                if old_sp in text and old_sp != new_sp:
                    count += text.count(old_sp)
                    text = text.replace(old_sp, new_sp)
        if count:
            print(f"{'would change' if a.check else 'changed'} {count:3d} path(s) in {rel}")
            if not a.check:
                f.write_text(text, encoding="utf-8")
        total += count
    print("new paths:", new)
    print(f"{total} replacement(s){' (dry run)' if a.check else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
