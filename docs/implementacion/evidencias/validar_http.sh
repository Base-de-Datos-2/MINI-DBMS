set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
original="${MINIDBMS_REPOSITORY:-$(CDPATH= cd -- "$script_dir/../../.." && pwd)}"
implementation="${MINIDBMS_IMPLEMENTATION_DIR:-${TMPDIR:-/tmp}/minidbms-implementation-20261004}"
python="${MINIDBMS_PYTHON:-$implementation/env/bin/python}"
cp -a "$original/api" "$original/engine" "$original/scripts" "$implementation/source/"
cd "$implementation/source"
export PYTHONPATH="$PWD"
"$python" scripts/integration_check.py --backend-only --data-dir "$implementation/http-launcher" --port 18810 --report "$original/docs/implementacion/evidencias/launcher_http.json" > "$original/docs/implementacion/evidencias/launcher_http.log" 2>&1
"$python" "$original/scripts/sanitize_evidence.py" "$original/docs/implementacion/evidencias/launcher_http.log" "$original/docs/implementacion/evidencias/launcher_http.json"
tail -n 26 "$original/docs/implementacion/evidencias/launcher_http.log"
