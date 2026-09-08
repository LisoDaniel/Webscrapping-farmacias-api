"""Modelos SQLAlchemy do histórico de monitoramento de preços."""

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ProductRecord(Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    ean: Mapped[Optional[str]] = mapped_column(String(14), unique=True, index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(500))
    laboratory: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    product_group: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ScrapeRunRecord(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source: Mapped[str] = mapped_column(String(32), index=True)
    query: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    ean: Mapped[Optional[str]] = mapped_column(String(14), index=True, nullable=True)
    client_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    cep: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class PriceQuoteRecord(Base):
    __tablename__ = "price_quotes"
    __table_args__ = (
        Index("ix_price_quotes_product_pharmacy_scraped", "product_id", "pharmacy_key", "scraped_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scrape_run_id: Mapped[str] = mapped_column(
        ForeignKey("scrape_runs.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    pharmacy_key: Mapped[str] = mapped_column(String(64), index=True)
    pharmacy_name: Mapped[str] = mapped_column(String(255))
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    list_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    discount_percentage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    available: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), index=True)
    product_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
