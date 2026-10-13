"""Fondos UE de toda España (2026-10-12, encargo de César).

Hasta ahora la web solo cargaba Murcia y Girona, y lo hacía dentro del propio proceso web (el volcado de CORDIS entero
en memoria). Este módulo hace dos cosas:

  1. Decide a qué pertenece cada operación (clasificar_cohesion / clasificar_cordis). Lo usan tanto el generador como
     la web, para que el refresco de Murcia/Girona que sigue corriendo dentro de la web no contradiga a la carga
     completa.
  2. Genera el fichero de toda España (python backend/fondos_ue_espana.py generar --salida fondos_ue.ndjson.gz), pensado
     para GitHub Actions (fondos-ue-espana.yml), que lo sube a POST /admin/fondos-ue.

Ámbito de cada fila (columna `ambito`):
  provincia     la operación está en una sola provincia (NUTS3) o es de un programa de una comunidad uniprovincial
  regional      programa de una comunidad con varias provincias, sin provincia concreta (o repartida entre varias)
  estatal       programa plurirregional o estatal sin provincia concreta, o repartido entre varias comunidades
  cooperacion   cooperación territorial (Interreg, Urbact, ESPON...): el importe es el de la operación COMPLETA, con
                socios de otros países; nunca se suma a una provincia

Cohesion Data se equivoca a veces en la ubicación (operaciones del programa de Murcia situadas en Cantabria, etc.):
cuando el programa es de una comunidad y la ubicación cae fuera de ella, manda el programa.

Nombres: Cohesion Data no publica el beneficiario para España. De CORDIS se guarda el nombre y el NIF de la
organización solo con --nombres (decisión de César del 13-10: el flujo lo pasa), y nunca los de quien tiene un NIF con
forma de DNI/NIE. El fichero no se guarda en el repositorio ni como artefacto.
"""
import argparse
import csv
import gzip
import io
import json
import re
import sys
import time
import zipfile

import requests

try:
    from . import licitaciones_place as LIC
except ImportError:
    import licitaciones_place as LIC

CORDIS_HORIZON_CSV_URL = "https://cordis.europa.eu/data/cordis-HORIZONprojects-csv.zip"
COHESION_DATA_URL = "https://cohesiondata.ec.europa.eu/resource/557j-pmg8.json"
KOHESIO_PROYECTO_URL = "https://kohesio.ec.europa.eu/es/projects/{qid}"

AMBITOS = ("provincia", "regional", "estatal", "cooperacion")

# comunidad de cada provincia de la app, sacada de las tablas NUTS que ya usa /convocatorias
COMUNIDAD_DE_PROVINCIA = {}
for _nuts, _prov in LIC.NUTS_PROVINCIA.items():
    if LIC.NUTS_COMUNIDAD.get(_nuts[:4]):
        COMUNIDAD_DE_PROVINCIA[_prov] = LIC.NUTS_COMUNIDAD[_nuts[:4]]
_PROVINCIAS_DE_COMUNIDAD = {}
for _prov, _com in COMUNIDAD_DE_PROVINCIA.items():
    _PROVINCIAS_DE_COMUNIDAD.setdefault(_com, set()).add(_prov)
# comunidades con una sola provincia en la app (el País Vasco es una única "provincia" en la web)
PROVINCIA_UNICA = {c: next(iter(ps)) for c, ps in _PROVINCIAS_DE_COMUNIDAD.items() if len(ps) == 1}

# Programas operativos 2014-2020 de una comunidad (los tres últimos dígitos del código): FEDER (RFOP) y FSE (SFOP).
_PROGRAMA_FEDER = {"003": "andalucia", "004": "aragon", "005": "asturias", "006": "baleares", "007": "canarias",
                   "008": "cantabria", "009": "castilla_y_leon", "010": "castilla_la_mancha", "011": "cataluna",
                   "012": "ceuta", "013": "valenciana", "014": "extremadura", "015": "galicia", "016": "la_rioja",
                   "017": "madrid", "018": "melilla", "019": "murcia", "020": "navarra", "021": "pais_vasco"}
_PROGRAMA_FSE = {"001": "la_rioja", "003": "murcia", "004": "asturias", "005": "baleares", "006": "castilla_y_leon",
                 "007": "cataluna", "008": "ceuta", "009": "galicia", "010": "navarra", "011": "pais_vasco",
                 "014": "canarias", "015": "castilla_la_mancha", "016": "extremadura", "017": "melilla",
                 "018": "aragon", "019": "cantabria", "020": "valenciana", "021": "madrid", "022": "andalucia"}
# Por si aparece un código que no está arriba: el nombre del programa empieza por la comunidad ("Murcia  - ERDF").
_PROGRAMA_POR_NOMBRE = (("andaluc", "andalucia"), ("arag", "aragon"), ("asturias", "asturias"), ("baleares", "baleares"),
                        ("canarias", "canarias"), ("cantabria", "cantabria"), ("castilla y le", "castilla_y_leon"),
                        ("castilla-la mancha", "castilla_la_mancha"), ("catalu", "cataluna"), ("ceuta", "ceuta"),
                        ("valenciana", "valenciana"), ("extremadura", "extremadura"), ("galicia", "galicia"),
                        ("la rioja", "la_rioja"), ("madrid", "madrid"), ("melilla", "melilla"), ("murcia", "murcia"),
                        ("navarra", "navarra"), ("país vasco", "pais_vasco"), ("pais vasco", "pais_vasco"))

# Dos primeras cifras del código postal -> provincia de la app (solo para las pocas filas de CORDIS sin NUTS3)
_CP_PROVINCIA = {
    "01": "pais_vasco", "02": "albacete", "03": "alicante", "04": "almeria", "05": "avila", "06": "badajoz",
    "07": "baleares", "08": "barcelona", "09": "burgos", "10": "caceres", "11": "cadiz", "12": "castellon",
    "13": "ciudad_real", "14": "cordoba", "15": "a_coruna", "16": "cuenca", "17": "girona", "18": "granada",
    "19": "guadalajara", "20": "pais_vasco", "21": "huelva", "22": "huesca", "23": "jaen", "24": "leon",
    "25": "lleida", "26": "la_rioja", "27": "lugo", "28": "madrid", "29": "malaga", "30": "murcia", "31": "navarra",
    "32": "ourense", "33": "asturias", "34": "palencia", "35": "las_palmas", "36": "pontevedra", "37": "salamanca",
    "38": "santa_cruz_tenerife", "39": "cantabria", "40": "segovia", "41": "sevilla", "42": "soria",
    "43": "tarragona", "44": "teruel", "45": "toledo", "46": "valencia", "47": "valladolid", "48": "pais_vasco",
    "49": "zamora", "50": "zaragoza", "51": "ceuta", "52": "melilla",
}

_RE_DNI_NIE = re.compile(r"^(\d{8}[A-Z]|[XYZ]\d{7}[A-Z])$")
_RE_QID = re.compile(r"/entity/(Q\d+)$")


def comunidad_del_programa(codigo, nombre=""):
    """Comunidad autónoma de un programa operativo regional, o '' si es estatal, plurirregional o de cooperación."""
    codigo = (codigo or "").strip().upper()
    if codigo.startswith("2014ES16RFOP"):
        return _PROGRAMA_FEDER.get(codigo[-3:], "")
    if codigo.startswith("2014ES05SFOP"):
        return _PROGRAMA_FSE.get(codigo[-3:], "")
    if codigo.startswith("2014ES"):
        return ""
    if codigo:
        return ""
    n = (nombre or "").strip().lower()
    for prefijo, comunidad in _PROGRAMA_POR_NOMBRE:
        if n.startswith(prefijo):
            return comunidad
    return ""


def es_cooperacion(codigo, nombre=""):
    codigo = (codigo or "").strip().upper()
    if codigo:
        return "TC" in codigo[4:6]
    n = (nombre or "").lower()
    return any(p in n for p in ("interreg", "urbact", "espon", "eni cbc"))


def clasificar_cohesion(nuts3="", programa_codigo="", programa_nombre=""):
    """(provincia, ambito, comunidad, discordante) de una operación de Cohesion Data.
    `discordante`: el programa es de una comunidad y la ubicación publicada cae fuera de ella (manda el programa)."""
    if es_cooperacion(programa_codigo, programa_nombre):
        return "", "cooperacion", "", False
    codigos = [c.strip().upper() for c in (nuts3 or "").split("|") if c.strip()]
    provincias = {LIC.provincia_de_nuts(c) for c in codigos if c.startswith("ES")} - {""}
    fuera_de_espana = any(not c.startswith("ES") for c in codigos)
    comunidad_prog = comunidad_del_programa(programa_codigo, programa_nombre)

    if comunidad_prog:
        dentro = {p for p in provincias if COMUNIDAD_DE_PROVINCIA.get(p) == comunidad_prog}
        discordante = bool(provincias - dentro) or fuera_de_espana
        if len(dentro) == 1 and not discordante:
            return next(iter(dentro)), "provincia", comunidad_prog, False
        if comunidad_prog in PROVINCIA_UNICA:
            return PROVINCIA_UNICA[comunidad_prog], "provincia", comunidad_prog, discordante
        return "", "regional", comunidad_prog, discordante

    if len(provincias) == 1 and not fuera_de_espana:
        provincia = next(iter(provincias))
        return provincia, "provincia", COMUNIDAD_DE_PROVINCIA.get(provincia, ""), False
    comunidades = {COMUNIDAD_DE_PROVINCIA.get(p, "") for p in provincias}
    if len(provincias) > 1 and len(comunidades) == 1 and not fuera_de_espana and "" not in comunidades:
        return "", "regional", next(iter(comunidades)), False
    return "", "estatal", "", False


def clasificar_cordis(nuts="", codigo_postal=""):
    """(provincia, ambito, comunidad) de una organización española de CORDIS."""
    nuts = (nuts or "").strip().upper()
    provincia = LIC.provincia_de_nuts(nuts) if len(nuts) >= 4 else ""
    if not provincia:
        provincia = _CP_PROVINCIA.get((codigo_postal or "").strip()[:2], "") if len((codigo_postal or "").strip()) == 5 else ""
    if provincia:
        return provincia, "provincia", COMUNIDAD_DE_PROVINCIA.get(provincia, "")
    comunidad = LIC.comunidad_de_nuts(nuts) if len(nuts) == 4 else ""
    if comunidad:
        return "", "regional", comunidad
    return "", "estatal", ""


def _importe(valor):
    try:
        return float(str(valor or "0").replace(",", "."))
    except ValueError:
        return 0.0


def _titulo(texto):
    """Quita los restos de salto de línea de Excel ("_x000D_") que trae la fuente en algunos títulos."""
    return " ".join((texto or "").replace("_x000D_", " ").split())


def fila_cohesion(row, con_nombres=True):
    """Fila de fondos_ue a partir de un registro de Cohesion Data, o None si no trae identificador.
    Cohesion Data no publica el beneficiario de las operaciones españolas; sí el de algunas de cooperación."""
    op_id = (row.get("operation_unique_identifier") or {}).get("url", "")
    if not op_id:
        return None
    provincia, ambito, comunidad, discordante = clasificar_cohesion(
        row.get("nuts3_code", ""), row.get("programme_code", ""), row.get("programme_name", ""))
    qid = _RE_QID.search(op_id)
    return {
        "id": f"cohesion-{op_id}",
        "fuente": "cohesion",
        "provincia": provincia,
        "ambito": ambito,
        "comunidad": comunidad,
        # texto de ubicación de la fuente; si contradice al programa no se enseña como ubicación
        "municipio": "" if discordante else (row.get("region") or ""),
        "nuts_code": row.get("nuts3_code", "") or "",
        # el título en el idioma del programa (castellano) antes que su traducción automática al inglés
        "titulo": _titulo(row.get("operation_name_programme_language") or row.get("operation_name_english")),
        "beneficiario": (row.get("beneficiary_name", "") or "") if con_nombres else "",
        "nif": "",
        "rol": "",
        "importe_num": _importe(row.get("total_eligible_expenditure_amount")),
        "fecha_inicio": row.get("operation_start_date", "") or "",
        "fecha_fin": row.get("operation_end_date", "") or "",
        "programa": row.get("programme_name", "") or "",
        "fondo": row.get("fund_name", "") or "",
        "url": KOHESIO_PROYECTO_URL.format(qid=qid.group(1)) if qid else "",
        "discordante": discordante,
    }


def fila_cordis(row, proyecto, con_nombres=False):
    """Fila de fondos_ue a partir de una participación de organization.csv (ya filtrada a España)."""
    provincia, ambito, comunidad = clasificar_cordis(row.get("nutsCode"), row.get("postCode"))
    nombre = nif = ""
    if con_nombres:
        nif = (row.get("vatNumber") or "").strip().upper()
        if nif.startswith("ES"):
            nif = nif[2:]
        nombre = (row.get("name") or "").strip()
        if _RE_DNI_NIE.match(nif):      # persona física: ni nombre ni NIF
            nombre = nif = ""
    return {
        "id": f"cordis-{row.get('projectID', '')}-{row.get('organisationID', '')}",
        "fuente": "cordis",
        "provincia": provincia,
        "ambito": ambito,
        "comunidad": comunidad,
        "municipio": (row.get("city") or "").strip(),
        "nuts_code": (row.get("nutsCode") or "").strip(),
        "titulo": proyecto.get("title", ""),
        "beneficiario": nombre,
        "nif": nif,
        "rol": row.get("role", "") or "",
        "importe_num": _importe(row.get("ecContribution")),
        "fecha_inicio": proyecto.get("startDate", ""),
        "fecha_fin": proyecto.get("endDate", ""),
        "programa": proyecto.get("frameworkProgramme", ""),
        "fondo": "Horizon Europe",
        "url": f"https://cordis.europa.eu/project/id/{row.get('projectID', '')}",
    }


def leer_cordis(contenido_zip, es_de_interes, con_nombres=False):
    """Recorre el ZIP de CORDIS y devuelve las filas de las organizaciones para las que es_de_interes(row) es cierto.
    De project.csv solo se guardan cuatro campos por proyecto (trae decenas de columnas, incluido el resumen)."""
    proyectos, filas = {}, []
    with zipfile.ZipFile(io.BytesIO(contenido_zip)) as z:
        with z.open("project.csv") as f:
            for row in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"), delimiter=";"):
                proyectos[row["id"]] = {"title": row.get("title", ""), "startDate": row.get("startDate", ""),
                                        "endDate": row.get("endDate", ""),
                                        "frameworkProgramme": row.get("frameworkProgramme", "")}
        with z.open("organization.csv") as f:
            for row in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"), delimiter=";"):
                if es_de_interes(row):
                    filas.append(fila_cordis(row, proyectos.get(row.get("projectID", ""), {}), con_nombres))
    return filas


# ─── Generador (GitHub Actions) ─────────────────────────────────────────────────────────────────────────────────────
_CAMPOS_COHESION = ("operation_unique_identifier,operation_name_english,operation_name_programme_language,country,"
                    "operation_start_date,operation_end_date,total_eligible_expenditure_amount,fund_name,"
                    "programme_code,programme_name,region,nuts3_code,beneficiary_name")
_LOTE_COHESION = 20000


def _pedir(sesion, url, intentos=4, **kw):
    for intento in range(1, intentos + 1):
        try:
            r = sesion.get(url, **kw)
            if r.status_code == 200:
                return r
            print(f"  HTTP {r.status_code} (intento {intento} de {intentos})", flush=True)
        except requests.RequestException as e:
            print(f"  {type(e).__name__} (intento {intento} de {intentos})", flush=True)
        time.sleep(20 * intento)
    raise SystemExit(f"ERROR: no se pudo descargar {url.split('?')[0]}")


def descargar_cohesion(sesion, con_nombres=False):
    """Todas las operaciones con España entre sus países, por páginas y solo con las columnas que se usan. La fuente
    repite la misma operación (mismo identificador e importe) una vez por socio en las de cooperación: se guarda una."""
    filas, vistos, desplazamiento = [], set(), 0
    while True:
        r = _pedir(sesion, COHESION_DATA_URL, timeout=180, params={
            "$select": _CAMPOS_COHESION, "$where": "country like '%Spain%'", "$order": ":id",
            "$limit": _LOTE_COHESION, "$offset": desplazamiento})
        lote = r.json()
        for row in lote:
            fila = fila_cohesion(row, con_nombres)
            if fila and fila["id"] not in vistos:
                vistos.add(fila["id"])
                filas.append(fila)
        print(f"  Cohesion Data: {desplazamiento + len(lote)} registros leídos", flush=True)
        if len(lote) < _LOTE_COHESION:
            return filas
        desplazamiento += _LOTE_COHESION


def descargar_cordis(sesion, con_nombres=False):
    r = _pedir(sesion, CORDIS_HORIZON_CSV_URL, timeout=600)
    filas, vistos = [], set()
    for fila in leer_cordis(r.content, lambda row: (row.get("country") or "").strip().upper() == "ES", con_nombres):
        if fila["id"] not in vistos:
            vistos.add(fila["id"])
            filas.append(fila)
    return filas


def _resumen(filas):
    """Recuentos para el registro del flujo. Nunca nombres."""
    por_ambito, por_fuente, provincias, discordantes = {}, {}, set(), 0
    for f in filas:
        clave = (f["fuente"], f["ambito"])
        n, eur = por_ambito.get(clave, (0, 0.0))
        por_ambito[clave] = (n + 1, eur + f["importe_num"])
        por_fuente[f["fuente"]] = por_fuente.get(f["fuente"], 0) + 1
        if f["ambito"] == "provincia":
            provincias.add(f["provincia"])
        discordantes += 1 if f.get("discordante") else 0
    return {"filas": len(filas), "por_fuente": por_fuente, "provincias_con_datos": len(provincias),
            "ubicacion_discordante": discordantes,
            "por_ambito": {f"{fu}/{am}": {"n": n, "millones": round(eur / 1e6, 1)}
                           for (fu, am), (n, eur) in sorted(por_ambito.items())},
            "con_nombre": sum(1 for f in filas if f["beneficiario"])}


def generar(salida, con_nombres=False):
    sesion = requests.Session()
    sesion.headers["User-Agent"] = "dinero-publico.com (fondos UE; datos abiertos de la Comisión Europea)"
    print("Cohesion Data (FEDER/FSE 2014-2020)…", flush=True)
    filas = descargar_cohesion(sesion)       # sin nombres: --nombres solo afecta a CORDIS
    print("CORDIS (Horizon Europe)…", flush=True)
    cordis = descargar_cordis(sesion, con_nombres)
    if len(filas) < 50000 or len(cordis) < 5000:
        raise SystemExit(f"ERROR: descarga incompleta ({len(filas)} de Cohesion Data, {len(cordis)} de CORDIS); "
                         "no se genera el fichero")
    filas += cordis
    with gzip.open(salida, "wt", encoding="utf-8") as f:
        for fila in filas:
            f.write(json.dumps({k: v for k, v in fila.items() if k != "discordante"}, ensure_ascii=False) + "\n")
    resumen = _resumen(filas)
    print(json.dumps(resumen, ensure_ascii=False, indent=1), flush=True)
    return resumen


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Fondos UE de toda España (Cohesion Data + CORDIS)")
    sub = ap.add_subparsers(dest="orden", required=True)
    g = sub.add_parser("generar")
    g.add_argument("--salida", required=True)
    g.add_argument("--nombres", action="store_true",
                   help="incluir el nombre y el NIF de las organizaciones de CORDIS (nunca de quien tiene un NIF con "
                        "forma de DNI/NIE)")
    a = ap.parse_args()
    if a.orden == "generar":
        generar(a.salida, a.nombres)
    sys.exit(0)
