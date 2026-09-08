"""Base compartilhada para as redes de farmácia com storefront VTEX.

A busca por EAN usa o filtro de catálogo ``alternateIds_Ean``, que devolve
correspondência exata. O índice de texto livre ``ft`` não cobre o EAN em todas
as lojas e, quando cobre, pode trazer outro produto na primeira posição — o que
faria o relatório do cliente exibir o preço de um item diferente do consultado.
"""

from typing import Any, Optional
from urllib.parse import quote

from app.core.logging import logger
from app.models.product import PriceQuote, ScrapeStatusEnum
from app.scrapers.base import BaseScraper


class VtexCatalogScraper(BaseScraper):
    """Consulta a rota pública de catálogo VTEX com verificação de EAN."""

    catalog_path = "/api/catalog_system/pub/products/search"

    # ------------------------------------------------------------------
    # Construção de resultados

    def _result(
        self,
        status: ScrapeStatusEnum,
        *,
        ean: Optional[str] = None,
        product_name: Optional[str] = None,
        product_url: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> PriceQuote:
        return PriceQuote(
            pharmacy_key=self.pharmacy_key,
            pharmacy_name=self.name,
            ean=ean,
            product_name=product_name,
            product_url=product_url,
            status=status,
            error_message=error_message,
        )

    def _not_found(
        self,
        ean: Optional[str] = None,
        product_name: Optional[str] = None,
        product_url: Optional[str] = None,
    ) -> PriceQuote:
        return self._result(
            ScrapeStatusEnum.NOT_FOUND,
            ean=ean,
            product_name=product_name,
            product_url=product_url,
        )

    def _blocked(self, status_code: int, ean: Optional[str] = None) -> PriceQuote:
        return self._result(
            ScrapeStatusEnum.BLOCKED,
            ean=ean,
            error_message=f"Catálogo bloqueou a consulta (HTTP {status_code}).",
        )

    def _error(self, message: str, ean: Optional[str] = None) -> PriceQuote:
        return self._result(ScrapeStatusEnum.ERROR, ean=ean, error_message=message)

    # ------------------------------------------------------------------
    # Interpretação da resposta

    @staticmethod
    def _is_catalog_success_status(status_code: int) -> bool:
        """A VTEX responde 206 quando entrega uma página parcial do catálogo."""
        return status_code in (200, 206)

    def _absolute_url(self, link: Optional[str]) -> Optional[str]:
        if not link:
            return None
        if link.startswith("http"):
            return link
        return f"{self.base_url}{link if link.startswith('/') else '/' + link}"

    @staticmethod
    def _offer(item: dict[str, Any]) -> dict[str, Any]:
        sellers = item.get("sellers") or []
        return (sellers[0].get("commertialOffer") if sellers else None) or {}

    def _select_item(
        self, product: dict[str, Any], requested_ean: Optional[str] = None
    ) -> Optional[dict[str, Any]]:
        """Escolhe o SKU, exigindo EAN idêntico quando um EAN foi consultado."""
        items = product.get("items") or []
        if requested_ean:
            return next(
                (item for item in items if str(item.get("ean") or "").strip() == requested_ean),
                None,
            )
        return items[0] if items else None

    def _parse_product(
        self, product: dict[str, Any], requested_ean: Optional[str] = None
    ) -> PriceQuote:
        item = self._select_item(product, requested_ean)
        if item is None:
            # Sem SKU com o EAN exato o produto não serve de resposta: um item
            # parecido de outro código não pode ser cotado como se fosse este.
            return self._not_found(requested_ean)

        product_name = product.get("productName")
        product_url = self._absolute_url(product.get("link"))
        # O EAN só é repetido na cotação quando o próprio catálogo o confirma.
        found_ean = str(item.get("ean") or "").strip() or None

        offer = self._offer(item)
        price = offer.get("Price")
        if price is None:
            price = offer.get("spotPrice")
        if price is None:
            return self._not_found(found_ean, product_name=product_name, product_url=product_url)

        list_price = offer.get("ListPrice")
        price_float = float(price)
        list_price_float = float(list_price) if list_price is not None else None
        available = bool(offer.get("IsAvailable")) or (offer.get("AvailableQuantity") or 0) > 0

        return PriceQuote(
            pharmacy_key=self.pharmacy_key,
            pharmacy_name=self.name,
            product_name=product_name,
            price=price_float,
            list_price=list_price_float,
            discount_percentage=self.calculate_discount(price_float, list_price_float),
            available=available,
            product_url=product_url,
            ean=found_ean,
            status=ScrapeStatusEnum.SUCCESS,
        )

    # ------------------------------------------------------------------
    # Acesso HTTP

    async def _fetch_catalog(
        self, query_string: str, requested_ean: Optional[str] = None
    ) -> tuple[Optional[list], Optional[PriceQuote]]:
        """Retorna (produtos, falha); exatamente um dos dois vem preenchido."""
        url = f"{self.base_url}{self.catalog_path}?{query_string}"
        async with self.get_http_client() as client:
            try:
                response = await client.get(url)
            except Exception as exc:
                logger.error(f"[{self.name}] Erro de conexão: {exc}")
                return None, self._error(str(exc), requested_ean)

        if response.status_code in (401, 403, 429):
            return None, self._blocked(response.status_code, requested_ean)
        if not self._is_catalog_success_status(response.status_code):
            return None, self._error(
                f"Resposta inesperada do catálogo (HTTP {response.status_code}).", requested_ean
            )
        try:
            products = response.json()
        except ValueError:
            return None, self._error("O catálogo retornou uma resposta inválida.", requested_ean)
        if not isinstance(products, list):
            return None, self._error("O catálogo retornou uma resposta inválida.", requested_ean)
        return products, None

    async def search_by_ean(self, ean: str) -> PriceQuote:
        products, failure = await self._fetch_catalog(
            f"fq=alternateIds_Ean:{quote(ean)}", requested_ean=ean
        )
        if failure is not None:
            return failure

        # Preserva o diagnóstico mais informativo quando o EAN existe no
        # catálogo mas nenhuma oferta tem preço.
        fallback: Optional[PriceQuote] = None
        for product in products:
            parsed = self._parse_product(product, requested_ean=ean)
            if parsed.status == ScrapeStatusEnum.SUCCESS:
                return parsed
            if fallback is None and parsed.product_name:
                fallback = parsed
        return fallback or self._not_found(ean)

    async def search_by_term(self, term: str) -> PriceQuote:
        products, failure = await self._fetch_catalog(f"ft={quote(term)}")
        if failure is not None:
            return failure
        if not products:
            return self._not_found()
        return self._parse_product(products[0])


class VtexIntelligentSearchScraper(VtexCatalogScraper):
    """Redes que também expõem o Intelligent Search.

    A relevância dele por nome é melhor que a do catálogo, então ele fica com a
    busca textual. A busca por EAN continua no catálogo, único lugar onde existe
    o filtro de correspondência exata.
    """

    intelligent_search_path = "/api/io/_v/api/intelligent-search/product_search/"

    async def search_by_term(self, term: str) -> PriceQuote:
        url = f"{self.base_url}{self.intelligent_search_path}?query={quote(term)}"
        async with self.get_http_client() as client:
            try:
                response = await client.get(url)
            except Exception as exc:
                logger.error(f"[{self.name}] Erro de conexão: {exc}")
                return self._error(str(exc))

        if response.status_code in (401, 403, 429):
            return self._blocked(response.status_code)
        if not self._is_catalog_success_status(response.status_code):
            return self._error(f"Resposta inesperada da busca (HTTP {response.status_code}).")
        try:
            payload = response.json()
        except ValueError:
            return self._error("A busca retornou uma resposta inválida.")

        products = (payload or {}).get("products") or []
        if not products:
            return self._not_found()
        return self._parse_product(products[0])
