"""Consulta de catálogo público VTEX da Farma Conde."""

from app.models.product import PharmacyEnum
from app.scrapers.vtex import VtexCatalogScraper


class FarmaCondeScraper(VtexCatalogScraper):
    pharmacy_key = PharmacyEnum.FARMA_CONDE
    name = "Farma Conde"
    base_url = "https://www.farmaconde.com.br"
