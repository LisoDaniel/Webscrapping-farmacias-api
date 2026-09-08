import asyncio
import json
import re
from typing import Optional
from app.core.logging import logger
from app.models.product import PharmacyEnum, PriceQuote, ScrapeStatusEnum
from app.scrapers.base import BaseScraper


class BaseRDScraper(BaseScraper):
    """Classe base para redes do grupo RD Saúde (Droga Raia e Drogasil)."""

    async def _fetch_via_curl(self, query: str) -> Optional[str]:
        """
        Executa a requisição assíncrona usando o curl.exe nativo do Windows.
        Essa abordagem contorna as restrições de TLS do Akamai Bot Manager
        sem necessidade de navegador headless pesado.
        """
        url = f"{self.base_url}/search?w={query}"
        cmd = ["curl.exe", "-s", "--max-time", str(int(self.timeout)), url]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await process.communicate()
            return stdout.decode("utf-8", errors="ignore")
        except Exception as e:
            logger.error(f"[{self.name}] Erro ao executar curl.exe: {e}")
            return None

    def _parse_next_data(self, html: str, requested_ean: Optional[str] = None) -> PriceQuote:
        """Extrai os dados estruturados do Next.js (__NEXT_DATA__)."""
        match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html)
        if not match:
            # Se não tem __NEXT_DATA__, verifica se houve bloqueio
            if "Access Denied" in html or "Reference #" in html:
                return PriceQuote(
                    pharmacy_key=self.pharmacy_key,
                    pharmacy_name=self.name,
                    ean=requested_ean,
                    status=ScrapeStatusEnum.BLOCKED,
                    error_message="Bloqueio temporário WAF (Akamai)"
                )
            return PriceQuote(
                pharmacy_key=self.pharmacy_key,
                pharmacy_name=self.name,
                ean=requested_ean,
                status=ScrapeStatusEnum.NOT_FOUND
            )

        try:
            data = json.loads(match.group(1))
            pp = data.get("props", {}).get("pageProps", {})
            
            # O Next.js da Raia/Drogasil por vezes aninha pageProps dentro de pageProps
            if "pageProps" in pp and isinstance(pp["pageProps"], dict):
                pp = pp["pageProps"]

            results = pp.get("results", {})
            products = results.get("products", [])

            if not products:
                return PriceQuote(
                    pharmacy_key=self.pharmacy_key,
                    pharmacy_name=self.name,
                    ean=requested_ean,
                    status=ScrapeStatusEnum.NOT_FOUND
                )

            prod = products[0]
            name = prod.get("name")
            raw_url = prod.get("url", "")
            full_url = f"{self.base_url}{raw_url}" if raw_url.startswith("/") else raw_url

            # Preço pode vir no priceService ou nos facets de preço
            price = prod.get("priceService")
            if price is None:
                facets = results.get("facets", [])
                for f in facets:
                    f_name = f.get("name", "").lower()
                    if "preço" in f_name or "preco" in f_name:
                        price = f.get("stats", {}).get("min")

            price_float = float(price) if price is not None else None

            # Desconto se disponível
            list_price = prod.get("oldPrice") or prod.get("listPrice")
            list_price_float = float(list_price) if list_price else None
            discount = self.calculate_discount(price_float, list_price_float)

            return PriceQuote(
                pharmacy_key=self.pharmacy_key,
                pharmacy_name=self.name,
                product_name=name,
                price=price_float,
                list_price=list_price_float,
                discount_percentage=discount,
                available=True if price_float else False,
                product_url=full_url,
                ean=requested_ean,
                status=ScrapeStatusEnum.SUCCESS
            )
        except Exception as e:
            logger.error(f"[{self.name}] Erro ao parsear JSON da página: {e}")
            return PriceQuote(
                pharmacy_key=self.pharmacy_key,
                pharmacy_name=self.name,
                ean=requested_ean,
                status=ScrapeStatusEnum.ERROR,
                error_message=str(e)
            )

    async def search_by_ean(self, ean: str) -> PriceQuote:
        html = await self._fetch_via_curl(ean)
        if not html:
            return PriceQuote(
                pharmacy_key=self.pharmacy_key,
                pharmacy_name=self.name,
                ean=ean,
                status=ScrapeStatusEnum.ERROR,
                error_message="Falha na comunicação de rede"
            )
        return self._parse_next_data(html, requested_ean=ean)

    async def search_by_term(self, term: str) -> PriceQuote:
        html = await self._fetch_via_curl(term)
        if not html:
            return PriceQuote(
                pharmacy_key=self.pharmacy_key,
                pharmacy_name=self.name,
                status=ScrapeStatusEnum.ERROR,
                error_message="Falha na comunicação de rede"
            )
        return self._parse_next_data(html)


class DrogaRaiaScraper(BaseRDScraper):
    pharmacy_key = PharmacyEnum.DROGA_RAIA
    name = "Droga Raia"
    base_url = "https://www.drogaraia.com.br"


class DrogasilScraper(BaseRDScraper):
    pharmacy_key = PharmacyEnum.DROGASIL
    name = "Drogasil"
    base_url = "https://www.drogasil.com.br"
