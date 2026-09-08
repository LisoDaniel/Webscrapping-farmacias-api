from app.models.product import PharmacyEnum
from app.scrapers.vtex import VtexIntelligentSearchScraper


class PagueMenosScraper(VtexIntelligentSearchScraper):
    pharmacy_key = PharmacyEnum.PAGUE_MENOS
    name = "Pague Menos"
    base_url = "https://www.paguemenos.com.br"
