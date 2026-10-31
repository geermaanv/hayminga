import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("GOOGLE_SPREADSHEET_ID", "test-sheet")

from src import achicar_cuentas_sin_aporte as acsa
from src.sheets import COLUMNS


class AchicarCuentasSinAporteTest(unittest.TestCase):
    """Regresión del hallazgo del 31/10/2026 (ver ROADMAP.md): de 510
    cuentas_seguidas, solo 48 aparecían alguna vez como Username en el
    historial de Eventos — el resto nunca aportó nada."""

    def setUp(self):
        self.config_file = tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False, encoding="utf-8"
        )
        json.dump(
            {
                "cuentas_seguidas": ["aporta_confirmado", "aporta_descartado", "sin_aporte", "protegida_sin_aporte"],
                "cuentas_protegidas": ["protegida_sin_aporte"],
            },
            self.config_file,
        )
        self.config_file.close()
        patcher = patch.object(acsa, "CONFIG_PATH", Path(self.config_file.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(lambda: Path(self.config_file.name).unlink(missing_ok=True))

    def _fila(self, username=""):
        fila = [""] * len(COLUMNS)
        fila[COLUMNS.index("Username")] = username
        return fila

    def _service_con(self, filas):
        service = Mock()
        service.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
            "values": filas
        }
        return service

    def test_identifica_cuentas_con_aporte_en_cualquier_estado(self):
        service = self._service_con([
            self._fila(username="aporta_confirmado"),
            self._fila(username="aporta_descartado"),
            self._fila(username="otra_cuenta_no_seguida"),
        ])
        aportantes = acsa.cuentas_con_aporte(service)
        self.assertEqual(aportantes, {"aporta_confirmado", "aporta_descartado", "otra_cuenta_no_seguida"})

    @patch("src.achicar_cuentas_sin_aporte.get_service")
    def test_quita_solo_las_sin_aporte_y_no_protegidas(self, mock_get_service):
        mock_get_service.return_value = self._service_con([
            self._fila(username="aporta_confirmado"),
            self._fila(username="aporta_descartado"),
        ])

        a_quitar = acsa.achicar(escribir=True)

        self.assertEqual(a_quitar, ["sin_aporte"])
        config = json.loads(Path(self.config_file.name).read_text())
        self.assertEqual(
            set(config["cuentas_seguidas"]),
            {"aporta_confirmado", "aporta_descartado", "protegida_sin_aporte"},
        )

    @patch("src.achicar_cuentas_sin_aporte.get_service")
    def test_dry_run_no_escribe_nada(self, mock_get_service):
        mock_get_service.return_value = self._service_con([
            self._fila(username="aporta_confirmado"),
        ])

        acsa.achicar(escribir=False)

        config = json.loads(Path(self.config_file.name).read_text())
        self.assertEqual(
            set(config["cuentas_seguidas"]),
            {"aporta_confirmado", "aporta_descartado", "sin_aporte", "protegida_sin_aporte"},
        )


if __name__ == "__main__":
    unittest.main()
