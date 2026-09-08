from typing import Optional
from urllib.parse import quote
from app.core.logging import logger
from app.models.product import PharmacyEnum, PriceQuote, ScrapeStatusEnum
from app.scrapers.base import BaseScraper


class PachecoScraper(BaseScraper):
    pharmacy_key = PharmacyEnum.PACHECO
    name = "Drogarias Pacheco"
    base_url = "https://www.drogariaspacheco.com.br"

    def _parse_product(self, product: dict, requested_ean: Optional[str] = None) -> PriceQuote:
        product_name = product.get("productName")
        raw_link = product.get("link", "")
        product_url = f"{self.base_url}{raw_link}" if raw_link.startswith("/") else raw_link

        items = product.get("items", [])
        if not items:
            return PriceQuote(
                pharmacy_key=self.pharmacy_key,
                pharmacy_name=self.name,
                ean=requested_ean,
                product_name=product_name,
                product_url=product_url,
                status=ScrapeStatusEnum.NOT_FOUND
            )

        matching_item = items[0]
        if requested_ean:
            for it in items:
                if it.get("ean") == requested_ean:
                    matching_item = it
                    break

        found_ean = matching_item.get("ean") or requested_ean
        sellers = matching_item.get("sellers", [])
        if not sellers:
            return PriceQuote(
                pharmacy_key=self.pharmacy_key,
                pharmacy_name=self.name,
                ean=found_ean,
                product_name=product_name,
                product_url=product_url,
                status=ScrapeStatusEnum.NOT_FOUND
            )

        offer = sellers[0].get("commertialOffer", {})
        price = offer.get("Price") or offer.get("spotPrice")
        list_price = offer.get("ListPrice")
        avail_qty = offer.get("AvailableQuantity", 0)
        available = bool(avail_qty and avail_qty > 0 and price and price > 0)

        price_float = float(price) if price is not None else None
        list_price_float = float(list_price) if list_price is not None else None
        discount = self.calculate_discount(price_float, list_price_float)

        return PriceQuote(
            pharmacy_key=self.pharmacy_key,
            pharmacy_name=self.name,
            product_name=product_name,
            price=price_float,
            list_price=list_price_float,
            discount_percentage=discount,
            available=available,
            product_url=product_url,
            ean=found_ean,
            status=ScrapeStatusEnum.SUCCESS
        )

    async def search_by_ean(self, ean: str) -> PriceQuote:
        encoded_query = quote(ean)
        url = f"{self.base_url}/api/io/_v/api/intelligent-search/product_search/?query={encoded_query}"

        async with self.get_http_client() as client:
            try:
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json()
                    products = data.get("products", [])
                    if products:
                        for prod in products:
                            item_eans = [it.get("ean") for it in prod.get("items", [])]
                            if ean in item_eans:
                                return self._parse_product(prod, requested_ean=ean)
                        return self._parse_product(products[0], requested_ean=ean)

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
        encoded_query = quote(term)
        url = f"{self.base_url}/api/io/_v/api/intelligent-search/product_search/?query={encoded_query}"

        async with self.get_http_client() as client:
            try:
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json()
                    products = data.get("products", [])
                    if products:
                        return self._parse_product(products[0])

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
