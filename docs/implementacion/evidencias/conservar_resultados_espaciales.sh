set -eu
original='/workspace/mini-dbms'
implementation='/local-user/.cache/minidbms-implementation-20261004'
python="$implementation/env/bin/python"
cp -a "$original/benchmarks" "$implementation/source/"
cd "$implementation/source"
export PYTHONPATH="$PWD"
"$python" "$original/docs/implementacion/evidencias/conservar_experimento_espacial.py" \
    --source '/local-user/.cache/minidbms-implementation-20261004/spatial-oficial-t719Hi/results' \
    --destination "$original/benchmarks/results/spatial/2026-10-04" \
    --figures "$original/docs/figuras/spatial" \
    > "$original/docs/implementacion/evidencias/espacial_graficos.log" 2>&1
cat "$original/docs/implementacion/evidencias/espacial_graficos.log"
