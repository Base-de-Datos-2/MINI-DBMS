set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
original="${MINIDBMS_REPOSITORY:-$(CDPATH= cd -- "$script_dir/../../.." && pwd)}"
implementation="${MINIDBMS_IMPLEMENTATION_DIR:-${TMPDIR:-/tmp}/minidbms-implementation-20261004}"
python="$implementation/env/bin/python"
cp -a "$original/benchmarks" "$implementation/source/"
cd "$implementation/source"
export PYTHONPATH="$PWD"
"$python" "$original/docs/implementacion/evidencias/conservar_experimento_espacial.py" \
    --source "${MINIDBMS_SPATIAL_RESULTS:?Set the completed spatial results directory}" \
    --destination "$original/benchmarks/results/spatial/2026-10-04" \
    --figures "$original/docs/figuras/spatial" \
    > "$original/docs/implementacion/evidencias/espacial_graficos.log" 2>&1
"$python" "$original/scripts/sanitize_evidence.py" "$original/docs/implementacion/evidencias/espacial_graficos.log"
cat "$original/docs/implementacion/evidencias/espacial_graficos.log"
