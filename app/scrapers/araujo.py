"""Consulta de catálogo da Farmácias Araujo.

O catálogo é VTEX, mas responde 403 quando o WAF identifica tráfego não
interativo. Esse caso é exposto como ``BLOCKED`` pela base compartilhada, para
que os relatórios não o confundam com produto inexistente.
"""

from app.models.product import PharmacyEnum
from app.scrapers.vtex import VtexCatalogScraper


class AraujoScraper(VtexCatalogScraper):
    pharmacy_key = PharmacyEnum.ARAUJO
    name = "Farmácias Araujo"
    base_url = "https://www.araujo.com.br"
