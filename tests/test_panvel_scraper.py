"""Regressão da Panvel.

A integração está fora do ar. O que estes testes travam é o modo de falhar: uma
rota morta tem de aparecer como ERROR, nunca como "produto não encontrado", que
é o que o relatório do cliente lê como "essa rede não vende esse item".
"""

import unittest

from app.models.product import ScrapeStatusEnum
from app.scrapers.panvel import PanvelScraper

EAN = "7891058003555"
OUTRO_EAN = "7897595901033"


class PanvelFailureModeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.scraper = PanvelScraper()

    async def test_bot_manager_404_is_an_error_not_a_missing_product(self):
        """O 404 vem do bot manager, não de rota inexistente nem de produto ausente."""
        quote = await self._search_with_response(status_code=404)
        self.assertEqual(quote.status, ScrapeStatusEnum.ERROR)
        self.assertIn("404", quote.error_message)
        self.assertEqual(quote.ean, EAN)

    async def test_server_error_is_an_error(self):
        quote = await self._search_with_response(status_code=500)
        self.assertEqual(quote.status, ScrapeStatusEnum.ERROR)

    async def test_waf_response_is_blocked(self):
        for status_code in (401, 403, 429):
            with self.subTest(status_code=status_code):
                quote = await self._search_with_response(status_code=status_code)
                self.assertEqual(quote.status, ScrapeStatusEnum.BLOCKED)

    async def test_empty_result_from_a_healthy_route_is_not_found(self):
        """Só uma resposta 200 válida autoriza dizer que o produto não existe."""
        quote = await self._search_with_response(status_code=200, payload={"items": []})
        self.assertEqual(quote.status, ScrapeStatusEnum.NOT_FOUND)

    async def test_exact_ean_is_required(self):
        payload = {"items": [{"ean": OUTRO_EAN, "name": "Outro produto", "price": 9.9}]}
        quote = await self._search_with_response(status_code=200, payload=payload)
        self.assertEqual(quote.status, ScrapeStatusEnum.NOT_FOUND)

    async def test_matching_ean_is_quoted(self):
        payload = {
            "items": [
                {"ean": OUTRO_EAN, "name": "Outro produto", "price": 9.9},
                {
                    "ean": EAN,
                    "name": "Puran T4 12,5mcg",
                    "price": {"dealPrice": 3.49, "originalPrice": 4.00},
                    "link": "/produto/puran-t4",
                },
            ]
        }
        quote = await self._search_with_response(status_code=200, payload=payload)
        self.assertEqual(quote.status, ScrapeStatusEnum.SUCCESS)
        self.assertEqual(quote.price, 3.49)
        self.assertEqual(quote.ean, EAN)
        self.assertEqual(quote.product_url, "https://www.panvel.com/produto/puran-t4")

    def test_uses_the_real_search_route(self):
        """A rota nunca mudou: POST /api/v3/search, com o termo no corpo."""
        self.assertEqual(self.scraper.search_path, "/api/v3/search")

    def test_sends_no_personal_or_evasion_signals(self):
        """O app-token identifica a aplicação; user-id e finger-print, não.

        O primeiro é público e igual para todo visitante. Os outros dois
        associam uma conta pessoal ao tráfego automatizado e servem para
        enganar o bot manager — nenhum dos dois entra na requisição.
        """
        sent = {key.lower() for key in self.scraper.headers}
        self.assertNotIn("user-id", sent)
        self.assertNotIn("finger-print", sent)
        self.assertNotIn("cookie", sent)
        self.assertEqual(self.scraper.app_token, "ZYkPuDaVJEiD")

    # ------------------------------------------------------------------

    async def _search_with_response(self, status_code: int, payload=None):
        """Executa _search contra uma resposta HTTP simulada."""

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


if __name__ == "__main__":
    unittest.main()
