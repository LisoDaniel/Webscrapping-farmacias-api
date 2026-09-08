from typing import List, Optional
from pydantic import BaseModel, Field
from app.models.product import PharmacyEnum


class CompetitorConfig(BaseModel):
    name: str
    site: str
    pharmacy_key: Optional[PharmacyEnum] = None


class ClientInfo(BaseModel):
    id: str
    folder_name: str
    file_path: str
    client_name: str
    city: Optional[str] = None
    state: Optional[str] = None
    cep: Optional[str] = None
    competitors: List[CompetitorConfig] = Field(default_factory=list)
    total_products: int = 0


class ClientScrapeRequest(BaseModel):
    limit: Optional[int] = Field(None, description="Limite máximo de produtos para pesquisar (útil para testes rápidos)")
    pharmacies: Optional[List[PharmacyEnum]] = Field(None, description="Filtrar apenas algumas farmácias")
    cep: Optional[str] = Field(None, description="CEP para contextualizar preço e estoque regionais")
    background: bool = Field(False, description="Executa a varredura em segundo plano e retorna um identificador de acompanhamento")


class ClientScrapeResponse(BaseModel):
    client_id: str
    client_name: str
    total_products: int
    scraped_products: int
    report_file: Optional[str] = None
    report_files: List[str] = Field(default_factory=list)
    download_url: Optional[str] = None
    duration_seconds: float = 0.0
    job_id: Optional[str] = None
    status: str = "completed"


class ScrapeJobResponse(BaseModel):
    """Estado de uma varredura iniciada em segundo plano."""
    job_id: str
    status: str
    client_folder: str
    total_products: int = 0
    scraped_products: int = 0
    report_files: List[str] = Field(default_factory=list)
    error_message: Optional[str] = None
    created_at: str
    finished_at: Optional[str] = None
