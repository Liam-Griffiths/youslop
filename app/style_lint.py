"""Offline narration heuristics, not grammatical or factual judgements.

Counts use Unicode words and sentence punctuation; phrase families are English.
An actual three-item fact list can legitimately trigger the advisory triplet rule.
"""
import re
from collections.abc import Iterable
from statistics import pstdev


# All numeric cutoffs live here. Spread needs enough sentences to be meaningful.
SHORT_WORDS = 5
RUN_SENTENCES = 2
TRIPLET_SENTENCES = 3
ITEM_WORDS = 4
SPREAD_SENTENCES = 4
MIN_SPREAD = 2.0
RHYTHM_SENTENCES = 4
SHORT_MEAN = 13
SHORT_SENTENCE = 12
SHORT_FRACTION = 0.6

_WORD = r"[^\W_]+(?:['’][^\W_]+)*"
_WORDS = re.compile(_WORD, re.UNICODE)
_ITEM = rf"{_WORD}(?:\s+{_WORD}){{0,{ITEM_WORDS - 1}}}"
_TRIPLET = re.compile(rf"\b{_ITEM},\s+{_ITEM},\s+and\s+{_ITEM}[.!?。！？\"”’']*$", re.I)
_PHRASES = tuple(re.compile(pattern, re.I) for pattern in (
    r"\b(?:little did \w+ know|\w+ had no idea|unbeknownst to \w+)\b",
    r"\b(?:only|just|merely) (?:the )?(?:beginning|start)\b",
    r"\b(?:what (?:happened|came) next|the best was yet to come|stay tuned)\b",
    r"\bhere(?:['’]s| is) (?:the thing|where (?:it|things) "
    r"(?:gets?|got) (?:interesting|exciting))\b",
    r"\b(?:the )?inside scoop\b",
    r"\b(?:spoiler(?: alert)?|buckle up|game[ -]changer|testament to)\b",
    r"\b(?:let['’]s|we['’]ll|we will) (?:dive|unpack|embark)\b",
))
# Teaser openers at the start of any sentence; "And then" only when it opens a paragraph.
_TEASER_TRANSITION = re.compile(
    r"^[\s\"'“‘]*(?:(?:stranger|weirder) still|even (?:stranger|weirder)(?: still)?"
    r"|but (?:that|this)(?:['’]s| is) not all)\b", re.I)
_PARAGRAPH_TEASER = re.compile(r"^[\s\"'“‘]*and then\b", re.I)


def sentences(text: str) -> list[str]:
    """Split without treating decimals, initials or common abbreviations as stops."""
    masked = list(text)
    for match in re.finditer(
            r"(?<=\d)\.(?=\d)|\b(?:Mr|Mrs|Ms|Dr|Prof|St|vs|etc)\."
            r"|\b(?:[A-Za-z]\.){2,}|\b[A-Z]\.(?=\s+[A-Z])", text):
        for i in range(match.start(), match.end()):
            if masked[i] == '.':
                masked[i] = '\0'
    boundary = re.compile(r"[.!?。！？]+[\"'”’)]*(?:\s+|$)")
    out, start = [], 0
    for match in boundary.finditer(''.join(masked)):
        part = text[start:match.end()].strip()
        if part:
            out.append(part)
        start = match.end()
    if text[start:].strip():
        out.append(text[start:].strip())
    return out


def lint(text: str) -> list[dict]:
    """Return sentence indices/text and reasons; runs never cross paragraphs.

    Indices are zero-based across the input. A run/paragraph hit is anchored at its
    first sentence and includes every affected index for a future targeted edit.
    """
    hits, offset = [], 0
    for paragraph in re.split(r"\n\s*\n", text):
        parts = sentences(paragraph)
        words = [_WORDS.findall(s) for s in parts]
        lengths = [len(w) for w in words]

        def hit(kind, index, reason, count=1):
            hits.append(dict(kind=kind, sentence_index=offset + index,
                             sentence_indices=list(range(offset + index, offset + index + count)),
                             sentence=parts[index], reason=reason))

        i = 0
        while i < len(parts):
            if not 0 < lengths[i] <= SHORT_WORDS:
                i += 1
                continue
            end = i + 1
            while end < len(parts) and 0 < lengths[end] <= SHORT_WORDS:
                end += 1
            if end - i >= RUN_SENTENCES:
                hit('fragment_run', i,
                    f'{end - i} consecutive sentences of {SHORT_WORDS} words or fewer.', end - i)
            i = end

        for i, sentence in enumerate(parts):
            if sentence.count(',') == 2 and _TRIPLET.search(sentence):
                hit('triplet', i, 'Three short items in an “X, Y, and Z” list.')
            group = words[i:i + TRIPLET_SENTENCES]
            if (len(group) == TRIPLET_SENTENCES
                    and all(0 < len(w) <= SHORT_WORDS for w in group)
                    and len({w[0].casefold() for w in group}) == 1):
                hit('parallel_triplet', i, 'Three short sentences with parallel openings.',
                    TRIPLET_SENTENCES)
            if (any(pattern.search(sentence) for pattern in _PHRASES)
                    or _TEASER_TRANSITION.search(sentence)
                    or (i == 0 and _PARAGRAPH_TEASER.search(sentence))):
                hit('teaser_hype', i, 'Teaser, foreshadowing or hype phrase.')
            if re.search(r'[!！]', sentence):
                hit('exclamation', i, 'Exclamation mark in narration.')
        if len(parts) >= SPREAD_SENTENCES and pstdev(lengths) < MIN_SPREAD:
            hit('low_spread', 0,
                f'Sentence-length spread is {pstdev(lengths):.2f} words '
                f'(below {MIN_SPREAD:g}); vary the rhythm.', len(parts))
        if len(parts) >= RHYTHM_SENTENCES:
            mean = sum(lengths) / len(parts)
            fraction = sum(n <= SHORT_SENTENCE for n in lengths) / len(parts)
            if mean < SHORT_MEAN or fraction >= SHORT_FRACTION:
                hit('short_rhythm', 0,
                    f'Short sentence rhythm: mean {mean:.1f} words; '
                    f'{fraction:.0%} of sentences have {SHORT_SENTENCE} words or fewer. '
                    'Vary the rhythm.', len(parts))
        offset += len(parts)
    return hits


def rate(texts: Iterable[str]) -> float:
    """Return lint hits per 100 sentences across narration texts, or 0 if empty.

    Texts are linted separately so paragraph rules never cross their boundaries.
    Each finding counts once, even when it covers several sentences; multiple
    rules may flag the same sentence, so the rate can exceed 100.
    """
    hits = count = 0
    for text in texts:
        hits += len(lint(text))
        count += sum(len(sentences(p)) for p in re.split(r"\n\s*\n", text))
    return 100.0 * hits / count if count else 0.0
