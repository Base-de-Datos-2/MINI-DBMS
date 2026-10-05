set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
original="${MINIDBMS_REPOSITORY:-$(CDPATH= cd -- "$script_dir/../../.." && pwd)}"
implementation="${MINIDBMS_IMPLEMENTATION_DIR:-${TMPDIR:-/tmp}/minidbms-implementation-20261004}"
python="$implementation/env/bin/python"
cp -a "$original/api" "$original/engine" "$original/scripts" "$original/benchmarks" "$implementation/source/"
cd "$implementation/source"
export PYTHONPATH="$PWD"
run_dir=$(mktemp -d "$implementation/spatial-http-XXXXXX")
"$python" scripts/spatial_integration_check.py --data-dir "$run_dir/database" --port 18811 --report "$original/docs/implementacion/evidencias/espacial_servidor.json" > "$original/docs/implementacion/evidencias/espacial_servidor.log" 2>&1
"$python" "$original/scripts/sanitize_evidence.py" "$original/docs/implementacion/evidencias/espacial_servidor.log" "$original/docs/implementacion/evidencias/espacial_servidor.json"
tail -n 24 "$original/docs/implementacion/evidencias/espacial_servidor.log"
