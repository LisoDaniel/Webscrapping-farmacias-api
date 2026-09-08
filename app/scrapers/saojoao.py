from typing import Optional
from app.core.logging import logger
from app.models.product import PharmacyEnum, PriceQuote, ScrapeStatusEnum
from app.scrapers.base import BaseScraper


class SaoJoaoScraper(BaseScraper):
    pharmacy_key = PharmacyEnum.SAO_JOAO
    name = "Farmácias São João"
    base_url = "https://www.saojoaofarmacias.com.br"

    def _parse_vtex_product(self, product: dict, requested_ean: Optional[str] = None) -> PriceQuote:
        product_name = product.get("productName")
        product_url = product.get("link")
        
        items = product.get("items", [])
        if not items:
            return PriceQuote(
                pharmacy_key=self.pharmacy_key,
                pharmacy_name=self.name,
                ean=requested_ean,
                status=ScrapeStatusEnum.NOT_FOUND
            )

        item = items[0]
        found_ean = item.get("ean")
        sellers = item.get("sellers", [])
        if not sellers:
            return PriceQuote(
                pharmacy_key=self.pharmacy_key,
                pharmacy_name=self.name,
                ean=requested_ean or found_ean,
                product_name=product_name,
                product_url=product_url,
                status=ScrapeStatusEnum.NOT_FOUND
            )

        offer = sellers[0].get("commertialOffer", {})
        price = offer.get("Price")
        list_price = offer.get("ListPrice")
        available = offer.get("IsAvailable", False)

        discount = self.calculate_discount(price, list_price)

        return PriceQuote(
            pharmacy_key=self.pharmacy_key,
            pharmacy_name=self.name,
            product_name=product_name,
            price=float(price) if price is not None else None,
            list_price=float(list_price) if list_price is not None else None,
            discount_percentage=discount,
            available=available,
            product_url=product_url,
            ean=requested_ean or found_ean,
            status=ScrapeStatusEnum.SUCCESS
        )

    async def search_by_ean(self, ean: str) -> PriceQuote:
        url = f"{self.base_url}/api/catalog_system/pub/products/search?ft={ean}"
        async with self.get_http_client() as client:
            try:
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, list) and len(data) > 0:
                        return self._parse_vtex_product(data[0], requested_ean=ean)
                return PriceQuote(
                    pharmacy_key=self.pharmacy_key,
                    pharmacy_name=self.name,
                    ean=ean,
                    status=ScrapeStatusEnum.NOT_FOUND
                )
            except Exception as e:
                logger.error(f"[{self.name}] Erro ao buscar EAN {ean}: {e}")
                return PriceQuote(
                    pharmacy_key=self.pharmacy_key,
                    pharmacy_name=self.name,
                    ean=ean,
                    status=ScrapeStatusEnum.ERROR,
                    error_message=str(e)
                )

    async def search_by_term(self, term: str) -> PriceQuote:
        url = f"{self.base_url}/api/catalog_system/pub/products/search?ft={term}"
        async with self.get_http_client() as client:
            try:
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, list) and len(data) > 0:
                        return self._parse_vtex_product(data[0])
                return PriceQuote(
                    pharmacy_key=self.pharmacy_key,
                    pharmacy_name=self.name,
                    status=ScrapeStatusEnum.NOT_FOUND
                )
            except Exception as e:
                logger.error(f"[{self.name}] Erro ao buscar termo '{term}': {e}")
                return PriceQuote(
                    pharmacy_key=self.pharmacy_key,
                    pharmacy_name=self.name,
                    status=ScrapeStatusEnum.ERROR,
                    error_message=str(e)
                )
