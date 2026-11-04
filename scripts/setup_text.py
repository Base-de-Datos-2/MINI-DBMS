"""Prepare immutable text collections in a NEW directory, with the server stopped."""
import argparse
import csv
from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from api.database import Database, NewTable
from engine.catalog import DataType


def prepare(directory, *, csv_path=None, table='documentos', text_column='contenido',
            memory_budget_bytes=8 * 1024 * 1024):
    """Default rows are an explicitly labelled demo, never experiment evidence."""
    def collection(name, column, rows):
        return (NewTable(name, (('id', DataType.INTEGER), (column, DataType.VARCHAR))),
                rows, 'id', column)
    if csv_path is None:
        collections = [
            collection('documentos', 'contenido', [
                (1, 'Una base de datos vectorial permite buscar documentos por similitud.'),
                (2, 'La base de datos conserva registros e índices persistentes.'),
                (3, 'Un índice invertido contiene términos y frecuencias.'),
                (4, 'La búsqueda vectorial representa documentos mediante vectores.')]),
            collection('articulos', 'texto', [
                (10, 'Machine learning uses data to train a model.'),
                (11, 'Learning algorithms include machine learning and deep learning.'),
                (12, 'Database systems store and retrieve persistent records.')])]
        return Database.prepare_text(directory, collections, memory_budget_bytes=memory_budget_bytes)
    with Path(csv_path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or 'id' not in reader.fieldnames or text_column not in reader.fieldnames:
            raise ValueError(f'CSV requires id and {text_column} columns')
        rows = ((int(row['id']), row[text_column]) for row in reader)
        return Database.prepare_text(directory, [collection(table, text_column, rows)],
                                     memory_budget_bytes=memory_budget_bytes)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=REPOSITORY / 'data/generated/text')
    parser.add_argument('--csv', type=Path, help='UTF-8 CSV with id and text columns; streamed during loading')
    parser.add_argument('--table', default='documentos')
    parser.add_argument('--text-column', default='contenido')
    parser.add_argument('--memory-budget-bytes', type=int, default=8 * 1024 * 1024)
    args = parser.parse_args(argv)
    entries = prepare(args.data_dir, csv_path=args.csv, table=args.table,
                      text_column=args.text_column, memory_budget_bytes=args.memory_budget_bytes)
    for entry in entries:
        print(f'{entry.table}.{entry.column}: published and reopened; generation {entry.generation}')
    print('Demo fixture only; no benchmark results are claimed.' if args.csv is None else 'CSV collection published.')


if __name__ == '__main__':
    main()
