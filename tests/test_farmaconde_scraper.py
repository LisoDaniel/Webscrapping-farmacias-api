import unittest

from app.models.product import ScrapeStatusEnum
from app.scrapers.farmaconde import FarmaCondeScraper


class FarmaCondeScraperTests(unittest.TestCase):
    def setUp(self):
        self.scraper = FarmaCondeScraper()
        self.product = {
            "productName": "Puran T4 100mcg Caixa 30 Comprimidos",
            "link": "https://www.farmaconde.com.br/puran-t4-100mcg-caixa-30-comprimidos/p",
            "items": [{
                "ean": "7897595901033",
                "sellers": [{"commertialOffer": {
                    "Price": 16.49,
                    "ListPrice": 17.73,
                    "IsAvailable": True,
                }}],
            }],
        }

    def test_parses_exact_ean_offer(self):
        quote = self.scraper._parse_product(self.product, "7897595901033")
        self.assertEqual(quote.status, ScrapeStatusEnum.SUCCESS)
        self.assertEqual(quote.price, 16.49)
        self.assertEqual(quote.ean, "7897595901033")

    def test_does_not_return_another_ean_as_exact_match(self):
        quote = self.scraper._parse_product(self.product, "7891058003555")
        self.assertEqual(quote.status, ScrapeStatusEnum.NOT_FOUND)

    def test_partial_catalog_response_is_accepted(self):
        self.assertTrue(self.scraper._is_catalog_success_status(206))
        self.assertFalse(self.scraper._is_catalog_success_status(500))
