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
  - **Droga Raia** (`drogaraia.com.br`) — `curl_cffi` em processo com parser do Next.js `__NEXT_DATA__`.
  - **Drogasil** (`drogasil.com.br`) — `curl_cffi` em processo com parser do Next.js `__NEXT_DATA__`.
  - **Pague Menos** (`paguemenos.com.br`) — API VTEX Intelligent Search de alta performance (preços, descontos, links).

---

## 🟡 2. Pendências por Rede de Farmácia

| Farmácia | Prioridade | Desafio Técnico | Status |
| :--- | :---: | :--- | :--- |
| **Drogarias Pacheco** | ~~Alta~~ | VTEX Intelligent Search. | ✅ **CONCLUÍDO** |
| **Drogaria São Paulo (DPSP)** | ~~Média~~ | Pertence ao grupo Pacheco — herdou o scraper. | ✅ **CONCLUÍDO** |
| **Panvel Farmácias** | ~~Alta~~ | Bot manager da Azion devolve HTTP 404 sintético para cliente automatizado. | ✅ **COLETA ASSISTIDA** — validada com preços reais em 08/09/2026 |
| **Farmácias Araujo** | **Média** | Consulta VTEX implementada com identificação de WAF. A rede responde HTTP 403. | 🟡 Implementado; bloqueado externamente até haver canal/API autorizado |
| **Farma Conde** | ~~Alta~~ | Catálogo VTEX público. | ✅ **CONCLUÍDO** — validado por EAN exato |

### Operação e manutenção dos scrapers
1. **Panvel** — a rota está viva e correta: `POST /api/v3/search?type=CSR&uf=<UF>`, com o termo no corpo JSON e preços regionais por UF. O que bloqueia é o **bot manager da Azion**, que fica na frente do domínio: um navegador recebe HTTP 200; um cliente automatizado recebe 404, mesmo com a URL e o `app-token` corretos. O 404 é sintético, não é rota inexistente — as assinaturas do controle são os cookies `az_botm`/`az_asm` e os cabeçalhos `x-azion-*` na resposta ao navegador.

   Passar por ele exigiria reproduzir o cabeçalho `finger-print` e replicar aqueles cookies, sinais que existem só para separar humano de robô. Isso é derrotar um controle de acesso, não integrar com um serviço, e por isso não é feito aqui — mesmo critério da Araujo. O `app-token` é enviado por identificar a aplicação do storefront (é público e igual para todo visitante); o `user-id` fica de fora porque identifica uma conta pessoal, e associá-la a tráfego automatizado é risco para o titular.

   **Coleta assistida** é o caminho adotado no lugar disso. O operador roda `tools/captura_panvel.js` no console do próprio navegador; o script percorre os EANs com intervalo entre as chamadas e baixa um `panvel.json`, que vai para a pasta `capturas/`. As requisições saem de uma sessão real aberta por uma pessoa — nada é falsificado, e o controle da rede continua valendo. Havendo captura recente do EAN, ela é usada e a rede nem é consultada.

   Duas salvaguardas: a cotação é datada pelo instante da captura (não pelo da leitura), então o histórico registra quando o preço foi de fato observado; e capturas acima de `CAPTURE_MAX_AGE_HOURS` (24 h por padrão) são recusadas com aviso para refazer a coleta, em vez de virarem preço desatualizado apresentado como atual.

   Sem captura, a consulta devolve `ERROR` com o motivo. **Nunca `NOT_FOUND`**: isso faria o relatório afirmar que a rede não vende o produto, quando na verdade não chegamos a perguntar.

   O `CaptureStore` (`app/core/capture_store.py`) é genérico por rede, então a Araujo pode usar o mesmo mecanismo quando fizer sentido.

   **Contrato da busca**, verificado em 08/09/2026 por captura real: `POST /api/v3/search?type=CSR&covenantCode=<código>&uf=<UF>`. O BFF exige os cabeçalhos `user-id`, `client-ip` (constante `"1"`), `sessionId` e `app-token`, e recusa com HTTP 400 nomeando um faltante por vez. O `finger-print` que o navegador envia **não** é exigido — foi por isso que a coleta assistida coube sem tocar no controle anti-bot.

   **A resposta não traz o EAN.** O item tem `name`, `panvelCode`, `link` e `price`, e nada de código de barras. Como não há o que conferir, a correspondência é confirmada pela unicidade: `totalItems == 1` para uma consulta de 13 dígitos é a loja identificando o produto; resposta ambígua não vira cotação. Cuidado com `price.pack`, que é preço por unidade em pacote fechado (4 un.) e não serve como preço avulso.
2. **Araujo** — mesma política. O scraper usa a rota pública de catálogo VTEX e informa `blocked` para HTTP 401/403/429.

### Retry das consultas

`SCRAPER_RETRY_ATTEMPTS` existia na configuração mas não era lido por ninguém.
Agora vale: é o **total** de tentativas por farmácia (1 desliga), com espera
exponencial e folga aleatória entre elas (`SCRAPER_RETRY_BASE_DELAY` e
`SCRAPER_RETRY_MAX_DELAY`). A folga evita que as farmácias consultadas em
paralelo repitam todas no mesmo instante depois de uma queda de rede.

Só falhas técnicas são repetidas. `ERROR` significa que a consulta não chegou a
acontecer — queda de rede, timeout, resposta ilegível — e repetir pode resolver.
`NOT_FOUND` é resposta da loja e `BLOCKED` é a loja recusando: repetir o
primeiro não muda nada e repetir o segundo é insistir com quem acabou de pedir
para parar. Ambos saem na primeira tentativa.

### Droga Raia e Drogasil: por que saiu o `curl.exe`

O storefront responde 403 a clientes HTTP comuns e entrega o HTML a quem se
identifica como curl. Isso era feito chamando `curl.exe` por subprocesso, o que
tinha dois defeitos: só funcionava no Windows e **falhava dentro do servidor**.
O uvicorn roda em `SelectorEventLoop`, onde `asyncio.create_subprocess_exec`
levanta `NotImplementedError` — então as duas redes funcionavam pela CLI e
devolviam "Falha na comunicação de rede" pela API e pelo dashboard. Não era
instabilidade: eram dois caminhos com comportamentos diferentes.

`curl_cffi` (já era dependência do projeto e não era usada) faz a mesma
requisição em processo. Não há impersonação de navegador: imitar Chrome é o que
faz o WAF responder 403; identificar-se como curl é o que passa.

Como o `__NEXT_DATA__` não traz EAN — só `sku`, nome e preço — vale aqui a mesma
regra da Panvel: uma consulta por código de barras devolve **um** produto, uma
busca por nome devolve treze, e só a resposta única autoriza a cotação.

### Garantia de correspondência exata por EAN
Todas as redes VTEX (Preço Popular, São João, Pacheco, DPSP, Pague Menos, Farma Conde, Araujo) herdam de `app/scrapers/vtex.py` e consultam o catálogo pelo filtro `fq=alternateIds_Ean:<ean>`, que devolve correspondência exata.

O índice de texto livre `ft=` **não** cobre EAN em todas as lojas — era por isso que a Farma Conde devolvia "não encontrado" para qualquer EAN — e, onde cobre, pode trazer outro produto na primeira posição. A regra que vale hoje: **uma cotação só carrega um EAN que a loja confirmou.** Sem SKU com o código exato, o resultado é `NOT_FOUND`, nunca o preço de um item parecido. Coberto por `tests/test_vtex_scraper.py`.

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
  - **O histórico é best-effort.** Gravar é um subproduto da coleta: quando o
    banco recusa uma linha ou está fora do ar, a falha vai para o log e a
    execução segue. O relatório e a consulta já estão prontos nesse ponto —
    perdê-los para preservar o registro seria trocar o entregável pelo recibo.
  - O estado vindo da planilha é normalizado para a sigla de duas letras em
    `app/core/locations.py`. As cinco planilhas de cliente traziam o estado por
    extenso ("RIO GRANDE DO SUL", "PARANÁ", …), o que estourava o `varchar(2)`
    de `scrape_runs.state` e derrubava a varredura **antes** de gerar o
    relatório. Sem `--cep`, `scrape-client` não funcionava para nenhum cliente;
    com `--cep` o ViaCEP devolvia a sigla e o defeito passava despercebido.
- [ ] **Ampliar o acervo de farmácias consultadas**:
  - Mapear novas redes regionais e nacionais, priorizando catálogos públicos ou APIs/feed de preços autorizados.
  - Validar cada integração por EAN e CEP antes de liberá-la para as varreduras de clientes.
  - Candidatas iniciais: Drogaria Catarinense, Drogaria Venancio, Drogaria Minas-Brasil e Farmácias Nissei.

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
