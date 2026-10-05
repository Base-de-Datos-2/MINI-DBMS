import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import tempfile

# Permite elegir la copia aislada del proyecto en PYTHONPATH; la raiz es fallback.
sys.path.append(str(Path(__file__).resolve().parents[3]))
from engine.catalog import Column, DataType, Schema
from engine.storage import HeapFile, Record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    schema = Schema([Column('id', DataType.INTEGER), Column('value', DataType.VARCHAR)])
    result = dict(input=[1, 2, 3], payload_lengths=[3200, 3200, 100])
    with tempfile.TemporaryDirectory(prefix='minidbms-audit-heap-') as temporary:
        path = Path(temporary) / 'arrival.heap'
        with HeapFile.create(path, schema) as heap:
            rids = [heap.insert(Record(schema, [identity, 'x' * size]))
                    for identity, size in zip(result['input'], result['payload_lengths'])]
            result['scan'] = [row.values[0] for _, row in heap.scan()]
            result['rids'] = [asdict(rid) for rid in rids]
        with HeapFile.open(path, schema) as heap:
            result['reopened_scan'] = [row.values[0] for _, row in heap.scan()]
    output = json.dumps(result, indent=2) + '\n'
    if args.output:
        args.output.write_text(output, encoding='utf-8')
    print(output, end='')
    # Defecto esperado del HEAD auditado; si cambia, revisar la evaluacion.
    assert result['scan'] == result['reopened_scan'] == [1, 3, 2]


if __name__ == '__main__':
    main()
