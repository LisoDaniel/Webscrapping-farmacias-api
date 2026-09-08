import unittest

from app.core.locations import normalize_state


class NormalizeStateTests(unittest.TestCase):
    def test_full_name_becomes_uf(self):
        """A planilha da CARIN traz "RIO GRANDE DO SUL" por extenso."""
        self.assertEqual(normalize_state("RIO GRANDE DO SUL"), "RS")
        self.assertEqual(normalize_state("São Paulo"), "SP")
        self.assertEqual(normalize_state("Distrito Federal"), "DF")

    def test_accents_and_casing_do_not_matter(self):
        for raw in ("goias", "GOIÁS", "Goiás", "  goiás  "):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_state(raw), "GO")

    def test_extra_whitespace_between_words(self):
        self.assertEqual(normalize_state("MATO  GROSSO   DO SUL"), "MS")

    def test_existing_uf_is_preserved(self):
        self.assertEqual(normalize_state("RS"), "RS")
        self.assertEqual(normalize_state("rs"), "RS")

    def test_unknown_value_becomes_none(self):
        """Melhor não ter estado do que propagar texto que ninguém interpreta."""
        self.assertIsNone(normalize_state("XX"))
        self.assertIsNone(normalize_state("Venâncio Aires"))
        self.assertIsNone(normalize_state(""))
        self.assertIsNone(normalize_state(None))

    def test_every_brazilian_state_is_mapped(self):
        self.assertEqual(
            len({normalize_state(name) for name in _ALL_STATE_NAMES}),
            27,
        )


_ALL_STATE_NAMES = [
    "Acre", "Alagoas", "Amapá", "Amazonas", "Bahia", "Ceará", "Distrito Federal",
    "Espírito Santo", "Goiás", "Maranhão", "Mato Grosso", "Mato Grosso do Sul",
    "Minas Gerais", "Pará", "Paraíba", "Paraná", "Pernambuco", "Piauí",
    "Rio de Janeiro", "Rio Grande do Norte", "Rio Grande do Sul", "Rondônia",
    "Roraima", "Santa Catarina", "São Paulo", "Sergipe", "Tocantins",
]


if __name__ == "__main__":
    unittest.main()
