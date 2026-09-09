"""Regressão do retry das consultas.

A regra é distinguir falha técnica de resposta da loja. Uma queda de rede pode
ser repetida; um "não temos esse produto" e um "pare de consultar" não. Repetir
o primeiro só gasta tempo, e repetir o segundo é insistir com quem acabou de
pedir para parar.
"""

import unittest

from app.models.product import PharmacyEnum, PriceQuote, ScrapeStatusEnum
from app.services.scraper_service import ScraperService


class ScraperFalso:
    """Devolve as cotações programadas, uma por tentativa."""

    name = "Farmácia de Teste"

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = 0

    def configure_location(self, **_):
        return self

    async def search(self, ean=None, term=None):
        self.chamadas += 1
        resposta = self.respostas[min(self.chamadas - 1, len(self.respostas) - 1)]
        if isinstance(resposta, Exception):
            raise resposta
        return resposta


def cotacao(status, price=None, error_message=None):
    return PriceQuote(
        pharmacy_key=PharmacyEnum.PANVEL,
        pharmacy_name="Farmácia de Teste",
        price=price,
        status=status,
        error_message=error_message,
    )


class RetryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.service = ScraperService()
        self.service.retry_attempts = 3
        self.esperas = []

        async def registrar(segundos):
            self.esperas.append(segundos)

        self.service._dormir = registrar

    async def _executar(self, respostas):
        scraper = ScraperFalso(respostas)
        resultado = await self.service._buscar_com_retry(
            scraper, PharmacyEnum.PANVEL, "7891058003555", None
        )
        return scraper, resultado

    async def test_transient_error_is_retried_until_it_works(self):
        scraper, resultado = await self._executar(
            [
                cotacao(ScrapeStatusEnum.ERROR, error_message="timeout"),
                cotacao(ScrapeStatusEnum.SUCCESS, price=3.97),
            ]
        )
        self.assertEqual(resultado.status, ScrapeStatusEnum.SUCCESS)
        self.assertEqual(resultado.price, 3.97)
        self.assertEqual(scraper.chamadas, 2)
        self.assertEqual(len(self.esperas), 1)

    async def test_not_found_is_not_retried(self):
        """É resposta da loja, não falha técnica: repetir não muda nada."""
        scraper, resultado = await self._executar([cotacao(ScrapeStatusEnum.NOT_FOUND)])
        self.assertEqual(resultado.status, ScrapeStatusEnum.NOT_FOUND)
        self.assertEqual(scraper.chamadas, 1)
        self.assertEqual(self.esperas, [])

    async def test_blocked_is_not_retried(self):
        """A loja pediu para parar; insistir seria martelar."""
        scraper, resultado = await self._executar([cotacao(ScrapeStatusEnum.BLOCKED)])
        self.assertEqual(resultado.status, ScrapeStatusEnum.BLOCKED)
        self.assertEqual(scraper.chamadas, 1)
        self.assertEqual(self.esperas, [])

    async def test_gives_up_after_the_configured_attempts(self):
        scraper, resultado = await self._executar(
            [cotacao(ScrapeStatusEnum.ERROR, error_message="rede fora")]
        )
        self.assertEqual(resultado.status, ScrapeStatusEnum.ERROR)
        self.assertEqual(resultado.error_message, "rede fora")
        self.assertEqual(scraper.chamadas, 3)
        # Espera entre as tentativas, não depois da última.
        self.assertEqual(len(self.esperas), 2)

    async def test_exception_becomes_an_error_quote_and_is_retried(self):
        scraper, resultado = await self._executar(
            [RuntimeError("conexão caiu"), cotacao(ScrapeStatusEnum.SUCCESS, price=1.0)]
        )
        self.assertEqual(resultado.status, ScrapeStatusEnum.SUCCESS)
        self.assertEqual(scraper.chamadas, 2)

    async def test_exception_on_every_attempt_reports_the_cause(self):
        _, resultado = await self._executar([RuntimeError("conexão caiu")])
        self.assertEqual(resultado.status, ScrapeStatusEnum.ERROR)
        self.assertIn("conexão caiu", resultado.error_message)
        self.assertEqual(resultado.ean, "7891058003555")

    async def test_a_single_attempt_disables_retry(self):
        self.service.retry_attempts = 1
        scraper, resultado = await self._executar([cotacao(ScrapeStatusEnum.ERROR)])
        self.assertEqual(scraper.chamadas, 1)
        self.assertEqual(self.esperas, [])
        self.assertEqual(resultado.status, ScrapeStatusEnum.ERROR)


class BackoffTests(unittest.TestCase):
    def setUp(self):
        self.service = ScraperService()
        self.service.retry_base_delay = 0.5
        self.service.retry_max_delay = 4.0

    def test_delay_grows_between_attempts(self):
        atrasos = [self.service._atraso(i) for i in (1, 2, 3)]
        self.assertLess(atrasos[0], atrasos[1])
        self.assertLess(atrasos[1], atrasos[2])

    def test_delay_respects_the_ceiling(self):
        """Mesmo com muitas tentativas a espera não cresce sem limite."""
        for tentativa in range(1, 12):
            with self.subTest(tentativa=tentativa):
                self.assertLessEqual(
                    self.service._atraso(tentativa),
                    self.service.retry_max_delay + self.service.retry_base_delay,
                )

    def test_delay_has_jitter(self):
        """Sem folga, as farmácias em paralelo repetiriam todas no mesmo instante."""
        amostras = {round(self.service._atraso(1), 6) for _ in range(20)}
        self.assertGreater(len(amostras), 1)

    def test_attempts_never_drop_below_one(self):
        self.service.retry_attempts = max(1, 0)
        self.assertGreaterEqual(self.service.retry_attempts, 1)


if __name__ == "__main__":
    unittest.main()
