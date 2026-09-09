"""Regressão das redes RD Saúde (Droga Raia e Drogasil).

Dois comportamentos são travados aqui.

A correspondência: o storefront não devolve EAN no produto, só sku e nome.
Quem confirma é a unicidade — uma consulta por código de barras devolve um
único produto, enquanto uma busca por nome devolve muitos. Resposta ambígua não
vira cotação.

E o transporte: a coleta não pode voltar a depender de subprocesso. Antes
chamava curl.exe, o que só funcionava no Windows e falhava dentro do uvicorn,
que roda em SelectorEventLoop, onde asyncio não suporta subprocessos.
"""

import inspect
import json
import unittest

from app.models.product import PharmacyEnum, ScrapeStatusEnum
from app.scrapers import drogaraia_drogasil as modulo
from app.scrapers.drogaraia_drogasil import DrogaRaiaScraper, DrogasilScraper

EAN = "7891058003555"


def produto(nome="Puran T4 Levotiroxina Sódica 12,5mcg 30 comprimidos", preco=3.79, sku=2851):
    """Produto no formato do __NEXT_DATA__ — sem nenhum campo de EAN."""
    return {
        "sku": sku,
        "url": "/puran-t4-12-5mcg-30-comprimidos.html?origin=search",
        "name": nome,
        "brand": "Puran T4",
        "amount": "30 Comprimidos",
        "priceService": preco,
        "objectID": sku,
    }


def html_com(produtos):
    estado = {"props": {"pageProps": {"results": {"products": produtos}}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(estado)}</script></html>'


class RDParsingTests(unittest.TestCase):
    def setUp(self):
        self.scraper = DrogaRaiaScraper()

    def test_single_result_confirms_the_barcode_match(self):
        quote = self.scraper._parse(html_com([produto()]), EAN)
        self.assertEqual(quote.status, ScrapeStatusEnum.SUCCESS)
        self.assertEqual(quote.price, 3.79)
        self.assertEqual(quote.ean, EAN)
        self.assertEqual(
            quote.product_url,
            "https://www.drogaraia.com.br/puran-t4-12-5mcg-30-comprimidos.html?origin=search",
        )

    def test_ambiguous_result_is_not_quoted(self):
        """Busca por nome devolve 13 dosagens; nenhuma delas é 'o' produto."""
        muitos = [produto(nome=f"Puran T4 {d}mcg", sku=i) for i, d in enumerate([25, 50, 75])]
        quote = self.scraper._parse(html_com(muitos), EAN)
        self.assertEqual(quote.status, ScrapeStatusEnum.NOT_FOUND)
        self.assertIsNone(quote.price)

    def test_term_search_takes_the_first_result(self):
        quote = self.scraper._parse(html_com([produto(), produto(nome="Outro", sku=99)]))
        self.assertEqual(quote.status, ScrapeStatusEnum.SUCCESS)
        self.assertIsNone(quote.ean)

    def test_empty_result_is_not_found(self):
        self.assertEqual(
            self.scraper._parse(html_com([]), EAN).status, ScrapeStatusEnum.NOT_FOUND
        )

    def test_product_without_price_is_not_found(self):
        sem_preco = produto()
        del sem_preco["priceService"]
        quote = self.scraper._parse(html_com([sem_preco]), EAN)
        self.assertEqual(quote.status, ScrapeStatusEnum.NOT_FOUND)
        self.assertIsNotNone(quote.product_name)

    def test_waf_challenge_is_blocked_not_missing(self):
        quote = self.scraper._parse("<html>Access Denied Reference #18.2</html>", EAN)
        self.assertEqual(quote.status, ScrapeStatusEnum.BLOCKED)

    def test_page_without_state_is_an_error_not_a_missing_product(self):
        """Sem o estado do Next.js não dá para afirmar que o produto não existe."""
        quote = self.scraper._parse("<html>qualquer outra coisa</html>", EAN)
        self.assertEqual(quote.status, ScrapeStatusEnum.ERROR)

    def test_nested_page_props_is_handled(self):
        estado = {"props": {"pageProps": {"pageProps": {"results": {"products": [produto()]}}}}}
        html = f'<script id="__NEXT_DATA__">{json.dumps(estado)}</script>'
        self.assertEqual(self.scraper._parse(html, EAN).status, ScrapeStatusEnum.SUCCESS)


class RDTransportTests(unittest.IsolatedAsyncioTestCase):
    def test_no_subprocess_is_used(self):
        """curl.exe por subprocesso quebrava dentro do servidor.

        A verificação olha o código que executa, não o texto do módulo: o
        docstring cita o histórico de propósito.
        """
        self.assertFalse(hasattr(modulo, "asyncio"), "o módulo não deve mais importar asyncio")
        self.assertTrue(hasattr(modulo, "AsyncSession"), "a busca deve usar curl_cffi")
        self.assertNotIn("subprocess", inspect.getsource(modulo.BaseRDScraper._fetch))

    def test_identifies_as_curl_without_impersonating_a_browser(self):
        """Imitar Chrome faz o WAF responder 403; identificar-se como curl passa."""
        agente = DrogaRaiaScraper.fetch_headers["User-Agent"]
        self.assertTrue(agente.startswith("curl/"))
        self.assertNotIn("Mozilla", agente)

    async def test_http_status_drives_the_diagnosis(self):
        casos = [
            (403, ScrapeStatusEnum.BLOCKED),
            (429, ScrapeStatusEnum.BLOCKED),
            (500, ScrapeStatusEnum.ERROR),
            (None, ScrapeStatusEnum.ERROR),
        ]
        for status, esperado in casos:
            with self.subTest(status=status):
                scraper = DrogaRaiaScraper()

                async def falso_fetch(_query, _status=status):
                    return (_status, None if _status is None else "<html></html>")

                scraper._fetch = falso_fetch
                quote = await scraper.search_by_ean(EAN)
                self.assertEqual(quote.status, esperado)
                self.assertEqual(quote.ean, EAN)

    def test_both_flags_share_the_base(self):
        self.assertEqual(DrogaRaiaScraper.pharmacy_key, PharmacyEnum.DROGA_RAIA)
        self.assertEqual(DrogasilScraper.pharmacy_key, PharmacyEnum.DROGASIL)
        self.assertTrue(issubclass(DrogasilScraper, modulo.BaseRDScraper))


if __name__ == "__main__":
    unittest.main()
