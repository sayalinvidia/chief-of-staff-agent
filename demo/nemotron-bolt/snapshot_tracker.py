"""Save the current state of the demo trackers so a finished run can be scored later.

Writes one JSON file per call under eval\\desktop-runs with the status and latest-update
text of every lane in the live campaign tracker and in the reference copy, plus which
saved daily briefs exist. Read-only against Google.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\Users\NVIDIA\chief-of-staff-agent\demo")
import seed_workspace as sw  # noqa: E402

out_dir = Path(r"C:\Users\NVIDIA\chief-of-staff-runtime\eval\desktop-runs")
out_dir.mkdir(parents=True, exist_ok=True)
svc = sw.services()
state = json.loads(sw.state_path().read_text(encoding="utf-8"))
snapshot = {"taken_at": time.strftime("%Y-%m-%d %H:%M:%S"), "taken_epoch": time.time(), "sheets": {}}
for key, label in (("sheet", "campaign_tracker"), ("original_sheet", "reference_copy")):
    rows = svc["sheets"].spreadsheets().values().get(
        spreadsheetId=state[key]["id"], range="'Campaign Lanes'!A7:G14").execute().get("values", [])
    snapshot["sheets"][label] = [
        {"lane": (r + [""] * 7)[0], "status": (r + [""] * 7)[2], "latest": (r + [""] * 7)[3], "blocker": (r + [""] * 7)[6]}
        for r in rows]
briefs = Path(r"C:\Users\NVIDIA\chief-of-staff-agent\CoS_Workspace\DailyBriefs")
snapshot["saved_briefs"] = sorted(p.name for p in briefs.glob("*.md")) if briefs.is_dir() else []
drafts = svc["gmail"].users().drafts().list(userId="me", maxResults=50).execute().get("drafts", [])
snapshot["gmail_drafts"] = len(drafts)
path = out_dir / f"tracker-{time.strftime('%Y%m%d-%H%M%S')}.json"
path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
live = snapshot["sheets"]["campaign_tracker"]
print("Saved", path.name)
print("Live tracker: " + ", ".join(f"{r['lane'][:18]}={r['status']}" for r in live))
