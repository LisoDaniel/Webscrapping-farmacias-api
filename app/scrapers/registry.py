from typing import Dict, List, Optional, Type
from app.models.product import PharmacyEnum
from app.scrapers.base import BaseScraper
from app.scrapers.preco_popular import PrecoPopularScraper
from app.scrapers.saojoao import SaoJoaoScraper
from app.scrapers.drogaraia_drogasil import DrogaRaiaScraper, DrogasilScraper
from app.scrapers.paguemenos import PagueMenosScraper
from app.scrapers.pacheco import PachecoScraper
from app.scrapers.drogaria_sao_paulo import DrogariaSaoPauloScraper
from app.scrapers.panvel import PanvelScraper
from app.scrapers.araujo import AraujoScraper


class ScraperRegistry:
    """Gerenciador e fábrica de scrapers de farmácias."""

    _scrapers: Dict[PharmacyEnum, Type[BaseScraper]] = {
        PharmacyEnum.PRECO_POPULAR: PrecoPopularScraper,
        PharmacyEnum.SAO_JOAO: SaoJoaoScraper,
        PharmacyEnum.DROGA_RAIA: DrogaRaiaScraper,
        PharmacyEnum.DROGASIL: DrogasilScraper,
        PharmacyEnum.PAGUE_MENOS: PagueMenosScraper,
        PharmacyEnum.PACHECO: PachecoScraper,
        PharmacyEnum.DROGARIA_SAO_PAULO: DrogariaSaoPauloScraper,
        PharmacyEnum.PANVEL: PanvelScraper,
        PharmacyEnum.ARAUJO: AraujoScraper,
    }

    # Mapeamento de termos e domínios encontrados nas planilhas do Instituto Bulla
    _domain_aliases: Dict[str, PharmacyEnum] = {
        "precopopular.com.br": PharmacyEnum.PRECO_POPULAR,
        "preco popular": PharmacyEnum.PRECO_POPULAR,
        "farmácia preço popular": PharmacyEnum.PRECO_POPULAR,
        "saojoaofarmacias.com.br": PharmacyEnum.SAO_JOAO,
        "são joão": PharmacyEnum.SAO_JOAO,
        "farmácias são joão": PharmacyEnum.SAO_JOAO,
        "drogaraia.com.br": PharmacyEnum.DROGA_RAIA,
        "droga raia": PharmacyEnum.DROGA_RAIA,
        "raia": PharmacyEnum.DROGA_RAIA,
        "drogasil.com.br": PharmacyEnum.DROGASIL,
        "drogasil": PharmacyEnum.DROGASIL,
        "paguemenos.com.br": PharmacyEnum.PAGUE_MENOS,
        "pague menos": PharmacyEnum.PAGUE_MENOS,
        "drogariaspacheco.com.br": PharmacyEnum.PACHECO,
        "drogarias pacheco": PharmacyEnum.PACHECO,
        "pacheco": PharmacyEnum.PACHECO,
        "drogariasaopaulo.com.br": PharmacyEnum.DROGARIA_SAO_PAULO,
        "drogaria sao paulo": PharmacyEnum.DROGARIA_SAO_PAULO,
        "drogaria são paulo": PharmacyEnum.DROGARIA_SAO_PAULO,
        "dpsp": PharmacyEnum.DROGARIA_SAO_PAULO,
        "panvel.com": PharmacyEnum.PANVEL,
        "panvel": PharmacyEnum.PANVEL,
        "araujo.com.br": PharmacyEnum.ARAUJO,
        "farmácias araujo": PharmacyEnum.ARAUJO,
        "farmacias araujo": PharmacyEnum.ARAUJO,
        "araujo": PharmacyEnum.ARAUJO,
    }

    @classmethod
    def get_scraper(cls, pharmacy: PharmacyEnum) -> Optional[BaseScraper]:
        """Instancia um scraper para a farmácia informada."""
        scraper_cls = cls._scrapers.get(pharmacy)
        if scraper_cls:
            return scraper_cls()
        return None

    @classmethod
    def resolve_pharmacy(cls, alias_or_domain: str) -> Optional[PharmacyEnum]:
        """Converte texto ou domínio de planilha para um PharmacyEnum."""
        clean = alias_or_domain.lower().strip()
        for key, enum_val in cls._domain_aliases.items():
            if key in clean or clean in key:
                return enum_val
        return None

    @classmethod
    def list_all(cls) -> List[Dict[str, str]]:
        """Lista todas as farmácias configuradas e seus metadados."""
        result = []
        for key, scraper_cls in cls._scrapers.items():
            result.append({
                "key": key.value,
                "name": scraper_cls.name,
                "base_url": scraper_cls.base_url,
            })
        return result
