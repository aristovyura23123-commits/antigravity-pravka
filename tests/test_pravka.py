import unittest
import sys
from pathlib import Path

scripts_dir = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

from unicode_check import scan_unicode, clean_unicode, CleanOptions
from protection import protected_spans, extract_atoms, validate_protected, fact_changes
from style import scan_style, light_edit


class TestUnicodeCheck(unittest.TestCase):
    def test_invisible_removal(self):
        text = "Привет\u200bмир\ufeff! Тест\u2060слова."
        cleaned = clean_unicode(text)
        self.assertEqual(cleaned, "Приветмир! Тестслова.")

    def test_mixed_script(self):
        # Cyrillic 'С' replaced with Latin 'C' in 'Сервис'
        text = "Cервис"  # first letter is Latin C
        findings = scan_unicode(text)
        mixed = [f for f in findings if f.code == "MIXED_SCRIPT"]
        self.assertEqual(len(mixed), 1)
        self.assertEqual(mixed[0].replacement, "Сервис")


class TestProtection(unittest.TestCase):
    def test_extract_atoms(self):
        text = "Крем 100 мл стоит 2 300 руб. Ссылка: [сайт](https://example.com). Код: `foo()`."
        atoms = extract_atoms(text)
        self.assertIn("100 мл", atoms)
        self.assertIn("2 300 руб", atoms)
        self.assertIn("[сайт](https://example.com)", atoms)
        self.assertIn("`foo()`", atoms)

    def test_validation_success(self):
        orig = "Цена 2 300 руб за 100 мл. Подробнее: https://aestetica.pro."
        draft = "Очищающий крем 100 мл доступен по цене 2 300 руб. Ссылка: https://aestetica.pro."
        # Should not raise
        validate_protected(orig, draft)

    def test_validation_failure_on_dropped_number(self):
        orig = "Цена 2 300 руб за 100 мл."
        draft = "Очищающий крем 100 мл доступен по выгодной цене."
        with self.assertRaises(ValueError):
            validate_protected(orig, draft)


class TestStyle(unittest.TestCase):
    def test_cliches(self):
        text = "Важно отметить, что компания осуществляет проверку документов."
        cleaned = light_edit(text)
        self.assertNotIn("Важно отметить, что", cleaned)
        self.assertIn("проводит проверку", cleaned)


if __name__ == "__main__":
    unittest.main()
