"""Acceptance checks for the new read-only HTTP text interface contract."""
import pytest
from pydantic import ValidationError as PydanticValidationError
from api.schemas import TextSearchRequest
from api.text_search import published_tables, run_published_search
from engine.errors import ValidationError


def test_request_defaults_and_limits():
    request = TextSearchRequest(table='documentos', column='contenido', query='base de datos')
    assert (request.model, request.order, request.limit, request.use_indexes) == ('BM25', 'score_desc', 10, True)
    for bad in ({'model': 'UNKNOWN'}, {'max_rows': 501}, {'limit': -1}, {'table': '../x'}, {'query': 'a'*4097}):
        with pytest.raises(PydanticValidationError):
            TextSearchRequest(**({'table':'documentos','column':'contenido','query':'base'} | bad))


def test_no_fabricated_collections():
    class Database:
        _text_indexes = {}
    assert published_tables(Database()) == []
    with pytest.raises(ValidationError, match='No compatible published'):
        run_published_search(Database(), TextSearchRequest(table='documentos', column='contenido', query='base'))
