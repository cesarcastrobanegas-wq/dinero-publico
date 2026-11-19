"""Prueba de la regla de repetidos dentro del feed de menores de PLACE (mismo_contrato_repetido, 15-11-2026).
Casos sacados de los ficheros oficiales (expedientes y objetos reales, sin nombres ni NIF).
Uso: python backend/place_repetidos_prueba.py  (termina con error si algún caso no da lo esperado)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from actualizar_contratos_menores_place import mismo_contrato_repetido  # noqa: E402

# (expediente a, objeto a, expediente b, objeto b, ¿mismo contrato?)
CASOS = [
    # Majadahonda y Pinto: el mismo contrato publicado dos veces
    ("EN_37/2024", "Lijado y saneado de la carpinteria metálica exterior colegio público Antonio Machado de Majadahonda",
     "EN-F/2024/4894 (37/2024)", "FRA 77 DE FECHA 16/08/2024 - Lijado y saneado de toda la carpintería metálica de exterior", True),
    ("EN_41/2024", "Reparación puertas colegio Santa Catalina de Majadahonda",
     "EN-41/2024", "Reparación puertas colegio Santa Catalina", True),
    ("2023-14568", "Contrato menor de suministro del material necesario para crear las áreas de compostaje comunitario en el municipio de Pinto",
     "2023/14568", "Material necesario para crear áreas de compostaje comunitario en el municipio de Pinto.", True),
    ("2023-14566", "Contrato menor del suministro de material para triturado, control, almacenamiento y transporte de biorresiduos domiciliarios para la elaboración de compost",
     "2023/14566", "Material necesario para las labores de triturado, control y almacenamiento y transportes de bioresiduos domiciliarios para la elaboración de compostaje.", True),
    ("DECRETO 2025/190", "servicio de limpieza viaria durante las fiestas de la Chanfaina",
     "RESOLUCION 2025/190", "Servicio de limpieza viaria durante las fiestas de la Chanfaina", True),
    ("AYTOZAM-SS-8034/2024", "Ferralla, malla y perfil.", "AYTOZAM-DEP-8034/2024", "Ferralla, malla y perfil.", True),
    # Mismo expediente, objeto distinto: pueden ser contratos distintos
    ("2157", "30 m3 hormigón aparcamiento los olivos", "2157.....", "2 Motosierras y 2 cortacésped", False),
    ("2024/PGCM/73", "Obra de refuerzo en el anclaje de los tableros", "2024/PGCM/73.",
     "Coordinación de actividades empresariales de instalación", False),
    # Sub-expedientes, «bis», lotes: no
    ("729/2024-B", "Taller de improvisación", "729/2024-M", "Taller de improvisación", False),
    ("39/2024R", "Ejecución pista de padel", "39/2024redaccion", "Redacción proyecto ejecución pista de padel", False),
    ("CM-29/2026", "Estrategia de promoción turística", "CM-29/2026 bis", "Estrategia de promoción turística y cartelería", False),
    ("CM 5/2024 lote 1", "Material deportivo", "CM 5/2024 lote 2", "Material deportivo", False),
    ("37/2024", "Reparación de aceras", "137/2024", "Reparación de aceras", False),
    ("1163/2026", "Redacción de proyecto: calle Los Llanos", "1165/2026", "Redacción de proyecto: calle Jacinto Benavente", False),
]

fallos = 0
for ea, oa, eb, ob, esperado in CASOS:
    r = mismo_contrato_repetido({"exp": ea, "titulo": oa, "sin_iva": 100.0}, {"exp": eb, "titulo": ob, "sin_iva": 100.0})
    if bool(r) != esperado:
        fallos += 1
        print(f"MAL: {ea!r} / {eb!r} -> {r!r} (se esperaba {'sí' if esperado else 'no'})")
# importe 0: nunca basta con el expediente
if mismo_contrato_repetido({"exp": "EN_41/2024", "titulo": "a b c", "sin_iva": 0.0}, {"exp": "EN-41/2024", "titulo": "a b d", "sin_iva": 0.0}):
    fallos += 1
    print("MAL: con importe 0 no se debe dar por repetido si cambia el objeto")
print(f"{len(CASOS) + 1 - fallos} de {len(CASOS) + 1} casos bien")
sys.exit(1 if fallos else 0)
