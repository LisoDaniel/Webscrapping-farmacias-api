"""Regressão da base VTEX.

O que estes testes protegem é uma garantia só: uma cotação nunca pode sair com
um EAN que a loja não confirmou. Foi assim que a Farma Conde passou a devolver
"não encontrado" para todo EAN e que as demais redes podiam cotar o produto
errado com o código do cliente carimbado por cima.
"""

import unittest

from app.models.product import PharmacyEnum, ScrapeStatusEnum
from app.scrapers.araujo import AraujoScraper
from app.scrapers.farmaconde import FarmaCondeScraper
from app.scrapers.pacheco import PachecoScraper
from app.scrapers.paguemenos import PagueMenosScraper
from app.scrapers.preco_popular import PrecoPopularScraper
from app.scrapers.saojoao import SaoJoaoScraper
from app.scrapers.vtex import VtexCatalogScraper, VtexIntelligentSearchScraper

EAN = "7897595901033"
OUTRO_EAN = "7891058003555"


def vtex_product(ean=EAN, price=16.49, list_price=17.73, name="Puran T4 100mcg 30 Comprimidos"):
    return {
        "productName": name,
        "link": "https://www.farmaconde.com.br/puran-t4-100mcg/p",
        "items": [
            {
                "ean": ean,
                "sellers": [
                    {
                        "commertialOffer": {
                            "Price": price,
                            "ListPrice": list_price,
                            "IsAvailable": True,
                        }
                    }
                ],
            }
        ],
    }


class VtexParsingTests(unittest.TestCase):
    def setUp(self):
        self.scraper = FarmaCondeScraper()

    def test_parses_exact_ean_offer(self):
        quote = self.scraper._parse_product(vtex_product(), EAN)
        self.assertEqual(quote.status, ScrapeStatusEnum.SUCCESS)
        self.assertEqual(quote.price, 16.49)
        self.assertEqual(quote.ean, EAN)
        self.assertTrue(quote.available)
        self.assertAlmostEqual(quote.discount_percentage, 7.0, places=1)

    def test_does_not_return_another_ean_as_exact_match(self):
        quote = self.scraper._parse_product(vtex_product(), OUTRO_EAN)
        self.assertEqual(quote.status, ScrapeStatusEnum.NOT_FOUND)
        self.assertIsNone(quote.price)

    def test_picks_the_matching_sku_among_several(self):
        product = vtex_product()
        product["items"].insert(
            0,
            {
                "ean": OUTRO_EAN,
                "sellers": [{"commertialOffer": {"Price": 3.01, "IsAvailable": True}}],
            },
        )
        quote = self.scraper._parse_product(product, EAN)
        self.assertEqual(quote.status, ScrapeStatusEnum.SUCCESS)
        self.assertEqual(quote.ean, EAN)
        self.assertEqual(quote.price, 16.49)

    def test_term_search_never_invents_an_ean(self):
        """Sem EAN consultado, a cotação carrega só o que a loja informou."""
        product = vtex_product(ean="")
        quote = self.scraper._parse_product(product)
        self.assertEqual(quote.status, ScrapeStatusEnum.SUCCESS)
        self.assertIsNone(quote.ean)

    def test_product_without_price_is_not_found(self):
        product = vtex_product()
        product["items"][0]["sellers"] = [{"commertialOffer": {}}]
        quote = self.scraper._parse_product(product, EAN)
        self.assertEqual(quote.status, ScrapeStatusEnum.NOT_FOUND)
        self.assertEqual(quote.product_name, "Puran T4 100mcg 30 Comprimidos")

    def test_available_quantity_counts_as_availability(self):
        product = vtex_product()
        product["items"][0]["sellers"][0]["commertialOffer"] = {
            "Price": 10.0,
            "AvailableQuantity": 5,
        }
        self.assertTrue(self.scraper._parse_product(product, EAN).available)

    def test_relative_link_becomes_absolute(self):
        product = vtex_product()
        product["link"] = "/puran-t4-100mcg/p"
        quote = self.scraper._parse_product(product, EAN)
        self.assertEqual(quote.product_url, "https://www.farmaconde.com.br/puran-t4-100mcg/p")

    def test_partial_catalog_response_is_accepted(self):
        self.assertTrue(self.scraper._is_catalog_success_status(206))
        self.assertTrue(self.scraper._is_catalog_success_status(200))
        self.assertFalse(self.scraper._is_catalog_success_status(500))

    def test_blocked_and_error_carry_the_requested_ean(self):
        blocked = self.scraper._blocked(403, EAN)
        self.assertEqual(blocked.status, ScrapeStatusEnum.BLOCKED)
        self.assertEqual(blocked.ean, EAN)
        self.assertIn("403", blocked.error_message)

        failed = self.scraper._error("falha de rede", EAN)
        self.assertEqual(failed.status, ScrapeStatusEnum.ERROR)
        self.assertEqual(failed.ean, EAN)


class VtexStoreWiringTests(unittest.TestCase):
    """Cada rede precisa herdar a verificação de EAN, não reimplementá-la."""

    CATALOG_ONLY = [
        (PrecoPopularScraper, PharmacyEnum.PRECO_POPULAR),
        (SaoJoaoScraper, PharmacyEnum.SAO_JOAO),
        (FarmaCondeScraper, PharmacyEnum.FARMA_CONDE),
        (AraujoScraper, PharmacyEnum.ARAUJO),
    ]
    INTELLIGENT_SEARCH = [
        (PachecoScraper, PharmacyEnum.PACHECO),
        (PagueMenosScraper, PharmacyEnum.PAGUE_MENOS),
    ]

    def test_every_vtex_store_uses_the_shared_base(self):
        for scraper_cls, key in self.CATALOG_ONLY + self.INTELLIGENT_SEARCH:
            with self.subTest(pharmacy=key.value):
                self.assertTrue(issubclass(scraper_cls, VtexCatalogScraper))
                self.assertEqual(scraper_cls.pharmacy_key, key)

    def test_intelligent_search_stores_keep_the_richer_term_route(self):
        for scraper_cls, key in self.INTELLIGENT_SEARCH:
            with self.subTest(pharmacy=key.value):
                self.assertTrue(issubclass(scraper_cls, VtexIntelligentSearchScraper))

    def test_no_store_reuses_the_requested_ean_on_a_mismatch(self):
        for scraper_cls, key in self.CATALOG_ONLY + self.INTELLIGENT_SEARCH:
            with self.subTest(pharmacy=key.value):
                quote = scraper_cls()._parse_product(vtex_product(), OUTRO_EAN)
                self.assertEqual(quote.status, ScrapeStatusEnum.NOT_FOUND)
                self.assertIsNone(quote.price)


if __name__ == "__main__":
    unittest.main()
