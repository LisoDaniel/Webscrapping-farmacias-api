import argparse
import asyncio
import json
import sys
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeRemainingColumn

from app.core.config import settings
from app.models.product import PharmacyEnum, ScrapeStatusEnum, SearchRequest
from app.scrapers.registry import ScraperRegistry
from app.services.excel_service import ExcelService
from app.services.scraper_service import ScraperService
from app.services.cep_service import CepService
from app.services.report_export_service import ReportExportService
from app.services.validation_service import ScraperValidationService
from app.services.price_history_service import PriceHistoryService

console = Console()
price_history_service = PriceHistoryService()


def cmd_list_clients():
    """Lista todos os clientes detectados na pasta Clientes/."""
    clients = ExcelService.list_available_clients()
    if not clients:
        console.print("[yellow]Nenhum cliente encontrado na pasta Clientes/[/yellow]")
        return

    table = Table(title="Clientes Detectados no Instituto Bulla", header_style="bold blue")
    table.add_column("Pasta / Cliente", style="cyan", no_wrap=True)
    table.add_column("Cidade", style="magenta")
    table.add_column("UF", style="green", justify="center")
    table.add_column("Produtos", style="yellow", justify="right")
    table.add_column("Concorrentes Identificados", style="white")

    for c in clients:
        comp_names = ", ".join(comp.name for comp in c.competitors) or "Nenhum detectado"
        table.add_row(
            c.client_name,
            c.city or "-",
            c.state or "-",
            str(c.total_products),
            comp_names
        )

    console.print(table)


def cmd_listar_eans(folder: str, limit: int = None):
    """Imprime os EANs da planilha como lista JS, para a coleta assistida.

    A saída vai em print() puro, sem formatação do rich, para poder ser colada
    direto no console do navegador junto de tools/captura_panvel.js.
    """
    try:
        _, products = ExcelService.parse_client_products(folder, limit=limit)
    except Exception as exc:
        console.print(f"[red]Erro ao carregar cliente '{folder}': {exc}[/red]")
        return
    eans = [product.ean for product in products if product.ean]
    if not eans:
        console.print("[yellow]Nenhum EAN encontrado na planilha.[/yellow]")
        return
    print(json.dumps(eans, ensure_ascii=False))


async def cmd_search(ean: str = None, query: str = None, cep: str = None):
    """Executa busca de preço para um produto específico."""
    if not ean and not query:
        console.print("[red]Erro: Forneça --ean ou --query para pesquisar.[/red]")
        return

    service = ScraperService()
    req = SearchRequest(ean=ean, query=query, cep=cep)

    with console.status(f"[bold green]Pesquisando preços para EAN={ean or '-'} Query='{query or '-'}'..."):
        resp = await service.search(req)
    await price_history_service.record_search(resp)

    table = Table(title=f"Resultados de Preços: {resp.query}", header_style="bold blue")
    table.add_column("Farmácia", style="cyan", no_wrap=True)
    table.add_column("Produto no Site", style="white")
    table.add_column("Preço (R$)", style="green", justify="right")
    table.add_column("Preço Tabela (R$)", style="dim", justify="right")
    table.add_column("Desconto %", style="magenta", justify="right")
    table.add_column("Status", style="yellow")
    table.add_column("Link da Oferta", style="blue")

    for q in resp.quotes:
        p_str = f"R$ {q.price:.2f}" if q.price is not None else "-"
        lp_str = f"R$ {q.list_price:.2f}" if q.list_price is not None else "-"
        desc_str = f"{q.discount_percentage:.1f}%" if q.discount_percentage else "-"

        status_text = q.status.value.upper()
        if q.status == ScrapeStatusEnum.SUCCESS and q.price is not None:
            status_style = "[green]ENCONTRADO[/green]"
        elif q.status == ScrapeStatusEnum.BLOCKED:
            status_style = "[yellow]BLOQUEADO (WAF)[/yellow]"
        elif q.status == ScrapeStatusEnum.ERROR:
            status_style = f"[red]ERRO: {q.error_message or ''}[/red]"
        else:
            status_style = "[dim]NÃO ENCONTRADO[/dim]"

        table.add_row(
            q.pharmacy_name,
            q.product_name or "-",
            p_str,
            lp_str,
            desc_str,
            status_style,
            q.product_url or "-"
        )

    console.print(table)

    if resp.cheapest_quote:
        console.print(
            f"\n[bold green][*] Menor Preço Encontrado:[/bold green] "
            f"[bold cyan]{resp.cheapest_quote.pharmacy_name}[/bold cyan] por "
            f"[bold yellow]R$ {resp.cheapest_quote.price:.2f}[/bold yellow]!"
        )


async def cmd_scrape_client(folder: str, limit: int = None, cep: str = None):
    """Executa a raspagem para a planilha de um cliente."""
    try:
        client_info, products = ExcelService.parse_client_products(folder, limit=limit)
    except Exception as e:
        console.print(f"[red]Erro ao carregar cliente '{folder}': {e}[/red]")
        return

    console.print(f"[bold blue]Cliente:[/bold blue] {client_info.client_name}")
    console.print(f"[bold blue]Cidade/UF:[/bold blue] {client_info.city or '-'} / {client_info.state or '-'}")
    console.print(f"[bold blue]Total de Produtos para pesquisar:[/bold blue] {len(products)}")

    # Identificar farmácias
    target_pharmacies = [c.pharmacy_key for c in client_info.competitors if c.pharmacy_key]
    if not target_pharmacies:
        target_pharmacies = [PharmacyEnum.PRECO_POPULAR, PharmacyEnum.SAO_JOAO]

    console.print(f"[bold blue]Farmácias Concorrentes:[/bold blue] {', '.join(p.value for p in target_pharmacies)}\n")

    service = ScraperService()
    try:
        location = await CepService.resolve(cep or client_info.cep)
    except ValueError as exc:
        console.print(f"[red]CEP inválido: {exc}[/red]")
        return

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
        console=console
    ) as progress:
        task = progress.add_task("[green]Varrendo produtos...", total=len(products))

    for prod in products:
            progress.update(task, description=f"[green]Pesquisando: {prod.name[:25]}...")
            await service.scrape_product_item(
                prod, target_pharmacies,
                cep=location.cep if location else None,
                city=location.city if location else client_info.city,
                state=location.state if location else client_info.state,
            )
            progress.advance(task)

    await price_history_service.record_client_scrape(
        client_info,
        products,
        cep=location.cep if location else None,
        city=location.city if location else client_info.city,
        state=location.state if location else client_info.state,
    )

    # Gerar planilha Excel
    output_path = ExcelService.generate_enriched_report(client_info, products, target_pharmacies)
    extra_paths = ReportExportService.generate(client_info, products, target_pharmacies)
    console.print(f"\n[bold green][OK] Relatório gerado com sucesso em:[/bold green]")
    console.print(f"[cyan]{output_path}[/cyan]\n")
    console.print("[bold green]Exportações adicionais:[/bold green]")
    for path in extra_paths:
        console.print(f"[cyan]{path}[/cyan]")


async def cmd_validate_scrapers(
    fixture: str = None,
    pharmacies: list[str] = None,
    cep: str = None,
    limit: int = None,
):
    """Valida as integrações usando EANs públicos de referência."""
    selected = [PharmacyEnum(value) for value in pharmacies] if pharmacies else None
    validator = ScraperValidationService()
    try:
        with console.status("[bold green]Validando scrapers por EAN..."):
            report = await validator.run_from_fixture(
                path=fixture, pharmacies=selected, cep=cep, limit=limit,
            )
            await price_history_service.record_validation(report)
    except ValueError as exc:
        console.print(f"[red]Erro de validação: {exc}[/red]")
        return

    table = Table(title="Validação de Scrapers", header_style="bold blue")
    table.add_column("EAN", style="cyan")
    table.add_column("Farmácia", style="white")
    table.add_column("Status", style="yellow")
    table.add_column("Preço", justify="right", style="green")
    table.add_column("Diagnóstico", style="dim")
    for entry in report.entries:
        detail = entry.error_message or entry.product_name or "-"
        price = f"R$ {entry.price:.2f}" if entry.price is not None else "-"
        table.add_row(entry.ean, entry.pharmacy_name, entry.status.value.upper(), price, detail)
    console.print(table)

    summary = Table(title="Resumo por Farmácia", header_style="bold blue")
    summary.add_column("Farmácia", style="cyan")
    for status in ScrapeStatusEnum:
        summary.add_column(status.value, justify="right")
    for pharmacy, counts in report.status_summary().items():
        summary.add_row(pharmacy, *(str(counts[status.value]) for status in ScrapeStatusEnum))
    console.print(summary)

    json_path, csv_path = validator.export(report)
    console.print("\n[bold green]Relatórios de validação gerados:[/bold green]")
    console.print(f"[cyan]{json_path}[/cyan]")
    console.print(f"[cyan]{csv_path}[/cyan]")


def main():
    parser = argparse.ArgumentParser(description="WebScrapping Farmácias - CLI de Consulta de Preços")
    subparsers = parser.add_subparsers(dest="command", help="Comandos disponíveis")

    # Comando list-clients
    subparsers.add_parser("list-clients", help="Lista clientes e planilhas detectadas")

    # Comando search
    search_parser = subparsers.add_parser("search", help="Pesquisa preço de um produto avulso")
    search_parser.add_argument("--ean", type=str, help="Código EAN do produto")
    search_parser.add_argument("--query", type=str, help="Nome ou termo do produto")
    search_parser.add_argument("--cep", type=str, help="CEP para contextualizar a busca regional")

    # Comando scrape-client
    client_parser = subparsers.add_parser("scrape-client", help="Varre a planilha de um cliente e gera relatório")
    client_parser.add_argument("--folder", type=str, required=True, help="Nome da pasta do cliente (ex: '1167 CARIN')")
    client_parser.add_argument("--limit", type=int, default=None, help="Limite de produtos a consultar")
    client_parser.add_argument("--cep", type=str, default=None, help="CEP para contextualizar preço e estoque")

    # Comando listar-eans
    eans_parser = subparsers.add_parser(
        "listar-eans",
        help="Imprime os EANs da planilha como lista JS, para a coleta assistida",
    )
    eans_parser.add_argument("--folder", type=str, required=True, help="Nome da pasta do cliente")
    eans_parser.add_argument("--limit", type=int, default=None, help="Limite de EANs")

    # Comando validate-scrapers
    validation_parser = subparsers.add_parser(
        "validate-scrapers",
        help="Valida todos os scrapers por EAN e gera relatório JSON/CSV",
    )
    validation_parser.add_argument(
        "--fixture",
        type=str,
        default=None,
        help="Arquivo JSON com produtos de referência (padrão: app/fixtures/validation_products.json)",
    )
    validation_parser.add_argument(
        "--pharmacies",
        nargs="+",
        choices=[pharmacy.value for pharmacy in PharmacyEnum],
        help="Farmácias a validar; se omitido, valida todas",
    )
    validation_parser.add_argument("--cep", type=str, default=None, help="CEP opcional para validação regional")
    validation_parser.add_argument("--limit", type=int, default=None, help="Limita os EANs do arquivo de referência")

    args = parser.parse_args()

    if args.command == "list-clients":
        cmd_list_clients()
    elif args.command == "search":
        asyncio.run(cmd_search(ean=args.ean, query=args.query, cep=args.cep))
    elif args.command == "listar-eans":
        cmd_listar_eans(folder=args.folder, limit=args.limit)
    elif args.command == "scrape-client":
        asyncio.run(cmd_scrape_client(folder=args.folder, limit=args.limit, cep=args.cep))
    elif args.command == "validate-scrapers":
        asyncio.run(cmd_validate_scrapers(
            fixture=args.fixture,
            pharmacies=args.pharmacies,
            cep=args.cep,
            limit=args.limit,
        ))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
