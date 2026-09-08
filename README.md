# WebScrapping Farmácias

API REST e Ferramenta de Linha de Comando (CLI) para consulta e monitoramento automatizado de preços de medicamentos e produtos em redes de farmácias brasileiras.

Desenvolvido para análise competitiva de preços do **Instituto Bulla**, com leitura automatizada das planilhas de clientes e concorrência local.

---

## 🏥 Farmácias Suportadas

* **Farmácia Preço Popular** (`precopopular.com.br`)
* **Farmácias São João** (`saojoaofarmacias.com.br`)
* **Droga Raia** (`drogaraia.com.br`)
* **Drogasil** (`drogasil.com.br`)
* **Drogarias Pacheco** (`drogariaspacheco.com.br`)
* **Drogaria São Paulo** (`drogariasaopaulo.com.br`)
* **Pague Menos** (`paguemenos.com.br`)
* **Panvel** (`panvel.com`)
* **Farmácias Araujo** (`araujo.com.br`, com detecção explícita de bloqueio WAF)

---

## 🚀 Como Executar

### 1. Iniciar o Servidor API (FastAPI)
```bash
uv run uvicorn app.main:app --reload --port 8000
```
Acesse a documentação Swagger interativa em:
👉 [http://localhost:8000/docs](http://localhost:8000/docs)

Interface web:
👉 [http://localhost:8000/dashboard](http://localhost:8000/dashboard)

### 2. Linha de Comando (CLI)

#### Pesquisar um produto avulso por EAN:
```bash
uv run python -m app.cli search --ean 7891058003555
```

#### Pesquisar por nome do produto:
```bash
uv run python -m app.cli search --query "Puran T4 12,5"
```

#### Pesquisar para uma região (CEP):
```bash
uv run python -m app.cli search --query "Puran T4 12,5" --cep 01001-000
```

#### Listar clientes e planilhas detectadas:
```bash
uv run python -m app.cli list-clients
```

#### Executar varredura da planilha de um cliente:
```bash
uv run python -m app.cli scrape-client --folder "1167 CARIN" --limit 10
```

Cada varredura gera os formatos `.xlsx`, `.csv` e `.json` em `reports/`.
Pela API, envie `{ "background": true }` para `POST /api/v1/clients/{folder}/scrape`
e acompanhe o resultado em `GET /api/v1/jobs/{job_id}`.

---

## 📁 Estrutura do Projeto

```
WebScrapping-farmacias/
├── Clientes/               # Planilhas de clientes do Instituto Bulla
├── app/
│   ├── main.py             # Aplicação FastAPI
│   ├── cli.py              # CLI para execução no terminal
│   ├── core/               # Configurações e logs
│   ├── models/             # Modelos de dados Pydantic
│   ├── scrapers/           # Módulos de scraping por farmácia
│   └── services/           # Leitura de planilhas e orquestração
│   └── static/             # Dashboard web simples
├── reports/                # Relatórios finais gerados
├── pyproject.toml
└── requirements.txt
```
