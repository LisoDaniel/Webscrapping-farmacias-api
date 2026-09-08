from app.models.product import PharmacyEnum
from app.scrapers.pacheco import PachecoScraper


class DrogariaSaoPauloScraper(PachecoScraper):
    pharmacy_key = PharmacyEnum.DROGARIA_SAO_PAULO
    name = "Drogaria São Paulo"
    base_url = "https://www.drogariasaopaulo.com.br"
