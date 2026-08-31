# Minigestor de Base de Datos Multimodal

Proyecto académico de **Base de Datos 2 (2026-2)**. El objetivo es implementar
un motor de base de datos propio, comenzando por la Parte 1 relacional.

## Estado actual

**Etapa 1 en desarrollo:** estructura del repositorio, configuración Python,
`DataType`, `Column` y `Schema`, con pruebas unitarias.

Todavía no existen almacenamiento físico, índices, consultas SQL, transacciones,
API ejecutable ni interfaz gráfica. Los directorios correspondientes reservan
su ubicación; no representan funcionalidades implementadas.

## Requisitos e instalación

- Python **3.11 o superior**; los comandos de Windows utilizan Python 3.12.
- `pip` y `venv`.
- Sin dependencias de ejecución del motor en esta etapa; `pytest` es la única
  dependencia directa de pruebas. `setuptools` se utiliza para empaquetar.

Desde la raíz del repositorio, en **Windows / PowerShell**:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pytest -q
```

Se invoca el intérprete del entorno explícitamente: no es necesario activar el
entorno ni modificar la política de ejecución de PowerShell. Evita usar un
`python` global que pudiera apuntar a Python 2. Si utilizas otra versión de
Python compatible, ajusta el selector del primer comando.

En **Linux / macOS**, con `python3` de versión 3.11 o superior:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[test]"
.venv/bin/python -m pytest -q
```

La instalación inicial puede necesitar acceso a Internet para descargar las
dependencias de construcción y pruebas. Una vez instalado el entorno, las
pruebas no necesitan red, servicios externos ni un DBMS instalado.

## Uso del modelo actual

Abre el intérprete del entorno virtual e importa las clases del catálogo:

```python
from engine.catalog import Column, DataType, Schema

schema = Schema([
    Column("id", DataType.INTEGER),
    Column("name", DataType.VARCHAR),
    Column("active", DataType.BOOLEAN),
])

assert len(schema) == 3
assert schema.column("name") == schema.column(1)
assert schema.index_of("active") == 2
```

Este ejemplo trabaja únicamente con metadatos en memoria. No crea una tabla en
disco ni ejecuta SQL.

### Reglas del modelo

- `DataType` es un `Enum` con valores textuales estables: `INTEGER`, `FLOAT`,
  `BOOLEAN` y `VARCHAR`. `Column` exige un miembro del enum, no un texto.
- `Column` y `Schema` son inmutables. El esquema conserva una copia de las
  columnas en una tupla, respetando su orden.
- Los nombres son sensibles a mayúsculas/minúsculas y no se normalizan ni
  recortan. Se rechazan nombres vacíos o compuestos únicamente por espacios.
- `Schema` acepta una secuencia de columnas, incluida una secuencia vacía;
  rechaza elementos que no sean `Column` y nombres exactamente duplicados.
- `column(nombre_o_posicion)` accede por nombre exacto o posición entera desde
  cero. No admite posiciones negativas, booleanos ni slices.
- `index_of(nombre)` devuelve la posición; `columns`, `len(schema)` e iteración
  permiten inspeccionar el esquema.
- Se utilizan `TypeError` para tipos de argumento incorrectos, `ValueError`
  para definiciones inválidas, `KeyError` para nombres desconocidos e
  `IndexError` para posiciones fuera de rango. La jerarquía general de errores
  del motor sigue pendiente.

## Organización

```text
engine/
  catalog/       # DataType, Column y Schema
  storage/       # Reservado: RID, Record, páginas y archivos
  indexes/       # Reservado: B+ y Extendible Hashing
  operators/     # Reservado: operadores relacionales
  query/         # Reservado: parser, planificador y ejecutor
  transactions/  # Reservado: transacciones y concurrencia
api/             # Paquete reservado; aún sin servidor
frontend/        # Reservado para la interfaz
tests/
  catalog/       # Pruebas del modelo implementado
  storage/       # Reservado
  indexes/       # Reservado
  operators/     # Reservado
benchmarks/      # Reservado para experimentos
data/            # Reservado para datos
docs/            # Reservado para documentación adicional
```

Los archivos `.gitkeep` conservan en Git los directorios que aún están vacíos.
Los paquetes Python se conservan mediante sus archivos `__init__.py`.

## Arquitectura

El catálogo actual utiliza solamente la biblioteca estándar de Python. No
depende del almacenamiento, del parser, de una API ni de la interfaz gráfica.
Las demás capas se implementarán progresivamente según el plan.

## Validación

En Windows, desde la raíz:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/catalog -q
.\.venv\Scripts\python.exe -m compileall -q engine api
```

En Linux/macOS, sustituye `.\.venv\Scripts\python.exe` por `.venv/bin/python`.

## Documentos de coordinación y siguiente paso

- [REQUIREMENTS.md](REQUIREMENTS.md): requisitos académicos.
- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md): arquitectura y decisiones estables.
- [PLAN.md](PLAN.md): las diez etapas de la Parte 1.
- [ETAPA_01.md](ETAPA_01.md): tareas y criterios de cierre de la etapa vigente.
- [AGENTS.md](AGENTS.md): reglas de trabajo en el repositorio.

El siguiente componente pendiente es `RID` (tarea 1.5 de `ETAPA_01.md`).
La Etapa 1 **no está completa**: siguen pendientes `Record`, metadatos de tablas
e índices, `Catalog`, contratos, errores de dominio y la integración de la etapa.
