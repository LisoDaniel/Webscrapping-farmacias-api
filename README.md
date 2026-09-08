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
* **Panvel** (`panvel.com`) — ⚠️ via coleta assistida: o bot manager da rede devolve HTTP 404 para clientes automatizados, então a busca é feita no navegador do operador. Veja abaixo.
* **Farmácias Araujo** (`araujo.com.br`, com detecção explícita de bloqueio WAF)
* **Farma Conde** (`farmaconde.com.br`, catálogo VTEX público)

As redes VTEX consultam o catálogo por `fq=alternateIds_Ean`, que exige
correspondência exata de EAN. Uma cotação nunca sai com um código que a loja não
confirmou: sem SKU com o EAN consultado, o resultado é "não encontrado" — jamais
o preço de um produto parecido.

### Coleta assistida (Panvel)

A Panvel bloqueia cliente automatizado por bot manager: o navegador recebe HTTP
200 e um script recebe 404. Em vez de forjar os sinais que o controle usa para
distinguir humano de robô, a busca é feita no navegador do próprio operador.

```bash
# 1. Gere a lista de EANs da planilha
uv run python -m app.cli listar-eans --folder "1167 CARIN"
```

2. Abra `panvel.com`, informe o CEP da região (os preços são regionais) e abra o
   console do navegador (F12).
3. Cole o conteúdo de `tools/captura_panvel.js` e rode
   `capturarPanvel([...])` com a lista do passo 1. Há intervalo entre as
   requisições, então uma planilha grande leva alguns minutos.
4. Mova o `panvel.json` baixado para a pasta `capturas/`.

A partir daí a Panvel entra normalmente nas varreduras. A cotação fica datada
pelo instante da captura, não pelo da leitura, e capturas com mais de 24 h
(`CAPTURE_MAX_AGE_HOURS`) são recusadas com um aviso para refazer a coleta —
preço velho não entra no relatório como se fosse atual.

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

### Banco de dados PostgreSQL

Com o Docker Desktop em execução, inicie o banco local:

```bash
docker compose up -d
docker compose ps
```

Na primeira inicialização da API, as tabelas `products`, `scrape_runs` e
`price_quotes` são criadas automaticamente. O banco mantém os dados no volume
Docker `postgres_data`, inclusive após reiniciar o container.

As credenciais locais de desenvolvimento estão em `.env.example`. Para um
ambiente compartilhado, crie um `.env` com senha própria antes de subir o
container. Para interromper o banco sem apagar o histórico:

```bash
docker compose stop
```

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

### 3. Validar os scrapers

O comando abaixo consulta cada rede apenas pelo EAN do arquivo
`app/fixtures/validation_products.json`, sem fallback por nome. Assim, um
bloqueio ou falha técnica não é confundido com produto inexistente.

```bash
uv run python -m app.cli validate-scrapers
```

Para testar redes específicas ou um CEP:

```bash
uv run python -m app.cli validate-scrapers --pharmacies panvel --cep 01001-000
```

Os relatórios JSON e CSV são gerados em `reports/` e não entram no Git. Antes
de usar a rotina como referência operacional, inclua outros EANs públicos no
arquivo de fixtures.
Por exigência de conformidade, a Araujo fica fora da validação automática até
haver acesso autorizado ao catálogo.

### Histórico de preços

Toda pesquisa da API, varredura de planilha e validação de scraper passa a ser
gravada automaticamente no PostgreSQL. Consulte pela API:

```text
GET /api/v1/history/7891058003555
GET /api/v1/history/7891058003555/summary
```

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
