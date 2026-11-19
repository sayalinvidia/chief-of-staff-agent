"""Reset the Chief of Staff demo workspace WITHOUT deleting and re-importing the seeded emails.

Same steps as the repo's full reset (demo/seed_workspace.py --reset), minus the Gmail
delete and re-import: the 82 seeded messages and their IDs stay as they are, so saved
briefs and open links keep working. Gmail drafts are still cleared. Mail dates and
read/unread state are NOT refreshed, so run the full reset at least once per demo day.

Uses the repo's own functions; it does not modify the repo.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(r"C:\Users\NVIDIA\chief-of-staff-agent")
sys.path.insert(0, str(REPO / "demo"))
import seed_workspace as sw  # noqa: E402
import task_scenario  # noqa: E402


def evidence_from_state(emails: list[dict]) -> dict[str, str]:
    """Rebuild the evidence links the full reset gets back from create_emails()."""
    if len(emails) < sw.MEANINGFUL_EMAIL_COUNT:
        raise SystemExit("State file lists too few seeded emails. Run the full reset instead.")
    evidence = {key: emails[index]["url"] for index, key in enumerate(("elena", "mike", "aisha", "daniel", "priya", "prd"))}
    for item in emails:
        for field in ("news_key", "task_key"):
            if item.get(field):
                evidence[item[field]] = item["url"]
    missing = [news["key"] for news in sw.NEWS_EMAILS if news["key"] not in evidence]
    missing += [task["key"] for task in task_scenario.TASKS if task["key"] not in evidence]
    if missing:
        raise SystemExit(f"State file does not identify these seeded emails: {missing}. Run the full reset once first.")
    return evidence


def main() -> int:
    path = sw.state_path()
    if not path.exists():
        raise SystemExit(f"No workspace state at {path}")
    state = json.loads(path.read_text(encoding="utf-8"))
    week_of = sw.week_monday(sw.local_now().date())
    evidence = evidence_from_state(state.get("emails", []))
    sw.check_reset(sw.ROOT, sw.hermes_home())
    sw.check_evidence_cache(sw.ROOT)
    svc = sw.services(tasks_required=bool(state.get("task_list")))

    # The seeded mail must still be there; otherwise tracker and task links would be dead.
    present = sw.seeded_gmail_message_ids(svc["gmail"], {item["id"] for item in state["emails"]})
    gone = [item["id"] for item in state["emails"] if item["id"] not in present]
    if gone:
        raise SystemExit(f"{len(gone)} seeded emails are missing from the mailbox. Run the full reset instead.")

    template_hash = sw.deck_template_hash()
    sw.reset_deck_baseline(svc["slides"], state["slides"]["id"], drive=svc["drive"],
                           restore_template=state["slides"].get("template_sha256") != template_hash)
    state["slides"]["template_sha256"] = template_hash
    sw.clear_seeded_tasks(svc["tasks"], state)
    drafts = sw.clear_all_drafts(svc["gmail"])

    # Calendar: remove the seeded events (tracked, or marked, in the stored week) and recreate them.
    start = state["week_of"] + "T00:00:00" + sw.utc_offset()
    end = (sw.date.fromisoformat(state["week_of"]) + sw.timedelta(days=5)).isoformat() + "T00:00:00" + sw.utc_offset()
    try:
        found = svc["calendar"].events().list(calendarId="primary", timeMin=start, timeMax=end,
                                              singleEvents=True, maxResults=2500).execute().get("items", [])
    except Exception:
        found = []
    event_ids = {item.get("id") for item in state.get("events", [])}
    event_ids |= {item.get("id") for item in found if sw.MARKER in (item.get("description") or "")}
    sw.execute_batched(svc["calendar"], [
        svc["calendar"].events().delete(calendarId="primary", eventId=event_id, sendUpdates="none")
        for event_id in event_ids if event_id
    ], ignore_errors=True)

    task_scenario.ensure_resources(
        SimpleNamespace(ROOT=sw.ROOT, upload_template=sw.upload_template, drive_service=sw.drive_service),
        svc, state, restore=True)
    sw.create_tasks(svc["tasks"], state, evidence)
    today = sw.local_now().date().isoformat()
    sw.reset_sheet_baseline(svc["sheets"], state, evidence, today)
    sw.reset_original_sheet(svc["drive"], svc["sheets"], state, evidence, today)
    state["events"] = sw.create_calendar(svc["calendar"], week_of, state["slides"]["url"], state["doc"]["url"], state["sheet"]["url"])
    state["week_of"] = week_of.isoformat()
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    second_brain = sw.reset_second_brain(sw.ROOT, sw.hermes_home())
    workspace_cleanup = sw.clear_evidence_cache(sw.ROOT)
    print(json.dumps({"ok": True, "status": "reset-kept-emails", "week_of": state["week_of"],
                      "emails_kept": len(state["emails"]), "drafts_cleared": drafts,
                      "events": len(state["events"]), "tasks": len(state.get("tasks", [])),
                      "second_brain": second_brain, "workspace_cleanup": workspace_cleanup}, indent=2))
    return 0


if __name__ == "__main__":
    with sw.workspace_write_lock():
        raise SystemExit(main())
