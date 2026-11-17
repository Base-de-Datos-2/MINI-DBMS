"""Check the new practice datasets through a running extended unified server."""

import argparse
import json
from urllib.request import Request, urlopen


def check(base):
    def query(part, sql):
        request = Request(f"{base}/parte{part}/api/query",
                          data=json.dumps({"sql": sql, "max_rows": 50}).encode(),
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=60) as response:
            return json.load(response)["rows"]

    with urlopen(f"{base}/api/parts", timeout=10) as response:
        parts = json.load(response)
    if [p["id"] for p in parts if p["status"] == "ready"] != [f"parte{i}" for i in range(1, 6)]:
        raise ValueError("Expected five ready parts")

    for ranking in ("TF_IDF", "BM25"):
        rows = query(3, f"SELECT id FROM documentos WHERE MATCH(contenido, 'Colca') USING {ranking} LIMIT 10;")
        if {row[0] for row in rows} != {37, 38, 39}:
            raise ValueError(f"{ranking}: unexpected Colca results: {rows}")

    for table, filename, index, metric in (
        ("imagenes", "consulta_rombos.png", "HNSW", "cosine"),
        ("canciones", "consulta_motivo.wav", "IVF", "euclidean"),
    ):
        rows = query(4, f"SELECT id FROM {table} WHERE SIMILAR_TO('{filename}', k=5) "
                        f"USING {index} WITH METRIC={metric};")
        if len({row[0] for row in rows}) != 5:
            raise ValueError(f"{index}: expected five different neighbors: {rows}")
        with urlopen(f"{base}/parte4/api/multimedia/{table}/media/{filename}", timeout=10) as response:
            prefix = response.read(4)
        if prefix != (b"RIFF" if table == "canciones" else b"\x89PNG"):
            raise ValueError(f"Unexpected media content for {filename}")

    for paper_id in (11, 12, 13):
        papers = query(5, f"SELECT title FROM papers WHERE paper_id = {paper_id};")
        chunks = query(5, f"SELECT content FROM chunks WHERE paper_id = {paper_id} LIMIT 1;")
        if len(papers) != 1 or not chunks or not 200 <= len(chunks[0][0].split()) <= 500:
            raise ValueError(f"Incomplete paper or passage for paper {paper_id}")
    print("Five parts ready; both text rankings, media searches, media files and extra papers passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    check(parser.parse_args().base_url.rstrip("/"))
