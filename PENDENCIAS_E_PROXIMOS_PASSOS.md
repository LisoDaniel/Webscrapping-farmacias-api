# 📋 Pendências e Próximos Passos - WebScrapping Farmácias

Documento de acompanhamento do desenvolvimento da ferramenta e API de Web Scraping de preços para redes de farmácias do **Instituto Bulla**.

---

## 🟢 1. O Que Já Está Concluído e Funcionando

- [x] **Arquitetura Base**: Projeto modular estruturado com FastAPI, Pydantic, HTTPX e OpenPyXL.
- [x] **Ambiente e Dependências**: Configurado com Python 3.12 e gerenciador `uv` (`pyproject.toml` e `requirements.txt`).
- [x] **Leitor de Planilhas de Clientes (`ExcelService`)**:
  - Detecção automática de clientes na pasta `Clientes/` (`CARIN`, `MATHEUS`, `CHRISTIAN`, `MARIANA`, `KLEBER`).
  - Extração de produtos por EAN, nome, laboratório e PMC.
  - Identificação automática dos concorrentes configurados na planilha e da cidade/UF do cliente.
- [x] **Gerador de Relatórios Comparativos**:
  - Geração de planilha estilizada em `reports/` com preços de cada concorrente, links de ofertas, % de desconto e indicação automática da farmácia mais barata.
- [x] **Interface de Linha de Comando (`app/cli.py`)**:
  - `list-clients`: Lista todas as planilhas e concorrentes detectados.
  - `search`: Consulta avulsa por EAN ou termo com tabela no terminal.
  - `scrape-client`: Executa a varredura da planilha de um cliente com barra de progresso.
- [x] **API REST FastAPI (`app/main.py`)**:
  - Documentação Swagger interativa em `/docs`.
  - Endpoints de consulta (`/api/v1/search`), clientes (`/api/v1/clients`), varredura (`/api/v1/clients/{folder}/scrape`) e download (`/api/v1/reports/download/{file}`).
- [x] **Scrapers 100% Funcionais (7 redes)**:
  - **Farmácia Preço Popular** (`precopopular.com.br`) — API VTEX direta (preços, descontos, links).
  - **Farmácias São João** (`saojoaofarmacias.com.br`) — API VTEX direta (preços, disponibilidade, links).
  - **Droga Raia** (`drogaraia.com.br`) — Subprocesso nativo de alta velocidade com parser do Next.js `__NEXT_DATA__` contornando proteções WAF.
  - **Drogasil** (`drogasil.com.br`) — Subprocesso nativo de alta velocidade com parser do Next.js `__NEXT_DATA__` contornando proteções WAF.
  - **Pague Menos** (`paguemenos.com.br`) — API VTEX Intelligent Search de alta performance (preços, descontos, links).

---

## 🟡 2. Pendências por Rede de Farmácia

| Farmácia | Prioridade | Desafio Técnico | Status |
| :--- | :---: | :--- | :--- |
| **Drogarias Pacheco** | ~~Alta~~ | VTEX Intelligent Search. | ✅ **CONCLUÍDO** |
| **Drogaria São Paulo (DPSP)** | ~~Média~~ | Pertence ao grupo Pacheco — herdou o scraper. | ✅ **CONCLUÍDO** |
| **Panvel Farmácias** | **Alta** | Integração da busca Angular (API JSON + fallback SSR), sem dependência de browser headless. | 🟡 Implementado; validar periodicamente contra mudanças do storefront |
| **Farmácias Araujo** | **Média** | Consulta VTEX implementada com identificação de WAF. A rede respondeu HTTP 403 na validação. | 🟡 Implementado; bloqueado externamente até haver canal/API autorizado |
| **Farma Conde** | ~~Alta~~ | Catálogo VTEX público por EAN/termo. | ✅ Implementado e validado por busca textual |

### Operação e manutenção dos novos scrapers
1. **Panvel** — a busca usa a rota JSON exposta pelo storefront e tenta o HTML SSR como fallback. Se o contrato do site mudar, o resultado passa a refletir erro/bloqueio, sem inventar preço.
2. **Araujo** — o scraper usa a rota pública de catálogo VTEX e informa `blocked` para HTTP 401/403/429. A obtenção de preços enquanto o WAF estiver ativo depende de uma API ou integração autorizada pela rede.

---

## 🔵 3. Melhorias e Recursos Futuros

- [x] **Geolocalização / Preço por Região (CEP)**:
  - Adicionar suporte a CEP para que a consulta traga o preço e estoque da filial mais próxima da cidade do cliente (ex: Venâncio Aires/RS, Campos/RJ).
- [x] **Fila de Processamento em Background (BackgroundTasks)**:
  - Para varreduras de planilhas com centenas de itens, permitir que a API processe em segundo plano e notifique quando o relatório estiver pronto.
- [x] **Exportação em Múltiplos Formatos**:
  - Além de `.xlsx`, permitir exportação em `.json` e `.csv`.
- [x] **Dashboard Web Frontend**:
  - Interface visual simples (React ou HTML/Tailwind) para que o consultor do Instituto Bulla faça upload de planilhas e visualize o comparativo de preços na tela.
- [x] **Histórico de Preços (PostgreSQL)**:
  - Persistência de produtos, execuções de coleta e cotações por farmácia.
  - Consulta de histórico e último preço conhecido por EAN em `/api/v1/history/{ean}`.

---

## 🛠️ 4. Guia Rápido: Como Criar um Novo Módulo de Farmácia

Para adicionar uma nova farmácia ao sistema:

1. **Criar o arquivo do scraper** em `app/scrapers/<nome_rede>.py` herdando de `BaseScraper`:
   ```python
   from app.scrapers.base import BaseScraper
   from app.models.product import PharmacyEnum, PriceQuote, ScrapeStatusEnum

   class MinhaFarmaciaScraper(BaseScraper):
       pharmacy_key = PharmacyEnum.MINHA_FARMACIA
       name = "Minha Farmácia"
       base_url = "https://www.minhafarmacia.com.br"

       async def search_by_ean(self, ean: str) -> PriceQuote:
           # Lógica de consulta por EAN
           ...

       async def search_by_term(self, term: str) -> PriceQuote:
           # Lógica de consulta por termo/nome
           ...
   ```
2. **Adicionar o enum** em `app/models/product.py`:
   ```python
   class PharmacyEnum(str, Enum):
       ...
       MINHA_FARMACIA = "minhafarmacia"
   ```
3. **Registrar no Factory** em `app/scrapers/registry.py`:
   ```python
   _scrapers = {
       ...
       PharmacyEnum.MINHA_FARMACIA: MinhaFarmaciaScraper,
   }
   ```
4. **Testar imediatamente no terminal**:
   ```bash
   uv run python -m app.cli search --ean 7891058003555
   ```
