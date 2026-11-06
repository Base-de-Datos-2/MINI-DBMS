"""Part 4 contracts frozen in phase 1 (docs/multimedia-contract.md).

Pure-Python reference definitions shared by the later numeric pipeline,
IVF/HNSW indexes, SQL binding and benchmarks:

* modalities, registered media keys and their file extensions;
* the three measures, the returned ``SIMILARITY_SCORE()`` (higher is always
  better) and the internal lower-is-better search objective;
* best-first ordering (score DESC, id ASC), k validation and output size;
* bag-of-words TF-IDF weights;
* starting feature/index parameters, frozen before the pilot.

The functions use ``math.fsum`` and plain sequences on purpose: they are the
independent scalar oracle that the vectorized implementation is checked
against, not the fast path.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import math
import re

from engine.errors import InvalidTypeError, ValidationError


CONTRACT_VERSION = 1


class Modality(Enum):
    """A collection holds one modality; vector spaces are never mixed."""

    IMAGE = "image"
    AUDIO = "audio"


class Metric(Enum):
    """``WITH METRIC=<name>``; SQL spelling is case-insensitive."""

    EUCLIDEAN = "euclidean"
    DOT = "dot"
    COSINE = "cosine"

    @classmethod
    def from_sql(cls, name: str) -> "Metric":
        if type(name) is not str:
            raise InvalidTypeError("Metric name must be a string")
        try:
            return cls(name.lower())
        except ValueError:
            raise ValidationError(
                f"Unknown metric {name!r}; expected euclidean, dot or cosine"
            ) from None


class IndexMethod(Enum):
    """``USING <method>``; SQL spelling is case-insensitive."""

    IVF = "IVF"
    HNSW = "HNSW"

    @classmethod
    def from_sql(cls, name: str) -> "IndexMethod":
        if type(name) is not str:
            raise InvalidTypeError("Index method must be a string")
        try:
            return cls(name.upper())
        except ValueError:
            raise ValidationError(
                f"Unknown vector index {name!r}; expected IVF or HNSW"
            ) from None


# Plan node names shown by EXPLAIN and the interface.
VECTOR_INDEX_SCAN = "VectorIndexScan"
VECTOR_SCAN = "VectorScan"


# --- Registered media keys -------------------------------------------------

MEDIA_EXTENSIONS: Mapping[Modality, frozenset[str]] = {
    Modality.IMAGE: frozenset({".jpg", ".jpeg", ".png"}),
    Modality.AUDIO: frozenset({".wav", ".mp3"}),
}
MAX_MEDIA_KEY_LENGTH = 128
# Declared VARCHAR bound for nombre/artista in imagenes/canciones. With the
# 4-byte UTF-8 worst case, the widest row (canciones) stays far below the
# 4,079-byte record limit; Heap insertion remains authoritative.
MAX_METADATA_TEXT_LENGTH = 200
_MEDIA_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def media_key_modality(key: str, expected: Modality | None = None) -> Modality:
    """Validate a registered media key and return its modality.

    A key is a single file name resolved by the owner inside a registered
    collection/query directory. Paths, URLs, traversal and hidden names are
    rejected here, before any filesystem access.
    """
    if type(key) is not str:
        raise InvalidTypeError("Media key must be a string")
    if not 1 <= len(key) <= MAX_MEDIA_KEY_LENGTH or _MEDIA_KEY.fullmatch(key) is None:
        raise ValidationError(
            "Media key must be a registered file name: letters, digits, '.', '_' "
            f"or '-', at most {MAX_MEDIA_KEY_LENGTH} characters, no path"
        )
    if ".." in key:
        raise ValidationError("Media key must not contain '..'")
    dot = key.rfind(".")
    extension = key[dot:].lower() if dot > 0 else ""
    for modality, extensions in MEDIA_EXTENSIONS.items():
        if extension in extensions:
            if expected is not None and modality is not expected:
                raise ValidationError(
                    f"Media key {key!r} is {modality.value}; the collection is "
                    f"{expected.value}"
                )
            return modality
    raise ValidationError(f"Unsupported media extension in {key!r}")


# --- Vectors, measures and scores ------------------------------------------

def validate_vector(values: Sequence[float], dimension: int | None = None) -> tuple[float, ...]:
    """Return a finite, nonzero-norm vector as floats; never coerce silently.

    Zero-norm vectors have no direction (cosine undefined) and only arise when
    an object has no usable descriptors, which feature extraction rejects.
    """
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise InvalidTypeError("Vector must be a sequence of numbers")
    if dimension is not None and (type(dimension) is not int or dimension < 1):
        raise InvalidTypeError("Vector dimension must be a positive integer")
    result = []
    for value in values:
        if type(value) not in (int, float):
            raise InvalidTypeError("Vector components must be int or float")
        number = float(value)
        if not math.isfinite(number):
            raise ValidationError("Vector components must be finite")
        result.append(number)
    if not result:
        raise ValidationError("Vector must not be empty")
    if dimension is not None and len(result) != dimension:
        raise ValidationError(f"Vector has dimension {len(result)}; expected {dimension}")
    if l2_norm(result) == 0.0:
        raise ValidationError("Zero-norm vectors cannot be indexed or queried")
    return tuple(result)


def _pair(x: Sequence[float], q: Sequence[float]) -> None:
    if len(x) != len(q):
        raise ValidationError(f"Vector dimensions differ: {len(x)} and {len(q)}")


def l2_norm(x: Sequence[float]) -> float:
    return math.sqrt(math.fsum(value * value for value in x))


def euclidean_distance(x: Sequence[float], q: Sequence[float]) -> float:
    _pair(x, q)
    return math.sqrt(math.fsum((a - b) * (a - b) for a, b in zip(x, q)))


def dot_product(x: Sequence[float], q: Sequence[float]) -> float:
    _pair(x, q)
    return math.fsum(a * b for a, b in zip(x, q))


def cosine_similarity(x: Sequence[float], q: Sequence[float]) -> float:
    _pair(x, q)
    denominator = l2_norm(x) * l2_norm(q)
    if denominator == 0.0:
        raise ValidationError("Cosine similarity is undefined for a zero-norm vector")
    return dot_product(x, q) / denominator


def similarity_score(metric: Metric, x: Sequence[float], q: Sequence[float]) -> float:
    """``SIMILARITY_SCORE()``: higher always means a better match.

    euclidean -> -distance (so ``ORDER BY score DESC`` is nearest first),
    dot -> dot product, cosine -> cosine similarity. Scores are not
    probabilities and are not comparable across metrics or modalities.
    """
    if metric is Metric.EUCLIDEAN:
        return 0.0 - euclidean_distance(x, q)      # 0.0, never -0.0, for identical vectors
    if metric is Metric.DOT:
        return dot_product(x, q)
    if metric is Metric.COSINE:
        return cosine_similarity(x, q)
    raise InvalidTypeError("metric must be a Metric")


def search_objective(metric: Metric, x: Sequence[float], q: Sequence[float]) -> float:
    """Internal lower-is-better objective used by IVF routing and HNSW.

    euclidean -> squared distance, dot -> -dot, cosine -> 1 - cosine. It
    orders candidates exactly like the score (ties aside); dot is not a
    metric distance, so graph search on it is heuristic.
    """
    if metric is Metric.EUCLIDEAN:
        _pair(x, q)
        return math.fsum((a - b) * (a - b) for a, b in zip(x, q))
    if metric is Metric.DOT:
        return -dot_product(x, q)
    if metric is Metric.COSINE:
        return 1.0 - cosine_similarity(x, q)
    raise InvalidTypeError("metric must be a Metric")


def ranking_key(score: float, object_id: int) -> tuple[float, int]:
    """Best-first order: score DESC, then the stable object id ASC."""
    return (-score, object_id)


def validate_k(k: int) -> int:
    if type(k) is not int:
        raise InvalidTypeError("k must be an integer")
    if k < 1:
        raise ValidationError("k must be a positive integer")
    return k


def output_size(k: int, limit: int | None, collection_size: int) -> int:
    """Rows returned: min(k, LIMIT, N). LIMIT never widens or replaces k."""
    validate_k(k)
    if limit is not None and (type(limit) is not int or limit < 0):
        raise ValidationError("LIMIT must be a nonnegative integer")
    if type(collection_size) is not int or collection_size < 0:
        raise ValidationError("Collection size must be a nonnegative integer")
    return min(k, collection_size) if limit is None else min(k, limit, collection_size)


@dataclass(frozen=True, slots=True)
class Neighbor:
    object_id: int
    score: float


def exact_top_k(items: Iterable[tuple[int, Sequence[float]]], query: Sequence[float],
                metric: Metric, k: int) -> tuple[Neighbor, ...]:
    """Exhaustive reference ranking over (object_id, vector) pairs.

    Recall@10 compares an index against this order computed on the same
    stored vectors. Duplicate ids are rejected rather than deduplicated.
    """
    validate_k(k)
    query = validate_vector(query)
    seen = set()
    scored = []
    for object_id, vector in items:
        if type(object_id) is not int:
            raise InvalidTypeError("Object ids must be integers")
        if object_id in seen:
            raise ValidationError(f"Duplicate object id {object_id}")
        seen.add(object_id)
        vector = validate_vector(vector, len(query))
        scored.append(Neighbor(object_id, similarity_score(metric, vector, query)))
    scored.sort(key=lambda item: ranking_key(item.score, item.object_id))
    return tuple(scored[:k])


def recall_at_k(approximate: Sequence[int], exact: Sequence[int], k: int = 10) -> float:
    """|approximate top-k ∩ exact top-k| / min(k, |exact|)."""
    validate_k(k)
    reference = list(exact[:k])
    if len(set(reference)) != len(reference) or len(set(approximate[:k])) != len(approximate[:k]):
        raise ValidationError("Recall inputs must not repeat ids")
    if not reference:
        raise ValidationError("Recall needs at least one exact neighbor")
    return len(set(approximate[:k]) & set(reference)) / len(reference)


# --- Bag of visual/audio words ---------------------------------------------

def tf_weight(count: int) -> float:
    """1 + ln(count) for a positive word count, else 0."""
    if type(count) is not int or count < 0:
        raise ValidationError("Word counts must be nonnegative integers")
    return 1.0 + math.log(count) if count > 0 else 0.0


def idf_weight(collection_size: int, document_frequency: int) -> float:
    """ln((N + 1) / (df + 1)) + 1, with df counted per object."""
    if type(collection_size) is not int or collection_size < 1:
        raise ValidationError("Collection size must be a positive integer")
    if type(document_frequency) is not int or not 0 <= document_frequency <= collection_size:
        raise ValidationError("Document frequency must be between 0 and N")
    return math.log((collection_size + 1) / (document_frequency + 1)) + 1.0


def weighted_histogram(counts: Sequence[int], document_frequencies: Sequence[int],
                       collection_size: int) -> tuple[float, ...]:
    """x_j = tf(h_j) * idf_j over the K vocabulary dimensions (unnormalized)."""
    if len(counts) != len(document_frequencies):
        raise ValidationError("Histogram and document frequencies differ in size")
    if not counts:
        raise ValidationError("Vocabulary must have at least one word")
    return tuple(tf_weight(h) * idf_weight(collection_size, df)
                 for h, df in zip(counts, document_frequencies))


# --- Starting parameters (frozen after the pilot, never tuned on final queries)

@dataclass(frozen=True, slots=True)
class ImageFeatureParameters:
    max_side: int = 512          # longest side after aspect-preserving resize
    grayscale: bool = True
    max_descriptors: int = 256   # strongest SIFT keypoints kept per image
    vocabulary_size: int = 256   # K visual words


@dataclass(frozen=True, slots=True)
class AudioFeatureParameters:
    sample_rate: int = 22_050
    mono: bool = True
    max_duration_seconds: float = 30.0   # longer clips are rejected, never cut silently
    n_mfcc: int = 20
    n_fft: int = 2_048
    hop_length: int = 512
    vocabulary_size: int = 64            # K audio words


@dataclass(frozen=True, slots=True)
class TrainingParameters:
    seed: int = 20_261_106
    max_training_descriptors: int = 100_000
    kmeans_restarts: int = 3
    kmeans_max_iterations: int = 100


@dataclass(frozen=True, slots=True)
class HnswParameters:
    m: int = 16
    m0: int = 32                 # base-layer degree cap (2M)
    ef_construction: int = 100
    min_ef_search: int = 64


def default_nlist(collection_size: int) -> int:
    """IVF coarse lists: min(N, max(1, round(sqrt(N))))."""
    if type(collection_size) is not int or collection_size < 1:
        raise ValidationError("Collection size must be a positive integer")
    return min(collection_size, max(1, round(math.sqrt(collection_size))))


def default_nprobe(nlist: int) -> int:
    if type(nlist) is not int or nlist < 1:
        raise ValidationError("nlist must be a positive integer")
    return min(8, nlist)


def default_ef_search(k: int, parameters: HnswParameters = HnswParameters()) -> int:
    return max(parameters.min_ef_search, validate_k(k))


__all__ = [
    "Modality", "Metric", "IndexMethod", "Neighbor",
    "ImageFeatureParameters", "AudioFeatureParameters", "TrainingParameters", "HnswParameters",
    "media_key_modality", "validate_vector", "l2_norm", "euclidean_distance", "dot_product",
    "cosine_similarity", "similarity_score", "search_objective", "ranking_key", "validate_k",
    "output_size", "exact_top_k", "recall_at_k", "tf_weight", "idf_weight", "weighted_histogram",
    "default_nlist", "default_nprobe", "default_ef_search",
]
