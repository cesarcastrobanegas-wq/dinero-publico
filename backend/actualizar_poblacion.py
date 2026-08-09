# encoding: utf-8
"""
Descarga la población oficial (INE, Cifras Oficiales de Población de los
Municipios Españoles: Revisión del Padrón Municipal) de cada municipio de
las 5 provincias que cubre esta app, y genera backend/poblacion.json.

Fuente: API pública Tempus3 del INE (servicios.ine.es/wstempus), sin
scraping HTML ni sesión -- un GET por tabla, JSON directo. Cada provincia
tiene su propia tabla dentro de esta operación ("Población por municipios
y sexo"), con un identificador numérico PERMANENTE (a diferencia de los
ficheros de Hacienda, cuyo nombre de fichero cambia con la fecha de
publicación): cuando el INE publique el padrón del año siguiente, la misma
tabla añade el dato nuevo sola, sin tocar este script.
  Murcia    -> tabla 2883  https://www.ine.es/jaxiT3/Tabla.htm?t=2883
  Girona    -> tabla 2870  https://www.ine.es/jaxiT3/Tabla.htm?t=2870
  Lleida    -> tabla 2878  https://www.ine.es/jaxiT3/Tabla.htm?t=2878  (2026-08-09)
  Barcelona -> tabla 2861  https://www.ine.es/jaxiT3/Tabla.htm?t=2861  (2026-08-09)
  Tarragona -> tabla 2900  https://www.ine.es/jaxiT3/Tabla.htm?t=2900  (2026-08-09)

?nult=1 devuelve solo el último dato publicado de cada serie. Cada serie es
una combinación municipio×sexo; se filtran las de "Total" (ambos sexos).

TRAMPA verificada a mano el 2026-08-04 con las dos tablas: la SEGUNDA fila
de "Nombre" (p.ej. "Girona. Total. Total habitantes. Personas.") es en
realidad el agregado de TODA la provincia, no un municipio -- comparte
literalmente el mismo nombre que la capital de esa provincia (que sí es un
municipio y aparece más abajo, en su posición alfabética real, con su
población mucho menor). Sin descartar esa primera fila, "Girona" en el
diccionario de salida acabaría teniendo el total provincial (832.026) en
vez de la población real de la capital (108.666) si el orden de iteración
cambiase alguna vez. Por eso se descarta explícitamente la primera entrada
y se valida el recuento final contra el número de municipios esperado.

Uso:  python actualizar_poblacion.py
(Solo usa 'requests', ya en requirements.txt.)
"""
import json
import re
import sys
import time

import requests

sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
from app import BASE_DIR, normalizar
from actualizar_alcaldes import _emparejar_municipio, MUNICIPIOS_POR_PROV_MIN

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36"}

TABLAS = {
    "Murcia": {"id": 2883, "provincia": "murcia"},
    "Girona": {"id": 2870, "provincia": "girona"},
    # IDs localizados y verificados en vivo el 2026-08-09 contra la propia
    # API (filas de "Total.Total habitantes" tras descartar el agregado
    # provincial: Lleida 231, Barcelona 311, Tarragona 184 -- coincide
    # exactamente con el nº de municipios oficiales de cada provincia).
    "Lleida": {"id": 2878, "provincia": "lleida"},
    "Barcelona": {"id": 2861, "provincia": "barcelona"},
    "Tarragona": {"id": 2900, "provincia": "tarragona"},
}
API_URL = "https://servicios.ine.es/wstempus/js/ES/DATOS_TABLA/{tabla_id}?nult=1"
URL_TABLA_HTML = "https://www.ine.es/jaxiT3/Tabla.htm?t={tabla_id}"

OUT_FILE = f"{BASE_DIR}/poblacion.json"

# El INE llama "Castell-Platja d'Aro" (nombre oficial abreviado) al
# municipio que esta app tiene con su nombre largo completo -- único
# desajuste de nomenclátor encontrado al ejecutar este script por primera
# vez (2026-08-04); mismo patrón que ALIAS_ISPA en actualizar_retribuciones.py.
ALIAS_POBLACION = {
    "Castell-Platja d'Aro": "Castell d'Aro, Platja d'Aro i s'Agaró",
    "Masarac": "Masarac i Vilarnadal",
}


def _descargar_tabla(session, tabla_id):
    r = session.get(API_URL.format(tabla_id=tabla_id), timeout=30)
    r.raise_for_status()
    return r.json()


def _filas_total(datos_json):
    """Series de población total (ambos sexos) de una tabla, DESCARTANDO
    la primera (agregado de toda la provincia -- ver docstring del módulo)."""
    totales = [s for s in datos_json if ". Total. Total habitantes." in s.get("Nombre", "")]
    if not totales:
        raise RuntimeError("no se encontraron series 'Total. Total habitantes.' en la tabla")
    return totales[1:]  # descarta el agregado provincial


def main():
    session = requests.Session()
    session.headers.update(HEADERS)

    resultado = {}
    sin_match = []

    for provincia_ine, cfg in TABLAS.items():
        tabla_id = cfg["id"]
        provincia_key = cfg["provincia"]
        esperados = len(MUNICIPIOS_POR_PROV_MIN[provincia_ine])
        print(f"Descargando tabla {tabla_id} ({provincia_ine})...")
        datos_json = _descargar_tabla(session, tabla_id)
        filas = _filas_total(datos_json)

        if len(filas) != esperados:
            print(f"  [aviso] {len(filas)} filas tras descartar el agregado, "
                  f"se esperaban {esperados} municipios de {provincia_ine} -- "
                  f"revisar a mano si el INE cambió la estructura de la tabla.")

        for serie in filas:
            nombre_crudo = serie["Nombre"].split(".")[0].strip()
            nombre_crudo = ALIAS_POBLACION.get(nombre_crudo, nombre_crudo)
            muni = _emparejar_municipio(nombre_crudo, provincia_ine)
            if not muni:
                sin_match.append((provincia_ine, nombre_crudo))
                continue
            dato = serie["Data"][0]
            resultado[normalizar(muni)] = {
                "municipio": muni,
                "provincia": provincia_key,
                "poblacion": int(dato["Valor"]),
                "anio": dato["Anyo"],
            }
        print(f"  {len(filas)} filas procesadas.")
        time.sleep(0.3)

    salida = {
        "generado": time.strftime("%Y-%m-%d %H:%M:%S"),
        "fuente_url": {
            cfg["provincia"]: URL_TABLA_HTML.format(tabla_id=cfg["id"])
            for cfg in TABLAS.values()
        },
        "municipios": resultado,
    }
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=1)

    print()
    for provincia_ine, cfg in TABLAS.items():
        esperados = len(MUNICIPIOS_POR_PROV_MIN[provincia_ine])
        n = sum(1 for v in resultado.values() if v["provincia"] == cfg["provincia"])
        print(f"Población -- {provincia_ine}: {n}/{esperados}")
    if sin_match:
        print(f"\nSin emparejar ({len(sin_match)}): {sin_match}")
    print(f"\nGuardado en {OUT_FILE}")


if __name__ == "__main__":
    main()
