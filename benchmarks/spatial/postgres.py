"""Prepare an isolated PostgreSQL comparator locally or inside Docker.

This is data/setup work only. Timed experiments and cross-engine validation
belong to E4. No password is accepted as a command argument or printed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

from .datasets import REQUIRED_SIZES

SCHEMA = "minidbms_spatial_bench"


def setup_sql(directory: Path, size: int) -> str:
    """Check generated inputs before preparing a new comparator schema."""
    directory = directory.resolve()
    manifest = json.loads((directory / "inputs.json").read_text(encoding="utf-8"))
    if (size not in REQUIRED_SIZES or manifest.get("format") != "MINIDBMS_SPATIAL_INPUTS"
            or manifest.get("version") != 1 or size not in manifest["sizes"]):
        raise ValueError("Unsupported or missing dataset")
    paths = [directory / f"points_{size}.csv", directory / "queries.csv"]
    for path in paths:
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["sha256"][path.name]:
            raise ValueError(f"Input checksum mismatch: {path.name}")
    points, queries = (str(path.as_posix()).replace("'", "''") for path in paths)
    return f"""BEGIN;
CREATE EXTENSION IF NOT EXISTS postgis;
-- No DROP or replacement: an existing experiment fails rather than being lost.
CREATE SCHEMA {SCHEMA};
CREATE TABLE {SCHEMA}.points (
    id bigint PRIMARY KEY, nombre text NOT NULL,
    latitud double precision NOT NULL CHECK (latitud BETWEEN -12.30 AND -11.80),
    longitud double precision NOT NULL CHECK (longitud BETWEEN -77.25 AND -76.75),
    ubicacion geography(Point,4326) GENERATED ALWAYS AS
      (ST_SetSRID(ST_MakePoint(longitud,latitud),4326)::geography) STORED
);
\\copy {SCHEMA}.points (id,nombre,latitud,longitud) FROM '{points}' WITH (FORMAT csv, HEADER true)
CREATE TABLE {SCHEMA}.queries (
    query_id integer PRIMARY KEY, latitud double precision, longitud double precision
);
\\copy {SCHEMA}.queries FROM '{queries}' WITH (FORMAT csv, HEADER true)
CREATE INDEX points_location_gist ON {SCHEMA}.points USING gist (ubicacion);
ANALYZE {SCHEMA}.points;
COMMIT;
SELECT version(), PostGIS_Full_Version();
SELECT count(*) AS point_count FROM {SCHEMA}.points;
-- Calibrate the actual spherical radius; E2/E4 must check it against the engine.
SELECT ST_Distance('SRID=4326;POINT(0 0)'::geography,
                   'SRID=4326;POINT(1 0)'::geography, false) / radians(1)
       AS spherical_radius_metres;
-- Candidate predicate plus strict exact residual in metres, with spherical mode.
EXPLAIN (ANALYZE, BUFFERS)
SELECT id FROM {SCHEMA}.points
WHERE ST_DWithin(ubicacion, 'SRID=4326;POINT(-77.0428 -12.0464)'::geography, 5000, false)
  AND ST_Distance(ubicacion, 'SRID=4326;POINT(-77.0428 -12.0464)'::geography, false) < 5000;
-- Geography <-> uses spherical k-NN; tied subsets need the E4 validation policy.
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, ubicacion <-> 'SRID=4326;POINT(-77.0428 -12.0464)'::geography AS distance_metres
FROM {SCHEMA}.points
ORDER BY ubicacion <-> 'SRID=4326;POINT(-77.0428 -12.0464)'::geography LIMIT 10;
"""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, default=Path("data/generated/spatial_inputs"))
    parser.add_argument("--size", type=int, choices=REQUIRED_SIZES, default=1000)
    parser.add_argument("--psql", default="psql")
    parser.add_argument("--container", help="running Docker container with PostgreSQL/PostGIS")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--database", default="minidbms_spatial")
    parser.add_argument("--sql-output", type=Path,
                        help="write SQL only, without connecting to PostgreSQL")
    args = parser.parse_args(argv)
    if args.container and args.sql_output:
        parser.error("--container and --sql-output cannot be combined")
    sql = setup_sql(args.inputs, args.size)
    if args.sql_output:
        with args.sql_output.open("x", encoding="utf-8", newline="\n") as output:
            output.write(sql)
        print(f"Comparator SQL written to {args.sql_output}")
        return
    if args.container:
        _run_container(args, sql)
        return
    command = [args.psql, "-X", "-w", "-v", "ON_ERROR_STOP=1", "-h", args.host,
               "-p", str(args.port), "-U", args.user, "-d", args.database, "-f", "-"]
    # psql reads pgpass itself. -w refuses to block on an interactive password prompt.
    subprocess.run(command, input=sql, text=True, encoding="utf-8", check=True)


def _run_container(args, verified_sql: str) -> None:
    """Copy checksum-verified inputs to a fresh directory and run container psql.

    Local Unix-socket authentication follows the container's existing policy.
    Neither network authentication nor any existing database is reconfigured.
    """
    prefix = ["docker", "exec", args.container]
    temporary = subprocess.run(
        [*prefix, "mktemp", "-d", "/tmp/minidbms-spatial.XXXXXXXX"],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout.strip()
    if not re.fullmatch(r"/tmp/minidbms-spatial\.[A-Za-z0-9]{8}", temporary):
        raise ValueError("Unexpected container temporary directory")
    local_paths = [args.inputs.resolve() / f"points_{args.size}.csv",
                   args.inputs.resolve() / "queries.csv"]
    remote_paths = [PurePosixPath(temporary) / path.name for path in local_paths]
    # Reuse exactly the verified SQL; only its client-side COPY paths change.
    sql = verified_sql
    try:
        for local, remote in zip(local_paths, remote_paths):
            subprocess.run(["docker", "cp", str(local), f"{args.container}:{remote}"], check=True)
            sql = sql.replace(str(local.as_posix()).replace("'", "''"), str(remote))
        command = ["docker", "exec", "-i", args.container, args.psql, "-X", "-w",
                   "-v", "ON_ERROR_STOP=1", "-U", args.user, "-d", args.database, "-f", "-"]
        subprocess.run(command, input=sql, text=True, encoding="utf-8", check=True)
    finally:
        # Delete only these two copies and their fresh directory, never recursively.
        subprocess.run([*prefix, "rm", "-f", "--", *map(str, remote_paths)], check=False)
        subprocess.run([*prefix, "rmdir", "--", temporary], check=False)


if __name__ == "__main__":
    main()
