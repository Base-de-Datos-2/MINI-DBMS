set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
original="${MINIDBMS_REPOSITORY:-$(CDPATH= cd -- "$script_dir/../../.." && pwd)}"
implementation="${MINIDBMS_IMPLEMENTATION_DIR:-${TMPDIR:-/tmp}/minidbms-implementation-20261004}"
python="$implementation/env/bin/python"
uv="${MINIDBMS_UV:-${MINIDBMS_AUDIT_DIR:-${TMPDIR:-/tmp}/minidbms-audit-20261004}/bootstrap/bin/uv}"
cd "$implementation/source"
"$uv" pip check --python "$python"
"$python" -m compileall -q engine api benchmarks scripts
printf 'compileall: correcto\n'
