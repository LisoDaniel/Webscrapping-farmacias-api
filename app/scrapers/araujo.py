"""Consulta de catálogo da Farmácias Araujo.

O catálogo é VTEX, mas pode responder 403 quando o WAF identifica tráfego não
interativo. Esse caso é exposto como ``BLOCKED`` para que relatórios não o
confundam com produto inexistente.
"""

from typing import Any, Optional
from urllib.parse import quote

from app.core.logging import logger
from app.models.product import PharmacyEnum, PriceQuote, ScrapeStatusEnum
from app.scrapers.base import BaseScraper


class AraujoScraper(BaseScraper):
    pharmacy_key = PharmacyEnum.ARAUJO
    name = "Farmácias Araujo"
    base_url = "https://www.araujo.com.br"

    def _quote(self, product: dict[str, Any], requested_ean: Optional[str] = None) -> PriceQuote:
        items = product.get("items") or []
        item = next((candidate for candidate in items if str(candidate.get("ean")) == requested_ean), None)
        item = item or (items[0] if items else {})
        offer = ((item.get("sellers") or [{}])[0].get("commertialOffer") or {})
        price = offer.get("Price") or offer.get("spotPrice")
        list_price = offer.get("ListPrice")
        product_url = product.get("link") or product.get("linkText") or ""
        if product_url and not product_url.startswith("http"):
            product_url = f"{self.base_url}{product_url if product_url.startswith('/') else '/' + product_url}"

        if price is None:
            return PriceQuote(
                pharmacy_key=self.pharmacy_key, pharmacy_name=self.name,
                product_name=product.get("productName"), product_url=product_url or None,
                ean=item.get("ean") or requested_ean, status=ScrapeStatusEnum.NOT_FOUND,
            )

        price_float = float(price)
        list_price_float = float(list_price) if list_price is not None else None
        return PriceQuote(
            pharmacy_key=self.pharmacy_key, pharmacy_name=self.name,
            product_name=product.get("productName"), price=price_float,
            list_price=list_price_float,
            discount_percentage=self.calculate_discount(price_float, list_price_float),
            available=bool(offer.get("AvailableQuantity", 0)), product_url=product_url or None,
            ean=item.get("ean") or requested_ean, status=ScrapeStatusEnum.SUCCESS,
        )

    async def _search_catalog(self, query: str, requested_ean: Optional[str] = None) -> PriceQuote:
        # Rota de catálogo VTEX documentada pelo próprio storefront da rede.
        url = f"{self.base_url}/api/catalog_system/pub/products/search/{quote(query)}"
        async with self.get_http_client() as client:
            try:
                response = await client.get(url)
            except Exception as exc:
                logger.error(f"[{self.name}] Erro de conexão: {exc}")
                return PriceQuote(pharmacy_key=self.pharmacy_key, pharmacy_name=self.name,
                                  ean=requested_ean, status=ScrapeStatusEnum.ERROR, error_message=str(exc))

        if response.status_code in (401, 403, 429):
            return PriceQuote(
                pharmacy_key=self.pharmacy_key, pharmacy_name=self.name, ean=requested_ean,
                status=ScrapeStatusEnum.BLOCKED,
                error_message=f"Catálogo bloqueou a consulta (HTTP {response.status_code}).",
            )
        if response.status_code != 200:
            return PriceQuote(pharmacy_key=self.pharmacy_key, pharmacy_name=self.name,
                              ean=requested_ean, status=ScrapeStatusEnum.ERROR,
                              error_message=f"Resposta inesperada do catálogo (HTTP {response.status_code}).")
        try:
            products = response.json()
        except ValueError:
            return PriceQuote(pharmacy_key=self.pharmacy_key, pharmacy_name=self.name,
                              ean=requested_ean, status=ScrapeStatusEnum.ERROR,
                              error_message="O catálogo retornou uma resposta inválida.")
        if not products:
            return PriceQuote(pharmacy_key=self.pharmacy_key, pharmacy_name=self.name,
                              ean=requested_ean, status=ScrapeStatusEnum.NOT_FOUND)
        return self._quote(products[0], requested_ean)

    async def search_by_ean(self, ean: str) -> PriceQuote:
        return await self._search_catalog(ean, requested_ean=ean)

    async def search_by_term(self, term: str) -> PriceQuote:
        return await self._search_catalog(term)
