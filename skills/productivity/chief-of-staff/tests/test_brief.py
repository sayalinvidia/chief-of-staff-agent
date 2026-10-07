from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "workspace.json"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


brief = load("cos_brief", ROOT / "scripts" / "brief.py")


class BriefTests(unittest.TestCase):
    def args(self):
        return argparse.Namespace(
            max_files=12,
            max_meetings=15,
            max_mail=12,
            work_start=8,
            work_end=18,
            min_focus_minutes=30,
        )

    def test_conflict_and_priority_evidence(self):
        snapshot = json.loads(FIXTURE.read_text(encoding="utf-8"))
        packet = brief.build_packet(snapshot, self.args())
        self.assertEqual(len(packet["conflicts"]), 1)
        self.assertEqual(len(packet["conflicts"][0]["events"]), 3)
        self.assertEqual(packet["mail"][0]["id"], "msg-urgent")
        self.assertEqual(packet["mail"][0]["url"], "https://mail.google.com/mail/u/owner@example.com/#all/thread-urgent")
        self.assertEqual(packet["source_status"], {"calendar": "ok", "gmail": "ok", "drive": "ok"})
        self.assertNotIn("trackers", packet)
        self.assertIn("three-section", packet["instruction"])
        exec_event = next(event for event in packet["meetings"] if event["id"] == "evt-exec")
        self.assertTrue(any(item["id"] == "deck-1" for item in exec_event["related"]["files"]))

    def test_scores_stay_internal_after_selection_even_with_spare_space(self):
        snapshot = json.loads(FIXTURE.read_text(encoding="utf-8"))
        args = self.args()
        args.max_mail = 1
        args.max_meetings = 1
        packet = brief.build_packet(snapshot, args)
        self.assertEqual([item["id"] for item in packet["mail"]], ["msg-urgent"])
        self.assertEqual([item["id"] for item in packet["meetings"]], ["evt-exec"])
        for result in (packet, json.loads(brief.fit_packet(packet, 100000))):
            for item in result["mail"] + result["meetings"]:
                self.assertNotIn("signal_score", item)
                self.assertNotIn("signals", item)
        self.assertTrue(packet["mail"][0]["snippet"])
        self.assertEqual(packet["mail"][0]["url"], "https://mail.google.com/mail/u/owner@example.com/#all/thread-urgent")

    def test_packet_respects_context_budget(self):
        snapshot = json.loads(FIXTURE.read_text(encoding="utf-8"))
        encoded = brief.fit_packet(brief.build_packet(snapshot, self.args()), 5000)
        self.assertLessEqual(len(encoded), 5000)
        self.assertIn("conflicts", json.loads(encoded))

    def test_focus_time_excludes_elapsed_time_and_merges_overlaps(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("UTC")
        events = [
            {"start": "2030-07-10T10:00:00Z", "end": "2030-07-10T11:00:00Z"},
            {"start": "2030-07-10T10:30:00Z", "end": "2030-07-10T12:00:00Z"},
        ]
        blocks = brief.focus_blocks(events, tz, "2030-07-10T00:00:00Z", 8, 17, 30, datetime(2030, 7, 10, 9, 30, tzinfo=tz))
        self.assertEqual([(b["start"][11:16], b["end"][11:16]) for b in blocks], [("09:30", "10:00"), ("12:00", "17:00")])
        self.assertEqual(brief.focus_blocks(events, tz, "2030-07-10T00:00:00Z", 8, 17, 30, datetime(2030, 7, 10, 18, tzinfo=tz)), [])

    def test_demo_time_uses_local_date_and_preserves_collection_time(self):
        for generated_at, expected in [
            ("2030-07-10T01:15:00Z", "2030-07-09T09:30:00-07:00"),
            ("2030-01-10T01:15:00Z", "2030-01-09T09:30:00-08:00"),
        ]:
            with self.subTest(generated_at=generated_at):
                snapshot = json.loads(FIXTURE.read_text(encoding="utf-8"))
                snapshot["timezone"] = "America/Los_Angeles"
                snapshot["generated_at"] = generated_at
                packet = brief.build_packet(snapshot, self.args())
                self.assertEqual(packet["freshness"]["local_time"], expected)
                self.assertEqual(packet["freshness"]["generated_at"], generated_at)

    def test_meeting_time_status_uses_demo_time_and_actual_intervals(self):
        snapshot = json.loads(FIXTURE.read_text(encoding="utf-8"))
        snapshot["timezone"] = "UTC"
        snapshot["generated_at"] = "2030-07-10T20:00:00Z"
        snapshot["events"] = [
            {"id": "past", "start": "2030-07-10T08:00:00Z", "end": "2030-07-10T09:30:00Z"},
            {"id": "now", "start": "2030-07-10T09:30:00Z", "end": "2030-07-10T10:00:00Z"},
            {"id": "future", "start": "2030-07-10T10:00:00Z", "end": "2030-07-10T11:00:00Z"},
        ]
        packet = brief.build_packet(snapshot, self.args())
        self.assertEqual({e["id"]: e["time_status"] for e in packet["meetings"]}, {"past": "ended", "now": "in_progress", "future": "upcoming"})
        self.assertEqual(
            {e["id"]: (e["start"], e["end"]) for e in packet["meetings"]},
            {e["id"]: (e["start"], e["end"]) for e in snapshot["events"]},
        )

    def test_focus_blocks_use_demo_time_for_early_and_late_snapshots(self):
        for generated_at in ["2030-07-09T14:00:00Z", "2030-07-10T01:15:00Z"]:
            for with_window in [True, False]:
                with self.subTest(generated_at=generated_at, with_window=with_window):
                    snapshot = json.loads(FIXTURE.read_text(encoding="utf-8"))
                    snapshot["timezone"] = "America/Los_Angeles"
                    snapshot["generated_at"] = generated_at
                    if with_window:
                        snapshot["window"] = {"start": "2030-07-09T00:00:00-07:00"}
                    else:
                        snapshot.pop("window", None)
                    snapshot["events"] = [
                        {"id": "first", "start": "2030-07-09T10:00:00-07:00", "end": "2030-07-09T11:00:00-07:00"},
                        {"id": "overlap", "start": "2030-07-09T10:30:00-07:00", "end": "2030-07-09T12:00:00-07:00"},
                    ]
                    args = self.args()
                    args.work_end = 17
                    packet = brief.build_packet(snapshot, args)
                    self.assertEqual(packet["focus_blocks"], [
                        {"start": "2030-07-09T09:30:00-07:00", "end": "2030-07-09T10:00:00-07:00", "minutes": 30},
                        {"start": "2030-07-09T12:00:00-07:00", "end": "2030-07-09T17:00:00-07:00", "minutes": 300},
                    ])

    def test_budget_drops_repeated_meeting_matches_before_primary_mail(self):
        snapshot = json.loads(FIXTURE.read_text(encoding="utf-8"))
        packet = brief.build_packet(snapshot, self.args())
        expected_mail = packet["mail"].copy()
        for meeting in packet["meetings"]:
            meeting["related"] = {"mail": expected_mail * 20}
        fitted = json.loads(brief.fit_packet(packet, 14000))
        self.assertEqual(fitted["mail"], expected_mail)
        self.assertTrue(all("related" not in item for item in fitted["meetings"]))

    def test_empty_success_is_not_reported_as_unavailable(self):
        snapshot = json.loads(FIXTURE.read_text(encoding="utf-8"))
        snapshot["events"] = []
        snapshot["files"] = []
        snapshot["coverage"].update({"events": 0, "files": 0, "errors": []})
        packet = brief.build_packet(snapshot, self.args())
        self.assertEqual(packet["source_status"]["calendar"], "ok_empty")
        self.assertEqual(packet["source_status"]["drive"], "ok_empty")

    def test_busy_calendar_does_not_crowd_out_work_evidence(self):
        snapshot = json.loads(FIXTURE.read_text(encoding="utf-8"))
        packet = brief.build_packet(snapshot, self.args())
        expected_mail = packet["mail"][:]
        packet["conflicts"] *= 30

        encoded = brief.fit_packet(packet, 14000)
        fitted = json.loads(encoded)

        self.assertLessEqual(len(encoded), 14000)
        self.assertGreater(fitted["omitted_conflict_groups"], 0)
        self.assertEqual(expected_mail, fitted["mail"])


if __name__ == "__main__":
    unittest.main()
