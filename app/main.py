from contextlib import asynccontextmanager
from datetime import datetime
import io
import mimetypes
from pathlib import Path
import time
from typing import List, Optional
from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse

from app.core.config import settings
from app.core.logging import logger
from app.db.session import database
from app.models.client import ClientInfo, ClientScrapeRequest, ClientScrapeResponse, ScrapeJobResponse
from app.models.history import PriceHistoryItem, PriceHistorySummary
from app.models.product import PharmacyEnum, SearchRequest, SearchResponse
from app.scrapers.registry import ScraperRegistry
from app.services.excel_service import ExcelService
from app.services.scraper_service import ScraperService
from app.services.cep_service import CepService
from app.services.job_service import ScrapeJobService
from app.services.report_export_service import ReportExportService
from app.services.price_history_service import PriceHistoryService

@asynccontextmanager
async def lifespan(_: FastAPI):
    """Inicializa o esquema do banco antes de aceitar requisições."""
    await database.create_schema()
    logger.info("Banco de dados conectado e esquema verificado.")
    yield
    await database.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    description="API de Web Scraping e Comparador de Preços para Redes de Farmácias do Instituto Bulla.",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Habilitar CORS para permitir consumo por frontends web ou dashboards
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

scraper_service = ScraperService()
job_service = ScrapeJobService()
price_history_service = PriceHistoryService()
STATIC_DIR = Path(__file__).parent / "static"


@app.get("/", include_in_schema=False)
async def root():
    """Redireciona para a documentação interativa."""
    return RedirectResponse(url="/docs")


@app.get("/dashboard", include_in_schema=False)
async def dashboard():
    """Interface web leve para consulta, upload e geração de relatórios."""
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")


@app.get("/health", tags=["Sistema"])
async def health_check():
    """Verifica a integridade da API."""
    database_ok = await database.ping()
    return {
        "status": "online",
        "database": "connected" if database_ok else "unavailable",
        "app_name": settings.APP_NAME,
        "timestamp": datetime.now().isoformat(),
        "environment": settings.APP_ENV
    }


@app.get("/api/v1/pharmacies", tags=["Farmácias"])
async def list_pharmacies():
    """Lista todas as redes de farmácias cadastradas no sistema e seus status."""
    pharmacies = ScraperRegistry.list_all()
    return {
        "total": len(pharmacies),
        "pharmacies": pharmacies
    }


@app.post("/api/v1/search", response_model=SearchResponse, tags=["Pesquisa de Preços"])
async def search_product(request: SearchRequest):
    """
    Pesquisa o preço de um produto por EAN (Código de Barras) ou por Nome.
    Consulta em paralelo as farmácias selecionadas (ou todas se omitido).
    """
    if not request.ean and not request.query:
        raise HTTPException(
            status_code=400,
            detail="É necessário fornecer pelo menos o 'ean' ou o 'query' para pesquisa."
        )

    logger.info(f"Recebida requisição de busca: EAN={request.ean}, Query={request.query}")
    try:
        response = await scraper_service.search(request)
        await price_history_service.record_search(response)
        return response
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/v1/history/{ean}", response_model=list[PriceHistoryItem], tags=["Histórico de Preços"])
async def get_price_history(
    ean: str,
    pharmacy: Optional[PharmacyEnum] = None,
    limit: int = Query(100, ge=1, le=500),
):
    """Lista as cotações registradas para um produto, da mais recente à mais antiga."""
    return await price_history_service.get_history(ean, pharmacy=pharmacy, limit=limit)


@app.get(
    "/api/v1/history/{ean}/summary",
    response_model=PriceHistorySummary,
    tags=["Histórico de Preços"],
)
async def get_price_history_summary(ean: str):
    """Retorna a última cotação conhecida de cada farmácia para um EAN."""
    return await price_history_service.get_summary(ean)


@app.get("/api/v1/clients", response_model=List[ClientInfo], tags=["Clientes & Planilhas"])
async def list_clients():
    """
    Lista todos os clientes detectados na pasta Clientes/ com seus concorrentes
    e total de produtos configurados.
    """
    return ExcelService.list_available_clients()


async def _run_client_scrape(client_folder: str, request: ClientScrapeRequest) -> ClientScrapeResponse:
    """Executa a rotina compartilhada pela chamada síncrona e pela fila local."""
    limit = request.limit
    pharmacies_filter = request.pharmacies
    start_time = time.time()
    client_info, products = ExcelService.parse_client_products(client_folder, limit=limit)

    if not products:
        raise ValueError("Nenhum produto encontrado na planilha do cliente.")

    # Determinar quais farmácias pesquisar
    if pharmacies_filter:
        target_pharmacies = pharmacies_filter
    elif client_info.competitors:
        target_pharmacies = [c.pharmacy_key for c in client_info.competitors if c.pharmacy_key]
        if not target_pharmacies:
            target_pharmacies = [PharmacyEnum.PRECO_POPULAR, PharmacyEnum.SAO_JOAO]
    else:
        target_pharmacies = [PharmacyEnum.PRECO_POPULAR, PharmacyEnum.SAO_JOAO]

    logger.info(
        f"Iniciando varredura para {client_info.client_name}: "
        f"{len(products)} produtos nas farmácias {[p.value for p in target_pharmacies]}"
    )

    # O CEP enviado substitui o da planilha; se houver, ele dá contexto à busca.
    location = await CepService.resolve(request.cep or client_info.cep)

    # Processar os produtos
    for prod in products:
        await scraper_service.scrape_product_item(
            prod, target_pharmacies,
            cep=location.cep if location else None,
            city=location.city if location else client_info.city,
            state=location.state if location else client_info.state,
        )

    await price_history_service.record_client_scrape(
        client_info,
        products,
        cep=location.cep if location else None,
        city=location.city if location else client_info.city,
        state=location.state if location else client_info.state,
    )

    # Gerar planilha Excel com resultados
    output_path = ExcelService.generate_enriched_report(client_info, products, target_pharmacies)
    additional_reports = ReportExportService.generate(client_info, products, target_pharmacies)
    report_paths = [output_path, *additional_reports]
    duration = round(time.time() - start_time, 2)

    return ClientScrapeResponse(
        client_id=client_info.id,
        client_name=client_info.client_name,
        total_products=client_info.total_products,
        scraped_products=len(products),
        report_file=output_path.name,
        report_files=[path.name for path in report_paths],
        download_url=f"/api/v1/reports/download/{output_path.name}",
        duration_seconds=duration,
        status="completed",
    )


async def _run_background_job(job_id: str, client_folder: str, request: ClientScrapeRequest) -> None:
    job_service.update(job_id, status="running")
    try:
        result = await _run_client_scrape(client_folder, request)
        job_service.update(
            job_id, status="completed", total_products=result.total_products,
            scraped_products=result.scraped_products, report_files=result.report_files,
            finished_at=datetime.now().isoformat(),
        )
    except Exception as exc:
        logger.exception(f"Falha na varredura em segundo plano {job_id}: {exc}")
        job_service.update(job_id, status="failed", error_message=str(exc), finished_at=datetime.now().isoformat())


@app.post(
    "/api/v1/clients/{client_folder}/scrape",
    response_model=ClientScrapeResponse,
    tags=["Clientes & Planilhas"]
)
async def scrape_client_spreadsheet(
    client_folder: str,
    background_tasks: BackgroundTasks,
    request: Optional[ClientScrapeRequest] = None,
):
    """Gera relatórios XLSX, CSV e JSON; opcionalmente executa em segundo plano."""
    request = request or ClientScrapeRequest()
    if request.background:
        try:
            # Valida a origem antes de devolver um job que necessariamente falharia.
            ExcelService.parse_client_products(client_folder, limit=1)
            CepService.normalize(request.cep)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        job = job_service.create(client_folder)
        background_request = request.model_copy(update={"background": False})
        background_tasks.add_task(_run_background_job, job.job_id, client_folder, background_request)
        return ClientScrapeResponse(
            client_id=client_folder.replace(" ", "_").lower(), client_name=client_folder,
            total_products=0, scraped_products=0, job_id=job.job_id, status="queued",
        )
    try:
        return await _run_client_scrape(client_folder, request)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/v1/jobs/{job_id}", response_model=ScrapeJobResponse, tags=["Processamento"])
async def get_scrape_job(job_id: str):
    job = job_service.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Processamento não encontrado.")
    return job


@app.post("/api/v1/clients/upload", response_model=ClientInfo, tags=["Clientes & Planilhas"])
async def upload_client_spreadsheet(
    client_name: str = Form(...), file: UploadFile = File(...),
):
    """Recebe uma nova planilha XLSX sem sobrescrever arquivos existentes."""
    folder_name = Path(client_name).name.strip()
    if not folder_name or folder_name in (".", ".."):
        raise HTTPException(status_code=400, detail="Nome do cliente inválido.")
    if not file.filename or Path(file.filename).suffix.lower() != ".xlsx":
        raise HTTPException(status_code=400, detail="Envie uma planilha no formato .xlsx.")
    contents = await file.read()
    try:
        # Valida o formato antes de gravar em Clientes/.
        import openpyxl
        workbook = openpyxl.load_workbook(io.BytesIO(contents), read_only=True)
        workbook.close()
    except Exception:
        raise HTTPException(status_code=400, detail="O arquivo não é uma planilha XLSX válida.")
    target_dir = settings.CLIENTS_DIR / folder_name
    target_path = target_dir / Path(file.filename).name
    if target_path.exists():
        raise HTTPException(status_code=409, detail="Já existe uma planilha com esse nome para o cliente.")
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(contents)
    clients = ExcelService.list_available_clients()
    client = next((item for item in clients if item.folder_name == folder_name), None)
    if not client:
        raise HTTPException(status_code=500, detail="A planilha foi recebida, mas não pôde ser processada.")
    return client


@app.get("/api/v1/reports/download/{filename}", tags=["Relatórios"])
async def download_report(filename: str):
    """Permite baixar os relatórios XLSX, CSV e JSON gerados."""
    reports_root = settings.REPORTS_DIR.resolve()
    file_path = (reports_root / filename).resolve()
    if reports_root not in file_path.parents or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Relatório não encontrado.")
    media_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type=media_type,
    )
