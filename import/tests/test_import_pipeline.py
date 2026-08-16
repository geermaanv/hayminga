import json
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

    def test_validate_event_detects_foreign_country_when_model_left_it_empty(self):
        # Caso real: un evento en CDMX con `pais` vacío (el modelo no lo
        # infirió) pasaba el filtro de hiker_pipeline.py que solo descarta
        # cuando `pais` está explícitamente seteado y no es Argentina.
        event = processor.validate_event_data(
            {
                "nombre": "Taller de bioconstrucción",
                "fecha_inicio": "27/07/2026",
                "provincia": None,
                "direccion": "Barrio de Coyoacán, Ciudad de México",
                "pais": None,
                "confianza": "alta",
            },
            today=date(2026, 7, 20),
        )

        self.assertEqual(event["pais"], "México")
        self.assertFalse(event["activo"])

    def test_validate_event_detects_country_name_in_direccion(self):
        event = processor.validate_event_data(
            {"nombre": "Curso", "fecha_inicio": "10/08/2026",
             "provincia": None, "direccion": "Finca rural, Colombia", "pais": None},
            today=date(2026, 7, 20),
        )
        self.assertEqual(event["pais"], "Colombia")

    def test_validate_event_does_not_flag_argentina_events_as_foreign(self):
        # El caso que más importa no romper: un evento real de Argentina no
        # debe quedar marcado como extranjero por una coincidencia de texto.
        # Santiago del Estero es justamente el caso adversarial (contiene
        # "Santiago", una de las ciudades ambiguas que la heurística evita
        # a propósito por esto mismo).
        event = processor.validate_event_data(
            {
                "nombre": "Minga de adobe",
                "fecha_inicio": "15/08/2026",
                "provincia": "Santiago del Estero",
                "direccion": "Ruta 9, Santiago del Estero",
                "pais": None,
                "confianza": "alta",
            },
            today=date(2026, 7, 20),
        )
        self.assertEqual(event["pais"], "Argentina")
        self.assertEqual(event["provincia"], "Santiago del Estero")

    def test_validate_event_does_not_override_explicit_pais(self):
        # Si el modelo ya dijo Argentina (aunque la provincia no matcheara,
        # ej. un typo), la heurística de texto no debe pisarlo.
        event = processor.validate_event_data(
            {"nombre": "Evento", "fecha_inicio": "10/08/2026",
             "provincia": "Buenos Aires (typo raro)", "direccion": "Chile 890",
             "pais": "Argentina"},
            today=date(2026, 7, 20),
        )
        self.assertEqual(event["pais"], "Argentina")

    def test_validate_event_does_not_flag_street_address_as_foreign_country(self):
        # Perú, Chile, México, Venezuela son calles reales del microcentro
        # porteño (San Telmo/Monserrat) — un evento en "Perú 1234" no puede
        # tratarse como si fuera de Perú. La guarda: si la palabra va
        # seguida de un número (patrón de dirección), no cuenta como país.
        event = processor.validate_event_data(
            {"nombre": "Feria de bioconstrucción", "fecha_inicio": "10/08/2026",
             "provincia": None, "direccion": "Perú 1234, San Telmo", "pais": None},
            today=date(2026, 7, 20),
        )
        self.assertFalse(event.get("pais"))

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

    def test_virtual_event_without_date_gets_import_date(self):
        event = processor.validate_event_data(
            {
                "nombre": "Curso online de inscripción continua",
                "fecha_inicio": None,
                "fecha_fin": None,
                "es_virtual": True,
                "pais": "Argentina",
                "anio_confirmado": False,
            },
            today=date(2026, 8, 15),
        )

        self.assertEqual(event["fecha_inicio_iso"], "2026-08-15")
        self.assertEqual(event["periodo"], "2026-08")
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

    def test_find_probable_duplicate_detects_repost_with_different_wording(self):
        # Caso real que motiva esto: mismo curso, dos posteos de Instagram
        # distintos, título reformulado en cada uno.
        existentes = [{
            "key": sheets.event_dedupe_key({
                "nombre": "Formación Práctica en Arquitectura Biológica",
                "fecha_inicio_iso": "2026-09-05", "provincia": "Córdoba",
            }),
            "id": "abc123",
            "nombre": "Formación Práctica en Arquitectura Biológica",
            "provincia": "Córdoba",
            "fecha_inicio_iso": "2026-09-05",
        }]
        nuevo = {
            "nombre": "Formación en Arquitectura Biológica y Bioconstrucción",
            "fecha_inicio_iso": "2026-09-08",
            "provincia": "Córdoba",
        }

        probable = sheets.find_probable_duplicate(nuevo, existentes)

        self.assertIsNotNone(probable)
        self.assertEqual(probable["id"], "abc123")

    def test_find_probable_duplicate_requires_same_provincia(self):
        existentes = [{
            "key": "x", "id": "1", "nombre": "Taller Intensivo de Superadobe",
            "provincia": "Córdoba", "fecha_inicio_iso": "2026-09-05",
        }]
        nuevo = {
            "nombre": "Taller Intensivo de Superadobe",
            "fecha_inicio_iso": "2026-09-06",
            "provincia": "Mendoza",
        }

        self.assertIsNone(sheets.find_probable_duplicate(nuevo, existentes))

    def test_find_probable_duplicate_requires_date_within_window(self):
        # Mismo nombre/provincia pero separados por meses: más probable que
        # sea una edición anual repetida que un repost del mismo evento.
        existentes = [{
            "key": "x", "id": "1", "nombre": "Encuentro de Bioconstructores",
            "provincia": "Córdoba", "fecha_inicio_iso": "2026-03-05",
        }]
        nuevo = {
            "nombre": "Encuentro de Bioconstructores",
            "fecha_inicio_iso": "2026-09-05",
            "provincia": "Córdoba",
        }

        self.assertIsNone(sheets.find_probable_duplicate(nuevo, existentes))

    def test_find_probable_duplicate_ignores_generic_shared_words(self):
        # Dos talleres reales, distintos, que solo comparten vocabulario
        # genérico del rubro no deben flaggearse como duplicados.
        existentes = [{
            "key": "x", "id": "1", "nombre": "Taller de Bioconstrucción Natural",
            "provincia": "Córdoba", "fecha_inicio_iso": "2026-09-05",
        }]
        nuevo = {
            "nombre": "Taller de Bioconstrucción con Adobe",
            "fecha_inicio_iso": "2026-09-07",
            "provincia": "Córdoba",
        }

        self.assertIsNone(sheets.find_probable_duplicate(nuevo, existentes))

    def test_find_probable_duplicate_known_limitation_shared_venue_name(self):
        # Límite conocido y ACEPTADO, no un bug: dos eventos DISTINTOS en el
        # mismo lugar conocido (San Marcos Sierras, recurrente en el Sheet
        # real — ver Etapa 9.7) pueden compartir tokens del nombre del lugar
        # y activar un falso positivo. Se acepta a propósito porque el costo
        # de errar acá es bajo: nunca se descarta un evento, solo se manda a
        # revisión — Germán aprueba los dos reales en un click en
        # ?pendientes. Si esto genera ruido en la práctica, subir
        # _RATIO_MINIMO_NOMBRE o excluir nombres de lugar conocidos de los
        # tokens contados.
        existentes = [{
            "key": "x", "id": "1",
            "nombre": "Curso de Permacultura y Diseño en San Marcos Sierras",
            "provincia": "Córdoba", "fecha_inicio_iso": "2026-09-05",
        }]
        nuevo = {
            "nombre": "Taller de Bioconstrucción y Permacultura en San Marcos Sierras",
            "fecha_inicio_iso": "2026-09-08",
            "provincia": "Córdoba",
        }

        self.assertIsNotNone(sheets.find_probable_duplicate(nuevo, existentes))

    @patch("src.sheets.ensure_header")
    @patch("src.sheets.load_processed_events")
    @patch("src.sheets.get_service")
    def test_append_events_flags_probable_duplicate_for_review(
        self, get_service, load_processed_events, ensure_header,
    ):
        load_processed_events.return_value = [{
            "key": sheets.event_dedupe_key({
                "nombre": "Formación Práctica en Arquitectura Biológica",
                "fecha_inicio_iso": "2026-09-05", "provincia": "Córdoba",
            }),
            "shortcode": "AAA111", "id": "abc123",
            "nombre": "Formación Práctica en Arquitectura Biológica",
            "provincia": "Córdoba", "fecha_inicio_iso": "2026-09-05",
        }]
        service = get_service.return_value

        sheets.append_events([{
            "nombre": "Formación en Arquitectura Biológica y Bioconstrucción",
            "fecha_inicio_iso": "2026-09-08", "provincia": "Córdoba",
            "activo": True, "link_promocional": "https://www.instagram.com/p/BBB222/",
        }])

        fila_escrita = service.spreadsheets.return_value.values.return_value.append.call_args.kwargs["body"]["values"][0]
        self.assertEqual(fila_escrita[0], "false")  # Activo
        self.assertEqual(fila_escrita[16], "pendiente_confirmacion")  # Estado
        self.assertIn("abc123", fila_escrita[8])  # Descripción menciona el id existente

    @patch("src.sheets.ensure_header")
    @patch("src.sheets.load_processed_events", return_value=[])
    @patch("src.sheets.get_service")
    def test_append_events_does_not_flag_unrelated_events(
        self, get_service, load_processed_events, ensure_header,
    ):
        service = get_service.return_value

        sheets.append_events([{
            "nombre": "Taller de Cerámica con Barro",
            "fecha_inicio_iso": "2026-09-08", "provincia": "Salta",
            "activo": True, "link_promocional": "https://www.instagram.com/p/CCC333/",
        }])

        fila_escrita = service.spreadsheets.return_value.values.return_value.append.call_args.kwargs["body"]["values"][0]
        self.assertEqual(fila_escrita[0], "true")  # Activo sin tocar


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


class NotificarRunTests(unittest.TestCase):
    """El notificador corre con if: always(), así que lo que más importa es
    que no explote justo en el caso que tiene que avisar (run incompleto,
    Sheet caído)."""

    def _mensaje(self, estado_job="success", resumen=None, contar=None):
        from src import notificar_run

        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                if resumen is not None:
                    Path("run_summary.json").write_text(json.dumps(resumen))
                with patch.object(notificar_run, "contar_estados") as contar_mock:
                    if isinstance(contar, Exception):
                        contar_mock.side_effect = contar
                    else:
                        contar_mock.return_value = contar or (0, 0)
                    return notificar_run.armar_mensaje(estado_job)
            finally:
                os.chdir(cwd)

    def test_incluye_pendientes_y_publicados(self):
        mensaje = self._mensaje(
            resumen={"eventos_insertados": 3, "error_cuentas_seguidas": "", "atribucion": {}},
            contar=(7, 42),
        )
        self.assertIn("Eventos nuevos guardados: 3", mensaje)
        self.assertIn("Pendientes de confirmar: 7", mensaje)
        self.assertIn("Publicados (activos): 42", mensaje)
        self.assertIn("?pendientes", mensaje)

    def test_reporta_caida_de_cuentas_seguidas(self):
        mensaje = self._mensaje(
            resumen={"eventos_insertados": 0, "error_cuentas_seguidas": "EOF occurred in violation of protocol"},
            contar=(1, 10),
        )
        self.assertIn("cuentas seguidas CAYÓ", mensaje)

    def test_sin_resumen_avisa_corrida_incompleta(self):
        # Caso timeout/cancelación: el pipeline nunca escribió run_summary.json.
        mensaje = self._mensaje(estado_job="cancelled", resumen=None, contar=(2, 10))
        self.assertIn("no llegó a terminar", mensaje)
        self.assertIn("cancelled", mensaje)

    def test_error_contando_no_rompe_el_aviso(self):
        mensaje = self._mensaje(
            resumen={"eventos_insertados": 1},
            contar=RuntimeError("sheet caído"),
        )
        self.assertIn("Eventos nuevos guardados: 1", mensaje)
        self.assertIn("No se pudieron contar", mensaje)

    def test_incluye_atribucion_recent_vs_top(self):
        mensaje = self._mensaje(resumen={
            "eventos_insertados": 1,
            "atribucion": {"posts_recent": 700, "posts_top": 450, "top_activo": True,
                           "solo_en_recent": 300, "eventos_solo_recent": 0},
        })
        self.assertIn("eventos que aportó solo recent: 0", mensaje)

    def test_con_top_apagado_no_reporta_comparacion(self):
        # Ya no hay contra qué comparar: informar "top: 0 posts" se leería
        # como que top falló, cuando en realidad está apagado a propósito.
        mensaje = self._mensaje(resumen={
            "eventos_insertados": 1,
            "atribucion": {"posts_recent": 850, "posts_top": 0, "top_activo": False,
                           "solo_en_recent": 850, "eventos_solo_recent": 1},
        })
        self.assertIn("top apagado", mensaje)
        self.assertNotIn("recent vs top", mensaje)


class CandidatosHashtagsTests(unittest.TestCase):
    """analizar() no debe llamar a HikerAPI/Gemini/Claude — solo lee la
    hoja de Sheets (ya mockeada acá) y config.json local."""

    def _fila(self, estado="confirmado", hashtags_post=""):
        from src.sheets import COLUMNS
        fila = [""] * len(COLUMNS)
        fila[16] = estado
        fila[23] = hashtags_post
        return fila

    def _analizar_con(self, hashtags_config, filas):
        from src import candidatos_hashtags

        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                Path("config.json").write_text(json.dumps({"hashtags": hashtags_config}))
                service = Mock()
                service.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
                    "values": filas
                }
                return candidatos_hashtags.analizar(service=service)
            finally:
                os.chdir(cwd)

    def test_ignora_hashtags_ya_configurados(self):
        candidatos = self._analizar_con(
            hashtags_config=["bioconstruccion"],
            filas=[
                self._fila(hashtags_post="#bioconstruccion #tapial"),
                self._fila(hashtags_post="#bioconstruccion #tapial"),
            ],
        )
        self.assertEqual([c[0] for c in candidatos], ["tapial"])

    def test_ignora_eventos_no_confirmados(self):
        candidatos = self._analizar_con(
            hashtags_config=[],
            filas=[
                self._fila(estado="pendiente_confirmacion", hashtags_post="#quincha #quincha"),
                self._fila(estado="pendiente_confirmacion", hashtags_post="#quincha"),
            ],
        )
        self.assertEqual(candidatos, [])

    def test_requiere_minimo_de_eventos_distintos(self):
        candidatos = self._analizar_con(
            hashtags_config=[],
            filas=[self._fila(hashtags_post="#adoberos")],  # un solo evento
        )
        self.assertEqual(candidatos, [])

    def test_no_cuenta_dos_veces_el_mismo_hashtag_repetido_en_una_fila(self):
        candidatos = self._analizar_con(
            hashtags_config=[],
            filas=[
                self._fila(hashtags_post="#adoberos #adoberos #adoberos"),
                self._fila(hashtags_post="#adoberos"),
            ],
        )
        self.assertEqual(candidatos, [("adoberos", 2)])

    def test_excluye_ruido_generico(self):
        candidatos = self._analizar_con(
            hashtags_config=[],
            filas=[
                self._fila(hashtags_post="#permacultura #superadobe"),
                self._fila(hashtags_post="#permacultura #superadobe"),
            ],
        )
        self.assertEqual([c[0] for c in candidatos], ["superadobe"])

    def test_ordena_de_mas_a_menos_frecuente(self):
        candidatos = self._analizar_con(
            hashtags_config=[],
            filas=[
                self._fila(hashtags_post="#quincha"),
                self._fila(hashtags_post="#quincha"),
                self._fila(hashtags_post="#quincha #adobe"),
                self._fila(hashtags_post="#adobe"),
                self._fila(hashtags_post="#adobe"),
                self._fila(hashtags_post="#adobe"),
            ],
        )
        self.assertEqual(candidatos, [("adobe", 4), ("quincha", 3)])


if __name__ == "__main__":
    unittest.main()
