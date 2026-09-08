"""Normalização de unidades federativas vindas das planilhas de clientes."""

import unicodedata
from typing import Optional

_UF_BY_NAME = {
    "acre": "AC",
    "alagoas": "AL",
    "amapa": "AP",
    "amazonas": "AM",
    "bahia": "BA",
    "ceara": "CE",
    "distrito federal": "DF",
    "espirito santo": "ES",
    "goias": "GO",
    "maranhao": "MA",
    "mato grosso": "MT",
    "mato grosso do sul": "MS",
    "minas gerais": "MG",
    "para": "PA",
    "paraiba": "PB",
    "parana": "PR",
    "pernambuco": "PE",
    "piaui": "PI",
    "rio de janeiro": "RJ",
    "rio grande do norte": "RN",
    "rio grande do sul": "RS",
    "rondonia": "RO",
    "roraima": "RR",
    "santa catarina": "SC",
    "sao paulo": "SP",
    "sergipe": "SE",
    "tocantins": "TO",
}

_UF_CODES = set(_UF_BY_NAME.values())


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def normalize_state(value: Optional[str]) -> Optional[str]:
    """Converte "RIO GRANDE DO SUL" ou "rs" na sigla "RS".

    As planilhas de clientes trazem o estado ora por extenso, ora abreviado, e
    todo o resto do sistema espera a sigla de duas letras — o histórico grava
    em ``varchar(2)`` e a busca regional usa o valor como parâmetro ``uf``.

    Devolver ``None`` para um valor irreconhecível é deliberado: é melhor não
    ter estado do que propagar um texto que nenhum consumidor sabe interpretar.
    """
    if not value:
        return None
    clean = " ".join(_strip_accents(str(value)).strip().lower().split())
    if not clean:
        return None
    if len(clean) == 2 and clean.upper() in _UF_CODES:
        return clean.upper()
    return _UF_BY_NAME.get(clean)
