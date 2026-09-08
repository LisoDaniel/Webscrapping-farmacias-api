import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from app.models.product import (
    PharmacyEnum,
    PriceQuote,
    ScrapeStatusEnum,
    SearchResponse,
)
from app.scrapers.base import BaseScraper
from app.services.validation_service import ScraperValidationService, ValidationProduct


class BlockingScraper(BaseScraper):
    pharmacy_key = PharmacyEnum.ARAUJO
    name = "Teste bloqueado"
    base_url = "https://example.invalid"

    def __init__(self):
        super().__init__()
        self.term_called = False

    async def search_by_ean(self, ean):
        return PriceQuote(
            pharmacy_key=self.pharmacy_key,
            pharmacy_name=self.name,
            ean=ean,
            status=ScrapeStatusEnum.BLOCKED,
        )

    async def search_by_term(self, term):
        self.term_called = True
        return PriceQuote(
            pharmacy_key=self.pharmacy_key,
            pharmacy_name=self.name,
            status=ScrapeStatusEnum.SUCCESS,
            price=1.0,
        )


class FakeScraperService:
    async def search(self, request):
        return SearchResponse(
            query=request.ean,
            ean=request.ean,
            total_found=1,
            quotes=[
                PriceQuote(
                    pharmacy_key=PharmacyEnum.PANVEL,
                    pharmacy_name="Panvel",
                    ean=request.ean,
                    product_name="Produto de teste",
                    price=10.0,
                    status=ScrapeStatusEnum.SUCCESS,
                )
            ],
        )


class ValidationServiceTests(unittest.TestCase):
    def test_blocked_ean_is_not_replaced_by_text_fallback(self):
        scraper = BlockingScraper()
        result = asyncio.run(scraper.search(ean="7891058003555", term="produto"))
        self.assertEqual(result.status, ScrapeStatusEnum.BLOCKED)
        self.assertFalse(scraper.term_called)

    def test_run_and_export_report(self):
        service = ScraperValidationService(scraper_service=FakeScraperService())
        report = asyncio.run(
            service.run(
                products=[ValidationProduct(ean="7891058003555", label="Produto de teste")],
                fixture_path="fixture.json",
                pharmacies=[PharmacyEnum.PANVEL],
            )
        )
        self.assertEqual(report.status_summary()["panvel"]["success"], 1)

        with tempfile.TemporaryDirectory() as temp_dir:
            json_path, csv_path = service.export(report, Path(temp_dir))
            self.assertTrue(json_path.exists())
            self.assertTrue(csv_path.exists())
            data = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(data["status_summary"]["panvel"]["success"], 1)

    def test_restricted_pharmacy_is_not_validated(self):
        service = ScraperValidationService(scraper_service=FakeScraperService())
        with self.assertRaisesRegex(ValueError, "não permitida"):
            asyncio.run(
                service.run(
                    products=[ValidationProduct(ean="7891058003555", label="Produto de teste")],
                    fixture_path="fixture.json",
                    pharmacies=[PharmacyEnum.ARAUJO],
                )
            )


if __name__ == "__main__":
    unittest.main()
