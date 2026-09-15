"""Task 7.4: tokenizer coverage."""

import pytest

from engine.query.lexer import SqlSyntaxError, TokenType, tokenize


def test_tokenizes_a_simple_select():
    tokens = tokenize("SELECT id, name FROM students WHERE age >= 18;")
    kinds = [(t.type, t.value) for t in tokens]
    assert kinds == [
        (TokenType.KEYWORD, "SELECT"),
        (TokenType.IDENTIFIER, "id"),
        (TokenType.PUNCTUATION, ","),
        (TokenType.IDENTIFIER, "name"),
        (TokenType.KEYWORD, "FROM"),
        (TokenType.IDENTIFIER, "students"),
        (TokenType.KEYWORD, "WHERE"),
        (TokenType.IDENTIFIER, "age"),
        (TokenType.PUNCTUATION, ">="),
        (TokenType.INTEGER, "18"),
        (TokenType.PUNCTUATION, ";"),
        (TokenType.EOF, ""),
    ]


def test_keywords_are_case_insensitive_but_normalized_upper():
    tokens = tokenize("select * from t")
    assert tokens[0].type is TokenType.KEYWORD
    assert tokens[0].value == "SELECT"


def test_identifiers_preserve_original_case():
    tokens = tokenize("SELECT Nombre FROM Estudiantes")
    ident = [t for t in tokens if t.type is TokenType.IDENTIFIER]
    assert [t.value for t in ident] == ["Nombre", "Estudiantes"]


def test_string_literal_with_escaped_quote():
    tokens = tokenize("SELECT 'O''Brien'")
    strings = [t for t in tokens if t.type is TokenType.STRING]
    assert strings[0].value == "O'Brien"


def test_float_vs_integer():
    tokens = tokenize("SELECT 3, 3.5")
    numeric = [t for t in tokens if t.type in (TokenType.INTEGER, TokenType.FLOAT)]
    assert numeric[0].type is TokenType.INTEGER
    assert numeric[1].type is TokenType.FLOAT


def test_not_equal_variants_normalize_to_diamond():
    tokens = tokenize("a <> b, a != b")
    punct = [t.value for t in tokens if t.type is TokenType.PUNCTUATION]
    assert punct == ["<>", ",", "<>"]


def test_line_comment_is_skipped():
    tokens = tokenize("SELECT 1 -- trailing comment\nFROM t")
    kinds = [t.type for t in tokens]
    assert TokenType.KEYWORD in kinds
    assert [t.value for t in tokens if t.type is TokenType.KEYWORD] == ["SELECT", "FROM"]


def test_unterminated_string_raises_with_position():
    with pytest.raises(SqlSyntaxError) as excinfo:
        tokenize("SELECT 'abc")
    assert excinfo.value.position == 8


def test_unrecognized_character_raises_with_position():
    with pytest.raises(SqlSyntaxError) as excinfo:
        tokenize("SELECT $foo")
    assert excinfo.value.position == 8


def test_non_string_input_rejected():
    with pytest.raises(SqlSyntaxError):
        tokenize(None)  # type: ignore[arg-type]
