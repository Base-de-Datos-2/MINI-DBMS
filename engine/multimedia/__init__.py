"""Part 4 multimedia retrieval (docs/multimedia-contract.md).

Contracts (phase 1), feature extraction and the exact vector store (phase 2).
Media decoding, SIFT/MFCC and the vocabulary K-Means are imported lazily by
``features``; ``numpy`` is required by the package.
"""

from .contracts import (
    AudioFeatureParameters, HnswParameters, ImageFeatureParameters, IndexMethod, Metric,
    Modality, Neighbor, TrainingParameters, cosine_similarity, default_ef_search,
    default_nlist, default_nprobe, dot_product, euclidean_distance, exact_top_k,
    idf_weight, l2_norm, media_key_modality, output_size, ranking_key, recall_at_k,
    search_objective, similarity_score, tf_weight, validate_k, validate_vector,
    weighted_histogram,
)
from .features import CollectionFeatures, FeatureExtractionError, FeatureModel
from .vectors import VectorSearchResult, VectorStore

__all__ = [
    "Modality", "Metric", "IndexMethod", "Neighbor",
    "ImageFeatureParameters", "AudioFeatureParameters", "TrainingParameters", "HnswParameters",
    "media_key_modality", "validate_vector", "l2_norm", "euclidean_distance", "dot_product",
    "cosine_similarity", "similarity_score", "search_objective", "ranking_key", "validate_k",
    "output_size", "exact_top_k", "recall_at_k", "tf_weight", "idf_weight", "weighted_histogram",
    "default_nlist", "default_nprobe", "default_ef_search",
    "CollectionFeatures", "FeatureExtractionError", "FeatureModel", "VectorSearchResult", "VectorStore",
]
