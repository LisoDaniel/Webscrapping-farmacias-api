from app.models.product import PharmacyEnum
from app.scrapers.vtex import VtexIntelligentSearchScraper


class PachecoScraper(VtexIntelligentSearchScraper):
    pharmacy_key = PharmacyEnum.PACHECO
    name = "Drogarias Pacheco"
    base_url = "https://www.drogariaspacheco.com.br"
