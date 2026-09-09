"""Leitura dos payloads coletados manualmente no navegador.

Algumas redes bloqueiam cliente automatizado por bot manager. Em vez de fingir
ser um navegador para passar por esse controle, o operador roda a busca no
próprio navegador (ver ``tools/captura_panvel.js``), baixa o JSON e o projeto
consome esse arquivo.

Formato esperado em ``capturas/<rede>.json``::

    {
      "pharmacy": "panvel",
      "uf": "GO",
      "captured_at": "2026-09-08T20:36:45",
      "results": {
        "7891058003555": { ...payload cru da API... }
      }
    }
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from app.core.config import settings
from app.core.logging import logger


@dataclass(frozen=True)
class CapturedPayload:
    """Payload cru de uma rede, com a hora em que foi realmente coletado."""

    payload: dict[str, Any]
    captured_at: datetime
    uf: Optional[str] = None


class CaptureExpired(Exception):
    """A captura existe, mas é velha demais para virar preço no relatório."""

    def __init__(self, captured_at: datetime, max_age_hours: float):
        self.captured_at = captured_at
        self.max_age_hours = max_age_hours
        super().__init__(
            f"A captura é de {captured_at:%d/%m/%Y %H:%M} e passou do limite de "
            f"{max_age_hours:g}h. Refaça a coleta no navegador."
        )


class CaptureStore:
    """Localiza o payload capturado de um produto em uma rede."""

    def __init__(
        self,
        directory: Optional[Path] = None,
        max_age_hours: Optional[float] = None,
    ):
        self.directory = directory or settings.CAPTURES_DIR
        self.max_age_hours = (
            max_age_hours if max_age_hours is not None else settings.CAPTURE_MAX_AGE_HOURS
        )

    def _path(self, pharmacy_key: str) -> Path:
        return self.directory / f"{pharmacy_key}.json"

    def _load(self, pharmacy_key: str) -> Optional[dict[str, Any]]:
        path = self._path(pharmacy_key)
        if not path.is_file():
            return None
        try:
            content = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(f"Captura ilegível em {path}: {exc}")
            return None
        return content if isinstance(content, dict) else None

    @staticmethod
    def _parse_timestamp(raw: Any) -> Optional[datetime]:
        """Converte o carimbo da captura para hora local ingênua.

        O navegador grava em UTC (``...Z``) e o resto do sistema compara com
        ``datetime.now()``, que é local. Descartar o fuso em vez de converter
        fazia a captura parecer estar no futuro pela diferença do offset — e,
        com isso, a verificação de validade nunca expirava nada.
        """
        if not isinstance(raw, str):
            return None
        try:
            # O sufixo Z não é aceito pelo fromisoformat das versões antigas.
            momento = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if momento.tzinfo is not None:
            momento = momento.astimezone().replace(tzinfo=None)
        return momento

    def get(self, pharmacy_key: str, ean: str) -> Optional[CapturedPayload]:
        """Devolve o payload do EAN, ou None se a rede não foi capturada.

        Levanta ``CaptureExpired`` quando o arquivo existe e está velho: é uma
        situação acionável pelo operador, diferente de simplesmente não haver
        captura.
        """
        content = self._load(pharmacy_key)
        if content is None:
            return None

        captured_at = self._parse_timestamp(content.get("captured_at"))
        if captured_at is None:
            logger.warning(f"Captura de {pharmacy_key} sem 'captured_at' válido; ignorada.")
            return None
        if datetime.now() - captured_at > timedelta(hours=self.max_age_hours):
            raise CaptureExpired(captured_at, self.max_age_hours)

        results = content.get("results")
        if not isinstance(results, dict):
            return None
        payload = results.get(str(ean).strip())
        if not isinstance(payload, dict):
            return None

        uf = content.get("uf")
        return CapturedPayload(
            payload=payload,
            captured_at=captured_at,
            uf=uf if isinstance(uf, str) else None,
        )
