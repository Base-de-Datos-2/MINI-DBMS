"""Compatibility entry point; SQL semantics belong exclusively to engine.query."""
from engine.query.ast import ExplainStatement, SelectStatement
from engine.query.text_binding import is_text_select


def is_text_statement(statement):
    select = statement.select if isinstance(statement, ExplainStatement) else statement
    return isinstance(select, SelectStatement) and is_text_select(select)


def run_text_sql(database, statement, *, source, session, use_indexes, max_rows):
    """Old callers share the native session and standard result serializer."""
    from .engine_service import EngineService
    from .schemas import QueryRequest
    runner = session or database.session_coordinator.default_session
    service = EngineService(database)
    result = runner.execute(source, use_indexes=use_indexes)
    return service._dispatch(result, QueryRequest(sql=source, use_indexes=use_indexes, max_rows=max_rows))
