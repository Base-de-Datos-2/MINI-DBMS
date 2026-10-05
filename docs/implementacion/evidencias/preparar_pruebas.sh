set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
original="${MINIDBMS_REPOSITORY:-$(CDPATH= cd -- "$script_dir/../../.." && pwd)}"
implementation="${MINIDBMS_IMPLEMENTATION_DIR:-${TMPDIR:-/tmp}/minidbms-implementation-20261004}"
audit="${MINIDBMS_AUDIT_DIR:-${TMPDIR:-/tmp}/minidbms-audit-20261004}"
uv="$audit/bootstrap/bin/uv"
"$uv" venv --python "$audit/env/bin/python" "$implementation/env"
"$uv" pip sync --offline --python "$implementation/env/bin/python" "$original/docs/implementacion/evidencias/entorno_pruebas.txt"
"$uv" pip install --offline --python "$implementation/env/bin/python" --no-deps -e "$implementation/source"
"$implementation/env/bin/python" -I -c 'import engine; print(engine.__file__)'
