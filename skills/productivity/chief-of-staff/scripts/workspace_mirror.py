#!/usr/bin/env python
"""Mirror bounded Google Workspace evidence into the Second Brain vault as linked Obsidian notes.

One hub note (`workspace/Google Workspace.md`) links to one note per source (Gmail, Calendar,
Drive, Sheets, Tasks); each source note links to one note per item; item notes link back and,
where a name matches, to the vault's existing people, meeting, and project pages. The result is a
graph you can watch in Obsidian while the demo runs.

The folder is machine-owned: every run deletes and rewrites `workspace/`. The agent's skills do not
read these notes; they keep using live Google evidence. Run on a schedule (Hermes cron, no agent)
and at the end of a workspace reset so IDs are always current.

Usage: workspace_mirror.py [--snapshot PATH] [--vault PATH] [--keep-snapshot]
  Without --snapshot the bundled ingest runs first (same bounded pull the daily brief uses).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from brief import hermes_home  # noqa: E402

MIRROR_DIR = "workspace"
GMAIL_URL = "https://mail.google.com/mail/u/#all/{thread}"
SOURCES = (
    ("gmail", "Gmail", "messages"),
    ("calendar", "Calendar", "events"),
    ("drive", "Drive", "files"),
    ("sheets", "Sheets", "trackers"),
    ("tasks", "Tasks", "tasks"),
)


# ---------------------------------------------------------------- vault helpers
def vault_path() -> Path:
    connection = hermes_home() / "second-brain.json"
    data = json.loads(connection.read_text(encoding="utf-8"))
    return Path(data["vault_path"])


def slug(text: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")
    return text[:80] or "item"


def frontmatter(title: str, kind: str, tags: list[str], today: str, source: str, **extra: str) -> str:
    lines = [
        "---",
        f"title: {json.dumps(title, ensure_ascii=False)}",
        f"created: {today}",
        f"updated: {today}",
        "type: summary",
        f"tags: [{', '.join(['workspace-mirror', kind] + tags)}]",
        f"sources: [{json.dumps(source, ensure_ascii=False)}]",
        "status: reference",
        "confidence: high",
    ]
    for key, value in extra.items():
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


LABELS: dict[str, str] = {}  # wikilink target -> display title, filled by load_titles


def load_titles(vault: Path, folder: str) -> dict[str, str]:
    """Map a note's title (and file stem) to its wikilink target; remember titles for labels."""
    titles: dict[str, str] = {}
    directory = vault / folder
    if not directory.is_dir():
        return titles
    for note in directory.glob("*.md"):
        stem = note.stem
        titles[stem.replace("-", " ").casefold()] = stem
        LABELS.setdefault(stem, stem.replace("-", " ").title())
        try:
            head = note.read_text(encoding="utf-8", errors="replace")[:600]
        except OSError:
            continue
        match = re.search(r"^title:\s*(.+)$", head, re.M)
        if match:
            title = match.group(1).strip().strip('"')
            titles[title.casefold()] = stem
            LABELS[stem] = title
    return titles


def display_name(address: str) -> str:
    name = address.split("<", 1)[0].strip().strip('"')
    if name:
        return name
    local = address.strip("<> ").split("@", 1)[0]
    return local.replace(".", " ").title()


def link_people(text: str, people: dict[str, str]) -> list[str]:
    """Wikilinks for any known person whose name appears in the text."""
    found = []
    low = text.casefold()
    for name, stem in people.items():
        if len(name) > 3 and name in low and stem not in found:
            found.append(stem)
    return found


def link_titles(text: str, titles: dict[str, str]) -> list[str]:
    low = text.casefold()
    return list(dict.fromkeys(stem for name, stem in titles.items() if len(name) > 5 and name in low))


def wikilinks(stems: list[str]) -> str:
    return ", ".join(f"[[{stem}|{LABELS.get(stem, stem.replace('-', ' ').title())}]]" for stem in stems)


# ---------------------------------------------------------------- note writers
def write_mail(out: Path, items: list[dict], today: str, people: dict, projects: dict) -> list[str]:
    folder = out / "gmail"
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for message in items:
        thread = message.get("thread_id") or message.get("id", "")
        sender = display_name(message.get("from", ""))
        subject = message.get("subject") or "(no subject)"
        stem = f"{slug(sender)}--{slug(subject)}--{thread[-6:]}"
        url = GMAIL_URL.format(thread=thread)
        tags = [t for t, flag in (("unread", message.get("unread")), ("important", message.get("important"))) if flag]
        linked_people = link_people(f"{sender} {message.get('to', '')} {message.get('cc', '')}", people)
        linked_projects = link_titles(f"{subject} {message.get('snippet', '')}", projects)
        body = frontmatter(subject, "gmail", tags, today, url, sender=sender, date=message.get("date", ""), thread_id=thread)
        body += f"# {subject}\n\n"
        body += f"- **From:** {sender}" + (f" ({wikilinks(linked_people)})" if linked_people else "") + "\n"
        body += f"- **Date:** {message.get('date', '')}\n"
        body += f"- **Flags:** {', '.join(tags) or 'read'}\n"
        body += f"- **Open:** [Gmail thread]({url})\n\n"
        if message.get("snippet"):
            body += f"> {message['snippet'].strip()}\n\n"
        if linked_projects:
            body += f"Related: {wikilinks(linked_projects)}\n\n"
        body += "Source: [[Gmail]] · [[Google Workspace]]\n"
        (folder / f"{stem}.md").write_text(body, encoding="utf-8")
        flag = "★" if message.get("important") else ("●" if message.get("unread") else "")
        rows.append(f"| {flag} | {message.get('date', '')[:16]} | {sender} | [[gmail/{stem}\\|{subject}]] |")
    return rows


def write_events(out: Path, items: list[dict], today: str, people: dict, meetings: dict) -> list[str]:
    folder = out / "calendar"
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for event in items:
        title = event.get("title") or "(untitled)"
        start = event.get("start", "")
        stem = f"{start[:10]}--{slug(title)}"
        attendees = ", ".join(a.get("email", "") if isinstance(a, dict) else str(a) for a in event.get("attendees", []))
        linked_people = link_people(f"{event.get('organizer', '')} {attendees}", people)
        linked_meetings = link_titles(title, meetings)
        url = event.get("html_link") or ""
        body = frontmatter(title, "calendar", [], today, url or "calendar", start=start, end=event.get("end", ""))
        body += f"# {title}\n\n- **When:** {start} → {event.get('end', '')}\n- **Organizer:** {event.get('organizer', '')}\n"
        if event.get("location"):
            body += f"- **Where:** {event['location']}\n"
        if event.get("meeting_url"):
            body += f"- **Join:** {event['meeting_url']}\n"
        if url:
            body += f"- **Open:** [Calendar event]({url})\n"
        if attendees:
            body += f"- **Attendees:** {attendees}\n"
        body += "\n"
        if linked_people:
            body += f"People: {wikilinks(linked_people)}\n\n"
        if linked_meetings:
            body += f"Meeting notes: {wikilinks(linked_meetings)}\n\n"
        body += "Source: [[Calendar]] · [[Google Workspace]]\n"
        (folder / f"{stem}.md").write_text(body, encoding="utf-8")
        rows.append(f"| {start[:16].replace('T', ' ')} | [[calendar/{stem}\\|{title}]] | {event.get('organizer', '')} |")
    return rows


def write_files(out: Path, items: list[dict], today: str, projects: dict) -> list[str]:
    folder = out / "drive"
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for item in items:
        name = item.get("name") or "(unnamed)"
        stem = slug(name)
        url = item.get("url", "")
        linked = link_titles(name, projects)
        body = frontmatter(name, "drive", [item.get("kind", "file")], today, url or "drive", modified=item.get("modified", ""))
        body += f"# {name}\n\n- **Type:** {item.get('kind', '')}\n- **Modified:** {item.get('modified', '')} by {item.get('last_editor', '')}\n"
        if url:
            body += f"- **Open:** [{item.get('kind', 'file')}]({url})\n"
        if item.get("description"):
            body += f"\n{item['description']}\n"
        body += "\n"
        if linked:
            body += f"Related: {wikilinks(linked)}\n\n"
        body += "Source: [[Drive]] · [[Google Workspace]]\n"
        (folder / f"{stem}.md").write_text(body, encoding="utf-8")
        rows.append(f"| {item.get('kind', '')} | [[drive/{stem}\\|{name}]] | {item.get('modified', '')[:16]} |")
    return rows


def write_trackers(out: Path, items: list[dict], today: str, people: dict, projects: dict) -> list[str]:
    """Ingest returns labelled lane records: {row, lane, pic, status, latest, next, due, blocker, evidence, artifact, notes}."""
    folder = out / "sheets"
    folder.mkdir(parents=True, exist_ok=True)
    sections = []
    skip = {"row", "lane", "pic", "owner", "status"}
    for tracker in items:
        name = tracker.get("name") or "Tracker"
        url = tracker.get("url", "")
        rows = [r for r in (tracker.get("rows") or []) if isinstance(r, dict) and str(r.get("lane", "")).strip()]
        if not rows:
            continue
        lines = [f"## {name}", ""]
        if url:
            lines += [f"[Open sheet]({url})", ""]
        lines += ["| Lane | Owner | Status | Blocker |", "|---|---|---|---|"]
        for row in rows:
            lane = str(row.get("lane", "")).strip()
            owner = str(row.get("pic") or row.get("owner") or "").strip()
            status = str(row.get("status", "")).strip()
            stem = f"{slug(name)}--{slug(lane)}"
            linked_people = link_people(owner, people)
            linked_projects = link_titles(f"{name} {lane} {row.get('latest', '')}", projects)
            body = frontmatter(f"{lane} ({name})", "sheets", [slug(status)] if status else [], today, url or "sheets",
                               lane=lane, status=status, owner=owner, tracker=name)
            body += f"# {lane}\n\n- **Tracker:** [[Sheets]] · {name}\n- **Owner:** {owner}"
            body += (f" ({wikilinks(linked_people)})" if linked_people else "") + f"\n- **Status:** {status}\n"
            for key, value in row.items():
                if key in skip or not str(value).strip():
                    continue
                label = key.replace("_", " ").capitalize()
                body += f"- **{label}:** {value}\n"
            body += "\n"
            if linked_projects:
                body += f"Related: {wikilinks(linked_projects)}\n\n"
            body += "Source: [[Sheets]] · [[Google Workspace]]\n"
            (folder / f"{stem}.md").write_text(body, encoding="utf-8")
            blocker = str(row.get("blocker", "")).strip().replace("|", "/")
            lines.append(f"| [[sheets/{stem}\\|{lane}]] | {owner} | {status} | {blocker} |")
        sections.append("\n".join(lines))
    return sections


def write_tasks(out: Path, items: list[dict], today: str, projects: dict) -> list[str]:
    folder = out / "tasks"
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for task in items:
        title = task.get("title") or "(untitled)"
        stem = slug(title)
        url = task.get("url", "")
        linked = link_titles(f"{title} {task.get('notes', '')}", projects)
        body = frontmatter(title, "tasks", [slug(task.get("status", ""))], today, url or "tasks", due=task.get("due", ""))
        body += f"# {title}\n\n- **Status:** {task.get('status', '')}\n- **Due:** {task.get('due', '') or 'none'}\n"
        if url:
            body += f"- **Open:** [Google Task]({url})\n"
        if task.get("notes"):
            body += f"\n{task['notes'].strip()}\n"
        body += "\n"
        if linked:
            body += f"Related: {wikilinks(linked)}\n\n"
        body += "Source: [[Tasks]] · [[Google Workspace]]\n"
        (folder / f"{stem}.md").write_text(body, encoding="utf-8")
        rows.append(f"| {task.get('status', '')} | {task.get('due', '')[:10]} | [[tasks/{stem}\\|{title}]] |")
    return rows


def write_source_note(out: Path, label: str, today: str, intro: str, table_header: str, rows: list[str]) -> None:
    body = frontmatter(label, slug(label), [], today, "google-workspace")
    body += f"# {label}\n\n{intro}\n\n"
    if rows:
        if table_header:
            body += table_header + "\n"
        body += "\n".join(rows) + "\n\n"
    else:
        body += "_Nothing in the current window._\n\n"
    body += "Part of [[Google Workspace]].\n"
    (out / f"{label}.md").write_text(body, encoding="utf-8")


def ensure_index_entry(vault: Path) -> None:
    index = vault / "index.md"
    if not index.is_file():
        return
    text = index.read_text(encoding="utf-8")
    if "[[Google Workspace]]" in text:
        return
    text = text.rstrip("\n") + "\n\n## Workspace mirror\n- [[Google Workspace]] — live mirror of Gmail, Calendar, Drive, Sheets, and Tasks (machine-maintained)\n"
    index.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------- main
def build(snapshot: dict, vault: Path) -> dict:
    today = datetime.now().date().isoformat()
    out = vault / MIRROR_DIR
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    people = load_titles(vault, "people")
    projects = load_titles(vault, "projects")
    meetings = load_titles(vault, "meetings")

    counts = {}
    rows = write_mail(out, snapshot.get("messages", []), today, people, projects)
    write_source_note(out, "Gmail", today, "Recent and important mail in the connected mailbox. ★ important, ● unread.",
                      "| | Date | From | Subject |\n|---|---|---|---|", rows)
    counts["messages"] = len(rows)

    rows = write_events(out, snapshot.get("events", []), today, people, meetings)
    write_source_note(out, "Calendar", today, "Events in the ingest window.", "| Start | Event | Organizer |\n|---|---|---|", rows)
    counts["events"] = len(rows)

    rows = write_files(out, snapshot.get("files", []), today, projects)
    write_source_note(out, "Drive", today, "Recently modified files.", "| Type | File | Modified |\n|---|---|---|", rows)
    counts["files"] = len(rows)

    sections = write_trackers(out, snapshot.get("trackers", []), today, people, projects)
    write_source_note(out, "Sheets", today, "Tracker spreadsheets, one lane per note.", "", sections)
    counts["trackers"] = len(sections)

    rows = write_tasks(out, snapshot.get("tasks", []), today, projects)
    write_source_note(out, "Tasks", today, "Open Google Tasks.", "| Status | Due | Task |\n|---|---|---|", rows)
    counts["tasks"] = len(rows)

    generated = snapshot.get("generated_at", "")
    identity = (snapshot.get("identity") or {}).get("email", "")
    hub = frontmatter("Google Workspace", "hub", [], today, "google-workspace", generated_at=generated, account=identity)
    hub += "# Google Workspace\n\nMachine-maintained mirror of the connected Google account. Regenerated on a schedule and after every demo reset; do not edit by hand.\n\n"
    hub += f"- Account: {identity}\n- Snapshot: {generated}\n- Window: {snapshot.get('window', {}).get('start', '')} → {snapshot.get('window', {}).get('end', '')}\n\n"
    hub += "## Sources\n"
    hub += f"- [[Gmail]] — {counts['messages']} messages\n- [[Calendar]] — {counts['events']} events\n- [[Drive]] — {counts['files']} files\n- [[Sheets]] — {counts['trackers']} trackers\n- [[Tasks]] — {counts['tasks']} tasks\n\n"
    hub += "Navigation: [[Home]] · [[index|Wiki Index]]\n"
    (out / "Google Workspace.md").write_text(hub, encoding="utf-8")
    ensure_index_entry(vault)
    counts["vault"] = str(vault)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--snapshot", type=Path, help="Use an existing ingest snapshot instead of running ingest")
    parser.add_argument("--vault", type=Path, help="Vault folder (default: from second-brain.json in HERMES_HOME)")
    parser.add_argument("--keep-snapshot", action="store_true", help="Leave the temporary snapshot on disk")
    args = parser.parse_args()
    vault = args.vault or vault_path()
    if not vault.is_dir():
        print(json.dumps({"ok": False, "error": f"Vault not found: {vault}"}), file=sys.stderr)
        return 1
    snapshot_path = args.snapshot
    temp_dir = None
    try:
        if snapshot_path is None:
            scripts = Path(__file__).resolve().parent
            ingest = scripts.parents[1] / "ingest" / "scripts" / "ingest.py"
            temp_dir = tempfile.mkdtemp(prefix="workspace-mirror-")
            snapshot_path = Path(temp_dir) / "snapshot.json"
            subprocess.run([sys.executable, "-X", "utf8", str(ingest), "--output", str(snapshot_path), "--stdout", "none"],
                           check=True, capture_output=True, encoding="utf-8")
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        counts = build(snapshot, vault)
        print(json.dumps({"ok": True, **counts}, ensure_ascii=False))
        return 0
    except subprocess.CalledProcessError as exc:
        print(json.dumps({"ok": False, "stage": "ingest", "error": (exc.stderr or exc.stdout or str(exc))[:1500]}), file=sys.stderr)
        return 1
    finally:
        if temp_dir and not args.keep_snapshot:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
