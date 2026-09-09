"""Scrapers do grupo RD Saúde (Droga Raia e Drogasil).

O storefront responde 403 a clientes HTTP comuns, mas entrega o HTML a um
cliente que se identifica como curl. Isso já era feito antes, só que chamando
``curl.exe`` por subprocesso — abordagem com dois defeitos. Ela só funcionava no
Windows, e, pior, falhava dentro do servidor: o uvicorn roda em
``SelectorEventLoop``, onde ``asyncio`` não suporta subprocessos e
``create_subprocess_exec`` levanta ``NotImplementedError``. Na prática as duas
redes funcionavam pela CLI e devolviam "Falha na comunicação de rede" pela API e
pelo dashboard.

``curl_cffi`` faz a mesma requisição em processo, sem subprocesso e sem depender
do event loop. Não há impersonação de navegador aqui — imitar Chrome é
justamente o que faz o WAF responder 403; identificar-se como curl é o que
funciona.

A busca aceita o código de barras como termo e devolve o produto no
``__NEXT_DATA__`` do Next.js, mas **sem campo de EAN**: só ``sku``, nome e
preço. Como não há o que conferir no payload, a correspondência é confirmada
pela unicidade — um único produto para um código de 13 dígitos é a loja
identificando o item, enquanto uma busca por nome devolve treze. Resposta
ambígua não vira cotação.
"""

import json
import re
from typing import Any, Optional
from urllib.parse import quote

from curl_cffi.requests import AsyncSession

from app.core.logging import logger
from app.models.product import PharmacyEnum, PriceQuote, ScrapeStatusEnum
from app.scrapers.base import BaseScraper

_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


class BaseRDScraper(BaseScraper):
    """Base comum às duas bandeiras, que compartilham o mesmo storefront."""

    # O site entrega o conteúdo a quem se identifica honestamente como curl.
    fetch_headers = {"User-Agent": "curl/8.4.0", "Accept": "*/*"}

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

    async def _fetch(self, query: str) -> tuple[Optional[int], Optional[str]]:
        """Retorna (status HTTP, HTML). Status ``None`` indica falha de rede."""
        url = f"{self.base_url}/search?w={quote(query)}"
        try:
            async with AsyncSession(timeout=self.timeout) as session:
                response = await session.get(url, headers=self.fetch_headers)
                return response.status_code, response.text
        except Exception as exc:
            logger.error(f"[{self.name}] Erro de conexão: {exc}")
            return None, None

    @staticmethod
    def _products(html: str) -> Optional[list[dict[str, Any]]]:
        """Extrai a lista de produtos do estado do Next.js."""
        match = _NEXT_DATA.search(html or "")
        if not match:
            return None
        try:
            data = json.loads(match.group(1))
        except (json.JSONDecodeError, TypeError):
            return None
        page = data.get("props", {}).get("pageProps", {})
        # O storefront às vezes aninha pageProps dentro de pageProps.
        if isinstance(page.get("pageProps"), dict):
            page = page["pageProps"]
        products = (page.get("results") or {}).get("products")
        return products if isinstance(products, list) else None

    def _quote_from_product(
        self, product: dict[str, Any], requested_ean: Optional[str] = None
    ) -> PriceQuote:
        raw_url = product.get("url") or ""
        product_url = f"{self.base_url}{raw_url}" if raw_url.startswith("/") else (raw_url or None)

        price = product.get("priceService")
        if not isinstance(price, (int, float)) or isinstance(price, bool):
            return PriceQuote(
                pharmacy_key=self.pharmacy_key,
                pharmacy_name=self.name,
                product_name=product.get("name"),
                product_url=product_url,
                ean=requested_ean,
                status=ScrapeStatusEnum.NOT_FOUND,
            )

        price_float = float(price)
        raw_list_price = product.get("oldPrice") or product.get("listPrice")
        list_price = (
            float(raw_list_price)
            if isinstance(raw_list_price, (int, float)) and not isinstance(raw_list_price, bool)
            else None
        )

        return PriceQuote(
            pharmacy_key=self.pharmacy_key,
            pharmacy_name=self.name,
            product_name=product.get("name"),
            price=price_float,
            list_price=list_price,
            discount_percentage=self.calculate_discount(price_float, list_price),
            available=True,
            product_url=product_url,
            # O EAN consultado só é assumido quando a unicidade da resposta já
            # confirmou de qual produto se trata.
            ean=requested_ean,
            status=ScrapeStatusEnum.SUCCESS,
        )

    def _parse(self, html: str, requested_ean: Optional[str] = None) -> PriceQuote:
        products = self._products(html)
        if products is None:
            # Sem o estado do Next.js não dá para afirmar que o produto não
            # existe: a página pode ser um desafio do WAF.
            if "Access Denied" in (html or "") or "Reference #" in (html or ""):
                return self._result(
                    ScrapeStatusEnum.BLOCKED, requested_ean, "Bloqueio do WAF (Akamai)."
                )
            return self._result(
                ScrapeStatusEnum.ERROR, requested_ean, "A busca não devolveu o estado esperado."
            )
        if not products:
            return self._result(ScrapeStatusEnum.NOT_FOUND, requested_ean)

        if requested_ean:
            # Um código de barras que casa devolve exatamente um produto; mais
            # de um é busca textual e não identifica o item consultado.
            if len(products) != 1:
                return self._result(ScrapeStatusEnum.NOT_FOUND, requested_ean)
            return self._quote_from_product(products[0], requested_ean)
        return self._quote_from_product(products[0])

    async def _search(self, query: str, requested_ean: Optional[str] = None) -> PriceQuote:
        status, html = await self._fetch(query)
        if status is None:
            return self._result(
                ScrapeStatusEnum.ERROR, requested_ean, "Falha na comunicação de rede."
            )
        if status in (401, 403, 429):
            return self._result(
                ScrapeStatusEnum.BLOCKED,
                requested_ean,
                f"A busca bloqueou a consulta (HTTP {status}).",
            )
        if status != 200:
            return self._result(
                ScrapeStatusEnum.ERROR,
                requested_ean,
                f"Resposta inesperada da busca (HTTP {status}).",
            )
        return self._parse(html, requested_ean)

    async def search_by_ean(self, ean: str) -> PriceQuote:
        return await self._search(ean, requested_ean=ean)

    async def search_by_term(self, term: str) -> PriceQuote:
        return await self._search(term)


class DrogaRaiaScraper(BaseRDScraper):
    pharmacy_key = PharmacyEnum.DROGA_RAIA
    name = "Droga Raia"
    base_url = "https://www.drogaraia.com.br"


class DrogasilScraper(BaseRDScraper):
    pharmacy_key = PharmacyEnum.DROGASIL
    name = "Drogasil"
    base_url = "https://www.drogasil.com.br"
