"""Person names (ADR-0004 §1): spaCy PER entities, plus names right after cue phrases.

- An entity counts only if it contains a proper noun, so a sentence-initial verb such as
  "Depositale" that the recogniser takes for a person is not erased (it is a scam signal).
- Cue phrases ("soy X", "Hola X", "Felicidades X") catch the single first names the recogniser
  misses most often, the classic "relative in trouble" opening among them.
- Official brands from config/official_domains.yaml and config/modalities.yaml always survive.

The recall floor is fixed in an amendment to ADR-0004, measured on
evals/redaction/names_validation.jsonl, a set never used for tuning.
"""

import re
import unicodedata
from collections.abc import Iterable
from typing import Protocol

from esfake.pipeline.redaction.deterministic import NAME_PATTERN

_PLACEHOLDER = re.compile(r"\[[A-Z_]+\]")
_HAS_LETTER = re.compile(r"[^\W\d_]")
_EDGE_FILLER = re.compile(r"^[\W_]+|[\W_]+$")
# Particles left over when a brand is cut out of an entity ("Rosa del BCP" -> "Rosa del").
_TRAILING_PARTICLES = re.compile(r"(?:\s+(?:de|del|la|los|y))+$", re.IGNORECASE)

# Only the cue ignores case; the name after it must be capitalised.
_CUED_NAME = re.compile(
    r"(?i:\b(?:soy|hola|hey|oye|felicidades|feliz cumpleaños|querid[oa]|estimad[oa]|"
    r"mi nombre es|me llamo|habla|te saluda|le saluda|te escribe|le escribe|gracias|"
    r"señor(?:a|ita)?|sr\.|sra\.|srta\.|dr\.|dra\.|ing\.|lic\.)[\s,]+)"
    rf"({NAME_PATTERN})"
)
# Capitalised words that follow those cues without being names ("Hola Mamá", "Gracias Dios").
_NOT_NAMES = frozenset(
    {
        "mama", "papa", "mami", "papi", "tia", "tio", "abuela", "abuelita", "abuelo",
        "abuelito", "hijo", "hija", "amigo", "amiga", "amor", "senor", "senora", "senorita",
        "cliente", "usuario", "usuaria", "estimado", "estimada", "dios", "todos", "todas",
        "equipo", "familia", "vecino", "vecina", "jefe", "doctor", "doctora",
    }
)  # fmt: skip

type Span = tuple[int, int]


class NameFinder(Protocol):
    def find(self, text: str) -> list[Span]: ...


def fold(text: str) -> str:
    """Lower-case and strip accents character by character, so offsets stay aligned."""
    return "".join(unicodedata.normalize("NFD", char)[0].lower() for char in text)


def _subtract(span: Span, holes: Iterable[Span]) -> list[Span]:
    pieces = [span]
    for hole_start, hole_end in holes:
        next_pieces = []
        for start, end in pieces:
            if hole_end <= start or hole_start >= end:
                next_pieces.append((start, end))
                continue
            if start < hole_start:
                next_pieces.append((start, hole_start))
            if hole_end < end:
                next_pieces.append((hole_end, end))
        pieces = next_pieces
    return pieces


def _trimmed(text: str, span: Span) -> Span | None:
    start, end = span
    piece = text[start:end]
    trimmed = _TRAILING_PARTICLES.sub("", _EDGE_FILLER.sub("", piece))
    if not _HAS_LETTER.search(trimmed):
        return None
    offset = start + piece.index(trimmed)
    return offset, offset + len(trimmed)


def cued_name_spans(text: str) -> list[Span]:
    """Capitalised names right after a cue phrase, skipping kinship and generic words."""
    spans: list[Span] = []
    for match in _CUED_NAME.finditer(text):
        start, end = match.span(1)
        for word in re.finditer(r"\S+", text[start:end]):
            if fold(word.group()).strip(".,!?") not in _NOT_NAMES:
                spans.append((start + word.start(), end))
                break
    return spans


class SpacyNameFinder:
    def __init__(self, model: str, exempt: Iterable[str], *, cues: bool = True) -> None:
        import spacy  # imported here so deterministic-only redaction never loads spaCy

        # Tokens, part-of-speech tags and entities only: the stage budget is 150 ms.
        self._nlp = spacy.load(model, enable=["tok2vec", "morphologizer", "ner"])
        terms = sorted({fold(term) for term in exempt}, key=len, reverse=True)
        self._exempt = re.compile(r"\b(?:" + "|".join(map(re.escape, terms)) + r")\b")
        self._cues = cues

    def find(self, text: str) -> list[Span]:
        holes = [match.span() for match in self._exempt.finditer(fold(text))]
        holes += [match.span() for match in _PLACEHOLDER.finditer(text)]
        doc = self._nlp(text)
        spans: list[Span] = []
        for entity in doc.ents:
            if entity.label_ != "PER":
                continue
            for start, end in _subtract((entity.start_char, entity.end_char), holes):
                tokens = doc.char_span(start, end, alignment_mode="expand") or ()
                if not any(token.pos_ == "PROPN" for token in tokens):
                    continue
                if (span := _trimmed(text, (start, end))) is not None:
                    spans.append(span)
        if self._cues:
            for cued in cued_name_spans(text):
                for piece in _subtract(cued, holes):
                    if (span := _trimmed(text, piece)) is not None:
                        spans.append(span)
        return spans
