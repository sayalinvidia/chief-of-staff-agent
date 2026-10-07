#!/usr/bin/env python
"""Create, reset, or remove the reference Chief of Staff Google Workspace."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import random
import re
import sys
import time
import tempfile
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from types import SimpleNamespace
from xml.etree import ElementTree
from zipfile import ZipFile
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "productivity" / "ingest" / "scripts"))
from actions import credentials  # noqa: E402
from baseline import reset_sheet_baseline  # noqa: E402
import task_scenario
from news_scenario import NEWS_EMAILS
from second_brain_seed import check_reset, reset_second_brain  # noqa: E402
from evidence_cache import check_evidence_cache, clear_evidence_cache  # noqa: E402
from googleapiclient.discovery import build  # noqa: E402
from googleapiclient.errors import HttpError  # noqa: E402

MARKER = "chief-of-staff-reference-workspace-v1"
STATE_FILE = "chief-of-staff-workspace-state.json"
TZ_NAME = os.environ.get("CHIEF_OF_STAFF_WORKSPACE_TZ", "America/Los_Angeles")
STATUS_VALUES = ["On track", "In progress", "Awaiting update", "Blocked", "Complete"]
MEANINGFUL_EMAIL_COUNT = 6 + len(NEWS_EMAILS)
BACKGROUND_EMAIL_COUNT = 70
CONTACT_EMAIL_COUNT = 1
EMAIL_REFERENCE_HOUR = 9
EMAIL_REFERENCE_MINUTE = 12
# Google accepts up to 50 requests per batch (100 for Gmail). The per-request retry in
# execute_batched handles throttling, so batches no longer need to be tiny.
BATCH_SIZE = 25
# messages.import costs 25 quota units against a 250 units/second/user Gmail limit.
GMAIL_IMPORT_BATCH_SIZE = 10
# Concurrent batches per call; Gmail imports stay at two to remain under that quota.
PARALLEL_BATCHES = 4
GMAIL_IMPORT_WORKERS = 2
TASKS_SCOPE = "https://www.googleapis.com/auth/tasks"

BACKGROUND_IDENTITIES = [
    ("Amara", "Okafor"), ("Aarav", "Shah"), ("Sofia", "Alvarez"), ("Liam", "Carter"),
    ("Celeste", "Whitmore"), ("Mateo", "Silva"), ("Iris", "Kimura"), ("Jonah", "Foster"),
    ("Nora", "Dubois"), ("Ethan", "Novak"), ("Amina", "Hassan"), ("Diego", "Morales"),
    ("Hana", "Park"), ("Ravi", "Desai"), ("Lucia", "Romero"), ("Felix", "Schneider"),
    ("Yara", "Haddad"), ("Kofi", "Mensah"), ("Mei", "Chen"), ("Hugo", "Pereira"),
    ("Zainab", "Ali"), ("Theo", "Martin"), ("Anika", "Rao"), ("Carlos", "Mendoza"),
    ("Fatima", "Zahra"), ("Kenji", "Sato"), ("Imani", "Brooks"), ("Miguel", "Santos"),
    ("Laila", "Nasser"), ("Arjun", "Patel"), ("Camille", "Laurent"), ("Javier", "Torres"),
    ("Nia", "Johnson"), ("Haruto", "Tanaka"), ("Gabriela", "Costa"), ("Omar", "Farouk"),
    ("Ana", "Ferreira"), ("Nikhil", "Gupta"), ("Samira", "Rahman"), ("Paolo", "Ricci"),
    ("Emi", "Nakamura"), ("Tariq", "Mahmoud"), ("Beatriz", "Souza"), ("Kai", "Nguyen"),
    ("Dalia", "Khalil"), ("Andre", "Walker"), ("Mina", "Lee"), ("Rafael", "Ortega"),
    ("Alina", "Popov"), ("Yusuf", "Demir"), ("Esme", "Clarke"), ("Bao", "Tran"),
    ("Noemi", "Rossi"), ("Jun", "Choi"), ("Farah", "Saleh"), ("Sora", "Yamamoto"),
    ("Grace", "Wilson"), ("Dev", "Kapoor"), ("Ines", "Martins"), ("Akira", "Watanabe"),
    ("Rosa", "Delgado"), ("Santiago", "Ruiz"), ("Nadia", "Ibrahim"), ("Ren", "Ito"),
    ("Maja", "Kowalski"), ("Luis", "Herrera"), ("Leila", "Mansour"), ("Owen", "Murphy"),
    ("Priyanka", "Bose"), ("Dae", "Kim"),
]

BACKGROUND_TOPICS = [
    ("Community volunteering opportunities", "The community team shared optional volunteering opportunities for colleagues who are interested."),
    ("Photography club photo walk", "The employee photography club posted details for its next optional photo walk."),
    ("Cafeteria menu highlights", "The workplace team shared this week's cafeteria menu highlights."),
    ("Wellness webinar recording", "The wellness team posted a recording for anyone who would like to watch it."),
    ("Office shuttle information", "The facilities team shared general office shuttle information."),
    ("Employee book club selection", "The employee book club announced its next optional reading selection."),
    ("Sustainability challenge recap", "The sustainability group posted a recap of its recent employee challenge."),
    ("Learning library recommendations", "The learning team shared a few optional additions to the employee library."),
    ("Community event photos", "The community team posted photos from a recent employee event."),
    ("Workspace tips digest", "The workplace team shared a short collection of optional workspace tips."),
]

BACKGROUND_AUDIENCES = ["Americas", "EMEA", "APAC", "Remote", "Santa Clara", "Austin", "New York"]



def _hermes_root() -> Path:
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "hermes"
    return Path.home() / ".hermes"


def _active_profile() -> str | None:
    """Profile name from HERMES_PROFILE, else the one the Hermes desktop app has selected."""
    name = os.environ.get("HERMES_PROFILE", "").strip()
    if name:
        return name
    if os.name == "nt" and os.environ.get("APPDATA"):
        try:
            data = json.loads((Path(os.environ["APPDATA"]) / "Hermes" / "active-profile.json").read_text(encoding="utf-8"))
            name = str(data.get("profile", "")).strip()
            return name or None
        except (OSError, ValueError, AttributeError):
            return None
    return None


def hermes_home() -> Path:
    """HERMES_HOME if set; otherwise the active profile's folder when it holds the demo state, else the Hermes root."""
    if os.environ.get("HERMES_HOME"):
        return Path(os.environ["HERMES_HOME"]).expanduser()
    root = _hermes_root()
    profile = _active_profile()
    home = root
    if profile:
        candidate = root / "profiles" / profile
        if (candidate / STATE_FILE).is_file() or (candidate / "google_token.json").is_file():
            home = candidate
    # The ingest/brief helpers read HERMES_HOME themselves (credentials, token paths), so
    # publish the resolved home once to keep every script on the same profile.
    os.environ["HERMES_HOME"] = str(home)
    return home


def state_path() -> Path:
    return hermes_home() / STATE_FILE


@contextmanager
def workspace_write_lock():
    """Serialize this user's seed/reset/cleanup runs, including other profiles."""
    # Keep the file: deleting a lock file can let another process lock a new inode.
    # The OS releases the lock when the handle closes, including after a crash.
    path = Path(tempfile.gettempdir()) / "chief-of-staff-workspace.lock"
    with path.open("a+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("Another demo seed/reset/cleanup is running. Wait for it to finish before retrying.") from exc
        yield


def local_now() -> datetime:
    return datetime.now(ZoneInfo(TZ_NAME))


def week_monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def utc_offset() -> str:
    raw = local_now().strftime("%z")
    return raw[:3] + ":" + raw[3:]


def iso(day: date, hm: str) -> str:
    return f"{day.isoformat()}T{hm}:00{utc_offset()}"


def task_service(creds, *, required: bool = False):
    """Check optional Tasks access before any seed/reset writes begin."""
    setup_hint = "Enable Google Tasks API in the OAuth client's project and rerun setup/google-workspace/setup.py to grant Google Tasks access."
    issue = "Google Tasks permission has not been granted."
    if creds.has_scopes([TASKS_SCOPE]):
        api = build("tasks", "v1", credentials=creds, cache_discovery=False)
        try:
            api.tasklists().list(maxResults=1).execute()
            return api
        except HttpError as error:
            if error.resp.status != 403:
                raise
            issue = "Google Tasks API access is unavailable."
    if required:
        raise RuntimeError(f"{issue} {setup_hint} No workspace reset or cleanup was started.")
    print(f"Skipping sample Google Tasks: {issue} {setup_hint}", file=sys.stderr)
    return None


def drive_service():
    """A fresh Drive client; googleapiclient services are not thread-safe, so parallel uploads each need one."""
    return build("drive", "v3", credentials=credentials(), cache_discovery=False)


def services(*, tasks_required: bool = False):
    creds = credentials()
    return {
        "tasks": task_service(creds, required=tasks_required),
        "drive": build("drive", "v3", credentials=creds, cache_discovery=False),
        "docs": build("docs", "v1", credentials=creds, cache_discovery=False),
        "sheets": build("sheets", "v4", credentials=creds, cache_discovery=False),
        "slides": build("slides", "v1", credentials=creds, cache_discovery=False),
        "calendar": build("calendar", "v3", credentials=creds, cache_discovery=False),
        "gmail": build("gmail", "v1", credentials=creds, cache_discovery=False),
    }


def _is_rate_limit(error: Exception) -> bool:
    if not isinstance(error, HttpError):
        return False
    if error.resp.status == 429:
        return True
    if error.resp.status != 403:
        return False
    try:
        reasons = {item.get("reason") for item in json.loads(error.content).get("error", {}).get("errors", [])}
    except (ValueError, TypeError):
        return False
    return bool(reasons & {"rateLimitExceeded", "userRateLimitExceeded"})


def _rate_limit_delay(error: Exception) -> float:
    value = error.resp.get("retry-after", "0")
    try:
        return max(0.0, float(value))
    except (ValueError, TypeError):
        from email.utils import parsedate_to_datetime
        try:
            return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
        except (ValueError, TypeError, OverflowError):
            return 0.0


def _batch_http():
    """A per-thread authorized transport; httplib2 connections must not be shared across threads."""
    try:
        import httplib2
        from google_auth_httplib2 import AuthorizedHttp
        return AuthorizedHttp(credentials(), http=httplib2.Http())
    except Exception:
        return None


def _run_batch_chunk(api: Any, requests: list[Any], pending: list[int], results: list[Any], *, ignore_errors: bool, http: Any = None) -> None:
    """Execute one chunk, retrying only requests Google explicitly throttled."""
    retries = 0
    while pending:
        errors = {}
        completed = set()
        batch = api.new_batch_http_request()

        def callback(request_id, response, exception):
            index = int(request_id)
            if exception is None:
                results[index] = response
                completed.add(index)
            else:
                errors[index] = exception

        for index in pending:
            batch.add(requests[index], callback=callback, request_id=str(index))
        try:
            batch.execute(http=http) if http is not None else batch.execute()
        except HttpError as error:
            if not _is_rate_limit(error):
                raise  # An ambiguous write failure must not be blindly replayed.
            errors.update({i: error for i in pending if i not in completed and i not in errors})
        unreported = set(pending) - completed - errors.keys()
        if unreported:
            raise RuntimeError("Google batch returned incomplete results; check live data before retrying")
        retry = []
        for index, error in sorted(errors.items()):
            if _is_rate_limit(error):
                retry.append(index)
            elif not ignore_errors:
                raise RuntimeError(f"Google batch request {index + 1} failed: {error}") from error
        if not retry:
            break
        if retries >= 5:
            raise RuntimeError(f"Google is still rate limiting request {retry[0] + 1} after 5 retries. Reset stopped; wait before retrying.") from errors[retry[0]]
        delay = max(2 ** retries + random.uniform(0, 1), *(_rate_limit_delay(errors[i]) for i in retry))
        if delay > 60:
            raise RuntimeError(f"Google asks to wait {delay:.0f} seconds before retrying. Reset stopped.") from errors[retry[0]]
        print(f"Google rate limited {len(retry)} request(s); retrying only those in {delay:.1f}s (attempt {retries + 1}/5).", file=sys.stderr, flush=True)
        time.sleep(delay)
        pending = retry
        retries += 1


def execute_batched(api: Any, requests: list[Any], *, ignore_errors: bool = False,
                    batch_size: int | None = None, workers: int | None = None) -> list[Any]:
    """Limit concurrency and retry explicit throttling failures, never successes.

    Google processes each batch mostly serially (about 2-3 s per Calendar or Gmail batch), so
    independent chunks run concurrently, each on its own transport. Without live credentials
    (unit tests) chunks run one after another on the service's shared transport.
    """
    size = batch_size or BATCH_SIZE
    results: list[Any] = [None] * len(requests)
    chunks = [list(range(offset, min(offset + size, len(requests)))) for offset in range(0, len(requests), size)]
    parallel = min(workers or PARALLEL_BATCHES, len(chunks))
    if parallel > 1 and _batch_http() is not None:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            futures = [pool.submit(_run_batch_chunk, api, requests, chunk, results, ignore_errors=ignore_errors, http=_batch_http()) for chunk in chunks]
            for future in futures:
                future.result()
        return results
    for offset, chunk in enumerate(chunks):
        if offset:
            time.sleep(0.25)
        _run_batch_chunk(api, requests, chunk, results, ignore_errors=ignore_errors)
    return results


def move_to_folder(drive, file_id: str, folder_id: str) -> None:
    parents = drive.files().get(fileId=file_id, fields="parents").execute().get("parents", [])
    if parents == [folder_id]:
        return
    drive.files().update(
        fileId=file_id,
        addParents=folder_id,
        removeParents=",".join(parents),
        fields="id,parents",
    ).execute()


def create_folder(drive) -> dict:
    item = drive.files().create(
        body={"name": "NeoAgent V2 Campaign", "mimeType": "application/vnd.google-apps.folder", "description": MARKER},
        fields="id,name,webViewLink",
    ).execute()
    return {"id": item["id"], "url": item.get("webViewLink", f"https://drive.google.com/drive/folders/{item['id']}")}


def upload_template(drive, folder_id: str, filename: str, name: str, mime_type: str) -> dict:
    from googleapiclient.http import MediaFileUpload
    source = ROOT / "demo" / "templates" / filename
    source_mimes = {"application/vnd.google-apps.document": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/vnd.google-apps.spreadsheet": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.google-apps.presentation": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}
    result = drive.files().create(body={"name": name, "parents": [folder_id], "mimeType": mime_type}, media_body=MediaFileUpload(str(source), mimetype=source_mimes[mime_type], resumable=False), fields="id,name,mimeType,webViewLink").execute()
    return {"id": result["id"], "url": result.get("webViewLink", "")}

def create_doc(drive, folder_id): return upload_template(drive, folder_id, "neoagent-v2-campaign-plan.docx", "NeoAgent V2 Campaign Plan", "application/vnd.google-apps.document")
def create_slides(drive, folder_id):
    result = upload_template(drive, folder_id, "neoagent-v2-exec-review.pptx", "NeoAgent V2 Exec Review", "application/vnd.google-apps.presentation")
    result["template_sha256"] = deck_template_hash()
    return result
def create_sheet(drive, folder_id): return upload_template(drive, folder_id, "neoagent-v2-campaign-tracker.xlsx", "NeoAgent V2 Campaign Tracker", "application/vnd.google-apps.spreadsheet")

def reset_original_sheet(drive, sheets, state: dict, evidence: dict, refreshed: str) -> None:
    """Keep one comparison copy at the seeded baseline, separate from the working tracker."""
    if state.get("original_sheet", {}).get("id") == state["sheet"]["id"]:
        raise ValueError("The original comparison copy must be separate from the working tracker.")
    if not state.get("original_sheet", {}).get("id"):
        copied = drive.files().copy(
            fileId=state["sheet"]["id"],
            body={"name": "Reference Tracker", "parents": [state["folder"]["id"]]},
            fields="id,webViewLink",
        ).execute()
        state["original_sheet"] = {"id": copied["id"], "url": copied["webViewLink"]}
    else:
        move_to_folder(drive, state["original_sheet"]["id"], state["folder"]["id"])
        drive.files().update(fileId=state["original_sheet"]["id"], body={"name": "Reference Tracker"}).execute()
    if state["original_sheet"]["id"] == state["sheet"]["id"]:
        raise ValueError("The original comparison copy must be separate from the working tracker.")
    # Keep the same evidence/working-file links; only the write target changes.
    comparison_state = {**state, "sheet": {**state["sheet"], "id": state["original_sheet"]["id"]}}
    reset_sheet_baseline(sheets, comparison_state, evidence, refreshed)

def seeded_email_times(count: int, now: datetime | None = None) -> list[datetime]:
    """Repeat an irregular local-time schedule relative to each reset date."""
    current = (now or local_now()).astimezone(ZoneInfo(TZ_NAME))
    cursor = current.replace(hour=EMAIL_REFERENCE_HOUR, minute=EMAIL_REFERENCE_MINUTE, second=0, microsecond=0)
    # A local fixed seed keeps each email's time stable without uniform spacing.
    rng = random.Random("chief-of-staff-email-times")
    times = []
    for _ in range(count):
        times.append(cursor)
        cursor -= timedelta(minutes=rng.randint(5, 24))
    return times


def seeded_inbox_times(now: datetime | None = None) -> list[datetime]:
    """Assign inbox positions without changing import order or evidence IDs."""
    background = MEANINGFUL_EMAIL_COUNT
    contact = background + BACKGROUND_EMAIL_COUNT
    task = contact + CONTACT_EMAIL_COUNT
    count = task + len(task_scenario.TASKS)
    newest_first = [
        background + 4,  # Celeste: shuttle information
        task + 2,        # Evan: notes assistant design
        0,               # Elena: executive review moved
        background,      # Volunteering
        background + 1,  # Photography club
        2,               # Aisha: deck feedback
        background + 3,  # Wellness recording
        7,               # Samira: robot demo ready
        task,            # Leah: ramp-up resources
        background + 2,  # Cafeteria menu
        5,               # Elena: security PRD
        background + 5,  # Book club
        1,               # Mike: approved results
        background + 6,  # Sustainability recap
        task + 1,        # Tessa: presenter availability
        background + 7,  # Learning library
        6,               # Morgan: SuperBox delay
        background + 8,  # Community photos
        3,               # Daniel: legal clearance
        contact,         # Rafael: social rollout introduction
        background + 9,  # Workspace tips
        4,               # Priya: venue preference
    ]
    remaining = [index for index in range(count) if index not in newest_first]
    received_at = dict(zip(newest_first + remaining, seeded_email_times(count, now)))
    return [received_at[index] for index in range(count)]


def background_email_specs() -> list[tuple[str, str, str]]:
    specs = []
    for index, (first, last) in enumerate(BACKGROUND_IDENTITIES):
        subject, body = BACKGROUND_TOPICS[index % len(BACKGROUND_TOPICS)]
        audience = BACKGROUND_AUDIENCES[index // len(BACKGROUND_TOPICS)]
        specs.append((
            f"{first} {last} <{first.lower()}.{last.lower()}.example@nvidia.com>",
            f"{subject} — {audience}",
            f"Hi,\n\n{body} This is informational only; no action is required.\n\nThanks,\n{first}",
        ))
    return specs


def mail_import_request(
    gmail,
    account: str,
    sender: str,
    subject: str,
    body: str,
    index: int,
    received_at: datetime,
    seed_run_id: str,
    *,
    important: bool,
) -> Any:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = account
    message["Subject"] = subject
    message["Date"] = format_datetime(received_at)
    message["Message-ID"] = f"<{MARKER}-{seed_run_id}-{index}@demo.invalid>"
    message.set_content(body + f"\n\n[{MARKER}]")
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    labels = ["INBOX", "UNREAD"]
    if important:
        labels.append("IMPORTANT")
    return gmail.users().messages().import_(userId="me", body={"raw": raw, "labelIds": labels}, internalDateSource="dateHeader", neverMarkSpam=True, processForCalendar=False)


EXEC_REVIEW_ROLES = "You will present the storyline and proposed demo slate. Planned attendees: you, Elena Park (chair and your manager), Mike Chen (performance results), Aisha Rahman (deck and partner readiness), and Daniel Cho (Legal). Final demo selection and the retail demo owner remain open decisions."


def create_emails(gmail, deck_url: str, sheet_url: str, doc_url: str, resources: dict) -> tuple[list[dict], dict[str, str]]:
    account = gmail.users().getProfile(userId="me").execute()["emailAddress"]
    meaningful = [
        ("Elena Park <elena.example@nvidia.com>", "URGENT: NeoAgent V2 Exec Review moved to 5 PM today", f"Hi,\n\nFollowing up on our one-on-one, please prioritize today’s leadership decisions. If other requests are competing for your time, let me know and I’ll help reprioritize. Leadership moved the NeoAgent V2 Exec Review from Thursday to 5:00 PM today. This is a decision meeting, not a working session. We need two outcomes: approval of the agent-first keynote storyline, and alignment on the GTC demo slate and owners.\n\n{EXEC_REVIEW_ROLES}\n\nDeck: {deck_url}\n\n— Elena"),
        ("Mike Chen <mike.example@nvidia.com>", "APPROVED: NeoAgent V2 performance results for slide 4", "Hi,\n\nThe V2 comparison is ready for today's review.\n\nTask success: NeoAgent V2 92% (184/200), versus NeoAgent V1 80% (160/200), a 12-percentage-point improvement.\nMedian completion time: 30% lower than NeoAgent V1 (V1 index 100, V2 70).\nModel tokens per completed task: 25% fewer than NeoAgent V1 (V1 index 100, V2 75).\n\nBoth versions used the same model, the same 200 internal document, email, and scheduling workflows, and the same execution environment. Success means the expected end state was reached without an incorrect write. Time compares tasks completed by both versions. Token usage includes input, output, and retries per completed task.\n\nPlease use these figures on slide 4 in the exec review deck. Keep the V1 baseline and evaluation scope with the figures. Daniel has cleared this wording for leadership review. These are the fictional internal figures for our demo.\n\nThanks,\nMike"),
        ("Aisha Rahman <aisha.example@nvidia.com>", "Exec Review deck pass: cut slide 6; protect slide 10", f"Hi,\n\nMy review is complete, but I haven't edited the deck.\n\nThe performance comparison is missing the approved results, and the customer example is too long.\n\nThese edits still need to be applied: put Mike's approved NeoAgent V2-versus-V1 results on slide 4, keeping the baseline and evaluation scope.\n\nSummarize the proposed customer-use example from slide 6 in the Customer Example section of slide 7, then remove slide 6 from the live flow. Keep the local laptop comparison, the draft follow-up reviewed by the associate, and customer details staying on the device. It's a proposed use case, not customer validation or an approved demo selection. The demo slate and owners still need a decision.\n\nKeep the opening short so there's time for the decisions on slide 10.\n\nDeck: {deck_url}\n\nThanks,\nAisha"),
        ("Daniel Cho <daniel.example@nvidia.com>", "Legal scope: NeoAgent V2 comparison cleared for leadership review", "Hi,\n\nI've cleared Mike's NeoAgent V2-versus-V1 comparison for today's leadership review. Keep the V1 baseline, the shared model and evaluation setup, and the internal-workflow scope. Please retain 'median' for completion time and 'per completed task' for token usage. The success improvement is 12 percentage points, not 12%.\n\nThis clearance is for leadership review only. Send the final external copy back to me before publication.\n\nThanks,\nDaniel"),
        ("Priya Nair <priya.example@nvidia.com>", "Your preference by 4:30 PM: marketing shoot venue", f"The planned venue is unavailable. I’ve checked the crew, equipment, and production schedule. Studio B Friday and Studio C Tuesday both work.\n\nJust let me know which you prefer by 4:30 PM today, before the holds expire. I’ll handle the booking and production arrangements.\n\nTracker: {sheet_url}"),
        ("Elena Park <elena.example@nvidia.com>", "Review, update, and finalize the Agent Security PRD today", f"Please review, update, and finalize the Agent Security PRD today. Decide the open fallback policies and audit requirements, then reflect those decisions in the document. Protect a focused hour for this review. You can skip the optional launch storyboard session; notes will be posted afterward.\n\nCampaign plan: {doc_url}"),
    ]
    meaningful.extend((item["sender"], item["subject"], item["body"]) for item in NEWS_EMAILS)
    background = background_email_specs()
    contacts = [
        ("Rafael Costa <rafael.example@nvidia.com>", "Introduction: NeoAgent V2 social rollout", "Hi,\n\nI’m Rafael, your point of contact for the NeoAgent V2 social rollout. Feel free to reach out if you have questions or want to discuss the social plans for the campaign.\n\nThanks\nRafael"),
    ]
    data = [(*item, True) for item in meaningful] + [(*item, False) for item in background + contacts]
    task_start = len(data)
    now = local_now()
    data.extend((*item, False) for item in task_scenario.email_specs(resources, now.date()))
    times = seeded_inbox_times(now)
    seed_run_id = uuid.uuid4().hex
    requests = [
        mail_import_request(
            gmail,
            account,
            sender,
            subject,
            body,
            index,
            times[index - 1],
            seed_run_id,
            important=important,
        )
        for index, (sender, subject, body, important) in enumerate(data, 1)
    ]
    results = execute_batched(gmail, requests, batch_size=GMAIL_IMPORT_BATCH_SIZE, workers=GMAIL_IMPORT_WORKERS)
    created = [
        {"id": result["id"], "thread_id": result.get("threadId", result["id"]), "url": f"https://mail.google.com/mail/u/{account}/#all/{result.get('threadId', result['id'])}"}
        for result in results
    ]
    evidence = {"elena": created[0]["url"], "mike": created[1]["url"], "aisha": created[2]["url"], "daniel": created[3]["url"], "priya": created[4]["url"], "prd": created[5]["url"]}
    for index, news in enumerate(NEWS_EMAILS, MEANINGFUL_EMAIL_COUNT - len(NEWS_EMAILS)):
        created[index]["news_key"] = news["key"]
        evidence[news["key"]] = created[index]["url"]
    for index, task in enumerate(task_scenario.TASKS):
        item = created[task_start + index]
        item["task_key"] = task["key"]
        evidence[task["key"]] = item["url"]
    return created, evidence


def create_tasks(api, state: dict, evidence: dict[str, str]) -> None:
    if api is None:
        return
    task_list = api.tasklists().get(tasklist="@default").execute()
    state["task_list"] = {"id": task_list["id"], "title": task_list["title"]}
    requests = [
        api.tasks().insert(tasklist=state["task_list"]["id"], body=body)
        for body in task_scenario.task_bodies(state["task_resources"], evidence, local_now().date(), MARKER)
    ]
    state["tasks"] = [
        {"id": item["id"], "title": item["title"], "url": item.get("webViewLink", "")}
        for item in execute_batched(api, requests)
    ]


def clear_seeded_tasks(api, state: dict) -> None:
    """Remove seeded tasks only; preserve the list and any personal tasks."""
    task_list = state.get("task_list", {}).get("id")
    if not task_list:
        return
    try:
        tracked = {item["id"] for item in state.get("tasks", [])}
        requests = []
        page_token = None
        while True:
            page = api.tasks().list(tasklist=task_list, maxResults=100, showCompleted=True, showHidden=True, pageToken=page_token).execute()
            requests.extend(
                api.tasks().delete(tasklist=task_list, task=item["id"])
                for item in page.get("items", [])
                if item["id"] in tracked or MARKER in (item.get("notes") or "")
            )
            page_token = page.get("nextPageToken")
            if not page_token:
                break
        execute_batched(api, requests)
    except HttpError as error:
        if error.resp.status != 404:
            raise
        state.pop("task_list", None)
    state["tasks"] = []


WEEKDAY_EVENTS = [
    [
        ("08:30", "09:00", "Launch-week priorities", "Set the week's critical path and decision owners."),
        ("09:30", "10:15", "Keynote speaker risk review", "Review the speaker lineup, alternates, and outreach."),
        ("10:30", "11:30", "GTC keynote structure workshop", "Align the four-talk sequence with the agent-first narrative."),
        ("12:00", "13:00", "Working lunch — partner story", "Review how partner proof points support the launch narrative."),
        ("13:30", "14:15", "Campaign operations sync", "Check creative, legal, partner, and production dependencies."),
        ("15:00", "16:00", "Focus block — campaign plan", "Update the campaign plan and unresolved decisions."),
        ("16:30", "17:00", "EMEA handoff", "Share decisions and risks with the regional team."),
    ],
    [
        ("08:45", "09:15", "Performance results check-in", "Review benchmark approval and open wording questions."),
        ("09:30", "10:30", "Resolve NeoAgent V2 creative comments", "Update the hero claim, stage banner, and product UI imagery."),
        ("11:00", "11:45", "Partner enablement review", "Review partner slides and the staged Windows pilot."),
        ("12:30", "13:15", "Lunch with developer relations", "Align launch examples and developer proof points."),
        ("13:30", "14:30", "Local AI Summit demo QA", "Review the three-station script, blockers, and AV dependencies."),
        ("15:15", "16:00", "Agency production check-in", "Review storyboard feedback, budget scenarios, and crew holds."),
        ("16:30", "17:15", "Focus block — partner edits", "Apply the agreed partner-slide changes."),
    ],
    [
        ("08:15", "08:45", "Midweek campaign pulse", "Review delivery risk and the decisions still waiting on owners."),
        ("09:00", "10:00", "Retail demo rehearsal", "Validate the retail demo flow and identify coverage gaps."),
        ("10:30", "11:15", "Social rollout planning", "Review asset readiness, timing, and channel dependencies."),
        ("11:30", "12:00", "Manager one-on-one", "Review launch priorities and executive-meeting goals."),
        ("13:00", "14:30", "Focus block — Agent Security PRD", "Review, update, and finalize the PRD, resolving the open fallback policies and audit requirements."),
        ("15:00", "15:45", "Legal office hours", "Review qualification language and external-copy routing."),
        ("16:15", "17:00", "Creative production review", "Review Priya's booking status and production arrangements."),
    ],
    [
        ("08:30", "09:00", "GTC campaign PMO", "Review critical path, partner commitments, and print readiness."),
        ("09:30", "10:15", "Performance results review", "Check the approved performance results, including the V1 baseline and evaluation scope."),
        ("10:45", "11:30", "Executive deck working session", "Reconcile review comments before leadership circulation."),
        ("12:00", "13:00", "Working lunch — demo slate", "Narrow the GTC demo options and proposed owners."),
        ("13:30", "14:15", "Launch video agency review", "Review booking status and production arrangements with Priya."),
        ("15:00", "16:00", "Focus block — executive deck", "Apply final content updates and verify decision slides."),
        ("16:30", "17:15", "Leadership pre-read handoff", "Prepare the decision-focused pre-read for leadership."),
    ],
    [
        ("08:30", "09:00", "Friday launch pulse", "Close open owners and flag anything that could slip next week."),
        ("09:30", "10:30", "Demo readiness review", "Confirm demo coverage, AV readiness, and escalation owners."),
        ("11:00", "11:45", "Campaign metrics review", "Review readiness signals and outstanding evidence."),
        ("12:30", "13:15", "Team lunch", "Informal launch-team check-in."),
        ("14:00", "15:00", "Weekly planning", "Set next week's milestones and owner commitments."),
        ("16:00", "16:30", "APAC decision handoff", "Share decisions and unresolved risks with APAC."),
    ],
]

WEEKDAY_ADDITIONAL_EVENTS = [
    [
        ("08:00", "08:15", "Executive briefing prep", "Review the overnight brief before the first leadership discussion."),
        ("08:15", "08:45", "Product leadership prep", "Review the day's executive decisions before the launch-week kickoff."),
        ("09:00", "09:30", "Finance and procurement checkpoint", "Clear launch purchases and budget questions awaiting a decision."),
        ("09:50", "10:40", "Executive communications check", "Align leadership messaging and open speaker questions."),
        ("10:50", "11:20", "Speaker outreach huddle", "Confirm outreach owners and backup speakers."),
        ("11:30", "12:00", "Chief of staff office hours", "Resolve quick owner and sequencing questions before lunch."),
        ("12:30", "13:15", "Partner escalation office hours", "Resolve urgent partner dependencies during the working lunch."),
        ("13:15", "13:30", "Decision log review", "Record decisions and flag follow-ups for the afternoon."),
        ("13:50", "14:40", "Creative delivery checkpoint", "Review priority creative handoffs and delivery risk."),
        ("14:40", "15:00", "Agency callback", "Close urgent agency questions before the focus block."),
        ("16:40", "17:20", "Regional decisions debrief", "Close the loop on launch decisions with regional leads."),
    ],
    [
        ("08:00", "08:30", "Overnight media scan", "Review overnight coverage and issues needing an executive response."),
        ("08:30", "09:00", "Morning leadership briefing", "Review overnight changes and today's escalation path."),
        ("09:15", "09:30", "Speaker confirmation", "Confirm the day's speaker and outreach commitments."),
        ("09:50", "10:20", "Brand review follow-up", "Resolve the remaining brand questions from creative review."),
        ("10:30", "10:50", "Launch partner callback", "Close a time-sensitive partner question before enablement review."),
        ("10:50", "11:20", "Partner launch escalation", "Unblock time-sensitive partner launch dependencies."),
        ("11:45", "12:30", "Product leadership pre-brief", "Prepare decisions and open questions for the afternoon reviews."),
        ("12:45", "13:30", "Developer ecosystem check-in", "Review developer commitments and launch examples."),
        ("14:00", "14:45", "Demo owner office hours", "Resolve ownership gaps raised during demo QA."),
        ("15:30", "16:30", "Production budget review", "Review agency tradeoffs and protected crew holds."),
    ],
    [
        ("08:00", "08:30", "Executive inbox triage", "Resolve urgent requests before the midweek campaign pulse."),
        ("08:45", "09:00", "Customer insights readout", "Review the latest customer signal before retail rehearsal."),
        ("09:30", "10:15", "Retail partner escalation", "Close partner questions discovered during rehearsal."),
        ("10:15", "10:30", "Editorial stand-up", "Confirm messaging handoffs for the rest of the day."),
        ("10:45", "11:30", "Content approvals huddle", "Review social assets and approvals needed today."),
        ("13:30", "14:15", "Security stakeholder check-in", "Align reviewers during the protected PRD work block."),
        ("14:30", "15:00", "Security requirements review", "Review the open fallback-policy and audit choices before finalizing the PRD."),
        ("15:20", "16:00", "Claims escalation review", "Resolve qualification questions raised in legal office hours."),
        ("16:00", "16:15", "Approval queue closeout", "Clear pending approvals before creative production review."),
        ("16:30", "17:15", "Production decisions huddle", "Review booking status and production arrangements before end of day."),
    ],
    [
        ("08:15", "08:45", "Leadership agenda check", "Confirm decisions and presenters for upcoming leadership reviews."),
        ("09:45", "10:30", "Product specifications messaging sync", "Align approved specifications with the executive narrative."),
        ("11:00", "12:00", "Executive communications review", "Polish the decision story while the deck is being updated."),
        ("12:00", "12:30", "Executive sponsor check-in", "Review the decisions that need sponsorship before the working lunch."),
        ("12:30", "13:30", "Demo owner working lunch", "Resolve ownership and readiness questions for the demo slate."),
        ("13:30", "13:50", "Demo production callback", "Close urgent production questions from the working lunch."),
        ("13:50", "14:40", "Agency escalation huddle", "Review booking status and any outstanding production arrangements with Priya."),
        ("14:40", "15:00", "Leadership materials check", "Confirm the materials needed for the afternoon pre-read."),
        ("15:30", "16:30", "Pre-read quality check", "Verify decision framing before the leadership handoff."),
    ],
    [
        ("08:00", "08:15", "Week-close inbox scan", "Identify urgent items that need attention before the Friday launch pulse."),
        ("08:15", "08:45", "End-of-week executive triage", "Resolve urgent requests before the Friday launch pulse."),
        ("09:00", "09:30", "Customer readiness check", "Review customer-facing readiness and outstanding commitments."),
        ("09:45", "10:15", "Demo escalation huddle", "Close the highest-risk findings from readiness review."),
        ("10:30", "10:45", "PR and analyst callback", "Resolve a time-sensitive external communications question."),
        ("10:45", "11:30", "Metrics narrative review", "Connect readiness evidence to the leadership story."),
        ("11:45", "12:30", "Finance and planning review", "Review launch spend and next week's planning assumptions."),
        ("12:45", "13:30", "Team commitments check", "Confirm owners and next steps during the team lunch."),
        ("13:30", "14:00", "Talent and staffing check-in", "Review staffing coverage for next week's launch milestones."),
        ("14:20", "14:50", "Planning decisions checkpoint", "Resolve open decisions before next week's plan is finalized."),
        ("15:00", "15:30", "Executive follow-up block", "Close outstanding leadership follow-ups before the global handoff."),
        ("16:10", "17:00", "Global handoff closeout", "Coordinate end-of-week decisions with the APAC handoff."),
    ],
]

TODAY_EVENTS = [
    ("08:00", "08:25", "Today's priorities", "Review overnight changes and today's critical decisions."),
    ("09:00", "09:45", "GTC campaign PMO", "Review critical path, partner commitments, and print readiness."),
    ("10:15", "11:00", "Agent messaging review", "Align campaign wording with the approved performance results."),
    ("11:00", "12:00", "Focus block — Agent Security PRD", "Review, update, and finalize the PRD, resolving the open fallback policies and audit requirements."),
    ("12:30", "13:15", "Partner working lunch", "Review partner proof points and pilot readiness."),
    ("14:00", "14:30", "Legal qualification check", "Confirm leadership-review wording keeps the V1 baseline and metric definitions intact."),
    ("15:00", "16:00", "Launch storyboard working session — notes available", "Optional working session; notes will be posted afterward."),
    ("16:00", "17:00", "Executive prep block", "Prepare the proposed keynote agenda, talking points, and demo slate. Weigh the alternatives and make a recommendation for the leadership decisions."),
    ("17:00", "17:45", "NeoAgent V2 Exec Review — leadership decisions", f"Decision meeting: approve the agent-first keynote storyline and align on GTC demos and owners. {EXEC_REVIEW_ROLES}"),
    ("17:00", "17:30", "Decision follow-up triage", "Capture decisions, unresolved owners, and required follow-ups."),
]


def calendar_event_specs(
    start_day: date,
    deck_url: str,
    doc_url: str,
    sheet_url: str,
    reference_day: date | None = None,
) -> list[tuple[date, str, str, str, str]]:
    current = reference_day or local_now().date()
    active_offset = (current - start_day).days
    if active_offset not in range(5):
        active_offset = 4
    specs = []
    for offset, weekday_events in enumerate(WEEKDAY_EVENTS):
        day = start_day + timedelta(days=offset)
        events = TODAY_EVENTS if offset == active_offset else weekday_events
        for begin, end, title, description in [*events, *WEEKDAY_ADDITIONAL_EVENTS[offset]]:
            link = f"\nDeck: {deck_url}" if title.startswith("NeoAgent V2 Exec Review") else f"\nNotes: {doc_url}" if title.startswith("Launch storyboard") else f"\nTracker: {sheet_url}" if title == "GTC campaign PMO" else ""
            specs.append((day, begin, end, title, f"{description}{link}"))
    return specs


def create_calendar(calendar, start_day: date, deck_url: str, doc_url: str, sheet_url: str) -> list[dict]:
    requests = []
    for day, begin, end, title, description in calendar_event_specs(start_day, deck_url, doc_url, sheet_url):
        requests.append(calendar.events().insert(calendarId="primary", body={"summary": title, "description": f"{description}\n[{MARKER}]", "start": {"dateTime": iso(day, begin), "timeZone": TZ_NAME}, "end": {"dateTime": iso(day, end), "timeZone": TZ_NAME}}, sendUpdates="none"))
    return [
        {"id": result["id"], "url": result.get("htmlLink", "")}
        for result in execute_batched(calendar, requests)
    ]


def seeded_gmail_message_ids(gmail, tracked_ids: set[str] | None = None) -> set[str]:
    """Find seed mail without relying on Gmail's eventually updated search index."""
    tracked_ids = tracked_ids or set()
    message_ids = set()
    page_token = None
    while True:
        kwargs = {
            "userId": "me",
            "includeSpamTrash": True,
            "maxResults": 500,
        }
        if page_token:
            kwargs["pageToken"] = page_token
        page = gmail.users().messages().list(**kwargs).execute()
        page_ids = {item["id"] for item in page.get("messages", []) if item.get("id")}
        message_ids.update(page_ids & tracked_ids)
        unknown_ids = sorted(page_ids - tracked_ids)
        headers = execute_batched(gmail, [
            gmail.users().messages().get(
                userId="me", id=message_id, format="metadata",
                metadataHeaders=["Message-ID"], fields="payload/headers",
            )
            for message_id in unknown_ids
        ])
        for message_id, message in zip(unknown_ids, headers):
            for header in message.get("payload", {}).get("headers", []):
                value = header.get("value", "").strip()
                if (header.get("name", "").lower() == "message-id"
                        and value.startswith(f"<{MARKER}-") and value.endswith("@demo.invalid>")):
                    message_ids.add(message_id)
        page_token = page.get("nextPageToken")
        if not page_token:
            return message_ids


def clear_all_drafts(gmail) -> int:
    draft_ids = []
    page_token = None
    while True:
        kwargs = {"userId": "me", "maxResults": 500}
        if page_token:
            kwargs["pageToken"] = page_token
        page = gmail.users().drafts().list(**kwargs).execute()
        draft_ids.extend(item["id"] for item in page.get("drafts", []) if item.get("id"))
        page_token = page.get("nextPageToken")
        if not page_token:
            break
    requests = [gmail.users().drafts().delete(userId="me", id=draft_id) for draft_id in draft_ids]
    execute_batched(gmail, requests)
    return len(draft_ids)


def remove_dynamic_items(state: dict, svc: dict, *, clear_drafts: bool = False) -> None:
    if clear_drafts:
        clear_all_drafts(svc["gmail"])
    email_ids = {item.get("id") for item in state.get("emails", []) if item.get("id")}
    email_ids.update(seeded_gmail_message_ids(svc["gmail"], email_ids))
    sorted_email_ids = sorted(email_ids)
    for offset in range(0, len(sorted_email_ids), 1000):
        svc["gmail"].users().messages().batchDelete(
            userId="me",
            body={"ids": sorted_email_ids[offset:offset + 1000]},
        ).execute()
    if seeded_gmail_message_ids(svc["gmail"], email_ids):
        raise RuntimeError("Demo emails remain after cleanup. No replacement emails were created; retry the reset.")
    try:
        start = state.get("week_of") + "T00:00:00" + utc_offset()
        end = (date.fromisoformat(state.get("week_of")) + timedelta(days=5)).isoformat() + "T00:00:00" + utc_offset()
        found_events = svc["calendar"].events().list(calendarId="primary", timeMin=start, timeMax=end, singleEvents=True, maxResults=2500).execute().get("items", [])
    except Exception:
        found_events = []
    event_ids = {item.get("id") for item in state.get("events", [])} | {item.get("id") for item in found_events if MARKER in (item.get("description") or "")}
    delete_requests = [
        svc["calendar"].events().delete(calendarId="primary", eventId=event_id, sendUpdates="none")
        for event_id in event_ids
        if event_id
    ]
    execute_batched(svc["calendar"], delete_requests, ignore_errors=True)


def cleanup(state: dict) -> None:
    svc = services(tasks_required=bool(state.get("task_list")))
    clear_seeded_tasks(svc["tasks"], state)
    remove_dynamic_items(state, svc)
    if state.get("folder", {}).get("id"):
        try: svc["drive"].files().update(fileId=state["folder"]["id"], body={"trashed": True}).execute()
        except Exception: pass


def seed(week_of: date) -> dict:
    svc = services()
    if seeded_gmail_message_ids(svc["gmail"]):
        raise RuntimeError("Demo emails already exist. Recover the workspace state and reset, or clean up the existing demo before seeding again.")
    state = {"schema": 1, "marker": MARKER, "week_of": week_of.isoformat(), "events": [], "emails": []}
    try:
        state["folder"] = create_folder(svc["drive"])
        state["doc"] = create_doc(svc["drive"], state["folder"]["id"])
        state["slides"] = create_slides(svc["drive"], state["folder"]["id"])
        reset_deck_baseline(svc["slides"], state["slides"]["id"], drive=svc["drive"])
        state["sheet"] = create_sheet(svc["drive"], state["folder"]["id"])
        task_scenario.ensure_resources(SimpleNamespace(ROOT=ROOT, upload_template=upload_template), svc, state)
        state["emails"], evidence = create_emails(svc["gmail"], state["slides"]["url"], state["sheet"]["url"], state["doc"]["url"], state["task_resources"])
        create_tasks(svc["tasks"], state, evidence)
        reset_sheet_baseline(svc["sheets"], state, evidence, local_now().date().isoformat())
        reset_original_sheet(svc["drive"], svc["sheets"], state, evidence, local_now().date().isoformat())
        state["events"] = create_calendar(svc["calendar"], week_of, state["slides"]["url"], state["doc"]["url"], state["sheet"]["url"])
        state_path().parent.mkdir(parents=True, exist_ok=True)
        state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")
        return state
    except Exception:
        cleanup(state)
        raise


def relink_saved_briefs(previous_emails: list[dict], emails: list[dict], today: date) -> dict:
    """Point today's saved brief (and the cron output it came from) at the re-imported mail.

    Reset deletes and re-imports every seeded message, so Gmail assigns new IDs. The morning
    brief links threads by ID; without this, Start of Day serves a brief full of dead links and
    follow-up tasks hit 404s. Seed order is deterministic, so old and new lists align by index."""
    if len(previous_emails) != len(emails):
        return {"relinked": 0, "reason": "email count changed"}
    mapping = {}
    for old, new in zip(previous_emails, emails):
        # Every ID this seat has ever had (accumulated across resets) now points at the new one,
        # so a brief written several resets ago still relinks. Aliases ride along in the state file.
        aliases = set(old.get("aliases", []))
        for key in ("thread_id", "id"):
            if old.get(key):
                aliases.add(old[key])
        aliases.discard(new.get("thread_id")); aliases.discard(new.get("id"))
        new["aliases"] = sorted(aliases)
        for alias in aliases:
            mapping[alias] = new.get("thread_id") or new["id"]
    if not mapping:
        return {"relinked": 0}
    targets = [ROOT / "CoS_Workspace" / "DailyBriefs" / f"{today.isoformat()}.md"]
    targets.extend((hermes_home() / "cron" / "output").glob(f"*/{today.isoformat()}_*.md"))
    relinked = 0
    for path in targets:
        if not path.is_file():
            continue
        text = original = path.read_text(encoding="utf-8")
        for old_id, new_id in mapping.items():
            text = text.replace(old_id, new_id)
        # Older briefs link /mail/u/0/; point them at the demo mailbox like new links do.
        mailbox = re.search(r"mail\.google\.com/mail/u/([^/]+)/", emails[0].get("url", "")) if emails else None
        if mailbox and mailbox.group(1) != "0":
            text = text.replace("mail.google.com/mail/u/0/", f"mail.google.com/mail/u/{mailbox.group(1)}/")
        if text != original:
            path.write_text(text, encoding="utf-8", newline="\n")
            relinked += 1
    return {"relinked": relinked}


def reset_in_place(state: dict, week_of: date) -> dict:
    svc = services(tasks_required=bool(state.get("task_list")))
    previous_emails = list(state.get("emails", []))
    template_hash = deck_template_hash()
    reset_deck_baseline(svc["slides"], state["slides"]["id"], drive=svc["drive"],
                        restore_template=state["slides"].get("template_sha256") != template_hash)
    state["slides"]["template_sha256"] = template_hash
    clear_seeded_tasks(svc["tasks"], state)
    remove_dynamic_items(state, svc, clear_drafts=True)
    task_scenario.ensure_resources(SimpleNamespace(ROOT=ROOT, upload_template=upload_template, drive_service=drive_service), svc, state, restore=True)
    state["emails"], evidence = create_emails(svc["gmail"], state["slides"]["url"], state["sheet"]["url"], state["doc"]["url"], state["task_resources"])
    create_tasks(svc["tasks"], state, evidence)
    reset_sheet_baseline(svc["sheets"], state, evidence, local_now().date().isoformat())
    reset_original_sheet(svc["drive"], svc["sheets"], state, evidence, local_now().date().isoformat())
    state["events"] = create_calendar(svc["calendar"], week_of, state["slides"]["url"], state["doc"]["url"], state["sheet"]["url"])
    state["week_of"] = week_of.isoformat()
    state["saved_brief"] = relink_saved_briefs(previous_emails, state["emails"], local_now().date())
    state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state


def deck_template_hash() -> str:
    return hashlib.sha256((ROOT / "demo" / "templates" / "neoagent-v2-exec-review.pptx").read_bytes()).hexdigest()


def deck_text_styles(source: Path, slide_number: int) -> list[dict]:
    """Read the template's native title/body style for Google Slides text resets."""
    ns = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main",
          "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
    with ZipFile(source) as archive:
        page = ElementTree.fromstring(archive.read(f"ppt/slides/slide{slide_number}.xml"))
    styles = []
    for shape in page.findall("p:cSld/p:spTree/p:sp", ns):
        if not shape.findall(".//a:t", ns):
            continue
        run = shape.find(".//a:rPr", ns)
        if run is None:
            styles.append({})
            continue
        color = run.find("a:solidFill/a:srgbClr", ns)
        font = run.find("a:latin", ns)
        style = {"bold": run.get("b") == "1"}
        if run.get("sz"):
            style["fontSize"] = {"magnitude": int(run.get("sz")) / 100, "unit": "PT"}
        if font is not None:
            style["fontFamily"] = font.get("typeface")
        if color is not None:
            value = color.get("val")
            style["foregroundColor"] = {"opaqueColor": {"rgbColor": {
                key: int(value[i:i + 2], 16) / 255
                for key, i in (("red", 0), ("green", 2), ("blue", 4))
            }}}
        styles.append(style)
    return (styles + [{}, {}])[:2]


def reset_deck_baseline(slides, presentation_id: str, *, drive=None, restore_template=False) -> None:
    presentation = slides.presentations().get(presentationId=presentation_id).execute()
    source = ROOT / "demo" / "templates" / "neoagent-v2-exec-review.pptx"
    with ZipFile(source) as template:
        root = ElementTree.fromstring(template.read("ppt/presentation.xml"))
    ns = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main"}
    expected_slides = len(root.findall("p:sldIdLst/p:sldId", ns))
    if not expected_slides:
        raise RuntimeError("The seed deck template contains no slides")
    if restore_template or len(presentation.get("slides", [])) != expected_slides:
        if drive is None:
            raise RuntimeError("The demo deck template or structure changed; reset needs Drive access to restore its template")
        from googleapiclient.http import MediaFileUpload

        # Refresh the design or restore deleted slides without changing existing deck links.
        drive.files().update(
            fileId=presentation_id,
            body={"mimeType": "application/vnd.google-apps.presentation"},
            media_body=MediaFileUpload(str(source), mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation", resumable=False),
            fields="id",
        ).execute()
        presentation = slides.presentations().get(presentationId=presentation_id).execute()
        if len(presentation.get("slides", [])) != expected_slides:
            raise RuntimeError("The demo deck template was not fully restored; retry the reset before running the demo")
    # The builder and reset share one baseline, so richer slide content survives resets.
    content = json.loads((ROOT / "demo" / "neoagent_deck.json").read_text(encoding="utf-8"))
    wanted = {number: (item["title"], item["body"]) for number, item in enumerate(content, 1) if number >= 3}
    requests = []
    for slide_number, (title, body) in wanted.items():
        slide = presentation["slides"][slide_number - 1]
        text_boxes = []
        for element in slide.get("pageElements", []):
            text = "".join(item.get("textRun", {}).get("content", "") for item in element.get("shape", {}).get("text", {}).get("textElements", [])).strip()
            if text:
                text_boxes.append(element["objectId"])
        if len(text_boxes) < 2:
            raise RuntimeError(f"Slide {slide_number} does not contain title/body text boxes")
        styles = deck_text_styles(source, slide_number)
        for index, (object_id, value) in enumerate(((text_boxes[0], title), (text_boxes[1], body))):
            requests.append({"deleteText": {"objectId": object_id, "textRange": {"type": "ALL"}}})
            requests.append({"insertText": {"objectId": object_id, "text": value}})
            # deleteText ALL removes character styling in Google Slides.
            if styles[index]:
                requests.append({"updateTextStyle": {
                    "objectId": object_id, "textRange": {"type": "ALL"},
                    "style": styles[index], "fields": ",".join(styles[index]),
                }})
    slides.presentations().batchUpdate(presentationId=presentation_id, body={"requests": requests}).execute()

def main() -> int:
    with workspace_write_lock():
        return run()


def run() -> int:
    parser = argparse.ArgumentParser(description="Seed, reset, or remove the reference Chief of Staff workspace")
    parser.add_argument("--week-of", help="Monday date (YYYY-MM-DD); defaults to the current week")
    parser.add_argument("--refresh-task-scenario", action="store_true", help="Replace only demo tasks and their supporting resources/mail")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument("--confirm", action="store_true", help="Required because this writes to Google Workspace")
    args = parser.parse_args()
    if not args.confirm:
        raise SystemExit("Refusing Google Workspace writes without --confirm")
    path = state_path()
    if sum((args.reset, args.cleanup, args.refresh_task_scenario)) > 1:
        raise SystemExit("Choose only one of reset, cleanup or refresh-task-scenario")
    if args.refresh_task_scenario:
        if not path.exists(): raise SystemExit(f"No workspace state at {path}")
        state = task_scenario.refresh(sys.modules[__name__], json.loads(path.read_text(encoding="utf-8")))
        print(json.dumps({"ok": True, "status": "task-scenario-refreshed", "resources": state["task_resources"], "tasks": len(state["tasks"]), "emails": len(state["emails"])}, indent=2))
        return 0
    if args.cleanup:
        if not path.exists(): raise SystemExit(f"No workspace state at {path}")
        cleanup(json.loads(path.read_text(encoding="utf-8")))
        path.unlink(missing_ok=True)
        print(json.dumps({"ok": True, "status": "removed"}))
        return 0
    chosen_week = date.fromisoformat(args.week_of) if args.week_of else week_monday(local_now().date())
    if args.reset:
        if not path.exists(): raise SystemExit(f"No workspace state at {path}")
        previous = json.loads(path.read_text(encoding="utf-8"))
        check_reset(ROOT, hermes_home())
        check_evidence_cache(ROOT)
        state = reset_in_place(previous, chosen_week)
        second_brain = reset_second_brain(ROOT, hermes_home())
        workspace_cleanup = clear_evidence_cache(ROOT)
        print(json.dumps({"ok": True, "status": "reset", "state": str(path), "week_of": state["week_of"], "folder": state["folder"], "sheet": state["sheet"], "doc": state["doc"], "slides": state["slides"], "emails": len(state["emails"]), "events": len(state["events"]), "tasks": len(state.get("tasks", [])), "second_brain": second_brain, "workspace_cleanup": workspace_cleanup}, indent=2))
        return 0
    elif path.exists():
        raise SystemExit(f"Workspace already exists. Run reset or cleanup first: {path}")
    state = seed(chosen_week)
    print(json.dumps({"ok": True, "state": str(path), "week_of": state["week_of"], "folder": state["folder"], "sheet": state["sheet"], "doc": state["doc"], "slides": state["slides"], "emails": len(state["emails"]), "events": len(state["events"]), "tasks": len(state.get("tasks", []))}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
