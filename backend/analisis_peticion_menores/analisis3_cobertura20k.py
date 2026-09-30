import sqlite3
import json
from collections import defaultdict

import os, sys
DB = sys.argv[1] if len(sys.argv) > 1 else "cache_analisis.db"   # copia de trabajo de cache.db (ver DATOS_PETICION_MENORES.md, Apéndice)
db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

POBLACION = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "poblacion.json"),
                            encoding="utf-8"))["municipios"]

PROV_A_CCAA = {
    "barcelona": "Cataluña", "girona": "Cataluña", "tarragona": "Cataluña", "lleida": "Cataluña",
    "pais_vasco": "País Vasco",
    "murcia": "Región de Murcia",
    "madrid": "Comunidad de Madrid",
    "a_coruna": "Galicia", "pontevedra": "Galicia", "lugo": "Galicia", "ourense": "Galicia",
    "baleares": "Illes Balears",
    "valencia": "Comunitat Valenciana", "alicante": "Comunitat Valenciana", "castellon": "Comunitat Valenciana",
    "valladolid": "Castilla y León", "burgos": "Castilla y León", "leon": "Castilla y León",
    "salamanca": "Castilla y León", "palencia": "Castilla y León", "zamora": "Castilla y León",
    "avila": "Castilla y León", "segovia": "Castilla y León", "soria": "Castilla y León",
    "toledo": "Castilla-La Mancha", "ciudad_real": "Castilla-La Mancha", "cuenca": "Castilla-La Mancha",
    "albacete": "Castilla-La Mancha", "guadalajara": "Castilla-La Mancha",
    "zaragoza": "Aragón", "huesca": "Aragón", "teruel": "Aragón",
    "las_palmas": "Canarias", "santa_cruz_tenerife": "Canarias",
    "sevilla": "Andalucía", "malaga": "Andalucía", "cadiz": "Andalucía", "cordoba": "Andalucía",
    "granada": "Andalucía", "almeria": "Andalucía", "jaen": "Andalucía", "huelva": "Andalucía",
    "asturias": "Asturias", "cantabria": "Cantabria", "la_rioja": "La Rioja", "navarra": "Navarra",
    "badajoz": "Extremadura", "caceres": "Extremadura",
}

# Regiones donde la fuente es un AGREGADOR REGIONAL que cubre estructuralmente TODOS los municipios (aunque un
# municipio concreto tenga 0 filas por no haber publicado nada en la ventana) -- Cataluña (RPC) y País Vasco
# (API Euskadi). El resto de fuentes son conectores municipio a municipio: solo cuenta como "con fuente" el
# municipio que de verdad tiene filas en la tabla.
PROVINCIAS_AGREGADOR_REGIONAL = {"barcelona", "girona", "tarragona", "lleida", "pais_vasco"}

municipios_con_filas = {row["municipio"] for row in db.execute("SELECT DISTINCT municipio FROM contratos_menors_locales")}
# normalizar minimamente para cruce (mismo criterio que normalizar() de app.py: minusculas, sin acentos ni signos)
import unicodedata


def normalizar(s):
    s = s.lower().strip()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    s = s.replace("'", " ").replace("-", " ")
    s = " ".join(s.split())
    return s


con_fuente_norm = {normalizar(m) for m in municipios_con_filas}

POB_MIN = 20000
sin_fuente = []
con_fuente_lista = []
for key, info in POBLACION.items():
    pob = info.get("poblacion")
    prov = info.get("provincia")
    if not pob or pob < POB_MIN:
        continue
    nombre = info.get("municipio")
    ccaa = PROV_A_CCAA.get(prov, f"(sin mapear: {prov})")
    if prov in PROVINCIAS_AGREGADOR_REGIONAL:
        con_fuente_lista.append({"municipio": nombre, "poblacion": pob, "ccaa": ccaa, "via": "agregador regional"})
        continue
    if normalizar(nombre) in con_fuente_norm:
        con_fuente_lista.append({"municipio": nombre, "poblacion": pob, "ccaa": ccaa, "via": "conector propio"})
    else:
        sin_fuente.append({"municipio": nombre, "poblacion": pob, "ccaa": ccaa, "provincia": prov})

sin_fuente.sort(key=lambda x: -x["poblacion"])
con_fuente_lista.sort(key=lambda x: -x["poblacion"])

OUT = {
    "poblacion_minima": POB_MIN,
    "n_municipios_esp_pob_min": len(sin_fuente) + len(con_fuente_lista),
    "n_con_fuente": len(con_fuente_lista),
    "n_sin_fuente": len(sin_fuente),
    "sin_fuente": sin_fuente,
    "con_fuente_resumen_por_ccaa": {},
}

por_ccaa_sin = defaultdict(int)
for m in sin_fuente:
    por_ccaa_sin[m["ccaa"]] += 1
OUT["sin_fuente_por_ccaa"] = dict(sorted(por_ccaa_sin.items(), key=lambda x: -x[1]))

por_ccaa_con = defaultdict(int)
for m in con_fuente_lista:
    por_ccaa_con[m["ccaa"]] += 1
OUT["con_fuente_por_ccaa"] = dict(sorted(por_ccaa_con.items(), key=lambda x: -x[1]))

json.dump(OUT, open("resultado_seccion1_20k.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"sin fuente (>= {POB_MIN} hab): {len(sin_fuente)}")
print(f"con fuente: {len(con_fuente_lista)}")
