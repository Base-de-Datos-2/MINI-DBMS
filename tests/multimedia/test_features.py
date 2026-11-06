"""Phase 2: SIFT/MFCC extraction, vocabulary, bag of words and TF-IDF."""

import json
from pathlib import Path
import subprocess
import sys
import wave
import struct

import numpy as np
import pytest

from engine.errors import ValidationError
from engine.multimedia import (
    AudioFeatureParameters, ImageFeatureParameters, Metric, Modality, TrainingParameters,
    exact_top_k, weighted_histogram,
)
from engine.multimedia.features import (
    FeatureExtractionError, FeatureModel, assign_words, audio_descriptors,
    build_collection_features, counts_to_features, decode_audio, document_frequencies,
    fit_vocabulary, image_descriptors, inverse_document_frequencies, preprocess_image,
    sample_descriptors, tfidf, train_vocabulary, word_counts,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
MANIFEST = json.loads((FIXTURES / "manifest.v1.json").read_text(encoding="utf-8"))
ROOT = Path(__file__).resolve().parents[2]


def names(modality, role):
    return [e["name"] for e in MANIFEST["files"] if e["modality"] == modality and e["role"] == role]


@pytest.fixture(scope="module")
def image_collection():
    gallery = names("image", "gallery")
    codebook = train_vocabulary(Modality.IMAGE, [FIXTURES / n for n in gallery], 16)
    return gallery, build_collection_features(
        Modality.IMAGE, [(i, FIXTURES / n) for i, n in enumerate(gallery, 1)], codebook)


@pytest.fixture(scope="module")
def audio_collection():
    gallery = names("audio", "gallery")
    codebook = train_vocabulary(Modality.AUDIO, [FIXTURES / n for n in gallery], 8)
    return gallery, build_collection_features(
        Modality.AUDIO, [(i, FIXTURES / n) for i, n in enumerate(gallery, 1)], codebook)


def write_wav(path, samples, rate=22_050, channels=1):
    frames = b"".join(struct.pack("<h", int(s)) for s in samples)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(frames)
    return path


# --- Images ----------------------------------------------------------------

def test_sift_returns_capped_float32_descriptors_strongest_first():
    descriptors = image_descriptors(FIXTURES / "scene_a.png")
    assert descriptors.dtype == np.float32 and descriptors.shape[1] == 128
    assert 0 < len(descriptors) <= 256
    capped = image_descriptors(FIXTURES / "scene_a.png", ImageFeatureParameters(max_descriptors=5))
    assert np.array_equal(capped, descriptors[:5])
    assert np.array_equal(image_descriptors(FIXTURES / "scene_a.png"), descriptors)


def test_large_images_shrink_to_512_and_small_ones_are_never_enlarged(tmp_path):
    import cv2
    small = cv2.imread(str(FIXTURES / "scene_a.png"))
    large = cv2.resize(small, (1200, 800), interpolation=cv2.INTER_NEAREST)
    ok, encoded = cv2.imencode(".png", large)
    assert ok
    assert preprocess_image(encoded.tobytes()).shape == (341, 512)
    assert preprocess_image((FIXTURES / "scene_a.png").read_bytes()).shape == (160, 160)
    tall = cv2.resize(small, (300, 900))
    assert preprocess_image(cv2.imencode(".png", tall)[1].tobytes()).shape == (512, 171)


@pytest.mark.parametrize("name, reason", [("blank.png", "no_descriptors"), ("corrupt.jpg", "undecodable")])
def test_images_without_a_searchable_vector_are_rejected_explicitly(name, reason):
    with pytest.raises(FeatureExtractionError) as error:
        image_descriptors(FIXTURES / name)
    assert error.value.reason == reason


def test_oversized_media_is_rejected_before_decoding(monkeypatch):
    import engine.multimedia.features as features
    monkeypatch.setattr(features, "MAX_MEDIA_BYTES", 100)
    with pytest.raises(FeatureExtractionError) as error:
        image_descriptors(FIXTURES / "scene_a.png")
    assert error.value.reason == "too_large"


# --- Audio -----------------------------------------------------------------

def test_mfcc_gives_one_20_dimensional_descriptor_per_frame():
    frames = audio_descriptors(FIXTURES / "acorde_grave.wav")
    # center=True: 1 + floor(22050 / 512) frames.
    assert frames.shape == (44, 20) and frames.dtype == np.float32
    assert np.all(np.isfinite(frames))


def test_mp3_query_decodes_to_the_same_frame_grid():
    assert audio_descriptors(FIXTURES / "audio_query.mp3").shape == (44, 20)


@pytest.mark.parametrize("name, reason", [("silencio.wav", "no_signal"), ("corrupt.mp3", "undecodable")])
def test_audio_without_a_searchable_vector_is_rejected_explicitly(name, reason):
    with pytest.raises(FeatureExtractionError) as error:
        audio_descriptors(FIXTURES / name)
    assert error.value.reason == reason


def test_clips_shorter_than_one_fft_window_or_longer_than_the_limit_are_rejected(tmp_path):
    short = write_wav(tmp_path / "short.wav", [1000 * ((i % 50) - 25) for i in range(2047)])
    with pytest.raises(FeatureExtractionError) as error:
        audio_descriptors(short)
    assert error.value.reason == "too_short"
    with pytest.raises(FeatureExtractionError) as error:
        audio_descriptors(FIXTURES / "acorde_grave.wav", AudioFeatureParameters(max_duration_seconds=0.5))
    assert error.value.reason == "too_long"


def test_stereo_44100_hz_input_is_downmixed_and_resampled(tmp_path):
    mono = wave.open(str(FIXTURES / "acorde_grave.wav")).readframes(22_050)
    samples = struct.unpack("<22050h", mono)
    doubled = [s for s in samples for _ in range(2)]            # 44,100 Hz
    stereo = [s for s in doubled for _ in range(2)]             # two equal channels
    path = write_wav(tmp_path / "stereo.wav", stereo, rate=44_100, channels=2)
    decoded = decode_audio(path.read_bytes())
    assert len(decoded) == 22_050
    assert audio_descriptors(path).shape == (44, 20)


# --- Vocabulary and weights -------------------------------------------------

def test_assignment_uses_squared_euclidean_and_ties_go_to_the_lower_word():
    codebook = np.array([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0]], dtype=np.float32)
    descriptors = np.array([[1, 1], [9, 1], [1, 8], [5, 0], [0, 5]], dtype=np.float32)
    assert assign_words(descriptors, codebook).tolist() == [0, 1, 2, 0, 0]
    assert word_counts(descriptors, codebook).tolist() == [3, 1, 1]
    with pytest.raises(ValidationError):
        assign_words(descriptors, codebook[:, :1])


def test_document_frequency_counts_objects_not_descriptors():
    counts = np.array([[5, 0, 1], [0, 0, 2], [1, 0, 0]])
    assert document_frequencies(counts).tolist() == [2, 0, 2]


def test_numpy_tfidf_matches_the_contract_oracle():
    counts = np.array([[0, 1, 3, 7], [2, 0, 1, 1], [1, 1, 0, 4]])
    frequencies = document_frequencies(counts)
    idf = inverse_document_frequencies(3, frequencies)
    vectors = tfidf(counts, idf)
    assert vectors.dtype == np.float32
    for row, vector in zip(counts, vectors):
        expected = weighted_histogram(row.tolist(), frequencies.tolist(), 3)
        assert vector.tolist() == pytest.approx(expected, rel=1e-6)


def test_vocabulary_training_is_seeded_bounded_and_needs_enough_distinct_descriptors():
    rng = np.random.default_rng(3)
    sets = [rng.normal(size=(40, 4)).astype(np.float32) for _ in range(5)]
    sample = sample_descriptors(sets, 50, seed=11)
    assert sample.shape == (50, 4)
    assert np.array_equal(sample, sample_descriptors(sets, 50, seed=11))
    assert sample_descriptors(sets, 1_000, seed=11).shape == (200, 4)
    first = fit_vocabulary(sample, 6, TrainingParameters(seed=5))
    assert first.shape == (6, 4) and first.dtype == np.float32
    assert np.array_equal(first, fit_vocabulary(sample, 6, TrainingParameters(seed=5)))
    with pytest.raises(ValidationError, match="distinct"):
        fit_vocabulary(np.ones((30, 4), dtype=np.float32), 2)


# --- Collections and fitted models ------------------------------------------

def test_image_collection_vectors_are_finite_nonzero_and_find_the_designed_neighbors(image_collection):
    gallery, features = image_collection
    assert features.vectors.shape == (len(gallery), 16)
    assert np.all(np.isfinite(features.vectors)) and np.all(np.linalg.norm(features.vectors, axis=1) > 0)
    items = [(int(i), v.tolist()) for i, v in zip(features.ids, features.vectors)]
    query = features.model.encode(FIXTURES / "foto_consulta.jpg").tolist()
    for metric in Metric:
        assert gallery[exact_top_k(items, query, metric, 1)[0].object_id - 1] == "scene_a.png"
    for variant, original in (("scene_a_shifted.png", "scene_a.png"), ("scene_b_mirror.png", "scene_b.png")):
        others = [item for item in items if gallery[item[0] - 1] != variant]
        vector = features.vectors[gallery.index(variant)].tolist()
        assert gallery[exact_top_k(others, vector, Metric.COSINE, 1)[0].object_id - 1] == original


def test_mp3_query_finds_its_source_chord_with_every_metric(audio_collection):
    gallery, features = audio_collection
    items = [(int(i), v.tolist()) for i, v in zip(features.ids, features.vectors)]
    query = features.model.encode(FIXTURES / "audio_query.mp3").tolist()
    for metric in Metric:
        assert gallery[exact_top_k(items, query, metric, 1)[0].object_id - 1] == "acorde_grave.wav"


def test_query_encoding_uses_gallery_idf_and_never_changes_the_model(image_collection):
    _, features = image_collection
    model = features.model
    before = (model.fingerprint, model.idf.copy())
    vector = model.encode(FIXTURES / "foto_consulta.jpg")
    counts = model.counts(FIXTURES / "foto_consulta.jpg")
    assert np.array_equal(vector, tfidf(counts, before[1]))
    assert model.fingerprint == before[0] and np.array_equal(model.idf, before[1])


def test_counts_path_equals_direct_collection_construction(image_collection):
    gallery, features = image_collection
    counts = np.stack([features.model.counts(FIXTURES / n) for n in gallery])
    rebuilt = counts_to_features(Modality.IMAGE, features.ids, counts, features.model.codebook)
    assert np.array_equal(rebuilt.vectors, features.vectors)
    assert rebuilt.model.fingerprint == features.model.fingerprint
    with pytest.raises(ValidationError, match="at least one descriptor"):
        counts_to_features(Modality.IMAGE, [1], np.zeros((1, 16), dtype=np.int64), features.model.codebook)


def test_model_reopens_without_training_and_encodes_identically(image_collection, tmp_path, monkeypatch):
    _, features = image_collection
    features.model.save(tmp_path / "model")
    import sklearn.cluster
    monkeypatch.setattr(sklearn.cluster, "KMeans", None)   # any training attempt would fail
    reopened = FeatureModel.load(tmp_path / "model")
    assert reopened.fingerprint == features.model.fingerprint
    assert np.array_equal(reopened.encode(FIXTURES / "foto_consulta.jpg"),
                          features.model.encode(FIXTURES / "foto_consulta.jpg"))
    with pytest.raises(FileExistsError):
        features.model.save(tmp_path / "model")


def test_audio_model_round_trip_keeps_mfcc_settings(audio_collection, tmp_path):
    _, features = audio_collection
    features.model.save(tmp_path / "audio")
    reopened = FeatureModel.load(tmp_path / "audio")
    assert reopened.modality is Modality.AUDIO and reopened.parameters == AudioFeatureParameters()
    assert np.array_equal(reopened.encode(FIXTURES / "audio_query.mp3"),
                          features.model.encode(FIXTURES / "audio_query.mp3"))


def test_damaged_or_incomplete_models_are_rejected(image_collection, tmp_path):
    _, features = image_collection
    features.model.save(tmp_path / "model")
    codebook = tmp_path / "model" / "codebook.npy"
    data = bytearray(codebook.read_bytes())
    data[-1] ^= 0xFF
    codebook.write_bytes(bytes(data))
    with pytest.raises(ValidationError, match="checksum"):
        FeatureModel.load(tmp_path / "model")
    features.model.save(tmp_path / "other")
    (tmp_path / "other" / "idf.npy").unlink()
    with pytest.raises(ValidationError, match="missing idf.npy"):
        FeatureModel.load(tmp_path / "other")
    features.model.save(tmp_path / "third")
    meta = tmp_path / "third" / "model.json"
    payload = json.loads(meta.read_text())
    payload["version"] = 99
    meta.write_text(json.dumps(payload))
    with pytest.raises(ValidationError, match="version"):
        FeatureModel.load(tmp_path / "third")


def test_a_fresh_process_reopens_the_model_and_reproduces_the_query_vector(image_collection, tmp_path):
    _, features = image_collection
    features.model.save(tmp_path / "model")
    expected = features.model.encode(FIXTURES / "foto_consulta.jpg")
    script = (
        "import sys, numpy as np; from pathlib import Path\n"
        "from engine.multimedia.features import FeatureModel\n"
        "model = FeatureModel.load(Path(sys.argv[1]))\n"
        "np.save(sys.argv[3], model.encode(Path(sys.argv[2])))\n"
    )
    output = tmp_path / "vector.npy"
    subprocess.run([sys.executable, "-c", script, str(tmp_path / "model"),
                    str(FIXTURES / "foto_consulta.jpg"), str(output)], check=True, cwd=ROOT)
    assert np.array_equal(np.load(output), expected)
