#!/usr/bin/env python
"""Bounded Google Workspace ingestion for a low-context chief of staff."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

GOOGLE_MIMES = {
    "application/vnd.google-apps.document": "doc",
    "application/vnd.google-apps.spreadsheet": "sheet",
    "application/vnd.google-apps.presentation": "slides",
    "application/vnd.google-apps.folder": "folder",
}
URL_RE = re.compile(r"https?://[^\s<>'\"]+")
OTP_RE = re.compile(
    r"(?i)\b(verification(?:\s+code)?|security\s+code|one[- ]time\s+(?:code|password)|otp|code)"
    r"(\s*(?:is|:)?\s*)\d{4,8}\b"
)


def hermes_home() -> Path:
    override = os.environ.get("HERMES_HOME")
    if override:
        return Path(override).expanduser()
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "hermes"
    return Path.home() / ".hermes"


def default_snapshot_path() -> Path:
    return hermes_home() / "chief-of-staff" / "snapshot.json"


def _iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _header(headers: list[dict[str, str]], name: str) -> str:
    wanted = name.casefold()
    return next((h.get("value", "") for h in headers if h.get("name", "").casefold() == wanted), "")


def _links(text: str, limit: int = 6) -> list[str]:
    seen: list[str] = []
    for raw in URL_RE.findall(text or ""):
        url = raw.rstrip(".,);]")
        if url not in seen:
            seen.append(url)
        if len(seen) >= limit:
            break
    return seen


def redact_sensitive(text: str) -> str:
    """Remove common one-time codes before data reaches model context."""
    return OTP_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", text or "")


def load_credentials() -> Any:
    token_path = hermes_home() / "google_token.json"
    if not token_path.exists():
        raise RuntimeError(
            f"Google OAuth is not connected. Missing {token_path}. "
            "Finish the google-workspace OAuth setup first."
        )
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError as exc:
        raise RuntimeError("Google dependencies are missing; run google-workspace setup.py --install-deps") from exc

    credentials = Credentials.from_authorized_user_file(str(token_path))
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        payload = json.loads(credentials.to_json())
        payload.setdefault("type", "authorized_user")
        token_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if not credentials.valid:
        raise RuntimeError("Google OAuth token is invalid; re-run google-workspace authorization")
    return credentials


def _calendar_timezone(calendar_service: Any) -> str:
    try:
        return calendar_service.settings().get(setting="timezone").execute().get("value", "UTC")
    except Exception:
        local = datetime.now().astimezone().tzinfo
        return getattr(local, "key", None) or "UTC"


def _calendar_window(target: str | None, days_ahead: int, tz_name: str) -> tuple[datetime, datetime]:
    tz = ZoneInfo(tz_name)
    target_day = date.fromisoformat(target) if target else datetime.now(tz).date()
    start = datetime.combine(target_day, time.min, tzinfo=tz)
    return start, start + timedelta(days=days_ahead)


def fetch_calendars(calendar_service: Any, start: datetime, end: datetime, max_events: int) -> tuple[list[dict[str, Any]], list[str]]:
    calendars: list[dict[str, Any]] = []
    token = None
    while True:
        response = calendar_service.calendarList().list(
            pageToken=token,
            minAccessRole="reader",
            showHidden=False,
        ).execute()
        calendars.extend(response.get("items", []))
        token = response.get("nextPageToken")
        if not token:
            break

    selected = [c for c in calendars if c.get("selected", c.get("primary", False))]
    if not selected:
        selected = [c for c in calendars if c.get("primary")][:1]

    events: list[dict[str, Any]] = []
    errors: list[str] = []
    for cal in selected:
        if len(events) >= max_events:
            break
        try:
            page = None
            while len(events) < max_events:
                result = calendar_service.events().list(
                    calendarId=cal["id"],
                    timeMin=_iso_z(start),
                    timeMax=_iso_z(end),
                    singleEvents=True,
                    orderBy="startTime",
                    showDeleted=False,
                    maxResults=min(250, max_events - len(events)),
                    pageToken=page,
                ).execute()
                for event in result.get("items", []):
                    if event.get("status") == "cancelled":
                        continue
                    self_status = next(
                        (a.get("responseStatus") for a in event.get("attendees", []) if a.get("self")),
                        None,
                    )
                    if self_status == "declined":
                        continue
                    start_value = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
                    end_value = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date")
                    attendees = [
                        {
                            "email": a.get("email", ""),
                            "name": a.get("displayName", ""),
                            "status": a.get("responseStatus", ""),
                            "self": bool(a.get("self")),
                        }
                        for a in event.get("attendees", [])[:20]
                    ]
                    text = " ".join(
                        str(event.get(k, "")) for k in ("description", "location", "hangoutLink")
                    )
                    attachment_links = [a.get("fileUrl", "") for a in event.get("attachments", []) if a.get("fileUrl")]
                    events.append(
                        {
                            "id": event.get("id"),
                            "calendar_id": cal.get("id"),
                            "calendar": cal.get("summary", ""),
                            "title": event.get("summary", "(untitled)"),
                            "start": start_value,
                            "end": end_value,
                            "all_day": "date" in event.get("start", {}),
                            "status": event.get("status"),
                            "self_status": self_status,
                            "organizer": event.get("organizer", {}).get("email", ""),
                            "attendees": attendees,
                            "location": event.get("location", ""),
                            "meeting_url": event.get("hangoutLink", ""),
                            "links": list(dict.fromkeys(attachment_links + _links(text))),
                            "html_link": event.get("htmlLink", ""),
                        }
                    )
                page = result.get("nextPageToken")
                if not page:
                    break
        except Exception as exc:
            errors.append(f"calendar:{cal.get('summary', cal.get('id'))}: {exc}")

    dedup: dict[tuple[str, str, str], dict[str, Any]] = {}
    for event in events:
        dedup[(event.get("title", ""), event.get("start", ""), event.get("end", ""))] = event
    ordered = sorted(dedup.values(), key=lambda e: (e.get("start") or "", e.get("title") or ""))
    return ordered[:max_events], errors


def fetch_mail(gmail_service: Any, days_back: int, max_messages: int, query: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from actions import decode_body

    profile = gmail_service.users().getProfile(userId="me").execute()
    # The chief of staff manages the active inbox, not just mail received in a
    # rolling time window. Older unread/important work remains actionable until
    # the user clears it. Gmail returns this query newest-first; max_messages keeps
    # the model-facing workload bounded.
    gmail_query = query or "in:inbox -category:promotions -category:social"
    refs: list[dict[str, str]] = []
    page = None
    while len(refs) < max_messages:
        response = gmail_service.users().messages().list(
            userId="me",
            q=gmail_query,
            maxResults=min(100, max_messages - len(refs)),
            pageToken=page,
        ).execute()
        refs.extend(response.get("messages", []))
        page = response.get("nextPageToken")
        if not page:
            break

    messages: list[dict[str, Any]] = []
    for ref in refs[:max_messages]:
        msg = gmail_service.users().messages().get(
            userId="me",
            id=ref["id"],
            format="full",
        ).execute()
        headers = msg.get("payload", {}).get("headers", [])
        text = decode_body(msg.get("payload", {})) or msg.get("snippet", "")
        snippet = redact_sensitive(re.sub(r"\s+", " ", text).strip())
        preview = snippet if len(snippet) <= 500 else snippet[:499].rsplit(" ", 1)[0] + "…"
        # A longer bounded excerpt lets the Second Brain mirror answer tracker-evidence
        # questions locally; the brief packet keeps using the short preview.
        excerpt = snippet if len(snippet) <= 700 else snippet[:699].rsplit(" ", 1)[0] + "…"
        messages.append(
            {
                "id": msg.get("id"),
                "thread_id": msg.get("threadId"),
                "from": _header(headers, "From"),
                "to": _header(headers, "To"),
                "cc": _header(headers, "Cc"),
                "subject": _header(headers, "Subject") or "(no subject)",
                "date": _header(headers, "Date"),
                "internal_ms": int(msg.get("internalDate", "0") or 0),
                "unread": "UNREAD" in msg.get("labelIds", []),
                "important": "IMPORTANT" in msg.get("labelIds", []),
                "labels": msg.get("labelIds", []),
                "snippet": preview,
                "excerpt": excerpt,
                "links": _links(snippet),
            }
        )
    messages.sort(key=lambda m: m.get("internal_ms", 0), reverse=True)
    return messages, {"email": profile.get("emailAddress", ""), "query": gmail_query}


def fetch_drive(drive_service: Any, days_back: int, max_files: int) -> list[dict[str, Any]]:
    cutoff = _iso_z(datetime.now(timezone.utc) - timedelta(days=days_back))
    query = f"trashed = false and modifiedTime >= '{cutoff}'"
    fields = "nextPageToken,files(id,name,mimeType,modifiedTime,createdTime,webViewLink,owners(displayName,emailAddress),lastModifyingUser(displayName,emailAddress),starred,description)"
    response = drive_service.files().list(
        q=query,
        orderBy="modifiedTime desc",
        pageSize=min(max_files, 100),
        fields=fields,
    ).execute()
    files: list[dict[str, Any]] = []
    for item in response.get("files", [])[:max_files]:
        mime = item.get("mimeType", "")
        files.append(
            {
                "id": item.get("id"),
                "name": item.get("name", ""),
                "kind": GOOGLE_MIMES.get(mime, mime),
                "mime_type": mime,
                "modified": item.get("modifiedTime", ""),
                "url": item.get("webViewLink", ""),
                "starred": bool(item.get("starred")),
                "last_editor": item.get("lastModifyingUser", {}).get("displayName", ""),
                "description": re.sub(r"\s+", " ", item.get("description", ""))[:240],
            }
        )
    return files


def fetch_tasks(tasks_service: Any, max_tasks: int = 20, task_list: str = "@default") -> tuple[list[dict[str, Any]], bool]:
    """Read one bounded page of unfinished tasks; never modify the task list."""
    if not 1 <= max_tasks <= 100:
        raise ValueError("max_tasks must be between 1 and 100")
    response = tasks_service.tasks().list(
        tasklist=task_list,
        maxResults=max_tasks,
        showCompleted=False,
        showDeleted=False,
        showHidden=False,
        showAssigned=True,
        fields="nextPageToken,items(id,title,status,due,notes,webViewLink,links,deleted,hidden)",
    ).execute()
    tasks = []
    seen = set()
    for item in response.get("items", [])[:max_tasks]:
        task_id = item.get("id")
        if not task_id or task_id in seen or item.get("status") != "needsAction" or item.get("deleted") or item.get("hidden"):
            continue
        seen.add(task_id)
        notes = redact_sensitive(re.sub(r"\s+", " ", item.get("notes") or "").strip())
        links = " ".join(link.get("link", "") for link in item.get("links", []))
        tasks.append({
            "id": task_id,
            "title": redact_sensitive(item.get("title") or "(untitled)")[:200],
            "status": item["status"],
            # Google Tasks stores a date, not a time to convert to another zone.
            "due": (item.get("due") or "")[:10],
            "notes": notes[:500],
            "links": _links(notes + " " + links),
            "url": item.get("webViewLink") or "https://tasks.google.com/",
        })
    return tasks, bool(response.get("nextPageToken"))


def fetch_trackers(credentials: Any, files: list[dict[str, Any]], max_rows: int = 14) -> list[dict[str, Any]]:
    """Read compact rows from recently found tracker spreadsheets."""
    from googleapiclient.discovery import build

    candidates = [item for item in files if item.get("kind") == "sheet" and "tracker" in item.get("name", "").casefold()]
    if not candidates:
        return []
    sheets = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    output: list[dict[str, Any]] = []
    for item in candidates[:2]:
        # Rows 1-5 hold the tracker's title and status definitions; the lane header is row 6.
        values = sheets.spreadsheets().values().get(
            spreadsheetId=item["id"], range=f"'Campaign Lanes'!A1:J{6 + max_rows}"
        ).execute().get("values", [])
        header_index = next((i for i, cells in enumerate(values) if cells and str(cells[0]).strip().casefold() == "lane"), 5)
        context = [" ".join(str(c).strip() for c in cells if str(c).strip()) for cells in values[:header_index]]
        rows = []
        for sheet_row, cells in enumerate(values[header_index + 1:], start=header_index + 2):
            padded = list(cells) + [""] * (10 - len(cells))
            if padded[0]:
                rows.append({"row": sheet_row, "lane": padded[0], "pic": padded[1], "status": padded[2], "latest": padded[3], "next": padded[4], "due": padded[5], "blocker": padded[6], "evidence": padded[7], "artifact": padded[8]})
        if rows:
            output.append({"id": item["id"], "name": item["name"], "url": item.get("url", ""), "sheet": "Campaign Lanes",
                           "context": [c for c in context if c], "rows": rows})
    return output


def collect(args: argparse.Namespace) -> dict[str, Any]:
    if args.fixture:
        data = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
        data.setdefault("source", "fixture")
        return data

    credentials = load_credentials()
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError("google-api-python-client is missing") from exc

    calendar = build("calendar", "v3", credentials=credentials, cache_discovery=False)
    gmail = build("gmail", "v1", credentials=credentials, cache_discovery=False)
    drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
    tz_name = _calendar_timezone(calendar)
    try:
        start, end = _calendar_window(args.date, args.days_ahead, tz_name)
    except Exception:
        tz_name = "UTC"
        start, end = _calendar_window(args.date, args.days_ahead, tz_name)

    errors: list[str] = []
    events: list[dict[str, Any]] = []
    messages: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    trackers: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []
    tasks_has_more = False
    identity: dict[str, Any] = {}
    try:
        events, calendar_errors = fetch_calendars(calendar, start, end, args.max_events)
        errors.extend(calendar_errors)
    except Exception as exc:
        errors.append(f"calendar: {exc}")
    try:
        messages, identity = fetch_mail(gmail, args.days_back, args.max_messages, args.gmail_query)
    except Exception as exc:
        errors.append(f"gmail: {exc}")
    try:
        files = fetch_drive(drive, args.days_back, args.max_files)
    except Exception as exc:
        errors.append(f"drive: {exc}")
    try:
        trackers = fetch_trackers(credentials, files)
    except Exception as exc:
        errors.append(f"sheets: {exc}")
    try:
        tasks, tasks_has_more = fetch_tasks(
            build("tasks", "v1", credentials=credentials, cache_discovery=False),
            getattr(args, "max_tasks", 20), getattr(args, "task_list", "@default"),
        )
    except Exception as exc:
        errors.append(f"tasks: {exc}")

    return {
        "schema": 1,
        "source": "google_workspace",
        "generated_at": _iso_z(datetime.now(timezone.utc)),
        "timezone": tz_name,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "identity": identity,
        "coverage": {
            "events": len(events),
            "messages": len(messages),
            "files": len(files),
            "tasks": len(tasks),
            "tasks_has_more": tasks_has_more,
            "errors": errors,
        },
        "events": events,
        "messages": messages,
        "files": files,
        "trackers": trackers,
        "tasks": tasks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a bounded Google Workspace snapshot")
    parser.add_argument("--date", help="Target local date (YYYY-MM-DD); defaults to today")
    parser.add_argument("--days-ahead", type=int, default=2)
    parser.add_argument("--days-back", type=int, default=30, help="Drive modification lookback; Gmail uses the bounded active inbox")
    parser.add_argument("--max-events", type=int, default=60)
    parser.add_argument("--max-messages", type=int, default=50)
    parser.add_argument("--max-files", type=int, default=30)
    parser.add_argument("--task-list", default="@default", help="Google Tasks list ID; defaults to My Tasks")
    parser.add_argument("--max-tasks", type=int, default=20, help="Read one page of 1-100 unfinished Google Tasks")
    parser.add_argument("--gmail-query", help="Override the bounded Gmail query")
    parser.add_argument("--output", type=Path, default=default_snapshot_path())
    parser.add_argument("--fixture", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--stdout", choices=("none", "summary", "json"), default="summary")
    args = parser.parse_args()
    if min(args.days_ahead, args.days_back, args.max_events, args.max_messages, args.max_files) < 1:
        parser.error("all numeric bounds must be positive")
    if not 1 <= args.max_tasks <= 100:
        parser.error("--max-tasks must be between 1 and 100")

    try:
        snapshot = collect(args)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.stdout == "json":
        print(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")))
    elif args.stdout == "summary":
        coverage = snapshot.get("coverage", {})
        print(json.dumps({"ok": True, "snapshot": str(args.output), "coverage": coverage}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
