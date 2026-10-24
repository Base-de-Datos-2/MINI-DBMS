"""Explicit maintenance command: python -m tests.text.freeze_expected.

Never called by tests. Review changes to inputs, numerical anchors and frozen
outputs together; fixture hashes are provenance, not proof of correctness.
"""

from hashlib import sha256
import json
from pathlib import Path

from tests.text.reference import PRECISION, frozen_statistics, rank


DIRECTORY = Path(__file__).with_name("fixtures")


def _read(name):
    return json.loads((DIRECTORY / name).read_text(encoding="utf-8"))


def _results(documents, tokens, model, order="score_desc", limit=None):
    return [{"id": identifier, "score": format(score, ".17g")}
            for identifier, score in rank(documents, tokens, model, order, limit)]


def main():
    collections = _read("collections.v1.json")["collections"]
    cases = _read("queries.v1.json")["cases"]
    worked = _read("worked_example.v1.json")
    expected = {
        "format_version": 1,
        "reference": {"arithmetic": "decimal", "precision": PRECISION},
        "collections": {
            name: frozen_statistics(collection["documents"])
            for name, collection in collections.items()
        },
        "queries": {
            case["id"]: _results(collections[case["collection"]]["documents"],
                                  case["tokens"], case["model"], case["order"], case["limit"])
            for case in cases
        },
        "worked_example": {
            "statistics": frozen_statistics(worked["documents"]),
            "queries": {
                case["id"]: {
                    model: _results(worked["documents"], case["tokens"], model)
                    for model in ("TF_IDF", "BM25")
                }
                for case in worked["queries"]
            },
        },
    }
    output = DIRECTORY / "expected.v1.json"
    output.write_text(json.dumps(expected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    names = ("collections.v1.json", "queries.v1.json", "invalid_documents.v1.json",
             "worked_example.v1.json", "expected.v1.json")
    manifest = {
        "format_version": 1,
        "fixture_version": "text-contract-v1",
        "ranking": {"tfidf": "log-tf-smoothed-idf-cosine-v1", "bm25": "positive-idf-distinct-query-v1",
                    "k1": "1.2", "b": "0.75", "score_rel_tol": "1e-10", "score_abs_tol": "1e-12"},
        "sha256": {name: sha256((DIRECTORY / name).read_bytes()).hexdigest() for name in names},
    }
    (DIRECTORY / "manifest.v1.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n",
    )


if __name__ == "__main__":
    main()
