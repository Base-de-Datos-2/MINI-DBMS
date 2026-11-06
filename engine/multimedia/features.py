"""Part 4 ExtractFeatures: SIFT/MFCC descriptors, vocabulary and TF-IDF.

Third-party helpers are imported lazily here only (decoding, SIFT, MFCC and
the vocabulary K-Means, as allowed by docs/multimedia-contract.md §7). The
bag-of-words assignment, histograms, TF-IDF and model persistence are ours.

Pipeline for one object, always with a fitted model:
descriptors -> nearest vocabulary word per descriptor -> word counts ->
x_j = (1 + ln h_j) * idf_j for h_j > 0.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
import hashlib
import io
import json
from pathlib import Path

import numpy as np

from engine.errors import InvalidTypeError, ValidationError

from .contracts import (
    AudioFeatureParameters, ImageFeatureParameters, Modality, TrainingParameters,
)
from .files import read_array, read_json, require_files, sha256_file, verify_checksums, write_array, write_json


MODEL_VERSION = 1
MAX_MEDIA_BYTES = 64 * 1024 * 1024
SIFT_DIMENSION = 128
# Mel/log-power settings pinned explicitly (library defaults change across
# versions); recorded in every fitted model.
MEL_SETTINGS = {"n_mels": 128, "fmin": 0.0, "fmax": None, "htk": False, "norm": "slaney",
                "window": "hann", "center": True, "pad_mode": "constant", "power": 2.0,
                "ref": 1.0, "amin": 1e-10, "top_db": 80.0, "dct_type": 2, "dct_norm": "ortho",
                "lifter": 0, "resample": "soxr_hq"}
MODEL_FILES = ("model.json", "codebook.npy", "idf.npy", "document_frequencies.npy")


class FeatureExtractionError(ValidationError):
    """An object cannot produce a searchable vector; ``reason`` is stable."""

    REASONS = frozenset({"undecodable", "no_descriptors", "no_signal", "too_short",
                         "too_long", "too_large"})

    def __init__(self, reason: str, message: str) -> None:
        if reason not in self.REASONS:
            raise ValueError(f"Unknown feature rejection reason {reason!r}")
        super().__init__(message)
        self.reason = reason


def _read_bounded(path: Path) -> bytes:
    path = Path(path)
    size = path.stat().st_size
    if size > MAX_MEDIA_BYTES:
        raise FeatureExtractionError("too_large", f"{path.name} exceeds {MAX_MEDIA_BYTES} bytes")
    return path.read_bytes()


# --- Images ----------------------------------------------------------------

def preprocess_image(data: bytes, parameters: ImageFeatureParameters = ImageFeatureParameters()):
    """Decode to grayscale (EXIF orientation applied) and shrink to max_side."""
    import cv2

    if not parameters.grayscale:
        raise ValidationError("SIFT runs on grayscale images; grayscale=False is unsupported")
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None or image.size == 0:
        raise FeatureExtractionError("undecodable", "The image cannot be decoded")
    height, width = image.shape[:2]
    scale = parameters.max_side / max(height, width)
    if scale < 1:
        size = (max(1, round(width * scale)), max(1, round(height * scale)))
        image = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
    return image


def image_descriptors(path: Path, parameters: ImageFeatureParameters = ImageFeatureParameters()) -> np.ndarray:
    """At most ``max_descriptors`` SIFT descriptors, strongest response first."""
    import cv2

    image = preprocess_image(_read_bounded(path), parameters)
    keypoints, descriptors = cv2.SIFT_create().detectAndCompute(image, None)
    if descriptors is None or not keypoints:
        raise FeatureExtractionError("no_descriptors", f"{Path(path).name} has no SIFT keypoints")
    order = sorted(range(len(keypoints)), key=lambda i: (
        -keypoints[i].response, keypoints[i].pt[1], keypoints[i].pt[0],
        -keypoints[i].size, keypoints[i].angle))
    return np.ascontiguousarray(descriptors[order[:parameters.max_descriptors]], dtype=np.float32)


# --- Audio -----------------------------------------------------------------

def decode_audio(data: bytes, parameters: AudioFeatureParameters = AudioFeatureParameters()) -> np.ndarray:
    """Mono float32 samples at ``sample_rate``; rejects long, silent or short clips."""
    import soundfile

    try:
        info = soundfile.info(io.BytesIO(data))
        if info.samplerate <= 0 or info.frames / info.samplerate > parameters.max_duration_seconds + 1e-9:
            raise FeatureExtractionError(
                "too_long", f"Audio longer than {parameters.max_duration_seconds} s is rejected")
        samples, rate = soundfile.read(io.BytesIO(data), dtype="float32", always_2d=True)
    except FeatureExtractionError:
        raise
    except Exception as error:
        raise FeatureExtractionError("undecodable", f"The audio cannot be decoded ({type(error).__name__})") from None
    if samples.size == 0 or not np.all(np.isfinite(samples)):
        raise FeatureExtractionError("undecodable", "The audio has no finite samples")
    if len(samples) / rate > parameters.max_duration_seconds + 1e-9:
        raise FeatureExtractionError("too_long", f"Audio longer than {parameters.max_duration_seconds} s is rejected")
    mono = samples.mean(axis=1) if parameters.mono else samples[:, 0]
    if not np.any(mono):
        raise FeatureExtractionError("no_signal", "Every decoded sample is zero")
    if rate != parameters.sample_rate:
        import librosa
        mono = librosa.resample(mono, orig_sr=rate, target_sr=parameters.sample_rate,
                                res_type=MEL_SETTINGS["resample"])
    if len(mono) < parameters.n_fft:
        raise FeatureExtractionError("too_short", f"Audio shorter than {parameters.n_fft} samples is rejected")
    return np.ascontiguousarray(mono, dtype=np.float32)


def mfcc_frames(samples: np.ndarray, parameters: AudioFeatureParameters = AudioFeatureParameters()) -> np.ndarray:
    import librosa

    settings = MEL_SETTINGS
    power = librosa.feature.melspectrogram(
        y=samples, sr=parameters.sample_rate, n_fft=parameters.n_fft,
        hop_length=parameters.hop_length, window=settings["window"], center=settings["center"],
        pad_mode=settings["pad_mode"], power=settings["power"], n_mels=settings["n_mels"],
        fmin=settings["fmin"], fmax=settings["fmax"], htk=settings["htk"], norm=settings["norm"])
    log_power = librosa.power_to_db(power, ref=settings["ref"], amin=settings["amin"],
                                    top_db=settings["top_db"])
    mfcc = librosa.feature.mfcc(S=log_power, n_mfcc=parameters.n_mfcc, dct_type=settings["dct_type"],
                                norm=settings["dct_norm"], lifter=settings["lifter"])
    return np.ascontiguousarray(mfcc.T, dtype=np.float32)


def audio_descriptors(path: Path, parameters: AudioFeatureParameters = AudioFeatureParameters()) -> np.ndarray:
    """One ``n_mfcc``-dimensional descriptor per frame."""
    frames = mfcc_frames(decode_audio(_read_bounded(path), parameters), parameters)
    if not len(frames) or not np.all(np.isfinite(frames)):
        raise FeatureExtractionError("no_descriptors", f"{Path(path).name} has no finite MFCC frames")
    return frames


def descriptors_for(modality: Modality, path: Path, parameters) -> np.ndarray:
    if modality is Modality.IMAGE:
        return image_descriptors(path, parameters)
    if modality is Modality.AUDIO:
        return audio_descriptors(path, parameters)
    raise InvalidTypeError("modality must be a Modality")


def default_parameters(modality: Modality):
    return ImageFeatureParameters() if modality is Modality.IMAGE else AudioFeatureParameters()


# --- Vocabulary (K-Means through scikit-learn) ------------------------------

def sample_descriptors(descriptor_sets: Sequence[np.ndarray], limit: int, seed: int) -> np.ndarray:
    """Seeded uniform sample of at most ``limit`` descriptors across objects."""
    if not descriptor_sets:
        raise ValidationError("Vocabulary training needs at least one object")
    dimension = descriptor_sets[0].shape[1]
    if any(d.ndim != 2 or d.shape[1] != dimension or not len(d) for d in descriptor_sets):
        raise ValidationError("Descriptor sets must be nonempty and share one dimension")
    every = np.concatenate(descriptor_sets).astype(np.float32, copy=False)
    if len(every) <= limit:
        return every
    chosen = np.sort(np.random.default_rng(seed).choice(len(every), size=limit, replace=False))
    return every[chosen]


def fit_vocabulary(sample: np.ndarray, vocabulary_size: int,
                   training: TrainingParameters = TrainingParameters()) -> np.ndarray:
    """K visual/audio words: scikit-learn K-Means (k-means++, Lloyd, seeded)."""
    from sklearn.cluster import KMeans

    if type(vocabulary_size) is not int or vocabulary_size < 1:
        raise ValidationError("Vocabulary size must be a positive integer")
    distinct = len(np.unique(sample, axis=0))
    if distinct < vocabulary_size:
        raise ValidationError(
            f"Only {distinct} distinct descriptors for K={vocabulary_size}; use a smaller K")
    model = KMeans(n_clusters=vocabulary_size, init="k-means++", n_init=training.kmeans_restarts,
                   max_iter=training.kmeans_max_iterations, random_state=training.seed,
                   algorithm="lloyd").fit(sample.astype(np.float64))
    return np.ascontiguousarray(model.cluster_centers_, dtype=np.float32)


# --- Bag of words and TF-IDF (own code) -----------------------------------

def assign_words(descriptors: np.ndarray, codebook: np.ndarray) -> np.ndarray:
    """Nearest word by squared Euclidean distance; ties go to the lower index."""
    if descriptors.ndim != 2 or codebook.ndim != 2 or descriptors.shape[1] != codebook.shape[1]:
        raise ValidationError("Descriptors and codebook dimensions differ")
    d = descriptors.astype(np.float64)
    c = codebook.astype(np.float64)
    distances = (d * d).sum(axis=1)[:, None] - 2.0 * (d @ c.T) + (c * c).sum(axis=1)[None, :]
    return np.argmin(distances, axis=1)


def word_counts(descriptors: np.ndarray, codebook: np.ndarray) -> np.ndarray:
    return np.bincount(assign_words(descriptors, codebook), minlength=len(codebook)).astype(np.int64)


def document_frequencies(counts: np.ndarray) -> np.ndarray:
    """df_j: number of objects whose count for word j is positive."""
    if counts.ndim != 2:
        raise ValidationError("Counts must be an objects x words matrix")
    return (counts > 0).sum(axis=0).astype(np.int64)


def inverse_document_frequencies(collection_size: int, frequencies: np.ndarray) -> np.ndarray:
    if collection_size < 1 or np.any(frequencies < 0) or np.any(frequencies > collection_size):
        raise ValidationError("Document frequencies must lie between 0 and N")
    return np.log((collection_size + 1) / (frequencies.astype(np.float64) + 1)) + 1.0


def tfidf(counts: np.ndarray, idf: np.ndarray) -> np.ndarray:
    """Unnormalized float32 vectors; one row per object (or one 1-D vector)."""
    counts = np.asarray(counts)
    if counts.shape[-1] != len(idf) or np.any(counts < 0):
        raise ValidationError("Counts do not match the vocabulary")
    tf = np.zeros(counts.shape, dtype=np.float64)
    positive = counts > 0
    tf[positive] = 1.0 + np.log(counts[positive].astype(np.float64))
    return (tf * idf).astype(np.float32)


# --- Fitted model ----------------------------------------------------------

def library_versions() -> dict:
    versions = {"numpy": np.__version__}
    for module in ("cv2", "librosa", "sklearn", "soundfile"):
        try:
            versions[module] = __import__(module).__version__
        except ImportError:
            versions[module] = None
    return versions


@dataclass(frozen=True, slots=True, eq=False)
class FeatureModel:
    """Vocabulary plus gallery IDF; queries never change N, df or the codebook."""

    modality: Modality
    parameters: object
    training: TrainingParameters
    codebook: np.ndarray
    document_frequencies: np.ndarray
    collection_size: int
    libraries: dict

    def __post_init__(self):
        # Private read-only copies: callers' arrays are never frozen or aliased.
        object.__setattr__(self, "codebook", np.array(self.codebook, copy=True))
        object.__setattr__(self, "document_frequencies", np.array(self.document_frequencies, copy=True))
        if type(self.collection_size) is not int or self.collection_size < 1:
            raise ValidationError("Collection size must be a positive integer")
        if self.codebook.ndim != 2 or self.codebook.dtype != np.float32:
            raise ValidationError("Codebook must be a float32 matrix")
        expected = SIFT_DIMENSION if self.modality is Modality.IMAGE else self.parameters.n_mfcc
        if self.codebook.shape[1] != expected:
            raise ValidationError("Codebook dimension does not match the descriptor type")
        if self.document_frequencies.shape != (len(self.codebook),):
            raise ValidationError("Document frequencies do not match the vocabulary")
        self.codebook.setflags(write=False)
        self.document_frequencies.setflags(write=False)

    @property
    def vocabulary_size(self) -> int:
        return len(self.codebook)

    @property
    def idf(self) -> np.ndarray:
        return inverse_document_frequencies(self.collection_size, self.document_frequencies)

    @property
    def fingerprint(self) -> str:
        digest = hashlib.sha256(json.dumps(self._description(), sort_keys=True).encode())
        digest.update(self.codebook.tobytes())
        digest.update(self.document_frequencies.tobytes())
        return digest.hexdigest()

    def _description(self) -> dict:
        return {"version": MODEL_VERSION, "modality": self.modality.value,
                "parameters": asdict(self.parameters), "training": asdict(self.training),
                "mel_settings": MEL_SETTINGS if self.modality is Modality.AUDIO else None,
                "vocabulary_size": self.vocabulary_size, "descriptor_dimension": self.codebook.shape[1],
                "collection_size": self.collection_size}

    def counts(self, path: Path) -> np.ndarray:
        return word_counts(descriptors_for(self.modality, path, self.parameters), self.codebook)

    def encode(self, path: Path) -> np.ndarray:
        """ExtractFeatures(object, fitted_model) -> float32[K]."""
        return tfidf(self.counts(path), self.idf)

    def save(self, directory: Path) -> None:
        """Write into a NEW directory; existing models are never overwritten."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=False)
        write_array(directory / "codebook.npy", self.codebook)
        write_array(directory / "document_frequencies.npy", self.document_frequencies)
        write_array(directory / "idf.npy", self.idf)
        payload = {**self._description(), "libraries": self.libraries, "fingerprint": self.fingerprint,
                   "files": {name: sha256_file(directory / name) for name in MODEL_FILES[1:]}}
        write_json(directory / "model.json", payload)

    @classmethod
    def load(cls, directory: Path) -> "FeatureModel":
        """Open a fitted model; never trains, extracts or recomputes vocabularies."""
        directory = Path(directory)
        require_files(directory, MODEL_FILES, "Feature model")
        payload = read_json(directory / "model.json", "Feature model metadata")
        if payload.get("version") != MODEL_VERSION:
            raise ValidationError("Unsupported feature model version")
        verify_checksums(directory, payload.get("files"), "Feature model")
        modality = Modality(payload["modality"])
        parameter_type = ImageFeatureParameters if modality is Modality.IMAGE else AudioFeatureParameters
        if modality is Modality.AUDIO and payload["mel_settings"] != MEL_SETTINGS:
            raise ValidationError("Feature model was built with different MFCC settings")
        model = cls(modality, parameter_type(**payload["parameters"]),
                    TrainingParameters(**payload["training"]),
                    read_array(directory / "codebook.npy", np.float32),
                    read_array(directory / "document_frequencies.npy", np.int64),
                    payload["collection_size"], payload["libraries"])
        stored_idf = read_array(directory / "idf.npy", np.float64)
        if not np.array_equal(stored_idf, model.idf) or model.fingerprint != payload["fingerprint"]:
            raise ValidationError("Feature model fingerprint or IDF is inconsistent")
        return model


# --- Collection-level construction ------------------------------------------

@dataclass(frozen=True, slots=True)
class CollectionFeatures:
    model: FeatureModel
    ids: np.ndarray       # int64, gallery order
    vectors: np.ndarray   # float32 N x K, unnormalized TF-IDF


def train_vocabulary(modality: Modality, training_paths: Iterable[Path], vocabulary_size: int | None = None,
                     parameters=None, training: TrainingParameters = TrainingParameters()) -> np.ndarray:
    """Extract descriptors of the training objects, sample them and fit K words."""
    parameters = parameters or default_parameters(modality)
    sets = [descriptors_for(modality, path, parameters) for path in training_paths]
    sample = sample_descriptors(sets, training.max_training_descriptors, training.seed)
    return fit_vocabulary(sample, vocabulary_size or parameters.vocabulary_size, training)


def build_collection_features(modality: Modality, gallery: Sequence[tuple[int, Path]], codebook: np.ndarray,
                              parameters=None, training: TrainingParameters = TrainingParameters()
                              ) -> CollectionFeatures:
    """Count words for every gallery object, then fit IDF on exactly this gallery."""
    parameters = parameters or default_parameters(modality)
    ids = np.array([object_id for object_id, _ in gallery], dtype=np.int64)
    if len(ids) == 0 or len(np.unique(ids)) != len(ids):
        raise ValidationError("The gallery needs unique object ids")
    counts = np.stack([word_counts(descriptors_for(modality, path, parameters), codebook)
                       for _, path in gallery])
    model = FeatureModel(modality, parameters, training, np.ascontiguousarray(codebook, dtype=np.float32),
                         document_frequencies(counts), len(ids), library_versions())
    return CollectionFeatures(model, ids, tfidf(counts, model.idf))


def counts_to_features(modality: Modality, ids: np.ndarray, counts: np.ndarray, codebook: np.ndarray,
                       parameters=None, training: TrainingParameters = TrainingParameters()
                       ) -> CollectionFeatures:
    """Same as build_collection_features for counts computed elsewhere (e.g. in parallel)."""
    parameters = parameters or default_parameters(modality)
    ids = np.asarray(ids, dtype=np.int64)
    counts = np.asarray(counts, dtype=np.int64)
    if counts.shape != (len(ids), len(codebook)) or len(np.unique(ids)) != len(ids):
        raise ValidationError("Counts must have one row per unique id and one column per word")
    if np.any(counts.sum(axis=1) == 0):
        raise ValidationError("Every object must have at least one descriptor")
    model = FeatureModel(modality, parameters, training, np.ascontiguousarray(codebook, dtype=np.float32),
                         document_frequencies(counts), len(ids), library_versions())
    return CollectionFeatures(model, ids, tfidf(counts, model.idf))


__all__ = [
    "FeatureExtractionError", "FeatureModel", "CollectionFeatures", "preprocess_image",
    "image_descriptors", "decode_audio", "mfcc_frames", "audio_descriptors", "descriptors_for",
    "default_parameters", "sample_descriptors", "fit_vocabulary", "assign_words", "word_counts",
    "document_frequencies", "inverse_document_frequencies", "tfidf", "library_versions",
    "train_vocabulary", "build_collection_features", "counts_to_features",
]
