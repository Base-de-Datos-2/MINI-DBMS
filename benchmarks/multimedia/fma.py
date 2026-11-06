"""Acquire the Part 4 audio collection from the Free Music Archive (FMA).

The audio path is functional (PLAN_PARTE_04 §2.8): 30 gallery clips and 5
query clips. Nothing large is downloaded: both FMA zips are read as remote
files through HTTP byte ranges, so only the central directory, ``tracks.csv``
and the selected MP3 members are transferred (``zipfile`` handles Zip64).

Selection (seeded): tracks of the ``small`` subset whose license allows
derivative works (Creative Commons without "NoDerivatives"), with title and
artist, spread across genres. Deterministic clipping, recorded per clip:

* gallery clip: seconds 0–10 of the 30-second FMA excerpt;
* query clip:   seconds 15–25 of the same excerpt for 5 gallery tracks, so a
  query is a different segment of a song present in the gallery.

Clips are re-encoded with ffmpeg as mono 22,050 Hz MP3 at 64 kbit/s. The first
query is named ``audio_query.mp3`` (the PDF example).

    python -m benchmarks.multimedia.fma --output data/multimedia_demo/audio
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import random
import subprocess
import tempfile
import urllib.request
import zipfile

METADATA_URL = "https://os.unil.cloud.switch.ch/fma/fma_metadata.zip"
AUDIO_URL = "https://os.unil.cloud.switch.ch/fma/fma_small.zip"
SEED = 20_261_106
GALLERY = 30
QUERIES = 5
USER_AGENT = "mini-dbms-coursework/1.0"


class RemoteFile(io.RawIOBase):
    """Seekable read-only view of a URL using HTTP Range requests (block cache)."""

    def __init__(self, url: str, block: int = 1 << 20):
        self.url, self.block, self.position, self.cache = url, block, 0, {}
        request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response:
            self.size = int(response.headers["Content-Length"])
        self.transferred = 0

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=io.SEEK_SET):
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self.position, io.SEEK_END: self.size}[whence]
        self.position = max(0, base + offset)
        return self.position

    def _block(self, number):
        if number not in self.cache:
            start = number * self.block
            stop = min(self.size, start + self.block) - 1
            request = urllib.request.Request(self.url, headers={"User-Agent": USER_AGENT,
                                                                "Range": f"bytes={start}-{stop}"})
            with urllib.request.urlopen(request, timeout=120) as response:
                if response.status != 206:
                    raise OSError(f"Range request not honoured (HTTP {response.status})")
                self.cache[number] = response.read()
            self.transferred += len(self.cache[number])
            if len(self.cache) > 64:
                self.cache.pop(next(iter(self.cache)))
        return self.cache[number]

    def readinto(self, buffer):
        """Fill ``buffer`` across block boundaries (short only at end of file)."""
        filled = 0
        view = memoryview(buffer)
        while filled < len(view) and self.position < self.size:
            number, offset = divmod(self.position, self.block)
            data = self._block(number)[offset:offset + len(view) - filled]
            view[filled:filled + len(data)] = data
            filled += len(data)
            self.position += len(data)
        return filled


def tracks(metadata: zipfile.ZipFile) -> list[dict]:
    with metadata.open("fma_metadata/tracks.csv") as raw:
        reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8"))
        top, sub, _ = next(reader), next(reader), next(reader)   # two header rows + "track_id"
        columns = {(a, b): i for i, (a, b) in enumerate(zip(top, sub))}
        def get(row, key):
            return row[columns[key]]
        result = []
        for row in reader:
            if get(row, ("set", "subset")) != "small":
                continue
            result.append({"track_id": int(row[0]), "title": get(row, ("track", "title")).strip(),
                           "artist": get(row, ("artist", "name")).strip(),
                           "license": get(row, ("track", "license")).strip(),
                           "genre": get(row, ("track", "genre_top")).strip()})
        return result


def eligible(track: dict) -> bool:
    license_name = track["license"].lower()
    return (track["title"] and track["artist"] and "creative commons" in license_name
            and "noderiv" not in license_name and "no deriv" not in license_name
            and len(track["title"]) <= 200 and len(track["artist"]) <= 200)


def choose(candidates: list[dict]) -> list[dict]:
    rng = random.Random(SEED)
    by_genre = {}
    for track in sorted(candidates, key=lambda t: t["track_id"]):
        by_genre.setdefault(track["genre"], []).append(track)
    for genre_tracks in by_genre.values():
        rng.shuffle(genre_tracks)
    chosen, genres = [], sorted(by_genre)
    while len(chosen) < GALLERY and any(by_genre.values()):
        for genre in genres:
            if by_genre[genre] and len(chosen) < GALLERY:
                chosen.append(by_genre[genre].pop())
    return chosen


def clip(mp3: bytes, start: float, seconds: float) -> bytes:
    with tempfile.TemporaryDirectory() as directory:
        source, target = Path(directory) / "in.mp3", Path(directory) / "out.mp3"
        source.write_bytes(mp3)
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-ss", str(start), "-t", str(seconds),
                        "-i", str(source), "-ac", "1", "-ar", "22050", "-codec:a", "libmp3lame", "-b:a", "64k",
                        "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:a", "+bitexact", str(target)],
                       check=True)
        return target.read_bytes()


def run(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    metadata_file = RemoteFile(METADATA_URL)
    with zipfile.ZipFile(metadata_file) as metadata:
        candidates = [t for t in tracks(metadata) if eligible(t)]
    audio_file = RemoteFile(AUDIO_URL)
    archive = zipfile.ZipFile(audio_file)
    names = set(archive.namelist())
    chosen = []
    for track in choose(candidates):
        member = f"fma_small/{track['track_id'] // 1000:03d}/{track['track_id']:06d}.mp3"
        if member in names:
            chosen.append((track, member))
    entries = []
    for index, (track, member) in enumerate(chosen, 1):
        original = archive.read(member)
        key = f"fma_{track['track_id']:06d}.mp3"
        data = clip(original, 0.0, 10.0)
        (output / key).write_bytes(data)
        entries.append({"id": index, "track_id": track["track_id"], "media_key": key, "role": "gallery",
                        "title": track["title"], "artist": track["artist"], "genre": track["genre"],
                        "license": track["license"], "source_member": member,
                        "original_sha256": hashlib.sha256(original).hexdigest(),
                        "clip": {"start_seconds": 0.0, "duration_seconds": 10.0},
                        "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
        if index <= QUERIES:
            query_key = "audio_query.mp3" if index == 1 else f"consulta_{track['track_id']:06d}.mp3"
            query = clip(original, 15.0, 10.0)
            (output / query_key).write_bytes(query)
            entries.append({"track_id": track["track_id"], "media_key": query_key, "role": "query",
                            "same_track_as": key, "title": track["title"], "artist": track["artist"],
                            "license": track["license"], "source_member": member,
                            "clip": {"start_seconds": 15.0, "duration_seconds": 10.0},
                            "sha256": hashlib.sha256(query).hexdigest(), "bytes": len(query)})
    manifest = {"source": "Free Music Archive, fma_small (Defferrard et al., ISMIR 2017)",
                "metadata_url": METADATA_URL, "audio_url": AUDIO_URL, "seed": SEED,
                "eligible_tracks": len(candidates), "selection": "seeded round-robin across genres; CC licenses "
                "allowing derivatives", "encoding": "ffmpeg libmp3lame mono 22,050 Hz 64 kbit/s",
                "bytes_transferred": metadata_file.transferred + audio_file.transferred,
                "clips": entries}
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8")
    print(f"{sum(e['role'] == 'gallery' for e in entries)} gallery clips, "
          f"{sum(e['role'] == 'query' for e in entries)} queries, "
          f"{manifest['bytes_transferred'] / 1e6:.1f} MB transferred", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=Path("data/multimedia_demo/audio"))
    run(parser.parse_args(argv).output)


if __name__ == "__main__":
    main()
