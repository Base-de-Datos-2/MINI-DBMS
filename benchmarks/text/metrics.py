"""Precision@10/Recall@10 over frozen qrels, independent of any ranking engine.

Positives are judgments with grade > 0 whose document belongs to the measured
subset. Precision keeps denominator 10 even with fewer results. A query with
no positive in the subset has no defined recall: it is reported as not
evaluable instead of being counted as zero.
"""

from __future__ import annotations

import csv
from pathlib import Path

CUTOFF = 10


def read_qrels(path) -> dict[int, dict[int, int]]:
    """Read TREC qrels ``query 0 document grade``; duplicates are rejected."""
    judgments: dict[int, dict[int, int]] = {}
    with Path(path).open(encoding="utf-8", newline="") as source:
        for row in csv.reader(source, delimiter="\t"):
            if len(row) != 4 or row[1] != "0":
                raise ValueError(f"Malformed qrels row: {row!r}")
            query, document, grade = int(row[0]), int(row[2]), int(row[3])
            if document in judgments.setdefault(query, {}):
                raise ValueError(f"Duplicate judgment for query {query}, document {document}")
            judgments[query][document] = grade
    return judgments


def positives(judgments: dict[int, int], documents: set[int] | None = None) -> set[int]:
    return {document for document, grade in judgments.items()
            if grade > 0 and (documents is None or document in documents)}


def precision_at_k(ranking, relevant, k=CUTOFF) -> float:
    if k <= 0:
        raise ValueError("k must be positive")
    top = list(ranking)[:k]
    if len(set(top)) != len(top):
        raise ValueError("A ranking cannot repeat a document")
    return sum(document in relevant for document in top) / k


def recall_at_k(ranking, relevant, k=CUTOFF) -> float | None:
    if not relevant:
        return None
    top = list(ranking)[:k]
    if len(set(top)) != len(top):
        raise ValueError("A ranking cannot repeat a document")
    return sum(document in relevant for document in top) / len(relevant)


def evaluate(ranking, relevant, k=CUTOFF) -> dict:
    return {"precision_at_10": precision_at_k(ranking, relevant, k),
            "recall_at_10": recall_at_k(ranking, relevant, k),
            "relevant_in_subset": len(relevant),
            "relevant_retrieved": sum(document in relevant for document in list(ranking)[:k]),
            "returned": min(len(list(ranking)), k)}


def mean(values) -> float | None:
    """Mean of defined values only; None when no value is defined."""
    defined = [value for value in values if value is not None]
    return sum(defined) / len(defined) if defined else None
