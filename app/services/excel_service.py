from datetime import datetime
from pathlib import Path
import re
from typing import List, Optional, Tuple
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.core.config import settings
from app.core.locations import normalize_state
from app.core.logging import logger
from app.models.client import ClientInfo, CompetitorConfig
from app.models.product import PharmacyEnum, PriceQuote, ProductItem, ScrapeStatusEnum
from app.scrapers.registry import ScraperRegistry


# Marcas de cabeçalho por campo, na ordem em que são testadas. A primeira que
# aparecer no texto da célula define a coluna.
_CABECALHOS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ean", ("CÓD. BARRAS", "COD. BARRAS", "CÓDIGO DE BARRAS", "CODIGO DE BARRAS", "EAN")),
    ("pmc", ("PMC",)),
    ("net_price", ("PREÇO LÍQ", "PRECO LIQ")),
    ("laboratory", ("FABRICANTE", "LABORATÓRIO", "LABORATORIO")),
    ("group", ("GRUPO",)),
    ("name", ("PRODUTO", "DESCRIÇÃO", "DESCRICAO")),
)

# Layout assumido quando não há cabeçalho reconhecível.
_COLUNAS_PADRAO = {"ean": 1, "name": 2, "laboratory": 3, "group": 4}


class ExcelService:
    """Serviço para leitura de planilhas de clientes e geração de relatórios de preços."""

    @staticmethod
    def _mapear_colunas(sheet, max_rows: int = 40) -> dict:
        """Mapeia as colunas pelo cabeçalho, em vez de assumir posições fixas.

        Os clientes não usam o mesmo layout. A planilha do MATHEUS traz PMC e
        preço líquido em C e D, o que empurra laboratório e grupo para E e F;
        as demais têm laboratório e grupo já em C e D. Com posições fixas, o
        relatório do MATHEUS saía com números nas colunas de laboratório e
        grupo.

        A busca começa pela linha de cabeçalho — a que nomeia o produto — para
        não confundir com o bloco de concorrentes, que fica em outras colunas
        mais abaixo.
        """
        for r_idx in range(1, min(sheet.max_row, max_rows) + 1):
            textos = [
                valor.strip().upper() if isinstance(valor, str) else ""
                for valor in (sheet.cell(r_idx, c).value for c in range(1, 15))
            ]
            if not any(texto.startswith("PRODUTO") for texto in textos):
                continue

            colunas: dict = {}
            for indice, texto in enumerate(textos, start=1):
                if not texto:
                    continue
                for campo, marcas in _CABECALHOS:
                    if campo not in colunas and any(marca in texto for marca in marcas):
                        colunas[campo] = indice
                        break
            if "ean" in colunas and "name" in colunas:
                return colunas
        return {}

    @staticmethod
    def _texto(sheet, row_idx: int, col_idx: Optional[int]) -> Optional[str]:
        if not col_idx:
            return None
        valor = sheet.cell(row_idx, col_idx).value
        if valor is None:
            return None
        texto = str(valor).strip()
        return texto or None

    @staticmethod
    def _numero(sheet, row_idx: int, col_idx: Optional[int]) -> Optional[float]:
        if not col_idx:
            return None
        valor = sheet.cell(row_idx, col_idx).value
        return float(valor) if isinstance(valor, (int, float)) and not isinstance(valor, bool) else None

    @staticmethod
    def list_available_clients() -> List[ClientInfo]:
        """Varre o diretório Clientes/ e identifica todas as pastas e planilhas válidas."""
        clients: List[ClientInfo] = []
        if not settings.CLIENTS_DIR.exists():
            return clients

        for folder in sorted(settings.CLIENTS_DIR.iterdir()):
            if not folder.is_dir():
                continue

            xlsx_files = list(folder.glob("*.xlsx"))
            if not xlsx_files:
                continue

            xlsx_path = xlsx_files[0]
            try:
                wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
                sheet = wb.active

                city = None
                state = None
                cep = None
                competitors: List[CompetitorConfig] = []
                total_products = 0

                # Lê as primeiras 25 linhas procurando cabeçalhos, cidade, concorrentes
                header_rows = list(sheet.iter_rows(values_only=True, max_row=30))
                for row in header_rows:
                    for cell in row:
                        if not cell or not isinstance(cell, str):
                            continue
                        text = cell.strip()
                        if text.upper().startswith("CIDADE:"):
                            city = text.split(":", 1)[1].strip()
                        elif text.upper().startswith("ESTADO:"):
                            state = normalize_state(text.split(":", 1)[1])
                        elif text.upper().startswith("CEP:"):
                            cep = re.sub(r"\D", "", text.split(":", 1)[1]) or None
                        elif ".com" in text.lower() or "farmacia" in text.lower():
                            resolved = ScraperRegistry.resolve_pharmacy(text)
                            if resolved and not any(c.site == text for c in competitors):
                                competitors.append(CompetitorConfig(
                                    name=resolved.value.replace("_", " ").title(),
                                    site=text,
                                    pharmacy_key=resolved
                                ))

                # Conta linhas com EAN válido
                for row in sheet.iter_rows(values_only=True):
                    val = row[0] if len(row) > 0 else None
                    if val and str(val).strip().isdigit() and len(str(val).strip()) >= 7:
                        total_products += 1

                wb.close()

                client_id = folder.name.replace(" ", "_").lower()
                clients.append(ClientInfo(
                    id=client_id,
                    folder_name=folder.name,
                    file_path=str(xlsx_path),
                    client_name=folder.name,
                    city=city,
                    state=state,
                    cep=cep,
                    competitors=competitors,
                    total_products=total_products
                ))
            except Exception as e:
                logger.error(f"Erro ao processar pasta do cliente {folder.name}: {e}")

        return clients

    @staticmethod
    def parse_client_products(
        folder_name: str,
        limit: Optional[int] = None
    ) -> Tuple[ClientInfo, List[ProductItem]]:
        """Extrai a lista de produtos da planilha do cliente informado."""
        target_dir = settings.CLIENTS_DIR / folder_name
        if not target_dir.exists():
            raise FileNotFoundError(f"Pasta do cliente não encontrada: {folder_name}")

        xlsx_files = list(target_dir.glob("*.xlsx"))
        if not xlsx_files:
            raise FileNotFoundError(f"Nenhuma planilha .xlsx encontrada em: {folder_name}")

        xlsx_path = xlsx_files[0]
        wb = openpyxl.load_workbook(xlsx_path, data_only=True)
        sheet = wb.active

        city = None
        state = None
        cep = None
        competitors: List[CompetitorConfig] = []
        products: List[ProductItem] = []

        # As colunas vêm do cabeçalho; o layout fixo é só o último recurso.
        colunas = ExcelService._mapear_colunas(sheet) or dict(_COLUNAS_PADRAO)
        ean_col_idx = colunas.get("ean", 1)
        name_col_idx = colunas.get("name", 2)
        lab_col_idx = colunas.get("laboratory")
        group_col_idx = colunas.get("group")
        pmc_col_idx = colunas.get("pmc")
        price_col_idx = colunas.get("net_price")

        # Primeiro passo: metadados das primeiras 40 linhas (cidade, estado,
        # CEP e concorrentes). As colunas já vieram do cabeçalho, acima.
        max_meta_rows = min(sheet.max_row, 40)
        for r_idx in range(1, max_meta_rows + 1):
            row_vals = [sheet.cell(r_idx, c_idx).value for c_idx in range(1, 15)]
            for col_idx, val in enumerate(row_vals):
                if not val or not isinstance(val, str):
                    continue
                v_upper = val.upper().strip()
                if v_upper.startswith("CIDADE:"):
                    city = val.split(":", 1)[1].strip()
                elif v_upper.startswith("ESTADO:"):
                    state = normalize_state(val.split(":", 1)[1])
                elif v_upper.startswith("CEP:"):
                    cep = re.sub(r"\D", "", val.split(":", 1)[1]) or None
                elif ".com" in val.lower():
                    resolved = ScraperRegistry.resolve_pharmacy(val)
                    if resolved and not any(c.site == val for c in competitors):
                        competitors.append(CompetitorConfig(
                            name=resolved.value.replace("_", " ").title(),
                            site=val,
                            pharmacy_key=resolved
                        ))

        # Segundo passo: Coleta de produtos respeitando o limit
        for row_idx in range(1, sheet.max_row + 1):
            raw_ean = sheet.cell(row_idx, ean_col_idx).value

            # Verificar se é linha de produto (EAN válido)
            if raw_ean and str(raw_ean).replace(".0", "").strip().isdigit():
                clean_ean = str(raw_ean).replace(".0", "").strip()
                prod_name = (
                    ExcelService._texto(sheet, row_idx, name_col_idx)
                    or f"Produto EAN {clean_ean}"
                )
                lab = ExcelService._texto(sheet, row_idx, lab_col_idx)
                grp = ExcelService._texto(sheet, row_idx, group_col_idx)
                pmc = ExcelService._numero(sheet, row_idx, pmc_col_idx)
                net_price = ExcelService._numero(sheet, row_idx, price_col_idx)

                products.append(ProductItem(
                    ean=clean_ean,
                    name=prod_name,
                    laboratory=lab,
                    group=grp,
                    client_pmc=pmc,
                    client_net_price=net_price
                ))

                if limit and len(products) >= limit:
                    break

        wb.close()

        client_info = ClientInfo(
            id=folder_name.replace(" ", "_").lower(),
            folder_name=folder_name,
            file_path=str(xlsx_path),
            client_name=folder_name,
            city=city,
            state=state,
            cep=cep,
            competitors=competitors,
            total_products=len(products)
        )

        return client_info, products

    @staticmethod
    def generate_enriched_report(
        client_info: ClientInfo,
        products: List[ProductItem],
        pharmacies: List[PharmacyEnum]
    ) -> Path:
        """Gera uma planilha Excel estilizada com as cotações e comparação de preços."""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Comparativo de Preços"

        # Estilos visuais profissionais
        header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
        comp_header_fill = PatternFill(start_color="2F5597", end_color="2F5597", fill_type="solid")
        cheapest_fill = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")
        font_header = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        font_data = Font(name="Calibri", size=10)
        font_bold = Font(name="Calibri", size=10, bold=True)
        thin_border = Border(
            left=Side(style="thin", color="D9D9D9"),
            right=Side(style="thin", color="D9D9D9"),
            top=Side(style="thin", color="D9D9D9"),
            bottom=Side(style="thin", color="D9D9D9")
        )

        # Montagem do Cabeçalho
        headers = [
            "CÓD. BARRAS / EAN",
            "PRODUTO",
            "LABORATÓRIO",
            "GRUPO",
            "PREÇO CLIENTE (R$)",
        ]

        # Colunas de cada concorrente
        pharmacy_names = {}
        for p in pharmacies:
            scraper = ScraperRegistry.get_scraper(p)
            p_name = scraper.name if scraper else p.value
            pharmacy_names[p] = p_name
            headers.append(f"PREÇO - {p_name}")
            headers.append(f"DESC % - {p_name}")
            headers.append(f"LINK - {p_name}")

        headers.extend([
            "MENOR PREÇO CONCORRENTES",
            "FARMÁCIA MAIS BARATA",
            "DIFERENÇA % (vs CLIENTE)",
        ])

        ws.append(headers)

        # Estilizar linha de cabeçalho
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.font = font_header
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.fill = comp_header_fill if col_idx > 5 else header_fill
        ws.row_dimensions[1].height = 28

        # Inserção dos dados
        for row_idx, prod in enumerate(products, start=2):
            row_data = [
                prod.ean,
                prod.name,
                prod.laboratory or "-",
                prod.group or "-",
                prod.client_net_price,
            ]

            valid_competitor_prices = []
            quotes_by_pharmacy = {q.pharmacy_key: q for q in prod.quotes}

            for p in pharmacies:
                quote = quotes_by_pharmacy.get(p)
                if quote and quote.status == ScrapeStatusEnum.SUCCESS and quote.price is not None:
                    row_data.append(quote.price)
                    row_data.append(quote.discount_percentage or 0.0)
                    row_data.append(quote.product_url or "-")
                    valid_competitor_prices.append((quote.price, pharmacy_names[p]))
                else:
                    status_text = "Não Encontrado" if not quote or quote.status == ScrapeStatusEnum.NOT_FOUND else "Erro"
                    row_data.append(status_text)
                    row_data.append("-")
                    row_data.append("-")

            # Resumo da concorrência
            if valid_competitor_prices:
                min_price, cheapest_pharmacy = min(valid_competitor_prices, key=lambda x: x[0])
                row_data.append(min_price)
                row_data.append(cheapest_pharmacy)

                if prod.client_net_price and prod.client_net_price > 0:
                    diff_pct = round(((min_price - prod.client_net_price) / prod.client_net_price) * 100, 1)
                    row_data.append(diff_pct)
                else:
                    row_data.append("-")
            else:
                row_data.extend(["-", "-", "-"])

            ws.append(row_data)

            # Estilização das células da linha
            for col_idx in range(1, len(headers) + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                cell.font = font_data
                cell.border = thin_border
                cell.alignment = Alignment(vertical="center")

                # Formatar moeda onde aplicável
                if isinstance(cell.value, float) and "PREÇO" in headers[col_idx - 1]:
                    cell.number_format = '"R$ "#,##0.00'

        # Ajuste automático de largura das colunas
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 40)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r"[^\w\-]", "_", client_info.folder_name)
        output_filename = f"RELATORIO_{safe_name}_{timestamp}.xlsx"
        output_path = settings.REPORTS_DIR / output_filename

        wb.save(output_path)
        logger.info(f"Relatório gerado com sucesso: {output_path}")
        return output_path
