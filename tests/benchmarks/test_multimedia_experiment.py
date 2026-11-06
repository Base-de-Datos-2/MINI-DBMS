"""Part 4 benchmark helpers that run without the large local corpus."""

import io
import json

import numpy as np
import pytest

from benchmarks.multimedia import coco, experiment, fma
from engine.multimedia import Metric


def test_coco_permutation_is_seeded_and_complete():
    images = [{"id": i} for i in range(50)]
    first, second = coco.permutation(images), coco.permutation(images)
    assert first == second and sorted(i["id"] for i in first) == list(range(50))
    assert [i["id"] for i in first] != list(range(50))


def test_fma_license_filter_keeps_only_derivative_friendly_creative_commons():
    base = {"title": "Song", "artist": "Band"}
    assert fma.eligible({**base, "license": "Creative Commons Attribution"})
    assert fma.eligible({**base, "license": "Creative Commons Attribution-NonCommercial-ShareAlike"})
    assert not fma.eligible({**base, "license": "Creative Commons Attribution-NoDerivatives"})
    assert not fma.eligible({**base, "license": "Attribution-NonCommercial-NoDerivatives"})
    assert not fma.eligible({**base, "license": "All rights reserved"})
    assert not fma.eligible({"title": "", "artist": "Band", "license": "Creative Commons Attribution"})


def test_fma_selection_is_deterministic_and_spreads_genres():
    tracks = [{"track_id": i, "genre": f"g{i % 4}", "title": "t", "artist": "a",
               "license": "Creative Commons Attribution"} for i in range(100)]
    chosen = fma.choose(tracks)
    assert chosen == fma.choose(list(reversed(tracks)))
    assert len(chosen) == fma.GALLERY
    counts = {g: sum(t["genre"] == g for t in chosen) for g in ("g0", "g1", "g2", "g3")}
    assert max(counts.values()) - min(counts.values()) <= 1


def test_remote_file_reads_through_ranges(monkeypatch):
    payload = bytes(range(256)) * 50
    requests = []

    class Response(io.BytesIO):
        def __init__(self, data, status, headers=None):
            super().__init__(data)
            self.status, self.headers = status, headers or {}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(request, timeout):
        if request.get_method() == "HEAD":
            return Response(b"", 200, {"Content-Length": str(len(payload))})
        start, stop = map(int, request.headers["Range"].split("=")[1].split("-"))
        requests.append((start, stop))
        return Response(payload[start:stop + 1], 206)

    monkeypatch.setattr(fma.urllib.request, "urlopen", urlopen)
    remote = fma.RemoteFile("http://example.invalid/archive.zip", block=1000)
    remote.seek(-10, io.SEEK_END)
    assert remote.read(10) == payload[-10:]
    remote.seek(995)
    assert remote.read(10) == payload[995:1005]           # spans two blocks
    assert remote.transferred == sum(stop - start + 1 for start, stop in requests)


def test_experiment_configurations_cover_both_indexes_and_metrics():
    assert {experiment.parse_config(c) for c in experiment.CONFIGS} == {
        ("ivf", Metric.EUCLIDEAN), ("ivf", Metric.COSINE), ("hnsw", Metric.EUCLIDEAN), ("hnsw", Metric.COSINE)}
    assert experiment.SIZES == (1_000, 10_000, 100_000) and experiment.K == 10


def test_child_results_are_reused_not_recomputed(tmp_path, monkeypatch):
    (tmp_path / "build_1000_ivf-cosine.json").write_text(json.dumps({"seconds": 1.5}))
    monkeypatch.setattr(experiment.subprocess, "run", lambda *a, **k: pytest.fail("must not rerun"))
    assert experiment.child(tmp_path, "build_1000_ivf-cosine", "build") == {"seconds": 1.5}


def test_memory_reset_and_measurement_use_procfs():
    experiment.reset_peak()
    before = experiment.memory()
    block = np.ones(20_000_000, dtype=np.uint8)            # ~19 MiB
    after = experiment.memory()
    assert after["peak_mib"] >= before["peak_mib"] + 15
    del block
