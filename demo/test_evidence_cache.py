"""Workspace cleanup tests use disposable folders, never live demo data."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from evidence_cache import PRESERVED_STATE_FILES, check_evidence_cache, clear_evidence_cache


class EvidenceCacheTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.workspace = self.root / "CoS_Workspace"
        self.state = self.workspace / ".chief-of-staff-state"
        self.state.mkdir(parents=True)

    def write(self, path, text="saved evidence"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_returns_workspace_to_baseline_and_preserves_only_required_state(self):
        runs = [self.state / "chief-of-staff" / ("daily-brief-" + "a" * 32),
                self.state / "daily-brief-f0zd281p"]
        for run in runs:
            self.write(run / "packet.json")
            self.write(run / "snapshot.json")
        incomplete = self.state / "chief-of-staff" / ("daily-brief-" + "b" * 32)
        incomplete.mkdir()
        standalone = [self.state / "snapshot.json",
                      self.state / "chief-of-staff/snapshot.json",
                      self.state / "chief-of-staff/packet.json"]
        for path in standalone:
            self.write(path)
        artifacts = [self.workspace / name for name in (
            "tracker_updates.json", "deck_output.json", "extract_trackers.py",
            "temp_read_thread.ps1", "draft-email.txt", "daily-brief.md", "snapshot.json",
            "google_token.json", ".hidden-output", "arbitrary-folder/nested/report.txt",
            "current_session_context/tool_calls/read/output.txt")]
        artifacts += [self.state / "other.json", self.state / "draft_body.txt",
                      self.state / "chief-of-staff/daily-brief-notes/notes.md"]
        for path in artifacts:
            self.write(path)
        preserved = [self.state / name for name in PRESERVED_STATE_FILES]
        preserved += [self.workspace / "CoS_SecondBrain/index.md",
                      self.root / "demo/seed_workspace.py",
                      self.root / "checkpoints/checkpoint-4/packet.json"]
        before = {path: self.write(path, "keep this").read_bytes() for path in preserved}

        result = clear_evidence_cache(self.root)

        self.assertEqual(result["files_removed"], 7 + len(artifacts))
        self.assertTrue(all(not path.exists() for path in [*runs, incomplete, *standalone]))
        self.assertTrue(all(not path.exists() for path in artifacts))
        self.assertEqual({"CoS_SecondBrain", ".chief-of-staff-state"}, {p.name for p in self.workspace.iterdir()})
        self.assertEqual(PRESERVED_STATE_FILES, {p.name for p in self.state.iterdir()})
        self.assertEqual(before, {path: path.read_bytes() for path in preserved})
        self.assertEqual(clear_evidence_cache(self.root),
                         {"folders_removed": 0, "files_removed": 0})

    def test_preflight_does_not_delete_or_create_files(self):
        packet = self.write(self.state / "chief-of-staff" / ("daily-brief-" + "c" * 32) / "packet.json")
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        check_evidence_cache(self.root)
        self.assertEqual(before, {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()})
        self.assertTrue(packet.exists())
        absent = self.root / "unused-checkout"
        self.assertEqual(clear_evidence_cache(absent),
                         {"folders_removed": 0, "files_removed": 0})
        self.assertFalse(absent.exists())

    def test_preserves_newest_dated_brief_unchanged_not_most_recently_modified(self):
        briefs = self.workspace / "DailyBriefs"
        older = self.write(briefs / "2026-10-05.md", "older brief")
        newest = self.write(briefs / "2026-10-06.md", "# What You Need to Know\n\nToday's brief\n")
        os.utime(newest, (100, 100))
        os.utime(older, (200, 200))
        before = newest.read_bytes(), newest.stat().st_mtime_ns
        artifacts = [older, self.write(briefs / "draft.md"),
                     self.write(briefs / "2026-99-99.md"),
                     self.write(briefs / "scratch/2026-10-07.md"),
                     self.write(self.workspace / "tracker_updates.json"),
                     self.write(self.state / "snapshot.json")]
        files_before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        check_evidence_cache(self.root)
        self.assertEqual(files_before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

        result = clear_evidence_cache(self.root)

        self.assertEqual(result["files_removed"], len(artifacts))
        self.assertTrue(all(not path.exists() for path in artifacts))
        self.assertEqual(list(briefs.iterdir()), [newest])
        self.assertEqual((newest.read_bytes(), newest.stat().st_mtime_ns), before)
        self.assertEqual(clear_evidence_cache(self.root), {"folders_removed": 0, "files_removed": 0})

    def test_preserves_latest_brief_even_when_it_is_not_from_today(self):
        brief = self.write(self.workspace / "DailyBriefs/2020-01-01.md", "last saved brief")
        clear_evidence_cache(self.root)
        self.assertEqual(brief.read_text(encoding="utf-8"), "last saved brief")

    def test_cleans_daily_briefs_folder_without_a_valid_dated_markdown_file(self):
        briefs = self.workspace / "DailyBriefs"
        for name in ("draft.md", "2026-02-30.md", "2026-10-06.json"):
            self.write(briefs / name)
        self.assertEqual(clear_evidence_cache(self.root), {"folders_removed": 1, "files_removed": 3})
        self.assertFalse(briefs.exists())

    def test_wrong_type_for_preserved_state_aborts_before_any_deletion(self):
        artifact = self.write(self.workspace / "tracker_updates.json")
        (self.state / "google_token.json").mkdir()
        with self.assertRaisesRegex(RuntimeError, "Expected a required state file"):
            clear_evidence_cache(self.root)
        self.assertTrue(artifact.exists())

    def test_workspace_without_runtime_state_keeps_only_the_vault(self):
        self.state.rmdir()
        note = self.write(self.workspace / "CoS_SecondBrain/index.md", "baseline")
        self.write(self.workspace / "random-output/file.json")
        clear_evidence_cache(self.root)
        self.assertEqual(["CoS_SecondBrain"], [p.name for p in self.workspace.iterdir()])
        self.assertEqual(note.read_text(), "baseline")

    def link_directory(self, link, target):
        link.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            shell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
            quote = lambda path: "'" + str(path).replace("'", "''") + "'"
            result = subprocess.run(
                [str(shell), "-NoProfile", "-NonInteractive", "-Command",
                 f"$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path {quote(link)} -Target {quote(target)} | Out-Null"],
                capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            link.symlink_to(target, target_is_directory=True)

    def test_refuses_linked_cache_root(self):
        outside = self.root / "another-workspace"
        evidence = self.write(outside / "snapshot.json", "do not delete")
        self.link_directory(self.state / "chief-of-staff", outside)
        with self.assertRaisesRegex(RuntimeError, "linked path"):
            clear_evidence_cache(self.root)
        self.assertEqual(evidence.read_text(), "do not delete")

    def test_refuses_linked_daily_briefs_folder_before_deleting_anything(self):
        artifact = self.write(self.workspace / "tracker_updates.json")
        outside = self.root / "another-workspace"
        brief = self.write(outside / "2026-10-06.md", "do not delete")
        self.link_directory(self.workspace / "DailyBriefs", outside)
        with self.assertRaisesRegex(RuntimeError, "linked path"):
            clear_evidence_cache(self.root)
        self.assertTrue(artifact.exists())
        self.assertEqual(brief.read_text(), "do not delete")

    def test_nested_link_aborts_before_deleting_any_cache(self):
        first = self.write(self.state / "chief-of-staff" / ("daily-brief-" + "1" * 32) / "packet.json")
        outside = self.root / "another-workspace"
        evidence = self.write(outside / "snapshot.json", "do not delete")
        self.link_directory(self.state / "chief-of-staff" / ("daily-brief-" + "2" * 32) / "linked", outside)
        with self.assertRaisesRegex(RuntimeError, "linked path"):
            clear_evidence_cache(self.root)
        self.assertTrue(first.exists())
        self.assertEqual(evidence.read_text(), "do not delete")

    def test_nested_workspace_link_aborts_before_deleting_any_artifact(self):
        first = self.write(self.workspace / "first.json")
        outside = self.root / "personal"
        note = self.write(outside / "keep.md", "personal note")
        self.link_directory(self.workspace / "agent-output/linked", outside)
        with self.assertRaisesRegex(RuntimeError, "linked path"):
            clear_evidence_cache(self.root)
        self.assertTrue(first.exists())
        self.assertEqual(note.read_text(), "personal note")


if __name__ == "__main__":
    unittest.main()
