import asyncio
from typing import List, Optional
from app.core.config import settings
from app.core.logging import logger
from app.models.product import (
    PharmacyEnum,
    PriceQuote,
    ProductItem,
    SearchRequest,
    SearchResponse,
    ScrapeStatusEnum,
)
from app.scrapers.registry import ScraperRegistry
from app.services.cep_service import CepService


class ScraperService:
    """Orquestrador de serviços de scraping assíncrono."""

    def __init__(self):
        self.semaphore = asyncio.Semaphore(settings.SCRAPER_MAX_CONCURRENCY)

    async def _execute_single_scraper(
        self,
        pharmacy: PharmacyEnum,
        ean: Optional[str] = None,
        term: Optional[str] = None,
        cep: Optional[str] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
    ) -> PriceQuote:
        async with self.semaphore:
            scraper = ScraperRegistry.get_scraper(pharmacy)
            if not scraper:
                return PriceQuote(
                    pharmacy_key=pharmacy,
                    pharmacy_name=pharmacy.value,
                    ean=ean,
                    status=ScrapeStatusEnum.ERROR,
                    error_message=f"Scraper não implementado para {pharmacy.value}"
                )
            try:
                scraper.configure_location(cep=cep, city=city, state=state)
                return await scraper.search(ean=ean, term=term)
            except Exception as e:
                logger.error(f"Erro no scraper {pharmacy.value}: {e}")
                return PriceQuote(
                    pharmacy_key=pharmacy,
                    pharmacy_name=scraper.name,
                    ean=ean,
                    status=ScrapeStatusEnum.ERROR,
                    error_message=str(e)
                )

    async def search(self, request: SearchRequest) -> SearchResponse:
        """Executa busca paralela em todas as farmácias solicitadas."""
        location = await CepService.resolve(request.cep)
        target_pharmacies = request.pharmacies
        if not target_pharmacies:
            target_pharmacies = list(ScraperRegistry._scrapers.keys())

        tasks = [
            self._execute_single_scraper(
                pharmacy=p,
                ean=request.ean,
                term=request.query,
                cep=location.cep if location else None,
                city=location.city if location else None,
                state=location.state if location else None,
            )
            for p in target_pharmacies
        ]

        quotes = await asyncio.gather(*tasks)

        # Identifica a cotação mais barata disponível
        valid_quotes = [
            q for q in quotes
            if q.status == ScrapeStatusEnum.SUCCESS and q.price is not None and q.price > 0
        ]
        cheapest = min(valid_quotes, key=lambda q: q.price) if valid_quotes else None

        query_str = request.ean or request.query or ""
        return SearchResponse(
            query=query_str,
            ean=request.ean,
            total_found=len(valid_quotes),
            quotes=quotes,
            cheapest_quote=cheapest,
            cep=location.cep if location else None,
            city=location.city if location else None,
            state=location.state if location else None,
        )

    async def scrape_product_item(
        self,
        item: ProductItem,
        pharmacies: List[PharmacyEnum],
        cep: Optional[str] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
    ) -> ProductItem:
        """Enriquece um ProductItem com cotações das farmácias indicadas."""
        tasks = [
            self._execute_single_scraper(
                pharmacy=p,
                ean=item.ean,
                term=item.name,
                cep=cep,
                city=city,
                state=state,
            )
            for p in pharmacies
        ]
        quotes = await asyncio.gather(*tasks)
        item.quotes = quotes
        return item
