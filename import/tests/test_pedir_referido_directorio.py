import os
import unittest
from datetime import date, timedelta
from unittest.mock import Mock, patch

os.environ.setdefault("GOOGLE_SPREADSHEET_ID", "test-sheet")

from src import pedir_referido_directorio as prd


class PrevisualizarTest(unittest.TestCase):
    """previsualizar() es de solo lectura — nunca debe llamar a
    spreadsheets().values().batchUpdate ni update, solo get."""

    def _service_con(self, filas):
        service = Mock()
        service.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
            "values": filas
        }
        return service

    def _fila(self, email="", ultimo=""):
        # F..L: Email, Whatsapp, Tecnicas, AnioDesde, RecibeNovedades,
        # OfreceServicios, UltimoPedidoReferido
        return [email, "", "", "", "", "", ultimo]

    def test_cuenta_emails_sin_pedido_previo(self):
        service = self._service_con([
            self._fila(email="a@x.com"),
            self._fila(email="b@x.com"),
        ])
        self.assertEqual(prd.previsualizar(service), 2)

    def test_ignora_filas_sin_email(self):
        service = self._service_con([
            self._fila(email=""),
            self._fila(email="a@x.com"),
        ])
        self.assertEqual(prd.previsualizar(service), 1)

    def test_excluye_a_quien_ya_se_le_pidio_hace_poco(self):
        reciente = date.today().isoformat()
        service = self._service_con([
            self._fila(email="a@x.com", ultimo=reciente),
            self._fila(email="b@x.com"),
        ])
        self.assertEqual(prd.previsualizar(service), 1)

    def test_incluye_a_quien_se_le_pidio_hace_mas_del_cooldown(self):
        viejo = (date.today() - timedelta(days=30 * prd.MESES_COOLDOWN_REFERIDO + 5)).isoformat()
        service = self._service_con([
            self._fila(email="a@x.com", ultimo=viejo),
        ])
        self.assertEqual(prd.previsualizar(service), 1)

    def test_fecha_invalida_no_excluye(self):
        service = self._service_con([
            self._fila(email="a@x.com", ultimo="no-es-una-fecha"),
        ])
        self.assertEqual(prd.previsualizar(service), 1)


class PedirTest(unittest.TestCase):
    @patch("src.pedir_referido_directorio.get_service")
    @patch("src.pedir_referido_directorio.requests.post")
    def test_dry_run_no_llama_a_code_gs(self, mock_post, mock_get_service):
        mock_get_service.return_value = Mock()
        mock_get_service.return_value.spreadsheets.return_value.values.return_value \
            .get.return_value.execute.return_value = {"values": []}

        prd.pedir(escribir=False)

        mock_post.assert_not_called()

    @patch("src.pedir_referido_directorio.get_service")
    @patch("src.pedir_referido_directorio.requests.post")
    @patch.dict(os.environ, {"APPS_SCRIPT_URL": "https://example.test", "APPS_SCRIPT_SHARED_SECRET": "s3cr3t"})
    def test_escribir_llama_a_code_gs_con_la_accion_correcta(self, mock_post, mock_get_service):
        mock_get_service.return_value = Mock()
        mock_get_service.return_value.spreadsheets.return_value.values.return_value \
            .get.return_value.execute.return_value = {"values": []}
        mock_post.return_value = Mock(json=lambda: {"success": True, "enviados": 7})

        enviados = prd.pedir(escribir=True)

        self.assertEqual(enviados, 7)
        _, kwargs = mock_post.call_args
        import json
        body = json.loads(kwargs["data"])
        self.assertEqual(body["accion"], "pedir_referido_directorio")
        self.assertEqual(body["secreto"], "s3cr3t")
        self.assertEqual(body["asunto"], prd.ASUNTO)
        self.assertEqual(body["texto"], prd.TEXTO)


if __name__ == "__main__":
    unittest.main()
