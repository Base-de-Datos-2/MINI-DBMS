"""GiST comparison with explicit access selection and server/client times."""

import csv
import io

from benchmarks.postgres_client import PostgresClient, identifier
from engine.spatial.metadata import EARTH_RADIUS_METRES

from .measurement import measure_settings
from .validation import peak_rss_bytes, uses_gist


def query_sql(schema, center, kind, value):
    schema = identifier(schema)
    latitude, longitude = center
    # Values originate in checksum-verified numeric inputs, never user SQL.
    point = f"'SRID=4326;POINT({float(longitude):.17g} {float(latitude):.17g})'::geography"
    if kind == "radius":
        source = (f"SELECT id, ST_Distance(ubicacion,{point},false) AS d FROM {schema}.points "
                  f"WHERE ST_DWithin(ubicacion,{point},{int(value)},false) "
                  f"AND ST_Distance(ubicacion,{point},false) < {int(value)}")
        ordering = "id"
    elif kind == "knn":
        source = (f"SELECT id, ubicacion <-> {point} AS d FROM {schema}.points "
                  f"ORDER BY ubicacion <-> {point}, id LIMIT {int(value)}")
        ordering = "d,id"
    else:
        raise ValueError("Unknown spatial query kind")
    return f"SELECT COALESCE(json_agg(json_build_array(id,d) ORDER BY {ordering}),'[]'::json) FROM ({source}) AS matches"


def create_points(client, schema, points):
    schema = identifier(schema)
    client.execute(f"""CREATE TABLE {schema}.points (
 id bigint PRIMARY KEY, nombre text NOT NULL, latitud double precision NOT NULL,
 longitud double precision NOT NULL, ubicacion geography(Point,4326) GENERATED ALWAYS AS
 (ST_SetSRID(ST_MakePoint(longitud,latitud),4326)::geography) STORED);
""")
    stream = io.StringIO()
    csv.writer(stream, lineterminator="\n").writerows(points)
    client.execute(f"COPY {schema}.points (id,nombre,latitud,longitud) FROM STDIN WITH (FORMAT csv);\n" + stream.getvalue() + "\\.\n")
    actual = client.json(f"SELECT json_agg(json_build_array(id,nombre,latitud,longitud) ORDER BY id) FROM {schema}.points;")
    if actual != [list(row) for row in points]:
        raise ValueError("PostgreSQL input rows differ from the CSV")


def measure_gist(args, points, oracle):
    schema = identifier(args.schema)
    with PostgresClient(args.container, args.database, args.docker) as client:
        created = False
        try:
            client.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
            client.execute(f"CREATE SCHEMA {schema};")
            created = True
            create_points(client, schema, points)
            build = client.measure(f"CREATE INDEX points_location_gist ON {schema}.points USING gist (ubicacion)")
            client.execute(f"ANALYZE {schema}.points;")
            calibration = client.json("SELECT json_build_object('radius',ST_Distance('SRID=4326;POINT(0 0)'::geography,'SRID=4326;POINT(1 0)'::geography,false)/radians(1));")
            if abs(calibration["radius"] - EARTH_RADIUS_METRES) > 1e-6:
                raise ValueError("PostGIS spherical radius differs from the declared metric")
            plans = {}
            def query(center, kind, value, *, preflight=False):
                sql = query_sql(schema, center, kind, value)
                key = center, kind, value
                if preflight:
                    plan = client.explain(sql, analyze=True)
                    if not uses_gist(plan["Plan"]):
                        raise ValueError("PostgreSQL did not use the requested GiST index")
                    plans[key] = plan["Plan"]
                result = client.measure(sql, returns_rows=True)
                return result["rows"], {"access": "GiST", "server_seconds": result["server_seconds"],
                                         "measured_elapsed_seconds": result["elapsed_seconds"], "plan": plans[key]}
            resources = measure_settings("gist", args.size, oracle["centers"], oracle["references"], points,
                                         query, args.output, client.resources)
            disk = client.json(f"SELECT json_build_object('data_bytes',pg_table_size('{schema}.points'), 'index_bytes',pg_relation_size('{schema}.points_location_gist'), 'primary_index_bytes',pg_relation_size('{schema}.points_pkey'));")
            return {"method": "gist", "size": args.size, "build_seconds": build["elapsed_seconds"],
                    "build_server_seconds": build["server_seconds"], "build_includes": "CREATE INDEX persistence and client transport; input load excluded",
                    **disk, "peak_rss_bytes": peak_rss_bytes(resources.pop("status")),
                    "memory_scope": "isolated PostgreSQL backend lifetime peak RSS; shared mappings included",
                    "postgres_resources": resources, "calibration": calibration,
                    "query_count_per_setting": len(oracle["centers"]),
                    "selector": "enable_seqscan=off, enable_bitmapscan=off, max_parallel_workers_per_gather=0, jit=off",
                    "preflight": "all query centers before timing each setting; same order repeated once"}
        finally:
            if created:
                if client.process.poll() is None:
                    client.execute(f"DROP SCHEMA {schema} CASCADE;")
                else:
                    with PostgresClient(args.container, args.database, args.docker) as cleanup:
                        cleanup.execute(f"DROP SCHEMA {schema} CASCADE;")
