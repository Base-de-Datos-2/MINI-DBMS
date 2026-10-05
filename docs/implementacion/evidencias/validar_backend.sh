set -eu
original='/mnt/c/Users/Ian/Desktop/UTEC/TRABAJOS (PAGOS)/Paolo - BD2'
implementation='/home/ian/.cache/minidbms-implementation-20261004'
python='/home/ian/.cache/minidbms-audit-20261004/env/bin/python'
stage="$1"
shift
mkdir -p "$implementation/source" "$implementation/results"
for component in engine api tests scripts demos benchmarks pyproject.toml; do
    cp -a "$original/$component" "$implementation/source/"
done
cd "$implementation/source"
export PYTHONPATH="$PWD"
set +e
"$python" -m pytest -q -W error "$@" --basetemp "$implementation/$stage-tests" -o cache_dir="$implementation/pytest-cache" --junitxml="$implementation/results/$stage.xml" > "$implementation/results/$stage.log" 2>&1
result=$?
tail -n 30 "$implementation/results/$stage.log"
cp "$implementation/results/$stage.log" "$original/docs/implementacion/evidencias/"
exit "$result"
