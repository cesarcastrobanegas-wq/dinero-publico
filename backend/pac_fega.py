"""Ayudas de la PAC (FEAGA y FEADER) del FEGA, con la OPCIÓN B decidida por César (18-10-2026): las personas físicas no
se publican nunca, ni con nombre ni en una fila propia.

Fuente: https://www.fega.gob.es/es/datos-abiertos/consulta-de-beneficiarios-pac/descarga-de-ficheros (un ZIP por
ejercicio financiero; solo están los dos últimos, por el art. 98.4 del Reglamento (UE) 2021/2116).

Qué hace (en GitHub Actions o en local; NADA de esto corre en Render):
  1. Lee el TXT del ZIP en flujo, sin descomprimirlo a disco, y comprueba que IMPORTE_EUROS = FEAGA + FEADER_COFIN.
  2. Clasifica cada beneficiario por su nombre (el FEGA no publica NIF). La regla va al revés que en los contratos:
     SOLO sale con nombre lo que tiene una forma jurídica clara (sociedad mercantil, cooperativa/SAT, entidad pública,
     asociación/fundación/comunidad de regantes...) o está en la lista de entidades verificadas a mano
     (pac_entidades_verificadas.json). Todo lo demás (personas físicas, comunidades de bienes, sociedades civiles,
     herencias, nombres dudosos y códigos de <= 1.250 €) es ANÓNIMO.
  3. Los anónimos salen del generador ya sumados: por municipio solo si en ese municipio hay 10 perceptores anónimos o
     más (el mismo umbral que usa el FEGA); si no, su número e importe pasan a «otros municipios de la provincia» y el
     total del municipio tampoco los incluye (restando no se puede saber lo que cobra una persona). Los tramos de
     importe, solo por provincia.
  4. Cada registro lleva la fecha de caducidad: fecha de publicación del FEGA + 2 años (art. 98.4). La web los borra
     sola ese día.

Salida: NDJSON en gzip SIN nombres de personas físicas, que se sube a POST /admin/pac (cabecera X-Admin-Token).
Con --revision se escribe además, SOLO EN LOCAL, la lista de anónimos de 300.000 € o más para que César revise si hay
alguna entidad (lleva nombres de personas: nunca al repositorio, a un artefacto ni a Render; .gitignore la excluye).

Uso:
  python pac_fega.py --ejercicio 2025 --salida pac_2025.ndjson.gz [--zip fichero.zip] [--fecha-publicacion AAAA-MM-DD]
                     [--revision pac_revision_2025.csv]
"""
import argparse
import collections
import datetime as dt
import gzip
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import time
import unicodedata
import urllib.request
import zipfile

AQUI = os.path.dirname(os.path.abspath(__file__))
PAGINA_FEGA = "https://www.fega.gob.es/es/datos-abiertos/consulta-de-beneficiarios-pac/descarga-de-ficheros"
# Comprobado el 17-10-2026 en la web del FEGA. Si la página da otra fecha, gana la de la página.
PUBLICACION_CONOCIDA = {
    2024: ("2025-05-26", "https://www.fega.gob.es/sites/default/files/files/document/"
                         "Beneficiarios_municipio_ejercicio-financiero-2024.zip"),
    2025: ("2026-05-25", "https://www.fega.gob.es/sites/default/files/files/document/"
                         "Beneficiarios_municipio_ejercicio_financiero-2025.zip"),
}
UMBRAL_ANONIMOS = 10            # perceptores anónimos mínimos para dar la suma de un municipio (decisión 3 de César)
UMBRAL_REVISION = 300000.0      # anónimos desde este importe van a la lista de revisión local (decisión 4)
ANIOS_PUBLICACION = 2           # art. 98.4 del Reglamento (UE) 2021/2116 (decisión 6)
TRAMOS = (1250, 5000, 20000, 100000, 300000)    # 6 tramos: <=1.250, ..., >300.000
VISIBLES = ("mercantil", "cooperativa_sat", "publica", "asociativa", "verificada")
VERSION = 1
SIN_DATOS = 3                   # código de salida: ejercicio caducado o aún no publicado (el flujo lo salta)

# Dos primeras cifras del código postal (= código INE de provincia) -> provincia de la web (igual que fondos_ue_espana)
CP_PROVINCIA = {
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


def norm(s):
    """Mayúsculas, sin acentos ni puntuación: "S.L.U." -> "S L U"."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9#]+", " ", s)).strip()


def huella(nombre_n):
    """Huella de un nombre normalizado (lista de supresiones: el repositorio nunca lleva el nombre)."""
    return hashlib.sha256(nombre_n.encode("utf-8")).hexdigest()


RE_CODIGO = re.compile(r"^[A-Z]{2}#\d+$")
RE_CP = re.compile(r"^(\d{5})\s*-\s*(.+)$")
RE_PROV_SOLO = re.compile(r"^(\d{2})(?:X{3})?\s*-\s*(.+)$")       # «08XXX - XXXXX» (medido el 19-10)
# Reglas medidas el 17-10 con los ficheros completos (PLAN PAC opcion B.md, §2.2). Orden: la primera que casa.
REGLAS = [
    ("mercantil", r"\b(S L U?|S L L|S L P|S L N E|S A U?|S A L|S R L|SLU?|SLL|SLP|SLNE|SAU?|SAL|SRL|SOCIEDAD (LIMITADA|ANONIMA)|"
                  r"LTD|LIMITED|GMBH|LDA|SARL|B ?V|N ?V)$|\bSOCIEDAD (LIMITADA|ANONIMA)\b|\bS ?L ?U?\b(?= [A-Z]+$)"),
    ("cooperativa_sat", r"\b(S ?COOP\w*|COOP|COOPS|COOPERATIV\w*|COOPERATIBA\w*|KOOP|KOOPERATIBA\w*|S ?C ?A|S ?C ?L|S ?C ?C ?L|SCCL|S ?A ?T|SAT|"
                        r"SOCIEDAD AGRARIA DE TRANSFORMACION|SOCIETAT AGRARIA)\b"),
    # palabras que también son apellidos (Cámara, Cambra, Iglesia, Escola, Monasterio, Concejo...) solo con complemento
    ("publica", r"\b(AYUNTAMIENTO|AJUNTAMENT|CONCELLO|UDALA|JUNTA VECINAL|JUNTA ADMINISTRATIVA|ENTIDAD LOCAL MENOR|"
                r"ENTIDAD LOCAL|DIPUTACION|DIPUTACIO|CABILDO INSULAR|CONSELL (COMARCAL|INSULAR|DE)|MANCOMUNIDAD|MANCOMUNITAT|"
                r"CONSORCIO|CONSORCI|COMARCA (DE|DEL)|GOBIERNO DE|GOVERN DE|XUNTA DE|GENERALITAT|CONSEJERIA|CONSELLERIA|"
                r"DEPARTAMENTO DE|MINISTERIO|UNIVERSIDAD|UNIVERSITAT|UNIBERTSITATE|INSTITUTO|INSTITUT D|AGENCIA|ORGANISMO|"
                r"EMPRESA PUBLICA|CONFEDERACION HIDROGRAFICA|PARQUE NACIONAL|CSIC|IFAPA|NEIKER|ITACYL|TRAGSA|ENTE PUBLICO|"
                r"PARROQUIA RURAL|CONCEJO (DE|ABIERTO)|JUNTA DE (ANDALUCIA|EXTREMADURA|CASTILLA|GALICIA|COMUNIDADES)|"
                r"COMUNIDAD AUTONOMA|REGION DE MURCIA|PRINCIPADO DE ASTURIAS|CIUDAD AUTONOMA|"
                # 19-10: sin esto, «COMUNIDAD» las mandaba a las sin personalidad (anónimas)
                r"COMUNIDAD DE MADRID|COMUNIDAD FORAL|CABILDO DE|ENTIDAD PUBLICA|SOCIEDAD ESTATAL|SOCIEDAD MERCANTIL ESTATAL|"
                r"FONDO ESPANOL|GOBIERNO VASCO|EUSKO JAURLARITZA|ADMINISTRACION GENERAL|ORGANISMO AUTONOMO)\b"),
    ("asociativa", r"\b(ASOCIACION|ASSOCIACIO|ELKARTEA|FUNDACION|FUNDACIO|FUNDAZIOA|FEDERACION|FEDERACIO|AGRUPACION|"
                   r"AGRUPACIO|UNION DE|UNIO DE|ORGANIZACION|ORGANITZACIO|CONSEJO REGULADOR|CONSELL REGULADOR|"
                   r"COMUNIDAD DE REGANTES|COMUNITAT DE REGANTS|COMUNIDAD DE USUARIOS|COMUNIDAD GENERAL|SINDICATO|"
                   r"SINDICAT|COMUNIDAD DE MONTES|MONTES VECINALES|MONTE VECINAL|MONTES VECINAIS|CMVMC|HEREDAMIENTO|"
                   r"COFRADIA|CAMARA (AGRARIA|OFICIAL)|CAMBRA (AGRARIA|OFICIAL)|COLEGIO (DE|OFICIAL)|COL LEGI|CENTRO DE|"
                   r"ESCUELA (DE|AGRARIA|FAMILIAR)|ESCOLA (AGRARIA|FAMILIAR|D)|CLUB|OBISPADO|ARZOBISPADO|"
                   r"MONASTERIO DE (SANTA|SAN|SANT|SANTO|NUESTRA)|CONVENTO DE|CONGREGACION|"
                   r"IGLESIA (PARROQUIAL|CATOLICA|EVANGELICA)|CARITAS|GRUPO DE ACCION LOCAL|INTERPROFESIONAL|"
                   r"OPFH|JUNTA DE REGANTES|JUNTA CENTRAL|ENTIDAD DE|PATRONATO|MUTUA|MUTUALIDAD|ASOC|ASOCIAC\w*|REGANTES|REGANTS|"
                   r"GDR|GRUPO DE DESARROLLO|DESARROLLO RURAL|DESENVOLUPAMENT RURAL|CRDOP|CR DOP|CONSEJO REG\w*|ASAJA|COAG|"
                   r"ORGANIZACION DE PRODUCTORES|ORG PRODUCTORES)\b"),
    # sin personalidad jurídica propia y formadas por personas físicas: anónimas (decisión 1 de César)
    ("sin_personalidad", r"\b(C ?B|COMUNIDAD DE BIENES|COMUNITAT DE BENS|S ?C ?P|SCP|S ?C|SOCIEDAD CIVIL|SOCIETAT CIVIL|"
                         r"HERENCIA YACENTE|HERENCIA|HEREDEROS|HEREUS|HERMANOS|HNOS|GERMANS|IRMANS|Y OTROS|Y OTRA|"
                         r"Y OTRAS|I ALTRES|ESPOSOS|COMUNIDAD HEREDITARIA|COMUNIDAD|CDAD|COM BIENES|TITULARIDAD COMPARTIDA|"
                         r"TIT COMPARTIDA|HIJOS|FILLS|E HIJOS)\b"),
]
REGLAS = [(g, re.compile(r)) for g, r in REGLAS]
# nombre con aire de empresa pero sin forma jurídica: dudoso (anónimo, y a la lista de revisión si es grande)
RE_DUDOSO = re.compile(r"\d|\b(CAMARA|CAMBRA|IGLESIA|ESCOLA|ESCUELA|MONASTERIO|CONCEJO|CENTRO|ENTIDAD|UNION|COLEGIO|"
                       r"AGENCIA|PARROQUIA|CIA|COMPANIA|AGRICOLA|AGRICOLAS|AGROPECUARIA|AGROPECUARIAS|AGRARIA|AGRARIAS|GANADERIA|GANADERIAS|GANADOS|"
                       r"EXPLOTACION|EXPLOTACIONES|FINCA|FINCAS|BODEGA|BODEGAS|VINEDOS|HACIENDA|CORTIJO|DEHESA|"
                       r"INVERSIONES|PROMOCIONES|GRUPO|HOLDING|SERVICIOS|AGRO|PRODUCCIONES|HORTOFRUTICOLA|"
                       r"FRUTAS|CEREALES|OLIVAR|ACEITES|LACTEOS|GRANJA|GRANJAS|VIVEROS|FORESTAL|PATRIMONIAL|"
                       r"GESTION|COMERCIAL|INDUSTRIAS|EXPORT|TRADING|COMPANY|HOLDINGS|PROPERTIES|ESTATE)\b")


def _cargar_json(nombre, defecto):
    p = os.path.join(AQUI, nombre)
    if not os.path.exists(p):
        return defecto
    with open(p, encoding="utf-8") as f:
        return json.load(f)


# Lista blanca: entidades sin forma jurídica en el nombre que César ha comprobado una a una (nombres de ENTIDADES,
# nunca de personas). Supresiones: huellas sha256 del nombre normalizado de quien ha pedido no salir (decisión 2).
VERIFICADAS = {norm(n) for n in _cargar_json("pac_entidades_verificadas.json", {"entidades": []})["entidades"]}
SUPRIMIDAS = set(_cargar_json("pac_supresiones.json", {"huellas": []})["huellas"])


def clasificar(nombre_n):
    """Grupo del beneficiario por su nombre normalizado. Solo los de VISIBLES salen con nombre."""
    if RE_CODIGO.match(nombre_n.replace(" ", "")):
        return "codigo"
    if huella(nombre_n) in SUPRIMIDAS:
        return "suprimida"
    if nombre_n in VERIFICADAS:
        return "verificada"
    for g, r in REGLAS:
        if r.search(nombre_n):
            return g
    if RE_DUDOSO.search(nombre_n) or len(nombre_n.split()) > 6 or len(nombre_n.split()) == 1:
        return "dudoso"
    return "persona_fisica_probable"


def _norm_muni(s):
    """Nombre de municipio comparable: «Rosal, O» / «Rosal (O)» / «O Rosal» -> ROSALO... sin espacios."""
    s = (s or "").strip()
    m = re.match(r"^(.*)\s*\(([^)]+)\)$", s) or re.match(r"^(.*),\s*([^,]{1,4})$", s)
    if m:
        art = m.group(2).strip()
        s = art.rstrip("'") + ("" if art.endswith("'") else " ") + m.group(1).strip()
    return norm(s).replace(" ", "")


def _indice_ine():
    """(código de provincia INE, nombre comparable) -> nombre oficial del INE (ine_municipios.json de la web)."""
    with open(os.path.join(AQUI, "ine_municipios.json"), encoding="utf-8") as f:
        muni = json.load(f)["municipios"]
    idx = {}
    for cod, (_com, nombre) in muni.items():
        for alt in [nombre] + nombre.split("/"):
            idx.setdefault((cod[:2], _norm_muni(alt)), nombre)
    return idx


def _num(s):
    s = (s or "").strip()
    if not s:
        return 0.0
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return float(s.replace(".", "").replace(",", "."))


def _filas(zip_path):
    """Filas del TXT del FEGA, leídas en flujo. Resuelve las trampas medidas el 17-10: en 2024 cada línea acaba en «;»;
    en 2025 hay «;» dentro del texto de la medida VI.8 (se leen los 8 últimos campos desde la derecha y el municipio se
    localiza por su forma «CP - nombre»)."""
    z = zipfile.ZipFile(zip_path)
    txt = next(i for i in z.infolist() if i.filename.lower().endswith((".txt", ".csv")))
    with io.TextIOWrapper(z.open(txt), encoding="latin-1") as f:
        cab = f.readline().strip().rstrip(";").split(";")
        if cab[:4] != ["BENEFICIARIO", "GRUPO_EMPRESA", "PROVINCIA", "MUNICIPIO"] or cab[-1] != "IMPORTE_EUROS":
            raise SystemExit(f"Cabecera inesperada del FEGA: {cab}. El formato ha cambiado: no se genera nada.")
        for line in f:
            p = line.rstrip("\r\n").split(";")
            if len(p) > 13 and not p[-1].strip():
                p = p[:-1]
            if len(p) < 13:
                yield None
                continue
            der, izq = p[-8:], p[:-8]
            if len(izq) == 5:
                nombre, _grupo, prov, muni, medida = izq
            else:
                j = next((k for k in range(3, len(izq)) if RE_CP.match(izq[k].strip())), 3)
                nombre, prov, muni = ";".join(izq[:j - 2]), izq[j - 1], izq[j]
                medida = ";".join(izq[j + 1:])
            yield nombre, prov, muni, medida, [_num(x) for x in der[3:8]]


def _pagina_fega(ejercicio):
    """(fecha de publicación, URL del ZIP) leídas de la página del FEGA; si no se pueden leer, las conocidas."""
    fecha, url = PUBLICACION_CONOCIDA.get(ejercicio, (None, None))
    try:
        req = urllib.request.Request(PAGINA_FEGA, headers={"User-Agent": "Mozilla/5.0 dinero-publico.com (PAC)"})
        with urllib.request.urlopen(req, timeout=60) as r:
            h = r.read().decode("utf-8", "replace")
        m = re.search(r'href="([^"]*' + str(ejercicio) + r'[^"]*\.zip)"', h, re.I)
        if m:
            url = urllib.request.urljoin(PAGINA_FEGA, m.group(1))
        i = h.find(str(ejercicio) + ".zip") if m is None else h.find(m.group(1))
        f = re.search(r"Fec\.?\s*Pub\.?[^0-9]{0,40}(\d{2})/(\d{2})/(\d{4})", h[max(0, i - 3000):i + 3000])
        if f:
            fecha = f"{f.group(3)}-{f.group(2)}-{f.group(1)}"
    except Exception as e:      # sin red o página cambiada: se usan las fechas comprobadas a mano
        print(f"[pac] no se pudo leer la página del FEGA ({type(e).__name__}); uso la fecha conocida", flush=True)
    return fecha, url


def _caduca(fecha_pub):
    d = dt.date.fromisoformat(fecha_pub)
    try:
        return d.replace(year=d.year + ANIOS_PUBLICACION).isoformat()
    except ValueError:          # 29 de febrero
        return d.replace(year=d.year + ANIOS_PUBLICACION, day=28).isoformat()


def _tramo(importe):
    return next((i for i, lim in enumerate(TRAMOS) if importe <= lim), len(TRAMOS))


def generar(ejercicio, zip_path, salida, fecha_pub, url, revision=None):
    t0 = time.time()
    caduca = _caduca(fecha_pub)
    if caduca <= dt.date.today().isoformat():
        print(f"El ejercicio {ejercicio} caducó el {caduca} (publicado el {fecha_pub}): no se genera.", flush=True)
        sys.exit(SIN_DATOS)
    ine = _indice_ine()
    tot = collections.Counter()
    descuadres = 0
    medidas_txt = {}
    # beneficiario: (nombre normalizado, provincia, clave de municipio) -> datos. Así dos homónimos de pueblos
    # distintos cuentan como dos perceptores (PLAN §2.3).
    benef = {}
    nombres_muni = {}           # clave de municipio -> nombre oficial del INE (o el del FEGA si no casa)
    for fila in _filas(zip_path):
        if fila is None:
            tot["filas_cortas"] += 1
            continue
        nombre, prov_txt, muni, medida, (feaga, feader, cofin, feader_cofin, importe) = fila
        tot["filas"] += 1
        if abs(feaga + feader_cofin - importe) > 0.011 or abs(feader + cofin - feader_cofin) > 0.011:
            descuadres += 1
        tot["feaga"] += feaga
        tot["feader_ue"] += feader
        tot["cofin"] += cofin
        tot["importe"] += importe
        m = RE_CP.match(muni.strip())
        if m:
            cp2 = m.group(1)[:2]
            clave = cp2 + "|" + _norm_muni(m.group(2))
            if clave not in nombres_muni:
                nombres_muni[clave] = ine.get((cp2, _norm_muni(m.group(2))), "~" + m.group(2).strip())
        else:   # «08XXX - XXXXX»: los <= 1.250 € de municipios pequeños, que el FEGA publica solo por provincia
            mp = RE_PROV_SOLO.match(muni.strip())
            cp2 = mp.group(1) if mp else ""
            clave = cp2 + "|"
        if cp2 not in CP_PROVINCIA:
            tot["sin_provincia"] += 1
            tot["importe_sin_provincia"] += importe
            continue
        cod = (medida.strip().split() or ["?"])[0]
        medidas_txt.setdefault(cod, re.sub(r"\s+", " ", medida.strip())[:200])
        nn = norm(nombre)
        k = (nn, clave)
        b = benef.get(k)
        if b is None:
            b = benef[k] = {"g": clasificar(nn), "n": nombre.strip(), "feaga": 0.0, "feader": 0.0, "imp": 0.0,
                            "med": collections.defaultdict(float)}
        b["feaga"] += feaga
        b["feader"] += feader_cofin
        b["imp"] += importe
        b["med"][cod] += importe
    if not tot["filas"]:
        raise SystemExit("El fichero no trae filas.")
    if descuadres > tot["filas"] * 0.001:
        raise SystemExit(f"{descuadres} filas no cuadran (IMPORTE_EUROS <> FEAGA + FEADER_COFIN): no se genera nada.")

    # ─── agregación (aquí desaparecen los nombres de los anónimos) ──────────────────────────────────────────────────
    muni = collections.defaultdict(lambda: {"feaga_v": 0.0, "feader_v": 0.0, "imp_v": 0.0, "n_v": 0,
                                            "feaga_a": 0.0, "feader_a": 0.0, "imp_a": 0.0, "n_a": 0})
    prov = collections.defaultdict(lambda: {"feaga": 0.0, "feader": 0.0, "importe": 0.0, "n_visibles": 0,
                                            "importe_visibles": 0.0, "n_anonimos": 0, "importe_anonimos": 0.0,
                                            "otros_n": 0, "otros_importe": 0.0, "tramos_n": [0] * 6,
                                            "tramos_importe": [0.0] * 6, "medidas": collections.defaultdict(lambda: [0.0, 0.0, 0])})
    pj, grupos, revisar = [], collections.Counter(), []
    for (nn, clave), b in benef.items():
        cp2, mclave = clave.split("|", 1)
        p = CP_PROVINCIA[cp2]
        vis = b["g"] in VISIBLES
        grupos[b["g"]] += 1
        pv = prov[p]
        pv["feaga"] += b["feaga"]
        pv["feader"] += b["feader"]
        pv["importe"] += b["imp"]
        for cod, v in b["med"].items():
            pv["medidas"][cod][0 if vis else 1] += v
            if not vis:
                pv["medidas"][cod][2] += 1
        if vis:
            pv["n_visibles"] += 1
            pv["importe_visibles"] += b["imp"]
            municipio = nombres_muni.get(clave, "") if mclave else ""
            pj.append({"t": "pj", "nombre": b["n"], "tipo": b["g"], "provincia": p, "municipio": municipio.lstrip("~"),
                       "municipio_ine": not municipio.startswith("~") and bool(municipio),
                       "feaga": round(b["feaga"], 2), "feader": round(b["feader"], 2), "importe": round(b["imp"], 2),
                       "medidas": {c: round(v, 2) for c, v in sorted(b["med"].items(), key=lambda t: -abs(t[1]))}})
        else:
            pv["n_anonimos"] += 1
            pv["importe_anonimos"] += b["imp"]
            t = _tramo(b["imp"])
            pv["tramos_n"][t] += 1
            pv["tramos_importe"][t] += b["imp"]
            if revision and b["g"] != "codigo" and b["imp"] >= UMBRAL_REVISION:
                revisar.append((b["imp"], b["g"], b["n"], p, nombres_muni.get(clave, "").lstrip("~")))
        if mclave:
            mu = muni[clave]
            s = "v" if vis else "a"
            mu["feaga_" + s] += b["feaga"]
            mu["feader_" + s] += b["feader"]
            mu["imp_" + s] += b["imp"]
            mu["n_" + s] += 1
        elif not vis:       # filas de nivel provincial (<= 1.250 € en municipios pequeños)
            prov[p]["otros_n"] += 1
            prov[p]["otros_importe"] += b["imp"]

    registros = []
    ocultos = 0
    for clave, mu in muni.items():
        p = CP_PROVINCIA[clave.split("|")[0]]
        nombre = nombres_muni[clave]
        publica_anon = mu["n_a"] >= UMBRAL_ANONIMOS
        if not publica_anon and mu["n_a"]:
            ocultos += 1
            prov[p]["otros_n"] += mu["n_a"]
            prov[p]["otros_importe"] += mu["imp_a"]
        registros.append({
            "t": "muni", "provincia": p, "municipio": nombre.lstrip("~"), "municipio_ine": not nombre.startswith("~"),
            # sin los anónimos cuando son menos de 10: tampoco van en el total (restando se sabría lo de una persona)
            "feaga": round(mu["feaga_v"] + (mu["feaga_a"] if publica_anon else 0), 2),
            "feader": round(mu["feader_v"] + (mu["feader_a"] if publica_anon else 0), 2),
            "importe_visibles": round(mu["imp_v"], 2), "n_visibles": mu["n_v"],
            "importe_anonimos": round(mu["imp_a"], 2) if publica_anon else 0.0,
            "n_anonimos": mu["n_a"] if publica_anon else 0,
            "anonimos_en_provincia": bool(mu["n_a"]) and not publica_anon})
    for p, pv in prov.items():
        # El mismo umbral dentro de la provincia: un tramo o una medida con menos de 10 anónimos no da su importe
        # (sería lo de una o dos personas); y una provincia con menos de 10 anónimos no da nada de ellos.
        pocos = pv["n_anonimos"] < UMBRAL_ANONIMOS
        r = {"t": "prov", "provincia": p, **{k: (round(v, 2) if isinstance(v, float) else v)
                                            for k, v in pv.items() if k not in ("medidas", "tramos_importe")}}
        r["tramos_importe"] = [round(x, 2) if n >= UMBRAL_ANONIMOS else None
                               for x, n in zip(pv["tramos_importe"], pv["tramos_n"])]
        r["medidas"] = {c: [round(a, 2), round(b_, 2) if n >= UMBRAL_ANONIMOS else None, n >= UMBRAL_ANONIMOS]
                        for c, (a, b_, n) in pv["medidas"].items()}
        if pocos:       # (Ceuta, Melilla...) solo lo de las personas jurídicas; FEAGA/FEADER no se separan
            r.update(importe=round(pv["importe_visibles"], 2), feaga=None, feader=None, n_anonimos=0,
                     importe_anonimos=0.0, otros_n=0, otros_importe=0.0, tramos_n=[0] * 6, tramos_importe=[None] * 6,
                     medidas={c: [v[0], None, False] for c, v in r["medidas"].items()})
        r["anonimos_ocultos"] = pocos
        registros.append(r)

    # ─── comprobación final: en lo que sale no hay ninguna persona física con nombre ───────────────────────────────
    for r in pj:
        nn = norm(r["nombre"])
        if r["tipo"] not in VISIBLES or clasificar(nn) != r["tipo"]:
            raise SystemExit("Comprobación de anonimato fallida: no se genera nada.")
    suma = sum(pv["importe"] for pv in prov.values())
    if abs(suma - (tot["importe"] - tot["importe_sin_provincia"])) > 1.0:
        raise SystemExit(f"Las sumas no cuadran ({suma:.2f} frente a {tot['importe']:.2f}): no se genera nada.")
    meta = {"t": "meta", "version": VERSION, "ejercicio": ejercicio, "fecha_publicacion": fecha_pub, "caduca": caduca,
            "fuente": url or PAGINA_FEGA, "pagina": PAGINA_FEGA, "generado": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "filas": tot["filas"], "filas_cortas": tot["filas_cortas"], "importe": round(tot["importe"], 2),
            "feaga": round(tot["feaga"], 2), "feader_ue": round(tot["feader_ue"], 2), "cofin": round(tot["cofin"], 2),
            "sin_provincia": [tot["sin_provincia"], round(tot["importe_sin_provincia"], 2)],
            "beneficiarios": len(benef), "visibles": len(pj), "municipios": len(muni),
            "municipios_anonimos_en_provincia": ocultos, "umbral_anonimos": UMBRAL_ANONIMOS,
            "grupos": dict(grupos), "medidas": medidas_txt}
    with gzip.open(salida, "wt", encoding="utf-8") as f:
        for r in [meta] + registros + pj:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if revision:
        revisar.sort(reverse=True)
        with open(revision, "w", encoding="utf-8-sig") as f:
            f.write("importe;grupo;beneficiario;provincia;municipio\n")
            for imp, g, n, p, mn in revisar:
                f.write(f"{imp:.2f};{g};{n.replace(';', ',')};{p};{mn}\n")
    print(f"[pac] ejercicio {ejercicio}: {tot['filas']} filas, {len(benef)} perceptores ({len(pj)} con nombre), "
          f"{tot['importe'] / 1e6:.1f} M€, {len(muni)} municipios ({ocultos} con anónimos en el total provincial), "
          f"caduca el {caduca}; {time.time() - t0:.0f} s" + (f"; revisión local: {len(revisar)} nombres" if revision else ""),
          flush=True)
    return meta


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ejercicio", type=int, required=True)
    ap.add_argument("--salida", required=True)
    ap.add_argument("--zip", help="ZIP ya descargado (si no, se descarga del FEGA a un temporal que se borra)")
    ap.add_argument("--fecha-publicacion", help="AAAA-MM-DD; por defecto, la de la página del FEGA")
    ap.add_argument("--revision", help="CSV LOCAL con los anónimos de 300.000 € o más (lleva nombres: nunca subirlo)")
    a = ap.parse_args()
    fecha, url = _pagina_fega(a.ejercicio) if not a.fecha_publicacion else (a.fecha_publicacion, None)
    if not fecha:
        print(f"El FEGA aún no ha publicado el ejercicio {a.ejercicio} (o no encuentro su fecha de publicación).", flush=True)
        sys.exit(SIN_DATOS)
    if a.zip:
        generar(a.ejercicio, a.zip, a.salida, fecha, url, a.revision)
        return
    if not url:
        print("No encuentro el enlace del ZIP en la página del FEGA.", flush=True)
        sys.exit(SIN_DATOS)
    with tempfile.TemporaryDirectory() as tmp:
        ruta = os.path.join(tmp, "fega.zip")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 dinero-publico.com (PAC)"})
        with urllib.request.urlopen(req, timeout=600) as r, open(ruta, "wb") as f:
            while True:
                trozo = r.read(1 << 20)
                if not trozo:
                    break
                f.write(trozo)
        generar(a.ejercicio, ruta, a.salida, fecha, url, a.revision)


if __name__ == "__main__":
    sys.exit(main())
