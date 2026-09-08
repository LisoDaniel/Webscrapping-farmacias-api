from app.models.product import PharmacyEnum
from app.scrapers.vtex import VtexCatalogScraper


class SaoJoaoScraper(VtexCatalogScraper):
    pharmacy_key = PharmacyEnum.SAO_JOAO
    name = "Farmácias São João"
    base_url = "https://www.saojoaofarmacias.com.br"
