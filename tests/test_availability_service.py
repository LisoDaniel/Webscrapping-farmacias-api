"""Regressão do painel de disponibilidade.

O risco deste painel é afirmar "disponível" para uma rede que não está. Estar
cadastrada no registry não prova nada: a Araujo está registrada e não pode ser
consultada, a Panvel depende de captura que vence, e uma rede fora da última
validação simplesmente não foi verificada. Cada teste aqui trava uma dessas
distinções.
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from app.core.capture_store import CaptureStore
from app.models.product import PharmacyEnum
from app.services.availability_service import AvailabilityEnum, AvailabilityService

EAN = "7891058003555"
REDES_DIRETAS = [
    PharmacyEnum.PRECO_POPULAR,
    PharmacyEnum.SAO_JOAO,
    PharmacyEnum.DROGA_RAIA,
    PharmacyEnum.DROGASIL,
    PharmacyEnum.PAGUE_MENOS,
    PharmacyEnum.PACHECO,
    PharmacyEnum.DROGARIA_SAO_PAULO,
    PharmacyEnum.FARMA_CONDE,
]


def entrada(pharmacy: PharmacyEnum, status: str, price=None, error_message=None):
    return {
        "ean": EAN,
        "product_label": "Puran T4 12,5mcg",
        "pharmacy_key": pharmacy.value,
        "pharmacy_name": pharmacy.value,
        "status": status,
        "price": price,
        "product_name": "Puran T4",
        "product_url": None,
        "error_message": error_message,
    }


class AvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.raiz = Path(self.temp.name)
        self.reports = self.raiz / "reports"
        self.capturas = self.raiz / "capturas"
        self.reports.mkdir()
        self.capturas.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def _servico(self, max_age_hours: float = 24.0) -> AvailabilityService:
        # Diretórios temporários: apontar para reports/ e capturas/ da máquina
        # faria o teste passar pelo motivo errado.
        return AvailabilityService(
            capture_store=CaptureStore(directory=self.capturas, max_age_hours=max_age_hours),
            reports_dir=self.reports,
        )

    def _validacao(self, entradas, quando: datetime = None, nome: str = None):
        quando = quando or datetime.now()
        caminho = self.reports / (nome or f"scraper_validation_{quando:%Y%m%d_%H%M%S}.json")
        caminho.write_text(
            json.dumps(
                {"executed_at": quando.isoformat(), "entries": entradas},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return caminho

    def _captura(self, quando: datetime, uf: str = "SP", eans=(EAN,)):
        (self.capturas / "panvel.json").write_text(
            json.dumps(
                {
                    "pharmacy": "panvel",
                    "uf": uf,
                    "captured_at": quando.isoformat(),
                    "results": {ean: {"totalItems": 1, "items": []} for ean in eans},
                }
            ),
            encoding="utf-8",
        )

    def _linha(self, relatorio, pharmacy: PharmacyEnum):
        return next(item for item in relatorio.pharmacies if item.key == pharmacy)

    # --------------------------------------------------------------- validação

    def test_success_in_the_last_run_marks_the_network_quotable(self):
        self._validacao([entrada(PharmacyEnum.SAO_JOAO, "success", price=3.91)])
        linha = self._linha(self._servico().build(), PharmacyEnum.SAO_JOAO)
        self.assertEqual(linha.availability, AvailabilityEnum.ONLINE)
        self.assertTrue(linha.quotable)

    def test_not_found_alone_still_means_the_integration_answers(self):
        """A loja respondeu e não tem o item: a integração está de pé."""
        self._validacao([entrada(PharmacyEnum.FARMA_CONDE, "not_found")])
        linha = self._linha(self._servico().build(), PharmacyEnum.FARMA_CONDE)
        self.assertEqual(linha.availability, AvailabilityEnum.ONLINE)
        self.assertIn("sem os EANs de referência", linha.detail)

    def test_error_marks_the_network_as_failing_with_the_reason(self):
        self._validacao(
            [entrada(PharmacyEnum.DROGASIL, "error", error_message="Falha na comunicação")]
        )
        linha = self._linha(self._servico().build(), PharmacyEnum.DROGASIL)
        self.assertEqual(linha.availability, AvailabilityEnum.FAILING)
        self.assertFalse(linha.quotable)
        self.assertIn("Falha na comunicação", linha.detail)

    def test_blocked_is_reported_as_refusal_not_as_absence(self):
        self._validacao([entrada(PharmacyEnum.PACHECO, "blocked")])
        linha = self._linha(self._servico().build(), PharmacyEnum.PACHECO)
        self.assertEqual(linha.availability, AvailabilityEnum.FAILING)
        self.assertIn("recusou", linha.detail)

    def test_a_network_outside_the_last_run_is_unverified_not_available(self):
        self._validacao([entrada(PharmacyEnum.SAO_JOAO, "success", price=3.91)])
        linha = self._linha(self._servico().build(), PharmacyEnum.PAGUE_MENOS)
        self.assertEqual(linha.availability, AvailabilityEnum.UNVERIFIED)
        self.assertFalse(linha.quotable)

    def test_without_any_report_nothing_direct_is_marked_available(self):
        relatorio = self._servico().build()
        self.assertIsNone(relatorio.validated_at)
        for pharmacy in REDES_DIRETAS:
            with self.subTest(pharmacy=pharmacy):
                self.assertEqual(
                    self._linha(relatorio, pharmacy).availability,
                    AvailabilityEnum.UNVERIFIED,
                )

    def test_the_newest_report_wins(self):
        ontem = datetime.now() - timedelta(days=1)
        self._validacao([entrada(PharmacyEnum.SAO_JOAO, "error")], quando=ontem)
        self._validacao([entrada(PharmacyEnum.SAO_JOAO, "success", price=3.91)])
        linha = self._linha(self._servico().build(), PharmacyEnum.SAO_JOAO)
        self.assertEqual(linha.availability, AvailabilityEnum.ONLINE)

    def test_a_corrupt_report_falls_back_to_the_previous_one(self):
        ontem = datetime.now() - timedelta(days=1)
        self._validacao([entrada(PharmacyEnum.SAO_JOAO, "success", price=3.91)], quando=ontem)
        (self.reports / "scraper_validation_29991231_235959.json").write_text(
            "{ isso nao e json", encoding="utf-8"
        )
        linha = self._linha(self._servico().build(), PharmacyEnum.SAO_JOAO)
        self.assertEqual(linha.availability, AvailabilityEnum.ONLINE)

    # ----------------------------------------------------------------- captura

    def test_fresh_capture_makes_panvel_quotable_and_says_so(self):
        self._captura(datetime.now() - timedelta(hours=2), uf="RS", eans=(EAN, "7897595901033"))
        linha = self._linha(self._servico().build(), PharmacyEnum.PANVEL)
        self.assertEqual(linha.availability, AvailabilityEnum.CAPTURE_ONLY)
        self.assertTrue(linha.quotable)
        self.assertEqual(linha.capture.uf, "RS")
        self.assertEqual(linha.capture.eans, 2)
        self.assertFalse(linha.capture.expired)

    def test_expired_capture_asks_for_a_new_collection(self):
        self._captura(datetime.now() - timedelta(hours=30))
        linha = self._linha(self._servico().build(), PharmacyEnum.PANVEL)
        self.assertEqual(linha.availability, AvailabilityEnum.NEEDS_CAPTURE)
        self.assertFalse(linha.quotable)
        self.assertIn("tools/captura_panvel.js", linha.detail)
        self.assertTrue(linha.capture.expired)

    def test_missing_capture_is_not_confused_with_an_expired_one(self):
        linha = self._linha(self._servico().build(), PharmacyEnum.PANVEL)
        self.assertEqual(linha.availability, AvailabilityEnum.NEEDS_CAPTURE)
        self.assertIsNone(linha.capture)
        self.assertIn("não há captura", linha.detail)

    def test_a_successful_direct_run_does_not_override_the_capture_state(self):
        """Panvel responde por captura; relatório antigo não a torna disponível."""
        self._validacao([entrada(PharmacyEnum.PANVEL, "success", price=3.97)])
        linha = self._linha(self._servico().build(), PharmacyEnum.PANVEL)
        self.assertEqual(linha.availability, AvailabilityEnum.NEEDS_CAPTURE)

    def test_capture_without_a_timestamp_counts_as_expired(self):
        (self.capturas / "panvel.json").write_text(
            json.dumps({"pharmacy": "panvel", "results": {EAN: {"items": []}}}),
            encoding="utf-8",
        )
        linha = self._linha(self._servico().build(), PharmacyEnum.PANVEL)
        self.assertEqual(linha.availability, AvailabilityEnum.NEEDS_CAPTURE)

    # ---------------------------------------------------------------- política

    def test_araujo_is_restricted_regardless_of_any_report(self):
        self._validacao([entrada(PharmacyEnum.ARAUJO, "success", price=9.99)])
        linha = self._linha(self._servico().build(), PharmacyEnum.ARAUJO)
        self.assertEqual(linha.availability, AvailabilityEnum.RESTRICTED)
        self.assertFalse(linha.quotable)
        self.assertIn("não autorizada", linha.detail)

    # ------------------------------------------------------------------ painel

    def test_every_registered_network_appears_exactly_once(self):
        relatorio = self._servico().build()
        chaves = [linha.key for linha in relatorio.pharmacies]
        self.assertEqual(len(chaves), len(set(chaves)))
        self.assertEqual(relatorio.total, len(chaves))

    def test_quotable_count_matches_the_rows(self):
        self._validacao([entrada(pharmacy, "success", price=1.0) for pharmacy in REDES_DIRETAS])
        self._captura(datetime.now() - timedelta(minutes=10))
        relatorio = self._servico().build()
        self.assertEqual(relatorio.quotable, len(REDES_DIRETAS) + 1)
        self.assertEqual(
            relatorio.quotable,
            sum(1 for linha in relatorio.pharmacies if linha.quotable),
        )

    def test_available_networks_come_first(self):
        self._validacao([entrada(PharmacyEnum.SAO_JOAO, "success", price=3.91)])
        disponiveis = [linha.quotable for linha in self._servico().build().pharmacies]
        self.assertEqual(disponiveis, sorted(disponiveis, reverse=True))


if __name__ == "__main__":
    unittest.main()
