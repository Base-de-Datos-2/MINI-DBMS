"""PostgreSQL FTS + GIN + ts_rank comparator for the Part 3 experiment.

PostgreSQL only compares; it never answers MINI-DBMS queries. To make both
systems see the same lexemes, documents and queries are first tokenized with
the engine tokenizer (NFC, lowercase, NFC, maximal alphanumeric runs).

PostgreSQL's own 'simple' parser is NOT used on the text: on the frozen ESCI
titles it silently drops characters that str.isalnum() accepts (for example
'½'), so the two systems would index different terms. Instead each document's
engine tokens are written in tsvector input syntax ('term':positions), which
PostgreSQL parses without dictionaries or stemming. It still builds the
tsvector values, the GIN index and the ts_rank scores. Lexeme/frequency and
match-set equality are verified before any timing is trusted.
"""

from __future__ import annotations

from collections import Counter
import csv
import hashlib
from pathlib import Path, PurePosixPath
import re
import secrets
import subprocess
import time

from engine.text import tokenize

from ..postgres_client import PostgresClient, identifier, literal

IMAGE = "postgres:17"
CONTAINER = "minidbms-text-pg"
#: Parallel workers and JIT stay off for single-process comparability; access
#: paths are NOT forced: the planner may pick a sequential scan (reported).
SESSION_SETTINGS = "SET max_parallel_workers_per_gather=0; SET jit=off;"
TS_RANK_NORMALIZATION = 0
SERVER_SETTINGS = {"shared_buffers": "128MB", "work_mem": "4MB"}
MEMORY_LIMIT = "2g"


def quoted_lexeme(term: str) -> str:
    if not term or any(character.isspace() for character in term):
        raise ValueError("Normalized terms cannot be empty or contain whitespace")
    return "'" + term.replace("\\", "\\\\").replace("'", "''") + "'"


def tsvector_text(text: str) -> str:
    """Engine tokens as tsvector input: each lexeme with its 1-based positions."""
    positions: dict[str, list[int]] = {}
    for position, term in enumerate(tokenize(text), start=1):
        if position > 16383:
            raise ValueError("tsvector positions are limited to 16383")
        positions.setdefault(term, []).append(position)
    if any(len(values) > 256 for values in positions.values()):
        raise ValueError("tsvector keeps at most 256 positions per lexeme")
    return " ".join(f"{quoted_lexeme(term)}:{','.join(map(str, values))}"
                    for term, values in positions.items())


def query_terms(text: str) -> tuple[str, ...]:
    """Distinct normalized query terms in first-appearance order (OR semantics)."""
    return tuple(dict.fromkeys(tokenize(text)))


def tsquery_text(text: str) -> str | None:
    """OR of quoted lexemes, cast later with ::tsquery (no reparsing or AND)."""
    terms = query_terms(text)
    if not terms:
        return None
    return " | ".join(quoted_lexeme(term) for term in terms)


def lexeme_line(document_id: int, text: str) -> str:
    counts = Counter(tokenize(text))
    return f"{document_id}:" + " ".join(f"{term}/{counts[term]}" for term in sorted(counts))


def lexeme_digest(documents) -> tuple[int, str]:
    """md5 over id-ordered canonical lexeme/frequency lines, as computed in SQL."""
    lines = [lexeme_line(document_id, text) for document_id, text in sorted(documents)]
    return len(lines), hashlib.md5("\n".join(lines).encode("utf-8")).hexdigest()


def ids_digest(identities) -> tuple[int, str]:
    ordered = sorted(identities)
    return len(ordered), hashlib.md5(",".join(map(str, ordered)).encode("ascii")).hexdigest()


LEXEME_DIGEST_SQL = """SELECT json_build_object('count', count(*), 'md5',
  md5(coalesce(string_agg(id::text || ':' || coalesce(l, ''), E'\\n' ORDER BY id), '')))
FROM (SELECT id, (SELECT string_agg(lexeme || '/' || coalesce(array_length(positions, 1), 0)::text,
                                    ' ' ORDER BY lexeme COLLATE "C")
                  FROM unnest(tsv)) AS l FROM docs) s;"""


def match_digest_sql(tsquery: str) -> str:
    return ("SELECT json_build_object('count', count(*), 'md5', "
            "md5(coalesce(string_agg(id::text, ',' ORDER BY id), ''))) "
            f"FROM docs WHERE tsv @@ {literal(tsquery)}::tsquery;")


def top10_sql(tsquery: str) -> str:
    query = f"{literal(tsquery)}::tsquery"
    return (f"SELECT id, ts_rank(tsv, {query}, {TS_RANK_NORMALIZATION}) AS r FROM docs "
            f"WHERE tsv @@ {query} ORDER BY r DESC, id ASC LIMIT 10")


#: The tsquery is a typed parameter bound with EXECUTE ... USING: one-shot
#: custom plans, never text concatenated into the search statement.
TOP10_FUNCTION = f"""
CREATE FUNCTION pg_temp.fts_top10(q tsquery) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE started timestamptz; result jsonb;
BEGIN
  started := clock_timestamp();
  EXECUTE 'SELECT coalesce(jsonb_agg(jsonb_build_array(id, r) ORDER BY r DESC, id), ''[]''::jsonb)
           FROM (SELECT id, ts_rank(tsv, $1, {TS_RANK_NORMALIZATION}) AS r FROM docs
                 WHERE tsv @@ $1 ORDER BY r DESC, id ASC LIMIT 10) s' INTO result USING q;
  RETURN jsonb_build_object('server_seconds', extract(epoch FROM clock_timestamp() - started),
                            'rows', result);
END $$;"""


def connect(database: str, container: str = CONTAINER, timeout: int = 1800) -> PostgresClient:
    return PostgresClient(container, database=database, timeout=timeout,
                          settings=SESSION_SETTINGS, extension_version_sql=None)


def docker(*arguments, check=True, capture=True):
    return subprocess.run(["docker", *arguments], check=check, text=True, encoding="utf-8",
                          capture_output=capture)


def start_container(name: str = CONTAINER, image: str = IMAGE) -> dict:
    """Start a NEW isolated comparator (no network). An existing name fails."""
    password = secrets.token_urlsafe(24)  # Never printed: only local socket trust is used.
    arguments = ["run", "-d", "--name", name, "--network", "none", "--memory", MEMORY_LIMIT,
                 "-e", f"POSTGRES_PASSWORD={password}", image]
    for key, value in SERVER_SETTINGS.items():
        arguments += ["-c", f"{key}={value}"]
    docker(*arguments)
    for _ in range(120):
        if docker("exec", name, "pg_isready", "-U", "postgres", check=False).returncode == 0:
            # The entrypoint restarts once after initialization; require two
            # consecutive ready checks so the first client does not race it.
            time.sleep(2)
            if docker("exec", name, "pg_isready", "-U", "postgres", check=False).returncode == 0:
                break
        time.sleep(1)
    else:
        raise RuntimeError("Comparator container did not become ready")
    digest = docker("image", "inspect", "--format", "{{index .RepoDigests 0}}", image).stdout.strip()
    return {"container": name, "image": image, "image_digest": digest, "network": "none",
            "memory_limit": MEMORY_LIMIT, "server_settings": dict(SERVER_SETTINGS)}


def write_staging(documents, path: Path) -> dict:
    """CSV of id, original text and engine tokens in tsvector input syntax.

    The Python tokenization time is reported separately: it is preparation
    shared with the engine's rules, not part of PostgreSQL's index build.
    """
    started = time.perf_counter()
    with path.open("x", encoding="utf-8", newline="") as destination:
        writer = csv.writer(destination, lineterminator="\n")
        for document_id, text in documents:
            writer.writerow((document_id, text, tsvector_text(text)))
    return {"python_tokenization_seconds": time.perf_counter() - started,
            "staging_bytes": path.stat().st_size}


def copy_into(container: str, local: Path) -> PurePosixPath:
    temporary = docker("exec", container, "mktemp", "-d", "/tmp/minidbms-text.XXXXXXXX").stdout.strip()
    if not re.fullmatch(r"/tmp/minidbms-text\.[A-Za-z0-9]{8}", temporary):
        raise ValueError("Unexpected container temporary directory")
    remote = PurePosixPath(temporary) / local.name
    docker("cp", str(local), f"{container}:{remote}")
    docker("exec", "-u", "root", container, "chmod", "a+r", str(remote))
    return remote


def build(container: str, size: int, documents, work_directory: Path) -> dict:
    """Create a NEW database and time tsvector conversion, GIN, key and ANALYZE."""
    database = identifier(f"minidbms_text_{size}")
    staging = write_staging(documents, work_directory / f"staging_{size}.csv")
    remote = copy_into(container, work_directory / f"staging_{size}.csv")
    docker("exec", container, "createdb", "-U", "postgres", database)
    stages = {}
    with connect(database, container) as client:
        start = client.resources()["status"]
        client.execute("CREATE TABLE staging (id bigint NOT NULL, contenido text NOT NULL, lexemes text NOT NULL);")
        started = time.perf_counter()
        client.execute(f"\\copy staging FROM {literal(str(remote))} WITH (FORMAT csv)")
        stages["copy_base_data"] = {"elapsed_seconds": time.perf_counter() - started, "server_seconds": None}
        statements = {
            "tsvector_conversion": "CREATE TABLE docs AS SELECT id, contenido, "
                                   "lexemes::tsvector AS tsv FROM staging",
            "gin_index": "CREATE INDEX docs_tsv_gin ON docs USING gin (tsv)",
            "primary_key": "ALTER TABLE docs ADD PRIMARY KEY (id)",
            "analyze": "ANALYZE docs",
        }
        for name, statement in statements.items():
            stages[name] = client.measure(statement)
        client.execute("DROP TABLE staging;")
        resources = client.resources()
        sizes = client.json("""SELECT json_build_object(
            'documents', (SELECT count(*) FROM docs),
            'table_main_bytes', pg_relation_size('docs'),
            'table_with_toast_bytes', pg_table_size('docs'),
            'gin_bytes', pg_relation_size('docs_tsv_gin'),
            'primary_key_bytes', pg_relation_size('docs_pkey'),
            'tsvector_column_bytes', (SELECT sum(pg_column_size(tsv)) FROM docs),
            'text_column_bytes', (SELECT sum(pg_column_size(contenido)) FROM docs),
            'database_bytes', pg_database_size(current_database()),
            'settings', json_build_object('shared_buffers', current_setting('shared_buffers'),
                'work_mem', current_setting('work_mem'),
                'maintenance_work_mem', current_setting('maintenance_work_mem'),
                'default_text_search_config', current_setting('default_text_search_config')));""")
    docker("exec", container, "rm", "-f", "--", str(remote), check=False)
    docker("exec", container, "rmdir", "--", str(remote.parent), check=False)
    construction = sum(stages[name]["elapsed_seconds"] for name in ("tsvector_conversion", "gin_index"))
    return {"method": "postgres_fts_gin", "size": size, "database": database, **staging,
            "stages": stages, "construction_seconds": construction,
            "construction_includes": "tsvector construction from engine tokens (tsvector input syntax, "
                                     "no PostgreSQL parser/dictionary) + GIN creation; Python "
                                     "tokenization, primary key and ANALYZE reported separately",
            "backend_status_start": start, "backend_status_end": resources["status"],
            "version": resources["version"], "sizes": sizes}
