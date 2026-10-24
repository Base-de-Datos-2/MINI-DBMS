"""Versioned lexical preprocessing; no storage, ranking, or SQL dependencies."""

from unicodedata import normalize, unidata_version

from engine.errors import InvalidTypeError


def tokenizer_signature() -> dict[str, str]:
    """Return fresh JSON-compatible metadata for the exact tokenization rules.

    Persist both fields with an index and compare them before reuse. Python's
    Unicode database affects normalization, lowercasing, and isalnum(), so the
    algorithm identifier alone is insufficient across runtime upgrades.
    """
    return {
        "algorithm": "nfc-lower-nfc-alnum-v1",
        "unicode_version": unidata_version,
    }


def tokenize(text: str) -> tuple[str, ...]:
    """Return maximal Unicode alphanumeric runs, preserving order/repetition.

    Apply NFC, lowercase (not casefold), then NFC again. Every character for
    which str.isalnum() is false delimits tokens, including underscores and
    residual combining marks. Keep accents, numbers, and stopwords. The same
    function is intended for both document text and query text.
    """
    if not isinstance(text, str):
        raise InvalidTypeError("Text tokenization requires a string")

    normalized = normalize("NFC", normalize("NFC", text).lower())
    tokens: list[str] = []
    start = 0
    for position, character in enumerate(normalized):
        if not character.isalnum():
            if start < position:
                tokens.append(normalized[start:position])
            start = position + 1
    if start < len(normalized):
        tokens.append(normalized[start:])
    return tuple(tokens)
