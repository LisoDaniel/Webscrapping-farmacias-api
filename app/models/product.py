from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class PharmacyEnum(str, Enum):
    PRECO_POPULAR = "precopopular"
    SAO_JOAO = "saojoao"
    DROGA_RAIA = "drogaraia"
    DROGASIL = "drogasil"
    PAGUE_MENOS = "paguemenos"
    PACHECO = "pacheco"
    DROGARIA_SAO_PAULO = "drogariasaopaulo"
    PANVEL = "panvel"
    ARAUJO = "araujo"


class ScrapeStatusEnum(str, Enum):
    SUCCESS = "success"
    NOT_FOUND = "not_found"
    ERROR = "error"
    BLOCKED = "blocked"


class PriceQuote(BaseModel):
    """Cotação individual de preço obtida em uma farmácia."""
    pharmacy_key: PharmacyEnum
    pharmacy_name: str
    product_name: Optional[str] = None
    price: Optional[float] = None
    list_price: Optional[float] = None
    discount_percentage: Optional[float] = None
    available: bool = False
    product_url: Optional[str] = None
    ean: Optional[str] = None
    status: ScrapeStatusEnum = ScrapeStatusEnum.SUCCESS
    error_message: Optional[str] = None
    scraped_at: datetime = Field(default_factory=datetime.now)


class ProductItem(BaseModel):
    """Produto a ser pesquisado ou extraído de planilha."""
    ean: Optional[str] = None
    name: str
    laboratory: Optional[str] = None
    group: Optional[str] = None
    client_pmc: Optional[float] = None
    client_net_price: Optional[float] = None
    quotes: List[PriceQuote] = Field(default_factory=list)


class SearchRequest(BaseModel):
    """Requisição de busca na API por EAN ou nome."""
    ean: Optional[str] = Field(None, description="Código de barras EAN do produto (ex: 7891058003555)")
    query: Optional[str] = Field(None, description="Nome ou termo de busca do produto (ex: Puran T4)")
    pharmacies: Optional[List[PharmacyEnum]] = Field(
        None,
        description="Lista de farmácias para buscar. Se omitido, busca em todas as ativas."
    )
    cep: Optional[str] = Field(
        None,
        description="CEP (somente dígitos) usado para contextualizar preço e disponibilidade regionais."
    )


class SearchResponse(BaseModel):
    """Resposta com os resultados das cotações."""
    query: str
    ean: Optional[str] = None
    total_found: int
    quotes: List[PriceQuote]
    cheapest_quote: Optional[PriceQuote] = None
    cep: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    scraped_at: datetime = Field(default_factory=datetime.now)
