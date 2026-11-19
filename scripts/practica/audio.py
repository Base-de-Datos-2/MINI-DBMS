"""Frequency sweeps with harmonics, as mono PCM WAV clips."""

from array import array
from math import cos, pi, sin
import sys
import wave


def escribir_audio(path, indice):
    tasa = 22050
    inicio = 130 + 23 * (indice % 24)
    cambio = 65 * (indice // 24 + 1)
    muestras = array("h")
    for i in range(tasa):
        t = i / tasa
        fase = 2 * pi * (inicio * t + cambio * t * t / 2)
        ventana = (1 - cos(2 * pi * t)) / 2
        muestras.append(round(10000 * ventana * (sin(fase) + 0.4 * sin(2 * fase))))
    if sys.byteorder != "little":
        muestras.byteswap()
    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, tasa, 0, "NONE", "not compressed"))
        wav.writeframes(muestras.tobytes())
