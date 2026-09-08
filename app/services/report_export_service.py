"""Exportações adicionais do comparativo, a partir dos mesmos dados do XLSX."""

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable

from app.core.config import settings
from app.models.client import ClientInfo
from app.models.product import PharmacyEnum, ProductItem, ScrapeStatusEnum
from app.scrapers.registry import ScraperRegistry


class ReportExportService:
    @staticmethod
    def _base_path(client_info: ClientInfo) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r"[^\w\-]", "_", client_info.folder_name)
        return settings.REPORTS_DIR / f"RELATORIO_{safe_name}_{stamp}"

    @staticmethod
    def _rows(products: Iterable[ProductItem], pharmacies: list[PharmacyEnum]) -> list[dict]:
        names = {
            pharmacy: (ScraperRegistry.get_scraper(pharmacy).name if ScraperRegistry.get_scraper(pharmacy) else pharmacy.value)
            for pharmacy in pharmacies
        }
        rows: list[dict] = []
        for product in products:
            row = {
                "ean": product.ean,
                "produto": product.name,
                "laboratorio": product.laboratory,
                "grupo": product.group,
                "preco_cliente": product.client_net_price,
            }
            valid_prices: list[tuple[float, str]] = []
            quotes = {quote.pharmacy_key: quote for quote in product.quotes}
            for pharmacy in pharmacies:
                quote = quotes.get(pharmacy)
                prefix = pharmacy.value
                row[f"preco_{prefix}"] = quote.price if quote and quote.status == ScrapeStatusEnum.SUCCESS else None
                row[f"desconto_{prefix}"] = quote.discount_percentage if quote and quote.status == ScrapeStatusEnum.SUCCESS else None
                row[f"link_{prefix}"] = quote.product_url if quote else None
                row[f"status_{prefix}"] = quote.status.value if quote else ScrapeStatusEnum.NOT_FOUND.value
                if quote and quote.status == ScrapeStatusEnum.SUCCESS and quote.price is not None:
                    valid_prices.append((quote.price, names[pharmacy]))
            if valid_prices:
                price, pharmacy_name = min(valid_prices, key=lambda item: item[0])
                row["menor_preco_concorrentes"] = price
                row["farmacia_mais_barata"] = pharmacy_name
                row["diferenca_percentual_vs_cliente"] = (
                    round(((price - product.client_net_price) / product.client_net_price) * 100, 1)
                    if product.client_net_price else None
                )
            else:
                row["menor_preco_concorrentes"] = None
                row["farmacia_mais_barata"] = None
                row["diferenca_percentual_vs_cliente"] = None
            rows.append(row)
        return rows

    @classmethod
    def generate(cls, client_info: ClientInfo, products: list[ProductItem], pharmacies: list[PharmacyEnum]) -> list[Path]:
        base_path = cls._base_path(client_info)
        rows = cls._rows(products, pharmacies)
        payload = {
            "generated_at": datetime.now().isoformat(),
            "client": client_info.model_dump(mode="json"),
            "rows": rows,
        }
        json_path = base_path.with_suffix(".json")
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        csv_path = base_path.with_suffix(".csv")
        fieldnames = list(rows[0].keys()) if rows else ["ean", "produto"]
        with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return [json_path, csv_path]
