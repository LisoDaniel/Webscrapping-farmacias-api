# WebScrapping Farmácias — Instituto Bulla

API FastAPI + CLI que lê planilhas de clientes, consulta o preço de cada produto
em redes de farmácia e gera relatório comparativo (XLSX/CSV/JSON), com histórico
em PostgreSQL.

## Comandos

```bash
uv run python -m app.cli list-clients                          # clientes detectados
uv run python -m app.cli search --ean 7891058003555            # consulta avulsa
uv run python -m app.cli scrape-client --folder "1167 CARIN"   # varredura + relatório
uv run python -m app.cli validate-scrapers                     # diagnóstico das integrações
uv run uvicorn app.main:app --reload --port 8000               # API + /dashboard
.venv/Scripts/python.exe -m unittest discover -s tests -t .    # suíte (Windows)
```

`validate-scrapers` é a forma mais rápida de ver quais redes estão de pé.

---

# A regra que governa o projeto

**Nunca afirmar o que não foi verificado.** Um preço errado ou um "não existe"
falso vai para o relatório de um consultor e vira decisão comercial. Preferir
sempre a falha visível ao palpite silencioso.

Isso se traduz em dois invariantes.

## 1. Uma cotação só carrega um EAN que a loja confirmou

Nunca devolver o preço de um item parecido carimbando o EAN consultado por cima.
Sem confirmação, o resultado é `NOT_FOUND`.

Há duas formas de confirmar, conforme a rede devolva ou não o EAN:

| Situação | Como confirmar |
| :--- | :--- |
| A resposta traz o EAN (lojas VTEX) | Comparar com o EAN consultado; sem SKU idêntico → `NOT_FOUND` |
| A resposta **não** traz EAN (Panvel, RD) | **Unicidade**: consulta por código de barras que devolve exatamente 1 produto identifica o item; 2 ou mais é ambíguo → `NOT_FOUND` |

A unicidade funciona porque a busca aceita o código de barras como termo: um EAN
devolve 1 resultado, um nome ("puran t4") devolve 13.

## 2. Cada status significa uma coisa só

| Status | Quando |
| :--- | :--- |
| `SUCCESS` | Preço obtido e correspondência confirmada |
| `NOT_FOUND` | **A loja respondeu** e não tem o produto |
| `BLOCKED` | A loja recusou a consulta (HTTP 401/403/429) |
| `ERROR` | Não conseguimos perguntar — rede fora, status inesperado, resposta ilegível |

O erro capital é devolver `NOT_FOUND` quando não chegamos a perguntar: o
relatório passa a afirmar que a rede não vende o produto. Já aconteceu duas
vezes neste projeto (Farma Conde e Panvel) e foi o que motivou boa parte da
arquitetura atual.

O retry em `ScraperService` repete **apenas** `ERROR`. `NOT_FOUND` é resposta da
loja e `BLOCKED` é a loja pedindo para parar — insistir seria martelar.

---

# Como adicionar uma nova farmácia

## Passo 0: descobrir o tipo da loja

```bash
curl -s "https://<dominio>/api/catalog_system/pub/products/search?fq=alternateIds_Ean:7891058003555" | head -c 400
```

Devolveu JSON com `productName` e `items[].ean`? É **VTEX** — o caso fácil, e a
maioria das redes brasileiras é. Vá para o Caminho A.

Caso contrário, Caminho B.

## Caminho A — loja VTEX (8 linhas)

```python
# app/scrapers/minha_rede.py
from app.models.product import PharmacyEnum
from app.scrapers.vtex import VtexCatalogScraper


class MinhaRedeScraper(VtexCatalogScraper):
    pharmacy_key = PharmacyEnum.MINHA_REDE
    name = "Minha Rede"
    base_url = "https://www.minharede.com.br"
```

`VtexCatalogScraper` (`app/scrapers/vtex.py`) já faz tudo: busca por
`fq=alternateIds_Ean`, verificação de EAN exato, HTTP 206 como sucesso,
401/403/429 como `BLOCKED`, URL relativa virando absoluta, desconto.

Se a rede também expuser o Intelligent Search (`/api/io/_v/api/intelligent-search/product_search/`),
herde de `VtexIntelligentSearchScraper`: a busca por EAN continua no catálogo,
que é o único lugar com filtro exato, e a busca textual usa o IS, que tem
relevância melhor. É o caso de Pacheco e Pague Menos.

**Nunca reimplemente o parsing VTEX num scraper novo.** Se precisar de algo que
a base não faz, estenda a base.

## Caminho B — loja com API própria

Modelo: `app/scrapers/panvel.py` e `app/scrapers/drogaraia_drogasil.py`.

**Descubra o contrato observando, não adivinhando.** Este projeto já perdeu
tempo inferindo formato de payload a partir de código antigo e errou. O caminho
certo: DevTools → Network → filtro `api` → aba **Payload** e **Headers** da
requisição real. A APIs bem-feitas recusam com 400 nomeando o campo que falta,
um por vez — siga a trilha.

Implemente:

1. `_fetch` devolvendo **status HTTP e corpo**, não só o corpo. Sem o status não
   dá para distinguir bloqueio de ausência.
2. Mapeamento de status → `BLOCKED` / `ERROR` / segue para parsing.
3. Parsing com confirmação de EAN pela regra que couber (ver invariante 1).
4. `search_by_ean` e `search_by_term`.

Use `curl_cffi` (`AsyncSession`), não `httpx`, quando a loja recusar cliente
comum — e **nunca subprocesso**: o uvicorn roda em `SelectorEventLoop`, onde
`asyncio.create_subprocess_exec` levanta `NotImplementedError`. Isso já fez Raia
e Drogasil funcionarem pela CLI e falharem pela API sem ninguém notar.

## Passo final (os dois caminhos)

1. Enum em `app/models/product.py` → `PharmacyEnum.MINHA_REDE = "minharede"`
2. Registro em `app/scrapers/registry.py` → `_scrapers` **e** `_domain_aliases`
   (os aliases fazem a planilha do cliente reconhecer a rede pelo domínio ou
   pelo nome)
3. Export em `app/scrapers/__init__.py`
4. Teste em `tests/` — ver seção abaixo
5. `uv run python -m app.cli validate-scrapers --pharmacies minharede`

---

# Redes que bloqueiam coleta automatizada

Algumas redes têm bot manager. **Não construa evasão**: nada de reproduzir
fingerprint de navegador, replicar cookies do bot manager ou forjar sessão de
terceiros. É o critério já aplicado à Araujo e à Panvel.

Distinção que vale: mandar cabeçalhos que a API exige e que identificam a
aplicação (`app-token`) ou o protocolo (`client-ip`, `source`) é falar o
protocolo. Reproduzir `finger-print` para parecer humano é enganar o mecanismo.

Quando a rede bloqueia, há dois caminhos:

- **Deixar falhar honestamente** (`BLOCKED`/`ERROR` com motivo). É o caso da Araujo.
- **Coleta assistida**: o operador roda a busca no próprio navegador com um
  script em `tools/`, baixa o JSON, e `CaptureStore` (`app/core/capture_store.py`)
  o entrega ao parser. É o caso da Panvel — ver `tools/captura_panvel.js`.

O `CaptureStore` é genérico por rede. Captura expira em
`CAPTURE_MAX_AGE_HOURS` (24h) e a cotação é datada pelo **instante da captura**,
não pelo da leitura — preço velho não pode entrar como atual. O dashboard mostra
a idade na coluna "Observado".

---

# Testes

```bash
.venv/Scripts/python.exe -m unittest discover -s tests -t .
```

Convenções que valem para scraper novo:

- **Use o payload real**, capturado da loja — não invente o formato. Um teste
  que passa contra um payload imaginário não prova nada; já aconteceu aqui.
- Cubra o modo de falhar, não só o sucesso: 403 → `BLOCKED`, resposta vazia →
  `NOT_FOUND`, corpo ilegível → `ERROR`.
- Cubra a ambiguidade: EAN diferente ou múltiplos resultados **não** podem virar
  cotação.
- Testes que usam `CaptureStore` devem apontar para um diretório temporário,
  senão leem `capturas/` da máquina e passam pelo motivo errado.

Modelos: `tests/test_vtex_scraper.py` (verificação por EAN), `tests/test_rd_scraper.py`
(unicidade + transporte), `tests/test_panvel_scraper.py` (captura assistida).

---

# Armadilhas conhecidas

- **Preço de pacote.** A Panvel traz `price.pack` (preço por unidade em pacote
  fechado de 4). Ler isso como preço avulso deixa a rede artificialmente barata.
  Verifique se a loja tem campo equivalente.
- **Índice de texto livre não cobre EAN.** O `ft=` da VTEX não indexa código de
  barras em todas as lojas — a Farma Conde devolvia "não encontrado" para
  qualquer EAN por isso. Use sempre `fq=alternateIds_Ean`.
- **Preço é regional.** Panvel usa `uf` na query; VTEX varia por sessão. Uma
  captura feita com CEP de SP não serve para relatório de cliente do RS.
- **Planilhas de cliente não têm layout único.** As colunas são localizadas pelo
  cabeçalho em `ExcelService._mapear_colunas`; só uma das cinco planilhas traz
  PMC e preço do cliente.
- **Histórico é best-effort.** Falha de banco vai para o log e a execução segue —
  o relatório é o entregável, não o registro dele.
