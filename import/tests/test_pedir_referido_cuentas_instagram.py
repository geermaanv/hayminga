import json
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("GOOGLE_SPREADSHEET_ID", "test-sheet")

from src import pedir_referido_cuentas_instagram as prci


class DestinatariosElegiblesTest(unittest.TestCase):
    def setUp(self):
        self.config_file = tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False, encoding="utf-8"
        )
        json.dump(
            {
                "cuentas_seguidas": ["buena_cuenta", "sin_email"],
                "cuentas_protegidas": ["protegida_buena"],
            },
            self.config_file,
        )
        self.config_file.close()
        patcher = patch.object(prci, "CONFIG_PATH", Path(self.config_file.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(lambda: Path(self.config_file.name).unlink(missing_ok=True))

    def _fila(self, username="", email="", ultimo=""):
        return [username, "", "", email, ultimo]

    def _service_con(self, filas):
        service = Mock()
        service.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
            "values": filas
        }
        return service

    @patch("src.pedir_referido_cuentas_instagram.cargar_emails_directorio", return_value=set())
    def test_incluye_cuentas_seguidas_y_protegidas_con_email(self, mock_dir):
        service = self._service_con([
            self._fila(username="buena_cuenta", email="a@x.com"),
            self._fila(username="protegida_buena", email="b@x.com"),
            self._fila(username="no_seguida", email="c@x.com"),
        ])
        elegibles = prci.destinatarios_elegibles(service)
        self.assertEqual(
            {(u, e) for _, u, e in elegibles},
            {("buena_cuenta", "a@x.com"), ("protegida_buena", "b@x.com")},
        )

    @patch("src.pedir_referido_cuentas_instagram.cargar_emails_directorio", return_value=set())
    def test_ignora_cuentas_sin_email(self, mock_dir):
        service = self._service_con([
            self._fila(username="sin_email", email=""),
        ])
        self.assertEqual(prci.destinatarios_elegibles(service), [])

    @patch("src.pedir_referido_cuentas_instagram.cargar_emails_directorio", return_value={"a@x.com"})
    def test_excluye_emails_ya_en_el_directorio(self, mock_dir):
        service = self._service_con([
            self._fila(username="buena_cuenta", email="a@x.com"),
        ])
        self.assertEqual(prci.destinatarios_elegibles(service), [])

    @patch("src.pedir_referido_cuentas_instagram.cargar_emails_directorio", return_value=set())
    def test_excluye_a_quien_ya_se_le_pidio_hace_poco(self, mock_dir):
        reciente = date.today().isoformat()
        service = self._service_con([
            self._fila(username="buena_cuenta", email="a@x.com", ultimo=reciente),
        ])
        self.assertEqual(prci.destinatarios_elegibles(service), [])

    @patch("src.pedir_referido_cuentas_instagram.cargar_emails_directorio", return_value=set())
    def test_incluye_a_quien_se_le_pidio_hace_mas_del_cooldown(self, mock_dir):
        viejo = (date.today() - timedelta(days=30 * prci.MESES_COOLDOWN_REFERIDO + 5)).isoformat()
        service = self._service_con([
            self._fila(username="buena_cuenta", email="a@x.com", ultimo=viejo),
        ])
        elegibles = prci.destinatarios_elegibles(service)
        self.assertEqual(len(elegibles), 1)


class PedirTest(unittest.TestCase):
    def setUp(self):
        self.config_file = tempfile.NamedTemporaryFile(
            suffix=".json", mode="w", delete=False, encoding="utf-8"
        )
        json.dump({"cuentas_seguidas": ["buena_cuenta"], "cuentas_protegidas": []}, self.config_file)
        self.config_file.close()
        patcher = patch.object(prci, "CONFIG_PATH", Path(self.config_file.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(lambda: Path(self.config_file.name).unlink(missing_ok=True))

    def _service_con(self, filas):
        service = Mock()
        service.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
            "values": filas
        }
        return service

    @patch("src.pedir_referido_cuentas_instagram.requests.post")
    @patch("src.pedir_referido_cuentas_instagram.cargar_emails_directorio", return_value=set())
    @patch("src.pedir_referido_cuentas_instagram.get_service")
    def test_dry_run_no_llama_a_code_gs(self, mock_get_service, mock_dir, mock_post):
        mock_get_service.return_value = self._service_con([["buena_cuenta", "", "", "a@x.com", ""]])

        prci.pedir(escribir=False)

        mock_post.assert_not_called()

    @patch("src.pedir_referido_cuentas_instagram.requests.post")
    @patch("src.pedir_referido_cuentas_instagram.cargar_emails_directorio", return_value=set())
    @patch("src.pedir_referido_cuentas_instagram.get_service")
    @patch.dict(os.environ, {"APPS_SCRIPT_URL": "https://example.test", "APPS_SCRIPT_SHARED_SECRET": "s3cr3t"})
    def test_escribir_manda_la_lista_correcta_y_actualiza_el_registro(self, mock_get_service, mock_dir, mock_post):
        service = self._service_con([["buena_cuenta", "", "", "a@x.com", ""]])
        mock_get_service.return_value = service
        mock_post.return_value = Mock(json=lambda: {"success": True, "enviados": 1})

        elegibles = prci.pedir(escribir=True)

        self.assertEqual(len(elegibles), 1)
        _, kwargs = mock_post.call_args
        body = json.loads(kwargs["data"])
        self.assertEqual(body["accion"], "enviar_mail_lista")
        self.assertEqual(body["emails"], ["a@x.com"])
        self.assertEqual(body["asunto"], prci.ASUNTO)
        self.assertEqual(body["texto"], prci.TEXTO)

        service.spreadsheets.return_value.values.return_value.batchUpdate.assert_called_once()
        batch_body = service.spreadsheets.return_value.values.return_value.batchUpdate.call_args.kwargs["body"]
        self.assertEqual(batch_body["data"][0]["range"], "CuentasIds!E2")
        self.assertEqual(batch_body["data"][0]["values"], [[date.today().isoformat()]])


if __name__ == "__main__":
    unittest.main()
