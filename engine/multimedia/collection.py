"""Published multimedia collection: one modality, one Heap, its vectors and indexes.

Directory layout (built once, offline, into a NEW directory):

    collection.json   identity, modality, columns, available methods/metrics
    model/            FeatureModel (vocabulary + gallery IDF)
    store/            VectorStore (ids, unnormalized TF-IDF vectors, norms)
    rids.npy          int64 N x 2 (page_id, slot_id) per vector row
    ivf/              IvfIndex (optional)
    hnsw_<metric>/    HnswIndex per metric (optional)
    media/            gallery files named by their media key
    queries/          registered query files (e.g. foto_consulta.jpg)

``open`` validates structure and restores every handle without extracting
features, training or building. Search resolves a registered key (queries
first, then gallery media), encodes it with the collection's fitted model and
runs the requested index or, when indexes are disabled, the exact VectorScan.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
import os
from pathlib import Path
import shutil
import time

import numpy as np

from engine.errors import InvalidTypeError, ValidationError
from engine.storage.rid import RID

from .contracts import (
    HnswParameters, IndexMethod, Metric, Modality, TrainingParameters, media_key_modality, validate_k,
)
from .features import FeatureModel, counts_to_features, default_parameters, descriptors_for, word_counts, \
    train_vocabulary
from .files import read_array, read_json, require_files, write_array, write_json
from .hnsw import HnswIndex
from .ivf import IvfIndex
from .vectors import VectorSearchResult, VectorStore


COLLECTION_VERSION = 1


@dataclass(frozen=True, slots=True)
class CollectionSearch:
    result: VectorSearchResult
    rids: tuple[RID, ...]
    requested_method: str | None
    executed_method: str          # "IVF", "HNSW" or "VectorScan"
    metric: Metric
    k: int
    timings: dict = field(default_factory=dict)


class MultimediaCollection:
    """Read-only owner of a published collection's model, vectors and indexes."""

    __slots__ = ("_directory", "_manifest", "_model", "_store", "_ivf", "_hnsw", "_rids",
                 "_rows_by_id", "_closed")

    def __init__(self) -> None:
        raise TypeError("Use build_collection() or MultimediaCollection.open()")

    @classmethod
    def open(cls, directory: Path, *, collection_id: str | None = None,
             generation: str | None = None) -> "MultimediaCollection":
        directory = Path(directory)
        require_files(directory, ("collection.json", "rids.npy"), "Multimedia collection")
        manifest = read_json(directory / "collection.json", "Multimedia collection manifest")
        if manifest.get("version") != COLLECTION_VERSION:
            raise ValidationError("Unsupported multimedia collection version")
        if collection_id is not None and manifest.get("collection_id") != collection_id:
            raise ValidationError("Multimedia collection id does not match its registration")
        if generation is not None and manifest.get("generation") != generation:
            raise ValidationError("Multimedia collection generation does not match its registration")
        collection = object.__new__(cls)
        collection._directory = directory
        collection._manifest = manifest
        collection._closed = False
        collection._ivf = None
        collection._hnsw = {}
        collection._store = None
        try:
            collection._model = FeatureModel.load(directory / "model")
            if collection._model.modality is not Modality(manifest["modality"]):
                raise ValidationError("Feature model modality differs from the collection")
            collection._store = VectorStore.open(directory / "store",
                                                 expected_fingerprint=collection._model.fingerprint)
            if collection._store.size != manifest["size"]:
                raise ValidationError("Vector store size differs from the collection manifest")
            rids = read_array(directory / "rids.npy", np.int64, (manifest["size"], 2))
            collection._rids = rids
            collection._rows_by_id = {int(i): row for row, i in enumerate(collection._store.ids.tolist())}
            if "IVF" in manifest["methods"]:
                collection._ivf = IvfIndex.open(directory / "ivf", collection._store)
                if set(m.value for m in collection._ivf.metrics) != set(manifest["methods"]["IVF"]):
                    raise ValidationError("IVF metrics differ from the collection manifest")
            for metric in manifest["methods"].get("HNSW", []):
                collection._hnsw[metric] = HnswIndex.open(directory / f"hnsw_{metric}", collection._store)
        except BaseException:
            collection.close()
            raise
        return collection

    # -- identity -----------------------------------------------------------
    def _require_open(self):
        if self._closed:
            raise ValidationError("Multimedia collection is closed")

    @property
    def directory(self) -> Path:
        return self._directory

    @property
    def collection_id(self) -> str:
        return self._manifest["collection_id"]

    @property
    def generation(self) -> str:
        return self._manifest["generation"]

    @property
    def modality(self) -> Modality:
        return Modality(self._manifest["modality"])

    @property
    def table_name(self) -> str:
        return self._manifest["table"]

    @property
    def id_column(self) -> str:
        return self._manifest["id_column"]

    @property
    def key_column(self) -> str:
        return self._manifest["key_column"]

    @property
    def size(self) -> int:
        return self._manifest["size"]

    @property
    def dimension(self) -> int:
        return self._store.dimension

    @property
    def model(self) -> FeatureModel:
        return self._model

    @property
    def store(self) -> VectorStore:
        return self._store

    @property
    def methods(self) -> dict:
        """{"IVF": [metrics...], "HNSW": [metrics...]} available in this generation."""
        return {method: list(metrics) for method, metrics in self._manifest["methods"].items()}

    @property
    def manifest(self) -> dict:
        return dict(self._manifest)

    def query_keys(self) -> list[str]:
        directory = self._directory / "queries"
        return sorted(p.name for p in directory.iterdir() if p.is_file()) if directory.is_dir() else []

    # -- media --------------------------------------------------------------
    def resolve_media(self, key: str) -> Path:
        """Path of a registered key: registered queries first, then gallery media."""
        self._require_open()
        media_key_modality(key, self.modality)
        for folder in ("queries", "media"):
            base = (self._directory / folder).resolve()
            candidate = (base / key).resolve()
            if candidate.parent == base and candidate.is_file():
                return candidate
        raise ValidationError(f"Media key {key!r} is not registered in this collection")

    def rid_for_id(self, object_id: int) -> RID:
        row = self._rows_by_id.get(object_id)
        if row is None:
            raise ValidationError(f"Unknown object id {object_id}")
        page, slot = self._rids[row]
        return RID(int(page), int(slot))

    # -- storage association ----------------------------------------------------
    def require_compatible_storage(self, storage) -> None:
        descriptor = getattr(storage, "seal_descriptor", None)
        if descriptor is None or descriptor.collection_id != self.collection_id \
                or descriptor.generation != self.generation:
            raise ValidationError("Heap seal does not match this multimedia collection generation")
        if storage.record_count != self.size:
            raise ValidationError("Heap record count differs from the multimedia collection")

    def verify_storage(self, storage) -> None:
        """Full publication check: every RID holds the expected id and media key."""
        keys = set()
        for row, object_id in enumerate(self._store.ids.tolist()):
            page, slot = self._rids[row]
            record = storage.read(RID(int(page), int(slot)))
            if record[self.id_column] != object_id:
                raise ValidationError(f"RID of object {object_id} holds a different id")
            key = record[self.key_column]
            if key in keys or not (self._directory / "media" / key).is_file():
                raise ValidationError(f"Media file for object {object_id} is missing or duplicated")
            keys.add(key)

    # -- search -------------------------------------------------------------------
    def search(self, key: str, metric: Metric, k: int, *, method: IndexMethod | None,
               use_index: bool = True, nprobe: int | None = None,
               ef_search: int | None = None) -> CollectionSearch:
        self._require_open()
        validate_k(k)
        if not isinstance(metric, Metric):
            raise InvalidTypeError("metric must be a Metric")
        if method is not None and not isinstance(method, IndexMethod):
            raise InvalidTypeError("method must be an IndexMethod or None")
        if method is not None and metric.value not in self._manifest["methods"].get(method.value, []):
            raise ValidationError(f"Collection has no {method.value} index for metric {metric.value}")
        started = time.perf_counter()
        query = self._model.encode(self.resolve_media(key))
        extracted = time.perf_counter()
        if not use_index or method is None:
            result = self._store.search(query, metric, k)
            executed = "VectorScan"
        elif method is IndexMethod.IVF:
            result = self._ivf.search(query, metric, k, nprobe=nprobe)
            executed = "IVF"
        else:
            result = self._hnsw[metric.value].search(query, metric, k, ef_search=ef_search)
            executed = "HNSW"
        finished = time.perf_counter()
        rids = tuple(self.rid_for_id(n.object_id) for n in result.neighbors)
        return CollectionSearch(result, rids, None if method is None else method.value, executed, metric, k,
                                {"extract_seconds": extracted - started, "search_seconds": finished - extracted})

    def close(self) -> None:
        for graph in getattr(self, "_hnsw", {}).values():
            graph.close()
        if getattr(self, "_ivf", None) is not None:
            self._ivf.close()
        if getattr(self, "_store", None) is not None:
            self._store.close()
        self._hnsw = {}
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed

    def __enter__(self) -> "MultimediaCollection":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _place(source: Path, target: Path) -> None:
    """Hard-link when possible (no extra disk), copy otherwise."""
    try:
        os.link(source, target)
    except OSError:
        shutil.copyfile(source, target)


def build_collection(directory: Path, *, heap, schema, table: str, id_column: str, key_column: str,
                     modality: Modality, media_directory: Path, query_files: Sequence[Path] = (),
                     collection_id: str, generation: str, vocabulary_size: int | None = None,
                     training_ids: Sequence[int] | None = None,
                     training: TrainingParameters = TrainingParameters(),
                     ivf_metrics: Sequence[Metric] = tuple(Metric),
                     hnsw_metrics: Sequence[Metric] = tuple(Metric),
                     hnsw_parameters: HnswParameters = HnswParameters(),
                     ivf_nlist: int | None = None) -> MultimediaCollection:
    """Build a complete collection from an existing (not yet sealed) Heap.

    Every Heap row must name a media file in ``media_directory``. Feature
    extraction failures abort the build: corpus preparation filters media
    first, and a published collection never silently drops rows.
    """
    if not isinstance(modality, Modality):
        raise InvalidTypeError("modality must be a Modality")
    directory = Path(directory)
    media_directory = Path(media_directory)
    schema.index_of(id_column), schema.index_of(key_column)      # unknown columns fail here
    rows = []
    for rid, record in heap.scan():
        object_id, key = record[id_column], record[key_column]
        media_key_modality(key, modality)
        if not (media_directory / key).is_file():
            raise ValidationError(f"Media file {key!r} for object {object_id} is missing")
        rows.append((object_id, key, rid))
    if not rows:
        raise ValidationError("A multimedia collection needs at least one object")
    ids = np.array([object_id for object_id, _, _ in rows], dtype=np.int64)
    if len(np.unique(ids)) != len(ids) or len({key for _, key, _ in rows}) != len(rows):
        raise ValidationError("Object ids and media keys must be unique")
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "media").mkdir()
    (directory / "queries").mkdir()
    for _, key, _ in rows:
        _place(media_directory / key, directory / "media" / key)
    for path in query_files:
        path = Path(path)
        media_key_modality(path.name, modality)
        _place(path, directory / "queries" / path.name)
    parameters = default_parameters(modality)
    chosen = set(ids.tolist()) if training_ids is None else set(training_ids)
    training_paths = [directory / "media" / key for object_id, key, _ in rows if object_id in chosen]
    codebook = train_vocabulary(modality, training_paths, vocabulary_size, parameters, training)
    counts = np.stack([word_counts(descriptors_for(modality, directory / "media" / key, parameters), codebook)
                       for _, key, _ in rows])
    features = counts_to_features(modality, ids, counts, codebook, parameters, training)
    features.model.save(directory / "model")
    store = VectorStore.create(directory / "store", features.ids, features.vectors,
                               model_fingerprint=features.model.fingerprint)
    try:
        write_array(directory / "rids.npy", np.array([[rid.page_id, rid.slot_id] for _, _, rid in rows],
                                                     dtype=np.int64))
        methods = {}
        if ivf_metrics:
            IvfIndex.build(directory / "ivf", store, metrics=tuple(ivf_metrics), nlist=ivf_nlist,
                           seed=training.seed).close()
            methods["IVF"] = sorted(m.value for m in ivf_metrics)
        for metric in hnsw_metrics:
            HnswIndex.build(directory / f"hnsw_{metric.value}", store, metric, parameters=hnsw_parameters,
                            seed=training.seed).close()
        if hnsw_metrics:
            methods["HNSW"] = sorted(m.value for m in hnsw_metrics)
    finally:
        store.close()
    write_json(directory / "collection.json", {
        "version": COLLECTION_VERSION, "collection_id": collection_id, "generation": generation,
        "modality": modality.value, "table": table, "id_column": id_column, "key_column": key_column,
        "size": len(rows), "vocabulary_size": int(len(codebook)), "methods": methods,
        "training_objects": len(training_paths)})
    return MultimediaCollection.open(directory, collection_id=collection_id, generation=generation)


__all__ = ["MultimediaCollection", "CollectionSearch", "build_collection"]
