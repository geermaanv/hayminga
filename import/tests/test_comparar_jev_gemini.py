import json
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("GOOGLE_SPREADSHEET_ID", "test-sheet")

from src import comparar_jev_gemini, jev_client


class JevClientTests(unittest.TestCase):
    def test_preguntar_requires_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                jev_client.preguntar("algo", {})

    @patch("src.jev_client.requests.post")
    def test_preguntar_builds_choice_payload_and_returns_answers(self, post):
        post.return_value = Mock(
            status_code=200,
            json=Mock(return_value={"answers": {"es_evento": "si"}}),
        )
        post.return_value.raise_for_status = Mock()

        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "fake-key"}):
            respuestas = jev_client.preguntar(
                "un caption cualquiera",
                {"es_evento": {"instructions": "¿es evento?", "criteria": {"si": "sí", "no": "no"}}},
            )

        self.assertEqual(respuestas, {"es_evento": "si"})
        args, kwargs = post.call_args
        self.assertEqual(args[0], jev_client.TYPESAFE_API_URL)
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer fake-key")
        self.assertEqual(kwargs["json"]["model"], jev_client.JEV_MODEL)
        self.assertEqual(kwargs["json"]["state"], "un caption cualquiera")
        self.assertEqual(kwargs["json"]["questions"]["es_evento"]["type"], "choice")
        self.assertEqual(kwargs["timeout"], 30)


class ComparacionTests(unittest.TestCase):
    @patch("src.hiker_pipeline._call_gemini_text")
    def test_gemini_clasificar_parses_es_evento_and_confianza(self, call_gemini):
        call_gemini.return_value = json.dumps(
            {"es_evento": True, "confianza": "media", "anio_confirmado": False}
        )
        resultado = comparar_jev_gemini._gemini_clasificar("caption", "2026-09-15")
        self.assertEqual(resultado["es_evento"], "si")
        self.assertEqual(resultado["confianza"], "media")

    @patch("src.hiker_pipeline._call_gemini_text")
    def test_gemini_clasificar_reports_unparseable_json_as_error(self, call_gemini):
        call_gemini.return_value = "no es json"
        resultado = comparar_jev_gemini._gemini_clasificar("caption", "2026-09-15")
        self.assertIsNone(resultado["es_evento"])
        self.assertIn("error", resultado)

    @patch("src.jev_client.preguntar")
    def test_jev_clasificar_extracts_choice_from_nested_answer(self, preguntar):
        # La API de Jev devuelve un objeto por pregunta, no el string pelado
        # (confirmado corriendo el script real, ver ROADMAP.md) — este test
        # fija ese contrato para que nadie vuelva a asumir un string plano.
        respuestas = {
            "es_evento": {"type": "choice", "choice": "no", "confidence": 1.0, "probabilities": {"si": 0.0, "no": 1.0}},
            "confianza": {"type": "choice", "choice": "baja", "confidence": 0.84, "probabilities": {"alta": 0.0, "media": 0.11, "baja": 0.89}},
        }
        preguntar.return_value = respuestas
        resultado = comparar_jev_gemini._jev_clasificar("caption")
        self.assertEqual(resultado["es_evento"], "no")
        self.assertEqual(resultado["es_evento_confidence"], 1.0)
        self.assertEqual(resultado["confianza"], "baja")
        self.assertEqual(resultado["confianza_confidence"], 0.84)
        self.assertEqual(resultado["raw"], respuestas)

    @patch.object(comparar_jev_gemini, "_jev_clasificar")
    @patch.object(comparar_jev_gemini, "_gemini_clasificar")
    def test_correr_comparacion_flags_agreement_and_disagreement(self, gemini_clasificar, jev_clasificar):
        casos = [
            {"id": "coincide", "caption": "x", "fecha_publicacion": "2026-09-15", "nota": ""},
            {"id": "difiere", "caption": "y", "fecha_publicacion": "2026-09-15", "nota": ""},
        ]
        gemini_clasificar.side_effect = [
            {"es_evento": "si", "confianza": "alta"},
            {"es_evento": "si", "confianza": "alta"},
        ]
        jev_clasificar.side_effect = [
            {"es_evento": "si", "confianza": "alta"},
            {"es_evento": "no", "confianza": "baja"},
        ]

        with patch.object(comparar_jev_gemini, "CASOS", casos):
            resultados = comparar_jev_gemini.correr_comparacion()

        self.assertTrue(resultados[0]["coincide_es_evento"])
        self.assertTrue(resultados[0]["coincide_confianza"])
        self.assertFalse(resultados[1]["coincide_es_evento"])
        self.assertFalse(resultados[1]["coincide_confianza"])

    @patch.object(comparar_jev_gemini, "_jev_clasificar")
    @patch.object(comparar_jev_gemini, "_gemini_clasificar")
    def test_correr_comparacion_survives_provider_error(self, gemini_clasificar, jev_clasificar):
        casos = [{"id": "falla_gemini", "caption": "x", "fecha_publicacion": "2026-09-15", "nota": ""}]
        gemini_clasificar.side_effect = RuntimeError("GEMINI_API_KEY no configurada")
        jev_clasificar.return_value = {"es_evento": "si", "confianza": "alta"}

        with patch.object(comparar_jev_gemini, "CASOS", casos):
            resultados = comparar_jev_gemini.correr_comparacion()

        self.assertIn("error", resultados[0]["gemini"])
        self.assertFalse(resultados[0]["coincide_es_evento"])


if __name__ == "__main__":
    unittest.main()
