
import unittest
from modules.nlp import NLPProcessor

class TestNLPCategorization(unittest.TestCase):
    def setUp(self):
        self.nlp = NLPProcessor()

    def test_food_categorization(self):
        test_cases = [
            ("saya makan nasi ayam tadi 20rb", "Makanan"),
            ("bsy makan 15rb", "Makanan"),
            ("beli nasi goreng 25000", "Makanan"),
            ("mkn bakso 10k", "Makanan"),
            ("sarapan bubur ayam 12rb", "Makanan"),
            ("lunch di warteg 20rb", "Makanan"),
            ("dinner steak 150rb", "Makanan"),
            ("go food mcd 50rb", "Makanan"),
            ("beli ayam geprek 15rb", "Makanan"),
            ("nasi padang 25rb", "Makanan")
        ]
        for text, expected_cat in test_cases:
            data = self.nlp.extract_transaction_data(text)
            self.assertEqual(data.get("category"), expected_cat, f"Failed for text: {text}")

    def test_slang_normalization(self):
        test_cases = [
            ("mkn bakso", "makan bakso"),
            ("bsy nasi", "beli nasi"),
            ("bli ayam", "beli ayam"),
            ("td makan", "makan") # 'tadi' should be removed as noise
        ]
        for text, expected in test_cases:
            norm = self.nlp.normalize_text(text)
            # We check if keywords exist in normalized text
            for word in expected.split():
                self.assertIn(word, norm, f"Word '{word}' not found in normalized text: {norm}")

    def test_other_categories(self):
        test_cases = [
            ("isi bensin pertalite 50rb", "Transportasi"),
            ("bayar listrik pln 200rb", "Tagihan"),
            ("beli pulsa telkomsel 100rb", "Tagihan"),
            ("ojol ke kantor 15rb", "Transportasi"),
            ("beli baju di shopee 150rb", "Belanja")
        ]
        for text, expected_cat in test_cases:
            data = self.nlp.extract_transaction_data(text)
            self.assertEqual(data.get("category"), expected_cat, f"Failed for text: {text}")

if __name__ == "__main__":
    unittest.main()
