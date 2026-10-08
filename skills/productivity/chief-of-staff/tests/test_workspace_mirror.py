from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mirror = load("cos_workspace_mirror", ROOT / "scripts" / "workspace_mirror.py")

SNAPSHOT = {
    "generated_at": "2026-10-07T16:00:00Z",
    "identity": {"email": "owner@example.com"},
    "window": {"start": "2026-10-07T00:00:00-07:00", "end": "2026-10-09T00:00:00-07:00"},
    "messages": [
        {"id": "m1", "thread_id": "t1", "from": "Elena Park <elena.example@nvidia.com>", "to": "owner@example.com",
         "subject": "Exec Review moved to 5 PM", "date": "Tue, 07 Oct 2026 09:00:00 -0700", "unread": True, "important": True,
         "snippet": "Please prepare the NeoAgent V2 storyline."},
    ],
    "events": [
        {"id": "e1", "title": "NeoAgent V2 Exec Review", "start": "2026-10-07T17:00:00-07:00", "end": "2026-10-07T18:00:00-07:00",
         "organizer": "elena.example@nvidia.com", "attendees": [{"email": "owner@example.com"}], "html_link": "https://calendar.google.com/x"},
    ],
    "files": [{"id": "f1", "name": "NeoAgent V2 Campaign Plan", "kind": "document", "modified": "2026-10-07T10:00:00Z", "url": "https://docs.google.com/d", "last_editor": "Owner"}],
    "trackers": [{"id": "s1", "name": "NeoAgent V2 Campaign Tracker", "url": "https://docs.google.com/spreadsheets/d/s1",
                  "rows": [{"row": 7, "lane": "Social rollout", "pic": "Rafael Costa", "status": "Awaiting update",
                            "latest": "No status received.", "blocker": "PIC status"}]}],
    "tasks": [{"id": "k1", "title": "Draft the ramp-up email", "status": "needsAction", "due": "2026-10-07", "notes": "For Leah.", "url": "https://tasks.google.com/k1"}],
}


class WorkspaceMirrorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.vault = Path(self.tmp.name)
        (self.vault / "people").mkdir()
        (self.vault / "projects").mkdir()
        (self.vault / "meetings").mkdir()
        (self.vault / "people" / "elena-park.md").write_text("---\ntitle: Elena Park\n---\n# Elena Park\n", encoding="utf-8")
        (self.vault / "people" / "rafael-costa.md").write_text("---\ntitle: Rafael Costa\n---\n", encoding="utf-8")
        (self.vault / "projects" / "neoagent-v2-launch.md").write_text("---\ntitle: NeoAgent V2 Launch\n---\n", encoding="utf-8")
        (self.vault / "meetings" / "neoagent-v2-executive-review.md").write_text("---\ntitle: NeoAgent V2 Exec Review\n---\n", encoding="utf-8")
        (self.vault / "index.md").write_text("# Wiki Index\n\n## Projects\n- [[neoagent-v2-launch|NeoAgent V2 Launch]]\n", encoding="utf-8")

    def test_builds_hub_sources_items_and_cross_links(self):
        counts = mirror.build(SNAPSHOT, self.vault)
        self.assertEqual({"messages": 1, "events": 1, "files": 1, "trackers": 1, "tasks": 1}, {k: counts[k] for k in ("messages", "events", "files", "trackers", "tasks")})
        out = self.vault / "workspace"
        for name in ("Google Workspace", "Gmail", "Calendar", "Drive", "Sheets", "Tasks"):
            self.assertTrue((out / f"{name}.md").is_file(), name)
        hub = (out / "Google Workspace.md").read_text(encoding="utf-8")
        self.assertIn("[[Gmail]]", hub)
        self.assertIn("owner@example.com", hub)

        mail = next((out / "gmail").glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("[[elena-park|Elena Park]]", mail)
        self.assertIn("https://mail.google.com/mail/u/#all/t1", mail)
        self.assertIn("[[Gmail]]", mail)

        event = next((out / "calendar").glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("[[neoagent-v2-executive-review|NeoAgent V2 Exec Review]]", event)

        lane = (out / "sheets" / "neoagent-v2-campaign-tracker--social-rollout.md").read_text(encoding="utf-8")
        self.assertIn("[[rafael-costa|Rafael Costa]]", lane)
        self.assertIn("- **Status:** Awaiting update", lane)
        self.assertIn("- **Blocker:** PIC status", lane)
        sheets = (out / "Sheets.md").read_text(encoding="utf-8")
        self.assertIn("| [[sheets/neoagent-v2-campaign-tracker--social-rollout\\|Social rollout]] | Rafael Costa | Awaiting update |", sheets)

        index = (self.vault / "index.md").read_text(encoding="utf-8")
        self.assertEqual(1, index.count("[[Google Workspace]]"))

    def test_rerun_replaces_the_folder_and_keeps_index_entry_single(self):
        mirror.build(SNAPSHOT, self.vault)
        stale = self.vault / "workspace" / "gmail" / "old-note.md"
        stale.write_text("stale", encoding="utf-8")
        mirror.build(SNAPSHOT, self.vault)
        self.assertFalse(stale.exists())
        self.assertEqual(1, (self.vault / "index.md").read_text(encoding="utf-8").count("[[Google Workspace]]"))

    def test_frontmatter_follows_vault_schema(self):
        mirror.build(SNAPSHOT, self.vault)
        text = (self.vault / "workspace" / "Gmail.md").read_text(encoding="utf-8")
        head = text.split("---")[1]
        for key in ("title:", "created:", "updated:", "type:", "tags:", "sources:", "status:", "confidence:"):
            self.assertIn(key, head)


if __name__ == "__main__":
    unittest.main()
