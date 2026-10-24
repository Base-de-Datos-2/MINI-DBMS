"""Small exhaustive Decimal reference for frozen fixtures, never engine code.

Inputs are manually specified token sequences. This module imports neither the
production tokenizer nor a text index/ranker; tokenizer agreement is tested
separately. It deliberately retains the entire tiny fixture in memory.
"""

from collections import Counter
from decimal import Decimal, localcontext


PRECISION = 60
SCORE_REL_TOL = 1e-10
SCORE_ABS_TOL = 1e-12


def collection_statistics(documents):
    """Compute frequencies and whole-vector norms, including tokenless rows."""
    with localcontext() as context:
        context.prec = PRECISION
        frequencies = {}
        for document in documents:
            identifier = document["id"]
            if type(identifier) is not int:
                raise TypeError("Document ID must be an integer")
            if identifier in frequencies:
                raise ValueError("Duplicate document ID")
            frequencies[identifier] = Counter(document["tokens"])
        count = len(frequencies)
        df = Counter(term for counts in frequencies.values() for term in counts)
        lengths = {identifier: sum(counts.values()) for identifier, counts in frequencies.items()}
        total = sum(lengths.values())
        idf = {
            term: (Decimal(count + 1) / Decimal(frequency + 1)).ln() + 1
            for term, frequency in sorted(df.items())
        }
        weights = {
            identifier: {
                term: (1 + Decimal(frequency).ln()) * idf[term]
                for term, frequency in sorted(counts.items())
            }
            for identifier, counts in frequencies.items()
        }
        norms = {
            identifier: sum((weight * weight for weight in vector.values()), Decimal(0)).sqrt()
            for identifier, vector in weights.items()
        }
        return {
            "N": count, "df": dict(sorted(df.items())), "lengths": lengths,
            "total_tokens": total,
            "avgdl": Decimal(total) / count if count else Decimal(0),
            "frequencies": frequencies, "idf": idf, "weights": weights, "norms": norms,
        }


def rank(documents, tokens, model, order="score_desc", limit=None):
    """Evaluate an OR query by examining every document, then order and limit."""
    if model not in {"TF_IDF", "BM25"}:
        raise ValueError("Unknown ranking model")
    if order not in {"score_desc", "score_asc", "id_asc", "id_desc"}:
        raise ValueError("Unknown result order")
    if limit is not None and (type(limit) is not int or limit < 0):
        raise ValueError("LIMIT must be a nonnegative integer")
    with localcontext() as context:
        context.prec = PRECISION
        stats = collection_statistics(documents)
        query = Counter(term for term in tokens if term in stats["df"])
        query_weights = {
            term: (1 + Decimal(frequency).ln()) * stats["idf"][term]
            for term, frequency in sorted(query.items())
        }
        query_norm = sum((weight * weight for weight in query_weights.values()), Decimal(0)).sqrt()
        results = []
        for identifier, counts in stats["frequencies"].items():
            matched = sorted(query.keys() & counts.keys())
            if not matched:
                continue
            if model == "TF_IDF":
                denominator = stats["norms"][identifier] * query_norm
                if not denominator:
                    continue
                score = sum(
                    (stats["weights"][identifier][term] * query_weights[term] for term in matched),
                    Decimal(0),
                ) / denominator
            else:
                if not stats["avgdl"]:
                    continue
                k1, b = Decimal("1.2"), Decimal("0.75")
                score = Decimal(0)
                for term in matched:
                    frequency = Decimal(counts[term])
                    df = Decimal(stats["df"][term])
                    inverse_frequency = (
                        1 + (Decimal(stats["N"]) - df + Decimal("0.5")) / (df + Decimal("0.5"))
                    ).ln()
                    denominator = frequency + k1 * (
                        1 - b + b * Decimal(stats["lengths"][identifier]) / stats["avgdl"]
                    )
                    score += inverse_frequency * frequency * (k1 + 1) / denominator
            results.append((identifier, score))
        keys = {
            "score_desc": lambda pair: (-pair[1], pair[0]),
            "score_asc": lambda pair: (pair[1], pair[0]),
            "id_asc": lambda pair: pair[0],
            "id_desc": lambda pair: -pair[0],
        }
        results.sort(key=keys[order])
        return results if limit is None else results[:limit]


def frozen_statistics(documents):
    """JSON representation of the reference statistics, to 17 significant digits."""
    stats = collection_statistics(documents)
    return {
        "N": stats["N"], "total_tokens": stats["total_tokens"],
        "avgdl": format(stats["avgdl"], ".17g"),
        "vocabulary": list(stats["df"]), "df": stats["df"],
        "documents": {
            str(identifier): {
                "tf": dict(sorted(stats["frequencies"][identifier].items())),
                "length": stats["lengths"][identifier],
                "norm": format(stats["norms"][identifier], ".17g"),
            }
            for identifier in sorted(stats["frequencies"])
        },
        "idf": {term: format(weight, ".17g") for term, weight in stats["idf"].items()},
    }
