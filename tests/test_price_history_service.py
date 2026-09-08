import tempfile
import unittest
from pathlib import Path

from app.db.session import Database
from app.models.client import ClientInfo
from app.models.product import (
    PharmacyEnum,
    PriceQuote,
    ProductItem,
    ScrapeStatusEnum,
    SearchResponse,
)
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

    async def test_spelled_out_state_is_persisted_as_uf(self):
        """A planilha da CARIN diz "RIO GRANDE DO SUL"; a coluna aceita 2 letras.

        Sem normalizar, o INSERT estoura com StringDataRightTruncationError e
        derruba a varredura inteira antes de o relatório ser gerado.
        """
        client = ClientInfo(
            id="1167_carin",
            folder_name="1167 CARIN",
            file_path="Clientes/1167 CARIN/planilha.xlsx",
            client_name="1167 CARIN",
            city="VENÂNCIO AIRES (CARIN)",
            state="RIO GRANDE DO SUL",
        )
        product = ProductItem(
            ean="7891058003555",
            name="PURAN T4 12,5MCG 30COMP",
            quotes=[
                PriceQuote(
                    pharmacy_key=PharmacyEnum.SAO_JOAO,
                    pharmacy_name="Farmácias São João",
                    ean="7891058003555",
                    price=3.91,
                    status=ScrapeStatusEnum.SUCCESS,
                )
            ],
        )

        run_id = await self.service.record_client_scrape(client, [product])
        self.assertIsNotNone(run_id)

        history = await self.service.get_history("7891058003555")
        self.assertEqual(history[0].state, "RS")
        self.assertEqual(history[0].city, "VENÂNCIO AIRES (CARIN)")

    async def test_history_failure_never_breaks_the_caller(self):
        """O relatório já está pronto neste ponto: o banco não pode custá-lo."""

        def exploding_session_factory():
            raise RuntimeError("banco indisponível")

        self.service.db.session_factory = exploding_session_factory

        response = SearchResponse(
            query="7891058003555",
            ean="7891058003555",
            total_found=0,
            quotes=[
                PriceQuote(
                    pharmacy_key=PharmacyEnum.SAO_JOAO,
                    pharmacy_name="Farmácias São João",
                    ean="7891058003555",
                    status=ScrapeStatusEnum.SUCCESS,
                    price=3.91,
                )
            ],
        )

        self.assertIsNone(await self.service.record_search(response))
