"""Part 4 multimedia retrieval: contracts first (phase 1).

Feature extraction, vector storage and the IVF/HNSW indexes are added by
later phases; see docs/multimedia-contract.md and PART_04/PLAN_PARTE_04.md.
"""

from .contracts import (
    AudioFeatureParameters, HnswParameters, ImageFeatureParameters, IndexMethod, Metric,
    Modality, Neighbor, TrainingParameters, cosine_similarity, default_ef_search,
    default_nlist, default_nprobe, dot_product, euclidean_distance, exact_top_k,
    idf_weight, l2_norm, media_key_modality, output_size, ranking_key, recall_at_k,
    search_objective, similarity_score, tf_weight, validate_k, validate_vector,
    weighted_histogram,
)

__all__ = [
    "Modality", "Metric", "IndexMethod", "Neighbor",
    "ImageFeatureParameters", "AudioFeatureParameters", "TrainingParameters", "HnswParameters",
    "media_key_modality", "validate_vector", "l2_norm", "euclidean_distance", "dot_product",
    "cosine_similarity", "similarity_score", "search_objective", "ranking_key", "validate_k",
    "output_size", "exact_top_k", "recall_at_k", "tf_weight", "idf_weight", "weighted_histogram",
    "default_nlist", "default_nprobe", "default_ef_search",
]
