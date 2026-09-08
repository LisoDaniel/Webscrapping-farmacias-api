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
 */

async function capturarPanvel(eans, opcoes = {}) {
  const intervaloMs = opcoes.intervaloMs ?? 1500;
  const uf =
    opcoes.uf ||
    (document.cookie.match(/(?:^|;\s*)UF=([A-Za-z]{2})/) || [])[1] ||
    "RS";

  if (!Array.isArray(eans) || eans.length === 0) {
    console.error("Passe uma lista de EANs: capturarPanvel([\"7891058003555\"])");
    return;
  }

  const resultados = {};
  const falhas = [];
  console.log(`[Panvel] capturando ${eans.length} EAN(s) para UF=${uf}...`);

  for (let i = 0; i < eans.length; i++) {
    const ean = String(eans[i]).trim();
    try {
      const resposta = await fetch(
        `/api/v3/search?type=CSR&uf=${encodeURIComponent(uf)}`,
        {
          method: "POST",
          credentials: "include",
          headers: {
            "content-type": "application/json",
            accept: "application/json, text/plain, */*",
            "app-token": "ZYkPuDaVJEiD",
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
        falhas.push({ ean, status: resposta.status });
        console.warn(`  ${ean}: HTTP ${resposta.status}`);
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
  "[Panvel] pronto. Rode: capturarPanvel([\"7891058003555\", \"7897595901033\"])"
);
