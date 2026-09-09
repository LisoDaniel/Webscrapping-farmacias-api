"""Regressão da leitura de colunas das planilhas de clientes.

Os clientes não usam o mesmo layout. Quatro das cinco planilhas trazem
laboratório e grupo em C e D; a do MATHEUS insere PMC e preço líquido antes,
empurrando as duas para E e F. Com posições fixas, o relatório do MATHEUS saía
com números nas colunas de laboratório e grupo.
"""

import tempfile
import unittest
from pathlib import Path

import openpyxl

from app.core.config import settings
from app.services.excel_service import ExcelService

LAYOUT_SIMPLES = ["CÓD. BARRAS/EAN", "PRODUTO", "FABRICANTE/LABORATÓRIO", "GRUPO"]
LAYOUT_COM_PRECOS = [
    "CÓD. BARRAS/EAN",
    "PRODUTO",
    "PMC (MEDICAMENTOS)",
    "PREÇO LÍQ. CLIENTE (MÉDIA 90 DIAS)",
    "FABRICANTE/LABORATÓRIO",
    "GRUPO",
]


class ExcelColumnTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.raiz = Path(self.temp.name)
        self._clientes_original = settings.CLIENTS_DIR
        settings.CLIENTS_DIR = self.raiz

    def tearDown(self):
        settings.CLIENTS_DIR = self._clientes_original
        self.temp.cleanup()

    def _planilha(self, nome: str, cabecalho, linhas, metadados=()):
        pasta = self.raiz / nome
        pasta.mkdir(parents=True, exist_ok=True)
        wb = openpyxl.Workbook()
        sheet = wb.active
        if cabecalho:
            sheet.append(cabecalho)
        for linha in linhas:
            sheet.append(linha)
        for posicao, valor in metadados:
            sheet[posicao] = valor
        wb.save(pasta / f"{nome}.xlsx")
        return nome

    def test_simple_layout_reads_lab_and_group_from_c_and_d(self):
        pasta = self._planilha(
            "CLIENTE SIMPLES",
            LAYOUT_SIMPLES,
            [["7891058003555", "PURAN T4 12,5MCG", "SANOFI", "REFERÊNCIA"]],
        )
        _, produtos = ExcelService.parse_client_products(pasta)
        produto = produtos[0]
        self.assertEqual(produto.laboratory, "SANOFI")
        self.assertEqual(produto.group, "REFERÊNCIA")
        self.assertIsNone(produto.client_pmc)
        self.assertIsNone(produto.client_net_price)

    def test_price_layout_shifts_lab_and_group_to_e_and_f(self):
        """O caso do MATHEUS: PMC e preço antes de laboratório e grupo."""
        pasta = self._planilha(
            "CLIENTE COM PRECOS",
            LAYOUT_COM_PRECOS,
            [["3400970002146", "FLEBODIA 600MG", 180.53, 157.48, "GROSS", "REFERÊNCIA"]],
        )
        _, produtos = ExcelService.parse_client_products(pasta)
        produto = produtos[0]
        self.assertEqual(produto.laboratory, "GROSS")
        self.assertEqual(produto.group, "REFERÊNCIA")
        self.assertEqual(produto.client_pmc, 180.53)
        self.assertEqual(produto.client_net_price, 157.48)

    def test_numbers_never_land_in_the_text_columns(self):
        """O sintoma original: laboratório e grupo preenchidos com valores."""
        pasta = self._planilha(
            "CLIENTE NUMEROS",
            LAYOUT_COM_PRECOS,
            [["42360407", "CR FACIAL NIVEA", None, 29.99, "BEIERSDORF", "PERFUMARIA"]],
        )
        _, produtos = ExcelService.parse_client_products(pasta)
        produto = produtos[0]
        self.assertEqual(produto.laboratory, "BEIERSDORF")
        self.assertEqual(produto.group, "PERFUMARIA")
        for campo in (produto.laboratory, produto.group):
            self.assertFalse(campo.replace(".", "").isdigit(), f"{campo} parece um número")

    def test_missing_price_columns_leave_the_fields_empty(self):
        pasta = self._planilha(
            "CLIENTE SEM PRECO",
            LAYOUT_SIMPLES,
            [["7891058003555", "PURAN T4", "SANOFI", "REFERÊNCIA"]],
        )
        _, produtos = ExcelService.parse_client_products(pasta)
        self.assertIsNone(produtos[0].client_net_price)

    def test_falls_back_to_fixed_positions_without_a_header(self):
        """Planilha sem cabeçalho reconhecível não pode virar erro."""
        pasta = self._planilha(
            "CLIENTE SEM CABECALHO",
            None,
            [["7891058003555", "PURAN T4", "SANOFI", "REFERÊNCIA"]],
        )
        _, produtos = ExcelService.parse_client_products(pasta)
        self.assertEqual(produtos[0].laboratory, "SANOFI")
        self.assertEqual(produtos[0].group, "REFERÊNCIA")

    def test_empty_cells_become_none_not_empty_strings(self):
        pasta = self._planilha(
            "CLIENTE VAZIO",
            LAYOUT_SIMPLES,
            [["7891058003555", "PURAN T4", None, None]],
        )
        _, produtos = ExcelService.parse_client_products(pasta)
        self.assertIsNone(produtos[0].laboratory)
        self.assertIsNone(produtos[0].group)

    def test_metadata_is_still_read_alongside_the_columns(self):
        pasta = self._planilha(
            "CLIENTE META",
            LAYOUT_SIMPLES,
            [["7891058003555", "PURAN T4", "SANOFI", "REFERÊNCIA"]],
            metadados=[("F3", "CIDADE: VENÂNCIO AIRES"), ("F4", "ESTADO: RIO GRANDE DO SUL")],
        )
        info, _ = ExcelService.parse_client_products(pasta)
        self.assertEqual(info.city, "VENÂNCIO AIRES")
        self.assertEqual(info.state, "RS")


if __name__ == "__main__":
    unittest.main()
