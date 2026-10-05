set -eu
original='/workspace/mini-dbms'
implementation='/local-user/.cache/minidbms-implementation-20261004'
python="$implementation/env/bin/python"
cp -a "$original/engine" "$original/benchmarks" "$original/api" "$original/scripts" "$original/pyproject.toml" "$implementation/source/"
cd "$implementation/source"
export PYTHONPATH="$PWD"
stage="$1"
shift
run_dir=$(mktemp -d "$implementation/spatial-$stage-XXXXXX")
source_commit=$(git -C "$original" rev-parse HEAD)
"$python" -m benchmarks.spatial run --output "$run_dir/results" --container minidbms-backend-bench-20261004 --source-commit "$source_commit" "$@" > "$original/docs/implementacion/evidencias/espacial_experimento_$stage.log" 2>&1
printf '%s\n' "$run_dir/results" > "$original/docs/implementacion/evidencias/espacial_experimento_$stage.path"
tail -n 25 "$original/docs/implementacion/evidencias/espacial_experimento_$stage.log"
