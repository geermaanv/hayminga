import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

os.environ.setdefault("GOOGLE_SPREADSHEET_ID", "test-sheet")

from src import candidates, processor


class CandidateStoreTests(unittest.TestCase):
    def make_store(self):
        store = candidates.CandidateStore.__new__(candidates.CandidateStore)
        store.service = MagicMock()
        return store

    def test_candidate_key_prefers_post_link(self):
        first = candidates.candidate_key({"link": "https://instagram.com/p/abc/", "hash": "one"})
        second = candidates.candidate_key({"link": "https://instagram.com/p/abc", "hash": "two"})

        self.assertEqual(first, second)

    def test_creates_candidate_sheet_and_header_when_missing(self):
        service = MagicMock()
        service.spreadsheets().get().execute.return_value = {"sheets": []}
        service.spreadsheets().values().get().execute.return_value = {"values": []}

        candidates.CandidateStore(service=service)

        service.spreadsheets().batchUpdate.assert_called_once()
        header_body = (
            service.spreadsheets().values().update.call_args.kwargs["body"]
        )
        self.assertEqual(header_body["values"][0], candidates.COLUMNS)

    def test_registers_new_candidate_before_processing(self):
        store = self.make_store()
        store.load_all = Mock(return_value=[])
        store.service.spreadsheets().values().append().execute.return_value = {
            "updates": {"updatedRange": "Candidatos!A2:Q2"}
        }
        metadata = {
            "link": "https://instagram.com/p/abc",
            "thumbnail": "https://example.com/image.jpg",
            "hash": "hash-1",
            "source": "google_images",
            "query": "bioconstruccion argentina",
            "discovered_at": "2026-07-27T12:00:00+00:00",
            "caption": "Taller de adobe en Córdoba",
        }

        ready = store.register([(Path("image.jpg"), metadata)])

        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0][1]["_candidate_row"], 2)
        self.assertEqual(ready[0][1]["_candidate_attempts"], 0)
        body = (
            store.service.spreadsheets().values().append.call_args.kwargs["body"]
        )
        self.assertEqual(body["values"][0][7], "nuevo")
        self.assertEqual(body["values"][0][16], "Taller de adobe en Córdoba")

    def test_does_not_register_existing_terminal_candidate(self):
        store = self.make_store()
        store.load_all = Mock(return_value=[{
            "link": "https://instagram.com/p/abc",
            "hash": "hash-1",
            "status": "publicado",
            "attempts": 1,
        }])

        ready = store.register([(
            Path("image.jpg"),
            {"link": "https://instagram.com/p/abc", "hash": "hash-1"},
        )])

        self.assertEqual(ready, [])
        store.service.spreadsheets().values().append.assert_not_called()

    def test_failed_retry_download_increments_attempts(self):
        store = self.make_store()
        candidate = {
            "id": "candidate-1",
            "discovered_at": "2026-07-27",
            "source": "google_images",
            "query": "",
            "link": "https://instagram.com/p/abc",
            "thumbnail": "https://example.com/image.jpg",
            "hash": "hash-1",
            "status": "reintentar",
            "attempts": 1,
            "_candidate_row": 2,
        }
        store.load_all = Mock(return_value=[candidate])
        store._download_retry = Mock(side_effect=RuntimeError("URL vencida"))
        store.update = Mock()

        ready = store.load_retries()

        self.assertEqual(ready, [])
        self.assertEqual(store.update.call_args.kwargs["attempts"], 2)
        self.assertEqual(store.update.call_args.kwargs["reason"], "descarga_fallida")


class ProcessorCandidateStateTests(unittest.TestCase):
    @patch("src.processor.save_link")
    @patch("src.processor.save_hash")
    @patch("src.processor.extract_event_data", return_value=None)
    def test_non_event_is_persisted_as_discarded(self, extract, save_hash, save_link):
        store = Mock()
        metadata = {
            "hash": "hash-1",
            "link": "https://instagram.com/p/abc",
            "_candidate_row": 2,
            "_candidate_attempts": 0,
        }
        with tempfile.NamedTemporaryFile(suffix=".jpg") as image:
            Path(image.name).write_bytes(b"fake-image")
            result = processor.process_batch(
                [(Path(image.name), metadata)],
                candidate_store=store,
            )

        self.assertEqual(result, [])
        statuses = [call.kwargs["status"] for call in store.update.call_args_list]
        self.assertEqual(statuses, ["procesando", "descartado"])


if __name__ == "__main__":
    unittest.main()
