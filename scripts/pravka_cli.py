#!/usr/bin/env python3
"""Pravka CLI for Antigravity.

Offline Unicode cleaning, style inspection, invariant protection,
and verification for Russian texts.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from pathlib import Path

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent))

from protection import extract_atoms, fact_changes, validate_protected
from style import light_edit, scan_style
from unicode_check import CleanOptions, clean_unicode, scan_unicode


def read_input(target: str) -> str:
    if target == "-" or not target:
        return sys.stdin.read()
    p = Path(target)
    if not p.exists():
        # If it is direct text
        return target
    return p.read_text(encoding="utf-8")


def cmd_analyze(args):
    text = read_input(args.file)
    u_findings = scan_unicode(text)
    s_findings = scan_style(text, genre=args.genre)
    atoms = extract_atoms(text)

    if args.json:
        out = {
            "unicode_findings": [f.__dict__ for f in u_findings],
            "style_findings": [f.__dict__ for f in s_findings],
            "protected_atoms_count": len(atoms),
            "protected_atoms": atoms[:50],
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    print("=== АНАЛИЗ ТЕКСТА (Pravka) ===\n")
    print(f"Длина текста: {len(text)} символов")
    print(f"Защищённых инвариантов (числа, ссылки, код, цитаты): {len(atoms)}")

    print(f"\n[1] Проверка Unicode ({len(u_findings)} замечаний):")
    if not u_findings:
        print("  ✓ Скрытых, невидимых символов и омоглифов не обнаружено.")
    else:
        for f in u_findings:
            auto = " [исправляется автоматически]" if f.auto_fix else ""
            print(f"  • Стр {f.line}:{f.column} [{f.severity.upper()}] {f.code}: {f.message}{auto}")

    print(f"\n[2] Проверка стиля и канцелярита ({len(s_findings)} замечаний):")
    if not s_findings:
        print("  ✓ Грубых канцеляризмов и шаблонных подводок не обнаружено.")
    else:
        for f in s_findings:
            auto = f" -> замена на «{f.replacement}»" if f.replacement is not None else ""
            print(f"  • Стр {f.line}:{f.column} [{f.code}] {f.message}{auto}")

    print("\n[3] Образец защищённых данных:")
    sample = atoms[:8]
    if sample:
        for a in sample:
            print(f"  • {a!r}")
        if len(atoms) > 8:
            print(f"  ... и ещё {len(atoms) - 8} элементов.")
    else:
        print("  (нет чисел, ссылок или кода)")


def cmd_clean(args):
    text = read_input(args.file)
    opts = CleanOptions(
        spaces=args.spaces,
        confusables=args.confusables,
        nfc=not args.no_nfc,
    )
    cleaned = clean_unicode(text, opts)
    if args.style:
        cleaned = light_edit(cleaned, genre=args.genre)

    if args.output:
        Path(args.output).write_text(cleaned, encoding="utf-8")
        print(f"Очищенный текст сохранён в: {args.output}")
    else:
        sys.stdout.write(cleaned)


def cmd_protect(args):
    text = read_input(args.file)
    atoms = extract_atoms(text)
    print(f"Найдено {len(atoms)} защищённых элементов:")
    for i, a in enumerate(atoms, 1):
        print(f" {i:3d}. {a}")


def cmd_verify(args):
    orig = read_input(args.original)
    draft = read_input(args.draft)

    errors = []
    try:
        validate_protected(orig, draft)
    except ValueError as e:
        errors.append(str(e))

    warnings = fact_changes(orig, draft)

    print("=== ВЕРИФИКАЦИЯ РЕЗУЛЬТАТА РЕДАКТУРЫ ===")
    if errors:
        print("\n❌ КРИТИЧЕСКИЕ ОШИБКИ (Нарушены факты / инварианты):")
        for err in errors:
            print(f"  • {err}")
    else:
        print("\n✓ Все числа, единицы измерения, ссылки, код и цитаты сохранены без потерь.")

    if warnings:
        print("\n⚠️ ПРЕДУПРЕЖДЕНИЯ ДЛЯ ВЫЧИТКИ:")
        for w in warnings:
            print(f"  • {w}")
    else:
        print("✓ Оговорки и отрицания сохранены корректно.")

    if errors:
        sys.exit(1)


def cmd_diff(args):
    orig = read_input(args.original)
    draft = read_input(args.draft)

    print("=== СРАВНЕНИЕ ТЕКСТОВ ===\n")
    warnings = fact_changes(orig, draft)
    if warnings:
        print("Замечания по смыслу:")
        for w in warnings:
            print(f"  ⚠️ {w}")
        print()

    orig_lines = orig.splitlines(keepends=True)
    draft_lines = draft.splitlines(keepends=True)
    diff = difflib.unified_diff(orig_lines, draft_lines, fromfile="Исходник", tofile="Результат")
    sys.stdout.writelines(diff)


def main():
    parser = argparse.ArgumentParser(
        description="Pravka CLI для Antigravity — профессиональная редактура, защита инвариантов и очистка Unicode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    # analyze
    p_an = sub.add_parser("analyze", help="Анализ текста: Unicode, скрытые символы, стиль, инварианты")
    p_an.add_argument("file", help="Путь к файлу с текстом (или '-' для stdin)")
    p_an.add_argument("--genre", choices=["plain", "business", "academic", "post"], default="plain")
    p_an.add_argument("--json", action="store_true", help="Вывод в формате JSON")
    p_an.set_defaults(func=cmd_analyze)

    # clean
    p_cl = sub.add_parser("clean", help="Детерминированная очистка невидимых символов и канцелярита")
    p_cl.add_argument("file", help="Путь к файлу")
    p_cl.add_argument("-o", "--output", help="Куда сохранить результат (по умолчанию stdout)")
    p_cl.add_argument("--spaces", action="store_true", help="Нормализовать типографические пробелы")
    p_cl.add_argument("--confusables", action="store_true", help="Исправлять латинские омоглифы в русских словах")
    p_cl.add_argument("--no-nfc", action="store_true", help="Не применять нормализацию Unicode NFC")
    p_cl.add_argument("--style", action="store_true", help="Применить базовую очистку пустых подводок и клише")
    p_cl.add_argument("--genre", choices=["plain", "business", "academic", "post"], default="plain")
    p_cl.set_defaults(func=cmd_clean)

    # protect
    p_pr = sub.add_parser("protect", help="Показать все защищённые данные (числа, ссылки, код, цитаты)")
    p_pr.add_argument("file", help="Путь к файлу")
    p_pr.set_defaults(func=cmd_protect)

    # verify
    p_ve = sub.add_parser("verify", help="Сравнить оригинал и черновик на сохранность фактов и чисел")
    p_ve.add_argument("original", help="Файл с исходным текстом")
    p_ve.add_argument("draft", help="Файл с отредактированным текстом")
    p_ve.set_defaults(func=cmd_verify)

    # diff
    p_df = sub.add_parser("diff", help="Показать diff и проверить смысловые оговорки")
    p_df.add_argument("original", help="Исходный файл")
    p_df.add_argument("draft", help="Отредактированный файл")
    p_df.set_defaults(func=cmd_diff)

    parsed = parser.parse_args()
    parsed.func(parsed)


if __name__ == "__main__":
    main()
