"""Generate the Part 4 phase-1 media fixtures (run once; outputs are committed).

Synthetic, deterministic test media for the feature/index/SQL phases. They are
labelled as generated fixtures, never as the demo or experimental corpus.

    python tests/multimedia/make_fixtures.py [--output DIR]

PNG and WAV files use only the standard library (integer image raster, seeded
noise). ffmpeg encodes the JPEG and MP3 query files; its version is recorded
in the manifest because those encoders are not byte-reproducible across
versions. Tests verify the committed bytes through manifest hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import struct
import subprocess
import tempfile
import wave
import zlib

OUTPUT = Path(__file__).resolve().parent / "fixtures"
SIZE = 160
SAMPLE_RATE = 22_050
DURATION_FRAMES = SAMPLE_RATE  # one second
ARTIST = "Generador sintético MINI-DBMS"


# --- Images ----------------------------------------------------------------

def scene(seed: int, *, shift=(0, 0), brightness=0):
    """RGB rows of a seeded scene of rectangles, discs and triangles."""
    rng = random.Random(seed)
    pixels = [[(40 + (x + y) * 60 // (2 * SIZE),) * 3 for x in range(SIZE)] for y in range(SIZE)]
    shapes = []
    for _ in range(14):
        kind = rng.choice(("rect", "disc", "tri"))
        color = tuple(rng.randrange(256) for _ in range(3))
        cx, cy = rng.randrange(10, SIZE - 10), rng.randrange(10, SIZE - 10)
        size = rng.randrange(8, 34)
        shapes.append((kind, color, cx, cy, size))
    dx, dy = shift
    for kind, color, cx, cy, size in shapes:
        cx, cy = cx + dx, cy + dy
        for y in range(max(0, cy - size), min(SIZE, cy + size + 1)):
            for x in range(max(0, cx - size), min(SIZE, cx + size + 1)):
                u, v = x - cx, y - cy
                if kind == "rect":
                    inside = abs(u) <= size and abs(v) <= size * 2 // 3
                elif kind == "disc":
                    inside = u * u + v * v <= size * size
                else:
                    inside = v >= -size and 2 * abs(u) <= v + size
                if inside:
                    pixels[y][x] = color
    if brightness:
        pixels = [[tuple(min(255, max(0, c + brightness)) for c in p) for p in row] for row in pixels]
    return pixels


def mirror(pixels):
    return [list(reversed(row)) for row in pixels]


def uniform(value):
    return [[(value,) * 3 for _ in range(SIZE)] for _ in range(SIZE)]


def png_bytes(pixels) -> bytes:
    """RGB8 PNG with filter type 0 on every row (decodable with zlib alone)."""
    height, width = len(pixels), len(pixels[0])
    raw = b"".join(b"\x00" + bytes(c for p in row for c in p) for row in pixels)

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


# --- Audio -----------------------------------------------------------------

def tones(frequencies, amplitude=0.8, detune=1.0):
    envelope = [min(1.0, i / 800, (DURATION_FRAMES - i) / 800) for i in range(DURATION_FRAMES)]
    share = amplitude / len(frequencies)
    return [envelope[i] * share * math.fsum(math.sin(2 * math.pi * f * detune * i / SAMPLE_RATE)
                                            for f in frequencies)
            for i in range(DURATION_FRAMES)]


def chirp(start, end, amplitude=0.7):
    rate = (end - start) / DURATION_FRAMES
    return [amplitude * math.sin(2 * math.pi * (start * i + rate * i * i / 2) / SAMPLE_RATE)
            for i in range(DURATION_FRAMES)]


def noise(seed, amplitude):
    rng = random.Random(seed)
    return [amplitude * (rng.random() * 2 - 1) for _ in range(DURATION_FRAMES)]


def clicks(rate_hz=8, amplitude=0.8):
    period = SAMPLE_RATE // rate_hz
    return [amplitude * math.exp(-(i % period) / 120) * math.sin(2 * math.pi * 2000 * i / SAMPLE_RATE)
            for i in range(DURATION_FRAMES)]


def mix(*signals):
    return [math.fsum(values) for values in zip(*signals)]


def wav_bytes(samples) -> bytes:
    frames = b"".join(struct.pack("<h", max(-32767, min(32767, round(s * 32767)))) for s in samples)
    with tempfile.SpooledTemporaryFile() as stream:
        with wave.open(stream, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(SAMPLE_RATE)
            writer.writeframes(frames)
        stream.seek(0)
        return stream.read()


def ffmpeg(source: bytes, suffix_in: str, suffix_out: str, *arguments: str) -> bytes:
    with tempfile.TemporaryDirectory() as directory:
        source_path = Path(directory) / f"in{suffix_in}"
        target_path = Path(directory) / f"out{suffix_out}"
        source_path.write_bytes(source)
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(source_path),
                        *arguments, "-map_metadata", "-1", "-fflags", "+bitexact",
                        "-flags:a", "+bitexact", "-flags:v", "+bitexact", str(target_path)],
                       check=True)
        return target_path.read_bytes()


def ffmpeg_version() -> str:
    return subprocess.run(["ffmpeg", "-version"], check=True, capture_output=True,
                          text=True).stdout.splitlines()[0].split(" Copyright")[0]


# --- Fixture set -----------------------------------------------------------

def build():
    """Return [(name, bytes, entry)] in manifest order."""
    images = {
        "scene_a.png": (scene(1), "gallery", None),
        "scene_b.png": (scene(2), "gallery", None),
        "scene_c.png": (scene(3), "gallery", None),
        "scene_d.png": (scene(4), "gallery", None),
        "scene_e.png": (scene(5), "gallery", None),
        "scene_f.png": (scene(6), "gallery", None),
        "scene_a_shifted.png": (scene(1, shift=(9, 6)), "gallery", "scene_a.png"),
        "scene_b_mirror.png": (mirror(scene(2)), "gallery", "scene_b.png"),
        "blank.png": (uniform(128), "invalid", None),
    }
    files = []
    for name, (pixels, role, near) in images.items():
        entry = {"modality": "image", "role": role, "format": "png", "width": SIZE, "height": SIZE,
                 "metadata": {"nombre": name.rsplit(".", 1)[0].replace("_", " ")}}
        if near:
            entry["near_duplicate_of"] = near
        if name == "blank.png":
            entry["expected_rejection"] = "no_descriptors"
        files.append((name, png_bytes(pixels), entry))
    query = ffmpeg(png_bytes(scene(1, brightness=12)), ".png", ".jpg", "-q:v", "3")
    files.append(("foto_consulta.jpg", query, {
        "modality": "image", "role": "query", "format": "jpeg", "width": SIZE, "height": SIZE,
        "near_duplicate_of": "scene_a.png",
        "metadata": {"nombre": "consulta: scene a más brillante (JPEG)"}}))
    files.append(("corrupt.jpg", bytes(random.Random(99).randrange(256) for _ in range(512)), {
        "modality": "image", "role": "invalid", "format": "garbage",
        "expected_rejection": "undecodable", "metadata": {"nombre": "bytes aleatorios"}}))

    grave = (220.0, 277.18, 329.63)
    clips = {
        "acorde_grave.wav": (tones(grave), "Acorde grave La-Do#-Mi", None),
        "acorde_agudo.wav": (tones((880.0, 1108.73, 1318.51)), "Acorde agudo La-Do#-Mi", None),
        "barrido.wav": (chirp(200, 2000), "Barrido de 200 a 2000 Hz", None),
        "ruido.wav": (noise(7, 0.3), "Ruido blanco", None),
        "pulsos.wav": (clicks(), "Pulsos a 8 Hz", None),
        "acorde_grave_variante.wav": (mix(tones(grave, amplitude=0.6), noise(8, 0.01)),
                                      "Acorde grave más suave con ruido", "acorde_grave.wav"),
        "silencio.wav": ([0.0] * DURATION_FRAMES, "Silencio", None),
    }
    for name, (samples, title, near) in clips.items():
        entry = {"modality": "audio", "role": "invalid" if name == "silencio.wav" else "gallery",
                 "format": "wav", "sample_rate": SAMPLE_RATE, "channels": 1,
                 "frames": DURATION_FRAMES, "metadata": {"nombre": title, "artista": ARTIST}}
        if near:
            entry["near_duplicate_of"] = near
        if name == "silencio.wav":
            entry["expected_rejection"] = "no_signal"
        files.append((name, wav_bytes(samples), entry))
    query = ffmpeg(wav_bytes(tones(grave, detune=1.005)), ".wav", ".mp3",
                   "-codec:a", "libmp3lame", "-b:a", "128k")
    files.append(("audio_query.mp3", query, {
        "modality": "audio", "role": "query", "format": "mp3", "sample_rate": SAMPLE_RATE,
        "channels": 1, "near_duplicate_of": "acorde_grave.wav",
        "metadata": {"nombre": "consulta: acorde grave desafinado 0,5 % (MP3)", "artista": ARTIST}}))
    files.append(("corrupt.mp3", bytes(random.Random(98).randrange(256) for _ in range(512)), {
        "modality": "audio", "role": "invalid", "format": "garbage",
        "expected_rejection": "undecodable", "metadata": {"nombre": "bytes aleatorios", "artista": ARTIST}}))
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    entries = []
    for name, data, entry in build():
        (args.output / name).write_bytes(data)
        entries.append({"name": name, "sha256": hashlib.sha256(data).hexdigest(),
                        "bytes": len(data), **entry})
    manifest = {"version": 1, "synthetic": True,
                "generator": "tests/multimedia/make_fixtures.py",
                "encoder": ffmpeg_version(), "files": entries}
    (args.output / "manifest.v1.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(entries)} fixture files written to {args.output}")


if __name__ == "__main__":
    main()
