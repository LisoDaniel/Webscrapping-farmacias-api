"""Regressão da coleta assistida.

A garantia central é a mesma do resto do projeto: nunca apresentar como atual
um dado que não é. Uma captura velha tem de virar erro acionável, não preço.
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app.core.capture_store import CaptureExpired, CaptureStore

EAN = "7891058003555"


def escrever_captura(directory: Path, captured_at: datetime, results=None, uf="GO"):
    payload = {
        "pharmacy": "panvel",
        "uf": uf,
        "captured_at": captured_at.isoformat(),
        "results": results
        if results is not None
        else {EAN: {"items": [{"ean": EAN, "name": "Puran T4", "price": 3.49}]}},
    }
    (directory / "panvel.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


class CaptureStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.store = CaptureStore(self.directory, max_age_hours=24)

    def tearDown(self):
        self.temp.cleanup()

    def test_absent_file_returns_none(self):
        self.assertIsNone(self.store.get("panvel", EAN))

    def test_fresh_capture_is_returned(self):
        agora = datetime.now()
        escrever_captura(self.directory, agora)
        captured = self.store.get("panvel", EAN)
        self.assertIsNotNone(captured)
        self.assertEqual(captured.uf, "GO")
        self.assertEqual(captured.payload["items"][0]["ean"], EAN)
        self.assertAlmostEqual(captured.captured_at.timestamp(), agora.timestamp(), places=0)

    def test_stale_capture_raises(self):
        """Preço de ontem não pode entrar no relatório como preço de hoje."""
        escrever_captura(self.directory, datetime.now() - timedelta(hours=30))
        with self.assertRaises(CaptureExpired) as ctx:
            self.store.get("panvel", EAN)
        self.assertIn("Refaça a coleta", str(ctx.exception))

    def test_ean_absent_from_capture_returns_none(self):
        escrever_captura(self.directory, datetime.now())
        self.assertIsNone(self.store.get("panvel", "7897595901033"))

    def test_malformed_file_is_ignored(self):
        (self.directory / "panvel.json").write_text("{ isso nao e json", encoding="utf-8")
        self.assertIsNone(self.store.get("panvel", EAN))

    def test_capture_without_timestamp_is_ignored(self):
        (self.directory / "panvel.json").write_text(
            json.dumps({"results": {EAN: {"items": []}}}), encoding="utf-8"
        )
        self.assertIsNone(self.store.get("panvel", EAN))


if __name__ == "__main__":
    unittest.main()
