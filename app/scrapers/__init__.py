from app.scrapers.base import BaseScraper
from app.scrapers.registry import ScraperRegistry
from app.scrapers.preco_popular import PrecoPopularScraper
from app.scrapers.saojoao import SaoJoaoScraper
from app.scrapers.drogaraia_drogasil import DrogaRaiaScraper, DrogasilScraper
from app.scrapers.paguemenos import PagueMenosScraper
from app.scrapers.pacheco import PachecoScraper
from app.scrapers.drogaria_sao_paulo import DrogariaSaoPauloScraper

__all__ = [
    "BaseScraper",
    "ScraperRegistry",
    "PrecoPopularScraper",
    "SaoJoaoScraper",
    "DrogaRaiaScraper",
    "DrogasilScraper",
    "PagueMenosScraper",
    "PachecoScraper",
    "DrogariaSaoPauloScraper",
]
