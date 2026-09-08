"""Scraper da Panvel usando a busca JSON do storefront Angular.

Há também um fallback para o HTML SSR. Isso evita depender de Playwright e
mantém a busca funcional se a rota de API mudar, sem mascarar bloqueios como
"produto não encontrado".
"""

import json
import re
from html import unescape
from typing import Any, Optional
from urllib.parse import quote

from app.core.logging import logger
from app.models.product import PharmacyEnum, PriceQuote, ScrapeStatusEnum
from app.scrapers.base import BaseScraper


class PanvelScraper(BaseScraper):
    pharmacy_key = PharmacyEnum.PANVEL
    name = "Panvel"
    base_url = "https://www.panvel.com"
    _app_token = "ZYkPuDaVJEiD"

    def _not_found(self, ean: Optional[str] = None) -> PriceQuote:
        return PriceQuote(pharmacy_key=self.pharmacy_key, pharmacy_name=self.name,
                          ean=ean, status=ScrapeStatusEnum.NOT_FOUND)

    def _from_item(self, item: dict[str, Any], requested_ean: Optional[str] = None) -> PriceQuote:
        price_data = item.get("price") or item.get("discount") or {}
        price = price_data.get("dealPrice") or price_data.get("price") or item.get("dealPrice") or item.get("price")
        list_price = price_data.get("originalPrice") or item.get("originalPrice") or item.get("listPrice")
        link = item.get("link") or item.get("url") or item.get("seoUrl")
        if link and not link.startswith("http"):
            link = f"{self.base_url}{link if link.startswith('/') else '/' + link}"
        if price is None:
            return PriceQuote(pharmacy_key=self.pharmacy_key, pharmacy_name=self.name,
                              product_name=item.get("name"), product_url=link,
                              ean=str(item.get("ean") or requested_ean or "") or None,
                              status=ScrapeStatusEnum.NOT_FOUND)
        price_float = float(price)
        list_price_float = float(list_price) if list_price is not None else None
        return PriceQuote(
            pharmacy_key=self.pharmacy_key, pharmacy_name=self.name,
            product_name=item.get("name") or item.get("productName"), price=price_float,
            list_price=list_price_float, discount_percentage=self.calculate_discount(price_float, list_price_float),
            available=bool(item.get("available", True)), product_url=link,
            ean=str(item.get("ean") or requested_ean or "") or None, status=ScrapeStatusEnum.SUCCESS,
        )

    def _parse_api_payload(self, payload: dict[str, Any], requested_ean: Optional[str] = None) -> PriceQuote:
        items = payload.get("items") or payload.get("products") or []
        if not items:
            return self._not_found(requested_ean)
        if requested_ean:
            exact = next((item for item in items if str(item.get("ean") or item.get("barcode")) == requested_ean), None)
            if exact:
                return self._from_item(exact, requested_ean)
        return self._from_item(items[0], requested_ean)

    def _parse_ssr_html(self, html: str, requested_ean: Optional[str] = None) -> Optional[PriceQuote]:
        # O storefront pode serializar o estado de busca como JSON no HTML SSR.
        for match in re.finditer(r'<script[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>', html, re.I | re.S):
            try:
                payload = json.loads(unescape(match.group(1)))
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(payload, dict) and (payload.get("items") or payload.get("products")):
                return self._parse_api_payload(payload, requested_ean)
        return None

    async def _search(self, term: str, requested_ean: Optional[str] = None) -> PriceQuote:
        body = {
            "term": term, "itemsPerPage": 24, "currentPage": 1,
            "assortment": "mais relevantes", "filters": [], "searchOffers": False,
            "searchType": "term",
        }
        headers = {
            **self.headers, "app-token": self._app_token, "user-id": "8601417",
            "client-ip": "1", "search-new": "A", "Origin": self.base_url,
            "Referer": f"{self.base_url}/panvel/buscarProduto.do?termoPesquisa={quote(term)}",
        }
        params = {"type": "CSR", "uf": self.state or "RS"}
        api_url = f"{self.base_url}/api/v3/search"
        async with self.get_http_client() as client:
            try:
                response = await client.post(api_url, json=body, params=params, headers=headers)
                if response.status_code == 200:
                    return self._parse_api_payload(response.json(), requested_ean)
                if response.status_code in (401, 403, 429):
                    return PriceQuote(pharmacy_key=self.pharmacy_key, pharmacy_name=self.name,
                                      ean=requested_ean, status=ScrapeStatusEnum.BLOCKED,
                                      error_message=f"Busca Panvel bloqueada (HTTP {response.status_code}).")
            except Exception as exc:
                logger.warning(f"[{self.name}] API de busca indisponível: {exc}")

            # Fallback deliberadamente leve: a página SSR não exige browser headless.
            try:
                page = await client.get(
                    f"{self.base_url}/panvel/buscarProduto.do",
                    params={"termoPesquisa": term}, headers={**self.headers, "Referer": self.base_url},
                )
                if page.status_code in (401, 403, 429):
                    return PriceQuote(pharmacy_key=self.pharmacy_key, pharmacy_name=self.name,
                                      ean=requested_ean, status=ScrapeStatusEnum.BLOCKED,
                                      error_message=f"Página Panvel bloqueada (HTTP {page.status_code}).")
                if page.status_code == 200:
                    parsed = self._parse_ssr_html(page.text, requested_ean)
                    if parsed:
                        return parsed
                return self._not_found(requested_ean)
            except Exception as exc:
                logger.error(f"[{self.name}] Erro na busca: {exc}")
                return PriceQuote(pharmacy_key=self.pharmacy_key, pharmacy_name=self.name,
                                  ean=requested_ean, status=ScrapeStatusEnum.ERROR, error_message=str(exc))

    async def search_by_ean(self, ean: str) -> PriceQuote:
        return await self._search(ean, requested_ean=ean)

    async def search_by_term(self, term: str) -> PriceQuote:
        return await self._search(term)
