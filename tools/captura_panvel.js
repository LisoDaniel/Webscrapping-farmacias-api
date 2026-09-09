/*
 * Coleta assistida da Panvel.
 *
 * A rede bloqueia cliente automatizado por bot manager, então a coleta é feita
 * pelo navegador do próprio operador, na sessão que ele já abriu. Nada é
 * forjado: as requisições saem da mesma origem e com os mesmos cookies que a
 * página usa quando você busca à mão.
 *
 * COMO USAR
 *
 *   1. Abra https://www.panvel.com e informe o CEP da região que interessa —
 *      os preços são regionais e a captura herda a UF da sua sessão.
 *   2. Abra o console do navegador (F12 > Console).
 *   3. Cole este arquivo inteiro e tecle Enter.
 *   4. Chame a função com os EANs, por exemplo:
 *
 *        capturarPanvel(["7891058003555", "7897595901033"])
 *
 *      Para varrer a planilha de um cliente, gere a lista com:
 *
 *        uv run python -m app.cli listar-eans --folder "1167 CARIN"
 *
 *   5. Ao final o navegador baixa "panvel.json". Mova o arquivo para a pasta
 *      "capturas/" na raiz do projeto.
 *
 * O intervalo entre requisições é deliberado: a coleta acompanha o ritmo de uso
 * humano em vez de disparar tudo de uma vez.
 *
 * SE DER HTTP 400
 *
 * A busca exige "covenantCode" na query string e o header "user-id". Os dois
 * são procurados sozinhos no armazenamento do storefront; não estando lá, o
 * console diz onde encontrá-los no DevTools. Para passar na mão:
 *
 *     capturarPanvel(eans, { covenantCode: "416061", userId: "8601417" })
 *
 * O mesmo vale para a UF, se o preço vier de outra região:
 *
 *     capturarPanvel(eans, { uf: "RS" })
 *
 * O corpo da resposta de erro é impresso junto do status — a API costuma
 * nomear exatamente o campo ou cabeçalho que faltou.
 */

/*
 * espiarPanvel() — descobre o contrato real da busca.
 *
 * Em vez de adivinhar o formato do corpo, observa a requisição que a própria
 * página dispara. Rode, faça uma busca normal no site, e o console imprime a
 * URL, o método e o payload exatos. Só lê; não altera nada do que é enviado.
 */
function espiarPanvel() {
  const ehBusca = (url) => String(url || "").includes("/api/v3/search");
  const mostrar = (origem, url, metodo, corpo) => {
    console.log(`%c[Panvel] requisição real (${origem})`, "color:#1f4e79;font-weight:bold");
    console.log("  URL   :", url);
    console.log("  Método:", metodo);
    console.log("  Corpo :", corpo);
  };

  const fetchOriginal = window.fetch;
  window.fetch = function (entrada, init) {
    const url = typeof entrada === "string" ? entrada : entrada && entrada.url;
    if (ehBusca(url)) mostrar("fetch", url, (init && init.method) || "GET", init && init.body);
    return fetchOriginal.apply(this, arguments);
  };

  // O HttpClient do Angular usa XMLHttpRequest, não fetch.
  const abrirOriginal = XMLHttpRequest.prototype.open;
  const enviarOriginal = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (metodo, url) {
    this.__panvelUrl = url;
    this.__panvelMetodo = metodo;
    return abrirOriginal.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function (corpo) {
    if (ehBusca(this.__panvelUrl)) {
      mostrar("xhr", this.__panvelUrl, this.__panvelMetodo, corpo);
    }
    return enviarOriginal.apply(this, arguments);
  };

  console.log(
    "%c[Panvel] espião ativo. Agora faça uma busca na página (ex.: digite 'puran t4' e tecle Enter).",
    "color:#18784a;font-weight:bold"
  );
}

/*
 * O código de convênio vai na query string e é obrigatório: sem ele a busca
 * responde HTTP 400. Não fica fixo no repositório porque pode variar por
 * sessão — é lido do armazenamento do storefront, e a opção explícita vence.
 * Se não for encontrado, copie da aba Network > a requisição "search" >
 * Payload > Query String Parameters > covenantCode.
 */
/*
 * A busca exige o header "user-id" — sem ele responde 400 dizendo
 * "Required header 'user-id' is not present".
 *
 * Aqui ele é legítimo: a requisição sai do seu navegador, na sua sessão, e já
 * vai com os seus cookies de qualquer forma — o mesmo header que o site manda
 * quando você busca à mão. Diferente seria fixá-lo no scraper Python, que roda
 * sem navegador nenhum: ali seria replicar uma sessão sintética, e por isso lá
 * ele continua fora.
 *
 * Não fica fixo no repositório porque identifica a sua conta.
 */
function descobrirUserId(opcoes) {
  if (opcoes.userId) return String(opcoes.userId);
  for (const store of [window.localStorage, window.sessionStorage]) {
    if (!store) continue;
    for (let i = 0; i < store.length; i++) {
      const chave = store.key(i);
      const achado = /user[_-]?id\D{0,10}(\d{4,12})/i.exec(`${chave}:${store.getItem(chave)}`);
      if (achado) return achado[1];
    }
  }
  const noCookie = document.cookie.match(/(?:^|;\s*)user[_-]?id=(\d{4,12})/i);
  return noCookie ? noCookie[1] : null;
}

function descobrirCovenantCode(opcoes) {
  if (opcoes.covenantCode) return String(opcoes.covenantCode);
  for (const store of [window.localStorage, window.sessionStorage]) {
    if (!store) continue;
    for (let i = 0; i < store.length; i++) {
      const chave = store.key(i);
      const achado = /covenant\D{0,20}(\d{4,10})/i.exec(`${chave}:${store.getItem(chave)}`);
      if (achado) return achado[1];
    }
  }
  return null;
}

async function capturarPanvel(eans, opcoes = {}) {
  const intervaloMs = opcoes.intervaloMs ?? 1500;
  // A UF acompanha o cookie que o storefront mantém, que nem sempre coincide
  // com o CEP exibido no topo. A opção explícita vence.
  const uf =
    opcoes.uf ||
    (document.cookie.match(/(?:^|;\s*)UF=([A-Za-z]{2})/) || [])[1] ||
    (document.cookie.match(/(?:^|;\s*)cookie_state=([A-Za-z]{2})/) || [])[1] ||
    "RS";

  if (!Array.isArray(eans) || eans.length === 0) {
    console.error('Passe uma lista de EANs: capturarPanvel(["7891058003555"])');
    return;
  }

  const covenantCode = descobrirCovenantCode(opcoes);
  if (!covenantCode) {
    console.error(
      "Não achei o covenantCode. Pegue em Network > requisição 'search' > Payload > " +
        'Query String Parameters, e rode: capturarPanvel(eans, {covenantCode: "416061"})'
    );
    return;
  }

  // O BFF exige o sessionId também como cabeçalho, não só como cookie. É o da
  // sua própria sessão, lido do navegador — nada é inventado aqui.
  const sessionId =
    opcoes.sessionId || (document.cookie.match(/(?:^|;\s*)sessionId=([^;]+)/i) || [])[1];
  if (!sessionId) {
    console.error(
      "Não achei o cookie sessionId. Recarregue a página do site logado e tente de novo."
    );
    return;
  }

  const userId = descobrirUserId(opcoes);
  if (!userId) {
    console.error(
      "Não achei o user-id, que a busca exige. Pegue em Network > requisição " +
        "'search' > Headers > Request Headers > user-id, e rode: " +
        'capturarPanvel(eans, {userId: "8601417"})'
    );
    return;
  }

  const resultados = {};
  const falhas = [];
  console.log(
    `[Panvel] capturando ${eans.length} EAN(s) — uf=${uf}, ` +
      `covenantCode=${covenantCode}, user-id=${userId}...`
  );

  for (let i = 0; i < eans.length; i++) {
    const ean = String(eans[i]).trim();
    try {
      const resposta = await fetch(
        `/api/v3/search?type=CSR&covenantCode=${encodeURIComponent(covenantCode)}` +
          `&uf=${encodeURIComponent(uf)}`,
        {
          method: "POST",
          credentials: "include",
          headers: {
            "content-type": "application/json",
            accept: "application/json, text/plain, */*",
            "app-token": "ZYkPuDaVJEiD",
            "user-id": userId,
            source: "desktop",
            // O BFF exige este header; o próprio site manda a constante "1".
            "client-ip": "1",
            "search-new": "A",
            sessionid: sessionId,
          },
          body: JSON.stringify({
            term: ean,
            itemsPerPage: 24,
            currentPage: 1,
            assortment: "mais relevantes",
            filters: [],
            searchOffers: false,
            searchType: "term",
          }),
        }
      );

      if (!resposta.ok) {
        // O corpo do erro costuma dizer qual campo a API recusou.
        const detalhe = await resposta.text().catch(() => "");
        falhas.push({ ean, status: resposta.status, detalhe: detalhe.slice(0, 200) });
        console.warn(`  ${ean}: HTTP ${resposta.status}`, detalhe.slice(0, 300));
      } else {
        resultados[ean] = await resposta.json();
        console.log(`  ${ean}: ok (${i + 1}/${eans.length})`);
      }
    } catch (erro) {
      falhas.push({ ean, erro: String(erro) });
      console.warn(`  ${ean}: ${erro}`);
    }

    if (i < eans.length - 1) {
      await new Promise((r) => setTimeout(r, intervaloMs));
    }
  }

  const captura = {
    pharmacy: "panvel",
    uf,
    covenant_code: covenantCode,
    captured_at: new Date().toISOString(),
    results: resultados,
  };

  const blob = new Blob([JSON.stringify(captura, null, 2)], {
    type: "application/json",
  });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = "panvel.json";
  link.click();
  URL.revokeObjectURL(link.href);

  console.log(
    `[Panvel] concluído: ${Object.keys(resultados).length} capturado(s), ` +
      `${falhas.length} falha(s).`
  );
  if (falhas.length) console.table(falhas);
  return captura;
}

console.log(
  "[Panvel] pronto.\n" +
    '  capturarPanvel(["7891058003555", "7897595901033"])  -> coleta\n' +
    "  espiarPanvel()  -> mostra a requisição real da página, se algo mudar"
);
