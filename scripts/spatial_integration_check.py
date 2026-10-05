"""Spatial SQL, HTTP, sessions and persistence through a real TCP server."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
from time import monotonic, sleep

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.spatial.datasets import FIXTURE_POLYGON
from scripts.integration_check import Checks, Server, stopped
from scripts.setup_spatial import prepare


SQL = "SELECT id FROM tiendas ORDER BY distancia(ubicacion, mi_ubicacion) LIMIT 2"
POINT = {"mi_ubicacion": [-12.0464, -77.0428]}


def check_queries(server, checks):
    for metric in ("euclidean", "haversine"):
        sql = f"SELECT id FROM tiendas WHERE distancia(ubicacion, POINT(-12.0464,-77.0428), '{metric}') < 5000 ORDER BY id"
        status, indexed = server.query(sql)
        other_status, scanned = server.query(sql, use_indexes=False)
        checks.check(f"radio {metric}: SQL R-Tree y scan coinciden",
                     status == other_status == 200 and indexed.get("rows") == scanned.get("rows")
                     and "SpatialIndexScan" in str(indexed.get("execution_plan")))
    status, body = server.query(SQL, parameters=POINT)
    checks.check("k-NN con parámetro y empate por id", status == 200 and body.get("rows") == [[1], [2]])
    payload = {"table": "tiendas", "kind": "polygon", "vertices": FIXTURE_POLYGON}
    status, indexed = server.post("/api/spatial/query", payload)
    other_status, scanned = server.post("/api/spatial/query", {**payload, "use_indexes": False})
    checks.check("polígono HTTP: registros y estadísticas reales",
                 status == other_status == 200 and indexed.get("matches") == scanned.get("matches")
                 and indexed.get("stats", {}).get("access") == "RTree"
                 and [item["id"] for item in indexed.get("matches", [])] == [1, 2, 3, 4, 5, 6])
    status, body = server.query(SQL)
    checks.check("parámetro ausente: error controlado", status == 422 and body.get("error", {}).get("code") == "SQL_ERROR")
    checks.check("recuperación tras error", server.query("SELECT id FROM tiendas LIMIT 1")[0] == 200)


def check_transactions(server, checks):
    writer = server.post("/api/sessions")[1]["token"]
    reader = server.post("/api/sessions")[1]["token"]
    checks.check("BEGIN e INSERT", server.query("BEGIN TRANSACTION", writer)[0] == 200 and
                 server.query("INSERT INTO tiendas VALUES (99, 'Nueva', -12.0464, -77.0428)", writer)[0] == 200)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(server.query, SQL.replace("LIMIT 2", "LIMIT 100"), reader, parameters=POINT)
        deadline = monotonic() + 3
        waiting = None
        while monotonic() < deadline and not future.done():
            waiting = server.get("/api/session", reader).get("waiting")
            if waiting:
                break
            sleep(.01)
        checks.check("lector espera en lock de tiendas", waiting is not None and waiting["resource"] == "tiendas")
        checks.check("commit desbloquea otra sesión", server.query("END TRANSACTION", writer)[0] == 200)
        status, body = future.result(timeout=5)
        checks.check("lector observa fila confirmada", status == 200 and [99] in body.get("rows", []))
    server.query("BEGIN TRANSACTION", writer)
    server.query("DELETE FROM tiendas WHERE id = 1", writer)
    checks.check("rollback restaura Heap y R-Tree", server.query("ROLLBACK", writer)[0] == 200 and
                 server.query(SQL, writer, parameters=POINT)[1].get("rows") == [[1], [2]])
    for token in (writer, reader):
        server._call("DELETE", "/api/session", token=token)


def run(directory, port, report):
    prepare(directory)
    checks = Checks()
    server = Server(directory, port, ("--spatial", "--frontend-dir", str(directory / "no-frontend")))
    try:
        server.start()
        check_queries(server, checks)
        check_transactions(server, checks)
    finally:
        if server.process is not None and server.process.poll() is None:
            status, output = server.stop()
            stopped(checks, "cierre espacial limpio", status, output)
    checks.check("puerto libre para reapertura", server.wait_for_port() < 1)
    try:
        server.start()
        status, body = server.query("SELECT id FROM tiendas WHERE id = 99")
        checks.check("fila confirmada persiste tras reabrir", status == 200 and body.get("rows") == [[99]])
        checks.check("restauración persiste tras reabrir", server.query(SQL, parameters=POINT)[1].get("rows") == [[1], [2]])
    finally:
        if server.process is not None and server.process.poll() is None:
            status, output = server.stop()
            stopped(checks, "segundo cierre espacial limpio", status, output)
    report.write_text(json.dumps(checks.results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return bool(checks.failed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18811)
    args = parser.parse_args()
    return run(args.data_dir, args.port, args.report)


if __name__ == "__main__":
    sys.exit(main())
