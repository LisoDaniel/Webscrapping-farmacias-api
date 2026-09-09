"""Regressão da Panvel.

Dois comportamentos são travados aqui.

O modo de falhar: a rede bloqueia cliente automatizado, e isso tem de aparecer
como ERROR, nunca como "produto não encontrado" — que o relatório do cliente lê
como "essa rede não vende esse item".

E a regra de correspondência. A busca da Panvel aceita o código de barras como
termo, mas **não devolve o EAN no item**: só nome, panvelCode e preço. Como não
há o que conferir no payload, o que confirma a correspondência é a unicidade da
resposta. Resultado ambíguo não vira cotação.

Os payloads abaixo reproduzem o formato real, capturado em 08/09/2026.
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app.core.capture_store import CaptureStore
from app.models.product import ScrapeStatusEnum
from app.scrapers.panvel import PanvelScraper

EAN = "7891058003555"
OUTRO_EAN = "7897595901033"


def item_real(
    nome="Puran T4 Levotiroxina Sódica 12,5mcg 30 Comprimidos",
    deal=3.97,
    original=3.97,
    codigo=101160,
):
    """Item no formato que a busca devolve — sem nenhum campo de EAN."""
    return {
        "link": f"https://www.panvel.com/panvel/puran-t4/p-{codigo}",
        "name": nome,
        "image": "https://cdn1.staticpanvel.com.br/produtos/15/forbidden.jpg",
        "panvelCode": codigo,
        "brandName": "PURAN T4",
        "presentationTitle": "30 comprimido(s) (R$0.09/co.)",
        "price": {
            "dealPrice": deal,
            "originalPrice": original,
            "pricePerUnit": 0.13,
            # Preço de pacote com 4 unidades: não é o preço unitário.
            "pack": {"quantity": 4, "dealPrice": 2.79},
            "discount": {"dealPrice": deal, "percentage": 0, "discountValue": 1.18},
        },
    }


def payload_real(itens):
    return {"totalItems": len(itens), "totalPages": 1, "items": itens}


class PanvelFailureModeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Store vazio de propósito: estes testes exercitam a via de rede e não
        # podem depender do que houver em capturas/ na máquina de quem roda.
        self.temp = tempfile.TemporaryDirectory()
        self.scraper = PanvelScraper(capture_store=CaptureStore(Path(self.temp.name)))

    def tearDown(self):
        self.temp.cleanup()

    async def test_bot_manager_404_is_an_error_not_a_missing_product(self):
        quote = await self._search_with_response(status_code=404)
        self.assertEqual(quote.status, ScrapeStatusEnum.ERROR)
        self.assertIn("404", quote.error_message)
        self.assertEqual(quote.ean, EAN)

    async def test_server_error_is_an_error(self):
        self.assertEqual(
            (await self._search_with_response(status_code=500)).status, ScrapeStatusEnum.ERROR
        )

    async def test_waf_response_is_blocked(self):
        for status_code in (401, 403, 429):
            with self.subTest(status_code=status_code):
                quote = await self._search_with_response(status_code=status_code)
                self.assertEqual(quote.status, ScrapeStatusEnum.BLOCKED)

    async def test_empty_result_from_a_healthy_route_is_not_found(self):
        """Só uma resposta 200 válida autoriza dizer que o produto não existe."""
        quote = await self._search_with_response(status_code=200, payload=payload_real([]))
        self.assertEqual(quote.status, ScrapeStatusEnum.NOT_FOUND)

    async def test_single_result_confirms_the_barcode_match(self):
        quote = await self._search_with_response(status_code=200, payload=payload_real([item_real()]))
        self.assertEqual(quote.status, ScrapeStatusEnum.SUCCESS)
        self.assertEqual(quote.price, 3.97)
        self.assertEqual(quote.ean, EAN)
        self.assertEqual(quote.product_url, "https://www.panvel.com/panvel/puran-t4/p-101160")

    async def test_ambiguous_result_is_not_quoted(self):
        """Vários produtos para um código de barras não identificam nenhum."""
        payload = payload_real([item_real(), item_real(nome="Outro Puran", codigo=6491)])
        quote = await self._search_with_response(status_code=200, payload=payload)
        self.assertEqual(quote.status, ScrapeStatusEnum.NOT_FOUND)
        self.assertIsNone(quote.price)

    async def test_pack_price_is_not_used_as_unit_price(self):
        """O pack de 4 sai por 2,79 a unidade; a cotação é do item avulso."""
        quote = await self._search_with_response(status_code=200, payload=payload_real([item_real()]))
        self.assertEqual(quote.price, 3.97)

    async def test_discount_is_computed_from_the_original_price(self):
        payload = payload_real([item_real(deal=3.20, original=4.00)])
        quote = await self._search_with_response(status_code=200, payload=payload)
        self.assertEqual(quote.price, 3.20)
        self.assertEqual(quote.list_price, 4.00)
        self.assertAlmostEqual(quote.discount_percentage, 20.0, places=1)

    def test_uses_the_real_search_route(self):
        self.assertEqual(self.scraper.search_path, "/api/v3/search")

    def test_server_side_scraper_sends_no_session_of_its_own(self):
        """Sem navegador não há sessão: nada de user-id ou finger-print fixos.

        A API exige `user-id`, então esta via nunca terá sucesso — e é assim
        que deve ser. Coletar da Panvel passa pela captura no navegador, onde
        esses valores são os do próprio operador.
        """
        enviados = {chave.lower() for chave in self.scraper.headers}
        self.assertNotIn("user-id", enviados)
        self.assertNotIn("finger-print", enviados)
        self.assertNotIn("cookie", enviados)

    async def _search_with_response(self, status_code: int, payload=None):
        class FakeResponse:
            def __init__(self, status_code, payload):
                self.status_code = status_code
                self._payload = payload

            def json(self):
                if self._payload is None:
                    raise ValueError("sem corpo JSON")
                return self._payload

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc_info):
                return False

            async def post(self, *args, **kwargs):
                return FakeResponse(status_code, payload)

        self.scraper.get_http_client = lambda: FakeClient()
        return await self.scraper.search_by_ean(EAN)


class PanvelAssistedCaptureTests(unittest.IsolatedAsyncioTestCase):
    """A captura feita no navegador alimenta o mesmo parser."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.scraper = PanvelScraper(capture_store=CaptureStore(self.directory, max_age_hours=24))
        # Havendo captura, a rede não deve ser tocada.
        self.scraper.get_http_client = _falhar_se_chamado

    def tearDown(self):
        self.temp.cleanup()

    def _escrever(self, captured_at, results):
        (self.directory / "panvel.json").write_text(
            json.dumps(
                {
                    "pharmacy": "panvel",
                    "uf": "SP",
                    "covenant_code": "416061",
                    "captured_at": captured_at.isoformat(),
                    "results": results,
                }
            ),
            encoding="utf-8",
        )

    async def test_capture_produces_a_quote_without_touching_the_network(self):
        self._escrever(datetime.now() - timedelta(hours=2), {EAN: payload_real([item_real()])})
        quote = await self.scraper.search_by_ean(EAN)
        self.assertEqual(quote.status, ScrapeStatusEnum.SUCCESS)
        self.assertEqual(quote.price, 3.97)
        self.assertEqual(quote.ean, EAN)

    async def test_quote_is_dated_by_the_capture_not_by_now(self):
        """O histórico tem de registrar quando o preço foi de fato observado."""
        momento = datetime.now() - timedelta(hours=5)
        self._escrever(momento, {EAN: payload_real([item_real()])})
        quote = await self.scraper.search_by_ean(EAN)
        self.assertAlmostEqual(quote.scraped_at.timestamp(), momento.timestamp(), places=0)

    async def test_stale_capture_becomes_an_actionable_error(self):
        self._escrever(datetime.now() - timedelta(hours=48), {EAN: payload_real([item_real()])})
        quote = await self.scraper.search_by_ean(EAN)
        self.assertEqual(quote.status, ScrapeStatusEnum.ERROR)
        self.assertIn("Refaça a coleta", quote.error_message)

    async def test_ambiguous_capture_is_not_quoted(self):
        """A regra de unicidade vale igual para o dado capturado."""
        self._escrever(
            datetime.now(),
            {EAN: payload_real([item_real(), item_real(nome="Outro", codigo=6491)])},
        )
        quote = await self.scraper.search_by_ean(EAN)
        self.assertEqual(quote.status, ScrapeStatusEnum.NOT_FOUND)

    async def test_ean_absent_from_capture_falls_back_to_the_network(self):
        self._escrever(datetime.now(), {OUTRO_EAN: payload_real([item_real()])})
        with self.assertRaises(AssertionError):
            await self.scraper.search_by_ean(EAN)


def _falhar_se_chamado():
    raise AssertionError("a rede não deve ser consultada quando há captura")


if __name__ == "__main__":
    unittest.main()
