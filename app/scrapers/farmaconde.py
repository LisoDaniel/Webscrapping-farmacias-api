"""Consulta de catálogo público VTEX da Farma Conde."""

from typing import Any, Optional
from urllib.parse import quote

from app.core.logging import logger
from app.models.product import PharmacyEnum, PriceQuote, ScrapeStatusEnum
from app.scrapers.base import BaseScraper


class FarmaCondeScraper(BaseScraper):
    pharmacy_key = PharmacyEnum.FARMA_CONDE
    name = "Farma Conde"
    base_url = "https://www.farmaconde.com.br"

    def _not_found(self, requested_ean: Optional[str] = None) -> PriceQuote:
        return PriceQuote(
            pharmacy_key=self.pharmacy_key,
            pharmacy_name=self.name,
            ean=requested_ean,
            status=ScrapeStatusEnum.NOT_FOUND,
        )

    @staticmethod
    def _is_catalog_success_status(status_code: int) -> bool:
        """A VTEX pode paginar a resposta de busca com HTTP 206."""
        return status_code in (200, 206)

    def _parse_product(self, product: dict[str, Any], requested_ean: Optional[str] = None) -> PriceQuote:
        items = product.get("items") or []
        item = None
        if requested_ean:
            item = next((candidate for candidate in items if str(candidate.get("ean")) == requested_ean), None)
            if item is None:
                return self._not_found(requested_ean)
        elif items:
            item = items[0]
        if not item:
            return self._not_found(requested_ean)

        offer = ((item.get("sellers") or [{}])[0].get("commertialOffer") or {})
        price = offer.get("Price")
        if price is None:
            return PriceQuote(
                pharmacy_key=self.pharmacy_key,
                pharmacy_name=self.name,
                product_name=product.get("productName"),
                product_url=product.get("link"),
                ean=item.get("ean") or requested_ean,
                status=ScrapeStatusEnum.NOT_FOUND,
            )

        list_price = offer.get("ListPrice")
        price_float = float(price)
        list_price_float = float(list_price) if list_price is not None else None
        return PriceQuote(
            pharmacy_key=self.pharmacy_key,
            pharmacy_name=self.name,
            product_name=product.get("productName"),
            price=price_float,
            list_price=list_price_float,
            discount_percentage=self.calculate_discount(price_float, list_price_float),
            available=bool(offer.get("IsAvailable", False)),
            product_url=product.get("link"),
            ean=item.get("ean") or requested_ean,
            status=ScrapeStatusEnum.SUCCESS,
        )

    async def _search(self, term: str, requested_ean: Optional[str] = None) -> PriceQuote:
        url = f"{self.base_url}/api/catalog_system/pub/products/search?ft={quote(term)}"
        async with self.get_http_client() as client:
            try:
                response = await client.get(url)
            except Exception as exc:
                logger.error(f"[{self.name}] Erro de conexão: {exc}")
                return PriceQuote(
                    pharmacy_key=self.pharmacy_key,
                    pharmacy_name=self.name,
                    ean=requested_ean,
                    status=ScrapeStatusEnum.ERROR,
                    error_message=str(exc),
                )

        if response.status_code in (401, 403, 429):
            return PriceQuote(
                pharmacy_key=self.pharmacy_key,
                pharmacy_name=self.name,
                ean=requested_ean,
                status=ScrapeStatusEnum.BLOCKED,
                error_message=f"Catálogo bloqueou a consulta (HTTP {response.status_code}).",
            )
        # A busca VTEX da Farma Conde pode responder 206 quando entrega uma
        # página parcial do catálogo; o corpo continua sendo JSON válido.
        if not self._is_catalog_success_status(response.status_code):
            return PriceQuote(
                pharmacy_key=self.pharmacy_key,
                pharmacy_name=self.name,
                ean=requested_ean,
                status=ScrapeStatusEnum.ERROR,
                error_message=f"Resposta inesperada do catálogo (HTTP {response.status_code}).",
            )
        try:
            products = response.json()
        except ValueError:
            return PriceQuote(
                pharmacy_key=self.pharmacy_key,
                pharmacy_name=self.name,
                ean=requested_ean,
                status=ScrapeStatusEnum.ERROR,
                error_message="O catálogo retornou uma resposta inválida.",
            )
        if not isinstance(products, list) or not products:
            return self._not_found(requested_ean)

        if requested_ean:
            exact_product = next(
                (
                    product
                    for product in products
                    if any(str(item.get("ean")) == requested_ean for item in product.get("items") or [])
                ),
                None,
            )
            return self._parse_product(exact_product, requested_ean) if exact_product else self._not_found(requested_ean)
        return self._parse_product(products[0])

    async def search_by_ean(self, ean: str) -> PriceQuote:
        return await self._search(ean, requested_ean=ean)

    async def search_by_term(self, term: str) -> PriceQuote:
        return await self._search(term)
