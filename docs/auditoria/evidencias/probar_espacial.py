import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path

from api.database import Database
from benchmarks.spatial.datasets import FIXTURE_POLYGON, point_rows, query_centers
from engine.query import parse_sql
from engine.spatial.geometry import Metric, Point, Polygon
from engine.spatial.metadata import EARTH_RADIUS_METRES, ORIGIN
from scripts.setup_spatial import SPATIAL_DATABASE, prepare


def reference_distance(center, latitude, longitude, metric):
    if metric is Metric.EUCLIDEAN:
        dx = EARTH_RADIUS_METRES * math.cos(math.radians(ORIGIN[0])) * math.radians(longitude-center.longitude)
        dy = EARTH_RADIUS_METRES * math.radians(latitude-center.latitude)
        return math.sqrt(dx*dx + dy*dy)
    def unit(latitude, longitude):
        phi, lam = math.radians(latitude), math.radians(longitude)
        return (math.cos(phi)*math.cos(lam), math.cos(phi)*math.sin(lam), math.sin(phi))
    a, b = unit(center.latitude, center.longitude), unit(latitude, longitude)
    cross = (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
    return EARTH_RADIUS_METRES * math.atan2(math.sqrt(sum(value*value for value in cross)),
                                           sum(x*y for x, y in zip(a, b)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.data, size=100000)
    raw = list(point_rows(100000))
    checks = []
    with Database.open(SPATIAL_DATABASE, args.data) as database:
        structural = database._spatial_indexes['puntos'].validate_structure()
        for _, latitude, longitude in query_centers()[:3]:
            center = Point(latitude, longitude)
            for metric in Metric:
                distances = [(reference_distance(center, lat, lon, metric), identity)
                             for identity, _, lat, lon in raw]
                ordered = sorted(distances)
                for family, parameters in [('radius', (1000, 5000, 10000)), ('knn', (10, 50, 100))]:
                    for value in parameters:
                        query = getattr(database, 'spatial_' + family)
                        indexed = query('puntos', center, value, metric=metric)
                        scan = query('puntos', center, value, metric=metric, use_index=False)
                        expected = (sorted(identity for distance, identity in distances if distance < value)
                                    if family == 'radius' else [identity for _, identity in ordered[:value]])
                        actual = [hit.identity for hit in indexed.hits]
                        passed = actual == expected and indexed.hits == scan.hits
                        checks.append(dict(family=family, parameter=value, metric=metric.value,
                                           center=asdict(center), passed=passed, returned=len(actual),
                                           stats=asdict(indexed.stats)))
        polygon = Polygon(tuple(Point(*pair) for pair in FIXTURE_POLYGON))
        indexed = database.spatial_polygon('puntos', polygon)
        expected = sorted(identity for identity, _, lat, lon in raw
                          if -12.06 <= lat <= -12.02 and -77.06 <= lon <= -77.02
                          and not (lat > -12.04 and lon > -77.04))
        checks.append(dict(family='polygon', passed=[hit.identity for hit in indexed.hits] == expected,
                           returned=len(indexed.hits), stats=asdict(indexed.stats)))
        before = [hit.identity for hit in database.spatial_knn('puntos', Point(*ORIGIN), 10).hits]
    with Database.open(SPATIAL_DATABASE, args.data) as database:
        after = [hit.identity for hit in database.spatial_knn('puntos', Point(*ORIGIN), 10).hits]
        checks.append(dict(family='fresh_owner_reopen', passed=before == after))
    sql_failures = []
    examples = [
        'SELECT * FROM tiendas WHERE distancia(ubicacion, POINT(-12.0464, -77.0428)) < 5000',
        'SELECT * FROM restaurantes ORDER BY distancia(ubicacion, mi_ubicacion) LIMIT 10',
        "SELECT * FROM documentos WHERE MATCH(contenido, 'base de datos vectorial') USING TF_IDF LIMIT 10",
        "SELECT *, SCORE() as relevancia FROM articulos WHERE MATCH(texto, 'machine learning') USING BM25 ORDER BY relevancia DESC",
        "SELECT * FROM imagenes WHERE SIMILAR_TO('foto_consulta.jpg', k=10) USING HNSW WITH METRIC=cosine",
        "SELECT nombre, artista, SIMILARITY_SCORE() as score FROM canciones WHERE SIMILAR_TO('audio_query.mp3', k=5) USING IVF WITH METRIC=euclidean ORDER BY score DESC",
    ]
    for sql in examples:
        try:
            parse_sql(sql)
            sql_failures.append(dict(sql=sql, supported=True))
        except Exception as error:
            sql_failures.append(dict(sql=sql, supported=False, error=type(error).__name__, message=str(error)))
    document = dict(size=100000, real_heap=True, structural=structural, checks=checks,
                    passed=sum(item['passed'] for item in checks), total=len(checks),
                    sql_examples=sql_failures, purpose='Functional validation, not the required 100-query experiment')
    (args.evidence / 'espacial_100k_real.json').write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({key: document[key] for key in ['size', 'real_heap', 'structural', 'passed', 'total']}, indent=2))
    return 0 if all(item['passed'] for item in checks) else 1


if __name__ == '__main__':
    raise SystemExit(main())
