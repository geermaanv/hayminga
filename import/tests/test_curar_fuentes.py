import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("GOOGLE_SPREADSHEET_ID", "test-sheet")

from src import curar_fuentes


class CurarBajasTest(unittest.TestCase):
    """Regresión del incidente 01/10/2026: curar() no tenía tope de
    bajas por corrida y sacó 85 de 137 cuentas de un saque al reactivar
    el cron (ver ROADMAP.md). También cubre hashtags_protegidos/
    cuentas_protegidas, agregados en la misma corrección."""

    def setUp(self):
        self.config_file = tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False, encoding="utf-8"
        )
        json.dump(
            {
                "hashtags": [f"hashtag_{i}" for i in range(40)] + ["protegido_1"],
                "cuentas_seguidas": [],
                "cuentas_excluidas": [],
                "hashtags_protegidos": ["protegido_1"],
                "cuentas_protegidas": [],
            },
            self.config_file,
        )
        self.config_file.close()
        patcher = patch.object(curar_fuentes, "CONFIG_PATH", Path(self.config_file.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(lambda: Path(self.config_file.name).unlink(missing_ok=True))

    @patch("src.curar_fuentes.get_service", return_value=Mock())
    def test_caps_removals_even_when_many_cross_the_threshold(self, mock_service):
        # Los 40 hashtag_N cruzan el umbral con intentos distintos (para
        # poder verificar que se priorizan los que tienen MÁS intentos
        # sin hit); protegido_1 también lo cruza pero está protegido.
        stats = {
            ("hashtag", f"hashtag_{i}"): {"fila": i + 2, "intentos_sin_hit": 50 + i}
            for i in range(40)
        }
        stats[("hashtag", "protegido_1")] = {"fila": 100, "intentos_sin_hit": 999}
        with patch("src.curar_fuentes.cargar_fuentes_stats", return_value=stats):
            bajas = curar_fuentes.curar()

        self.assertLessEqual(len(bajas), curar_fuentes.MAX_BAJAS_POR_CORRIDA)
        self.assertEqual(len(bajas), curar_fuentes.MAX_BAJAS_POR_CORRIDA)
        # Se priorizan los de MÁS intentos sin hit (hashtag_39 .. hashtag_15
        # para un tope de 25, ya que hashtag_i tiene 50+i intentos).
        nombres_baja = {nombre for _, nombre in bajas}
        esperados = {f"hashtag_{i}" for i in range(40 - curar_fuentes.MAX_BAJAS_POR_CORRIDA, 40)}
        self.assertEqual(nombres_baja, esperados)
        self.assertNotIn("protegido_1", nombres_baja)

        config = json.loads(Path(self.config_file.name).read_text())
        self.assertIn("protegido_1", config["hashtags"])
        self.assertEqual(
            len(config["hashtags"]), 41 - curar_fuentes.MAX_BAJAS_POR_CORRIDA
        )

    @patch("src.curar_fuentes.get_service", return_value=Mock())
    def test_protected_source_never_removed_regardless_of_misses(self, mock_service):
        stats = {("hashtag", "protegido_1"): {"fila": 2, "intentos_sin_hit": 999}}
        with patch("src.curar_fuentes.cargar_fuentes_stats", return_value=stats):
            bajas = curar_fuentes.curar()

        self.assertEqual(bajas, [])
        config = json.loads(Path(self.config_file.name).read_text())
        self.assertIn("protegido_1", config["hashtags"])


class DescubrirCandidatosCapTest(unittest.TestCase):
    """Regresión del incidente 08/09/2026: descubrir_candidatos() agregó
    515 cuentas en una sola corrida (137 -> 652) porque el piso de "al
    menos N sugerencias" no tenía tope de volumen."""

    def setUp(self):
        self.config_file = tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False, encoding="utf-8"
        )
        json.dump(
            {
                "cuentas_seguidas": ["fuente_a", "fuente_b", "fuente_c"],
                "cuentas_excluidas": [],
                "hashtags": [],
            },
            self.config_file,
        )
        self.config_file.close()
        patcher = patch.object(curar_fuentes, "CONFIG_PATH", Path(self.config_file.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(lambda: Path(self.config_file.name).unlink(missing_ok=True))

    @patch("src.curar_fuentes.guardar_cuentas_ids")
    @patch("src.curar_fuentes.marcar_cuentas_consultadas")
    @patch("src.curar_fuentes.cargar_cuentas_ids", return_value={})
    @patch("src.curar_fuentes.cargar_cuentas_consultadas", return_value={})
    @patch("src.curar_fuentes.get_service", return_value=Mock())
    @patch("src.curar_fuentes._pk_de", return_value=123)
    def test_caps_additions_even_when_many_candidates_pass_the_floor(
        self, mock_pk, mock_service, mock_consultadas, mock_ids, mock_marcar, mock_guardar
    ):
        # Cada una de las 3 cuentas fuente sugiere las mismas 40 cuentas
        # nuevas -> las 40 pasan MIN_SUGERENCIAS_PARA_AGREGAR (sugeridas
        # por las 3), pero el tope debe frenar en MAX_ALTAS_POR_CORRIDA.
        # 40 > cualquier valor razonable del tope, para que la regresión
        # siga probando algo aunque el tope se vuelva a ajustar.
        candidatas_generico = [f"candidata_{i}" for i in range(40)]
        with patch(
            "src.curar_fuentes._sugeridas_para", return_value=candidatas_generico
        ):
            nuevas = curar_fuentes.descubrir_candidatos()

        self.assertLessEqual(len(nuevas), curar_fuentes.MAX_ALTAS_POR_CORRIDA)
        self.assertEqual(len(nuevas), curar_fuentes.MAX_ALTAS_POR_CORRIDA)

        config = json.loads(Path(self.config_file.name).read_text())
        self.assertEqual(
            len(config["cuentas_seguidas"]), 3 + curar_fuentes.MAX_ALTAS_POR_CORRIDA
        )

    @patch("src.curar_fuentes.guardar_cuentas_ids")
    @patch("src.curar_fuentes.marcar_cuentas_consultadas")
    @patch("src.curar_fuentes.cargar_cuentas_ids", return_value={})
    @patch("src.curar_fuentes.cargar_cuentas_consultadas", return_value={})
    @patch("src.curar_fuentes.get_service", return_value=Mock())
    @patch("src.curar_fuentes._pk_de", return_value=123)
    def test_candidate_below_floor_is_not_added(
        self, mock_pk, mock_service, mock_consultadas, mock_ids, mock_marcar, mock_guardar
    ):
        # "sugerida_debil" solo la sugiere 1 de las 3 cuentas fuente ->
        # no llega a MIN_SUGERENCIAS_PARA_AGREGAR (3).
        def sugeridas(username, pk=None):
            return ["sugerida_debil"] if username == "fuente_a" else []

        with patch("src.curar_fuentes._sugeridas_para", side_effect=sugeridas):
            nuevas = curar_fuentes.descubrir_candidatos()

        self.assertEqual(nuevas, [])


if __name__ == "__main__":
    unittest.main()
