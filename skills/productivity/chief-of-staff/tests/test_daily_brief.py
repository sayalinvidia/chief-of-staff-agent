from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import brief
import daily_brief

FIXTURE = ROOT / "tests/fixtures/workspace.json"


class DailyBriefTests(unittest.TestCase):
    def invoke(self, home, *extra):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {"HERMES_HOME": str(home)}), patch.object(
            sys, "argv", ["daily_brief.py", "--fixture", str(FIXTURE), *extra]
        ), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = daily_brief.main()
        return code, stdout.getvalue(), stderr.getvalue()

    def test_fixture_pipeline_runs_each_script_once_and_saves_exact_packet(self):
        with tempfile.TemporaryDirectory() as home, patch.object(
            daily_brief, "run", wraps=daily_brief.run
        ) as run:
            code, output, error = self.invoke(home)
            self.assertEqual(code, 0, error)
            self.assertEqual([call.args[0].name for call in run.call_args_list], ["ingest.py", "brief.py"])
            receipt, encoded = output.splitlines()
            saved = Path(json.loads(receipt)["packet_path"])
            self.assertTrue(saved.is_relative_to(Path(home).resolve()))
            self.assertEqual(saved.read_bytes(), (encoded + "\n").encode("utf-8"))
            self.assertLessEqual(len(encoded), 14000)
            self.assertIn("source_status", json.loads(encoded))

    def test_update_mode_collects_once_and_emits_update_instructions_without_editing_notes(self):
        with tempfile.TemporaryDirectory() as home, patch.object(daily_brief, 'run', wraps=daily_brief.run) as run:
            vault = Path(home) / 'CoS_SecondBrain'
            vault.mkdir()
            note = vault / 'index.md'
            note.write_text('# Existing notes\nNeoAgent V2 review\n', encoding='utf-8')
            before = note.read_bytes()
            (Path(home) / 'second-brain.json').write_text(json.dumps({'vault_path': str(vault)}), encoding='utf-8')
            code, output, error = self.invoke(home, '--mode', 'second-brain-update')
            self.assertEqual(code, 0, error)
            self.assertEqual([call.args[0].name for call in run.call_args_list], ['ingest.py', 'brief.py'])
            receipt, encoded = output.splitlines()
            packet = json.loads(encoded)
            self.assertEqual(packet['mode'], 'second-brain-update')
            self.assertNotIn('three-section', packet['instruction'])
            self.assertNotIn('Make no other tool calls', packet['instruction'])
            self.assertNotIn('Do not edit Google Workspace or Second Brain', packet['instruction'])
            self.assertIn('Updating Second Brain', packet['instruction'])
            self.assertIn('Do not modify Google Workspace', packet['instruction'])
            self.assertLessEqual(len(encoded), daily_brief.MAX_CHARS)
            self.assertEqual(Path(json.loads(receipt)['packet_path']).read_text(encoding='utf-8'), encoded + '\n')
            self.assertEqual(note.read_bytes(), before)
            self.assertEqual(list(vault.iterdir()), [note])

    def test_failed_ingest_does_not_run_brief_retry_or_return_old_packet(self):
        with tempfile.TemporaryDirectory() as home, patch.object(
            daily_brief, "run", side_effect=subprocess.CalledProcessError(1, "ingest.py", stderr="fixture failure")
        ) as run:
            code, output, error = self.invoke(home)
            self.assertEqual(code, 1)
            self.assertEqual(output, "")
            self.assertEqual(json.loads(error)["stage"], "ingest")
            run.assert_called_once()
            self.assertEqual(list(Path(home).rglob("packet.json")), [])

    def test_failed_brief_does_not_retry_or_publish_a_packet(self):
        with tempfile.TemporaryDirectory() as home, patch.object(
            daily_brief, "run", side_effect=["", subprocess.CalledProcessError(1, "brief.py", stderr="fixture failure")]
        ) as run:
            code, output, error = self.invoke(home)
            self.assertEqual(code, 1)
            self.assertEqual(output, "")
            self.assertEqual(json.loads(error)["stage"], "brief")
            self.assertEqual(run.call_count, 2)
            self.assertEqual(list(Path(home).rglob("packet.json")), [])

    def test_final_budget_reduces_background_before_live_work(self):
        packet = {"instruction": "Use this evidence", "mail": [{"id": "manager", "snippet": "Decision due today"}],
                  "tasks": [{"id": "task", "title": "Prepare proposal"}],
                  "focus_blocks": [{"start": "09:30", "end": "10:30"}],
                  "source_status": {"gmail": "ok", "tasks": "ok"}}
        baseline = copy.deepcopy(packet)
        packet["second_brain"] = {"status": "ok", "notes": [
            {"title": f"Background {i}", "excerpt": "Long background context " * 100} for i in range(5)]}
        encoded = brief.fit_packet(packet, 600)
        self.assertLessEqual(len(encoded), 600)
        final = json.loads(encoded)
        for key, value in baseline.items():
            self.assertEqual(final[key], value)
        self.assertTrue(final["second_brain"]["truncated"])

    def test_impossible_budget_fails_instead_of_returning_oversized_json(self):
        with self.assertRaises(ValueError):
            brief.fit_packet({"instruction": "Required instructions" * 100}, 100)


if __name__ == "__main__":
    unittest.main()


class FailedCronReportTests(unittest.TestCase):
    def test_failed_cron_report_is_not_a_saved_brief(self):
        report = '# Cron Job: Morning daily brief (FAILED)' + chr(10)*2 + '## Prompt' + chr(10)*2 + '#### What You Need to Know' + chr(10)*2 + 'RuntimeError: Connection error.' + chr(10)
        self.assertEqual('', daily_brief._response_section(report))

    def test_report_without_response_section_is_ignored(self):
        self.assertEqual('', daily_brief._response_section('# Cron Job: x' + chr(10)*2 + '## Prompt' + chr(10)*2 + '**What You Need to Know**' + chr(10)))

    def test_successful_report_keeps_only_the_response(self):
        report = '# Cron Job: x' + chr(10)*2 + '## Prompt' + chr(10)*2 + 'stuff' + chr(10)*2 + '## Response' + chr(10)*2 + '**What You Need to Know**' + chr(10)*2 + 'body' + chr(10)
        self.assertEqual('**What You Need to Know**' + chr(10)*2 + 'body', daily_brief._response_section(report))
