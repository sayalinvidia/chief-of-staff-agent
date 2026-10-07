"""Exercise partial batch failures without sending live Google requests."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httplib2
from googleapiclient.errors import HttpError

sys.path.insert(0, str(Path(__file__).parent))
import seed_workspace as seed


def error(status, reason, retry_after=None):
    headers = {"status": str(status)}
    if retry_after is not None:
        headers["retry-after"] = str(retry_after)
    return HttpError(httplib2.Response(headers), json.dumps({"error": {"message": reason, "errors": [{"reason": reason}]}}).encode())


class FakeAPI:
    def __init__(self, outcomes, transport=None):
        self.outcomes = {key: list(values) for key, values in outcomes.items()}
        self.batches = []
        self.transport = list(transport or [])

    def new_batch_http_request(self):
        api = self
        class Batch:
            def __init__(self): self.items = []
            def add(self, request, callback, request_id): self.items.append((request, callback, request_id))
            def execute(self):
                api.batches.append([r for r, _, _ in self.items])
                if api.transport:
                    exc = api.transport.pop(0)
                    if exc: raise exc
                for request, callback, request_id in self.items:
                    outcome = api.outcomes.get(request, [request]).pop(0)
                    callback(request_id, None if isinstance(outcome, Exception) else outcome, outcome if isinstance(outcome, Exception) else None)
        return Batch()


class GoogleBatchTests(unittest.TestCase):
    def setUp(self):
        self.sleep = patch.object(seed.time, 'sleep').start()
        patch.object(seed.random, 'uniform', return_value=0).start()
        patch.object(seed, '_batch_http', return_value=None).start()  # sequential path; FakeAPI has no transport
        self.addCleanup(patch.stopall)

    def test_retries_only_rejected_imports_and_preserves_result_order(self):
        api = FakeAPI({'a': [{'id': 'a'}], 'b': [error(429, 'rateLimitExceeded'), {'id': 'b'}], 'c': [{'id': 'c'}]})
        self.assertEqual([{'id': 'a'}, {'id': 'b'}, {'id': 'c'}], seed.execute_batched(api, ['a', 'b', 'c']))
        self.assertEqual([['a', 'b', 'c'], ['b']], api.batches)
        self.sleep.assert_called_once_with(1)

    def test_permissions_error_is_not_retried_and_stops_later_batches(self):
        api = FakeAPI({0: [error(403, 'insufficientPermissions')]})
        with self.assertRaises(RuntimeError): seed.execute_batched(api, list(range(seed.BATCH_SIZE + 1)))
        self.assertEqual(1, len(api.batches))
        self.sleep.assert_not_called()

    def test_respects_retry_after_and_403_rate_limit(self):
        api = FakeAPI({'a': [error(403, 'userRateLimitExceeded', 7), 'ok']})
        self.assertEqual(['ok'], seed.execute_batched(api, ['a']))
        self.sleep.assert_called_once_with(7)

    def test_exhaustion_is_reported_even_when_cleanup_ignores_missing_items(self):
        api = FakeAPI({'a': [error(429, 'rateLimitExceeded')] * 6})
        with self.assertRaisesRegex(RuntimeError, 'after 5 retries'):
            seed.execute_batched(api, ['a'], ignore_errors=True)
        self.assertEqual(6, len(api.batches))

    def test_missing_cleanup_item_can_be_ignored(self):
        api = FakeAPI({'a': [error(404, 'notFound')], 'b': ['ok']})
        self.assertEqual([None, 'ok'], seed.execute_batched(api, ['a', 'b'], ignore_errors=True))

    def test_batch_level_rejection_is_retried(self):
        api = FakeAPI({'a': ['ok']}, transport=[error(429, 'rateLimitExceeded'), None])
        self.assertEqual(['ok'], seed.execute_batched(api, ['a']))
        self.assertEqual([['a'], ['a']], api.batches)

    def test_unknown_write_failure_is_not_replayed(self):
        api = FakeAPI({}, transport=[TimeoutError('unknown outcome')])
        with self.assertRaises(TimeoutError): seed.execute_batched(api, ['a'])
        self.assertEqual(1, len(api.batches))


if __name__ == '__main__':
    unittest.main()
