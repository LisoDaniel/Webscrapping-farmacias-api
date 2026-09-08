import tempfile
import unittest
from pathlib import Path

from app.db.session import Database
from app.models.product import PharmacyEnum, PriceQuote, ScrapeStatusEnum, SearchResponse
from app.services.price_history_service import PriceHistoryService


class PriceHistoryServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_file = Path(self.temp_dir.name) / "history.db"
        self.database = Database(f"sqlite+aiosqlite:///{database_file.as_posix()}")
        await self.database.create_schema()
        self.service = PriceHistoryService(self.database)

    async def asyncTearDown(self):
        await self.database.dispose()
        self.temp_dir.cleanup()

    async def test_persists_search_and_returns_latest_price_per_pharmacy(self):
        response = SearchResponse(
            query="7891058003555",
            ean="7891058003555",
            total_found=1,
            cep="01001000",
            city="São Paulo",
            state="SP",
            quotes=[
                PriceQuote(
                    pharmacy_key=PharmacyEnum.PAGUE_MENOS,
                    pharmacy_name="Pague Menos",
                    product_name="Puran T4 12,5 mcg",
                    ean="7891058003555",
                    price=2.89,
                    available=True,
                    status=ScrapeStatusEnum.SUCCESS,
                ),
                PriceQuote(
                    pharmacy_key=PharmacyEnum.PANVEL,
                    pharmacy_name="Panvel",
                    ean="7891058003555",
                    status=ScrapeStatusEnum.NOT_FOUND,
                ),
            ],
        )

        run_id = await self.service.record_search(response)
        history = await self.service.get_history("7891058003555")
        summary = await self.service.get_summary("7891058003555")

        self.assertEqual(len(run_id), 36)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].ean, "7891058003555")
        self.assertEqual(history[0].cep, "01001000")
        self.assertEqual(summary.total_quotes, 2)
        self.assertEqual({item.pharmacy_key for item in summary.latest_prices}, {
            PharmacyEnum.PAGUE_MENOS,
            PharmacyEnum.PANVEL,
        })
