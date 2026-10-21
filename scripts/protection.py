"""Data protection and invariant validation.

Protects numbers with units, dates, code blocks, Markdown links, URLs,
quotations, and custom terms from accidental deletion, modification, or hallucination.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections import Counter
from typing import Iterator, Tuple

CODE = re.compile(r"(?<!`)(`{1,3})(?!`)([^\n]{1,4096}?)(?<!`)\1(?!`)")
LINK = re.compile(r"!?\[[^\]\n]{0,1024}\]\((?:[^()\n]|\([^()\n]{0,1024}\)){0,8192}\)")
URL = re.compile(
    r"(?i:https?://)[^\s<>\"«»]+|(?<![\w.+-])[\w.+-]{1,64}@[\w.-]{1,253}\.[A-Za-z]{2,63}\b"
)
NUMBER = re.compile(
    r"(?<!\w)[+−-]?(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)"
    r"(?:[.,:/−-]\d+)*"
    r"(?:[ \t\u00a0\u202f]*(?:млрд\.?|млн\.?|тыс\.?|миллион\w*|миллиард\w*|тысяч\w*)(?!\w))?"
    r"(?:[ \t\u00a0\u202f]*(?:₽|%|руб(?:лей|ля|ль|лях)?\.?|процент\w*|секунд\w*|минут\w*|"
    r"час(?:ов|а)?|дн(?:ей|я)|дней|год(?:а|ов)?|лет|км|кг|мг|мл|ГБ|МБ|ТБ|°[CС])(?!\w))?",
    re.IGNORECASE,
)
QUALIFIERS = re.compile(
    r"\b(?:обычно|примерно|возможно|иногда|вероятно|может|могут|часто|редко|"
    r"всегда|никогда|во многом|прежде всего|в основном)\b",
    re.I,
)


def qualification_changes(before: str, after: str) -> list[dict]:
    old = Counter(m.group().casefold() for m in QUALIFIERS.finditer(before))
    new = Counter(m.group().casefold() for m in QUALIFIERS.finditer(after))
    return [
        {"phrase": phrase, "source_count": old[phrase], "draft_count": new[phrase]}
        for phrase in sorted(old.keys() | new.keys())
        if old[phrase] != new[phrase]
    ]


def url_spans(text: str) -> Iterator[Tuple[int, int]]:
    """Bare links follow prose punctuation; Markdown links protect it all."""
    for match in URL.finditer(text):
        end = match.end()
        if "://" in match.group():
            while end > match.start():
                value = text[match.start() : end]
                if value[-1] in ".,;!?" or (
                    value[-1] == ")" and value.count(")") > value.count("(")
                ):
                    end -= 1
                else:
                    break
        yield match.start(), end


def merge(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if result and start < result[-1][1]:
            result[-1] = (result[-1][0], max(end, result[-1][1]))
        else:
            result.append((start, end))
    return result


def quote_spans(text: str) -> list[tuple[int, int]]:
    pairs = {"«": "»", "“": "”", '"': '"'}
    spans, start, closing, escaped = [], None, "", False
    for index, char in enumerate(text):
        if start is None:
            if char in pairs:
                start, closing = index, pairs[char]
        else:
            if char == closing and not (closing == '"' and escaped):
                spans.append((start, index + 1))
                start, closing = None, ""
            escaped = char == "\\" and not escaped
    if start is not None:
        spans.append((start, len(text)))
    return spans


def protected_spans(
    text: str, *, numbers: bool = False, terms: tuple[str, ...] = ()
) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    fence_start = None
    fence_char, fence_size = "", 0
    offset = 0

    for line in text.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\r\n"))
        if marker:
            token, tail = marker.groups()
            if fence_start is None:
                fence_start, fence_char, fence_size = offset, token[0], len(token)
            elif token[0] == fence_char and len(token) >= fence_size and not tail.strip():
                spans.append((fence_start, offset + len(line)))
                fence_start = None
        if fence_start is None and line.lstrip().startswith(">"):
            spans.append((offset, offset + len(line)))
        offset += len(line)

    if fence_start is not None:
        spans.append((fence_start, len(text)))

    spans.extend(quote_spans(text))
    for pattern in (CODE, LINK):
        spans.extend((m.start(), m.end()) for m in pattern.finditer(text))
    spans.extend(url_spans(text))

    if numbers:
        spans.extend((m.start(), m.end()) for m in NUMBER.finditer(text))

    for term in terms:
        if term and term.strip():
            pattern = re.compile(r"(?<!\w)" + re.escape(term.strip()) + r"(?!\w)", re.I)
            spans.extend((m.start(), m.end()) for m in pattern.finditer(text))

    return merge(spans)


def overlaps(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    index = bisect_right(spans, (start, float("inf")))
    return (index > 0 and spans[index - 1][1] > start) or (
        index < len(spans) and spans[index][0] < end
    )


def normalize_atom(s: str) -> str:
    s = s.strip()
    # Normalize trailing dot in abbreviations like руб., тыс., млн.
    for abbr in ("руб.", "тыс.", "млн.", "млрд."):
        if s.lower().endswith(abbr):
            s = s[:-1]
    return s.rstrip(".,;:!?")


def extract_atoms(text: str, terms: tuple[str, ...] = ()) -> list[str]:
    """Returns a list of all protected text fragments."""
    spans = protected_spans(text, numbers=True, terms=terms)
    return [normalize_atom(text[start:end]) for start, end in spans]


def validate_protected(original: str, draft: str, terms: tuple[str, ...] = ()) -> None:
    """Validate rewritten text without dropping, altering, or hallucinating invariants."""
    orig_nums = Counter(normalize_atom(m.group()) for m in NUMBER.finditer(original))
    draft_nums = Counter(normalize_atom(m.group()) for m in NUMBER.finditer(draft))
    if orig_nums != draft_nums:
        diff = []
        for n, count in orig_nums.items():
            if draft_nums[n] != count:
                diff.append(f"было: {n} (x{count}), стало: x{draft_nums[n]}")
        for n, count in draft_nums.items():
            if n not in orig_nums:
                diff.append(f"добавлено новое число: {n}")
        raise ValueError("Числа или единицы измерения изменены/утеряны: " + "; ".join(diff))

    orig_atoms = Counter(extract_atoms(original, terms=terms))
    draft_atoms = Counter(extract_atoms(draft, terms=terms))
    if orig_atoms != draft_atoms:
        diff = []
        for a, count in orig_atoms.items():
            if draft_atoms[a] != count:
                diff.append(f"утеряно/изменено: {a!r}")
        for a, count in draft_atoms.items():
            if a not in orig_atoms:
                diff.append(f"добавлено: {a!r}")
        raise ValueError("Защищённые фрагменты изменены: " + "; ".join(diff[:5]))


def fact_changes(before: str, after: str) -> list[str]:
    """Inspects changes in numbers, links, qualifications, and negations."""
    warnings = []
    before_nums = Counter(m.group().strip() for m in NUMBER.finditer(before))
    after_nums = Counter(m.group().strip() for m in NUMBER.finditer(after))
    if before_nums != after_nums:
        warnings.append("Числа или единицы измерения изменились — требуется проверка.")

    before_urls = Counter(before[s:e] for s, e in url_spans(before))
    after_urls = Counter(after[s:e] for s, e in url_spans(after))
    if before_urls != after_urls:
        warnings.append("Ссылки или email-адреса изменились.")

    qual_diffs = qualification_changes(before, after)
    if qual_diffs:
        phrases = ", ".join(f"«{d['phrase']}»" for d in qual_diffs[:4])
        warnings.append(f"Изменились оговорки степени уверенности ({phrases}).")

    negative = re.compile(r"\b(?:не|нет|ни|без|невозможно|нельзя)\b", re.I)
    before_neg = Counter(m.group().lower() for m in negative.finditer(before))
    after_neg = Counter(m.group().lower() for m in negative.finditer(after))
    if before_neg != after_neg:
        warnings.append("Изменились отрицания (не/нет/ни/нельзя) — проверьте сохранение смысла.")

    return warnings
