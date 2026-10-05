# Comandos y reproducciones de la auditoría

Base original: commit 841977a36c4e88e412f263bd1b83347ad0eb7e1b; ver commit.txt. Los scripts de esta carpeta son evidencias nuevas, no tests incorporados al proyecto. Ejecutar siempre sobre una copia y directorios de datos nuevos. No reutilizar la base demo del usuario.

## Ejecución registrada

Desde PowerShell, en la raíz del proyecto:

~~~powershell
wsl bash 'docs/auditoria/evidencias/preparar_entorno.sh'
wsl bash 'docs/auditoria/evidencias/verificar.sh'
~~~

Los scripts registran rutas absolutas del entorno usado. Para repetir, copiar los scripts a un directorio temporal, cambiar audit_base por una ruta nueva y elegir otra carpeta de salida evidence. No sobrescribir las evidencias de esta auditoría. preparar_entorno.sh exporta HEAD con git archive e instala las dependencias dentro de esa copia. verificar.sh ejecuta:

~~~bash
python -m pytest -q -W error --basetemp "$audit_base/pytest-temp" -o cache_dir="$audit_base/pytest-cache" --junitxml="$evidence/pytest.xml"
python -W error -m demos.transactions_demo
cd frontend
npm run typecheck
npm test
npm run build
cd ..
python scripts/integration_check.py --data-dir "$audit_base/http-data" --port 18765 --report "$evidence/integracion_http.json"
python -m playwright install chromium
~~~

Aquí python representa audit_base/env/bin/python; las variables y redirecciones exactas están en verificar.sh. El comando HTTP terminó con estado 1 por tres verificaciones operativas fallidas, no por falta de arranque o fallo transaccional.

## Navegador real y espacial

Después de instalar Chromium y sus bibliotecas privadas, desde la copia aislada:

~~~bash
audit_base='/local-user/.cache/minidbms-audit-20261004'
evidence='/workspace/mini-dbms/docs/auditoria/evidencias'
cd "$audit_base/source"
export PYTHONPATH="$PWD"
export PLAYWRIGHT_BROWSERS_PATH="$audit_base/browsers"
export LD_LIBRARY_PATH="$audit_base/browser-libs/root/usr/lib/x86_64-linux-gnu"
"$audit_base/env/bin/python" "$evidence/probar_navegador.py" --evidence "$evidence" --data "$audit_base/browser-data-4" --port 18768
"$audit_base/env/bin/python" "$evidence/probar_espacial.py" --evidence "$evidence" --data "$audit_base/spatial100k-data"
~~~

Las rutas anteriores identifican el ensayo registrado; reemplazar base, salida y directorios de datos para nuevas ejecuciones. Las bibliotecas faltantes se resolvieron descargando paquetes de Ubuntu con apt-get download y extrayendo con dpkg-deb -x bajo audit_base/browser-libs/root. bibliotecas_navegador.log y los intentos 1–3 conservan la causa. En un entorno con Chromium funcional no hace falta esa extracción.

probar_navegador.py arranca su servidor y lo cierra en finally; usa dos páginas con sesiones diferentes. probar_espacial.py genera 100.000 filas y compara R-Tree, scan y referencia matemática independiente. Ambos exigen bases independientes del usuario.

## Reproducción del Heap

Desde la raíz original (solo importa módulos; crea y elimina un TemporaryDirectory):

~~~powershell
$env:PYTHONIOENCODING='utf-8'
python docs/auditoria/evidencias/probar_heap_llegada.py
~~~

Resultado del HEAD auditado: entrada [1,2,3]; scan y reapertura [1,3,2]. El script verifica ese defecto esperado. --output permite guardar JSON en una ruta nueva. Después de una corrección deberá cambiarse la aceptación a [1,2,3]; no usar este assert como test de conformidad del requisito.

## Inspección y regeneración de documentos

Desde la raíz original:

~~~powershell
$env:PYTHONPATH=(Get-Location).Path
python docs/auditoria/evidencias/inspeccionar.py
python docs/auditoria/evidencias/contrastar_reportes.py --evidence docs/auditoria/evidencias
python docs/auditoria/evidencias/catalogo.py
python docs/auditoria/evidencias/evaluar.py
python docs/auditoria/evidencias/redactar.py
python docs/auditoria/evidencias/verificar_integridad.py
~~~

inspeccionar.py examina código, imports y los JSONL oficiales; contrastar_reportes.py regenera tablas/gráficas. catalogo.py y evaluar.py recrean el denominador y la evaluación fijada; no descubren automáticamente implementaciones nuevas. Si cambia el proyecto, actualizar la evaluación con evidencia actual antes de recalcular. verificar_integridad.py comprueba trazabilidad/cálculos/preservación y actualiza el manifiesto de huellas.

## Repetición selectiva diagnóstica de 1k

La ejecución usó el CLI python -m benchmarks run, que llama a file_organization e indexes: tamaño 1.000, una repetición y presupuesto de carga mixta 3 s, con run-id auditoria_20261004_1k. El siguiente comando reproduce su configuración, con variables apuntando a una copia y a una salida de evidencias nueva. Para repetir, elegir rutas nuevas; el harness añade registros al JSONL existente.

~~~bash
"$audit_base/env/bin/python" -m benchmarks run --experiment all --sizes 1000 --repetitions 1 --workload-budget-seconds 3 --run-id auditoria_20261004_1k --workdir "$audit_base/benchmark-1k" --results "$evidence/repeticion_1k.jsonl"
~~~

Los JSONL guardan la configuración. El reporte oficial se regeneró mediante contrastar_reportes.py, que llama a benchmarks.report.render. Las 35 filas diagnósticas no sustituyen las 455 oficiales ni sus repeticiones. La ejecución coincidió con el ensayo espacial y no se usa para comparar tiempos.

No se ejecutaron comparaciones GiST/GIN ni experimentos multimedia: faltan sus harnesses completos. Sí existe preparación espacial GiST y logs históricos de E1. La consulta actual docker ps falló por daemon no disponible, como registra comparador_entorno_actual.json. No hay un resultado histórico usado como sustituto de una ejecución no disponible.
