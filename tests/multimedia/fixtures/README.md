# Part 4 phase-1 media fixtures

Synthetic, deterministic files for the feature, index and SQL tests of Part 4.
They are **generated test fixtures**, not the demo collection and not the
experimental corpus; no result obtained on them is evidence about real media.

Regenerate with `python tests/multimedia/make_fixtures.py` (needs `ffmpeg`
for the JPEG/MP3 query files). `manifest.v1.json` records every file's role,
format, SHA-256, size and descriptive metadata, plus the encoder version.
PNG and WAV regeneration has been checked byte-identical on the generating
machine; `test_fixtures.py` checks the committed bytes against the manifest and
the decoded pixels/samples against the generator.

| Role | Images | Audio |
|---|---|---|
| Gallery | `scene_a`…`scene_f` (160×160 PNG of seeded shapes), `scene_a_shifted` (translated), `scene_b_mirror` (mirrored) | Five 1-second mono 22,050 Hz WAV clips (two chords, a sweep, noise, pulses) and `acorde_grave_variante` |
| Query (PDF names) | `foto_consulta.jpg`: `scene_a` brighter, JPEG | `audio_query.mp3`: low chord detuned 0.5 %, MP3 |
| Must be rejected | `blank.png` (no descriptors), `corrupt.jpg` (undecodable) | `silencio.wav` (no signal), `corrupt.mp3` (undecodable) |

`near_duplicate_of` marks the expected nearest gallery object of each variant
and query. It is a design intention for later feature tests, not a guaranteed
neighbor: phase 2 must verify it with the actual SIFT/MFCC pipeline.

Phase 2 check (16 visual words, 8 audio words): `foto_consulta.jpg` finds
`scene_a`, both image variants find their originals, and `audio_query.mp3`
finds `acorde_grave` under every metric. `acorde_grave_variante` (quieter,
with noise) is closer to `barrido` than to `acorde_grave`: a real
representation failure of bag-of-MFCC-words with level and noise changes,
kept as an error example rather than "fixed".
