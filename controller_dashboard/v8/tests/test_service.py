import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import service


class ServiceTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.env = patch.dict("os.environ", {"V8_TOKEN": "z" * 48, "V8_DB": tmp.name + "/state"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.api = TestClient(service.app)
        self.headers = {"X-Bitrix-User": "17", "X-Dashboard-Token": "z" * 48}

    def test_acl(self):
        for route in ("view", "source", "observe"):
            self.assertEqual(self.api.post("/" + route, json={}).status_code, 403)
        self.assertEqual(
            self.api.post("/observe", headers={"X-Dashboard-Token": "z" * 48}, json={}).status_code,
            401,
        )
        self.assertEqual(
            self.api.post(
                "/source", headers=self.headers, json={"source": "memo", "group": 123}
            ).status_code,
            403,
        )

    def test_markers_and_restriction(self):
        def observe(ids, user="17"):
            response = self.api.post(
                "/observe",
                headers={**self.headers, "X-Bitrix-User": user},
                json={
                    "group": 123,
                    "rows": [{"id": i, "state": "open", "last_comment": 5} for i in ids],
                },
            )
            self.assertEqual(response.status_code, 200)
            return response.json()

        self.assertIsNone(observe([1, 2])["extra"]["1"]["unread"])
        for marker in (5, 2):
            self.api.post(
                "/view", headers=self.headers, json={"task": 1, "marker": marker}
            ).raise_for_status()
        self.assertFalse(observe([1])["extra"]["1"]["unread"])
        self.assertIsNone(observe([1], "18")["extra"]["1"]["unread"])
        self.assertTrue(all("2" not in ids for ids in observe([1])["history"].values()))

    def test_calendar(self):
        def dt(s):
            return service.stamp(s + "+03:00")

        self.assertEqual(service.minutes(dt("2026-01-08T09:00"), dt("2026-01-12T18:00")), 480)
        self.assertEqual(service.minutes(dt("2026-04-30T09:00"), dt("2026-05-01T18:00")), 420)
        self.assertIsNone(service.minutes(dt("2031-04-30T09:00"), dt("2031-05-01T18:00")))
        self.assertIsNone(service.elapsed_days(None, dt("2026-04-30T09:00")))

    def test_sources(self):
        self.assertEqual(service.candidates([], None, False)["tasks"], {})
        with self.assertRaises(ValueError):
            service.candidates(None, None, True)
        rows = [
            {"task_id": 1, "role": "assistant"},
            {"task_id": 1, "role": "executor", "memo": "A"},
        ]
        self.assertEqual(service.candidates(rows, None, True)["tasks"][1]["document"], "A")
