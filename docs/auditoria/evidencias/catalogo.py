import json
from pathlib import Path

ROWS = []


def add(part, stage, page, section, title, criteria):
    number = 1 + sum(r['parte'] == part and r['etapa'] == stage for r in ROWS)
    ROWS.append(dict(id=f'{part}.{stage}.{number}', parte=part, etapa=stage,
                     pagina=page, seccion=section, requisito=title,
                     criterios=criteria.split('|')))


for title, criteria in [
    ('Heap File en páginas de disco', 'Registros codificados en páginas|Escritura y lectura de archivos reales|Reapertura conserva filas'),
    ('Heap sin ordenamiento por clave y con inserción en orden de llegada', 'Inserción inicial conserva llegada|No ordena por clave|Política de reutilización explícita'),
    ('Reutilización de espacio libre del Heap', 'Borrado libera espacio|Inserción reutiliza espacio|Reapertura reconstruye reutilización'),
    ('Inserción ordenada en Archivo Secuencial Paginado', 'Entradas desordenadas quedan ordenadas|División multipágina conserva orden|Reapertura conserva orden'),
    ('Eliminación lazy del secuencial', 'Borrado lógico|Scan excluye eliminados|Persistencia de tombstones'),
    ('Estrategia de reorganización del secuencial', 'Criterio de activación documentado|Reorganización compacta|Filas e índices conservan coherencia')]:
    add('1','1',1,'2.1.1',title,criteria)
for title, criteria in [
    ('Índice B+ agrupado', 'B+ propio|Almacenamiento ordenado por clave indexada|Igualdad y rango correctos|Mantenimiento tras mutaciones'),
    ('Índice B+ no agrupado', 'B+ propio|RIDs hacia almacenamiento independiente|Igualdad y rango correctos|Mantenimiento tras mutaciones'),
    ('Hash dinámico extensible', 'Directorio y profundidades|Split y doubling|Igualdad y colisiones|Borrado y reapertura'),
    ('ORDER BY con External Sorting k-way merge', 'Generación de runs en disco|Merge k-way|Integración SQL|Resultados y limpieza'),
    ('GROUP BY optimizado con hashing externo o índices', 'Algoritmo propio compatible|Ruta externa o indexada real|Integración SQL|Agregados correctos'),
    ('JOIN optimizado con hashing externo o índices', 'Algoritmo propio compatible|Ruta externa o indexada real|Integración SQL|Multiplicidad correcta')]:
    add('1','2',1,'2.1.2',title,criteria)
for title, criteria in [
    ('SELECT y WHERE básicos', 'Parser y AST|Binding de tablas y columnas|Ejecución y resultados|Errores controlados'),
    ('INSERT INTO VALUES', 'Sintaxis requerida|Escritura real|Mantenimiento de índices'),
    ('DELETE WHERE', 'Sintaxis requerida|Selección y borrado exactos|Mantenimiento de índices')]:
    add('1','3','1–2','2.1.3',title,criteria)
for title, criteria in [
    ('BEGIN TRANSACTION y END TRANSACTION', 'Agrupación entre sentencias|Publicación al END|Aislamiento por sesión'),
    ('Control de concurrencia para múltiples usuarios', 'Locks o mecanismo equivalente propio|Lectores y escritores concurrentes|Conflictos gestionados correctamente'),
    ('Demostración obligatoria con threads', 'Transacciones simultáneas|Race condition reproducida|Resultado protegido comparado con referencia')]:
    add('1','4',2,'2.1.4',title,criteria)
for title, criteria in [
    ('Panel de Archivos', 'Tablas cargadas visibles|Estructura de tablas visible'),
    ('Panel de Consultas', 'Editor SQL|Envío al motor'),
    ('Panel de Resultados', 'Resultados reales en tabla|Errores visibles'),
    ('Panel de Plan de Ejecución', 'Operadores reales|Índices realmente usados|Orden de operaciones')]:
    add('1','5',2,'2.1.5',title,criteria)
for title, criteria in [
    ('Comparación experimental Heap frente a secuencial', 'Datos 1000 10000 100000|Tiempo inserción|Búsqueda PK|Espacio disco|Reorganización'),
    ('Comparación experimental B+ agrupado no agrupado y hash', 'Tres estructuras reales|Igualdad|Rango|Ordenamiento|Construcción|Consulta|Espacio adicional|Inserciones y borrados frecuentes'),
    ('Gráficos comparativos relacionales', 'Gráficos existentes|Correspondencia con datos crudos'),
    ('Tabla de ventajas y desventajas relacionales', 'Todas las técnicas requeridas|Ventajas y desventajas'),
    ('Conclusiones de cuándo usar cada estructura', 'Heap y secuencial|B+ agrupado y no agrupado y hash|Conclusiones respaldadas por mediciones')]:
    add('1','6',2,'2.1.6',title,criteria)
for title, criteria in [
    ('R-Tree propio sobre puntos latitud longitud', 'Nodos y MBR propios|Inserción y división|Árbol multinivel|Persistencia y asociación con datos'),
    ('Consultas espaciales por rango o radio', 'Resultados correctos|Traversal del índice real|Validación contra secuencial'),
    ('k vecinos más cercanos', 'Orden por distancia|k y empates|Traversal indexado real'),
    ('Intersección de puntos con polígonos', 'Filtro MBR|Predicado geométrico exacto|Límites y polígonos cóncavos'),
    ('Distancia Euclidiana', 'Métrica implementada|Unidades y proyección explícitas|Resultado verificado'),
    ('Distancia geodésica Haversine', 'Fórmula implementada|Unidades explícitas|Resultado verificado')]:
    add('2','1',3,'2.2.1',title,criteria)
for title, criteria in [
    ('Panel de mapa interactivo', 'Mapa interactivo|Puntos almacenados visibles'),
    ('Resultados espaciales resaltados en el mapa', 'Consultas conectadas al mapa|Resultados resaltados')]:
    add('2','2',3,'2.2.2',title,criteria)
for title, criteria in [
    ('SQL espacial por distancia y POINT', 'Sintaxis espacial|Binding de ubicación|Ejecución con resultados reales'),
    ('SQL espacial k-NN por distancia y LIMIT', 'Ordenamiento por distancia|Límite k|Integración con motor espacial')]:
    add('2','3',3,'2.2.3',title,criteria)
for title, criteria in [
    ('Comparador secuencial R-Tree propio y GiST PostgreSQL', 'Secuencial medido|R-Tree medido|GiST medido|Consultas y datos equivalentes'),
    ('Experimentos espaciales con radios k y tamaños requeridos', 'Radios 1 5 10 km|k 10 50 100|1000 10000 100000 puntos'),
    ('Tiempos espaciales de construcción y consulta', 'Tiempo construcción|Promedio de 100 consultas'),
    ('Memoria y espacio en disco espaciales', 'Memoria medida|Disco medido'),
    ('Presentación experimental espacial', 'Gráficas comparativas|Tabla de cuándo usar cada técnica')]:
    add('2','4',3,'2.2.4',title,criteria)
for title, criteria in [
    ('Índice invertido con SPIMI', 'Procesamiento de documentos|Bloques SPIMI|Postings y merge propios'),
    ('Ranking TF-IDF con similitud coseno', 'Pesos TF-IDF|Coseno|Ranking correcto'),
    ('Ranking BM25', 'Fórmula y estadísticas|Ranking correcto')]:
    add('3','1',3,'2.3.1',title,criteria)
for title, criteria in [
    ('Comparación TF-IDF Coseno BM25 y GIN PostgreSQL', 'Tres técnicas medidas|Mismas consultas'),
    ('Datasets y longitud de consulta textual', '1000 10000 100000 documentos|Consultas 1 3 y 5+ palabras'),
    ('Tiempos textuales de construcción y consulta', 'Construcción medida|Consulta medida'),
    ('Relevancia Precision@10 y Recall@10', 'Juicios de relevancia|Precision@10|Recall@10'),
    ('Uso de memoria y disco textual', 'Memoria medida|Disco medido'),
    ('Presentación experimental textual', 'Gráficas|Tabla de ventajas y desventajas')]:
    add('3','2',3,'2.3.2',title,criteria)
add('3','3','3–4','2.3.3','SQL textual MATCH USING SCORE LIMIT', 'MATCH|USING TF_IDF y BM25|SCORE y ordenamiento|LIMIT')
for title, criteria in [
    ('ExtractFeatures para imágenes mediante SIFT', 'Función de extracción|Descriptores SIFT'),
    ('ExtractFeatures para audio mediante MFCC', 'Función de extracción|Descriptores MFCC'),
    ('Cuantización Bag of Visual Audio Words', 'K-Means o Tree Quantization|Asignación de descriptores a K centroides'),
    ('Histogramas multimedia con TF-IDF de dimensión K', 'Frecuencias por palabra|Pesos TF-IDF|Vector dimensión K')]:
    add('4','1',4,'2.4.1',title,criteria)
for title, criteria in [
    ('Índice IVF', 'Índice propio|Búsqueda vectorial'),
    ('Índice HNSW', 'Grafo jerárquico propio|Búsqueda vectorial'),
    ('Métrica vectorial Euclidiana', 'Distancia alta dimensión|Integración con búsqueda'),
    ('Métrica vectorial Producto Punto', 'Producto punto|Integración con búsqueda'),
    ('Métrica vectorial Coseno', 'Coseno alta dimensión|Integración con búsqueda')]:
    add('4','2',4,'2.4.2',title,criteria)
add('4','3',4,'2.4.3','SQL multimedia SIMILAR_TO USING WITH METRIC', 'SIMILAR_TO con k|Selección IVF HNSW|WITH METRIC|SIMILARITY_SCORE y ordenamiento')
for title, criteria in [
    ('Comparación multimedia IVF HNSW y métricas', 'IVF frente a HNSW|Euclidiana frente a coseno'),
    ('Datasets multimedia y k-NN requeridos', '1000 10000 100000 imágenes audios|k igual a 10'),
    ('Tiempos y memoria multimedia', 'Tiempo construcción|Tiempo consulta|Memoria'),
    ('Recall@10 multimedia', 'Oracle de vecinos|Recall@10'),
    ('Presentación experimental multimedia', 'Gráficas tiempo tamaño|Galería de éxito y error|Tabla de recomendaciones')]:
    add('4','4',4,'2.4.4',title,criteria)
for title, criteria in [
    ('Aplicación real consume API REST o GraphQL del motor', 'Aplicación de dominio real|Consumo del API propio'),
    ('Aplicación integra al menos dos tipos de datos', 'Primer tipo funcional|Segundo tipo funcional|Integración en una experiencia'),
    ('Interfaz de aplicación demuestra capacidades', 'Flujo de usuario del dominio|Resultados multimodales reales'),
    ('Una opción de aplicación del Anexo A', 'Opción elegida|Componentes obligatorios de esa opción')]:
    add('5','1','4–7','2.5 y Anexo A',title,criteria)
for title, criteria in [
    ('Código en repositorio GitHub o GitLab', 'Código versionado|Remoto configurado|Publicación accesible verificada'),
    ('README con arquitectura y organización', 'Arquitectura documentada|Organización documentada|Correspondencia con código actual'),
    ('Manual de instalación', 'Instrucciones y dependencias|Arranque reproducible'),
    ('Video demo de 5 a 10 minutos', 'Video disponible|Duración requerida|Funcionalidades demostradas'),
    ('Informe incremental técnico', 'Diseño arquitectónico|Dominio de datos|Algoritmos|Sección experimental|Cobertura del avance multimodal'),
    ('Presentación final de 15 minutos y 5 de preguntas', 'Material de presentación|Duración prevista|Presentación final acreditada')]:
    add('T','1',5,'3',title,criteria)


if __name__ == '__main__':
    path = Path(__file__).with_name('REQUISITOS_FIJADOS.json')
    path.write_text(json.dumps(ROWS, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{len(ROWS)} requisitos y {sum(len(r["criterios"]) for r in ROWS)} criterios fijados')
