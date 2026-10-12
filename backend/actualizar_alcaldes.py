# encoding: utf-8
"""
Descarga alcaldes y concejales de la legislatura vigente desde la app
"concejalesApp" del Ministerio de Política Territorial y Memoria
Democrática (https://concejales.redsara.es/consulta/) y genera
backend/alcaldes_concejales.json con los municipios de TODAS las provincias
de MUNICIPIOS_POR_PROVINCIA (ampliado a toda España el 2026-09-30; antes
solo Murcia y Cataluña, ver _provincia_ministerio_a_clave más abajo).

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
from app import BASE_DIR, clave_municipio, MUNICIPIOS_POR_PROVINCIA, PROVINCIA_LABEL, normalizar

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "es-ES,es;q=0.9",
}
URL_HOME = "https://concejales.redsara.es/consulta/"
URL_ALCALDES = "https://concejales.redsara.es/consulta/getAlcaldesLegislatura"
URL_CONCEJALES = "https://concejales.redsara.es/consulta/getConcejalesLegislatura"

OUT_FILE = f"{BASE_DIR}/alcaldes_concejales.json"

# Provincia tal como aparece en la columna "Provincia" del XLSX del
# Ministerio -> clave interna de la app. Hasta el 2026-09-30 era un dict fijo
# de 5 provincias (Murcia + Cataluña); ahora se deriva de PROVINCIA_LABEL
# quitando el prefijo ("Provincia de ", "Región de "...), igual que
# _provincia_ispa_a_clave() de actualizar_retribuciones.py, con los mismos
# nombres irregulares (verificados en el XLSX real: 52 nombres distintos,
# las 3 provincias vascas van a la clave única "pais_vasco").
_PREFIJOS_LABEL = ("Provincia de ", "Región de ", "Comunidad de ",
                    "Principado de ", "Ciudad Autónoma de ", "Comunidad Foral de ")
PROVINCIA_MINISTERIO_OVERRIDE = {
    "pais_vasco": ["Araba/Alava", "Gipuzkoa", "Bizkaia"],
    "alicante": ["Alacant/Alicante"],
    "castellon": ["Castelló/Castellón"],
    "valencia": ["València/Valencia"],
    "a_coruna": ["Coruña, A"],
    "las_palmas": ["Palmas, Las"],
    "la_rioja": ["Rioja, La"],
}


def _provincia_ministerio_a_clave():
    resultado = {}
    for clave in MUNICIPIOS_POR_PROVINCIA:
        if clave in PROVINCIA_MINISTERIO_OVERRIDE:
            nombres = PROVINCIA_MINISTERIO_OVERRIDE[clave]
        else:
            label = PROVINCIA_LABEL.get(clave, "")
            for pref in _PREFIJOS_LABEL:
                if label.startswith(pref):
                    label = label[len(pref):]
                    break
            nombres = [label] if label else []
        for nombre in nombres:
            resultado[normalizar(nombre)] = clave
    return resultado


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
    # Detectados 2026-09-18 al ejecutar actualizar_poblacion.py y
    # actualizar_deuda_y_liquidaciones.py sobre Galicia -- ninguno es un
    # problema de artículo pospuesto (ya cubierto por
    # _formas_nucleo_articulo): son nombres cortos/con o sin guion que el
    # INE/Hacienda usan de forma distinta a nuestra lista. Puesto aquí
    # (compartido) en vez de en un dict local de un solo script para que
    # beneficie a ambos por igual -- mismo criterio que las 2 entradas de
    # arriba.
    "alfoz": "Alfoz do Castrodouro",
    "ribeira de piquin": "A Ribeira de Piquín",
    "castro caldelas": "O Castro de Caldelas",
    "rios": "O Riós",
    "campo lameiro": "O Campo Lameiro",
    "cangas": "Cangas de Morrazo",
    "cerdedo-cotobade": "Cerdedo Cotobade",
    "mondariz-balneario": "Mondariz Balneario",
    # Detectados 2026-09-18 al ejecutar actualizar_poblacion.py sobre
    # Castilla y León (9 provincias). "candin" es un caso distinto a los
    # demás: NO es un desajuste de formato, es un municipio renombrado
    # (Candín -> Valle de Ancares, 23/08/2023) que el INE/Hacienda todavía
    # catalogan con el nombre antiguo en varias tablas -- verificado en
    # Wikipedia (https://es.wikipedia.org/wiki/Cand%C3%ADn_(Le%C3%B3n),
    # redirige a "Valle de Ancares"). El resto son nombres cortos/con
    # grafía distinta que el INE usa frente a la forma verificada contra
    # Wikipedia/Diputación puesta en MUNICIPIOS_BURGOS/SORIA/ZAMORA.
    "candin": "Valle de Ancares",
    "santa maria rivarredonda": "Santa María Ribarredonda",
    "zarzosa de rio pisuerga": "Zarzosa de Riopisuerga",
    "arcos": "Arcos de la Llana",
    "burgo de osma-ciudad de osma": "El Burgo de Osma-Ciudad de Osma",
    "roales": "Roales del Pan",
    "roa de duero": "Roa",
    # Detectado 2026-09-18 al ejecutar actualizar_poblacion.py sobre
    # Castilla-La Mancha (5 provincias): mismo patrón que "arcos"/"roales"
    # de arriba -- el INE usa el nombre corto "Alcoba" en su tabla de
    # población, mientras que el nombre oficial completo (Wikipedia,
    # Diputación de Ciudad Real) es "Alcoba de los Montes".
    "alcoba": "Alcoba de los Montes",
    # Detectados 2026-09-18 al ejecutar actualizar_poblacion.py sobre
    # Navarra: no son desajustes de formato sino RENOMBRES OFICIALES muy
    # recientes (2024-2025, ver Acuerdos del Gobierno de Navarra) que las
    # tablas del INE todavía no reflejan -- el INE sigue usando el nombre
    # antiguo, ya despojado de tilde en su tabla de población ("Goni").
    "goni": "Val de Goñi/Goñerri",
    "noain (valle de elorz)": "Valle de Elorz/Elortzibar",
    "noain (elortzibar)": "Valle de Elorz/Elortzibar",
    # Detectado 2026-09-30 (César): Hacienda (deuda viva y saldo) y la ISPA escriben la capital de Castellón solo en
    # valenciano, "Castelló de la Plana", y la app la guarda como "Castellón de la Plana" -- se quedaba sin deuda,
    # saldo ni sueldo del alcalde (población y cuentas sí casaban).
    "castello de la plana": "Castellón de la Plana",
    # Detectados 2026-09-30 al ampliar actualizar_alcaldes.py a toda España (XLSX del Ministerio de Política
    # Territorial): nombres cortos, guiones o artículos que la lista de la app escribe de otra forma. Los vascos
    # son los mismos que ALIAS_ISPA de actualizar_retribuciones.py (prefijo "la Anteiglesia de", forma bilingüe
    # completa...). Sin alias a propósito: "Ezkio-Itsaso" (Gipuzkoa), que la lista de la app guarda como dos
    # municipios separados, "Ezkio" e "Itsaso" -- repartirle el alcalde a uno de los dos sería inventar.
    "abadino": "la Anteiglesia de Abadiño",
    "erandio": "la Anteiglesia de Erandio",
    "munitibar-arbatzegi gerrikaitz": "Munitibar-Arbatzegi-Gerrikaitz",
    "abanto y ciervana-abanto zierbena": "Abanto Zierbena",
    "valle de carranza": "Carranza",
    "trucios-turtzioz": "Trucíos",
    "arratzu": "Arrazu",
    "valdegovia": "Valdegovia-Gaubea",
    "leaburu": "Leaburu-Txarama",
    "leintz-gatzaga": "Leintz Gatzaga",
    "soraluze-placencia de las armas": "Soraluze",
    "zarza-capilla": "Zarza Capilla",
    "aldehuela de jerte": "Aldehuela del Jerte",
    "oza cesuras": "Oza-Cesuras",
    "o porto do son": "Porto do Son",
    "pastoriza": "A Pastoriza",
    "frontera": "La Frontera",
    "puebla de alborton": "La Puebla de Albortón",
    # Detectados 2026-09-30 al regenerar la deuda viva de Hacienda: "Abanto y Ciérvana/Abanto-Zierbena" (con guion),
    # "Benlloch" (grafía castellana antigua), "El Grado-Lo Grau" (bilingüe con guion) y "Algimia Alfara (de)".
    "abanto-zierbena": "Abanto Zierbena",
    "benlloch": "Benlloc",
    "el grado-lo grau": "El Grado",
    "algimia alfara (de)": "Algímia d'Alfara",
    "medina-sidonia": "Medina Sidonia",
    # Errata del propio Ministerio en la liquidación 2025 ("Poquín" por "Piquín").
    "a ribeira de poquin": "A Ribeira de Piquín",
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
#
# AMPLIADO 2026-09-18 (piloto Galicia + auditoría de actualizar_poblacion.py
# tras conectar Aragón/Extremadura/Galicia): el mismo patrón "Núcleo,
# Artículo" del Ministerio/INE se usa también con artículos CASTELLANOS
# (Los/Las) y GALLEGOS (O/A/Os/As), que esta regex no reconocía -- se
# detectó al ejecutar actualizar_poblacion.py con Galicia recién conectada:
# Lugo 54/67, Ourense 74/92, Pontevedra 48/61 sin emparejar, casi todos del
# tipo "Corgo, O"/"Arnoia, A"/"Estrada, A" (nuestra app ya guarda "O Corgo"/
# "A Arnoia"/"A Estrada", artículo antepuesto, mismo criterio que "A
# Coruña"). Al revisar la salida completa del script también aparecían sin
# emparejar municipios de Cantabria/Santa Cruz de Tenerife/Badajoz/Huesca/
# Teruel/Zaragoza con "Los"/"Las" pospuesto ("Corrales de Buelna, Los",
# "Llanos de Aridane, Los", "Santos de Maimona, Los"...) -- un déficit
# PREEXISTENTE (no causado por los cambios de hoy) que nunca se había
# detectado porque nadie había revisado la lista completa de "sin
# emparejar" con atención. Un solo artículo de una letra (O/A) tiene, en
# teoría, más riesgo de falso positivo que "El/La/Los/Las" -- pero el
# patrón exige que sea EXACTAMENTE eso tras una coma final en un nombre de
# municipio ya filtrado por el propio catálogo del Ministerio, no una
# coincidencia libre en cualquier texto, así que el riesgo real es mínimo.
_RE_NUCLEO_ARTICULO = re.compile(r"^(.+),\s*(El|La|Los|Las|L'|Els|Les|Es|Ets|Sa|Ses|S'|O|A|Os|As)\s*$", re.IGNORECASE)

# "de + el" -> "del", "de + els" -> "dels" (única contracción real en
# catalán con el artículo pospuesto). El nomenclátor PSCP de origen de
# Lleida/Barcelona/Tarragona hereda esta forma contraída de forma
# INCONSISTENTE para una decena de municipios (p.ej. "dels Hostalets de
# Pierola" en vez de "els Hostalets de Pierola") -- ver memoria del
# proyecto: no se normalizó a mano a propósito para no introducir un error
# propio sobre datos de contratos ya verificados, así que aquí se prueban
# ambas formas en vez de "corregir" el nomenclátor. Sin entrada equivalente
# para castellano/gallego: "del"/"da"/"do" SÍ existen como contracciones
# reales en esos idiomas, pero no se ha visto ningún caso real en los
# nomenclátores propios de esta app donde el límite "de + artículo" quede
# justo en el borde del nombre reordenado (a diferencia del catalán, donde
# sí se detectó la inconsistencia real arriba) -- añadir sin un caso real
# que lo justifique sería adivinar, no corregir.
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
    sep = "" if articulo in ("l'", "s'") else " "
    formas = {f"{articulo}{sep}{nucleo}"}
    contraida = _CONTRACCION_DE.get(articulo)
    if contraida:
        formas.add(f"{contraida} {nucleo}")
    return formas


def _emparejar_municipio(nombre_oficial, lista_municipios):
    """El nombre de municipio del XLSX del Ministerio puede no coincidir
    carácter a carácter con el listado propio de la app (acentos, orden
    'la Bisbal' vs 'Bisbal, la', apóstrofes curvos, nombres bilingües con
    "/" en uno u otro lado...) -- empareja por forma normalizada, probando
    también las formas con el artículo reordenado a prefijo (ver
    _formas_nucleo_articulo) y, al final, los alias explícitos. Misma lógica
    que _emparejar_en_lista() de actualizar_retribuciones.py."""
    partes = nombre_oficial.split("/") if "/" in nombre_oficial else [nombre_oficial]
    candidatos = set()
    for parte in partes:
        candidatos.add(normalizar(_sin_apostrofes_curvos(parte)))
        for forma in _formas_nucleo_articulo(parte):
            candidatos.add(normalizar(_sin_apostrofes_curvos(forma)))
    for m in lista_municipios:
        if normalizar(_sin_apostrofes_curvos(m)) in candidatos:
            return m
        if "/" in m:
            for parte_m in m.split("/"):
                if normalizar(_sin_apostrofes_curvos(parte_m)) in candidatos:
                    return m
    # Al revés: la lista de la app pospone el artículo ("Vall de Gallinera, la") y el Ministerio lo antepone
    # ("la Vall de Gallinera").
    for m in lista_municipios:
        if any(normalizar(_sin_apostrofes_curvos(f)) in candidatos for f in _formas_nucleo_articulo(m)):
            return m
    for buscado in candidatos:
        alias = ALIAS_MUNICIPIO.get(buscado)
        if alias and alias in lista_municipios:
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

    prov_a_clave = _provincia_ministerio_a_clave()
    sin_provincia = set()
    resultado = {}  # clave normalizada de municipio -> {municipio, provincia, alcalde, concejales}

    n_alcaldes_match = 0
    sin_match_alcaldes = []
    for fila in _filas(wb_alc.active):
        prov = prov_a_clave.get(normalizar(fila.get("Provincia") or ""))
        if not prov:
            sin_provincia.add(fila.get("Provincia"))
            continue
        provincia = fila.get("Provincia")
        muni = _emparejar_municipio(fila.get("Municipio", ""), MUNICIPIOS_POR_PROVINCIA[prov])
        if not muni:
            sin_match_alcaldes.append((provincia, fila.get("Municipio")))
            continue
        clave = clave_municipio(muni, prov)   # clave compuesta para homónimos (2026-09-30)
        resultado.setdefault(clave, {
            "municipio": muni, "provincia": prov,
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
        prov = prov_a_clave.get(normalizar(fila.get("Provincia") or ""))
        if not prov:
            sin_provincia.add(fila.get("Provincia"))
            continue
        provincia = fila.get("Provincia")
        muni = _emparejar_municipio(fila.get("Municipio", ""), MUNICIPIOS_POR_PROVINCIA[prov])
        if not muni:
            sin_match_conc.add((provincia, fila.get("Municipio")))
            continue
        clave = clave_municipio(muni, prov)   # clave compuesta para homónimos (2026-09-30)
        resultado.setdefault(clave, {
            "municipio": muni, "provincia": prov,
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

    total_esperado = sum(len(m) for m in MUNICIPIOS_POR_PROVINCIA.values())
    print(f"\nAlcaldes emparejados: {n_alcaldes_match}")
    print(f"Filas de concejales emparejadas: {n_conc_match}")
    print(f"Municipios con datos: {len(resultado)} / {total_esperado} esperados")
    if sin_match_alcaldes:
        print(f"\nSin emparejar (alcaldes), {len(sin_match_alcaldes)}: {sin_match_alcaldes}")
    if sin_match_conc:
        print(f"\nSin emparejar (concejales), {len(sin_match_conc)}: {sorted(sin_match_conc, key=str)[:40]}")
    if sin_provincia:
        print(f"\nProvincias del XLSX sin clave en la app: {sorted(map(str, sin_provincia))}")
    faltan = [(m, p) for p, lista in MUNICIPIOS_POR_PROVINCIA.items() for m in lista
              if clave_municipio(m, p) not in resultado]
    if faltan:
        print(f"\nMunicipios de la app SIN ningún dato encontrado ({len(faltan)}): {faltan[:60]}")
    print(f"\nGuardado en {OUT_FILE}")


if __name__ == "__main__":
    main()
