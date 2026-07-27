import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("GOOGLE_SPREADSHEET_ID", "test-sheet")

from src import email_intake, processor, sheets


class ProcessorTests(unittest.TestCase):
    def test_validate_event_calculates_active_and_normalizes_province(self):
        event = processor.validate_event_data(
            {
                "nombre": "Taller de adobe",
                "fecha_inicio": "27/07/2026",
                "fecha_fin": None,
                "provincia": "cordoba",
                "pais": None,
                "confianza": "alta",
            },
            today=date(2026, 7, 27),
        )

        self.assertTrue(event["activo"])
        self.assertEqual(event["provincia"], "Córdoba")
        self.assertEqual(event["pais"], "Argentina")
        self.assertEqual(event["fecha_inicio_iso"], "2026-07-27")

    def test_validate_event_rejects_invalid_or_past_date(self):
        invalid = processor.validate_event_data(
            {"nombre": "Evento", "fecha_inicio": "32/13/2026", "pais": "Argentina"},
            today=date(2026, 7, 27),
        )
        past = processor.validate_event_data(
            {"nombre": "Evento", "fecha_inicio": "01/01/2026", "pais": "Argentina"},
            today=date(2026, 7, 27),
        )

        self.assertFalse(invalid["activo"])
        self.assertEqual(invalid["fecha_inicio_iso"], "")
        self.assertFalse(past["activo"])

    def test_validate_event_keeps_ongoing_event_active(self):
        event = processor.validate_event_data(
            {
                "nombre": "Formación anual",
                "fecha_inicio": "01/07/2026",
                "fecha_fin": "30/07/2026",
                "pais": "Argentina",
            },
            today=date(2026, 7, 27),
        )

        self.assertTrue(event["activo"])

    @patch("src.processor._get_raw_json")
    def test_supplied_email_body_is_included_in_initial_prompt(self, get_raw_json):
        get_raw_json.return_value = (
            '{"es_evento":true,"nombre":"Minga","fecha_inicio":"30/07/2026",'
            '"fecha_fin":null,"es_virtual":false,"provincia":"Mendoza",'
            '"pais":"Argentina","confianza":"alta"}'
        )
        with tempfile.NamedTemporaryFile(suffix=".jpg") as image:
            Path(image.name).write_bytes(b"fake-image")
            processor.extract_event_data(
                Path(image.name),
                {
                    "caption": "El encuentro comienza a las 9",
                    "source": "email",
                    "discovered_at": "2026-07-27",
                },
            )

        prompt = get_raw_json.call_args.args[3]
        self.assertIn("El encuentro comienza a las 9", prompt)


class SheetsTests(unittest.TestCase):
    def test_dedupe_key_allows_same_title_on_different_dates(self):
        first = sheets.event_dedupe_key(
            {"nombre": "Taller de Barro", "fecha_inicio_iso": "2026-08-01", "provincia": "Córdoba"}
        )
        second = sheets.event_dedupe_key(
            {"nombre": "taller de barro", "fecha_inicio_iso": "2026-09-01", "provincia": "Cordoba"}
        )

        self.assertNotEqual(first, second)


class EmailIntakeTests(unittest.TestCase):
    @patch("src.email_intake.mark_row")
    @patch("src.email_intake.append_events")
    @patch("src.email_intake.extract_event_data")
    @patch("src.email_intake.download_drive_image", return_value=True)
    @patch("src.email_intake.load_pending_rows")
    @patch("src.email_intake.get_service")
    def test_marks_row_only_after_successful_append(
        self,
        get_service,
        load_pending_rows,
        download_drive_image,
        extract_event_data,
        append_events,
        mark_row,
    ):
        service = Mock()
        get_service.return_value = service
        load_pending_rows.return_value = [{
            "sheet_row": 2,
            "remitente": "organizador@example.com",
            "asunto": "Evento",
            "codigo": "",
            "cuerpo": "Datos del evento",
            "imagen_url": "https://example.com/image.jpg",
            "timestamp": "2026-07-27",
        }]
        event = {
            "nombre": "Minga",
            "fecha_inicio_iso": "2026-08-01",
            "provincia": "Mendoza",
        }
        extract_event_data.return_value = event
        key = sheets.event_dedupe_key(event)
        append_events.return_value = {key}

        calls = []
        append_events.side_effect = lambda *args, **kwargs: calls.append("append") or {key}
        mark_row.side_effect = lambda *args, **kwargs: calls.append("mark")

        inserted = email_intake.process_queue()

        self.assertEqual(inserted, 1)
        self.assertEqual(calls, ["append", "mark"])
        mark_row.assert_called_once_with(service, 2, "true")

    @patch("src.email_intake.mark_row")
    @patch("src.email_intake.append_events", side_effect=RuntimeError("Sheets no disponible"))
    @patch("src.email_intake.extract_event_data")
    @patch("src.email_intake.download_drive_image", return_value=True)
    @patch("src.email_intake.load_pending_rows")
    @patch("src.email_intake.get_service", return_value=Mock())
    def test_does_not_mark_row_when_append_fails(
        self,
        get_service,
        load_pending_rows,
        download_drive_image,
        extract_event_data,
        append_events,
        mark_row,
    ):
        load_pending_rows.return_value = [{
            "sheet_row": 2,
            "remitente": "organizador@example.com",
            "asunto": "Evento",
            "codigo": "",
            "cuerpo": "Datos del evento",
            "imagen_url": "https://example.com/image.jpg",
            "timestamp": "2026-07-27",
        }]
        extract_event_data.return_value = {
            "nombre": "Minga",
            "fecha_inicio_iso": "2026-08-01",
            "provincia": "Mendoza",
        }

        with self.assertRaisesRegex(RuntimeError, "Sheets no disponible"):
            email_intake.process_queue()

        mark_row.assert_not_called()


if __name__ == "__main__":
    unittest.main()
