import asyncio
import random
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
        self.retry_attempts = max(1, settings.SCRAPER_RETRY_ATTEMPTS)
        self.retry_base_delay = settings.SCRAPER_RETRY_BASE_DELAY
        self.retry_max_delay = settings.SCRAPER_RETRY_MAX_DELAY

    def _atraso(self, tentativa: int) -> float:
        """Espera exponencial com folga aleatória entre as tentativas.

        A folga evita que as farmácias consultadas em paralelo repitam todas no
        mesmo instante depois de uma queda de rede.
        """
        atraso = self.retry_base_delay * (2 ** (tentativa - 1))
        return min(atraso, self.retry_max_delay) + random.uniform(0, self.retry_base_delay / 2)

    async def _dormir(self, segundos: float) -> None:
        await asyncio.sleep(segundos)

    async def _buscar_com_retry(
        self,
        scraper,
        pharmacy: PharmacyEnum,
        ean: Optional[str],
        term: Optional[str],
    ) -> PriceQuote:
        """Repete apenas falhas técnicas.

        ``ERROR`` significa que a consulta não chegou a acontecer — queda de
        rede, timeout, resposta ilegível — e repetir pode resolver.

        ``NOT_FOUND`` é uma resposta da loja, e ``BLOCKED`` é a loja recusando
        a consulta. Repetir o primeiro não muda nada; repetir o segundo é
        insistir com quem acabou de pedir para parar. Ambos saem na primeira
        tentativa.
        """
        ultima: Optional[PriceQuote] = None
        for tentativa in range(1, self.retry_attempts + 1):
            try:
                cotacao = await scraper.search(ean=ean, term=term)
            except Exception as exc:
                logger.error(f"Erro no scraper {pharmacy.value}: {exc}")
                cotacao = PriceQuote(
                    pharmacy_key=pharmacy,
                    pharmacy_name=scraper.name,
                    ean=ean,
                    status=ScrapeStatusEnum.ERROR,
                    error_message=str(exc),
                )

            if cotacao.status != ScrapeStatusEnum.ERROR:
                return cotacao

            ultima = cotacao
            if tentativa < self.retry_attempts:
                espera = self._atraso(tentativa)
                logger.warning(
                    f"[{scraper.name}] tentativa {tentativa}/{self.retry_attempts} falhou "
                    f"({cotacao.error_message}); repetindo em {espera:.1f}s"
                )
                await self._dormir(espera)

        return ultima

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
            scraper.configure_location(cep=cep, city=city, state=state)
            return await self._buscar_com_retry(scraper, pharmacy, ean, term)

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
