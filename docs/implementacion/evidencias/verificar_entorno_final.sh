set -eu
original='/workspace/mini-dbms'
implementation='/local-user/.cache/minidbms-implementation-20261004'
python="$implementation/env/bin/python"
uv='/local-user/.cache/minidbms-audit-20261004/bootstrap/bin/uv'
cd "$implementation/source"
"$uv" pip check --python "$python"
"$python" -m compileall -q engine api benchmarks scripts
printf 'compileall: correcto\n'
