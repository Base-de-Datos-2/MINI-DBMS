"""Persistent psql session for isolated external comparator experiments."""

import json
import re
import subprocess
from threading import Timer
from time import perf_counter
from uuid import uuid4


def identifier(value):
    if type(value) is not str or re.fullmatch(r"[a-z][a-z_0-9]{0,62}", value) is None:
        raise ValueError("Comparator identifiers must be plain lowercase names")
    return value


def literal(value):
    return "'" + value.replace("'", "''") + "'"


class PostgresClient:
    def __init__(self, container, database="minidbms_bench", docker="docker", timeout=120):
        self.timeout = timeout
        self.process = subprocess.Popen(
            [docker, "exec", "-i", container, "psql", "-X", "-w", "-qAt",
             "-v", "ON_ERROR_STOP=1", "-P", "pager=off", "-U", "postgres", "-d", identifier(database)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", bufsize=1,
        )
        try:
            self.execute("SET max_parallel_workers_per_gather=0; SET enable_seqscan=off; SET enable_bitmapscan=off; SET jit=off;")
            self.execute("""
CREATE FUNCTION pg_temp.measure(statement text, returns_rows boolean) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE started timestamptz; result jsonb; elapsed double precision;
BEGIN
  started := clock_timestamp();
  IF returns_rows THEN EXECUTE statement INTO result; ELSE EXECUTE statement; END IF;
  elapsed := extract(epoch FROM clock_timestamp()-started);
  RETURN jsonb_build_object('server_seconds',elapsed,'rows',result);
END $$;
""")
        except BaseException:
            self.close()
            raise

    def execute(self, sql):
        marker = "minidbms_end_" + uuid4().hex
        timer = Timer(self.timeout, self.process.kill)
        timer.daemon = True
        timer.start()
        lines = []
        try:
            self.process.stdin.write(sql.rstrip() + "\n\\echo " + marker + "\n")
            self.process.stdin.flush()
            while True:
                line = self.process.stdout.readline()
                if not line:
                    raise RuntimeError("Comparator psql failed or timed out: " + "\n".join(lines[-8:]))
                if line.rstrip() == marker:
                    return lines
                lines.append(line.rstrip())
        finally:
            timer.cancel()

    def json(self, sql):
        lines = self.execute(sql)
        if len(lines) != 1:
            raise RuntimeError("Expected one comparator JSON row: " + "\n".join(lines[-8:]))
        return json.loads(lines[0])

    def measure(self, sql, *, returns_rows=False):
        started = perf_counter()
        result = self.json(f"SELECT pg_temp.measure({literal(sql)}, {'true' if returns_rows else 'false'});")
        result["elapsed_seconds"] = perf_counter() - started
        return result

    def explain(self, sql, *, analyze=False):
        options = "ANALYZE, TIMING OFF, BUFFERS, FORMAT JSON" if analyze else "FORMAT JSON"
        return json.loads("\n".join(self.execute(f"EXPLAIN ({options}) " + sql + ";")))[0]

    def resources(self):
        return self.json("""SELECT json_build_object(
            'status',pg_read_file('/proc/'||pg_backend_pid()||'/status'),
            'shared_buffers',current_setting('shared_buffers'),
            'work_mem',current_setting('work_mem'),
            'version',version(),'postgis',PostGIS_Full_Version());""")

    def close(self):
        if not self.process.stdin.closed:
            try:
                self.process.stdin.close()
            except OSError:
                pass
        if self.process.poll() is None:
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process.stdout.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
