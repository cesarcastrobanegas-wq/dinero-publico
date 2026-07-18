# encoding: utf-8
"""
Descarga alcaldes y concejales de la legislatura vigente desde la app
"concejalesApp" del Ministerio de Política Territorial y Memoria
Democrática (https://concejales.redsara.es/consulta/) y genera
backend/alcaldes_concejales.json filtrado a los municipios de Murcia y
Girona que cubre esta app.

No hay una API pública documentada (sin token/Swagger): son descargas
XLSX directas por URL. Por eso este script no se llama desde las rutas
web -- se ejecuta manualmente / de forma periódica (ej. trimestral, o
tras una moción de censura conocida), y el resultado se versiona como
un JSON estático que app.py carga en memoria al arrancar.

Uso:  python actualizar_alcaldes.py
"""
import io
import json
import sys
import time

import openpyxl
import requests

sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
from app import BASE_DIR, MUNICIPIOS_MURCIA, MUNICIPIOS_GIRONA, normalizar

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
MUNICIPIOS_POR_PROV_MIN = {"Murcia": MUNICIPIOS_MURCIA, "Girona": MUNICIPIOS_GIRONA}
PROV_A_KEY = {"Murcia": "murcia", "Girona": "girona"}


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
}


def _emparejar_municipio(nombre_oficial, provincia):
    """El nombre de municipio del XLSX del Ministerio puede no coincidir
    carácter a carácter con el listado propio de la app (acentos, orden
    'la Bisbal' vs 'Bisbal, la', apóstrofes curvos, etc.) -- empareja por
    forma normalizada, con alias explícitos para los casos de reordenación."""
    buscado = normalizar(_sin_apostrofes_curvos(nombre_oficial))
    for m in MUNICIPIOS_POR_PROV_MIN[provincia]:
        if normalizar(_sin_apostrofes_curvos(m)) == buscado:
            return m
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

    total_esperado = len(MUNICIPIOS_MURCIA) + len(MUNICIPIOS_GIRONA)
    print(f"\nAlcaldes emparejados: {n_alcaldes_match}")
    print(f"Filas de concejales emparejadas: {n_conc_match}")
    print(f"Municipios con datos: {len(resultado)} / {total_esperado} esperados")
    if sin_match_alcaldes:
        print(f"\nSin emparejar (alcaldes), {len(sin_match_alcaldes)}: {sin_match_alcaldes[:20]}")
    if sin_match_conc:
        print(f"\nSin emparejar (concejales), {len(sin_match_conc)}: {list(sin_match_conc)[:20]}")
    faltan = [m for m in MUNICIPIOS_MURCIA + MUNICIPIOS_GIRONA if normalizar(m) not in resultado]
    if faltan:
        print(f"\nMunicipios de la app SIN ningún dato encontrado ({len(faltan)}): {faltan}")
    print(f"\nGuardado en {OUT_FILE}")


if __name__ == "__main__":
    main()
