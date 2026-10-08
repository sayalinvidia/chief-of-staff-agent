#!/usr/bin/env python
"""Focused Google Workspace reads and guarded mutations for chief-of-staff workflows."""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from email.message import EmailMessage
from email.utils import getaddresses
from html import unescape
from pathlib import Path
from typing import Any


def hermes_home() -> Path:
    override = os.environ.get("HERMES_HOME")
    if override:
        return Path(override).expanduser()
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "hermes"
    return Path.home() / ".hermes"


def credentials() -> Any:
    token = hermes_home() / "google_token.json"
    if not token.exists():
        raise RuntimeError(f"Google OAuth is not connected: {token} does not exist")
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = Credentials.from_authorized_user_file(str(token))
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        payload = json.loads(creds.to_json())
        payload.setdefault("type", "authorized_user")
        token.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if not creds.valid:
        raise RuntimeError("Google OAuth token is invalid")
    return creds


def service(name: str, version: str) -> Any:
    from googleapiclient.discovery import build

    return build(name, version, credentials=credentials(), cache_discovery=False)


def emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def require_confirm(args: argparse.Namespace, action: str) -> None:
    if not getattr(args, "confirm", False):
        raise RuntimeError(f"Refusing {action} without --confirm after user approval")


def decode_body(payload: dict[str, Any]) -> str:
    candidates: list[tuple[str, str]] = []

    def walk(part: dict[str, Any]) -> None:
        if part.get("filename"):
            return
        data = part.get("body", {}).get("data")
        if data and part.get("mimeType") in {"text/plain", "text/html"}:
            try:
                text = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")
                candidates.append((part.get("mimeType", ""), text))
            except Exception:
                pass
        for child in part.get("parts", []):
            walk(child)

    walk(payload)
    if not candidates:
        return ""
    plain = next((text for mime, text in candidates if mime == "text/plain"), None)
    text = plain if plain is not None else candidates[0][1]
    if plain is None:
        text = unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def headers(payload: dict[str, Any]) -> dict[str, str]:
    return {h.get("name", "").lower(): h.get("value", "") for h in payload.get("headers", [])}


_MAILBOX: list[str] = []


def mailbox() -> str:
    """The signed-in Gmail address, used in place of the account index in web links.

    `/mail/u/0/` opens whichever Google account the browser signed into first, which in a
    multi-account browser is often not the demo mailbox; `?authuser=<address>` is unambiguous."""
    if not _MAILBOX:
        try:
            address = service("gmail", "v1").users().getProfile(userId="me").execute().get("emailAddress")
            _MAILBOX.append(address if isinstance(address, str) and "@" in address else "0")
        except Exception:
            _MAILBOX.append("0")
    return _MAILBOX[0]


def gmail_url(thread_id: str | None) -> str | None:
    if not thread_id:
        return None
    account = mailbox()
    # authuser= selects the signed-in account by address (or shows the chooser); /u/<address>/
    # can answer "account temporarily unavailable" in multi-account browsers.
    selector = f"?authuser={account}" if account != "0" else "u/0/"
    return f"https://mail.google.com/mail/{selector}#all/{thread_id}"


def gmail_get(args: argparse.Namespace) -> None:
    api = service("gmail", "v1")
    msg = api.users().messages().get(userId="me", id=args.message_id, format="full").execute()
    hdr = headers(msg.get("payload", {}))
    emit({
        "id": msg.get("id"),
        "thread_id": msg.get("threadId"),
        "url": gmail_url(msg.get("threadId")),
        "from": hdr.get("from", ""),
        "to": hdr.get("to", ""),
        "cc": hdr.get("cc", ""),
        "subject": hdr.get("subject", ""),
        "date": hdr.get("date", ""),
        "message_id_header": hdr.get("message-id", ""),
        "body": decode_body(msg.get("payload", {}))[: args.max_chars],
    })


def gmail_thread(args: argparse.Namespace) -> None:
    api = service("gmail", "v1")
    thread = api.users().threads().get(userId="me", id=args.thread_id, format="full").execute()
    output = []
    for msg in thread.get("messages", [])[-args.max_messages :]:
        hdr = headers(msg.get("payload", {}))
        output.append({
            "id": msg.get("id"),
            "from": hdr.get("from", ""),
            "to": hdr.get("to", ""),
            "subject": hdr.get("subject", ""),
            "date": hdr.get("date", ""),
            "body": decode_body(msg.get("payload", {}))[: args.max_chars],
        })
    emit({"thread_id": args.thread_id, "url": gmail_url(thread.get("id") or args.thread_id), "messages": output})


def gmail_search(args: argparse.Namespace) -> None:
    """Return a small metadata-only set of Gmail matches for targeted follow-up."""
    api = service("gmail", "v1")
    limit = min(max(args.max, 1), 10)
    refs = api.users().messages().list(userId="me", q=args.query, maxResults=limit).execute().get("messages", [])
    matches = []
    for ref in refs[:limit]:
        msg = api.users().messages().get(
            userId="me",
            id=ref["id"],
            format="metadata",
            metadataHeaders=["From", "To", "Cc", "Reply-To", "Subject", "Date"],
        ).execute()
        hdr = headers(msg.get("payload", {}))
        matches.append({
            "id": msg.get("id"),
            "thread_id": msg.get("threadId"),
            "labels": msg.get("labelIds", []),
            "url": gmail_url(msg.get("threadId")),
            "from": hdr.get("from", ""),
            "to": hdr.get("to", ""),
            "cc": hdr.get("cc", ""),
            "reply_to": hdr.get("reply-to", ""),
            "subject": hdr.get("subject", ""),
            "date": hdr.get("date", ""),
        })
    emit({"query": args.query, "matches": matches})


def gmail_drafts(args: argparse.Namespace) -> None:
    """Read all saved drafts, including bodies, without a recipient filter."""
    drafts_api = service("gmail", "v1").users().drafts()
    drafts = []
    page_token = None
    while True:
        params = {"userId": "me", "maxResults": 500}
        if page_token:
            params["pageToken"] = page_token
        page = drafts_api.list(**params).execute()
        for ref in page.get("drafts", []):
            draft = drafts_api.get(userId="me", id=ref["id"], format="full").execute()
            msg = draft["message"]
            payload = msg.get("payload", {})
            hdr = headers(payload)
            drafts.append({
                "draft_id": draft["id"],
                "message_id": msg.get("id"),
                "thread_id": msg.get("threadId"),
                "url": gmail_url(msg.get("threadId")),
                "to": hdr.get("to", ""),
                "cc": hdr.get("cc", ""),
                "bcc": hdr.get("bcc", ""),
                "subject": hdr.get("subject", ""),
                "body": decode_body(payload),
            })
        page_token = page.get("nextPageToken")
        if not page_token:
            break
    # Emit only after every page and body succeeds, never a misleading partial list.
    emit({"complete": True, "count": len(drafts), "drafts": drafts})


def gmail_important(args: argparse.Namespace) -> None:
    """Return a bounded set of recent important messages with full bodies."""
    api = service("gmail", "v1")
    limit = min(max(args.max, 1), 20)
    days = min(max(args.newer_than_days, 1), 30)
    query = f"is:important newer_than:{days}d"
    refs = api.users().messages().list(userId="me", q=query, maxResults=limit).execute().get("messages", [])
    messages = []
    for ref in refs[:limit]:
        msg = api.users().messages().get(userId="me", id=ref["id"], format="full").execute()
        hdr = headers(msg.get("payload", {}))
        messages.append({
            "id": msg.get("id"),
            "thread_id": msg.get("threadId"),
            "url": gmail_url(msg.get("threadId")),
            "from": hdr.get("from", ""),
            "to": hdr.get("to", ""),
            "cc": hdr.get("cc", ""),
            "subject": hdr.get("subject", ""),
            "date": hdr.get("date", ""),
            "body": decode_body(msg.get("payload", {}))[: args.max_chars],
        })
    emit({"query": query, "messages": messages})


def validate_recipient_header(value: str, field: str) -> None:
    addresses = [address.strip() for _name, address in getaddresses([value])]
    if not addresses or any("@" not in address or not all(address.rsplit("@", 1)) for address in addresses):
        raise RuntimeError(f"{field} must include a complete email address; search Gmail or reply to a verified message instead")


def _verify_draft_recipients(api: Any, recipient_headers: list[str]) -> None:
    """Verify explicit mailboxes against at most five non-draft messages each."""
    addresses = sorted({address.strip().casefold() for _name, address in getaddresses(recipient_headers) if address.strip()})
    messages = api.users().messages()
    for address in addresses:
        quoted = address.replace("\\", "\\\\").replace('"', '\\"')
        query = f'-in:drafts {{from:"{quoted}" to:"{quoted}" cc:"{quoted}"}}'
        verified = False
        try:
            refs = messages.list(userId="me", q=query, maxResults=5).execute().get("messages", [])
            for ref in refs[:5]:
                candidate = messages.get(
                    userId="me", id=ref["id"], format="metadata",
                    metadataHeaders=["From", "Reply-To", "To", "Cc"],
                ).execute()
                if "DRAFT" in candidate.get("labelIds", []):
                    continue
                values = [header.get("value", "") for header in candidate.get("payload", {}).get("headers", [])
                          if header.get("name", "").casefold() in {"from", "reply-to", "to", "cc"}]
                if address in {mailbox.strip().casefold() for _name, mailbox in getaddresses(values)}:
                    verified = True
                    break
        except Exception as exc:
            raise RuntimeError(f"Recipient {address!r} not verified: Gmail header lookup failed: {type(exc).__name__}: {exc}") from exc
        if not verified:
            raise RuntimeError(f"Recipient {address!r} not verified in bounded non-draft Gmail evidence; use a verified address, or --allow-new-recipient only for an address explicitly supplied or confirmed by the user")


def gmail_draft(args: argparse.Namespace) -> None:
    body_file = getattr(args, "body_file", None)
    body_text = (sys.stdin.read() if body_file == "-" else Path(body_file).read_text(encoding="utf-8")) if body_file else args.body
    if not body_text or not body_text.strip():
        raise RuntimeError("A draft needs a nonempty body")
    expected_to = getattr(args, "expected_to", "")
    if args.reply_to_message and not args.to and not expected_to:
        raise RuntimeError("A reply without --to requires --expected-to from the intended recipient's verified email address")
    if expected_to:
        validate_recipient_header(expected_to, "--expected-to")
    api = service("gmail", "v1")
    message = EmailMessage()
    to = args.to
    subject = args.subject
    thread_id = args.thread_id
    if args.reply_to_message:
        original = api.users().messages().get(
            userId="me",
            id=args.reply_to_message,
            format="metadata",
            metadataHeaders=["From", "Reply-To", "Subject", "Message-ID", "References"],
        ).execute()
        original_headers = headers(original.get("payload", {}))
        to = to or original_headers.get("reply-to") or original_headers.get("from", "")
        original_subject = original_headers.get("subject", "")
        subject = subject or (original_subject if original_subject.casefold().startswith("re:") else f"Re: {original_subject}")
        message_id = original_headers.get("message-id", "")
        references = " ".join(filter(None, [original_headers.get("references", ""), message_id]))
        if message_id:
            message["In-Reply-To"] = message_id
        if references:
            message["References"] = references
        thread_id = original.get("threadId", thread_id)
    if not to or not subject:
        raise RuntimeError("A draft needs recipients and a subject")
    validate_recipient_header(to, "To")
    if expected_to:
        expected = {address.strip().casefold() for _name, address in getaddresses([expected_to])}
        resolved = {address.strip().casefold() for _name, address in getaddresses([to])}
        if expected != resolved:
            raise RuntimeError(f"Draft recipient mismatch: expected {expected_to!r}, resolved {to!r}. Read the intended thread and correct the source message or recipient before retrying")
    if args.cc:
        validate_recipient_header(args.cc, "Cc")
    if not getattr(args, "allow_new_recipient", False) and (args.to or args.cc):
        _verify_draft_recipients(api, [args.to, args.cc])
    message["To"] = to
    if args.cc:
        message["Cc"] = args.cc
    message["Subject"] = subject
    message.set_content(body_text)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    body: dict[str, Any] = {"message": {"raw": raw}}
    if thread_id:
        body["message"]["threadId"] = thread_id
    result = api.users().drafts().create(userId="me", body=body).execute()
    emit({"status": "drafted", "to": str(message["To"]), "subject": str(message["Subject"]),
          "draft_id": result.get("id"), "message_id": result.get("message", {}).get("id")})


def drive_search(args: argparse.Namespace) -> None:
    safe = args.query.replace("'", "\\'")
    query = args.query if args.raw_query else f"trashed = false and fullText contains '{safe}'"
    result = service("drive", "v3").files().list(
        q=query,
        orderBy="modifiedTime desc",
        pageSize=args.max,
        fields="files(id,name,mimeType,modifiedTime,webViewLink,owners(displayName,emailAddress),description)",
    ).execute()
    emit(result.get("files", []))


def docs_get(args: argparse.Namespace) -> None:
    doc = service("docs", "v1").documents().get(documentId=args.document_id).execute()
    chunks: list[str] = []
    for block in doc.get("body", {}).get("content", []):
        for element in block.get("paragraph", {}).get("elements", []):
            chunks.append(element.get("textRun", {}).get("content", ""))
    emit({"id": args.document_id, "title": doc.get("title", ""), "text": "".join(chunks)[: args.max_chars]})


def docs_append(args: argparse.Namespace) -> None:
    require_confirm(args, "Docs append")
    api = service("docs", "v1")
    doc = api.documents().get(documentId=args.document_id).execute()
    end_index = max(1, doc.get("body", {}).get("content", [{}])[-1].get("endIndex", 1) - 1)
    api.documents().batchUpdate(
        documentId=args.document_id,
        body={"requests": [{"insertText": {"location": {"index": end_index}, "text": args.text}}]},
    ).execute()
    emit({"status": "appended", "document_id": args.document_id, "characters": len(args.text)})


def docs_replace(args: argparse.Namespace) -> None:
    require_confirm(args, "Docs text replacement")
    result = service("docs", "v1").documents().batchUpdate(
        documentId=args.document_id,
        body={
            "requests": [
                {
                    "replaceAllText": {
                        "containsText": {"text": args.find, "matchCase": args.match_case},
                        "replaceText": args.replace,
                    }
                }
            ]
        },
    ).execute()
    occurrences = sum(
        reply.get("replaceAllText", {}).get("occurrencesChanged", 0)
        for reply in result.get("replies", [])
    )
    emit({"status": "updated", "document_id": args.document_id, "occurrences_changed": occurrences})


def tracker_read_view(values: list[list[Any]]) -> dict[str, Any] | None:
    """Label tracker cells without interpreting status or dropping columns."""
    aliases = {
        "pic": "owner", "latest update": "latest", "next action": "next",
        "dependency / blocker": "blocker",
    }
    for header_index, row in enumerate(values):
        headers = [str(cell).strip().casefold() for cell in row]
        if "lane" not in headers or "status" not in headers:
            continue
        keys = [aliases.get(header, header) for header in headers]
        # Fall back to raw cells if labels would overwrite or omit any values.
        data_rows = values[header_index + 1:]
        if not all(keys) or len(set(keys)) != len(keys) or any(len(item) > len(keys) for item in data_rows):
            return None
        lanes = [
            {key: item[column] if column < len(item) else "" for column, key in enumerate(keys)}
            for item in data_rows if any(cell != "" for cell in item)
        ]
        return {"context": values[:header_index], "lanes": lanes}
    return None


def sheets_get(args: argparse.Namespace) -> None:
    result = service("sheets", "v4").spreadsheets().values().get(
        spreadsheetId=args.spreadsheet_id,
        range=args.range,
    ).execute()
    metadata = {"spreadsheet_id": args.spreadsheet_id, "range": result.get("range")}
    values = result.get("values", [])
    tracker = tracker_read_view(values)
    if tracker is None:
        emit({**metadata, "values": values})
    else:
        print(json.dumps({**metadata, **tracker}, ensure_ascii=False, indent=2))


def sheets_update(args: argparse.Namespace) -> None:
    require_confirm(args, "Sheets update")
    values = json.loads(args.values)
    if not isinstance(values, list):
        raise RuntimeError("--values must be a JSON array of rows")
    result = service("sheets", "v4").spreadsheets().values().update(
        spreadsheetId=args.spreadsheet_id,
        range=args.range,
        valueInputOption="USER_ENTERED",
        body={"values": values},
    ).execute()
    emit({"status": "updated", **result})


TRACKER_STATUSES = {"On track", "In progress", "Awaiting update", "Blocked", "Complete"}


def _load_tracker_updates(args: argparse.Namespace) -> Any:
    """Load tracker updates without requiring JSON to be shell-escaped."""
    if args.updates is not None:
        payload = args.updates
    elif args.updates_file == "-":
        payload = sys.stdin.read()
    else:
        payload = Path(args.updates_file).read_text(encoding="utf-8")
    return json.loads(payload.removeprefix("\ufeff"))


def sheets_update_lanes(args: argparse.Namespace) -> None:
    """Update tracker lanes by name with validated, named fields."""
    require_confirm(args, "tracker lane update")
    updates = _load_tracker_updates(args)
    if not isinstance(updates, list) or not updates:
        raise RuntimeError("--updates must be a non-empty JSON array")
    lanes = [str(item.get("lane", "")).strip() for item in updates if isinstance(item, dict)]
    if len(lanes) != len(updates) or any(not lane for lane in lanes):
        raise RuntimeError("Every tracker update needs a lane")
    if len(set(lanes)) != len(lanes):
        raise RuntimeError("Each tracker lane may be updated only once")
    for item in updates:
        unknown = set(item) - {"lane", "status", "latest", "next", "due", "blocker", "evidence"}
        if unknown:
            raise RuntimeError(f"Unsupported tracker fields: {sorted(unknown)}; use lane, status, latest, next, due, blocker, evidence")
        if getattr(args, "status_only", True) and set(item) - {"lane", "status"}:
            raise RuntimeError(
                "Status-only updates accept only lane and status; remove other fields and retry. "
                "Nothing was written. Use --include-details only when the user explicitly requested non-status edits."
            )
        if item.get("status") not in TRACKER_STATUSES:
            raise RuntimeError(f"Invalid status for {item['lane']!r}; use one of {sorted(TRACKER_STATUSES)}")

    api = service("sheets", "v4")
    current = api.spreadsheets().values().get(
        spreadsheetId=args.spreadsheet_id,
        range=f"'{args.sheet}'!A6:H100",
    ).execute().get("values", [])
    row_by_lane = {row[0]: index for index, row in enumerate(current[1:], start=7) if row}
    missing = [lane for lane in lanes if lane not in row_by_lane]
    if missing:
        raise RuntimeError(
            f"Tracker lane(s) not found: {missing}. "
            f"Use exact lane names from this sheet: {sorted(row_by_lane)}. "
            "Nothing was written."
        )

    data = []
    unreviewed_blockers = []
    for item in updates:
        row = row_by_lane[item["lane"]]
        if getattr(args, "status_only", True):
            data.append({"range": f"'{args.sheet}'!C{row}", "values": [[item["status"]]]})
            continue
        existing = current[row - 6]
        if (len(existing) > 6 and str(existing[6] or "").strip()
                and item["status"] != existing[2] and not isinstance(item.get("blocker"), str)):
            unreviewed_blockers.append(item["lane"])
        # Sheets skips null cells; an explicit empty string still clears a cell.
        values = [[
            item["status"], item.get("latest"), item.get("next"),
            item.get("due"), item.get("blocker"), item.get("evidence"),
        ]]
        data.append({"range": f"'{args.sheet}'!C{row}:H{row}", "values": values})
    if unreviewed_blockers:
        raise RuntimeError(
            f"Status changes need explicit blocker text for {unreviewed_blockers}: "
            "preserve or revise each dependency, or use an empty string if resolved. Nothing was written."
        )
    result = api.spreadsheets().values().batchUpdate(
        spreadsheetId=args.spreadsheet_id,
        body={"valueInputOption": "USER_ENTERED", "data": data},
    ).execute()
    # Read the changed rows back here so the caller's verification step needs no second call.
    header = current[0] if current else []
    ranges = [f"'{args.sheet}'!A{row_by_lane[lane]}:H{row_by_lane[lane]}" for lane in lanes]
    readback = api.spreadsheets().values().batchGet(spreadsheetId=args.spreadsheet_id, ranges=ranges).execute()
    value_ranges = readback.get("valueRanges", []) if isinstance(readback, dict) else []
    rows = []
    for lane, block in zip(lanes, value_ranges):
        values = (block.get("values") or [[]])[0]
        rows.append({"lane": lane, **{str(header[i]): values[i] if i < len(values) else "" for i in range(1, min(len(header), 8))}})
    emit({"status": "updated", "spreadsheet_id": args.spreadsheet_id, "lanes": lanes, "updated_rows": result.get("totalUpdatedRows", 0), "updated_cells": result.get("totalUpdatedCells", 0), "rows": rows, "verified": True})


def _slide_text(slide: dict[str, Any]) -> str:
    chunks: list[str] = []
    for element in slide.get("pageElements", []):
        for item in element.get("shape", {}).get("text", {}).get("textElements", []):
            chunks.append(item.get("textRun", {}).get("content", ""))
        for row in element.get("table", {}).get("tableRows", []):
            for cell in row.get("tableCells", []):
                for item in cell.get("text", {}).get("textElements", []):
                    chunks.append(item.get("textRun", {}).get("content", ""))
    return re.sub(r"\n{3,}", "\n\n", "".join(chunks)).strip()


def slides_get(args: argparse.Namespace) -> None:
    deck = service("slides", "v1").presentations().get(presentationId=args.presentation_id).execute()
    slides = [
        {"number": index, "object_id": slide.get("objectId"), "text": _slide_text(slide)[: args.max_chars_per_slide]}
        for index, slide in enumerate(deck.get("slides", []), start=1)
    ]
    emit({"id": args.presentation_id, "title": deck.get("title", ""), "url": f"https://docs.google.com/presentation/d/{args.presentation_id}/edit", "slides": slides})


def slides_replace(args: argparse.Namespace) -> None:
    require_confirm(args, "Slides text replacement")
    replacement = {"containsText": {"text": args.find, "matchCase": args.match_case}, "replaceText": args.replace}
    slide_id = getattr(args, "slide_id", None)
    if slide_id is not None:
        if not slide_id.strip():
            raise RuntimeError("--slide-id cannot be empty; use an object_id returned by slides get")
        replacement["pageObjectIds"] = [slide_id]
    result = service("slides", "v1").presentations().batchUpdate(
        presentationId=args.presentation_id,
        body={"requests": [{"replaceAllText": replacement}]},
    ).execute()
    replies = result.get("replies", [])
    occurrences = sum(r.get("replaceAllText", {}).get("occurrencesChanged", 0) for r in replies)
    if not occurrences:
        raise RuntimeError("No matching slide text was replaced; read the intended slide and correct the target before continuing")
    emit({"status": "updated", "presentation_id": args.presentation_id, "occurrences_changed": occurrences})


def slides_delete(args: argparse.Namespace) -> None:
    require_confirm(args, "slide deletion")
    api = service("slides", "v1").presentations()
    deck = api.get(presentationId=args.presentation_id, fields="revisionId,slides(objectId)").execute()
    if args.slide_id not in {slide["objectId"] for slide in deck.get("slides", [])}:
        raise RuntimeError("Slide not found in this presentation; read the deck again before deleting")
    body = {"requests": [{"deleteObject": {"objectId": args.slide_id}}]}
    if deck.get("revisionId"):
        body["writeControl"] = {"requiredRevisionId": deck["revisionId"]}
    api.batchUpdate(presentationId=args.presentation_id, body=body).execute()
    emit({"status": "deleted", "presentation_id": args.presentation_id, "slide_id": args.slide_id})


def calendar_create(args: argparse.Namespace) -> None:
    require_confirm(args, "Calendar event creation")
    event: dict[str, Any] = {
        "summary": args.title,
        "start": {"dateTime": args.start},
        "end": {"dateTime": args.end},
    }
    if args.description:
        event["description"] = args.description
    if args.attendees:
        event["attendees"] = [{"email": email.strip()} for email in args.attendees.split(",") if email.strip()]
    result = service("calendar", "v3").events().insert(
        calendarId=args.calendar,
        body=event,
        sendUpdates="all" if args.attendees else "none",
    ).execute()
    emit({"status": "created", "id": result.get("id"), "url": result.get("htmlLink")})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Focused Google Workspace actions")
    groups = parser.add_subparsers(dest="resource", required=True)

    gmail = groups.add_parser("gmail").add_subparsers(dest="action", required=True)
    p = gmail.add_parser("get")
    p.add_argument("message_id")
    p.add_argument("--max-chars", type=int, default=12000)
    p.set_defaults(func=gmail_get)
    p = gmail.add_parser("thread")
    p.add_argument("thread_id")
    p.add_argument("--max-messages", type=int, default=12)
    p.add_argument("--max-chars", type=int, default=8000)
    p.set_defaults(func=gmail_thread)
    p = gmail.add_parser("search")
    p.add_argument("query")
    p.add_argument("--max", type=int, default=5)
    p.set_defaults(func=gmail_search)
    p = gmail.add_parser("drafts", help="Read all saved drafts with recipients, subjects, threads, and bodies")
    p.set_defaults(func=gmail_drafts)
    p = gmail.add_parser("important")
    p.add_argument("--max", type=int, default=12)
    p.add_argument("--newer-than-days", type=int, default=2)
    p.add_argument("--max-chars", type=int, default=8000)
    p.set_defaults(func=gmail_important)
    p = gmail.add_parser("draft")
    p.add_argument("--to", default="")
    p.add_argument("--expected-to", default="", help="Verify intended recipients; required when deriving a reply recipient")
    p.add_argument("--allow-new-recipient", action="store_true", help="Allow explicit To/Cc addresses supplied or confirmed by the user without prior Gmail evidence")
    p.add_argument("--cc", default="")
    p.add_argument("--subject", default="")
    draft_body = p.add_mutually_exclusive_group(required=True)
    draft_body.add_argument("--body")
    draft_body.add_argument("--body-file", help="Read UTF-8 body text from a file, or - for standard input")
    p.add_argument("--thread-id", default="")
    p.add_argument("--reply-to-message", default="", help="Build a correctly threaded reply draft")
    p.set_defaults(func=gmail_draft)

    drive = groups.add_parser("drive").add_subparsers(dest="action", required=True)
    p = drive.add_parser("search")
    p.add_argument("query")
    p.add_argument("--max", type=int, default=10)
    p.add_argument("--raw-query", action="store_true")
    p.set_defaults(func=drive_search)

    docs = groups.add_parser("docs").add_subparsers(dest="action", required=True)
    p = docs.add_parser("get")
    p.add_argument("document_id")
    p.add_argument("--max-chars", type=int, default=30000)
    p.set_defaults(func=docs_get)
    p = docs.add_parser("append")
    p.add_argument("document_id")
    p.add_argument("--text", required=True)
    p.add_argument("--confirm", action="store_true")
    p.set_defaults(func=docs_append)
    p = docs.add_parser("replace-text")
    p.add_argument("document_id")
    p.add_argument("--find", required=True)
    p.add_argument("--replace", required=True)
    p.add_argument("--match-case", action="store_true")
    p.add_argument("--confirm", action="store_true")
    p.set_defaults(func=docs_replace)

    sheets = groups.add_parser("sheets").add_subparsers(dest="action", required=True)
    p = sheets.add_parser("get")
    p.add_argument("spreadsheet_id")
    p.add_argument("range", nargs="?", default="A1:J80")
    p.set_defaults(func=sheets_get)
    p = sheets.add_parser("update")
    p.add_argument("spreadsheet_id")
    p.add_argument("range")
    p.add_argument("--values", required=True)
    p.add_argument("--confirm", action="store_true")
    p.set_defaults(func=sheets_update)
    p = sheets.add_parser("update-lanes")
    p.add_argument("spreadsheet_id")
    p.add_argument("--sheet", default="Campaign Lanes")
    updates_input = p.add_mutually_exclusive_group(required=True)
    updates_input.add_argument("--updates", help="JSON array of named lane updates")
    updates_input.add_argument("--updates-file", help="JSON file path, or - to read JSON from standard input")
    scope = p.add_mutually_exclusive_group()
    scope.add_argument("--status-only", dest="status_only", action="store_true", default=True, help="Write only Status cells (default); reject all other update fields")
    scope.add_argument("--include-details", dest="status_only", action="store_false", help="Allow named non-status fields only when explicitly requested by the user")
    p.add_argument("--confirm", action="store_true")
    p.set_defaults(func=sheets_update_lanes)

    slides = groups.add_parser("slides").add_subparsers(dest="action", required=True)
    p = slides.add_parser("get")
    p.add_argument("presentation_id")
    p.add_argument("--max-chars-per-slide", type=int, default=4000)
    p.set_defaults(func=slides_get)
    p = slides.add_parser("replace-text")
    p.add_argument("presentation_id")
    p.add_argument("--slide-id", help="Limit replacement to a slide object_id returned by slides get")
    p.add_argument("--find", required=True)
    p.add_argument("--replace", required=True)
    p.add_argument("--match-case", action="store_true")
    p.add_argument("--confirm", action="store_true")
    p.set_defaults(func=slides_replace)
    p = slides.add_parser("delete")
    p.add_argument("presentation_id")
    p.add_argument("--slide-id", required=True, help="Slide object_id returned by slides get, not its display number")
    p.add_argument("--confirm", action="store_true")
    p.set_defaults(func=slides_delete)

    calendar = groups.add_parser("calendar").add_subparsers(dest="action", required=True)
    p = calendar.add_parser("create")
    p.add_argument("--title", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--description", default="")
    p.add_argument("--attendees", default="")
    p.add_argument("--calendar", default="primary")
    p.add_argument("--confirm", action="store_true")
    p.set_defaults(func=calendar_create)
    from workspace_formatting import register_commands
    register_commands(groups, service)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        args.func(args)
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
