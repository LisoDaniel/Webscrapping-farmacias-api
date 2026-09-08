"""Validação operacional dos scrapers com EANs de referência públicos."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from pydantic import BaseModel, Field

from app.core.config import settings
from app.models.product import PharmacyEnum, ScrapeStatusEnum, SearchRequest
from app.scrapers.registry import ScraperRegistry
from app.services.scraper_service import ScraperService


class ValidationProduct(BaseModel):
    """Produto público usado como referência na verificação."""

    ean: str = Field(description="EAN-8, EAN-13 ou GTIN-14 do produto")
    label: str = Field(description="Identificação legível no relatório")


class ValidationEntry(BaseModel):
    ean: str
    product_label: str
    pharmacy_key: PharmacyEnum
    pharmacy_name: str
    status: ScrapeStatusEnum
    price: Optional[float] = None
    product_name: Optional[str] = None
    product_url: Optional[str] = None
    error_message: Optional[str] = None


class ValidationReport(BaseModel):
    executed_at: datetime = Field(default_factory=datetime.now)
    fixture_path: str
    cep: Optional[str] = None
    products_checked: int
    pharmacies_checked: list[PharmacyEnum]
    entries: list[ValidationEntry]

    def status_summary(self) -> dict[str, dict[str, int]]:
        """Agrupa os estados por farmácia para consulta rápida."""
        result: dict[str, dict[str, int]] = {}
        for pharmacy in self.pharmacies_checked:
            counts = Counter(
                entry.status.value
                for entry in self.entries
                if entry.pharmacy_key == pharmacy
            )
            result[pharmacy.value] = {
                status.value: counts.get(status.value, 0)
                for status in ScrapeStatusEnum
            }
        return result


class ScraperValidationService:
    """Executa e exporta um diagnóstico de disponibilidade das integrações."""

    default_fixture = settings.BASE_DIR / "app" / "fixtures" / "validation_products.json"
    # A Araujo veda data mining em seus termos públicos. A integração só deve
    # voltar a ser validada por rede após autorização ou acesso oficial.
    restricted_pharmacies = {PharmacyEnum.ARAUJO}

    def __init__(self, scraper_service: Optional[ScraperService] = None):
        self.scraper_service = scraper_service or ScraperService()

    @staticmethod
    def _resolve_fixture_path(path: Optional[str | Path]) -> Path:
        fixture = Path(path) if path else ScraperValidationService.default_fixture
        return fixture if fixture.is_absolute() else settings.BASE_DIR / fixture

    @classmethod
    def load_products(cls, path: Optional[str | Path] = None) -> tuple[Path, list[ValidationProduct]]:
        fixture = cls._resolve_fixture_path(path)
        try:
            content = json.loads(fixture.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError(f"Arquivo de referência não encontrado: {fixture}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON inválido no arquivo de referência: {fixture}") from exc

        raw_products = content.get("products") if isinstance(content, dict) else content
        if not isinstance(raw_products, list) or not raw_products:
            raise ValueError("O arquivo de referência deve possuir uma lista não vazia em 'products'.")

        products = [ValidationProduct.model_validate(item) for item in raw_products]
        for product in products:
            if not re.fullmatch(r"\d{8,14}", product.ean):
                raise ValueError(f"EAN inválido na referência: {product.ean}")
        return fixture, products

    async def run(
        self,
        products: Iterable[ValidationProduct],
        fixture_path: str | Path,
        pharmacies: Optional[list[PharmacyEnum]] = None,
        cep: Optional[str] = None,
    ) -> ValidationReport:
        selected_pharmacies = pharmacies or [
            pharmacy
            for pharmacy in ScraperRegistry._scrapers.keys()
            if pharmacy not in self.restricted_pharmacies
        ]
        restricted = set(selected_pharmacies) & self.restricted_pharmacies
        if restricted:
            names = ", ".join(pharmacy.value for pharmacy in sorted(restricted, key=str))
            raise ValueError(
                f"Validação automática não permitida para: {names}. "
                "Use uma API ou feed de preços autorizado."
            )
        entries: list[ValidationEntry] = []
        products = list(products)

        for product in products:
            # A validação é intencionalmente apenas por EAN, sem fallback por
            # nome: mede a precisão da integração, não a relevância da busca.
            response = await self.scraper_service.search(
                SearchRequest(ean=product.ean, pharmacies=selected_pharmacies, cep=cep)
            )
            entries.extend(
                ValidationEntry(
                    ean=product.ean,
                    product_label=product.label,
                    pharmacy_key=quote.pharmacy_key,
                    pharmacy_name=quote.pharmacy_name,
                    status=quote.status,
                    price=quote.price,
                    product_name=quote.product_name,
                    product_url=quote.product_url,
                    error_message=quote.error_message,
                )
                for quote in response.quotes
            )

        return ValidationReport(
            fixture_path=str(fixture_path),
            cep=cep,
            products_checked=len(products),
            pharmacies_checked=selected_pharmacies,
            entries=entries,
        )

    async def run_from_fixture(
        self,
        path: Optional[str | Path] = None,
        pharmacies: Optional[list[PharmacyEnum]] = None,
        cep: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> ValidationReport:
        fixture, products = self.load_products(path)
        if limit is not None:
            products = products[:limit]
        if not products:
            raise ValueError("Nenhum produto selecionado para validar.")
        return await self.run(products, fixture, pharmacies, cep)

    @staticmethod
    def export(report: ValidationReport, output_dir: Optional[Path] = None) -> tuple[Path, Path]:
        directory = output_dir or settings.REPORTS_DIR
        directory.mkdir(parents=True, exist_ok=True)
        stamp = report.executed_at.strftime("%Y%m%d_%H%M%S")
        json_path = directory / f"scraper_validation_{stamp}.json"
        csv_path = directory / f"scraper_validation_{stamp}.csv"

        payload = report.model_dump(mode="json")
        payload["status_summary"] = report.status_summary()
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        fields = [
            "ean", "product_label", "pharmacy_key", "pharmacy_name", "status",
            "price", "product_name", "product_url", "error_message",
        ]
        with csv_path.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            for entry in report.entries:
                row = entry.model_dump(mode="json")
                row["pharmacy_key"] = entry.pharmacy_key.value
                row["status"] = entry.status.value
                writer.writerow(row)
        return json_path, csv_path
