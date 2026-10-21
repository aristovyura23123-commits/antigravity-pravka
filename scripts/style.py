"""Style inspection, cliches detection, and rule-based light editing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from protection import overlaps, protected_spans
from unicode_check import Finding, find_pos, line_starts


@dataclass(frozen=True)
class StyleRule:
    code: str
    pattern: str
    explanation: str
    replacement: Optional[str] = None
    formal_ok: bool = False


STYLE_RULES = (
    StyleRule(
        "PARAGRAPH_OPENING",
        r"(?:^|(?<=[.!?\n])\s*)(?:одним\s+из|одной\s+из|важное\s+место|большой\s+вклад|значительный\s+вклад|важную\s+роль)\b",
        "Начните с самого предмета и его действия вместо абстрактной оценки важности.",
    ),
    StyleRule(
        "CONCLUSION_OPENING",
        r"(?:^|(?<=[.!?\n])\s*)(?:таким\s+образом|итак|в\s+целом|подводя\s+итог[и]?),\s*",
        "Если вывод логичен, начните прямо с тезиса без канцеляристской связки.",
    ),
    StyleRule(
        "INTRO",
        r"(?:^|(?<=[.!?\n])\s*)(?:необходимо|следует|стоит|важно)\s+(?:отметить|подчеркнуть|помнить),\s+что\s+",
        "Пустая вводная конструкция перед утверждением. Начните прямо с сути мысли.",
        "",
        True,
    ),
    StyleRule(
        "INTRO2",
        r"(?:^|(?<=[.!?\n])\s*)как\s+уже\s+было\s+сказано\s+выше,\s*",
        "Ссылка на ранее сказанное часто избыточна.",
        "",
        True,
    ),
    StyleRule(
        "CHECK",
        r"\bосуществляет\s+проверку\b",
        "Канцелярит: расщепленное сказуемое. Лучше «проверяет» или «проводит проверку».",
        "проводит проверку",
        True,
    ),
    StyleRule(
        "PROCESS",
        r"\bосуществляет\s+обработку\b",
        "Канцелярит: лучше использовать глагол «обрабатывает».",
        None,
        True,
    ),
    StyleRule(
        "INSTALL",
        r"\bосуществить\s+установку\b",
        "Канцелярит: лучше «установить».",
        None,
        True,
    ),
    StyleRule(
        "HELP",
        r"\bоказывает\s+помощь\b",
        "Канцелярит: лучше сказать прямо «помогает».",
        "помогает",
        True,
    ),
    StyleRule(
        "ANALYZE",
        r"\bпроизводит\s+анализ\b",
        "Канцелярит: лучше сказать «анализирует».",
        None,
        True,
    ),
    StyleRule(
        "NOW",
        r"\bна\s+данный\s+момент\s+времени\b",
        "Многословие: замените на «сейчас».",
        "сейчас",
        True,
    ),
    StyleRule(
        "IN_ORDER",
        r"\bдля\s+того,\s+чтобы\b",
        "Многословие: часто достаточно союза «чтобы».",
        "чтобы",
        True,
    ),
    StyleRule(
        "CAN",
        r"\bимеет\s+возможность\b(?=\s+[а-яё]+(?:ть|ти|чь)\b)",
        "Многословие: замените на «может».",
        "может",
        True,
    ),
    StyleRule(
        "WORLD",
        r"\bв\s+(?:современном|сегодняшнем)\s+(?:цифровом\s+)?мире\b",
        "Шаблонное клише: проверьте, несет ли эта фраза реальный смысл.",
    ),
    StyleRule(
        "INTEGRAL_PART",
        r"\bявляется\s+неотъемлемой\s+частью\b",
        "Заезженный штамп: назовите конкретную связь или функцию.",
    ),
    StyleRule(
        "KEY_ROLE",
        r"\bиграет\s+(?:ключевую|важнейшую|главную)\s+роль\b",
        "Штамп: опишите конкретное влияние или пользу действия.",
    ),
)


def scan_style(text: str, genre: str = "plain") -> list[Finding]:
    result: list[Finding] = []
    positions = line_starts(text)
    spans = protected_spans(text)

    for rule in STYLE_RULES:
        if genre in ("business", "academic") and rule.formal_ok and not rule.replacement:
            continue
        for match in re.finditer(rule.pattern, text, re.IGNORECASE):
            if overlaps(match.start(), match.end(), spans):
                continue
            replacement = rule.replacement
            end = match.end()
            raw = text[match.start() : end]

            # Adjust capitalization if deleting empty introductory clause
            if replacement == "":
                replacement = raw[: len(raw) - len(raw.lstrip())]
                if (
                    raw.lstrip()[:1].isupper()
                    and end < len(text)
                    and text[end] in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
                    and not overlaps(end, end + 1, spans)
                ):
                    replacement += text[end].upper()
                    end += 1

            line, col = find_pos(match.start(), positions)
            result.append(
                Finding(
                    start=match.start(),
                    end=end,
                    line=line,
                    column=col,
                    kind="style",
                    code=rule.code,
                    severity="suggestion",
                    message=rule.explanation,
                    replacement=replacement,
                    auto_fix=replacement is not None,
                )
            )

    # Long sentences check (>220 chars)
    for match in re.finditer(r"[^.!?\n]{220,}[.!?]?(?=\s|$)", text):
        if not overlaps(match.start(), match.end(), spans):
            line, col = find_pos(match.start(), positions)
            result.append(
                Finding(
                    start=match.start(),
                    end=match.end(),
                    line=line,
                    column=col,
                    kind="style",
                    code="LONG_SENTENCE",
                    severity="suggestion",
                    message="Длинное предложение (>220 симв.): проверьте, можно ли разделить мысли на 2–3 предложения.",
                )
            )

    return sorted(result, key=lambda item: item.start)


def light_edit(text: str, genre: str = "plain") -> str:
    """Applies safe rule-based replacements to eliminate common cliches and empty intros."""
    findings = [f for f in scan_style(text, genre) if f.auto_fix and f.replacement is not None]
    parts, previous = [], 0
    for item in sorted(findings, key=lambda item: item.start):
        if item.start >= previous:
            parts.extend((text[previous : item.start], item.replacement))
            previous = item.end
    parts.append(text[previous:])
    return "".join(parts)
