#!/usr/bin/env python
"""Collect once and deliver a saved, bounded daily-brief packet."""
from __future__ import annotations

import argparse
import re
import json
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

from brief import hermes_home

MAX_CHARS = 14000
# A scheduled Hermes job (see README "Scheduled daily brief") writes the finished brief
# each morning. Interactive Start of Day returns that saved brief when one exists for
# today instead of collecting evidence and generating again.
SAVED_BRIEF_JOB = "Morning daily brief"
SAVED_BRIEF_DIR = "DailyBriefs"
# The model renders this heading inconsistently ("**...**", "## ...", "#### ..."), so match
# the words regardless of Markdown markup.
BRIEF_HEADING = re.compile(r"^[#*\s]*What You Need to Know[*\s]*$", re.IGNORECASE | re.MULTILINE)


def run(script: Path, *args: str) -> str:
    result = subprocess.run(
        [sys.executable, "-X", "utf8", str(script), *args],
        capture_output=True, encoding="utf-8", check=True,
    )
    return result.stdout


def workspace_root() -> Path:
    """The demo workspace holding CoS_SecondBrain; falls back to the profile state folder."""
    connection = hermes_home() / "second-brain.json"
    try:
        vault = Path(json.loads(connection.read_text(encoding="utf-8"))["vault_path"])
        if vault.is_dir():
            return vault.parent
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return hermes_home() / "chief-of-staff"


def _cron_output_for_today(today: date) -> Path | None:
    """Newest brief the scheduled job produced today, from Hermes's cron output folder."""
    cron = hermes_home() / "cron"
    try:
        jobs = json.loads((cron / "jobs.json").read_text(encoding="utf-8")).get("jobs", [])
    except (OSError, ValueError, AttributeError):
        return None
    prefix = today.isoformat()
    candidates: list[Path] = []
    for job in jobs:
        if not isinstance(job, dict) or job.get("name") != SAVED_BRIEF_JOB or not job.get("id"):
            continue
        folder = cron / "output" / str(job["id"])
        if folder.is_dir():
            candidates.extend(p for p in folder.glob(f"{prefix}_*.md") if p.is_file())
    for path in sorted(candidates, key=lambda p: p.name, reverse=True):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        brief = _response_section(text)
        if brief and BRIEF_HEADING.search(brief):
            return brief
    return None


def _response_section(report: str) -> str:
    """Hermes saves each run as a report (header, prompt, then ``## Response``). Keep the response."""
    marker = "\n## Response\n"
    index = report.rfind(marker)
    body = report[index + len(marker):] if index >= 0 else report
    return body.strip()


def _brief_is_current(text: str) -> bool:
    """A brief whose Gmail links point at messages the demo workspace no longer has is stale.

    Reset re-imports the seeded mail under new IDs; serving the old brief would hand the user
    dead links and send follow-up tasks after threads that 404. Without a workspace state file
    (non-demo use) every brief counts as current."""
    try:
        state = json.loads((hermes_home() / "chief-of-staff-workspace-state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    known = {item.get(key) for item in state.get("emails", []) for key in ("id", "thread_id")}
    return all(link in known for link in re.findall(r"mail\.google\.com/mail/(?:u/[^/]+/|\?authuser=[^#]+)#all/([0-9a-f]+)", text))


def saved_brief(today: date | None = None) -> Path | None:
    """Return today's saved brief, publishing it from the scheduled job's output if needed."""
    today = today or datetime.now().date()
    briefs = workspace_root() / SAVED_BRIEF_DIR
    target = briefs / f"{today.isoformat()}.md"
    if target.is_file():
        if _brief_is_current(target.read_text(encoding="utf-8")):
            return target
        target.unlink()  # stale after a workspace reset; fall through to a current source or fresh evidence
    brief = _cron_output_for_today(today)
    if brief is None or not _brief_is_current(brief):
        return None
    briefs.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".tmp")
    partial.write_text(brief + "\n", encoding="utf-8", newline="\n")
    partial.replace(target)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('daily-brief', 'second-brain-update'), default='daily-brief')
    parser.add_argument("--fixture", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--fresh", action="store_true",
                        help="Ignore today's saved brief and collect evidence now (used by the scheduled job)")
    args = parser.parse_args()
    scripts = Path(__file__).resolve().parent
    # Perplexity bundles ingest here. Hermes keeps it in the sibling skill.
    ingest = scripts / "ingest.py"
    if not ingest.is_file():
        ingest = scripts.parents[1] / "ingest/scripts/ingest.py"
    stage = "prepare"
    try:
        if args.mode == "daily-brief" and not args.fresh and not args.fixture:
            saved = saved_brief()
            if saved is not None:
                print(json.dumps({"saved_brief": str(saved)}, ensure_ascii=False))
                print(saved.read_text(encoding="utf-8").strip())
                return 0
        state = hermes_home() / "chief-of-staff"
        state.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            # Inherit the workspace's access rules on Windows.
            folder = (state / f"daily-brief-{uuid4().hex}").resolve()
            folder.mkdir()
        else:
            folder = Path(tempfile.mkdtemp(prefix="daily-brief-", dir=state)).resolve()
        snapshot = folder / "snapshot.json"
        packet_path = folder / "packet.json"
        stage = "ingest"
        fixture = ["--fixture", str(args.fixture)] if args.fixture else []
        run(ingest, "--output", str(snapshot), "--stdout", "none", *fixture)
        stage = "brief"
        encoded = run(
            scripts / "brief.py", "--snapshot", str(snapshot),
            "--mode", args.mode,
            "--max-meetings", "10", "--max-mail", "8", "--max-files", "8",
            "--max-chars", str(MAX_CHARS), "--work-end", "17",
        ).strip()
        json.loads(encoded)  # Never publish an incomplete or malformed packet.
        if len(encoded) > MAX_CHARS:
            raise ValueError("Brief packet exceeds its output budget")
        stage = "save"
        packet_path.write_text(encoded + "\n", encoding="utf-8", newline="\n")
        # Emit the fallback path first so it survives tail truncation by a tool.
        print(json.dumps({"packet_path": str(packet_path)}, ensure_ascii=False))
        print(encoded)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        detail = exc.stderr if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        print(json.dumps({"ok": False, "stage": stage, "error": (detail or str(exc))[:2000]}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
