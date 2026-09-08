import abc
from typing import Optional
import httpx

from app.core.config import settings
from app.core.logging import logger
from app.models.product import PharmacyEnum, PriceQuote, ScrapeStatusEnum


class BaseScraper(abc.ABC):
    """Classe base abstrata para todos os scrapers de farmácias."""

    pharmacy_key: PharmacyEnum
    name: str
    base_url: str

    def __init__(self, timeout: Optional[float] = None):
        self.timeout = timeout or settings.SCRAPER_TIMEOUT_SECONDS
        self.headers = {
            "User-Agent": settings.DEFAULT_USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        self.cep: Optional[str] = None
        self.city: Optional[str] = None
        self.state: Optional[str] = None

    def configure_location(
        self,
        cep: Optional[str] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
    ) -> "BaseScraper":
        """Define o contexto regional da busca quando a rede oferece essa opção."""
        self.cep = cep
        self.city = city
        self.state = state
        return self

    def get_http_client(self) -> httpx.AsyncClient:
        """Cria um cliente HTTP assíncrono com configurações padrão."""
        return httpx.AsyncClient(
            headers=self.headers,
            timeout=self.timeout,
            follow_redirects=True,
            verify=True
        )

    def calculate_discount(self, price: Optional[float], list_price: Optional[float]) -> Optional[float]:
        """Calcula o percentual de desconto entre preço de tabela e preço promocional."""
        if price and list_price and list_price > price and list_price > 0:
            return round(((list_price - price) / list_price) * 100, 1)
        return 0.0

    @abc.abstractmethod
    async def search_by_ean(self, ean: str) -> PriceQuote:
        """Busca o produto pelo código de barras EAN."""
        pass

    @abc.abstractmethod
    async def search_by_term(self, term: str) -> PriceQuote:
        """Busca o produto pelo nome ou termo textual."""
        pass

    async def search(self, ean: Optional[str] = None, term: Optional[str] = None) -> PriceQuote:
        """
        Orquestra a busca: prioriza o EAN (exato e confiável).
        Se não encontrar por EAN e tiver um termo, tenta fallback por termo.
        """
        clean_ean = str(ean).strip() if ean else None
        # Remove zeros à esquerda ou sufixos decimais acidentais
        if clean_ean and clean_ean.endswith(".0"):
            clean_ean = clean_ean[:-2]

        ean_quote: Optional[PriceQuote] = None
        if clean_ean and len(clean_ean) >= 7:
            try:
                ean_quote = await self.search_by_ean(clean_ean)
                if ean_quote.status == ScrapeStatusEnum.SUCCESS and ean_quote.price is not None:
                    return ean_quote

                # Um bloqueio ou erro técnico não deve ser disfarçado por uma
                # busca textual. Isso também preserva o diagnóstico correto no
                # relatório de validação dos scrapers.
                if ean_quote.status in (ScrapeStatusEnum.BLOCKED, ScrapeStatusEnum.ERROR):
                    return ean_quote
            except Exception as e:
                logger.warning(f"[{self.name}] Falha na busca por EAN {clean_ean}: {e}")

        # Fallback por nome/termo
        if term and term.strip():
            clean_term = term.strip()
            try:
                return await self.search_by_term(clean_term)
            except Exception as e:
                logger.warning(f"[{self.name}] Falha na busca por termo '{clean_term}': {e}")
                return PriceQuote(
                    pharmacy_key=self.pharmacy_key,
                    pharmacy_name=self.name,
                    ean=clean_ean,
                    status=ScrapeStatusEnum.ERROR,
                    error_message=str(e)
                )

        if ean_quote is not None:
            return ean_quote

        return PriceQuote(
            pharmacy_key=self.pharmacy_key,
            pharmacy_name=self.name,
            ean=clean_ean,
            status=ScrapeStatusEnum.NOT_FOUND
        )
