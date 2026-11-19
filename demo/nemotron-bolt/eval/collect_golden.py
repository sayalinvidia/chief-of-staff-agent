"""Collect fresh demo sessions as fine-tuning source material.

For each session: reset the demo data (keep-emails reset, full reset as fallback), run the
three demo prompts through the Hermes CLI in one chat against whatever model server is on
127.0.0.1:8080, snapshot the tracker, score the run, and export the full transcript from
state.db into eval\\golden\\<model>\\<timestamp>\\.

    python eval\\collect_golden.py N            run N sessions
    python eval\\collect_golden.py N --no-reset skip the reset before the first session

Do not use Hermes Desktop while this runs (one model slot).
"""
import json
import os
import random
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

RUNTIME = Path(r"C:\Users\NVIDIA\chief-of-staff-runtime")
REPO = Path(r"C:\Users\NVIDIA\chief-of-staff-agent")
HERMES_ROOT = os.path.expandvars(r"%LOCALAPPDATA%\hermes-channel-build-nvidia-local-offer")
PROFILE = Path(HERMES_ROOT) / "profiles" / "chief-of-staff"
PY = str(RUNTIME / "python" / "python.exe")
OUT_ROOT = RUNTIME / "eval" / "golden"

# Phrasings the presenter has actually used, in Desktop sessions.
PROMPTS = [
    ["hey chief of staff, what should i work on today?",
     "hey chief of staff, tell me what should I work on today",
     "hey chief of staff, tell me what should i work on today?"],
    ["help me prepare for the exec review",
     "Help me prepare for the exec review"],
    ["Hey chief of staff, update the status of the NeoAgent V2 tracker",
     "hey chief of staff, update the status of the neoagent v2 tracker"],
]

# Expected tracker after prompt 3 (confirmed in the 17 Nov Desktop runs).
EXPECTED = {
    "Performance results": "Complete",
    "Exec Review deck": "In progress",
    "Agent Messaging": "In progress",
    "Marketing shoot": "Blocked",
    "Partner enablement": "On track",
    "Social rollout": "Awaiting update",
    "Retail demo readiness": "Blocked",
    "Legal intake LGL-2026-0847": "Complete",
}

ERR_MARKERS = ("Traceback", "command not found", "No such file", "returned error", "Error:", "error:", "not recognized", "Permission denied", "usage:")


def server_model():
    with urllib.request.urlopen("http://127.0.0.1:8080/v1/models", timeout=5) as r:
        return json.load(r)["models"][0]["name"]


def on_mains():
    out = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Battery).BatteryStatus"],
                         capture_output=True, text=True).stdout.strip()
    return out == "2", out


def reset_demo(log):
    env = dict(os.environ, HERMES_HOME=str(PROFILE), PYTHONUTF8="1")
    r = subprocess.run([PY, str(RUNTIME / "reset_keep_emails.py")], cwd=REPO, env=env, capture_output=True, text=True)
    (log / "reset.log").write_text(r.stdout + r.stderr, encoding="utf-8")
    if r.returncode == 0:
        return "keep-emails"
    r = subprocess.run([PY, str(REPO / "demo" / "reset_workspace.py")], cwd=REPO, env=env, capture_output=True, text=True)
    (log / "reset-full.log").write_text(r.stdout + r.stderr, encoding="utf-8")
    if r.returncode != 0:
        raise SystemExit("Both resets failed; see " + str(log))
    return "full"


def snapshot_tracker(log, name):
    env = dict(os.environ, HERMES_HOME=str(PROFILE), PYTHONUTF8="1")
    before = set(p.name for p in (RUNTIME / "eval" / "desktop-runs").glob("tracker-*.json"))
    r = subprocess.run([PY, str(RUNTIME / "snapshot_tracker.py")], cwd=REPO, env=env, capture_output=True, text=True)
    new = [p for p in (RUNTIME / "eval" / "desktop-runs").glob("tracker-*.json") if p.name not in before]
    if r.returncode != 0 or not new:
        (log / f"{name}.snapshot-error.txt").write_text(r.stdout + r.stderr, encoding="utf-8")
        return None
    data = json.loads(new[0].read_text(encoding="utf-8"))
    (log / f"{name}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data


def run_prompts(log, prompts):
    env = dict(os.environ, HERMES_HOME=HERMES_ROOT)
    timings = []
    for i, p in enumerate(prompts, 1):
        args = ["hermes-nvidia-local-offer.exe", "-p", "chief-of-staff"] + (["--resume", "latest"] if i > 1 else []) + ["-z", p]
        t0 = time.time()
        r = subprocess.run(args, cwd=REPO / "CoS_Workspace", env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        dt = round(time.time() - t0, 1)
        (log / f"q{i}.reply.md").write_text(r.stdout, encoding="utf-8")
        (log / f"q{i}.stderr.txt").write_text(r.stderr, encoding="utf-8")
        timings.append({"prompt": p, "seconds": dt, "exit": r.returncode})
        print(f"    q{i} {dt}s exit={r.returncode}", flush=True)
    return timings


def export_session(log, start_epoch):
    db = sqlite3.connect(f"file:{PROFILE / 'state.db'}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    sess = db.execute("select * from sessions where source='oneshot' and cast(started_at as real) >= ? order by started_at desc limit 1",
                      (start_epoch - 5,)).fetchone()
    if not sess:
        return None, None
    sysprompt = None
    if sess["system_prompt_hash"]:
        row = db.execute("select prompt from system_prompts where hash=?", (sess["system_prompt_hash"],)).fetchone()
        sysprompt = row[0] if row else None
    msgs = [dict(m) for m in db.execute("select * from messages where session_id=? order by display_order, id", (sess["id"],))]
    for m in msgs:
        for k, v in list(m.items()):
            if isinstance(v, bytes):
                m[k] = v.hex()
    out = {"session": {k: sess[k] for k in sess.keys() if not isinstance(sess[k], bytes)}, "system_prompt": sysprompt, "messages": msgs}
    (log / "session.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return sess, msgs


def score(msgs, tracker_after, timings):
    asst = [m for m in msgs if m["role"] == "assistant"]
    tools = [m for m in msgs if m["role"] == "tool"]
    finals = [m for m in asst if not m["tool_calls"] and (m["content"] or "").strip()]
    tool_errors = sum(1 for m in tools if any(k in (m["content"] or "")[:400] for k in ERR_MARKERS))
    narrated = sum(1 for m in finals if not (m["content"] or "").lstrip().startswith(("#", "|", ">")))
    out_chars = sum(len(m["content"] or "") for m in asst)
    reason_chars = sum(len(m["reasoning"] or "") for m in asst)
    tracker_ok, diffs = None, []
    if tracker_after:
        live = {r["lane"]: r["status"] for r in tracker_after["sheets"]["campaign_tracker"]}
        diffs = [f"{lane}: {live.get(lane)} (expected {exp})" for lane, exp in EXPECTED.items() if live.get(lane) != exp]
        tracker_ok = not diffs
    return {
        "model_turns": len(asst), "tool_calls": len(tools), "tool_errors": tool_errors, "final_replies": len(finals),
        "narrated_replies": narrated, "output_chars": out_chars, "reasoning_chars": reason_chars,
        "tracker_correct": tracker_ok, "tracker_diffs": diffs, "total_seconds": round(sum(t["seconds"] for t in timings), 1),
        "all_exit_zero": all(t["exit"] == 0 for t in timings),
        # pass: correct and error-free. clean: pass with no narration line before the heading (strippable later).
        "pass": bool(tracker_ok) and tool_errors == 0 and all(t["exit"] == 0 for t in timings),
        "clean": bool(tracker_ok) and tool_errors == 0 and narrated == 0 and all(t["exit"] == 0 for t in timings),
    }


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    do_reset = "--no-reset" not in sys.argv
    model = server_model()
    mains, raw = on_mains()
    print(f"model on server: {model} | mains power: {mains} (status {raw})", flush=True)
    out_dir = OUT_ROOT / model
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random()
    for k in range(n):
        ts = time.strftime("%Y%m%d-%H%M%S")
        log = out_dir / ts
        log.mkdir()
        print(f"[{k + 1}/{n}] {log.name}", flush=True)
        reset_kind = None
        if do_reset or k > 0:
            t0 = time.time()
            reset_kind = reset_demo(log)
            print(f"    reset ({reset_kind}) {round(time.time() - t0)}s", flush=True)
        before = snapshot_tracker(log, "tracker-before")
        prompts = [rng.choice(v) for v in PROMPTS]
        start = time.time()
        timings = run_prompts(log, prompts)
        after = snapshot_tracker(log, "tracker-after")
        sess, msgs = export_session(log, start)
        sc = score(msgs or [], after, timings)
        sc.update({"session_id": sess["id"] if sess else None, "model": model, "mains_power": mains, "reset": reset_kind,
                   "prompts": prompts, "timings": timings, "folder": str(log),
                   "tracker_before_ok": bool(before) and all(
                       r["status"] == {**EXPECTED, "Performance results": "Awaiting update", "Exec Review deck": "Awaiting update",
                                       "Agent Messaging": "Awaiting update", "Legal intake LGL-2026-0847": "Awaiting update"}.get(r["lane"])
                       for r in before["sheets"]["campaign_tracker"])})
        (log / "score.json").write_text(json.dumps(sc, indent=2, ensure_ascii=False), encoding="utf-8")
        with open(OUT_ROOT / "index.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(sc, ensure_ascii=False) + "\n")
        print(f"    turns={sc['model_turns']} tools={sc['tool_calls']} errors={sc['tool_errors']} narrated={sc['narrated_replies']} "
              f"tracker={sc['tracker_correct']} total={sc['total_seconds']}s PASS={sc['pass']} clean={sc['clean']}", flush=True)


if __name__ == "__main__":
    main()
