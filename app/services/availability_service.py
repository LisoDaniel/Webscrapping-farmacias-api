"""Disponibilidade das redes: onde dá para cotar agora.

O dashboard precisa responder uma pergunta operacional — "em quais redes eu
consigo preço neste momento?" — sem prometer mais do que sabemos. Estar
cadastrada no registry não torna uma rede disponível: a Araujo está registrada e
não pode ser consultada, e a Panvel depende de uma captura que vence em 24h.

Por isso cada linha carrega a origem da afirmação: a data da última validação, o
estado do arquivo de captura ou a política que impede a consulta. O que este
serviço não sabe, ele marca como não verificado em vez de supor que funciona.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from app.core.capture_store import CaptureSnapshot, CaptureStore
from app.core.config import settings
from app.core.logging import logger
from app.models.product import PharmacyEnum, ScrapeStatusEnum
from app.scrapers.registry import ScraperRegistry
from app.services.validation_service import ScraperValidationService


class AvailabilityEnum(str, Enum):
    """Situação de uma rede para efeito de cotação."""

    ONLINE = "online"                  # consulta direta respondendo
    CAPTURE_ONLY = "capture_only"      # só pela captura do navegador, ainda válida
    NEEDS_CAPTURE = "needs_capture"    # captura ausente ou vencida
    RESTRICTED = "restricted"          # coleta automatizada não autorizada
    FAILING = "failing"                # última validação não obteve preço
    UNVERIFIED = "unverified"          # sem validação que confirme


QUOTABLE = {AvailabilityEnum.ONLINE, AvailabilityEnum.CAPTURE_ONLY}


class CaptureInfo(BaseModel):
    """Estado da coleta assistida de uma rede."""

    captured_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    expired: bool
    eans: int
    uf: Optional[str] = None


class PharmacyAvailability(BaseModel):
    key: PharmacyEnum
    name: str
    base_url: str
    availability: AvailabilityEnum
    # Resposta direta ao operador: dá ou não dá para cotar nesta rede agora.
    quotable: bool
    detail: str
    last_checked_at: Optional[datetime] = None
    last_statuses: Optional[dict[str, int]] = None
    capture: Optional[CaptureInfo] = None


class AvailabilityReport(BaseModel):
    generated_at: datetime = Field(default_factory=datetime.now)
    total: int
    quotable: int
    # De onde vem a informação de funcionamento; ausente se nunca se validou.
    validated_at: Optional[datetime] = None
    validation_report: Optional[str] = None
    pharmacies: list[PharmacyAvailability]


@dataclass(frozen=True)
class _UltimaValidacao:
    """Leitura do relatório de validação mais recente em reports/."""

    path: Path
    executed_at: Optional[datetime]
    resumo: dict[str, dict[str, int]] = field(default_factory=dict)
    motivos: dict[str, str] = field(default_factory=dict)

    def contagem(self, key: str) -> Optional[dict[str, int]]:
        return self.resumo.get(key)


class AvailabilityService:
    """Monta o painel de disponibilidade a partir do que é verificável."""

    def __init__(
        self,
        capture_store: Optional[CaptureStore] = None,
        reports_dir: Optional[Path] = None,
    ):
        self.capture_store = capture_store or CaptureStore()
        self.reports_dir = reports_dir or settings.REPORTS_DIR

    # ------------------------------------------------------------------ leitura

    def _ultima_validacao(self) -> Optional[_UltimaValidacao]:
        """Pega o relatório mais recente que dê para ler.

        O nome traz o carimbo ``AAAAMMDD_HHMMSS``, então a ordem alfabética é a
        cronológica. Um arquivo corrompido não invalida o painel: cai para o
        anterior.
        """
        arquivos = sorted(self.reports_dir.glob("scraper_validation_*.json"))
        for caminho in reversed(arquivos):
            try:
                conteudo = json.loads(caminho.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning(f"Relatório de validação ilegível em {caminho}: {exc}")
                continue
            if not isinstance(conteudo, dict):
                continue

            resumo = conteudo.get("status_summary")
            entradas = conteudo.get("entries")
            if not isinstance(resumo, dict):
                resumo = self._resumir(entradas)
            return _UltimaValidacao(
                path=caminho,
                executed_at=self._data(conteudo.get("executed_at")),
                resumo={
                    chave: valor
                    for chave, valor in resumo.items()
                    if isinstance(valor, dict)
                },
                motivos=self._motivos(entradas),
            )
        return None

    @staticmethod
    def _data(bruto: object) -> Optional[datetime]:
        if not isinstance(bruto, str):
            return None
        try:
            momento = datetime.fromisoformat(bruto.replace("Z", "+00:00"))
        except ValueError:
            return None
        return momento.astimezone().replace(tzinfo=None) if momento.tzinfo else momento

    @staticmethod
    def _resumir(entradas: object) -> dict[str, dict[str, int]]:
        """Reconstrói a contagem por rede quando o relatório não a traz."""
        resumo: dict[str, dict[str, int]] = {}
        if not isinstance(entradas, list):
            return resumo
        for entrada in entradas:
            if not isinstance(entrada, dict):
                continue
            chave = entrada.get("pharmacy_key")
            status = entrada.get("status")
            if not isinstance(chave, str) or not isinstance(status, str):
                continue
            resumo.setdefault(chave, {})
            resumo[chave][status] = resumo[chave].get(status, 0) + 1
        return resumo

    @staticmethod
    def _motivos(entradas: object) -> dict[str, str]:
        """Guarda uma mensagem de erro por rede, para explicar a falha."""
        motivos: dict[str, str] = {}
        if not isinstance(entradas, list):
            return motivos
        for entrada in entradas:
            if not isinstance(entrada, dict):
                continue
            chave = entrada.get("pharmacy_key")
            mensagem = entrada.get("error_message")
            if isinstance(chave, str) and isinstance(mensagem, str) and mensagem.strip():
                motivos.setdefault(chave, mensagem.strip())
        return motivos

    # ----------------------------------------------------------- classificação

    def _por_captura(
        self, key: PharmacyEnum
    ) -> tuple[AvailabilityEnum, str, Optional[CaptureInfo]]:
        """Classifica uma rede que só entrega preço por coleta assistida."""
        snapshot: Optional[CaptureSnapshot] = self.capture_store.describe(key.value)
        script = f"tools/captura_{key.value}.js"
        if snapshot is None:
            return (
                AvailabilityEnum.NEEDS_CAPTURE,
                "A rede recusa consulta automatizada e não há captura em "
                f"capturas/{key.value}.json. Rode {script} no navegador para liberar.",
                None,
            )

        info = CaptureInfo(
            captured_at=snapshot.captured_at,
            expires_at=snapshot.expires_at,
            expired=snapshot.expired,
            eans=snapshot.eans,
            uf=snapshot.uf,
        )
        if snapshot.expired:
            quando = (
                f"de {snapshot.captured_at:%d/%m %H:%M}"
                if snapshot.captured_at
                else "sem data de coleta"
            )
            return (
                AvailabilityEnum.NEEDS_CAPTURE,
                f"A captura {quando} não vale mais "
                f"({settings.CAPTURE_MAX_AGE_HOURS:g}h de validade). Refaça a coleta "
                f"com {script} antes de usar em relatório.",
                info,
            )

        regiao = f" de {snapshot.uf}" if snapshot.uf else ""
        return (
            AvailabilityEnum.CAPTURE_ONLY,
            f"Disponível pela captura{regiao} de {snapshot.captured_at:%d/%m %H:%M}, "
            f"válida até {snapshot.expires_at:%d/%m %H:%M}. Cobre {snapshot.eans} "
            "EAN(s) coletados — produto fora dessa lista não tem preço, e a captura "
            "vale para a região em que foi feita.",
            info,
        )

    def _por_validacao(
        self, key: PharmacyEnum, validacao: Optional[_UltimaValidacao]
    ) -> tuple[AvailabilityEnum, str, Optional[dict[str, int]]]:
        """Classifica pelo resultado da última validação, nunca pelo cadastro."""
        if validacao is None:
            return (
                AvailabilityEnum.UNVERIFIED,
                "Nunca validada nesta instalação. Rode a validação para saber se a "
                "integração responde.",
                None,
            )

        contagem = validacao.contagem(key.value)
        quando = (
            f"{validacao.executed_at:%d/%m %H:%M}"
            if validacao.executed_at
            else "data desconhecida"
        )
        if not contagem:
            return (
                AvailabilityEnum.UNVERIFIED,
                f"Fora da última validação ({quando}); sem confirmação recente de que "
                "responde.",
                None,
            )

        sucesso = contagem.get(ScrapeStatusEnum.SUCCESS.value, 0)
        nao_achou = contagem.get(ScrapeStatusEnum.NOT_FOUND.value, 0)
        bloqueado = contagem.get(ScrapeStatusEnum.BLOCKED.value, 0)
        erro = contagem.get(ScrapeStatusEnum.ERROR.value, 0)

        if sucesso:
            resto = f" ({sucesso} com preço, {nao_achou} sem o produto)" if nao_achou else ""
            return (
                AvailabilityEnum.ONLINE,
                f"Consulta direta respondendo; verificada em {quando}{resto}.",
                contagem,
            )
        if nao_achou and not (erro or bloqueado):
            # A loja respondeu, só não tem os EANs de referência. A integração
            # está de pé — é diferente de não conseguirmos perguntar.
            return (
                AvailabilityEnum.ONLINE,
                f"Respondeu na validação de {quando}, sem os EANs de referência no "
                "catálogo. A integração está de pé.",
                contagem,
            )
        if bloqueado:
            motivo = validacao.motivos.get(key.value, "")
            return (
                AvailabilityEnum.FAILING,
                (
                    f"A rede recusou a consulta na validação de {quando} "
                    f"(HTTP 401/403/429). {motivo}"
                ).strip(),
                contagem,
            )
        motivo = validacao.motivos.get(key.value)
        return (
            AvailabilityEnum.FAILING,
            f"Não obteve preço na validação de {quando}"
            + (f": {motivo}" if motivo else "."),
            contagem,
        )

    # ------------------------------------------------------------------- painel

    def build(self) -> AvailabilityReport:
        validacao = self._ultima_validacao()
        restritas = ScraperValidationService.restricted_pharmacies
        linhas: list[PharmacyAvailability] = []

        for key, scraper_cls in ScraperRegistry._scrapers.items():
            captura: Optional[CaptureInfo] = None
            contagem: Optional[dict[str, int]] = None

            if key in restritas:
                situacao = AvailabilityEnum.RESTRICTED
                detalhe = (
                    "Coleta automatizada não autorizada pelos termos da rede. "
                    "Depende de API ou feed de preços oficial."
                )
            elif getattr(scraper_cls, "requires_capture", False):
                situacao, detalhe, captura = self._por_captura(key)
            else:
                situacao, detalhe, contagem = self._por_validacao(key, validacao)

            linhas.append(
                PharmacyAvailability(
                    key=key,
                    name=scraper_cls.name,
                    base_url=scraper_cls.base_url,
                    availability=situacao,
                    quotable=situacao in QUOTABLE,
                    detail=detalhe,
                    last_checked_at=validacao.executed_at if validacao else None,
                    last_statuses=contagem,
                    capture=captura,
                )
            )

        # Disponíveis primeiro: é a pergunta que o painel responde.
        linhas.sort(key=lambda linha: (not linha.quotable, linha.name))
        return AvailabilityReport(
            total=len(linhas),
            quotable=sum(1 for linha in linhas if linha.quotable),
            validated_at=validacao.executed_at if validacao else None,
            validation_report=validacao.path.name if validacao else None,
            pharmacies=linhas,
        )
