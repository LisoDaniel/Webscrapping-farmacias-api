"""Resolução leve de CEP para dar contexto regional às consultas."""

import re
from dataclasses import dataclass
from typing import Optional

import httpx


@dataclass(frozen=True)
class CepLocation:
    cep: str
    city: Optional[str] = None
    state: Optional[str] = None


class CepService:
    base_url = "https://viacep.com.br/ws"

    @staticmethod
    def normalize(cep: Optional[str]) -> Optional[str]:
        if not cep:
            return None
        clean = re.sub(r"\D", "", cep)
        if len(clean) != 8:
            raise ValueError("CEP deve conter exatamente 8 dígitos.")
        return clean

    @classmethod
    async def resolve(cls, cep: Optional[str]) -> Optional[CepLocation]:
        clean = cls.normalize(cep)
        if not clean:
            return None
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(f"{cls.base_url}/{clean}/json/")
        if response.status_code != 200:
            raise ValueError("Não foi possível localizar o CEP informado.")
        data = response.json()
        if data.get("erro"):
            raise ValueError("CEP não encontrado.")
        return CepLocation(cep=clean, city=data.get("localidade"), state=data.get("uf"))
