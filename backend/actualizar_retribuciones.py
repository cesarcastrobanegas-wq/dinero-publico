# encoding: utf-8
"""
Descarga las retribuciones de alcaldes/alcaldesas publicadas anualmente por
el Portal MTDFP - Espacio ISPA (Información Salarial de Puestos de la
Administración, Ministerio para la Transformación Digital y de la Función
Pública, https://digital.gob.es/funcion-publica/dgfp/espacio-ispa) y genera
backend/retribuciones_ispa.json filtrado a los municipios de Murcia y
Girona que cubre esta app.

No hay API: es un fichero XLSX de descarga directa, publicado una vez al
año (ISPA 2025 = retribuciones del ejercicio 2024). La URL de abajo
(RETRIB_ANIO/RETRIB_URL) incluye el año de la edición y hay que
actualizarla a mano cuando el Ministerio publique la siguiente -- mismo
patrón que actualizar_alcaldes.py, no hay forma de descubrirla en runtime
sin re-scrapear la página índice del portal.

IMPORTANTE -- por qué este script NO toca concejales:
El fichero "retribuciones_concejales.xlsx" del mismo portal trae una fila
por asiento de concejal (AYUNTAMIENTO, PROVINCIA, CCAA, RÉGIMEN DEDICACIÓN,
TOTAL PERCIBIDO) pero SIN nombre ni cargo distintivo -- el campo "cargo" de
ALCALDES_CONCEJALES es siempre el literal "Concejal" para todos, así que no
hay ninguna columna en común que permita saber qué importe de esa lista
corresponde a qué concejal cuando un municipio tiene varios (el caso
mayoritario). Atribuir una fila cualquiera a un nombre concreto sería
inventar un dato que la fuente no da. El fichero de alcaldes, en cambio, SÍ
es seguro: una única fila por ayuntamiento = el sueldo de esa única
persona, sin ambigüedad. Instrucción del 2026-08-02: solo alcalde/sa con
importe, concejales solo con el resaltado de color (sin importe).

Uso:  pip install openpyxl && python actualizar_retribuciones.py
(openpyxl no está en requirements.txt por el mismo motivo que en
actualizar_alcaldes.py: solo la usa este script, no el servidor de
producción.)
"""
import io
import json
import re
import sys
import time

import openpyxl
import requests

sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
from app import BASE_DIR, normalizar
from actualizar_alcaldes import _emparejar_municipio, PROV_A_KEY

# Alias específicos del XLSX de ISPA que no coinciden con el listado propio
# de la app y que _emparejar_municipio() (heredado de actualizar_alcaldes.py)
# no resuelve por sí solo -- verificado descargando el fichero real
# (retribuciones_alcaldes.xlsx, ISPA 2025) el 2026-08-02: "Calonge" venía
# truncado (el nombre oficial es "Calonge i Sant Antoni") y "Mieres
# (Girona)" traía el paréntesis desambiguador frente al Mieres asturiano.
ALIAS_ISPA = {
    "Calonge": "Calonge i Sant Antoni",
    # Detectado 2026-08-09 al ejecutar sobre Lleida/Barcelona/Tarragona:
    # ISPA escribe este municipio sin artículo, a diferencia del XLSX del
    # Ministerio de Política Territorial (que sí usa "Pont de Suert, El").
    "Pont de Suert": "el Pont de Suert",
}


def _limpiar_nombre_ispa(nombre):
    """Quita el sufijo entre paréntesis que ISPA añade a algunos municipios
    para desambiguar homónimos de otras provincias (p.ej. 'Mieres (Girona)')."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", nombre or "").strip()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "es-ES,es;q=0.9",
}

# ISPA 2025 = retribuciones del ejercicio 2024, última edición publicada al
# escribir este script (ver digital.gob.es/funcion-publica/dgfp/espacio-ispa
# /estadisticas/informac_estad_2024). Actualizar ambas constantes cuando
# salga la siguiente edición.
RETRIB_ANIO = 2024
RETRIB_URL_ALCALDES = (
    "https://digital.gob.es/content/dam/portal-mtdfp/funcion-publica/dgfp/"
    "ispa/ispa2025/retrib_2024/retribuciones_alcaldes.xlsx"
)

OUT_FILE = f"{BASE_DIR}/retribuciones_ispa.json"

# Provincias (tal como aparecen en la columna PROVINCIA del XLSX de ISPA,
# que coincide con la nomenclatura del INE que ya usa actualizar_alcaldes.py)
# Ampliado 2026-08-09 a las 3 provincias catalanas restantes -- revisar
# sin_match tras la primera ejecución por si aparecen alias nuevos.
PROVINCIAS_CUBIERTAS = ("Murcia", "Girona", "Lleida", "Barcelona", "Tarragona")


def _descargar_xlsx(session, url):
    r = session.get(url, timeout=60)
    r.raise_for_status()
    return openpyxl.load_workbook(io.BytesIO(r.content), read_only=True, data_only=True)


def _filas_alcaldes(ws):
    """Salta las filas de título del XLSX de ISPA y devuelve tuplas
    (ayuntamiento, provincia, regimen_dedicacion, total_percibido) para
    cada fila de datos -- la cabecera real está en la columna B."""
    it = ws.iter_rows(values_only=True)
    encontrada_cabecera = False
    for row in it:
        if not encontrada_cabecera:
            if row and row[1] == "AYUNTAMIENTO":
                encontrada_cabecera = True
            continue
        if not row or not row[1]:
            continue
        yield row[1], row[2], row[4], row[5]


def main():
    session = requests.Session()
    session.headers.update(HEADERS)

    print(f"Descargando retribuciones de alcaldes (ISPA, ejercicio {RETRIB_ANIO})...")
    wb = _descargar_xlsx(session, RETRIB_URL_ALCALDES)

    resultado = {}  # clave normalizada de municipio -> datos de retribución
    n_match = 0
    sin_match = []
    n_filtradas_provincia = 0

    for ayuntamiento, provincia, regimen, importe in _filas_alcaldes(wb.active):
        if provincia not in PROVINCIAS_CUBIERTAS:
            n_filtradas_provincia += 1
            continue
        nombre_limpio = _limpiar_nombre_ispa(str(ayuntamiento).strip())
        nombre_limpio = ALIAS_ISPA.get(nombre_limpio, nombre_limpio)
        muni = _emparejar_municipio(nombre_limpio, provincia)
        if not muni:
            sin_match.append((provincia, ayuntamiento))
            continue
        try:
            importe_num = float(importe)
        except (TypeError, ValueError):
            continue
        resultado[normalizar(muni)] = {
            "municipio": muni,
            "provincia": PROV_A_KEY[provincia],
            "importe": importe_num,
            "regimen_dedicacion": (regimen or "").strip(),
            "anio": RETRIB_ANIO,
        }
        n_match += 1

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump({"generado": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "anio": RETRIB_ANIO, "municipios": resultado},
                   f, ensure_ascii=False, indent=1)

    print(f"\nAlcaldes con retribución emparejada: {n_match}")
    print(f"Filas de otras provincias descartadas: {n_filtradas_provincia}")
    if sin_match:
        print(f"\nSin emparejar ({len(sin_match)}): {sin_match[:20]}")
    print(f"\nGuardado en {OUT_FILE}")


if __name__ == "__main__":
    main()
