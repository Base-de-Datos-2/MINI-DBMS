set -eu
original='/mnt/c/Users/Ian/Desktop/UTEC/TRABAJOS (PAGOS)/Paolo - BD2'
implementation='/home/ian/.cache/minidbms-implementation-20261004'
python="$implementation/env/bin/python"
cp -a "$original/api" "$original/engine" "$original/scripts" "$original/benchmarks" "$implementation/source/"
cd "$implementation/source"
export PYTHONPATH="$PWD"
run_dir=$(mktemp -d "$implementation/spatial-http-XXXXXX")
"$python" scripts/spatial_integration_check.py --data-dir "$run_dir/database" --port 18811 --report "$original/docs/implementacion/evidencias/espacial_servidor.json" > "$original/docs/implementacion/evidencias/espacial_servidor.log" 2>&1
tail -n 24 "$original/docs/implementacion/evidencias/espacial_servidor.log"
