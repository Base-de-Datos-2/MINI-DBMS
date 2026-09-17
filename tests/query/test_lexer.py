"""Task 7.4: tokenizer coverage."""

import pytest

from engine.query.lexer import (
    MAX_NUMERIC_LITERAL_DIGITS,
    MAX_SQL_INPUT_CHARS,
    SqlLexicalError,
    SqlSyntaxError,
    TokenType,
    tokenize,
)


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
        (TokenType.COMPARISON_OPERATOR, ">="),
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
    operators = [
        t.value for t in tokens if t.type is TokenType.COMPARISON_OPERATOR
    ]
    assert operators == ["<>", "<>"]
    assert [t.value for t in tokens if t.type is TokenType.PUNCTUATION] == [","]


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


def test_tokens_retain_original_lexeme_decoded_value_and_exact_span():
    tokens = tokenize("select 12, 'O''Brien', a != 2.5")

    keyword, integer, string, inequality, floating = (
        tokens[0],
        tokens[1],
        tokens[3],
        tokens[6],
        tokens[7],
    )
    assert (keyword.lexeme, keyword.value, keyword.decoded) == (
        "select",
        "SELECT",
        "SELECT",
    )
    assert (integer.lexeme, integer.decoded) == ("12", 12)
    assert (string.lexeme, string.value, string.decoded) == (
        "'O''Brien'",
        "O'Brien",
        "O'Brien",
    )
    assert (inequality.lexeme, inequality.value) == ("!=", "<>")
    assert (floating.lexeme, floating.decoded) == ("2.5", 2.5)
    assert (keyword.span.start, keyword.span.end) == (0, 6)
    assert (
        keyword.span.start_line,
        keyword.span.start_column,
        keyword.span.end_line,
        keyword.span.end_column,
    ) == (1, 1, 1, 7)


def test_plus_and_minus_are_separate_from_numeric_literals():
    tokens = tokenize("-12 + 3.5")

    assert [(token.type, token.value) for token in tokens] == [
        (TokenType.MINUS, "-"),
        (TokenType.INTEGER, "12"),
        (TokenType.PLUS, "+"),
        (TokenType.FLOAT, "3.5"),
        (TokenType.EOF, ""),
    ]


def test_eof_and_multiline_locations_use_half_open_offsets():
    tokens = tokenize("SELECT\nname")

    name = tokens[1]
    eof = tokens[-1]
    assert (name.span.start_line, name.span.start_column) == (2, 1)
    assert (name.span.end_line, name.span.end_column) == (2, 5)
    assert (eof.span.start, eof.span.end) == (11, 11)
    assert (eof.span.start_line, eof.span.start_column) == (2, 5)


def test_keyword_prefix_and_quoted_separators_are_not_split():
    tokens = tokenize("SELECTED 'FROM,;--still text'")

    assert tokens[0].type is TokenType.IDENTIFIER
    assert tokens[0].value == "SELECTED"
    assert tokens[1].type is TokenType.STRING
    assert tokens[1].decoded == "FROM,;--still text"


def test_input_limit_accepts_boundary_and_rejects_first_excess_character():
    assert tokenize(" " * MAX_SQL_INPUT_CHARS)[-1].type is TokenType.EOF

    with pytest.raises(SqlLexicalError) as excinfo:
        tokenize(" " * (MAX_SQL_INPUT_CHARS + 1))
    assert excinfo.value.position == MAX_SQL_INPUT_CHARS + 1


def test_oversized_numeric_literal_is_a_controlled_lexical_error():
    with pytest.raises(SqlLexicalError) as excinfo:
        tokenize("9" * (MAX_NUMERIC_LITERAL_DIGITS + 1))
    assert excinfo.value.position == 1


def test_non_ascii_numeric_character_is_rejected_without_conversion_leak():
    with pytest.raises(SqlLexicalError) as excinfo:
        tokenize("SELECT ²")
    assert excinfo.value.position == 8


@pytest.mark.parametrize("literal", ["1.", ".5", "1.2.3"])
def test_malformed_decimal_is_rejected_by_the_lexer(literal):
    with pytest.raises(SqlLexicalError):
        tokenize(f"SELECT {literal}")


def test_empty_and_whitespace_input_produce_only_eof():
    for source in ("", " \t\r\n"):
        tokens = tokenize(source)
        assert len(tokens) == 1
        assert tokens[0].type is TokenType.EOF
        assert tokens[0].span.start == len(source)
