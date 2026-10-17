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


# ─── FEDER, FSE+ y Transición Justa 2021-2027 (Kohesio) ─────────────────────────────────────────────────────────────
# 2026-10-17 (encargo de César). Cohesion Data solo llega a 2014-2020; las operaciones de 2021-2027 las agrega Kohesio
# (Comisión Europea) a partir de las listas de cada autoridad de gestión. Su API pública no está documentada (sale del
# código de la propia web kohesio.ec.europa.eu): la lista de proyectos no trae ni el fondo, ni el programa, ni la
# provincia, ni el beneficiario, pero admite filtros. Así que se pide la lista entera y luego la lista filtrada por cada
# fondo, cada programa, cada comunidad y cada provincia (NUTS3): unas 250 páginas de 1.000. El beneficiario sale de la
# ficha de cada beneficiario (10.500, con todos sus proyectos), no de la de cada proyecto (28.000).
# Sin NIF. El nombre solo se guarda cuando es claramente una entidad (forma jurídica o tipo de organismo en el nombre):
# en el FSE+ hay personas físicas (autónomos) y la web no las nombra.
KOHESIO_API = "https://kohesio.ec.europa.eu/api"
_LOD = "https://linkedopendata.eu/entity/"
KOHESIO_ESPANA = _LOD + "Q7"
KOHESIO_2127 = _LOD + "Q7333082"
_KOHESIO_LOTE = 1000

# Formas jurídicas: palabra entera (para no confundir "SA" con "SANCHEZ"). Tipos de organismo: por el principio de la
# palabra ("UNIVERSI" vale para Universidad, Universitat, Unibertsitatea…).
_RE_FORMA_JURIDICA = re.compile(
    r"(?<![\w])(S\.?\s?L\.?\s?(U|L|NE|P)?\.?|S\.?\s?A\.?\s?(U|L|T|D)?\.?|S\.?\s?COOP\.?|S\.?A\.?T\.?|C\.?\s?B\.?|"
    r"A\.?\s?I\.?\s?E\.?|U\.?T\.?E\.?|LTDA?|GMBH|SRL|SAS|INC|LLC|BV|SAU|SLU|SLL|SL|SA|ONCE|CSIC|CDTI|ICEX|SEPE|SGPAE|"
    r"ADIF|RENFE|AENA)(?![\w])", re.I)
_RE_ORGANISMO = re.compile(
    r"\b(SOCIEDAD|SOCIETAT|COOPERATIV|LIMITADA|AN[OÓ]NIMA|AYUNTAMIENTO|AJUNTAMENT|CONCELLO|UDAL|DIPUTACI|DEPUTACI|"
    r"CABILDO|CONSELL|MANCOMUNI|COMARCA|CONSORCI|ENTIDAD|ENTITAT|ORGANISMO|AGENCIA|AG[EÈ]NCIA|INSTITU|SERVICIO|"
    r"SERVEI|SERVIZO|MINISTERIO|SECRETAR|DIRECCI|CONSEJER|CONSELLER|DEPARTAMENT|JUNTA|GOBIERNO|GOVERN|XUNTA|"
    r"GENERALITAT|EUSKO|COMUNIDAD|COMUNITAT|REGI[OÓ]N|PRINCIPADO|CIUDAD AUT|UNIVERSI|UNIBERTSITATE|ESCUELA|ESCOLA|"
    r"COLEGIO|COL·LEGI|CENTRO|CENTRE|HOSPITAL|SALUD|SANITARI|FUNDACI|FUNDAZIO|ASOCIACI|ASSOCIACI|ELKARTE|FEDERACI|"
    r"CONFEDERACI|C[AÁ]MARA|COFRAD|SINDICA|UNI[OÓ]N|PATRONAT|AUTORIDAD|PUERTO|AEROPUERTO|GRUPO|GROUP|HOLDING|"
    r"INDUSTRI|EMPRESA|COMPA[NÑ][IÍ]A|PARQUE|TECNOL[OÓ]GIC|LABORATORI|CL[UÚ]STER|PLATAFORMA|C[AÁ]RITAS|CRUZ ROJA|"
    r"REGANTES|OBISPADO|PARROQUIA|ARZOBISPADO|ENTE |EMPRESA P[UÚ]BLICA|INGENIER|CONSTRUCC|TRANSPORT|"
    r"COMERCIAL|DISTRIBUCI|SERVICIOS|SOLUCIONES|SISTEMAS|TECHNOLOG|SOLUTIONS|ENERG|INVERSION|PROMOCI|GESTI[OÓ]N)", re.I)


def es_entidad(nombre):
    """Cierto si el nombre lleva una forma jurídica o un tipo de organismo. Lo dudoso se trata como persona física."""
    return bool(_RE_FORMA_JURIDICA.search(nombre or "") or _RE_ORGANISMO.search(nombre or ""))


def comunidad_del_programa_2127(etiqueta):
    """Comunidad de un programa regional 2021-2027 por su nombre ("2021ES16RFPR002 - Programa Andalucía FEDER…"),
    o '' si es estatal, plurirregional o de cooperación."""
    codigo, _, nombre = (etiqueta or "").partition(" - ")
    if es_cooperacion(codigo, nombre) or "pluri" in nombre.lower() or "españa" in nombre.lower():
        return ""
    n = nombre.lower()
    for clave, comunidad in _PROGRAMA_POR_NOMBRE:
        if clave in n:
            return comunidad
    return ""


def _k_importe(lista_o_valor):
    """La lista trae "239977467,04" y la ficha "+241445982.04"."""
    v = lista_o_valor[0] if isinstance(lista_o_valor, list) and lista_o_valor else lista_o_valor
    s = str(v or "0").strip().lstrip("+")
    return _importe(s.replace(".", "").replace(",", ".") if "," in s else s)


def _kohesio_ids(sesion, filtro=""):
    """{QID: entrada de la lista} de los proyectos de España 2021-2027 que cumplen el filtro ('&fund=…', etc.)."""
    salida, desplazamiento = {}, 0
    while True:
        r = _pedir(sesion, f"{KOHESIO_API}/projects?country={KOHESIO_ESPANA}&programmingPeriod={KOHESIO_2127}"
                           f"&language=es&limit={_KOHESIO_LOTE}&offset={desplazamiento}{filtro}", timeout=180)
        d = r.json()
        lote = d.get("list") or []
        for x in lote:
            if x.get("item"):
                salida[x["item"]] = x
        desplazamiento += _KOHESIO_LOTE
        if len(lote) < _KOHESIO_LOTE or desplazamiento >= int(d.get("numberResults") or 0):
            return salida


def _kohesio_consulta(sesion, que, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    return _pedir(sesion, f"{KOHESIO_API}/queries/{que}?language=es" + (f"&{q}" if q else ""), timeout=120).json()


def _kohesio_beneficiarios(sesion, hilos=4):
    """{QID de proyecto: [nombres de beneficiario]} a partir de la ficha de cada beneficiario de España 2021-2027."""
    from concurrent.futures import ThreadPoolExecutor
    # La lista de beneficiarios solo deja llegar a los 1.000 primeros de cada consulta (offset + limit <= 1.000): se
    # pide por programa; los programas con más de 1.000, por programa y comunidad; y si aun así pasan de 1.000, los
    # 1.000 de mayor importe más los 1.000 de menor (cubre hasta 2.000).
    base = f"{KOHESIO_API}/beneficiaries?country={KOHESIO_ESPANA}&programmingPeriod={KOHESIO_2127}&language=es"

    def _lista(filtro, orden=""):
        d = _pedir(sesion, f"{base}&limit={_KOHESIO_LOTE}&offset=0{filtro}{orden}", timeout=180).json()
        return int(d.get("numberResults") or 0), [(x.get("id") or "").rsplit("/", 1)[-1] for x in d.get("list") or []
                                                  if x.get("id")]

    total = int(_pedir(sesion, f"{base}&limit=1&offset=0", timeout=180).json().get("numberResults") or 0)
    ids, sin_cubrir = set(), 0
    regiones = _kohesio_consulta(sesion, "regions", country=KOHESIO_ESPANA)
    for p in _kohesio_consulta(sesion, "programs", country=KOHESIO_ESPANA):
        if not p.get("instanceLabel", "").startswith("2021"):
            continue
        n, lote = _lista(f"&program={p['instance']}")
        trozos = [(f"&program={p['instance']}", n, lote)]
        if n > _KOHESIO_LOTE:
            trozos = []
            for r in regiones:
                filtro = f"&program={p['instance']}&region={r['region']}"
                nr, lote_r = _lista(filtro)
                if nr:
                    trozos.append((filtro, nr, lote_r))
        for filtro, n, lote in trozos:
            ids.update(lote)
            if n > _KOHESIO_LOTE:
                ids.update(_lista(filtro, "&orderEuBudget=true")[1])
                sin_cubrir += max(0, n - 2 * _KOHESIO_LOTE)
    ids = sorted(ids)
    print(f"  Kohesio: {len(ids)} beneficiarios distintos de {total} (sin poder recorrer: {sin_cubrir})", flush=True)

    def ficha(qid):
        for intento in range(3):
            try:
                r = sesion.get(f"{KOHESIO_API}/beneficiaries/{qid}?id={_LOD}{qid}&language=es&pageSize=5000", timeout=120)
                if r.status_code == 200:
                    d = r.json()
                    return d.get("beneficiaryLabel") or "", [(p.get("project") or "").rsplit("/", 1)[-1]
                                                             for p in d.get("projects") or []]
            except (requests.RequestException, ValueError):
                pass
            time.sleep(5 * (intento + 1))
        return None

    por_proyecto, fallos = {}, 0
    with ThreadPoolExecutor(hilos) as ex:
        for i, res in enumerate(ex.map(ficha, ids), 1):
            if res is None:
                fallos += 1
            else:
                nombre, proyectos = res
                for p in proyectos:
                    por_proyecto.setdefault(p, []).append(nombre)
            if i % 1000 == 0:
                print(f"  … {i}/{len(ids)} fichas de beneficiario ({fallos} fallidas)", flush=True)
    if fallos > len(ids) * 0.05:
        raise SystemExit(f"ERROR: {fallos} fichas de beneficiario de Kohesio fallidas de {len(ids)}")
    return por_proyecto


def descargar_kohesio(sesion, con_nombres=True):
    """Operaciones de España 2021-2027 de Kohesio como filas de fondos_ue (fuente 'kohesio')."""
    base = _kohesio_ids(sesion)
    print(f"  Kohesio: {len(base)} operaciones 2021-2027", flush=True)
    fondo, programa, provincias, comunidades = {}, {}, {}, {}
    for f in _kohesio_consulta(sesion, "funds"):
        if "(2021-2027)" in f.get("instanceLabel", ""):
            corto = f["instanceLabel"].split(" - ")[0].strip()
            for q in _kohesio_ids(sesion, f"&fund={f['instance']}"):
                fondo.setdefault(q, []).append(corto)
    for p in _kohesio_consulta(sesion, "programs", country=KOHESIO_ESPANA):
        if p.get("instanceLabel", "").startswith("2021"):
            for q in _kohesio_ids(sesion, f"&program={p['instance']}"):
                programa.setdefault(q, p["instanceLabel"])
    for reg in _kohesio_consulta(sesion, "regions", country=KOHESIO_ESPANA):
        nuts3 = _kohesio_consulta(sesion, "nuts3", country=KOHESIO_ESPANA, region=reg["region"])
        com = next((LIC.comunidad_de_nuts(n.get("nuts_code", "")[:4]) for n in nuts3 if n.get("nuts_code")), "")
        if com:
            for q in _kohesio_ids(sesion, f"&region={reg['region']}"):
                comunidades.setdefault(q, set()).add(com)
        for n in nuts3:
            prov = LIC.provincia_de_nuts(n.get("nuts_code", ""))
            if prov:
                for q in _kohesio_ids(sesion, f"&region={reg['region']}&nuts3={n['instance']}"):
                    provincias.setdefault(q, set()).add(prov)
    print(f"  Kohesio: con fondo {len(fondo)}, con programa {len(programa)}, con comunidad {len(comunidades)}, "
          f"con provincia {len(provincias)}", flush=True)
    benef = _kohesio_beneficiarios(sesion) if con_nombres else {}
    filas = []
    for q, x in base.items():
        etiqueta = programa.get(q, "")
        codigo = etiqueta.split(" - ")[0].strip()
        provs, coms = provincias.get(q, set()), set(comunidades.get(q, set()))
        coms |= {COMUNIDAD_DE_PROVINCIA.get(p, "") for p in provs} - {""}
        com_prog = comunidad_del_programa_2127(etiqueta)
        if es_cooperacion(codigo, etiqueta.partition(" - ")[2]):
            provincia, ambito, comunidad = "", "cooperacion", ""
        elif com_prog:
            dentro = {p for p in provs if COMUNIDAD_DE_PROVINCIA.get(p) == com_prog}
            if len(dentro) == 1 and dentro == provs:
                provincia, ambito, comunidad = next(iter(dentro)), "provincia", com_prog
            elif com_prog in PROVINCIA_UNICA:
                provincia, ambito, comunidad = PROVINCIA_UNICA[com_prog], "provincia", com_prog
            else:
                provincia, ambito, comunidad = "", "regional", com_prog
        elif len(provs) == 1:
            provincia = next(iter(provs))
            provincia, ambito, comunidad = provincia, "provincia", COMUNIDAD_DE_PROVINCIA.get(provincia, "")
        elif len(coms) == 1:
            comunidad = next(iter(coms))
            if comunidad in PROVINCIA_UNICA:
                provincia, ambito = PROVINCIA_UNICA[comunidad], "provincia"
            else:
                provincia, ambito = "", "regional"
        else:
            provincia, ambito, comunidad = "", "estatal", ""
        nombres = [n for n in benef.get(q, []) if n and es_entidad(n)]
        filas.append({
            "id": f"kohesio-{q}",
            "fuente": "kohesio",
            "provincia": provincia,
            "ambito": ambito,
            "comunidad": comunidad,
            "municipio": "",
            "nuts_code": "",
            "titulo": _titulo((x.get("labels") or [""])[0]),
            "beneficiario": "; ".join(dict.fromkeys(nombres))[:300],
            "nif": "",
            "rol": "",
            "importe_num": _k_importe(x.get("totalBudgets")),
            "fecha_inicio": (x.get("startTimes") or [""])[0] or "",
            "fecha_fin": (x.get("endTimes") or [""])[0] or "",
            "programa": etiqueta,
            "fondo": "/".join(fondo.get(q, [])) or "",
            "url": KOHESIO_PROYECTO_URL.format(qid=q),
        })
    print(f"  Kohesio: {sum(1 for f in filas if f['beneficiario'])} con nombre de entidad; "
          f"{sum(1 for q in base if benef.get(q) and not any(es_entidad(n) for n in benef[q]))} sin nombre "
          "(posible persona física o nombre sin forma jurídica)", flush=True)
    return filas


# ─── Los 100 mayores perceptores finales del Plan de Recuperación ───────────────────────────────────────────────────
# Lista oficial que publica el Gobierno (art. 25 bis del Reglamento 2021/241). Todos son personas jurídicas; aun así,
# un NIF con forma de DNI/NIE no se guardaría. Sin ubicación: van como "estatal".
MRR100_URL = ("https://digital.gob.es/content/dam/portal-mtdfp/ministerio/"
              "Listado_100_mayores_perceptores_finales_Next_Generation_20240430.xlsx")
MRR100_FECHA = "2024-04-30"


def descargar_mrr100(sesion):
    import openpyxl
    r = _pedir(sesion, MRR100_URL, timeout=120)
    hoja = openpyxl.load_workbook(io.BytesIO(r.content), read_only=True, data_only=True).worksheets[0]
    perceptores, actual = {}, None
    for fila in hoja.iter_rows(values_only=True):
        celdas = list(fila)[1:6] if len(fila) >= 6 else []
        if len(celdas) < 5 or celdas[0] == "NIF":
            continue
        nif, nombre, comp, nombre_comp, total = celdas
        if nif:
            nif = str(nif).strip().upper()
            actual = None if _RE_DNI_NIE.match(nif) else perceptores.setdefault(
                nif, {"nombre": str(nombre or "").strip(), "total": 0.0, "componentes": []})
        if actual is None or not isinstance(total, (int, float)):
            continue
        actual["total"] += float(total)
        if comp:
            actual["componentes"].append(f"{comp} {nombre_comp or ''}".strip())
    if not 90 <= len(perceptores) <= 110:
        raise SystemExit(f"ERROR: la lista de los 100 mayores perceptores trae {len(perceptores)}")
    return [{
        "id": f"mrr100-{nif}", "fuente": "mrr100", "provincia": "", "ambito": "estatal", "comunidad": "",
        "municipio": "", "nuts_code": "", "titulo": "; ".join(dict.fromkeys(p["componentes"]))[:500],
        "beneficiario": p["nombre"], "nif": nif, "rol": "", "importe_num": round(p["total"], 2),
        "fecha_inicio": "", "fecha_fin": MRR100_FECHA, "programa": "Plan de Recuperación, Transformación y Resiliencia",
        "fondo": "MRR (Next Generation EU)", "url": MRR100_URL,
    } for nif, p in perceptores.items()]


def generar(salida, con_nombres=False, kohesio=True, mrr100=True):
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
    if kohesio:
        print("Kohesio (FEDER, FSE+ y Transición Justa 2021-2027)…", flush=True)
        koh = descargar_kohesio(sesion, con_nombres)
        if len(koh) < 20000:
            raise SystemExit(f"ERROR: Kohesio trae solo {len(koh)} operaciones 2021-2027; no se genera el fichero")
        filas += koh
    if mrr100:
        print("Plan de Recuperación: los 100 mayores perceptores…", flush=True)
        filas += descargar_mrr100(sesion)
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
    g.add_argument("--sin-kohesio", action="store_true", help="no bajar FEDER/FSE+ 2021-2027 de Kohesio")
    g.add_argument("--sin-mrr100", action="store_true", help="no bajar los 100 mayores perceptores del Plan de Recuperación")
    k = sub.add_parser("kohesio", help="solo Kohesio 2021-2027 (pruebas)")
    k.add_argument("--salida", required=True)
    k.add_argument("--sin-beneficiarios", action="store_true")
    a = ap.parse_args()
    if a.orden == "generar":
        generar(a.salida, a.nombres, kohesio=not a.sin_kohesio, mrr100=not a.sin_mrr100)
    elif a.orden == "kohesio":
        s = requests.Session()
        s.headers["User-Agent"] = "dinero-publico.com (fondos UE; datos abiertos de la Comisión Europea)"
        filas = descargar_kohesio(s, not a.sin_beneficiarios) + descargar_mrr100(s)
        with gzip.open(a.salida, "wt", encoding="utf-8") as f:
            for fila in filas:
                f.write(json.dumps(fila, ensure_ascii=False) + "\n")
        print(json.dumps(_resumen(filas), ensure_ascii=False, indent=1), flush=True)
    sys.exit(0)
