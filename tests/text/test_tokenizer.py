"""Exact lexical expectations shared by future document/query consumers."""

import json
import unicodedata

import pytest

from engine.errors import InvalidTypeError
from engine.text import tokenize, tokenizer_signature


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", ()),
        (" \t\n\r\u00a0", ()),
        ("... ¿?! — _ 👋", ()),
        ("Base DE datos", ("base", "de", "datos")),
        ("¡ÁRBOL, NIÑO, pingüino!", ("árbol", "niño", "pingüino")),
        ("cafe\u0301 nin\u0303o", ("café", "niño")),
        ("á a", ("á", "a")),
        ("base base BASE", ("base", "base", "base")),
        ("el de y la", ("el", "de", "y", "la")),
        ("machine-learning/base_datos", ("machine", "learning", "base", "datos")),
        ("don't l'amour", ("don", "t", "l", "amour")),
        ("2026 3.14 -42 A1", ("2026", "3", "14", "42", "a1")),
        ("１２ ٣ ²", ("１２", "٣", "²")),
        ("中文 東京", ("中文", "東京")),
        ("Straße STRASSE", ("straße", "strasse")),
        ("ﬀ ff", ("ﬀ", "ff")),
        ("İSTANBUL", ("i", "stanbul")),
        ("x\u0301y", ("x", "y")),
        ("a\x00b", ("a", "b")),
        ("fin", ("fin",)),
    ],
)
def test_exact_tokens(text, expected, no_file_io):
    with no_file_io():
        assert tokenize(text) == expected


@pytest.mark.parametrize("text", ["CAFÉ", "NIÑO", "PINGÜINO", "ÅNGSTRÖM", "École"])
def test_canonically_equivalent_inputs_have_identical_tokens(text):
    assert tokenize(text) == tokenize(unicodedata.normalize("NFD", text))


@pytest.mark.parametrize("text", [None, 42, True, b"text", ["text"], {"text": "a"}])
def test_invalid_inputs_are_not_implicitly_converted(text):
    with pytest.raises(InvalidTypeError, match="requires a string"):
        tokenize(text)


def test_signature_is_serializable_versioned_and_independent(no_file_io):
    with no_file_io():
        signature = tokenizer_signature()
        assert signature == {
            "algorithm": "nfc-lower-nfc-alnum-v1",
            "unicode_version": unicodedata.unidata_version,
        }
        assert json.loads(json.dumps(signature)) == signature
        signature["algorithm"] = "changed by a caller"
        assert tokenizer_signature()["algorithm"] == "nfc-lower-nfc-alnum-v1"
