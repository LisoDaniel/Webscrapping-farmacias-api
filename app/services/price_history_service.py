"""Persistência e consulta do histórico de preços coletados."""

from __future__ import annotations

from typing import Iterable, Optional, TYPE_CHECKING

from sqlalchemy import select

from app.core.locations import normalize_state
from app.core.logging import logger
from app.db.models import PriceQuoteRecord, ProductRecord, ScrapeRunRecord
from app.db.session import Database, database
from app.models.client import ClientInfo
from app.models.history import PriceHistoryItem, PriceHistorySummary
from app.models.product import PharmacyEnum, PriceQuote, ProductItem, SearchResponse

if TYPE_CHECKING:
    from app.services.validation_service import ValidationReport


class PriceHistoryService:
    """Registra cotações imutáveis e permite consultar a evolução por EAN."""

    def __init__(self, db: Database = database):
        self.db = db

    @staticmethod
    def _fit(value: Optional[str], length: int) -> Optional[str]:
        """Ajusta o texto ao limite da coluna em vez de deixar o INSERT falhar."""
        if value is None:
            return None
        text = str(value).strip()
        return text[:length] if text else None

    async def _get_or_create_product(
        self,
        session,
        ean: Optional[str],
        name: str,
        laboratory: Optional[str] = None,
        product_group: Optional[str] = None,
    ) -> ProductRecord:
        product = None
        if ean:
            product = await session.scalar(select(ProductRecord).where(ProductRecord.ean == ean))
        if product is None:
            product = ProductRecord(
                ean=ean,
                name=name or f"Produto sem identificação ({ean or 'consulta textual'})",
                laboratory=laboratory,
                product_group=product_group,
            )
            session.add(product)
            await session.flush()
            return product

        if name:
            product.name = name
        if laboratory:
            product.laboratory = laboratory
        if product_group:
            product.product_group = product_group
        return product

    async def _record(
        self,
        *,
        source: str,
        query: Optional[str],
        ean: Optional[str],
        client_name: Optional[str],
        cep: Optional[str],
        city: Optional[str],
        state: Optional[str],
        items: Iterable[tuple[Optional[str], str, Optional[str], Optional[str], PriceQuote]],
    ) -> Optional[str]:
        try:
            async with self.db.session_factory() as session:
                async with session.begin():
                    run = ScrapeRunRecord(
                        source=source,
                        query=self._fit(query, 500),
                        ean=self._fit(ean, 14),
                        client_name=self._fit(client_name, 255),
                        cep=self._fit(cep, 8),
                        city=self._fit(city, 120),
                        # Última linha de defesa antes do varchar(2): as
                        # planilhas trazem o estado por extenso com frequência.
                        state=normalize_state(state),
                    )
                    session.add(run)
                    await session.flush()

                    for product_ean, product_name, laboratory, product_group, quote in items:
                        product = await self._get_or_create_product(
                            session,
                            product_ean or quote.ean,
                            product_name
                            or quote.product_name
                            or query
                            or "Produto sem identificação",
                            laboratory,
                            product_group,
                        )
                        session.add(
                            PriceQuoteRecord(
                                scrape_run_id=run.id,
                                product_id=product.id,
                                pharmacy_key=quote.pharmacy_key.value,
                                pharmacy_name=quote.pharmacy_name,
                                price=quote.price,
                                list_price=quote.list_price,
                                discount_percentage=quote.discount_percentage,
                                available=quote.available,
                                status=quote.status.value,
                                product_url=quote.product_url,
                                error_message=quote.error_message,
                                scraped_at=quote.scraped_at,
                            )
                        )
                    return run.id
        except Exception as exc:
            # O histórico é um subproduto da coleta. A consulta e o relatório já
            # foram produzidos com sucesso neste ponto — perdê-los porque o
            # banco recusou uma linha seria trocar o entregável pelo registro
            # dele. Falha alto no log e segue.
            logger.exception(f"Falha ao gravar o histórico de preços ({source}): {exc}")
            return None

    async def record_search(self, response: SearchResponse) -> Optional[str]:
        """Salva uma pesquisa avulsa feita pela API ou CLI."""
        items = [
            (quote.ean or response.ean, quote.product_name or response.query, None, None, quote)
            for quote in response.quotes
        ]
        return await self._record(
            source="search", query=response.query, ean=response.ean,
            client_name=None, cep=response.cep, city=response.city, state=response.state, items=items,
        )

    async def record_client_scrape(
        self,
        client: ClientInfo,
        products: Iterable[ProductItem],
        *,
        cep: Optional[str] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
    ) -> Optional[str]:
        """Salva todas as cotações de uma varredura de planilha em uma execução."""
        items = [
            (product.ean, product.name, product.laboratory, product.group, quote)
            for product in products
            for quote in product.quotes
        ]
        return await self._record(
            source="client_scrape", query=None, ean=None, client_name=client.client_name,
            cep=cep or client.cep, city=city or client.city, state=state or client.state, items=items,
        )

    async def record_validation(self, report: "ValidationReport") -> Optional[str]:
        """Armazena também o resultado técnico da validação dos scrapers."""
        items = [
            (
                entry.ean,
                entry.product_name or entry.product_label,
                None,
                None,
                PriceQuote(
                    pharmacy_key=entry.pharmacy_key,
                    pharmacy_name=entry.pharmacy_name,
                    product_name=entry.product_name,
                    price=entry.price,
                    product_url=entry.product_url,
                    ean=entry.ean,
                    status=entry.status,
                    error_message=entry.error_message,
                ),
            )
            for entry in report.entries
        ]
        return await self._record(
            source="validation", query="Validação operacional de scrapers", ean=None,
            client_name=None, cep=report.cep, city=None, state=None, items=items,
        )

    @staticmethod
    def _to_history_item(quote: PriceQuoteRecord, product: ProductRecord, run: ScrapeRunRecord) -> PriceHistoryItem:
        return PriceHistoryItem(
            run_id=run.id, ean=product.ean or "", product_name=product.name,
            pharmacy_key=PharmacyEnum(quote.pharmacy_key), pharmacy_name=quote.pharmacy_name,
            price=quote.price, list_price=quote.list_price, available=quote.available,
            status=quote.status, product_url=quote.product_url, error_message=quote.error_message,
            cep=run.cep, city=run.city, state=run.state, scraped_at=quote.scraped_at,
        )

    async def get_history(
        self, ean: str, pharmacy: Optional[PharmacyEnum] = None, limit: int = 100,
    ) -> list[PriceHistoryItem]:
        statement = (
            select(PriceQuoteRecord, ProductRecord, ScrapeRunRecord)
            .join(ProductRecord, PriceQuoteRecord.product_id == ProductRecord.id)
            .join(ScrapeRunRecord, PriceQuoteRecord.scrape_run_id == ScrapeRunRecord.id)
            .where(ProductRecord.ean == ean)
            .order_by(PriceQuoteRecord.scraped_at.desc())
            .limit(limit)
        )
        if pharmacy:
            statement = statement.where(PriceQuoteRecord.pharmacy_key == pharmacy.value)
        async with self.db.session_factory() as session:
            rows = (await session.execute(statement)).all()
        return [self._to_history_item(quote, product, run) for quote, product, run in rows]

    async def get_summary(self, ean: str) -> PriceHistorySummary:
        history = await self.get_history(ean, limit=500)
        latest: dict[PharmacyEnum, PriceHistoryItem] = {}
        for item in history:
            if item.pharmacy_key not in latest:
                latest[item.pharmacy_key] = item
        return PriceHistorySummary(ean=ean, total_quotes=len(history), latest_prices=list(latest.values()))
