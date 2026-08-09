# encoding: utf-8
"""
Descarga alcaldes y concejales de la legislatura vigente desde la app
"concejalesApp" del Ministerio de Política Territorial y Memoria
Democrática (https://concejales.redsara.es/consulta/) y genera
backend/alcaldes_concejales.json filtrado a los municipios de las 5
provincias que cubre esta app (Murcia, Girona, Lleida, Barcelona, Tarragona
-- ampliado 2026-08-09, ver MUNICIPIOS_POR_PROV_MIN más abajo).

No hay una API pública documentada (sin token/Swagger): son descargas
XLSX directas por URL. Por eso este script no se llama desde las rutas
web -- se ejecuta manualmente / de forma periódica (ej. trimestral, o
tras una moción de censura conocida), y el resultado se versiona como
un JSON estático que app.py carga en memoria al arrancar.

Uso:  pip install openpyxl && python actualizar_alcaldes.py

openpyxl no está en requirements.txt a propósito: es la única dependencia
de todo el proyecto que usa este script y no el servidor de producción, así
que no tiene sentido instalarla en cada deploy de Render. Instálala aparte
en tu entorno local antes de ejecutar este script.
"""
import io
import json
import re
import sys
import time

import openpyxl
import requests

sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
from app import (BASE_DIR, MUNICIPIOS_MURCIA, MUNICIPIOS_GIRONA, MUNICIPIOS_LLEIDA,
                  MUNICIPIOS_BARCELONA, MUNICIPIOS_TARRAGONA, normalizar)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "es-ES,es;q=0.9",
}
URL_HOME = "https://concejales.redsara.es/consulta/"
URL_ALCALDES = "https://concejales.redsara.es/consulta/getAlcaldesLegislatura"
URL_CONCEJALES = "https://concejales.redsara.es/consulta/getConcejalesLegislatura"

OUT_FILE = f"{BASE_DIR}/alcaldes_concejales.json"

# provincia (tal como aparece en el XLSX del Ministerio) -> lista de
# municipios oficial de esta app, para poder normalizar/emparejar nombres.
# Ampliado 2026-08-09 a las 3 provincias catalanas restantes -- las claves
# "Lleida"/"Barcelona"/"Tarragona" son la nomenclatura INE estándar, mismo
# patrón ya verificado con "Girona"; revisar sin_match_alcaldes/sin_match_conc
# tras la primera ejecución por si el XLSX usa una grafía distinta.
MUNICIPIOS_POR_PROV_MIN = {
    "Murcia": MUNICIPIOS_MURCIA, "Girona": MUNICIPIOS_GIRONA,
    "Lleida": MUNICIPIOS_LLEIDA, "Barcelona": MUNICIPIOS_BARCELONA, "Tarragona": MUNICIPIOS_TARRAGONA,
}
PROV_A_KEY = {"Murcia": "murcia", "Girona": "girona",
              "Lleida": "lleida", "Barcelona": "barcelona", "Tarragona": "tarragona"}


def _descargar_xlsx(session, url):
    r = session.get(url, timeout=60)
    r.raise_for_status()
    return openpyxl.load_workbook(io.BytesIO(r.content), read_only=True, data_only=True)


def _filas(ws):
    """Salta las 6 filas de cabecera/título del XLSX del Ministerio y
    devuelve dicts {columna: valor} para cada fila de datos."""
    it = ws.iter_rows(values_only=True)
    header = None
    for row in it:
        if row and row[0] == "Código INE":
            header = row
            break
    if header is None:
        raise RuntimeError("no se encontró la fila de cabecera 'Código INE' en el XLSX")
    for row in it:
        if not row or not row[1]:
            continue
        yield dict(zip(header, row))


def _nombre_completo(fila):
    partes = [fila.get("Nombre") or "", fila.get("1er Apellido") or "", fila.get("2º Apellido") or ""]
    return " ".join(p.strip() for p in partes if p.strip())


def _sin_apostrofes_curvos(s):
    return (s or "").replace("’", "'").replace("‘", "'").replace("`", "'")


# El XLSX del Ministerio ordena algunos nombres como "Núcleo, Artículo"
# (convención alfabética del INE) y usa guion donde la app usa espacio;
# la lista de 4 casos detectados al ejecutar este script sobre Murcia+Girona.
ALIAS_MUNICIPIO = {
    "alcazares, los": "Los Alcázares",
    "union, la": "La Unión",
    "torres de cotillas, las": "Las Torres de Cotillas",
    "torre-pacheco": "Torre Pacheco",
    # Detectados 2026-08-09 al ejecutar este script sobre Lleida/Barcelona/
    # Tarragona -- renombres/fusiones reales, no un problema de formato
    # (mismo patrón ya documentado para "Bisbal de Falset" -> "Bisbal de
    # Montsant" en el nomenclátor PSCP, ver memoria del proyecto).
    "bigues i riells del fai": "Bigues i Riells",
    "la bisbal de falset": "la Bisbal de Montsant",
}

# Girona se curó a mano al estilo "núcleo, artículo, en minúscula" (p.ej.
# "Bisbal d'Empordà, la"), que ya coincide con la convención alfabética del
# XLSX del Ministerio ("Bisbal d'Empordà, La") sin necesitar más que el
# normalizado de mayúsculas de arriba. Lleida/Barcelona/Tarragona (añadidas
# 2026-08-09) NO se curaron así -- conservan el artículo catalán como
# prefijo tal cual venía del dataset de origen (PSCP), p.ej. "la Seu
# d'Urgell", "el Bruc", "l'Ametlla del Vallès" -- así que frente al XLSX
# ("Seu d'Urgell, La", "Bruc, El", "Ametlla del Vallès, L'") no hay ningún
# emparejamiento directo. Detectado al ejecutar este script por primera vez
# sobre las 3 provincias nuevas: 122 municipios sin emparejar, casi todos
# con este mismo patrón sistemático (no casos sueltos) -- se resuelve
# reordenando el nombre de origen en vez de añadir cientos de alias a mano.
_RE_NUCLEO_ARTICULO = re.compile(r"^(.+),\s*(El|La|L'|Els|Les|Es|Ets)\s*$", re.IGNORECASE)

# "de + el" -> "del", "de + els" -> "dels" (única contracción real en
# catalán con el artículo pospuesto). El nomenclátor PSCP de origen de
# Lleida/Barcelona/Tarragona hereda esta forma contraída de forma
# INCONSISTENTE para una decena de municipios (p.ej. "dels Hostalets de
# Pierola" en vez de "els Hostalets de Pierola") -- ver memoria del
# proyecto: no se normalizó a mano a propósito para no introducir un error
# propio sobre datos de contratos ya verificados, así que aquí se prueban
# ambas formas en vez de "corregir" el nomenclátor.
_CONTRACCION_DE = {"el": "del", "els": "dels"}


def _formas_nucleo_articulo(nombre):
    """'Bruc, El' -> {'el Bruc'}, 'Hostalets de Pierola, Els' -> {'els
    Hostalets de Pierola', 'dels Hostalets de Pierola'} -- convierte la
    convención alfabética del XLSX del Ministerio al estilo "artículo
    prefijo" que usa el nomenclátor de Lleida/Barcelona/Tarragona en esta
    app, incluida la variante contraída con "de" cuando aplica. Devuelve un
    set vacío si el nombre no encaja el patrón "Núcleo, Artículo"."""
    m = _RE_NUCLEO_ARTICULO.match(nombre or "")
    if not m:
        return set()
    nucleo, articulo = m.groups()
    articulo = articulo.lower()
    sep = "" if articulo == "l'" else " "
    formas = {f"{articulo}{sep}{nucleo}"}
    contraida = _CONTRACCION_DE.get(articulo)
    if contraida:
        formas.add(f"{contraida} {nucleo}")
    return formas


def _emparejar_municipio(nombre_oficial, provincia):
    """El nombre de municipio del XLSX del Ministerio puede no coincidir
    carácter a carácter con el listado propio de la app (acentos, orden
    'la Bisbal' vs 'Bisbal, la', apóstrofes curvos, etc.) -- empareja por
    forma normalizada, con alias explícitos para los casos de reordenación,
    y probando también las formas con el artículo reordenado a prefijo (ver
    _formas_nucleo_articulo, necesario para Lleida/Barcelona/Tarragona)."""
    candidatos_normalizados = {normalizar(_sin_apostrofes_curvos(nombre_oficial))}
    for forma in _formas_nucleo_articulo(nombre_oficial):
        candidatos_normalizados.add(normalizar(_sin_apostrofes_curvos(forma)))
    for m in MUNICIPIOS_POR_PROV_MIN[provincia]:
        if normalizar(_sin_apostrofes_curvos(m)) in candidatos_normalizados:
            return m
    for buscado in candidatos_normalizados:
        alias = ALIAS_MUNICIPIO.get(buscado)
        if alias and alias in MUNICIPIOS_POR_PROV_MIN[provincia]:
            return alias
    return None


def main():
    session = requests.Session()
    session.headers.update(HEADERS)
    session.get(URL_HOME, timeout=30)  # calienta cookies de sesión; sin esto la descarga da 403

    print("Descargando alcaldes...")
    wb_alc = _descargar_xlsx(session, URL_ALCALDES)
    print("Descargando concejales...")
    wb_con = _descargar_xlsx(session, URL_CONCEJALES)

    resultado = {}  # clave normalizada de municipio -> {municipio, provincia, alcalde, concejales}

    n_alcaldes_match = 0
    sin_match_alcaldes = []
    for fila in _filas(wb_alc.active):
        provincia = fila.get("Provincia")
        if provincia not in MUNICIPIOS_POR_PROV_MIN:
            continue
        muni = _emparejar_municipio(fila.get("Municipio", ""), provincia)
        if not muni:
            sin_match_alcaldes.append((provincia, fila.get("Municipio")))
            continue
        clave = normalizar(muni)
        resultado.setdefault(clave, {
            "municipio": muni, "provincia": PROV_A_KEY[provincia],
            "alcalde": None, "concejales": [],
        })
        resultado[clave]["alcalde"] = {
            "nombre": _nombre_completo(fila),
            "partido": (fila.get("Partido") or "").strip(),
            "fecha_posesion": (fila.get("Fecha de Posesión") or "").strip(),
        }
        n_alcaldes_match += 1

    n_conc_match = 0
    sin_match_conc = set()
    for fila in _filas(wb_con.active):
        provincia = fila.get("Provincia")
        if provincia not in MUNICIPIOS_POR_PROV_MIN:
            continue
        muni = _emparejar_municipio(fila.get("Municipio", ""), provincia)
        if not muni:
            sin_match_conc.add((provincia, fila.get("Municipio")))
            continue
        clave = normalizar(muni)
        resultado.setdefault(clave, {
            "municipio": muni, "provincia": PROV_A_KEY[provincia],
            "alcalde": None, "concejales": [],
        })
        cargo = (fila.get("Cargo") or "").strip()
        resultado[clave]["concejales"].append({
            "nombre": _nombre_completo(fila),
            "cargo": cargo,
            "partido": (fila.get("Partido") or "").strip(),
        })
        n_conc_match += 1

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump({"generado": time.strftime("%Y-%m-%d %H:%M:%S"), "municipios": resultado},
                   f, ensure_ascii=False, indent=1)

    total_esperado = sum(len(m) for m in MUNICIPIOS_POR_PROV_MIN.values())
    print(f"\nAlcaldes emparejados: {n_alcaldes_match}")
    print(f"Filas de concejales emparejadas: {n_conc_match}")
    print(f"Municipios con datos: {len(resultado)} / {total_esperado} esperados")
    if sin_match_alcaldes:
        print(f"\nSin emparejar (alcaldes), {len(sin_match_alcaldes)}: {sin_match_alcaldes[:20]}")
    if sin_match_conc:
        print(f"\nSin emparejar (concejales), {len(sin_match_conc)}: {list(sin_match_conc)[:20]}")
    todos_municipios = [m for lista in MUNICIPIOS_POR_PROV_MIN.values() for m in lista]
    faltan = [m for m in todos_municipios if normalizar(m) not in resultado]
    if faltan:
        print(f"\nMunicipios de la app SIN ningún dato encontrado ({len(faltan)}): {faltan}")
    print(f"\nGuardado en {OUT_FILE}")


if __name__ == "__main__":
    main()
