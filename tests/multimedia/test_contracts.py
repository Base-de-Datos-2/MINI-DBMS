"""Part 4 phase-1 contracts: measures, scores, ordering, k and TF-IDF."""

import math

import pytest

from engine.errors import InvalidTypeError, ValidationError
from engine.multimedia import (
    AudioFeatureParameters, HnswParameters, ImageFeatureParameters, IndexMethod, Metric,
    Modality, Neighbor, TrainingParameters, cosine_similarity, default_ef_search,
    default_nlist, default_nprobe, dot_product, euclidean_distance, exact_top_k, idf_weight,
    media_key_modality, output_size, ranking_key, recall_at_k, search_objective,
    similarity_score, tf_weight, validate_k, validate_vector, weighted_histogram,
)
from engine.multimedia.contracts import MAX_MEDIA_KEY_LENGTH


# Rankings of these three objects differ under each measure for QUERY.
QUERY = (1.0, 0.0)
OBJECTS = {1: (10.0, 10.0), 2: (1.0, 0.1), 3: (0.5, 0.0)}


def order(metric):
    return [n.object_id for n in exact_top_k(OBJECTS.items(), QUERY, metric, 3)]


def test_the_three_measures_give_three_different_orders():
    assert order(Metric.EUCLIDEAN) == [2, 3, 1]
    assert order(Metric.DOT) == [1, 2, 3]
    assert order(Metric.COSINE) == [3, 2, 1]


def test_scores_match_independent_formulas_and_higher_is_better():
    x, q = OBJECTS[1], QUERY
    assert similarity_score(Metric.EUCLIDEAN, x, q) == pytest.approx(-math.sqrt(81 + 100))
    assert similarity_score(Metric.DOT, x, q) == pytest.approx(10.0)
    assert similarity_score(Metric.COSINE, x, q) == pytest.approx(10 / (math.sqrt(200) * 1))
    euclidean = exact_top_k(OBJECTS.items(), QUERY, Metric.EUCLIDEAN, 3)
    assert all(n.score <= 0 for n in euclidean)
    assert [n.score for n in euclidean] == sorted((n.score for n in euclidean), reverse=True)


@pytest.mark.parametrize("metric", list(Metric))
def test_search_objective_orders_exactly_like_the_score(metric):
    by_score = sorted(OBJECTS, key=lambda i: -similarity_score(metric, OBJECTS[i], QUERY))
    by_objective = sorted(OBJECTS, key=lambda i: search_objective(metric, OBJECTS[i], QUERY))
    assert by_score == by_objective


def test_objectives_are_squared_distance_negative_dot_and_one_minus_cosine():
    x, q = (3.0, 4.0), (0.0, 1.0)
    assert search_objective(Metric.EUCLIDEAN, x, q) == pytest.approx(euclidean_distance(x, q) ** 2)
    assert search_objective(Metric.DOT, x, q) == pytest.approx(-dot_product(x, q))
    assert search_objective(Metric.COSINE, x, q) == pytest.approx(1 - cosine_similarity(x, q))


def test_unit_vectors_make_euclidean_and_cosine_rank_identically():
    # Why raw vectors are kept: normalizing everything would make the required
    # Euclidean-versus-cosine comparison trivial (||x-q||^2 = 2 - 2 cos).
    unit = {i: tuple(c / math.hypot(*v) for c in v) for i, v in OBJECTS.items()}
    for v in unit.values():
        assert euclidean_distance(v, QUERY) ** 2 == pytest.approx(2 - 2 * cosine_similarity(v, QUERY))
    assert ([n.object_id for n in exact_top_k(unit.items(), QUERY, Metric.EUCLIDEAN, 3)]
            == [n.object_id for n in exact_top_k(unit.items(), QUERY, Metric.COSINE, 3)])


def test_equal_scores_break_ties_by_ascending_id():
    items = [(9, (1.0, 1.0)), (4, (1.0, 1.0)), (7, (2.0, 2.0))]
    result = exact_top_k(items, (1.0, 1.0), Metric.COSINE, 3)
    assert [n.object_id for n in result] == [4, 7, 9]
    assert ranking_key(0.5, 3) < ranking_key(0.5, 8) < ranking_key(0.4, 1)


def test_k_larger_than_collection_returns_every_object_once():
    result = exact_top_k(OBJECTS.items(), QUERY, Metric.DOT, 50)
    assert len(result) == 3 and len({n.object_id for n in result}) == 3
    assert isinstance(result[0], Neighbor)


@pytest.mark.parametrize("k", [0, -1])
def test_nonpositive_k_is_rejected(k):
    with pytest.raises(ValidationError, match="positive"):
        validate_k(k)


@pytest.mark.parametrize("k", [True, 1.0, "10", None])
def test_k_is_never_coerced(k):
    with pytest.raises(InvalidTypeError):
        validate_k(k)


def test_exact_reference_rejects_duplicates_dimension_mismatch_and_bad_vectors():
    with pytest.raises(ValidationError, match="Duplicate"):
        exact_top_k([(1, (1.0, 0.0)), (1, (0.0, 1.0))], QUERY, Metric.DOT, 1)
    with pytest.raises(ValidationError, match="dimension"):
        exact_top_k([(1, (1.0, 0.0, 0.0))], QUERY, Metric.DOT, 1)
    with pytest.raises(ValidationError, match="Zero-norm"):
        exact_top_k([(1, (0.0, 0.0))], QUERY, Metric.DOT, 1)
    with pytest.raises(ValidationError, match="Zero-norm"):
        exact_top_k([(1, (1.0, 0.0))], (0.0, 0.0), Metric.DOT, 1)
    with pytest.raises(InvalidTypeError):
        exact_top_k([("1", (1.0, 0.0))], QUERY, Metric.DOT, 1)


@pytest.mark.parametrize("vector", [(math.nan, 1.0), (math.inf, 1.0), (-math.inf, 0.0)])
def test_non_finite_components_are_rejected(vector):
    with pytest.raises(ValidationError, match="finite"):
        validate_vector(vector)


@pytest.mark.parametrize("vector", [(True, 1.0), ("1", 1.0), (None,), "12", b"12", {1.0}])
def test_vectors_are_never_coerced(vector):
    with pytest.raises(InvalidTypeError):
        validate_vector(vector)


def test_valid_vectors_become_float_tuples_of_the_declared_dimension():
    assert validate_vector([1, 2.5], 2) == (1.0, 2.5)
    with pytest.raises(ValidationError, match="empty"):
        validate_vector([])
    with pytest.raises(ValidationError, match="expected 3"):
        validate_vector([1.0, 2.0], 3)


@pytest.mark.parametrize("k, limit, n, expected", [
    (10, None, 1000, 10), (10, 3, 1000, 3), (10, 50, 1000, 10),
    (10, None, 4, 4), (5, 0, 100, 0), (5, 2, 1, 1),
])
def test_output_size_is_min_of_k_limit_and_n(k, limit, n, expected):
    assert output_size(k, limit, n) == expected


def test_output_size_rejects_invalid_limit_and_k():
    with pytest.raises(ValidationError):
        output_size(10, -1, 5)
    with pytest.raises(ValidationError):
        output_size(0, None, 5)


def test_recall_uses_exact_top_k_as_denominator():
    exact = list(range(10))
    assert recall_at_k([0, 1, 2, 3, 4, 5, 6, 7, 8, 99], exact) == 0.9
    assert recall_at_k([3, 2, 1], [1, 2, 3]) == 1.0          # N < 10: min(10, N)
    assert recall_at_k([], exact) == 0.0
    with pytest.raises(ValidationError, match="repeat"):
        recall_at_k([1, 1], exact)
    with pytest.raises(ValidationError, match="at least one"):
        recall_at_k([1], [])


def test_tf_idf_histogram_matches_hand_computation():
    # Three words, N=4 objects: counts in one object and df across objects.
    vector = weighted_histogram([0, 1, 3], [0, 2, 4], 4)
    assert vector[0] == 0.0
    assert vector[1] == pytest.approx(1.0 * (math.log(5 / 3) + 1))
    assert vector[2] == pytest.approx((1 + math.log(3)) * 1.0)    # word in every object: idf 1
    assert tf_weight(0) == 0.0 and tf_weight(1) == 1.0
    assert idf_weight(4, 0) == pytest.approx(math.log(5) + 1)


@pytest.mark.parametrize("counts, dfs, n", [
    ([1, -1], [1, 1], 2), ([1, 1], [3, 1], 2), ([1], [1, 1], 2), ([], [], 2), ([1], [1], 0),
])
def test_invalid_histogram_inputs_are_rejected(counts, dfs, n):
    with pytest.raises(ValidationError):
        weighted_histogram(counts, dfs, n)


def test_sql_names_parse_case_insensitively_and_unknown_names_fail():
    assert Metric.from_sql("COSINE") is Metric.COSINE
    assert Metric.from_sql("euclidean") is Metric.EUCLIDEAN
    assert IndexMethod.from_sql("hnsw") is IndexMethod.HNSW
    with pytest.raises(ValidationError, match="Unknown metric"):
        Metric.from_sql("manhattan")
    with pytest.raises(ValidationError, match="Unknown vector index"):
        IndexMethod.from_sql("PQ")
    with pytest.raises(InvalidTypeError):
        Metric.from_sql(None)


@pytest.mark.parametrize("key, modality", [
    ("foto_consulta.jpg", Modality.IMAGE), ("audio_query.mp3", Modality.AUDIO),
    ("000000000009.jpg", Modality.IMAGE), ("Clip-01.WAV", Modality.AUDIO),
    ("scene.a.png", Modality.IMAGE), ("x.jpeg", Modality.IMAGE),
])
def test_registered_media_keys_resolve_their_modality(key, modality):
    assert media_key_modality(key) is modality
    assert media_key_modality(key, modality) is modality


@pytest.mark.parametrize("key", [
    "", "../x.jpg", "a/b.jpg", "a\\b.jpg", "http://host/a.jpg", ".hidden.jpg", "a..jpg",
    "C:x.jpg", "a b.jpg", "x" * (MAX_MEDIA_KEY_LENGTH - 3) + ".jpg",
])
def test_paths_urls_and_traversal_are_rejected_before_filesystem_access(key):
    with pytest.raises(ValidationError):
        media_key_modality(key)


@pytest.mark.parametrize("key", ["image.gif", "noextension", "clip.ogg", "video.mp4"])
def test_unsupported_extensions_are_rejected(key):
    with pytest.raises(ValidationError, match="Unsupported"):
        media_key_modality(key)


def test_wrong_modality_and_non_string_keys_are_rejected():
    with pytest.raises(ValidationError, match="is audio; the collection is image"):
        media_key_modality("audio_query.mp3", Modality.IMAGE)
    with pytest.raises(InvalidTypeError):
        media_key_modality(b"x.jpg")


def test_longest_valid_media_key_is_accepted():
    assert media_key_modality("x" * (MAX_MEDIA_KEY_LENGTH - 4) + ".jpg") is Modality.IMAGE


@pytest.mark.parametrize("n, nlist", [(1, 1), (3, 2), (1000, 32), (10_000, 100), (100_000, 316)])
def test_default_ivf_lists_follow_square_root_rule(n, nlist):
    assert default_nlist(n) == nlist
    assert default_nprobe(nlist) == min(8, nlist)


def test_starting_parameters_match_the_plan():
    assert ImageFeatureParameters() == ImageFeatureParameters(512, True, 256, 256)
    audio = AudioFeatureParameters()
    assert (audio.sample_rate, audio.n_mfcc, audio.n_fft, audio.hop_length,
            audio.vocabulary_size) == (22_050, 20, 2_048, 512, 64)
    assert HnswParameters() == HnswParameters(16, 32, 100, 64)
    assert TrainingParameters().max_training_descriptors == 100_000
    assert default_ef_search(10) == 64 and default_ef_search(100) == 100
    with pytest.raises(ValidationError):
        default_nlist(0)
