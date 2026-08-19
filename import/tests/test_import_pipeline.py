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

    def test_validate_event_detects_country_from_phone_prefix(self):
        event = processor.validate_event_data(
            {"nombre": "Taller de bioconstrucción", "fecha_inicio": "10/08/2026",
             "provincia": None, "direccion": None,
             "contacto": "+52 55 1234 5678", "pais": None},
            today=date(2026, 7, 20),
        )
        self.assertEqual(event["pais"], "México")

    def test_validate_event_accepts_00_prefix_for_phone_country(self):
        event = processor.validate_event_data(
            {"nombre": "Taller", "fecha_inicio": "10/08/2026",
             "provincia": None, "direccion": None,
             "contacto": "0051 987 654 321", "pais": None},
            today=date(2026, 7, 20),
        )
        self.assertEqual(event["pais"], "Perú")

    def test_validate_event_does_not_flag_argentina_phone_prefix(self):
        # +549... es el formato de celular argentino (9 = móvil), no un
        # código de país distinto.
        event = processor.validate_event_data(
            {"nombre": "Taller", "fecha_inicio": "10/08/2026",
             "provincia": None, "direccion": None,
             "contacto": "+54 9 11 1234-5678", "pais": None},
            today=date(2026, 7, 20),
        )
        self.assertFalse(event.get("pais"))

    def test_validate_event_ignores_phone_without_international_prefix(self):
        # Sin "+" ni "00" no hay forma de saber el país desde el número —
        # un teléfono local argentino ("11 4444-5555") no dice nada, y no
        # se adivina para evitar falsos positivos.
        event = processor.validate_event_data(
            {"nombre": "Taller", "fecha_inicio": "10/08/2026",
             "provincia": None, "direccion": None,
             "contacto": "11 4444-5555", "pais": None},
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


class CuentasPaisTests(unittest.TestCase):
    """PaisTelefono en CuentasIds: señal de país del perfil de Instagram
    (public_phone_country_code), cacheada junto al user_id."""

    @patch("src.sheets.get_or_create_sheet_with_headers")
    def test_cargar_cuentas_pais_ignora_filas_sin_pais(self, get_or_create):
        service = Mock()
        service.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
            "values": [
                ["cuenta_ar", "111", ""],
                ["cuenta_mx", "222", "México"],
                ["cuenta_sin_pais"],
            ]
        }
        out = sheets.cargar_cuentas_pais(service)
        self.assertEqual(out, {"cuenta_mx": "México"})

    def test_guardar_cuentas_ids_incluye_pais_cuando_se_pasa(self):
        service = Mock()
        sheets.guardar_cuentas_ids(service, {"cuenta_mx": 222}, {"cuenta_mx": "México"})
        body = service.spreadsheets.return_value.values.return_value.append.call_args.kwargs["body"]
        self.assertEqual(body["values"], [["cuenta_mx", "222", "México"]])

    def test_guardar_cuentas_ids_sin_pais_deja_columna_vacia(self):
        service = Mock()
        sheets.guardar_cuentas_ids(service, {"cuenta_ar": 111})
        body = service.spreadsheets.return_value.values.return_value.append.call_args.kwargs["body"]
        self.assertEqual(body["values"], [["cuenta_ar", "111", ""]])

    @patch("src.hiker_pipeline.requests.get")
    @patch.dict(os.environ, {"HIKERAPI_KEY": "test-key"})
    def test_resolver_user_id_y_pais_detecta_pais_no_argentina(self, get):
        from src import hiker_pipeline

        get.return_value = Mock(status_code=200, json=lambda: {
            "pk": 999, "public_phone_country_code": "52",
        })

        user_id, pais = hiker_pipeline.resolver_user_id_y_pais("cuenta_mx")

        self.assertEqual(user_id, 999)
        self.assertEqual(pais, "México")

    @patch("src.hiker_pipeline.requests.get")
    @patch.dict(os.environ, {"HIKERAPI_KEY": "test-key"})
    def test_resolver_user_id_y_pais_no_marca_argentina(self, get):
        from src import hiker_pipeline

        get.return_value = Mock(status_code=200, json=lambda: {
            "pk": 111, "public_phone_country_code": "54",
        })

        user_id, pais = hiker_pipeline.resolver_user_id_y_pais("cuenta_ar")

        self.assertEqual(user_id, 111)
        self.assertEqual(pais, "")

    @patch("src.hiker_pipeline.subir_imagen_a_drive")
    @patch("src.hiker_pipeline._download_image", return_value=False)
    @patch("src.hiker_pipeline.extraer_evento")
    def test_procesar_post_usa_pais_de_cuenta_como_ultimo_recurso(
        self, extraer_evento, download_image, subir_imagen,
    ):
        from src import hiker_pipeline

        extraer_evento.return_value = {
            "es_evento": True, "nombre": "Taller de Bioconstrucción",
            "fecha_inicio": "10/12/2026", "provincia": None,
            "direccion": None, "contacto": None, "pais": None,
            "confianza": "alta",
        }
        post = {"link": "https://www.instagram.com/p/AAA111/", "image_url": "https://x.test/i.jpg",
                "caption": "Taller de bioconstrucción con barro", "username": "cuenta_mx"}

        evento = hiker_pipeline.procesar_post(post, set(), pais_cuenta="México")

        self.assertIsNone(evento)  # se descarta por no-argentino, pero no explota

    @patch("src.hiker_pipeline.subir_imagen_a_drive")
    @patch("src.hiker_pipeline._download_image", return_value=False)
    @patch("src.hiker_pipeline.extraer_evento")
    def test_procesar_post_no_pisa_pais_ya_detectado_por_el_flyer(
        self, extraer_evento, download_image, subir_imagen,
    ):
        from src import hiker_pipeline

        extraer_evento.return_value = {
            "es_evento": True, "nombre": "Taller de Bioconstrucción",
            "fecha_inicio": "10/12/2026", "provincia": "Córdoba",
            "direccion": None, "contacto": None, "pais": None,
            "confianza": "alta",
        }
        post = {"link": "https://www.instagram.com/p/BBB222/", "image_url": "https://x.test/i.jpg",
                "caption": "Taller de bioconstrucción con barro en Córdoba", "username": "cuenta_mx"}

        # pais_cuenta dice México, pero la provincia del flyer (Córdoba,
        # Argentina) ya resolvió el país — la cuenta no debe pisarlo.
        evento = hiker_pipeline.procesar_post(post, set(), pais_cuenta="México")

        self.assertIsNotNone(evento)
        self.assertEqual(evento["pais"], "Argentina")


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

    def test_incluye_llamadas_a_hikerapi(self):
        mensaje = self._mensaje(
            resumen={"eventos_insertados": 1, "llamadas_hikerapi": 187},
        )
        self.assertIn("Llamadas a HikerAPI: 187", mensaje)

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


class HikerApiCostTests(unittest.TestCase):
    """Costo de HikerAPI por corrida — recomendación #3 de ESTADO.md, sin
    número real en los logs hasta ahora. _hiker_get() es el único punto por
    el que pasan las llamadas pagas."""

    @patch("src.hiker_pipeline.requests.get")
    @patch.dict(os.environ, {"HIKERAPI_KEY": "test-key"})
    def test_hiker_get_cuenta_cada_llamada(self, get):
        from src import hiker_pipeline

        hiker_pipeline._llamadas_hikerapi[0] = 0
        hiker_pipeline._hiker_get("https://api.hikerapi.com/v1/algo")
        hiker_pipeline._hiker_get("https://api.hikerapi.com/v1/otra")

        self.assertEqual(hiker_pipeline._llamadas_hikerapi[0], 2)
        self.assertEqual(get.call_count, 2)

    @patch("src.hiker_pipeline.requests.get")
    @patch.dict(os.environ, {"HIKERAPI_KEY": "test-key"})
    def test_hiker_get_no_cuenta_la_descarga_de_imagen(self, get):
        # _download_image usa requests.get directo (no _hiker_get) porque
        # baja bytes de una URL ya resuelta, no es una llamada a la API.
        from src import hiker_pipeline

        hiker_pipeline._llamadas_hikerapi[0] = 0
        get.return_value = Mock(status_code=200, content=b"x" * 2000)
        with tempfile.TemporaryDirectory() as tmp:
            hiker_pipeline._download_image("https://cdn.example.com/img.jpg", Path(tmp) / "x.jpg")

        self.assertEqual(hiker_pipeline._llamadas_hikerapi[0], 0)


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


class CandidatosTecnicasTests(unittest.TestCase):
    """Igual que CandidatosHashtagsTests: solo lee la hoja (mockeada acá),
    no toca HikerAPI ni ningún proveedor de IA."""

    def _fila(self, nombre="", descripcion="", estado="confirmado"):
        from src.sheets import COLUMNS
        fila = [""] * len(COLUMNS)
        fila[1] = nombre
        fila[8] = descripcion
        fila[16] = estado
        return fila

    def _analizar_con(self, filas):
        from src import candidatos_tecnicas

        service = Mock()
        service.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
            "values": filas
        }
        return candidatos_tecnicas.analizar(service=service)

    def test_solo_cuenta_eventos_confirmados(self):
        candidatos, _ = self._analizar_con([
            self._fila(nombre="Taller de quincha"),
            self._fila(nombre="Taller de quincha", estado="descartado"),
            self._fila(nombre="Taller de quincha", estado="pendiente_confirmacion"),
        ])
        self.assertEqual(candidatos, [("quincha", 1)])

    def test_no_cuenta_dos_veces_la_misma_tecnica_en_un_evento(self):
        # nombre y descripción mencionan lo mismo: es UN evento, no dos.
        candidatos, _ = self._analizar_con([
            self._fila(nombre="Taller de quincha",
                       descripcion="Aprendemos quincha con técnica de quincha liviana"),
        ])
        self.assertEqual(candidatos, [("quincha", 1)])

    def test_agrupa_sinonimos_bajo_la_tecnica_canonica(self):
        candidatos, _ = self._analizar_con([
            self._fila(nombre="Curso de cubiertas vivas"),
            self._fila(nombre="Taller de techo verde"),
        ])
        self.assertEqual(candidatos, [("techo verde", 2)])

    def test_no_descarta_tecnicas_de_un_solo_evento(self):
        """A diferencia de candidatos_hashtags (donde frecuencia 1 = ruido),
        una técnica que aparece una vez es real, solo tiene poca oferta.
        Filtrarla borraría del vocabulario justo lo más específico."""
        candidatos, _ = self._analizar_con([
            self._fila(nombre="Curso de superadobe"),
        ])
        self.assertEqual(candidatos, [("superadobe", 1)])

    def test_ignora_el_nombre_del_rubro_como_si_fuera_tecnica(self):
        candidatos, _ = self._analizar_con([
            self._fila(nombre="Taller de Bioconstrucción",
                       descripcion="Introducción a la bioarquitectura"),
        ])
        self.assertEqual(candidatos, [])

    def test_matchea_tipografia_fancy_de_instagram(self):
        # Los títulos gritados del feed vienen en unicode matemático.
        candidatos, _ = self._analizar_con([
            self._fila(nombre="𝗧𝗔𝗟𝗟𝗘𝗥 𝗗𝗘 𝗤𝗨𝗜𝗡𝗖𝗛𝗔"),
        ])
        self.assertEqual(candidatos, [("quincha", 1)])

    def test_reporta_eventos_sin_tecnica_para_descubrir_vocabulario(self):
        _, sin_clasificar = self._analizar_con([
            self._fila(nombre="Taller de quincha"),
            self._fila(nombre="Geometrías Orgánicas en Techos"),
        ])
        self.assertEqual(sin_clasificar, ["Geometrías Orgánicas en Techos"])


class UsernameColumnTests(unittest.TestCase):
    """El username de la cuenta de origen ya venía en la respuesta de HikerAPI
    y solo vivía en memoria (filtro de cuentas_excluidas). Persistirlo no cuesta
    ninguna llamada extra y es lo que permite contactar al organizador."""

    def test_event_to_row_guarda_el_username_normalizado(self):
        fila = sheets.event_to_row({"nombre": "Taller", "username": "@ElAbrazal"})
        self.assertEqual(len(fila), len(sheets.COLUMNS))
        self.assertEqual(fila[-1], "elabrazal")

    def test_event_to_row_sin_username_deja_la_celda_vacia(self):
        # Los eventos que entran por mail o formulario no tienen cuenta de origen.
        fila = sheets.event_to_row({"nombre": "Taller"})
        self.assertEqual(fila[-1], "")

    def test_username_es_la_ultima_columna(self):
        # Va al final a propósito: mover posiciones existentes rompe al
        # frontend, que lee por GViz (ver PATRONES.md).
        self.assertEqual(sheets.COLUMNS[-1], "Username")

    def test_procesar_post_propaga_el_username_del_post(self):
        from src import hiker_pipeline
        post = {
            "link": "https://www.instagram.com/p/ABC123/",
            "image_url": "https://x/i.jpg", "caption": "taller de barro en Cordoba",
            "taken_at_ts": None, "username": "elabrazal",
        }
        with patch.object(hiker_pipeline, "extraer_evento",
                          return_value={"es_evento": True, "nombre": "Taller",
                                        "provincia": "Córdoba", "confianza": "alta"}), \
             patch.object(hiker_pipeline, "subir_imagen_a_drive", return_value=None):
            evento = hiker_pipeline.procesar_post(post, set())
        self.assertEqual(evento["username"], "elabrazal")


class DuplicadoPorCuentaTests(unittest.TestCase):
    """Cuarta señal de find_probable_duplicate: misma cuenta de Instagram +
    nombre prácticamente idéntico, sin importar fecha ni provincia. Cubre el
    caso que las otras no ven — el mismo organizador promocionando lo mismo
    con la fecha extraída distinta."""

    def _existente(self, nombre, username="", provincia="", fecha=""):
        return {"id": "abc123", "nombre": nombre, "username": username,
                "provincia": provincia, "fecha_inicio_iso": fecha}

    def test_misma_cuenta_y_mismo_nombre_con_fechas_lejanas(self):
        # Caso real: @aulaabierta.ambiente con el mismo curso cargado dos
        # veces, fechas separadas por meses y una fila sin provincia. Las
        # tres señales anteriores lo dejaban pasar.
        existentes = [self._existente(
            "Curso Universitario: Diseño y Construcción de Techos y Cubiertas Vivas",
            username="aulaabierta.ambiente", provincia="Córdoba", fecha="2026-08-05")]
        evento = {
            "nombre": "Curso Universitario: Diseño y Construcción de Techos y Cubiertas Vivas",
            "username": "aulaabierta.ambiente", "provincia": "", "fecha_inicio_iso": "2026-10-26",
        }
        self.assertIsNotNone(sheets.find_probable_duplicate(evento, existentes))

    def test_no_marca_ediciones_distintas_del_mismo_taller(self):
        """El riesgo de esta señal: en este rubro es habitual dictar el mismo
        curso por módulos o varias veces al año. Matarlos sería peor que el
        duplicado que se quiere evitar."""
        existentes = [self._existente("Taller de Wood Frame", username="latinyscom")]
        evento = {"nombre": "Taller Construir en Madera y Wood Frame Módulo II",
                  "username": "latinyscom", "provincia": "", "fecha_inicio_iso": "2026-09-01"}
        self.assertIsNone(sheets.find_probable_duplicate(evento, existentes))

    def test_distinta_cuenta_con_mismo_nombre_no_alcanza(self):
        # Sin la cuenta en común vuelve a hacer falta provincia + fecha
        # cercana, que es la señal vieja.
        existentes = [self._existente("Taller de quincha liviana",
                                      username="cuenta_a", provincia="Córdoba",
                                      fecha="2026-08-05")]
        evento = {"nombre": "Taller de quincha liviana", "username": "cuenta_b",
                  "provincia": "", "fecha_inicio_iso": "2026-12-20"}
        self.assertIsNone(sheets.find_probable_duplicate(evento, existentes))

    def test_sin_username_sigue_valiendo_la_senal_vieja(self):
        # Los eventos que entran por mail o formulario no tienen cuenta de
        # origen: la señal de provincia + fecha cercana tiene que seguir viva.
        existentes = [self._existente("Taller de quincha liviana", username="",
                                      provincia="Córdoba", fecha="2026-08-05")]
        evento = {"nombre": "Jornada de quincha liviana", "username": "",
                  "provincia": "Córdoba", "fecha_inicio_iso": "2026-08-08"}
        self.assertIsNotNone(sheets.find_probable_duplicate(evento, existentes))


class GeocodificarTests(unittest.TestCase):
    """Sin red: se mockea la consulta a Nominatim. La regla que fijan estos
    tests es 'ante la duda, None' — sin coordenadas el mapa cae al centroide
    de la provincia, que es honesto; un pin en el lugar equivocado no."""

    def _resultado(self, lat, lon, state="Córdoba", addresstype="town"):
        return {"lat": str(lat), "lon": str(lon), "addresstype": addresstype,
                "display_name": "x", "address": {"state": state}}

    def _con_respuestas(self, respuestas):
        from src import geocodificar
        return patch.object(geocodificar, "_consultar_nominatim",
                            side_effect=list(respuestas))

    def test_direccion_virtual_no_consulta_nada(self):
        from src import geocodificar
        with patch.object(geocodificar, "_consultar_nominatim") as consulta:
            self.assertIsNone(geocodificar.geocodificar_direccion(
                "meet.google.com/ujb-zeog-ufe", ""))
            consulta.assert_not_called()

    def test_descarta_resultado_fuera_de_argentina(self):
        from src import geocodificar
        # Madrid: coordenadas válidas pero de otro continente.
        with self._con_respuestas([[self._resultado(40.41, -3.70, state="Madrid")], [], []]):
            self.assertIsNone(geocodificar.geocodificar_direccion("Belgrano 123", "Córdoba"))

    def test_descarta_resultado_a_nivel_provincia(self):
        """Caso real: 'El Hoyo, Comarca Andina, Chubut' resolvía al centro de
        Chubut, a 400 km del pueblo. Eso no es una ubicación, es el centroide
        que el frontend ya calcula solo — escribirlo finge una precisión que
        no existe."""
        from src import geocodificar
        with self._con_respuestas([
            [self._resultado(-45.58, -69.05, state="Chubut", addresstype="state")],
            [], [],
        ]):
            self.assertIsNone(geocodificar.geocodificar_direccion("El Hoyo", "Chubut"))

    def test_descarta_resultado_en_otra_provincia(self):
        # Los topónimos repetidos son moneda corriente acá (San Martín,
        # Belgrano, Rivadavia): sin este chequeo el pin se va a 1000 km.
        from src import geocodificar
        with self._con_respuestas([
            [self._resultado(-34.60, -58.38, state="Buenos Aires")], [], [],
        ]):
            self.assertIsNone(geocodificar.geocodificar_direccion("San Martín", "Córdoba"))

    def test_cae_a_tramos_mas_cortos_si_la_direccion_completa_no_resuelve(self):
        """El flyer arranca con el nombre del salón, que Nominatim no conoce.
        Sacando ese tramo queda la localidad, que sí resuelve."""
        from src import geocodificar
        with self._con_respuestas([[], [self._resultado(-30.78, -64.63)]]):
            punto = geocodificar.geocodificar_direccion(
                "Ecoescuela Tay Pichín, San Marcos Sierras", "Córdoba")
        self.assertEqual(punto, (-30.78, -64.63))

    def test_no_gasta_intentos_en_la_provincia_ni_el_pais(self):
        from src import geocodificar
        variantes = geocodificar._variantes("El Hoyo, Comarca Andina, Chubut, Argentina", "Chubut")
        self.assertNotIn("Chubut", variantes)
        self.assertNotIn("Argentina", variantes)
        self.assertIn("El Hoyo", variantes)


class ContenidoInstagramTests(unittest.TestCase):
    """La cola de Instagram cuelga de un cron que corre cada 3 horas, así que
    lo que más importa es que sea idempotente: correrla de nuevo no puede
    duplicar piezas."""

    def _evento(self, id="ev1", nombre="Taller de quincha", username="elabrazal",
                estado="confirmado", virtual=False):
        from datetime import date
        return {"id": id, "nombre": nombre, "username": username, "estado": estado,
                "fecha": date(2026, 9, 15), "provincia": "Córdoba",
                "es_virtual": virtual, "link": "https://instagram.com/p/AAA/",
                "imagen": "https://drive/x", "tipo_evento": "Taller"}

    def _generar(self, eventos, claves_existentes=(), organizadores=()):
        from datetime import date
        from src import contenido_instagram
        service = Mock()
        (service.spreadsheets.return_value.values.return_value.get
         .return_value.execute.return_value) = {"values": [[c] for c in claves_existentes]}
        with patch.object(contenido_instagram, "proximos_eventos", return_value=eventos), \
             patch.object(contenido_instagram, "organizadores_a_invitar",
                          return_value=list(organizadores)), \
             patch.object(contenido_instagram, "get_or_create_sheet_with_headers"):
            n = contenido_instagram.generar(service=service, hoy=date(2026, 8, 18))
        append = service.spreadsheets.return_value.values.return_value.append
        filas = append.call_args.kwargs["body"]["values"] if append.called else []
        return n, filas

    def test_genera_una_historia_por_evento_mas_el_carrusel(self):
        n, filas = self._generar([self._evento()])
        self.assertEqual(n, 2)
        self.assertEqual([f[2] for f in filas], ["historia_evento", "carrusel_semanal"])

    def test_no_repite_lo_que_ya_esta_en_la_cola(self):
        n, _ = self._generar([self._evento()],
                             claves_existentes=["historia:ev1", "carrusel:2026-W34"])
        self.assertEqual(n, 0)

    def test_saltea_la_pieza_aunque_ya_este_publicada_o_descartada(self):
        # El generador mira solo la Clave, no el Estado: una fila publicada o
        # descartada tiene que seguir bloqueando la regeneración. Por eso las
        # filas se descartan y no se borran.
        n, _ = self._generar([self._evento()], claves_existentes=["historia:ev1"])
        self.assertEqual([f[2] for f in _], ["carrusel_semanal"])
        self.assertEqual(n, 1)

    def test_ignora_eventos_sin_confirmar(self):
        """Mientras REVISION_MANUAL esté en true todo entra como pendiente:
        promocionar algo sin revisar sería peor que no promocionar nada."""
        n, _ = self._generar([self._evento(estado="pendiente_confirmacion")])
        self.assertEqual(n, 0)

    def test_la_historia_incluye_la_mencion_a_la_cuenta_de_origen(self):
        _, filas = self._generar([self._evento()])
        self.assertEqual(filas[0][5], "@elabrazal")
        self.assertIn("@elabrazal", filas[0][8])

    def test_evento_sin_cuenta_de_origen_no_inventa_mencion(self):
        # Los eventos cargados por mail o formulario no tienen cuenta.
        _, filas = self._generar([self._evento(username="")])
        self.assertEqual(filas[0][5], "")
        self.assertNotIn("@", filas[0][8])

    def test_encola_un_dm_por_cuenta_organizadora(self):
        _, filas = self._generar(
            [], organizadores=[{"usuario": "elabrazal", "eventos": 3, "mensaje": "Hola!"}])
        self.assertEqual([f[2] for f in filas], ["dm_organizador"])
        self.assertEqual(filas[0][5], "@elabrazal")
        self.assertEqual(filas[0][0], "dm:elabrazal")

    def test_no_le_escribe_dos_veces_a_la_misma_cuenta(self):
        # La clave del DM no lleva el evento: es una invitación por cuenta,
        # no una por cada taller que suban.
        n, _ = self._generar(
            [], claves_existentes=["dm:elabrazal"],
            organizadores=[{"usuario": "elabrazal", "eventos": 3, "mensaje": "Hola!"}])
        self.assertEqual(n, 0)

    def test_los_dm_se_ordenan_por_cuanto_aporto_cada_cuenta(self):
        _, filas = self._generar([], organizadores=[
            {"usuario": "poco", "eventos": 1, "mensaje": "x"},
            {"usuario": "mucho", "eventos": 7, "mensaje": "x"},
        ])
        # Fecha_Evento se usa como orden: la cuenta con más eventos va antes.
        self.assertLess(
            [f for f in filas if f[5] == "@mucho"][0][3],
            [f for f in filas if f[5] == "@poco"][0][3],
        )

    def test_el_caption_del_carrusel_lleva_el_recordatorio_de_como_aportar(self):
        _, filas = self._generar([self._evento()])
        self.assertIn("#hayminga", filas[1][8])
        self.assertIn("hayminga.org", filas[1][8])


if __name__ == "__main__":
    unittest.main()
