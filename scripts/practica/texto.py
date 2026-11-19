"""Bitácoras sintéticas reproducibles para probar recuperación en español."""

from itertools import product

SENSORES = {
    "humedad": ("higrómetro", "%", 42),
    "temperatura": ("termómetro", "grados Celsius", 18),
    "presión": ("barómetro", "hPa", 980),
    "iluminación": ("fotómetro", "lux", 360),
    "ruido": ("sonómetro", "dB", 45),
    "viento": ("anemómetro", "km/h", 9),
}
SEDES = ("Barranco", "Miraflores", "Surco", "Lince", "Breña", "Chorrillos",
         "San Miguel", "Surquillo", "Pueblo Libre", "Magdalena")


def registros():
    for numero, (dia, sede, variable) in enumerate(
        product(range(1, 21), SEDES, SENSORES), start=1
    ):
        equipo, unidad, base = SENSORES[variable]
        lectura = base + (numero * 7 + dia) % 19
        yield (numero, f"Bitácora de {sede}, día {dia}. El {equipo} de la estación "
                       f"registró una {variable} de {lectura} {unidad}. "
                       f"Referencia de calibración: sensor{numero:04d}.")
