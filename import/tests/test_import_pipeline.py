import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch
from google.genai import types

os.environ.setdefault("GOOGLE_SPREADSHEET_ID", "test-sheet")

from src import email_intake, processor, sheets


class ProcessorTests(unittest.TestCase):
    def test_source_match_requires_specific_name_and_corroboration(self):
        event = {
            "nombre": "Taller de Permacultura y Sustentación en Crotto",
            "fecha_inicio_iso": "2026-07-25",
            "direccion": "Museo Comunitario Municipal Crotto",
            "provincia": "Buenos Aires",
            "organizador": "Proyecto Sierra Morena",
        }

        self.assertTrue(processor.source_matches_event(
            event,
            "Taller de Permacultura y Sustentación en Crotto. "
            "25 de julio, Museo Comunitario Municipal Crotto.",
        ))
        self.assertFalse(processor.source_matches_event(
            event,
            "Instalación y manejo de sistema de agromonte en La Pituca, "
            "22 de julio.",
        ))

    def test_parse_json_recovers_object_surrounded_by_claude_explanation(self):
        raw = (
            "# Análisis del flyer\n"
            "```json\n"
            '{"es_evento": true, "nombre": "Taller de barro"}'
            "\n```\nLa fecha fue leída de la imagen."
        )

        parsed = processor._parse_json_evento(raw, Path("flyer.jpg"))

        self.assertEqual(parsed["nombre"], "Taller de barro")

    def test_parse_json_does_not_accept_truncated_object(self):
        processor._batch_state["last_failure_reason"] = ""

        parsed = processor._parse_json_evento(
            '{"es_evento": true, "nombre": "Taller"',
            Path("flyer.jpg"),
        )

        self.assertIsNone(parsed)
        self.assertEqual(
            processor._batch_state["last_failure_reason"],
            "json_invalido",
        )

    def setUp(self):
        processor._batch_state.update({
            "gemini_exhausted": False,
            "claude_exhausted": False,
            "claude_calls": 0,
            "last_failure_reason": "",
        })

    def test_event_schema_is_accepted_by_installed_google_sdk(self):
        schema = types.Schema.model_validate(processor.EVENT_SCHEMA)
        self.assertEqual(schema.type, types.Type.OBJECT)
        serialized = schema.model_dump(by_alias=True, exclude_none=True)
        self.assertNotIn("additionalProperties", serialized)
        self.assertNotIn("additional_properties", serialized)

    def test_read_image_detects_real_mime_instead_of_file_extension(self):
        with tempfile.NamedTemporaryFile(suffix=".jpg") as image:
            Path(image.name).write_bytes(b"\x89PNG\r\n\x1a\nfake")
            _, media_type = processor.read_image(Path(image.name))
        self.assertEqual(media_type, "image/png")

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("src.processor.genai.Client")
    def test_gemini_uses_stable_low_cost_model_with_minimal_thinking(self, client_class):
        response = Mock()
        response.text = '{"es_evento":false}'
        response.candidates = []
        client_class.return_value.models.generate_content.return_value = response

        raw = processor._call_gemini(b"image", "image/jpeg", "extraer")

        self.assertEqual(raw, '{"es_evento":false}')
        call = client_class.return_value.models.generate_content.call_args
        self.assertEqual(call.kwargs["model"], "gemini-3.5-flash-lite")
        config = call.kwargs["config"]
        self.assertEqual(config.thinking_config.thinking_level.value, "MINIMAL")
        self.assertIsNone(config.temperature)
        self.assertEqual(config.max_output_tokens, 2048)

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
    @patch("src.processor.genai.Client")
    def test_gemini_records_max_tokens_truncation(self, client_class):
        response = Mock()
        response.text = '{"es_evento":true'
        candidate = Mock()
        candidate.finish_reason.value = "MAX_TOKENS"
        response.candidates = [candidate]
        client_class.return_value.models.generate_content.return_value = response

        processor._call_gemini(b"image", "image/jpeg", "extraer")

        self.assertEqual(
            processor._batch_state["last_failure_reason"],
            "json_truncado",
        )

    @patch("src.processor._get_raw_json", return_value='{"es_evento":true')
    def test_invalid_json_is_queued_with_specific_reason(self, get_raw_json):
        store = Mock()
        metadata = {
            "_candidate_row": 2,
            "_candidate_attempts": 0,
            "hash": "hash",
        }
        with tempfile.NamedTemporaryFile(suffix=".jpg") as image:
            Path(image.name).write_bytes(b"fake-image")
            events = processor.process_batch(
                [(Path(image.name), metadata)],
                candidate_store=store,
            )

        self.assertEqual(events, [])
        retry_call = store.update.call_args_list[-1]
        self.assertEqual(retry_call.kwargs["status"], "reintentar")
        self.assertEqual(retry_call.kwargs["reason"], "json_invalido")

    @patch.dict(os.environ, {"MAX_CLAUDE_CALLS_PER_RUN": "1"})
    @patch("src.processor._call_claude")
    def test_claude_call_limit_prevents_unbounded_fallback_cost(self, call_claude):
        processor._batch_state.update({
            "gemini_exhausted": True,
            "claude_exhausted": False,
            "claude_calls": 1,
        })

        raw = processor._get_raw_json(
            Path("image.jpg"),
            b"image",
            "image/jpeg",
            "extraer",
        )

        self.assertIsNone(raw)
        self.assertTrue(processor._batch_state["claude_exhausted"])
        call_claude.assert_not_called()

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

    def test_validate_event_rejects_inferred_year(self):
        event = processor.validate_event_data(
            {
                "nombre": "Taller sin año visible",
                "fecha_inicio": "24/11/2026",
                "pais": "Argentina",
                "provincia": "Córdoba",
                "anio_confirmado": False,
            },
            today=date(2026, 7, 28),
        )

        self.assertFalse(event["activo"])

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

    @patch(
        "src.processor.fetch_caption",
        return_value=(
            "Fecha de publicación indexada: hace 9 meses\n"
            "Taller del 24 al 30 de noviembre"
        ),
    )
    @patch("src.processor._get_raw_json")
    def test_missing_year_uses_indexed_publication_context(
        self,
        get_raw_json,
        fetch_caption,
    ):
        get_raw_json.side_effect = [
            (
                '{"es_evento":true,"nombre":"Taller","fecha_inicio":null,'
                '"fecha_fin":null,"anio_confirmado":false,'
                '"es_virtual":false,"provincia":"Córdoba",'
                '"pais":"Argentina","confianza":"media"}'
            ),
            (
                '{"es_evento":true,"nombre":"Taller","fecha_inicio":"24/11/2025",'
                '"fecha_fin":"30/11/2025","anio_confirmado":true,'
                '"es_virtual":false,"provincia":"Córdoba",'
                '"pais":"Argentina","confianza":"alta"}'
            ),
        ]
        with tempfile.NamedTemporaryFile(suffix=".jpg") as image:
            Path(image.name).write_bytes(b"fake-image")
            event = processor.extract_event_data(
                Path(image.name),
                {
                    "caption": "Fecha: 24 al 30 de noviembre",
                    "link": "https://instagram.com/p/evento",
                },
            )

        fetch_caption.assert_called_once()
        second_prompt = get_raw_json.call_args_list[1].args[3]
        self.assertIn("Fecha: 24 al 30 de noviembre", second_prompt)
        self.assertIn("hace 9 meses", second_prompt)
        self.assertEqual(event["fecha_inicio_iso"], "2025-11-24")
        self.assertFalse(event["activo"])


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

    @patch("src.email_intake.mark_row")
    @patch("src.email_intake.extract_event_data", return_value=email_intake.RETRY)
    @patch("src.email_intake.download_drive_image", return_value=True)
    @patch("src.email_intake.load_pending_rows")
    @patch("src.email_intake.get_service", return_value=Mock())
    def test_provider_failure_marks_retry_and_fails_workflow(
        self,
        get_service,
        load_pending_rows,
        download_drive_image,
        extract_event_data,
        mark_row,
    ):
        load_pending_rows.return_value = [{
            "sheet_row": 2,
            "remitente": "organizador@example.com",
            "asunto": "Evento",
            "codigo": "",
            "cuerpo": "Datos del evento",
            "imagen_url": "https://example.com/image.png",
            "timestamp": "2026-07-27",
        }]

        with self.assertRaisesRegex(RuntimeError, "quedaron para reintentar"):
            email_intake.process_queue()

        mark_row.assert_called_once_with(get_service.return_value, 2, "reintentar")


if __name__ == "__main__":
    unittest.main()
