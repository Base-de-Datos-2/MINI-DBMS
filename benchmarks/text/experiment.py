"""Part 3 block 6: MINI-DBMS SPIMI (TF-IDF/coseno, BM25) vs PostgreSQL FTS+GIN.

Usage, from the repository root (Python matching the frozen tokenizer
signature; the closure used CPython 3.12 / Unicode 15.0.0):

    python -m benchmarks.text.experiment run \
        --corpus data/generated/text_corpus/esci_us_test/accepted_py312 \
        --output benchmarks/results/text/<run> --work data/generated/text_bench/<run>

Each size gets two isolated worker processes: one prepares/publishes the
engine collection, the other verifies semantics and times queries. Raw rows
are written as they are measured; nothing is estimated or filled in.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import gc
import hashlib
import json
import os
import platform
from pathlib import Path
import subprocess
import sys
import time

REPOSITORY = Path(__file__).resolve().parents[2]
SIZES = (1000, 10000, 100000)
METHODS = ("tfidf", "bm25", "postgres")
ENGINE_MODELS = {"tfidf": "TF_IDF", "bm25": "BM25"}
REPETITIONS = 3
SPIMI_BUDGET_BYTES = 8 * 1024 * 1024  # Owner default used by Database.prepare_text.
SCORE_TOLERANCE = 1e-9


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as destination:
        json.dump(value, destination, ensure_ascii=False, indent=2, sort_keys=True)
        destination.write("\n")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def documents(corpus: Path, size: int):
    with (corpus / str(size) / "documents.jsonl").open(encoding="utf-8") as source:
        for line in source:
            row = json.loads(line)
            yield row["id"], row["text"]


def queries(corpus: Path):
    return read_json(corpus / "1000" / "queries.json")["queries"]


def status_value(status: str, key: str) -> int:
    line = next(line for line in status.splitlines() if line.startswith(key + ":"))
    return int(line.split()[1]) * 1024


def own_status() -> str:
    return Path("/proc/self/status").read_text(encoding="utf-8")


def reset_peak_rss():
    Path("/proc/self/clear_refs").write_text("5", encoding="ascii")


def directory_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def sql_literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def engine_sql(model: str, text: str, *, limit=True, order_by_id=False) -> str:
    sql = (f"SELECT id, SCORE() AS s FROM documentos WHERE MATCH(contenido, {sql_literal(text)}) "
           f"USING {ENGINE_MODELS[model]}")
    if order_by_id:
        sql += " ORDER BY id ASC"
    return sql + (" LIMIT 10" if limit else "")


# --------------------------------------------------------------------------- engine build

def build_engine_worker(corpus: Path, size: int, root: Path, output: Path):
    """Prepare and publish through the real owner, timing each stage."""
    import engine.text as text_package
    import engine.text.registry as registry
    import engine.text.spimi as spimi
    from api.database import Database, NewTable
    from engine.catalog import DataType

    timings = Counter()
    spimi_stages = Counter()
    observed = {"temporary_peak_bytes": 0}

    def timed(bucket, name, function):
        def wrapper(*args, **kwargs):
            started = time.perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                bucket[name] += time.perf_counter() - started
        return wrapper

    def tracking(name, function):
        inner = timed(spimi_stages, name, function)
        def wrapper(path_or_paths, *args, **kwargs):
            result = inner(path_or_paths, *args, **kwargs)
            stage = Path(args[0] if name == "merge_runs" else path_or_paths).parent
            observed["temporary_peak_bytes"] = max(observed["temporary_peak_bytes"], directory_bytes(stage))
            return result
        return wrapper

    spimi._write_block = tracking("write_blocks", spimi._write_block)
    spimi._merge_runs = tracking("merge_runs", spimi._merge_runs)
    spimi._finish = timed(spimi_stages, "write_postings_lexicon_statistics_norms", spimi._finish)
    original_build = text_package.build_spimi

    def build(*args, **kwargs):
        reset_peak_rss()
        observed["rss_before_bytes"] = status_value(own_status(), "VmRSS")
        started = time.perf_counter()
        report = original_build(*args, **kwargs)
        timings["spimi_build"] += time.perf_counter() - started
        status = own_status()
        observed["rss_peak_bytes"] = status_value(status, "VmHWM")
        observed["rss_after_bytes"] = status_value(status, "VmRSS")
        observed["report"] = asdict(report)
        return report

    text_package.build_spimi = build
    text_package.seal_text_collection = timed(timings, "seal", text_package.seal_text_collection)
    registry.publish_text_registry = timed(timings, "publish_registry", registry.publish_text_registry)
    Database.create_gui_table = timed(timings, "load_base_heap", Database.create_gui_table)

    table = NewTable("documentos", (("id", DataType.INTEGER), ("contenido", DataType.VARCHAR)))
    started = time.perf_counter()
    registrations = Database.prepare_text(root, [(table, documents(corpus, size), "id", "contenido")],
                                          memory_budget_bytes=SPIMI_BUDGET_BYTES)
    total = time.perf_counter() - started
    registration = registrations[0]
    heap_files = sorted(root.glob("g_*.heap"))
    if len(heap_files) != 1:
        raise RuntimeError("Expected exactly one Heap file in the text collection")
    index_directory = root / registration.directory
    components = {item.name: item.stat().st_size for item in sorted(index_directory.iterdir()) if item.is_file()}
    built = observed["report"]
    elapsed = dict(timings)
    elapsed["spimi_stages"] = dict(spimi_stages)
    elapsed["spimi_scan_tokenize_accumulate_and_validate"] = (
        timings["spimi_build"] - sum(spimi_stages.values()))
    elapsed["prepare_text_total"] = total
    elapsed["create_reopen_and_final_validation"] = total - sum(timings.values())
    write_json(output, {
        "method": "engine_spimi", "size": size, "collection_directory": registration.directory,
        "construction_seconds": timings["spimi_build"],
        "construction_includes": "SPIMI: Heap scan, tokenization, blocks, k-way merge, postings, lexicon, "
                                 "statistics, TF-IDF norms, ID/RID map and full index/storage validation "
                                 "(shared by TF-IDF and BM25)",
        "elapsed_seconds": elapsed, "spimi_report": built,
        "statistics": read_json(index_directory / "manifest.json")["statistics"],
        "disk": {"heap_bytes": heap_files[0].stat().st_size, "index_components_bytes": components,
                 "index_total_bytes": sum(components.values()),
                 "spimi_temporary_peak_bytes": observed["temporary_peak_bytes"],
                 "registry_bytes": (root / "text_tables.json").stat().st_size},
        "memory": {"scope": "isolated Python worker; VmHWM reset immediately before SPIMI",
                   "rss_before_spimi_bytes": observed["rss_before_bytes"],
                   "rss_peak_during_spimi_bytes": observed["rss_peak_bytes"],
                   "rss_after_spimi_bytes": observed["rss_after_bytes"],
                   "process_lifetime_peak_bytes": status_value(own_status(), "VmHWM")},
    })


# --------------------------------------------------------------------------- query worker

def engine_rows(database, sql, **options):
    with database.engine.execute(sql, **options) as result:
        return [tuple(row.values) for row in result]


def query_worker(corpus: Path, size: int, root: Path, container: str, output_directory: Path):
    from api.database import Database, DatabaseDefinition
    from . import fts
    from .metrics import evaluate, positives, read_qrels

    frozen_queries = queries(corpus)
    qrels = read_qrels(corpus / str(size) / "qrels.tsv")
    subset = {document_id for document_id, _ in documents(corpus, size)}
    status_start = own_status()
    opened = time.perf_counter()
    database = Database.open(DatabaseDefinition("text"), root)
    open_seconds = time.perf_counter() - opened
    rss_after_open = status_value(own_status(), "VmRSS")
    # Verification and plans use their own PostgreSQL session; the timed
    # workload gets a FRESH session so its backend peak excludes them.
    client = fts.connect(f"minidbms_text_{size}", container)
    try:
        # ---- semantics: lexemes, match sets, index/scan equivalence (untimed)
        expected_lexemes = fts.lexeme_digest(documents(corpus, size))
        actual_lexemes = client.json(fts.LEXEME_DIGEST_SQL)
        semantics = {"lexemes": {"engine_tokenizer": list(expected_lexemes), "postgres": actual_lexemes,
                                 "equal": [actual_lexemes["count"], actual_lexemes["md5"]] == list(expected_lexemes)},
                     "queries": []}
        for query in frozen_queries:
            tsquery = fts.tsquery_text(query["text"])
            engine_ids = [row[0] for row in engine_rows(database, engine_sql("bm25", query["text"], limit=False,
                                                                                order_by_id=True))]
            expected = fts.ids_digest(engine_ids)
            actual = client.json(fts.match_digest_sql(tsquery))
            entry = {"query_id": query["id"], "terms": list(fts.query_terms(query["text"])),
                     "tsquery": tsquery, "engine_matches": expected[0], "postgres_matches": actual["count"],
                     "match_sets_equal": [actual["count"], actual["md5"]] == list(expected)}
            for model in ENGINE_MODELS:
                indexed = engine_rows(database, engine_sql(model, query["text"]))
                scanned = engine_rows(database, engine_sql(model, query["text"]), use_indexes=False)
                entry[f"{model}_index_equals_scan"] = (
                    [row[0] for row in indexed] == [row[0] for row in scanned]
                    and all(abs(a[1] - b[1]) <= SCORE_TOLERANCE * max(1.0, abs(b[1]))
                            for a, b in zip(indexed, scanned)))
            semantics["queries"].append(entry)
        semantics["all_match_sets_equal"] = all(q["match_sets_equal"] for q in semantics["queries"])
        semantics["all_index_equals_scan"] = all(q[f"{m}_index_equals_scan"]
                                                 for q in semantics["queries"] for m in ENGINE_MODELS)
        if not (semantics["lexemes"]["equal"] and semantics["all_match_sets_equal"]
                and semantics["all_index_equals_scan"]):
            write_json(output_directory / f"semantics_{size}.json", semantics)
            raise RuntimeError(f"Semantic verification failed for N={size}; timings would be meaningless")
        write_json(output_directory / f"semantics_{size}.json", semantics)

        # ---- real PostgreSQL plans, recorded and not forced
        plans = []
        for query in frozen_queries:
            plan = client.explain(fts.top10_sql(fts.tsquery_text(query["text"])), analyze=True)
            plans.append({"query_id": query["id"], "node_types": sorted(node_types(plan["Plan"])),
                          "uses_gin": uses_index(plan["Plan"], "docs_tsv_gin"), "plan": plan})
        write_json(output_directory / f"plans_{size}.json", plans)
        verification_backend = client.resources()["status"]
        client.close()

        # ---- timed workload: fresh PostgreSQL session, Python peak reset
        client = fts.connect(f"minidbms_text_{size}", container)
        client.execute(fts.TOP10_FUNCTION)
        backend_start = client.resources()["status"]
        gc.collect()
        reset_peak_rss()
        rss_before_timing = status_value(own_status(), "VmRSS")

        def run(method, query):
            if method == "postgres":
                started = time.perf_counter()
                answer = client.json(f"SELECT pg_temp.fts_top10({fts.literal(fts.tsquery_text(query['text']))}::tsquery);")
                elapsed = time.perf_counter() - started
                return elapsed, answer["server_seconds"], [(row[0], float(row[1])) for row in answer["rows"]]
            started = time.perf_counter()
            rows = engine_rows(database, engine_sql(method, query["text"]))
            elapsed = time.perf_counter() - started
            return elapsed, None, [(row[0], float(row[1])) for row in rows]

        # ---- warm-up, then three repetitions with rotating method order
        for query in frozen_queries:
            for method in METHODS:
                run(method, query)
        rankings = {}
        rows_path = output_directory / f"queries_{size}.jsonl"
        with rows_path.open("x", encoding="utf-8") as destination:
            for repetition in range(REPETITIONS):
                for position, query in enumerate(frozen_queries):
                    shift = (repetition + position) % len(METHODS)
                    for order, method in enumerate(METHODS[shift:] + METHODS[:shift]):
                        elapsed, server, ranking = run(method, query)
                        key = (method, query["id"])
                        if key in rankings and rankings[key] != [identity for identity, _ in ranking]:
                            raise RuntimeError(f"Non-deterministic ranking for {key}")
                        rankings[key] = [identity for identity, _ in ranking]
                        relevant = positives(qrels.get(query["id"], {}), subset)
                        destination.write(json.dumps({
                            "size": size, "method": method, "query_id": query["id"],
                            "group": query["group"], "length": query["length"], "repetition": repetition,
                            "order_in_rotation": order, "elapsed_seconds": elapsed, "server_seconds": server,
                            "top10": ranking, **evaluate([identity for identity, _ in ranking], relevant),
                        }) + "\n")
                        destination.flush()
        backend_end = client.resources()["status"]
        timing_status = own_status()
    finally:
        client.close()
        database.close()
    write_json(output_directory / f"query_resources_{size}.json", {
        "size": size, "engine_open_seconds": open_seconds,
        "python_worker": {"scope": "isolated Python query worker: owner, open readers, harness and "
                                   "result rows; VmHWM reset after semantic verification, so the peak "
                                   "covers warm-up plus timed queries only",
                          "rss_start_bytes": status_value(status_start, "VmRSS"),
                          "rss_after_open_bytes": rss_after_open,
                          "rss_before_timing_bytes": rss_before_timing,
                          "peak_bytes": status_value(timing_status, "VmHWM")},
        "postgres_backend": {"scope": "backend of the fresh timed-query session only (excludes psql "
                                      "client, Docker, other server processes and the verification session)",
                             "rss_start_bytes": status_value(backend_start, "VmRSS"),
                             "peak_bytes": status_value(backend_end, "VmHWM"),
                             "verification_session_peak_bytes": status_value(verification_backend, "VmHWM")},
    })


def node_types(plan):
    yield plan["Node Type"]
    for child in plan.get("Plans", []):
        yield from node_types(child)


def uses_index(plan, name):
    if plan.get("Index Name") == name:
        return True
    return any(uses_index(child, name) for child in plan.get("Plans", []))


# --------------------------------------------------------------------------- orchestration

def environment(corpus: Path, container_info: dict) -> dict:
    import unicodedata
    from engine.text import tokenizer_signature
    from engine.text.ranking import BM25_B, BM25_K1
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPOSITORY, capture_output=True,
                            text=True, check=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "engine", "api", "benchmarks"],
                           cwd=REPOSITORY, capture_output=True, text=True, check=True).stdout.strip()
    memory = next(line for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemTotal"))
    cpu = next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name")), platform.processor())
    corpus_files = {f"{size}/{name}": sha256(corpus / str(size) / name)
                    for size in SIZES for name in ("documents.jsonl", "queries.json", "qrels.tsv", "manifest.json")}
    measured_sources = sorted([*REPOSITORY.glob("engine/text/*.py"), *REPOSITORY.glob("benchmarks/text/*.py"),
                               REPOSITORY / "benchmarks/postgres_client.py", REPOSITORY / "api/database.py",
                               REPOSITORY / "engine/query/text_binding.py"])
    source_hashes = {str(path.relative_to(REPOSITORY)): sha256(path) for path in measured_sources}
    return {"format": "MINIDBMS_TEXT_EXPERIMENT", "version": 1, "commit": commit,
            "uncommitted_changes_in_engine_api_benchmarks": dirty.splitlines(),
            "measured_source_sha256": source_hashes,
            "python": sys.version, "unicode": unicodedata.unidata_version, "platform": platform.platform(),
            "cpu": cpu, "cpu_count": os.cpu_count(), "memory_total": memory.split(":", 1)[1].strip(),
            "tokenizer": tokenizer_signature(), "spimi_memory_budget_bytes": SPIMI_BUDGET_BYTES,
            "bm25": {"k1": BM25_K1, "b": BM25_B},
            "tfidf": "tf_weight=1+ln(tf); idf=ln((N+1)/(df+1))+1; cosine over full document norm",
            "postgres": {**container_info, "session_settings": "max_parallel_workers_per_gather=0, jit=off",
                         "lexemes": "engine tokens loaded as tsvector input ('term':positions); the "
                                    "'simple' parser drops characters such as '½' that the engine keeps",
                         "ts_rank_normalization": 0, "query_operator": "OR of quoted lexemes"},
            "repetitions": REPETITIONS, "warmup_passes": 1, "methods": list(METHODS), "sizes": list(SIZES),
            "query_count": len(queries(corpus)), "corpus": str(corpus.relative_to(REPOSITORY)),
            "corpus_sha256": corpus_files,
            "timing_boundary": {
                "engine": "SqlEngine.execute through parse, bind, plan, TextIndexScan and iteration of the "
                          "top-10 id/score rows (no HTTP, UI or document texts)",
                "postgres": "client round trip through psql/docker exec of a function returning top-10 "
                            "id/ts_rank as JSON; server_seconds measured separately inside PostgreSQL"}}


def run(args):
    from . import fts
    corpus, output, work = args.corpus.resolve(), args.output.resolve(), args.work.resolve()
    output.mkdir(parents=True, exist_ok=False)
    work.mkdir(parents=True, exist_ok=False)
    container_info = fts.start_container(args.container) if args.start_container else {"container": args.container}
    with fts.connect("postgres", args.container) as client:
        container_info["version"] = client.resources()["version"]
    write_json(output / "environment.json", environment(corpus, container_info))
    python = sys.executable
    for size in args.sizes:
        root = work / f"engine_{size}"
        print(f"[{time.strftime('%H:%M:%S')}] N={size}: engine build", flush=True)
        subprocess.run([python, "-m", "benchmarks.text.experiment", "build-engine", "--corpus", str(corpus),
                        "--size", str(size), "--root", str(root),
                        "--output", str(output / f"build_engine_{size}.json")], cwd=REPOSITORY, check=True)
        print(f"[{time.strftime('%H:%M:%S')}] N={size}: PostgreSQL build", flush=True)
        write_json(output / f"build_postgres_{size}.json",
                   fts.build(args.container, size, documents(corpus, size), work))
        print(f"[{time.strftime('%H:%M:%S')}] N={size}: semantics and timed queries", flush=True)
        subprocess.run([python, "-m", "benchmarks.text.experiment", "query", "--corpus", str(corpus),
                        "--size", str(size), "--root", str(root), "--container", args.container,
                        "--output", str(output)], cwd=REPOSITORY, check=True)
    print(f"[{time.strftime('%H:%M:%S')}] done: {output}", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    full = commands.add_parser("run")
    full.add_argument("--corpus", type=Path, required=True)
    full.add_argument("--output", type=Path, required=True)
    full.add_argument("--work", type=Path, required=True)
    full.add_argument("--container", default="minidbms-text-pg")
    full.add_argument("--start-container", action="store_true")
    full.add_argument("--sizes", type=int, nargs="+", default=list(SIZES), choices=SIZES)
    worker = commands.add_parser("build-engine")
    worker.add_argument("--corpus", type=Path, required=True)
    worker.add_argument("--size", type=int, required=True, choices=SIZES)
    worker.add_argument("--root", type=Path, required=True)
    worker.add_argument("--output", type=Path, required=True)
    timed = commands.add_parser("query")
    timed.add_argument("--corpus", type=Path, required=True)
    timed.add_argument("--size", type=int, required=True, choices=SIZES)
    timed.add_argument("--root", type=Path, required=True)
    timed.add_argument("--container", required=True)
    timed.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "run":
        run(args)
    elif args.command == "build-engine":
        build_engine_worker(args.corpus.resolve(), args.size, args.root.resolve(), args.output.resolve())
    else:
        query_worker(args.corpus.resolve(), args.size, args.root.resolve(), args.container,
                     args.output.resolve())


if __name__ == "__main__":
    main()
