from app.models.product import PharmacyEnum
from app.scrapers.vtex import VtexCatalogScraper


class PrecoPopularScraper(VtexCatalogScraper):
    pharmacy_key = PharmacyEnum.PRECO_POPULAR
    name = "Farmácia Preço Popular"
    base_url = "https://www.precopopular.com.br"
