# Gráficos y datos relacionales

Los PNG y `resultados.md` de esta carpeta son las mediciones históricas de
Etapa 10. Conservan los tres tamaños prescritos, con fuentes y limitaciones
en [EXPERIMENTOS.md](../EXPERIMENTOS.md). No se sobrescriben ni se atribuyen a
la versión posterior a la auditoría.

La repetición de 2026-10-04 corrige la procedencia insuficiente de las corridas
pequeñas: 1.000 y 10.000 registros, cinco repeticiones por tamaño, con el motor
corregido. Sus [11 gráficos y tabla](actualizados_1k_10k/resultados.md),
[datos, manifest, código archivado y driver](../../benchmarks/results/relational/2026-10-04/)
y [verificación](../implementacion/evidencias/relacional_verificacion.json)
están disponibles.
No son un informe académico.

## Lectura de las series

- Cada punto representa la mediana de cinco repeticiones. Las barras y tablas
  indican mínimo y máximo; no son intervalos de confianza.
- Los datasets y operaciones siguen el harness existente: Heap/secuencial,
  construcción B+ agrupado/no agrupado y hash extensible, igualdad, rangos,
  recuperación ordenada, espacio y carga mixta real.
- La carga mixta termina al alcanzar 200 operaciones o al revisar un
  presupuesto de 60 segundos entre operaciones. Una operación puede superar
  ese tiempo. La tabla registra las operaciones realmente completadas: no se
  divide siempre por 200 ni se da por terminado un objetivo incumplido.
- Los tiempos se obtuvieron en WSL2 con Python 3.11.9 y 24 CPU lógicas;
  cada ensayo es secuencial y tiene sus propios archivos temporales. La fuente
  exacta queda archivada, con hash del driver y código, aunque la copia no
  contiene `.git`. No hubo limpieza de caché ni extrapolación de valores.
- Las curvas nuevas contienen solo 1.000 y 10.000. No se incorpora como
  tercer punto el resultado histórico de 100.000, medido en otro entorno
  con una revisión anterior. Su commit y hash sí se recuperan y verifican.
- La verificación adicional comprueba 35 operaciones/configuraciones por
  repetición, claves sin duplicados, tiempos finitos, conversión de unidades,
  búsquedas presentes/ausentes, conteos analíticos de rangos, consumo completo,
  borrado del 40 %, reorganización y coherencia de las cargas mixtas.
  No se afirma que esos conteos prueben por sí solos todos los valores de las
  filas; la suite independiente del motor cubre esa corrección.

En todas las repeticiones nuevas, B+ no agrupado y hash completaron 200
operaciones (100 inserciones y 100 borrados). El agrupado completó 51
(26 inserciones, 25 borrados) a 1.000 y 5 (3 inserciones, 2 borrados) a 10.000.
Su ensayo de 10.000 duró aproximadamente 77 segundos: el presupuesto de
60 segundos se comprobaba entre operaciones, no cancelaba la última. Estas
cargas tienen prefijos y proporciones distintas; las tasas son observaciones
de cada ensayo, no una comparación de 200 operaciones idénticas. La extensión
histórica de 100.000 solo ejecutó una inserción agrupada y ningún borrado;
no se atribuye a ella una demostración de borrados frecuentes.

## Reproducción

En una copia del proyecto y directorios nuevos:

```bash
python -m benchmarks run --experiment all --sizes 1000 10000 --repetitions 5 --results /tmp/repeticion-relacional.jsonl --workdir /tmp/repeticion-relacional-trabajo
python -m benchmarks report --results /tmp/repeticion-relacional.jsonl --output /tmp/graficos-relacionales
```

La ejecución conservada utilizó el mismo harness y archivó su código antes
de medir. Los scripts `docs/implementacion/evidencias/repetir_relacional.py`
y `.sh` documentan ese archivado; no se deben ejecutar contra directorios
existentes. El verificador `verificar_relacional.py` comprueba los datos nuevos
y recupera las fuentes históricas de 100.000 directamente de Git.
