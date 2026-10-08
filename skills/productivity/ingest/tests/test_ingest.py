from __future__ import annotations

import argparse
import base64
import email
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).resolve().parents[2] / "chief-of-staff" / "tests" / "fixtures" / "workspace.json"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ingest = load("cos_ingest", ROOT / "scripts" / "ingest.py")
actions = load("cos_actions", ROOT / "scripts" / "actions.py")


class GmailDraftListTests(unittest.TestCase):
    def setUp(self):
        self.api = unittest.mock.Mock()
        self.drafts = self.api.users.return_value.drafts.return_value
        self.args = actions.build_parser().parse_args(["gmail", "drafts"])

    def read(self):
        with patch.object(actions, "service", return_value=self.api), patch.object(actions, "emit") as emit:
            self.args.func(self.args)
        return emit.call_args.args[0]

    @staticmethod
    def draft(ident, recipient, body, mime="text/plain"):
        return {"id": ident, "message": {"id": "message-" + ident, "threadId": "thread-" + ident,
            "payload": {"mimeType": mime, "headers": [
                {"name": "To", "value": recipient}, {"name": "Cc", "value": "ops@example.test"},
                {"name": "Bcc", "value": "archive@example.test"}, {"name": "Subject", "value": "Project question"}],
                "body": {"data": base64.urlsafe_b64encode(body.encode()).decode()}}}}

    def test_all_pages_recipients_and_full_bodies_are_returned_read_only(self):
        long_body = "Details\n" * 3000 + "Different request at the end."
        self.drafts.list.return_value.execute.side_effect = [
            {"drafts": [{"id": "one"}], "nextPageToken": "page-two"},
            {"drafts": [{"id": "two"}]}]
        self.drafts.get.return_value.execute.side_effect = [
            self.draft("one", "Lina <lina@example.test>", long_body),
            self.draft("two", "Musa <musa@example.test>", "Please confirm delivery.\n\nThanks")]
        result = self.read()
        self.assertTrue(result["complete"])
        self.assertEqual(2, result["count"])
        self.assertEqual(long_body, result["drafts"][0]["body"])
        self.assertEqual("Musa <musa@example.test>", result["drafts"][1]["to"])
        first = result["drafts"][0]
        self.assertEqual(("one", "message-one", "thread-one"),
                         (first["draft_id"], first["message_id"], first["thread_id"]))
        self.assertEqual("ops@example.test", first["cc"])
        self.assertEqual("archive@example.test", first["bcc"])
        self.drafts.list.assert_has_calls([
            unittest.mock.call(userId="me", maxResults=500),
            unittest.mock.call(userId="me", maxResults=500, pageToken="page-two")], any_order=True)
        self.assertEqual(2, self.drafts.get.call_count)
        self.assertEqual({"list", "list().execute", "get", "get().execute"},
                         {call[0] for call in self.drafts.mock_calls})

    def test_empty_mailbox_is_complete_not_an_error(self):
        self.drafts.list.return_value.execute.return_value = {}
        self.assertEqual({"complete": True, "count": 0, "drafts": []}, self.read())
        self.drafts.get.assert_not_called()

    def test_html_and_empty_drafts_are_not_omitted(self):
        self.drafts.list.return_value.execute.return_value = {"drafts": [{"id": "one"}, {"id": "two"}]}
        self.drafts.get.return_value.execute.side_effect = [
            self.draft("one", "a@example.test", "<p>Research &amp; review</p>", "text/html"),
            self.draft("two", "b@example.test", "")]
        result = self.read()
        self.assertEqual("Research & review", result["drafts"][0]["body"])
        self.assertEqual("", result["drafts"][1]["body"])
        self.assertEqual(2, result["count"])

    def test_failure_does_not_emit_a_partial_or_empty_success(self):
        for stage in ("list", "get"):
            with self.subTest(stage=stage):
                self.drafts.list.return_value.execute.side_effect = [
                    {"drafts": [{"id": "one"}], "nextPageToken": "next"}, RuntimeError("read failed")]
                self.drafts.get.return_value.execute.side_effect = (
                    RuntimeError("read failed") if stage == "get" else None)
                self.drafts.get.return_value.execute.return_value = self.draft("one", "a@example.test", "Draft")
                with patch.object(actions, "service", return_value=self.api), patch.object(actions, "emit") as emit:
                    with self.assertRaisesRegex(RuntimeError, "read failed"):
                        self.args.func(self.args)
                emit.assert_not_called()
                self.drafts.create.assert_not_called()


class GmailUrlTests(unittest.TestCase):
    def check_message_read(self, operation, thread_id, include_thread_id=True):
        api = unittest.mock.Mock()
        messages = api.users.return_value.messages.return_value
        message = {
            "id": "actual-message",
            "payload": {
                "mimeType": "text/plain",
                "body": {"data": base64.urlsafe_b64encode(b"Full evidence").decode("ascii")},
                "headers": [{"name": "Subject", "value": "Project update"}],
            },
        }
        if include_thread_id:
            message["threadId"] = thread_id
        messages.get.return_value.execute.return_value = message
        messages.list.return_value.execute.return_value = {
            "messages": [{"id": "requested-message", "threadId": "reference-thread"}],
        }
        args = argparse.Namespace(message_id="requested-message", query="project", max=50,
                                  newer_than_days=90, max_chars=4)
        with patch.object(actions, "service", return_value=api) as service, patch.object(actions, "emit") as emit:
            getattr(actions, "gmail_" + operation)(args)
        service.assert_called_once_with("gmail", "v1")
        emit.assert_called_once()
        result = emit.call_args.args[0]
        result = result if operation == "get" else result["matches" if operation == "search" else "messages"][0]
        self.assertEqual("actual-message", result["id"])
        self.assertEqual(thread_id, result["thread_id"])
        self.assertEqual("Project update", result["subject"])
        self.assertEqual(f"https://mail.google.com/mail/u/#all/{thread_id}" if thread_id else None, result["url"])
        get_args = {"userId": "me", "id": "requested-message", "format": "full"}
        if operation == "search":
            get_args.update(format="metadata", metadataHeaders=["From", "To", "Cc", "Reply-To", "Subject", "Date"])
            self.assertNotIn("body", result)
        else:
            self.assertEqual("Full", result["body"])
        calls = []
        if operation != "get":
            query = "project" if operation == "search" else "is:important newer_than:30d"
            limit = 10 if operation == "search" else 20
            calls.extend([unittest.mock.call.list(userId="me", q=query, maxResults=limit),
                          unittest.mock.call.list().execute()])
        calls.extend([unittest.mock.call.get(**get_args), unittest.mock.call.get().execute()])
        self.assertEqual(calls, messages.mock_calls)
        self.assertEqual([], api.users.return_value.threads.mock_calls)
        self.assertEqual([], api.users.return_value.drafts.mock_calls)

    def test_get_url_uses_actual_response_thread_without_extra_requests(self):
        self.check_message_read("get", "actual-thread")

    def test_search_urls_use_actual_response_threads_without_extra_requests(self):
        self.check_message_read("search", "actual-thread")

    def test_important_urls_use_actual_response_threads_without_extra_requests(self):
        self.check_message_read("important", "actual-thread")

    def test_message_read_urls_are_null_when_thread_id_is_missing_or_empty(self):
        for operation in ("get", "search", "important"):
            for thread_id, include_thread_id in ((None, False), (None, True), ("", True)):
                with self.subTest(operation=operation, thread_id=thread_id, present=include_thread_id):
                    self.check_message_read(operation, thread_id, include_thread_id)

    def test_thread_url_prefers_response_id_then_resolved_request_id(self):
        for response_fields, requested_id, expected_id in (
            ({"id": "actual-thread"}, "requested-thread", "actual-thread"),
            ({}, "requested-thread", "requested-thread"),
            ({"id": None}, "requested-thread", "requested-thread"),
            ({"id": ""}, "requested-thread", "requested-thread"),
            ({}, None, None),
        ):
            with self.subTest(response_fields=response_fields, requested_id=requested_id):
                api = unittest.mock.Mock()
                threads = api.users.return_value.threads.return_value
                thread = {"messages": [{"id": "message-1"}, {"id": "message-2"}]}
                thread.update(response_fields)
                threads.get.return_value.execute.return_value = thread
                args = argparse.Namespace(thread_id=requested_id, max_messages=1, max_chars=4)
                with patch.object(actions, "service", return_value=api) as service, patch.object(actions, "emit") as emit:
                    actions.gmail_thread(args)
                service.assert_called_once_with("gmail", "v1")
                emit.assert_called_once()
                result = emit.call_args.args[0]
                self.assertEqual(requested_id, result["thread_id"])
                self.assertEqual(f"https://mail.google.com/mail/u/#all/{expected_id}" if expected_id else None, result["url"])
                self.assertEqual(["message-2"], [message["id"] for message in result["messages"]])
                self.assertEqual([unittest.mock.call.get(userId="me", id=requested_id, format="full"),
                                  unittest.mock.call.get().execute()], threads.mock_calls)
                self.assertEqual([], api.users.return_value.messages.mock_calls)
                self.assertEqual([], api.users.return_value.drafts.mock_calls)


class IngestTests(unittest.TestCase):
    def test_fixture_round_trip_is_bounded(self):
        args = argparse.Namespace(fixture=FIXTURE)
        snapshot = ingest.collect(args)
        self.assertEqual(snapshot["source"], "fixture")
        self.assertEqual(snapshot["coverage"]["events"], 4)
        self.assertLessEqual(len(snapshot["messages"]), 50)

    def test_cloud_mutation_requires_confirmation(self):
        with self.assertRaisesRegex(RuntimeError, "without --confirm"):
            actions.require_confirm(argparse.Namespace(confirm=False), "test mutation")
        actions.require_confirm(argparse.Namespace(confirm=True), "test mutation")

    def test_tracker_updates_can_be_read_from_standard_input(self):
        payload = '[{"lane":"Exec Review deck","status":"In progress","latest":"Aisha\'s review is complete."}]'
        args = argparse.Namespace(updates=None, updates_file="-")

        with patch.object(actions.sys, "stdin", io.StringIO(payload)):
            updates = actions._load_tracker_updates(args)

        self.assertEqual("Aisha's review is complete.", updates[0]["latest"])

    def test_inline_tracker_updates_remain_supported(self):
        payload = '[{"lane":"Exec Review deck","status":"In progress"}]'
        args = argparse.Namespace(updates=payload, updates_file=None)

        self.assertEqual("Exec Review deck", actions._load_tracker_updates(args)[0]["lane"])

    def test_one_time_codes_are_redacted_before_model_context(self):
        text = "Your verification code is 865913. It expires soon."
        redacted = ingest.redact_sensitive(text)
        self.assertNotIn("865913", redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_tracker_inputs_accept_optional_bom_without_changing_content(self):
        expected = [{"lane": "Packing", "status": "In progress", "latest": "Keep \ufeff inside text"}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "updates.json"
            for prefix in ("", "\ufeff"):
                payload = prefix + json.dumps(expected, ensure_ascii=False)
                path.write_bytes(payload.encode("utf-8"))
                for source in ("inline", "stdin", "file"):
                    with self.subTest(bom=bool(prefix), source=source):
                        args = argparse.Namespace(
                            updates=payload if source == "inline" else None,
                            updates_file="-" if source == "stdin" else str(path),
                        )
                        with patch.object(actions.sys, "stdin", io.StringIO(payload)):
                            self.assertEqual(expected, actions._load_tracker_updates(args))

    def test_malformed_tracker_json_is_rejected_before_network_with_or_without_bom(self):
        for prefix in ("", "\ufeff"):
            with self.subTest(bom=bool(prefix)):
                args = actions.build_parser().parse_args([
                    "sheets", "update-lanes", "sheet-id", "--confirm",
                    "--updates", prefix + '[{"lane":]',
                ])
                with patch.object(actions, "service") as service:
                    with self.assertRaises(json.JSONDecodeError):
                        actions.sheets_update_lanes(args)
                    service.assert_not_called()

    def test_gmail_search_is_metadata_only_and_bounded(self):
        calls = {}

        class Request:
            def __init__(self, value):
                self.value = value

            def execute(self):
                return self.value

        class Messages:
            def list(self, **kwargs):
                calls["list"] = kwargs
                return Request({"messages": [{"id": "message-1"}]})

            def get(self, **kwargs):
                calls["get"] = kwargs
                return Request({
                    "id": "message-1",
                    "threadId": "thread-1",
                    "labelIds": ["DRAFT"],
                    "payload": {"headers": [
                        {"name": "From", "value": "Person <person@example.com>"},
                        {"name": "Subject", "value": "Project update"},
                    ]},
                })

        class Users:
            def messages(self):
                return Messages()

        class Api:
            def users(self):
                return Users()

        original_service = actions.service
        actions.service = lambda *_args: Api()
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                actions.gmail_search(argparse.Namespace(query="Person project", max=50))
        finally:
            actions.service = original_service

        result = json.loads(output.getvalue())
        self.assertEqual(10, calls["list"]["maxResults"])
        self.assertEqual("metadata", calls["get"]["format"])
        self.assertEqual("Person <person@example.com>", result["matches"][0]["from"])
        self.assertEqual(["DRAFT"], result["matches"][0]["labels"])
        self.assertNotIn("body", result["matches"][0])

    def test_recent_important_mail_returns_bounded_full_evidence(self):
        calls = {}

        class Request:
            def __init__(self, value):
                self.value = value

            def execute(self):
                return self.value

        encoded = base64.urlsafe_b64encode(b"Complete evidence body").decode("ascii")

        class Messages:
            def list(self, **kwargs):
                calls["list"] = kwargs
                return Request({"messages": [{"id": "message-1"}]})

            def get(self, **kwargs):
                calls["get"] = kwargs
                return Request({
                    "id": "message-1",
                    "threadId": "thread-1",
                    "payload": {
                        "mimeType": "text/plain",
                        "body": {"data": encoded},
                        "headers": [
                            {"name": "From", "value": "Person <person@example.com>"},
                            {"name": "Subject", "value": "Approved update"},
                        ],
                    },
                })

        class Users:
            def messages(self):
                return Messages()

        class Api:
            def users(self):
                return Users()

        with patch.object(actions, "service", return_value=Api()):
            output = io.StringIO()
            with redirect_stdout(output):
                actions.gmail_important(argparse.Namespace(max=50, newer_than_days=2, max_chars=8000))

        result = json.loads(output.getvalue())
        self.assertEqual("is:important newer_than:2d", calls["list"]["q"])
        self.assertEqual(20, calls["list"]["maxResults"])
        self.assertEqual("full", calls["get"]["format"])
        self.assertEqual("Complete evidence body", result["messages"][0]["body"])

    def test_reply_draft_is_threaded(self):
        captured = {}
        requests = []

        class Request:
            def __init__(self, value):
                self.value = value

            def execute(self):
                return self.value

        class Messages:
            def get(self, **kwargs):
                requests.append(("get", kwargs))
                return Request({
                    "threadId": "thread-1",
                    "payload": {"headers": [
                        {"name": "From", "value": "Person <person@example.com>"},
                        {"name": "Subject", "value": "Project update"},
                        {"name": "Message-ID", "value": "<original@example.com>"},
                    ]},
                })

        class Drafts:
            def create(self, **kwargs):
                requests.append(("create", kwargs))
                captured.update(kwargs["body"])
                return Request({"id": "draft-1", "message": {"id": "message-1"}})

        class Users:
            def messages(self):
                return Messages()

            def drafts(self):
                return Drafts()

        class Api:
            def users(self):
                return Users()

        original_service = actions.service
        actions.service = lambda *_args: Api()
        try:
            args = argparse.Namespace(
                to="",
                cc="",
                subject="",
                body="Thanks — I will update it.",
                thread_id="",
                reply_to_message="message-0",
                expected_to="person@example.com",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                actions.gmail_draft(args)
        finally:
            actions.service = original_service

        self.assertEqual(captured["message"]["threadId"], "thread-1")
        raw = captured["message"]["raw"]
        parsed = email.message_from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        self.assertEqual(parsed["To"], "Person <person@example.com>")
        self.assertEqual(parsed["Subject"], "Re: Project update")
        self.assertEqual(parsed["In-Reply-To"], "<original@example.com>")
        self.assertEqual(parsed["References"], "<original@example.com>")
        result = json.loads(output.getvalue())
        self.assertEqual(result["to"], parsed["To"])
        self.assertEqual(result["subject"], parsed["Subject"])
        self.assertEqual(result["status"], "drafted")
        self.assertEqual(result["draft_id"], "draft-1")
        self.assertEqual(result["message_id"], "message-1")
        self.assertEqual([operation for operation, _ in requests], ["get", "create"])
        self.assertEqual(requests[0][1]["format"], "metadata")
        self.assertEqual(requests[0][1]["id"], "message-0")

    def test_standalone_draft_receipt_matches_headers_without_a_metadata_read(self):
        api = unittest.mock.Mock()
        create = api.users.return_value.drafts.return_value.create
        create.return_value.execute.return_value = {
            "id": "draft-standalone", "message": {"id": "message-standalone"}
        }
        args = argparse.Namespace(
            to="Coordinator <coordinator@example.test>",
            cc="Reviewer <reviewer@example.test>",
            subject="Warehouse handoff options",
            body="Which handoff time works for the team?\n\nThanks",
            thread_id="",
            reply_to_message="",
            allow_new_recipient=True,
        )
        output = io.StringIO()
        with patch.object(actions, "service", return_value=api), redirect_stdout(output):
            actions.gmail_draft(args)

        network_calls = [item[0] for item in api.mock_calls if item[0].endswith("execute")]
        self.assertEqual(network_calls, ["users().drafts().create().execute"])
        create.assert_called_once()
        submitted = create.call_args.kwargs["body"]["message"]
        parsed = email.message_from_bytes(base64.urlsafe_b64decode(submitted["raw"]))
        receipt = json.loads(output.getvalue())
        self.assertEqual(receipt["to"], parsed["To"])
        self.assertEqual(receipt["to"], args.to)
        self.assertEqual(receipt["subject"], parsed["Subject"])
        self.assertEqual(receipt["subject"], args.subject)
        self.assertEqual(parsed["Cc"], args.cc)
        self.assertNotIn("threadId", submitted)
        self.assertIsNone(parsed["In-Reply-To"])
        self.assertEqual(receipt["draft_id"], "draft-standalone")

    def test_reply_receipt_preserves_reply_to_precedence_and_explicit_overrides(self):
        for explicit_to, explicit_subject in (
            ("", ""),
            ("Delegate <delegate@example.test>", "Revised handoff question"),
        ):
            with self.subTest(to=explicit_to, subject=explicit_subject):
                api = unittest.mock.Mock()
                get = api.users.return_value.messages.return_value.get
                get.return_value.execute.return_value = {
                    "threadId": "thread-original",
                    "payload": {"headers": [
                        {"name": "From", "value": "Coordinator <coordinator@example.test>"},
                        {"name": "Reply-To", "value": "Operations <operations@example.test>"},
                        {"name": "Subject", "value": "Re: Warehouse handoff"},
                        {"name": "Message-ID", "value": "<original@example.test>"},
                        {"name": "References", "value": "<earlier@example.test>"},
                    ]},
                }
                create = api.users.return_value.drafts.return_value.create
                create.return_value.execute.return_value = {
                    "id": "draft-reply", "message": {"id": "message-reply"}
                }
                args = argparse.Namespace(
                    to=explicit_to, cc="", subject=explicit_subject,
                    body="Could you confirm the handoff owner?\n\nThanks",
                    thread_id="", reply_to_message="source-message",
                    expected_to="" if explicit_to else "operations@example.test",
                    allow_new_recipient=bool(explicit_to),
                )
                output = io.StringIO()
                with patch.object(actions, "service", return_value=api), redirect_stdout(output):
                    actions.gmail_draft(args)

                network_calls = [item[0] for item in api.mock_calls if item[0].endswith("execute")]
                self.assertEqual(network_calls, [
                    "users().messages().get().execute", "users().drafts().create().execute"
                ])
                get.assert_called_once()
                create.assert_called_once()
                self.assertEqual(get.call_args.kwargs["format"], "metadata")
                self.assertEqual(get.call_args.kwargs["id"], "source-message")
                submitted = create.call_args.kwargs["body"]["message"]
                parsed = email.message_from_bytes(base64.urlsafe_b64decode(submitted["raw"]))
                receipt = json.loads(output.getvalue())
                self.assertEqual(receipt["to"], parsed["To"])
                self.assertEqual(receipt["to"], explicit_to or "Operations <operations@example.test>")
                self.assertEqual(receipt["subject"], parsed["Subject"])
                self.assertEqual(receipt["subject"], explicit_subject or "Re: Warehouse handoff")
                self.assertEqual(submitted["threadId"], "thread-original")
                self.assertEqual(parsed["In-Reply-To"], "<original@example.test>")
                self.assertEqual(parsed["References"], "<earlier@example.test> <original@example.test>")

    def test_implicit_reply_requires_valid_expected_recipient_before_network_access(self):
        for expected_to in ("", "Coordinator", "missing-domain@", "@missing-local"):
            with self.subTest(expected_to=expected_to):
                args = actions.build_parser().parse_args([
                    "gmail", "draft", "--reply-to-message", "source-message",
                    "--expected-to", expected_to, "--body", "Please send an update.",
                ])
                with patch.object(actions, "service") as service, self.assertRaisesRegex(RuntimeError, "--expected-to"):
                    actions.gmail_draft(args)
                service.assert_not_called()

    def test_reply_recipient_assertion_uses_resolved_headers_and_exact_mailbox_sets(self):
        cases = [
            # From mismatch, then Reply-To mismatch even though From matches.
            ("other@example.test", "", "", "person@example.test", False),
            ("person@example.test", "other@example.test", "", "person@example.test", False),
            # Reply-To wins over From; display names and case do not change mailboxes.
            ("other@example.test", "Person <PERSON@example.test>", "", "person@EXAMPLE.TEST", True),
            ("First <first@example.test>, Second <second@example.test>", "", "",
             "SECOND@example.test, Renamed <first@EXAMPLE.TEST>", True),
            ("first@example.test, second@example.test", "", "", "first@example.test", False),
            # Do not apply provider-specific plus or dot alias equivalence.
            ("person+team@example.test", "", "", "person@example.test", False),
            ("per.son@example.test", "", "", "person@example.test", False),
            # An explicit To remains authoritative, with or without an assertion.
            ("person@example.test", "reply@example.test", "delegate@example.test", "", True),
            ("person@example.test", "reply@example.test", "delegate@example.test", "DELEGATE@example.test", True),
            ("person@example.test", "reply@example.test", "delegate@example.test", "person@example.test", False),
        ]
        for sender, reply_to, explicit_to, expected_to, succeeds in cases:
            with self.subTest(sender=sender, reply_to=reply_to, to=explicit_to, expected_to=expected_to):
                api = unittest.mock.Mock()
                get = api.users.return_value.messages.return_value.get
                get.return_value.execute.return_value = {
                    "threadId": "source-thread",
                    "payload": {"headers": [
                        {"name": "From", "value": sender},
                        {"name": "Reply-To", "value": reply_to},
                        {"name": "Subject", "value": "Coordination update"},
                        {"name": "Message-ID", "value": "<source@example.test>"},
                    ]},
                }
                create = api.users.return_value.drafts.return_value.create
                create.return_value.execute.return_value = {"id": "saved-draft", "message": {"id": "saved-message"}}
                args = actions.build_parser().parse_args([
                    "gmail", "draft", "--reply-to-message", "source-message",
                    "--to", explicit_to, "--expected-to", expected_to, "--body", "Please send an update.",
                ] + (["--allow-new-recipient"] if explicit_to else []))
                with patch.object(actions, "service", return_value=api), redirect_stdout(io.StringIO()):
                    if succeeds:
                        actions.gmail_draft(args)
                    else:
                        with self.assertRaisesRegex(RuntimeError, "Draft recipient mismatch"):
                            actions.gmail_draft(args)
                network_calls = [item[0] for item in api.mock_calls if item[0].endswith("execute")]
                expected_calls = ["users().messages().get().execute"]
                if succeeds:
                    expected_calls.append("users().drafts().create().execute")
                    create.assert_called_once()
                    submitted = create.call_args.kwargs["body"]["message"]
                    parsed = email.message_from_bytes(base64.urlsafe_b64decode(submitted["raw"]))
                    self.assertEqual(parsed["To"], explicit_to or reply_to or sender)
                    self.assertEqual(submitted["threadId"], "source-thread")
                else:
                    create.assert_not_called()
                self.assertEqual(network_calls, expected_calls)

    def test_standalone_draft_expected_recipient_is_checked_before_create(self):
        api = unittest.mock.Mock()
        args = actions.build_parser().parse_args([
            "gmail", "draft", "--to", "coordinator@example.test", "--expected-to", "other@example.test",
            "--subject", "Coordination update", "--body", "Please send an update.",
        ])
        with patch.object(actions, "service", return_value=api), self.assertRaisesRegex(RuntimeError, "Draft recipient mismatch"):
            actions.gmail_draft(args)
        api.users.return_value.messages.return_value.get.assert_not_called()
        api.users.return_value.drafts.return_value.create.assert_not_called()

    def test_explicit_draft_recipient_requires_exact_non_draft_header_evidence(self):
        cases = [
            ("from", "Renamed <PERSON@example.test>", [], True),
            ("Reply-To", "Person <person@example.test>", [], True),
            ("To", "Other <other@example.test>, Person <person@example.test>", [], True),
            ("Cc", "person@example.test", [], True),
            ("From", "not-person@example.test", [], False),
            ("From", "person+team@example.test", [], False),
            ("Subject", "person@example.test", [], False),
            ("From", "person@example.test", ["DRAFT"], False),
        ]
        for field, value, labels, succeeds in cases:
            with self.subTest(field=field, value=value, labels=labels):
                api = unittest.mock.Mock()
                messages = api.users.return_value.messages.return_value
                messages.list.return_value.execute.return_value = {"messages": [{"id": "candidate"}]}
                messages.get.return_value.execute.return_value = {
                    "labelIds": labels, "payload": {"headers": [{"name": field, "value": value}]},
                }
                create = api.users.return_value.drafts.return_value.create
                create.return_value.execute.return_value = {"id": "draft", "message": {"id": "message"}}
                args = actions.build_parser().parse_args([
                    "gmail", "draft", "--to", "Person <person@example.test>",
                    "--subject", "Coordination", "--body", "Please send an update.\n\nThanks",
                ])
                with patch.object(actions, "service", return_value=api) as service, redirect_stdout(io.StringIO()):
                    if succeeds:
                        actions.gmail_draft(args)
                        create.assert_called_once()
                    else:
                        with self.assertRaisesRegex(RuntimeError, "not verified"):
                            actions.gmail_draft(args)
                        create.assert_not_called()
                service.assert_called_once_with("gmail", "v1")
                messages.list.assert_called_once_with(
                    userId="me", q='-in:drafts {from:"person@example.test" to:"person@example.test" cc:"person@example.test"}', maxResults=5,
                )
                messages.get.assert_called_once_with(
                    userId="me", id="candidate", format="metadata", metadataHeaders=["From", "Reply-To", "To", "Cc"],
                )

    def test_recipient_lookup_rejects_absent_address_before_draft_create(self):
        api = unittest.mock.Mock()
        messages = api.users.return_value.messages.return_value
        messages.list.return_value.execute.return_value = {"messages": []}
        args = actions.build_parser().parse_args([
            "gmail", "draft", "--to", "guessed@example.test", "--subject", "Coordination", "--body", "Update?",
        ])
        with patch.object(actions, "service", return_value=api), self.assertRaisesRegex(RuntimeError, "not verified"):
            actions.gmail_draft(args)
        messages.get.assert_not_called()
        api.users.return_value.drafts.return_value.create.assert_not_called()

    def test_recipient_lookup_caps_candidates_and_stops_on_first_exact_match(self):
        for match_index in (0, 4, 5, None):
            with self.subTest(match_index=match_index):
                api = unittest.mock.Mock()
                messages = api.users.return_value.messages.return_value
                messages.list.return_value.execute.return_value = {"messages": [{"id": f"candidate-{i}"} for i in range(7)]}
                messages.get.side_effect = lambda **kw: unittest.mock.Mock(execute=lambda: {
                    "payload": {"headers": [{"name": "From", "value":
                        "person@example.test" if kw["id"] == f"candidate-{match_index}" else "other@example.test"}]},
                })
                create = api.users.return_value.drafts.return_value.create
                create.return_value.execute.return_value = {"id": "draft", "message": {"id": "message"}}
                args = actions.build_parser().parse_args([
                    "gmail", "draft", "--to", "person@example.test", "--subject", "Coordination", "--body", "Update?",
                ])
                with patch.object(actions, "service", return_value=api), redirect_stdout(io.StringIO()):
                    if match_index in (0, 4):
                        actions.gmail_draft(args)
                        create.assert_called_once()
                    else:
                        with self.assertRaisesRegex(RuntimeError, "not verified"):
                            actions.gmail_draft(args)
                        create.assert_not_called()
                self.assertEqual(messages.get.call_count, 1 if match_index == 0 else 5)
                self.assertEqual(messages.list.call_args.kwargs["maxResults"], 5)

    def test_explicit_to_and_cc_are_verified_once_per_mailbox(self):
        api = unittest.mock.Mock()
        messages = api.users.return_value.messages.return_value
        messages.list.return_value.execute.return_value = {"messages": [{"id": "candidate"}]}
        messages.get.return_value.execute.return_value = {"payload": {"headers": [
            {"name": "To", "value": "first@example.test"},
            {"name": "To", "value": "second@example.test"},
            {"name": "Cc", "value": "third@example.test"},
        ]}}
        api.users.return_value.drafts.return_value.create.return_value.execute.return_value = {
            "id": "draft", "message": {"id": "message"},
        }
        args = actions.build_parser().parse_args([
            "gmail", "draft", "--to", "First <FIRST@example.test>, second@example.test",
            "--cc", "first@example.test, third@example.test", "--subject", "Coordination", "--body", "Update?",
        ])
        with patch.object(actions, "service", return_value=api), redirect_stdout(io.StringIO()):
            actions.gmail_draft(args)
        self.assertEqual(messages.list.call_count, 3)
        self.assertEqual(messages.get.call_count, 3)
        api.users.return_value.drafts.return_value.create.assert_called_once()

    def test_reply_explicit_to_and_cc_need_evidence_but_inferred_to_does_not(self):
        for explicit_to, cc, known in (("delegate@example.test", "", True),
                                       ("delegate@example.test", "", False),
                                       ("", "reviewer@example.test", True),
                                       ("", "reviewer@example.test", False)):
            with self.subTest(to=explicit_to, cc=cc, known=known):
                api = unittest.mock.Mock()
                messages = api.users.return_value.messages.return_value
                source = {"threadId": "source-thread", "payload": {"headers": [
                    {"name": "From", "value": "sender@example.test"},
                    {"name": "Subject", "value": "Coordination"},
                    {"name": "Message-ID", "value": "<source@example.test>"},
                ]}}
                evidence = {"payload": {"headers": [{"name": "From", "value": explicit_to or cc}]}}
                messages.get.side_effect = [unittest.mock.Mock(execute=lambda: source), unittest.mock.Mock(execute=lambda: evidence)]
                messages.list.return_value.execute.return_value = {"messages": [{"id": "candidate"}] if known else []}
                create = api.users.return_value.drafts.return_value.create
                create.return_value.execute.return_value = {"id": "draft", "message": {"id": "message"}}
                args = actions.build_parser().parse_args([
                    "gmail", "draft", "--reply-to-message", "source-message", "--to", explicit_to,
                    "--cc", cc, "--expected-to", explicit_to or "sender@example.test", "--body", "Update?",
                ])
                with patch.object(actions, "service", return_value=api), redirect_stdout(io.StringIO()):
                    if known:
                        actions.gmail_draft(args)
                        create.assert_called_once()
                        self.assertEqual(create.call_args.kwargs["body"]["message"]["threadId"], "source-thread")
                    else:
                        with self.assertRaisesRegex(RuntimeError, "not verified"):
                            actions.gmail_draft(args)
                        create.assert_not_called()
                messages.list.assert_called_once()
                self.assertNotIn("sender@example.test", messages.list.call_args.kwargs["q"])
                self.assertEqual(messages.get.call_count, 2 if known else 1)

    def test_allow_new_recipient_does_not_bypass_expected_recipient_assertion(self):
        api = unittest.mock.Mock()
        args = actions.build_parser().parse_args([
            "gmail", "draft", "--to", "new@example.test", "--expected-to", "other@example.test",
            "--allow-new-recipient", "--subject", "Coordination", "--body", "Update?",
        ])
        with patch.object(actions, "service", return_value=api), self.assertRaisesRegex(RuntimeError, "Draft recipient mismatch"):
            actions.gmail_draft(args)
        api.users.return_value.messages.assert_not_called()
        api.users.return_value.drafts.return_value.create.assert_not_called()

    def test_recipient_lookup_failure_does_not_save_or_claim_address_invalid(self):
        for stage, error in (("list", TimeoutError("timed out")), ("get", RuntimeError("Lookup unavailable"))):
            with self.subTest(stage=stage):
                api = unittest.mock.Mock()
                messages = api.users.return_value.messages.return_value
                messages.list.return_value.execute.return_value = {"messages": [{"id": "candidate"}]}
                getattr(messages, stage).return_value.execute.side_effect = error
                args = actions.build_parser().parse_args([
                    "gmail", "draft", "--to", "person@example.test", "--subject", "Coordination", "--body", "Update?",
                ])
                with patch.object(actions, "service", return_value=api), self.assertRaisesRegex(RuntimeError, "not verified: Gmail header lookup failed") as raised:
                    actions.gmail_draft(args)
                self.assertIn(f"{type(error).__name__}: {error}", str(raised.exception))
                self.assertIs(raised.exception.__cause__, error)
                self.assertNotIn("--allow-new-recipient", str(raised.exception))
                api.users.return_value.drafts.return_value.create.assert_not_called()

    def test_sheets_get_defaults_to_bounded_range_and_reports_resolved_tab(self):
        for provided_range in (None, "'Project Overview'!B3:F12"):
            with self.subTest(range=provided_range):
                argv = ["sheets", "get", "spreadsheet-1"]
                if provided_range is not None:
                    argv.append(provided_range)
                args = actions.build_parser().parse_args(argv)
                self.assertEqual(args.range, provided_range or "A1:J80")
                api = unittest.mock.Mock()
                get = api.spreadsheets.return_value.values.return_value.get
                resolved_range = provided_range or "'Project Overview'!A1:J80"
                get.return_value.execute.return_value = {"range": resolved_range, "values": [["Project", "Status"]]}
                output = io.StringIO()
                with patch.object(actions, "service", return_value=api), redirect_stdout(output):
                    actions.sheets_get(args)
                get.assert_called_once_with(spreadsheetId="spreadsheet-1", range=args.range)
                self.assertEqual(json.loads(output.getvalue()), {
                    "spreadsheet_id": "spreadsheet-1", "range": resolved_range, "values": [["Project", "Status"]],
                })
                self.assertEqual([item[0] for item in api.mock_calls if item[0].endswith("execute")], [
                    "spreadsheets().values().get().execute",
                ])

    def test_name_only_draft_recipient_is_rejected_before_create(self):
        api = unittest.mock.Mock()
        args = argparse.Namespace(
            to="Grant Walker",
            cc="",
            subject="Retail demo ownership",
            body="Can you take ownership?\n\nThanks",
            thread_id="",
            reply_to_message="",
        )

        with patch.object(actions, "service", return_value=api), self.assertRaisesRegex(RuntimeError, "complete email address"):
            actions.gmail_draft(args)

        api.users().drafts().create.assert_not_called()

    def test_draft_body_inputs_preserve_text_and_real_newlines(self):
        text = "Hi team,\n\nLet's discuss \"options\" and $cost. Literal \\n stays literal.\n\nThanks\n"
        for option, value in [("--body", text), ("--body-file", "-"), ("--body-file", "body.txt")]:
            with self.subTest(option=option, value=value):
                args = actions.build_parser().parse_args([
                    "gmail", "draft", "--to", "team@example.test", "--subject", "Options", option, value,
                    "--allow-new-recipient",
                ])
                api = unittest.mock.Mock()
                create = api.users.return_value.drafts.return_value.create
                create.return_value.execute.return_value = {"id": "draft", "message": {"id": "message"}}
                with patch.object(actions, "service", return_value=api), patch.object(actions.sys, "stdin", io.StringIO(text)), patch.object(actions.Path, "read_text", return_value=text) as read_text, redirect_stdout(io.StringIO()):
                    actions.gmail_draft(args)
                if value == "body.txt":
                    read_text.assert_called_once_with(encoding="utf-8")
                else:
                    read_text.assert_not_called()
                raw = create.call_args.kwargs["body"]["message"]["raw"]
                parsed = email.message_from_bytes(base64.urlsafe_b64decode(raw))
                self.assertEqual(parsed.get_payload(decode=True).decode("utf-8"), text)
                api.users.return_value.messages.assert_not_called()
                create.assert_called_once()

    def test_empty_draft_body_is_rejected_before_network(self):
        for option, value in [("--body", "  \n"), ("--body-file", "-")]:
            with self.subTest(option=option):
                args = actions.build_parser().parse_args([
                    "gmail", "draft", "--to", "team@example.test", "--subject", "Options", option, value,
                ])
                with patch.object(actions, "service") as service, patch.object(actions.sys, "stdin", io.StringIO("\n ")):
                    with self.assertRaisesRegex(RuntimeError, "nonempty body"):
                        actions.gmail_draft(args)
                    service.assert_not_called()

    def test_draft_body_sources_are_required_and_mutually_exclusive(self):
        for argv in [[], ["--body", "Text", "--body-file", "-"]]:
            with self.subTest(argv=argv), redirect_stdout(io.StringIO()), patch.object(actions.sys, "stderr", io.StringIO()):
                with self.assertRaises(SystemExit):
                    actions.build_parser().parse_args(["gmail", "draft", *argv])

    def test_tracker_omitted_fields_are_skipped_and_explicit_empty_clears(self):
        updates = [
            {"lane": "Packaging check", "status": "In progress", "latest": "Review received"},
            {"lane": "Supplier clearance", "status": "Complete", "blocker": ""},
        ]
        args = actions.build_parser().parse_args([
            "sheets", "update-lanes", "sheet-id", "--sheet", "Operations", "--updates", json.dumps(updates), "--confirm", "--include-details",
        ])
        api = unittest.mock.Mock()
        values = api.spreadsheets.return_value.values.return_value
        values.get.return_value.execute.return_value = {"values": [
            ["Lane", "PIC", "Status", "Latest", "Next", "Due", "Blocker", "Evidence"],
            ["Packaging check", "Owner", "Awaiting update", "Old", "Review options", "2030-03-12", "", "source"],
            ["Supplier clearance", "Owner", "Blocked", "Old", "Follow up", "2030-03-13", "Waiting", "source"],
        ]}
        values.batchUpdate.return_value.execute.return_value = {"totalUpdatedRows": 2, "totalUpdatedCells": 4}
        with patch.object(actions, "service", return_value=api), redirect_stdout(io.StringIO()):
            actions.sheets_update_lanes(args)
        values.batchUpdate.assert_called_once_with(spreadsheetId="sheet-id", body={
            "valueInputOption": "USER_ENTERED", "data": [
                {"range": "'Operations'!C7:H7", "values": [["In progress", "Review received", None, None, None, None]]},
                {"range": "'Operations'!C8:H8", "values": [["Complete", None, None, None, "", None]]},
            ],
        })

    def test_unsupported_tracker_fields_fail_before_network_instead_of_being_ignored(self):
        for unsupported in ["next_action", "typo", "owner"]:
            with self.subTest(field=unsupported):
                args = actions.build_parser().parse_args([
                    "sheets", "update-lanes", "sheet-id", "--confirm", "--updates", json.dumps([
                        {"lane": "Packaging check", "status": "In progress", unsupported: "New text"},
                    ]),
                ])
                with patch.object(actions, "service") as service:
                    with self.assertRaisesRegex(RuntimeError, "Unsupported tracker fields"):
                        actions.sheets_update_lanes(args)
                    service.assert_not_called()


class TrackerBlockerReviewTests(unittest.TestCase):
    def test_unknown_lane_error_lists_current_names_without_writing_or_rereading(self):
        args, api, values = self.setup_update([
            ["Packing", "Owner", "Awaiting update"],
            ["Clearance", "Owner", "Awaiting update"],
        ], [
            {"lane": "Packing", "status": "Complete"},
            {"lane": "Missing lane", "status": "Complete"},
        ])
        with patch.object(actions, "service", return_value=api), patch.object(actions, "emit") as emit:
            with self.assertRaises(RuntimeError) as raised:
                actions.sheets_update_lanes(args)
        self.assertIn("Tracker lane(s) not found: ['Missing lane']", str(raised.exception))
        self.assertIn("Use exact lane names from this sheet: ['Clearance', 'Packing']", str(raised.exception))
        self.assertIn("Nothing was written.", str(raised.exception))
        values.get.assert_called_once_with(spreadsheetId="ops-sheet", range="'Operations'!A6:H100")
        values.get.return_value.execute.assert_called_once()
        values.batchUpdate.assert_not_called()
        emit.assert_not_called()

    def test_omitted_scope_flag_defaults_to_status_only(self):
        args, api, values = self.setup_update([
            ["Packing", "Owner", "Blocked", "Keep", "Next", "=TODAY()", "Old dependency", "source"],
        ], [{"lane": "Packing", "status": "Complete"}])
        args = actions.build_parser().parse_args([
            "sheets", "update-lanes", "ops-sheet", "--sheet", "Operations",
            "--updates", args.updates, "--confirm",
        ])
        self.assertTrue(args.status_only)
        with patch.object(actions, "service", return_value=api), redirect_stdout(io.StringIO()):
            actions.sheets_update_lanes(args)
        self.assertEqual(values.batchUpdate.call_args.kwargs["body"]["data"], [
            {"range": "'Operations'!C7", "values": [["Complete"]]},
        ])

    def test_default_scope_rejects_details_before_network(self):
        for field in ("latest", "next", "due", "blocker", "evidence"):
            with self.subTest(field=field):
                args = actions.build_parser().parse_args([
                    "sheets", "update-lanes", "ops-sheet", "--confirm", "--updates",
                    json.dumps([{"lane": "Packing", "status": "Complete", field: ""}]),
                ])
                with patch.object(actions, "service") as service:
                    with self.assertRaisesRegex(RuntimeError, "only lane and status"):
                        actions.sheets_update_lanes(args)
                service.assert_not_called()

    def test_scope_flags_are_mutually_exclusive(self):
        with patch.object(actions.sys, "stderr", io.StringIO()), self.assertRaises(SystemExit):
            actions.build_parser().parse_args([
                "sheets", "update-lanes", "ops-sheet", "--updates", "[]",
                "--status-only", "--include-details",
            ])

    def test_status_only_batches_exact_cells_without_touching_other_fields(self):
        args, api, values = self.setup_update([
            ["Packing", "Owner", "Blocked", "Keep", "", "=TODAY()", "Old dependency", "source"],
            ["Routing", "Owner", "Awaiting update", "", "Keep"],
            ["Clearance", "Owner", "Awaiting update"],
        ], [{"lane": lane, "status": "Complete"} for lane in ("Packing", "Routing", "Clearance")])
        args.status_only = True
        with patch.object(actions, "service", return_value=api), redirect_stdout(io.StringIO()):
            actions.sheets_update_lanes(args)
        values.batchUpdate.assert_called_once_with(spreadsheetId="ops-sheet", body={
            "valueInputOption": "USER_ENTERED", "data": [
                {"range": f"'Operations'!C{row}", "values": [["Complete"]]} for row in (7, 8, 9)
            ],
        })

    def test_status_only_rejects_extra_fields_before_any_api_call(self):
        for extra in ("latest", "next", "due", "blocker", "evidence"):
            with self.subTest(field=extra):
                args, _, _ = self.setup_update([], [{"lane": "Packing", "status": "Complete", extra: ""}])
                args.status_only = True
                with patch.object(actions, "service") as service:
                    with self.assertRaisesRegex(RuntimeError, "only lane and status"):
                        actions.sheets_update_lanes(args)
                service.assert_not_called()

    def setup_update(self, rows, updates):
        args = actions.build_parser().parse_args([
            "sheets", "update-lanes", "ops-sheet", "--sheet", "Operations",
            "--updates", json.dumps(updates), "--confirm", "--include-details",
        ])
        api = unittest.mock.Mock()
        values = api.spreadsheets.return_value.values.return_value
        values.get.return_value.execute.return_value = {"values": [
            ["Lane", "PIC", "Status", "Latest", "Next", "Due", "Blocker", "Evidence"],
            *rows,
        ]}
        values.batchUpdate.return_value.execute.return_value = {"totalUpdatedRows": len(updates)}
        return args, api, values

    def test_missing_and_null_blockers_reject_whole_batch_and_name_every_lane(self):
        args, api, values = self.setup_update([
            ["Packing", "Owner", "Blocked", "", "", "", "Awaiting packaging specification"],
            ["Routing", "Owner", "Blocked", "", "", "", "Awaiting route confirmation"],
            ["Inventory", "Owner", "Awaiting update"],
        ], [
            {"lane": "Inventory", "status": "On track"},
            {"lane": "Packing", "status": "In progress"},
            {"lane": "Routing", "status": "Complete", "blocker": None},
        ])
        with patch.object(actions, "service", return_value=api):
            with self.assertRaises(RuntimeError) as raised:
                actions.sheets_update_lanes(args)
        self.assertIn("Packing", str(raised.exception))
        self.assertIn("Routing", str(raised.exception))
        self.assertIn("Nothing was written", str(raised.exception))
        values.get.assert_called_once()
        values.batchUpdate.assert_not_called()

    def test_nonstring_blocker_cannot_bypass_review(self):
        for blocker in [None, False, 0, [], {}]:
            with self.subTest(blocker=blocker):
                args, api, values = self.setup_update([
                    ["Packing", "Owner", "Blocked", "", "", "", "Supplier confirmation"],
                ], [{"lane": "Packing", "status": "In progress", "blocker": blocker}])
                with patch.object(actions, "service", return_value=api):
                    with self.assertRaisesRegex(RuntimeError, "explicit blocker text"):
                        actions.sheets_update_lanes(args)
                values.batchUpdate.assert_not_called()

    def test_explicit_preserve_clear_or_revision_writes_verbatim(self):
        for blocker in ["Supplier confirmation", "", "Final shipment inspection"]:
            with self.subTest(blocker=blocker):
                args, api, values = self.setup_update([
                    ["Packing", "Owner", "Blocked", "Old", "Next", "2031-04-09", "Supplier confirmation", "source"],
                ], [{"lane": "Packing", "status": "In progress", "blocker": blocker}])
                with patch.object(actions, "service", return_value=api), redirect_stdout(io.StringIO()):
                    actions.sheets_update_lanes(args)
                values.get.assert_called_once()
                values.batchUpdate.assert_called_once_with(spreadsheetId="ops-sheet", body={
                    "valueInputOption": "USER_ENTERED", "data": [
                        {"range": "'Operations'!C7:H7", "values": [["In progress", None, None, None, blocker, None]]},
                    ],
                })

    def test_unchanged_status_can_still_omit_blocker(self):
        args, api, values = self.setup_update([
            ["Packing", "Owner", "Blocked", "Old", "Next", "2031-04-09", "Supplier confirmation", "source"],
        ], [{"lane": "Packing", "status": "Blocked", "latest": "Reminder received"}])
        with patch.object(actions, "service", return_value=api), redirect_stdout(io.StringIO()):
            actions.sheets_update_lanes(args)
        data = values.batchUpdate.call_args.kwargs["body"]["data"]
        self.assertEqual(data[0]["values"], [["Blocked", "Reminder received", None, None, None, None]])

    def test_blank_and_short_rows_do_not_require_a_blocker(self):
        rows = [["Sparse"], ["Trailing blanks", "Owner", "Awaiting update"]]
        rows.extend([
            [f"Empty {index}", "Owner", "Awaiting update", "", "", "", value]
            for index, value in enumerate(["", " \t ", None])
        ])
        args, api, values = self.setup_update(rows, [
            {"lane": row[0], "status": "On track"} for row in rows
        ])
        with patch.object(actions, "service", return_value=api), redirect_stdout(io.StringIO()):
            actions.sheets_update_lanes(args)
        values.get.assert_called_once()
        values.batchUpdate.assert_called_once()
        data = values.batchUpdate.call_args.kwargs["body"]["data"]
        self.assertEqual(len(data), len(rows))
        self.assertTrue(all(item["values"] == [["On track", None, None, None, None, None]] for item in data))


if __name__ == "__main__":
    unittest.main()
