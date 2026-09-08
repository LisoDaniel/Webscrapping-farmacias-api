from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.product import PharmacyEnum, ScrapeStatusEnum


class PriceHistoryItem(BaseModel):
    run_id: str
    ean: str
    product_name: str
    pharmacy_key: PharmacyEnum
    pharmacy_name: str
    price: Optional[float] = None
    list_price: Optional[float] = None
    available: bool
    status: ScrapeStatusEnum
    product_url: Optional[str] = None
    error_message: Optional[str] = None
    cep: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    scraped_at: datetime


class PriceHistorySummary(BaseModel):
    ean: str
    total_quotes: int
    latest_prices: list[PriceHistoryItem]
