import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("GOOGLE_SPREADSHEET_ID", "test-sheet")

import main
from src.sheets import event_dedupe_key


class MainPipelineTests(unittest.TestCase):
    @patch("main.process_manual_queue", return_value=0)
    @patch("main.append_events")
    @patch("main.process_batch")
    @patch("main.download_all")
    @patch("main.CandidateStore")
    def test_published_event_finalizes_candidate(
        self,
        candidate_store_class,
        download_all,
        process_batch,
        append_events,
        process_manual_queue,
    ):
        store = Mock()
        candidate_store_class.return_value = store
        store.load_retries.return_value = []
        discovered = [(Path("image.jpg"), {"hash": "hash-1"})]
        store.register.return_value = discovered
        download_all.return_value = discovered
        event = {
            "nombre": "Taller de adobe",
            "fecha_inicio_iso": "2026-08-01",
            "provincia": "Córdoba",
            "id": "event-1",
            "_candidate_row": 2,
            "_candidate_attempts": 1,
            "activo": True,
        }
        process_batch.return_value = [event]
        append_events.return_value = {event_dedupe_key(event)}

        inserted = main.run()

        self.assertEqual(inserted, 1)
        final_call = store.update.call_args_list[-1]
        self.assertEqual(final_call.kwargs["status"], "publicado")
        self.assertEqual(final_call.kwargs["event_id"], "event-1")


if __name__ == "__main__":
    unittest.main()
