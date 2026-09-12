import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("GOOGLE_SPREADSHEET_ID", "test-sheet")

from src import curar_fuentes


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
        # Cada una de las 3 cuentas fuente sugiere las mismas 20 cuentas
        # nuevas -> las 20 pasan MIN_SUGERENCIAS_PARA_AGREGAR (sugeridas
        # por las 3), pero el tope debe frenar en MAX_ALTAS_POR_CORRIDA.
        candidatas_generico = [f"candidata_{i}" for i in range(20)]
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
