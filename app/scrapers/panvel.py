"""Scraper da Panvel.

Estado atual: a rota de busca que o storefront expunha (``/api/v3/search``)
responde HTTP 404 e a página de busca é um shell Angular renderizado no
cliente, sem nenhum dado de produto no HTML. Ou seja, **não há hoje integração
funcional com a Panvel**.

Enquanto isso durar, toda consulta devolve ``ERROR`` com o motivo. O que não
pode acontecer é devolver ``NOT_FOUND``: isso faria o relatório do cliente
afirmar que o produto não existe na rede, quando na verdade nem chegamos a
perguntar. Um preço ausente é um incômodo; um preço ausente disfarçado de
"produto inexistente" é uma informação errada entregue ao consultor.

Restabelecer a cobertura depende de uma API ou feed autorizado pela rede — o
mesmo critério já adotado para a Araujo. A rota anterior só respondia mediante
um ``app-token`` extraído do bundle e um ``user-id`` de cliente real, o que
significaria forjar a sessão de um terceiro.
"""

from typing import Any, Optional

from app.core.logging import logger
from app.models.product import PharmacyEnum, PriceQuote, ScrapeStatusEnum
from app.scrapers.base import BaseScraper


class PanvelScraper(BaseScraper):
    pharmacy_key = PharmacyEnum.PANVEL
    name = "Panvel"
    base_url = "https://www.panvel.com"
    search_path = "/api/v1/search"

    def _result(
        self,
        status: ScrapeStatusEnum,
        ean: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> PriceQuote:
        return PriceQuote(
            pharmacy_key=self.pharmacy_key,
            pharmacy_name=self.name,
            ean=ean,
            status=status,
            error_message=error_message,
        )

    def _from_item(self, item: dict[str, Any], requested_ean: Optional[str] = None) -> PriceQuote:
        price_data = item.get("price") or item.get("discount") or {}
        price = (
            price_data.get("dealPrice")
            or price_data.get("price")
            or item.get("dealPrice")
            or item.get("price")
        )
        list_price = (
            price_data.get("originalPrice") or item.get("originalPrice") or item.get("listPrice")
        )
        link = item.get("link") or item.get("url") or item.get("seoUrl")
        if link and not link.startswith("http"):
            link = f"{self.base_url}{link if link.startswith('/') else '/' + link}"

        found_ean = str(item.get("ean") or item.get("barcode") or "").strip() or None
        if price is None:
            return PriceQuote(
                pharmacy_key=self.pharmacy_key,
                pharmacy_name=self.name,
                product_name=item.get("name"),
                product_url=link,
                ean=found_ean,
                status=ScrapeStatusEnum.NOT_FOUND,
            )

        price_float = float(price)
        list_price_float = float(list_price) if list_price is not None else None
        return PriceQuote(
            pharmacy_key=self.pharmacy_key,
            pharmacy_name=self.name,
            product_name=item.get("name") or item.get("productName"),
            price=price_float,
            list_price=list_price_float,
            discount_percentage=self.calculate_discount(price_float, list_price_float),
            available=bool(item.get("available", True)),
            product_url=link,
            ean=found_ean,
            status=ScrapeStatusEnum.SUCCESS,
        )

    def _parse_payload(
        self, payload: dict[str, Any], requested_ean: Optional[str] = None
    ) -> PriceQuote:
        items = payload.get("items") or payload.get("products") or []
        if not items:
            # Só aqui o "não encontrado" é legítimo: a rede respondeu e não tem
            # o produto.
            return self._result(ScrapeStatusEnum.NOT_FOUND, requested_ean)
        if requested_ean:
            exact = next(
                (
                    item
                    for item in items
                    if str(item.get("ean") or item.get("barcode") or "").strip() == requested_ean
                ),
                None,
            )
            # Sem SKU com o EAN exato, não cotamos outro item no lugar dele.
            return (
                self._from_item(exact, requested_ean)
                if exact
                else self._result(ScrapeStatusEnum.NOT_FOUND, requested_ean)
            )
        return self._from_item(items[0])

    async def _search(self, term: str, requested_ean: Optional[str] = None) -> PriceQuote:
        body = {
            "term": term,
            "itemsPerPage": 24,
            "currentPage": 1,
            "assortment": "mais relevantes",
            "filters": [],
            "searchOffers": False,
            "searchType": "term",
        }
        headers = {**self.headers, "Origin": self.base_url, "Referer": f"{self.base_url}/"}
        params = {"type": "CSR", "uf": self.state or "RS"}

        async with self.get_http_client() as client:
            try:
                response = await client.post(
                    f"{self.base_url}{self.search_path}",
                    json=body,
                    params=params,
                    headers=headers,
                )
            except Exception as exc:
                logger.error(f"[{self.name}] Erro de conexão: {exc}")
                return self._result(ScrapeStatusEnum.ERROR, requested_ean, str(exc))

        if response.status_code in (401, 403, 429):
            return self._result(
                ScrapeStatusEnum.BLOCKED,
                requested_ean,
                f"Busca Panvel bloqueada (HTTP {response.status_code}).",
            )
        if response.status_code != 200:
            return self._result(
                ScrapeStatusEnum.ERROR,
                requested_ean,
                f"Integração Panvel indisponível: a busca respondeu HTTP "
                f"{response.status_code}. É necessário um acesso autorizado à rede.",
            )
        try:
            payload = response.json()
        except ValueError:
            return self._result(
                ScrapeStatusEnum.ERROR,
                requested_ean,
                "A busca Panvel retornou uma resposta inválida.",
            )
        if not isinstance(payload, dict):
            return self._result(
                ScrapeStatusEnum.ERROR,
                requested_ean,
                "A busca Panvel retornou um formato inesperado.",
            )
        return self._parse_payload(payload, requested_ean)

    async def search_by_ean(self, ean: str) -> PriceQuote:
        return await self._search(ean, requested_ean=ean)

    async def search_by_term(self, term: str) -> PriceQuote:
        return await self._search(term)
