import datetime as dt
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from meta_client import MetaAPIError, MetaClient  # noqa: E402
from normalize import build_row, expand_schema, norm_phone, sha256  # noqa: E402
from sync import batches_with_last_flag, upload_rows  # noqa: E402


class NormalizeTests(unittest.TestCase):
    def test_full_row(self):
        columns = {"EMAIL": "email", "PHONE": "phone", "FN": "fn", "LN": "ln",
                   "ST": "st", "ZIP": "zip", "DOB": "dob", "EXTERN_ID": "id"}
        schema = expand_schema(columns, "us")
        self.assertEqual(schema, ["EMAIL", "PHONE", "FN", "LN", "ST", "ZIP",
                                  "DOBY", "DOBM", "DOBD", "EXTERN_ID", "COUNTRY"])
        row = build_row({"email": "  John.Doe@Example.COM ", "phone": "(555) 123-4567",
                         "fn": "Mary-Ann", "ln": "O'Brien", "st": "New York",
                         "zip": "10001-1234", "dob": dt.date(1990, 3, 7), "id": 42},
                        columns, schema, default_country="us", default_phone_cc="1")
        expected = ["john.doe@example.com", "15551234567", "maryann", "obrien", "ny",
                    "10001", "1990", "03", "07"]
        self.assertEqual(row[:9], [sha256(v) for v in expected])
        self.assertEqual(row[9], "42")             # EXTERN_ID is not hashed
        self.assertEqual(row[10], sha256("us"))

    def test_missing_fields_are_empty_and_unusable_rows_dropped(self):
        columns = {"EMAIL": "email", "FN": "fn"}
        schema = expand_schema(columns, None)
        self.assertEqual(build_row({"email": "a@b.co", "fn": None}, columns, schema),
                         [sha256("a@b.co"), ""])
        self.assertIsNone(build_row({"email": "not-an-email", "fn": "Bob"}, columns, schema))

    def test_prehashed_passthrough(self):
        h = sha256("a@b.co")
        self.assertEqual(build_row({"e": h.upper()}, {"EMAIL": "e"}, ["EMAIL"]), [h])

    def test_phone(self):
        self.assertEqual(norm_phone("+44 7700 900123"), "447700900123")
        self.assertEqual(norm_phone("07700 900123", "44"), "447700900123")
        self.assertEqual(norm_phone("1-555-123-4567", "1"), "15551234567")


class BatchingTests(unittest.TestCase):
    def test_last_flag(self):
        out = list(batches_with_last_flag(([str(i)] for i in range(5)), 2))
        self.assertEqual([(len(b), last) for b, last in out], [(2, False), (2, False), (1, True)])
        self.assertEqual(list(batches_with_last_flag(iter([]), 2)), [])

    def test_upload_sessions(self):
        client = mock.Mock()
        client.upload.return_value = {"num_received": 2, "num_invalid_entries": 0}
        stats = upload_rows(client, "123", "replace", ["EMAIL"], ([str(i)] for i in range(3)),
                            batch_size=2, estimated_total=3)
        sessions = [c.args[4] for c in client.upload.call_args_list]
        self.assertEqual([s["batch_seq"] for s in sessions], [1, 2])
        self.assertEqual([s["last_batch_flag"] for s in sessions], [False, True])
        self.assertEqual(len({s["session_id"] for s in sessions}), 1)
        self.assertEqual(stats["sent"], 3)

    def test_replace_with_no_rows_refuses(self):
        with self.assertRaises(RuntimeError):
            upload_rows(mock.Mock(), "123", "replace", ["EMAIL"], [])


class ClientTests(unittest.TestCase):
    def _resp(self, status, body, headers=None):
        r = mock.Mock(status_code=status, ok=status < 400, headers=headers or {})
        r.json.return_value = body
        return r

    def test_upload_request_shape_and_retry(self):
        http = mock.Mock()
        http.request.side_effect = [
            self._resp(400, {"error": {"code": 80003, "message": "throttled"}}),
            self._resp(200, {"audience_id": "123", "num_received": 1}),
        ]
        client = MetaClient("tok", "secret", api_version="v24.0", session=http)
        with mock.patch("meta_client.time.sleep"):
            client.upload("123", "add", ["EMAIL"], [["h"]], {"session_id": 1})
        method, url = http.request.call_args.args
        data = http.request.call_args.kwargs["data"]
        self.assertEqual((method, url), ("POST", "https://graph.facebook.com/v24.0/123/users"))
        self.assertEqual(json.loads(data["payload"]), {"schema": ["EMAIL"], "data": [["h"]]})
        self.assertEqual(data["access_token"], "tok")
        self.assertIn("appsecret_proof", data)
        self.assertEqual(http.request.call_count, 2)

    def test_non_retryable_error_raises(self):
        http = mock.Mock()
        http.request.return_value = self._resp(400, {"error": {"code": 100, "message": "bad"}})
        with self.assertRaises(MetaAPIError):
            MetaClient("tok", session=http).upload("1", "remove", ["EMAIL"], [["h"]])
        self.assertEqual(http.request.call_args.args[0], "DELETE")


if __name__ == "__main__":
    unittest.main()
