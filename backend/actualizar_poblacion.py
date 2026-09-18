# encoding: utf-8
"""
Descarga la población oficial (INE, Cifras Oficiales de Población de los
Municipios Españoles: Revisión del Padrón Municipal) de CUALQUIER provincia
que MUNICIPIOS_POR_PROVINCIA (app.py) cubra, y genera backend/poblacion.json.

Fuente: API pública Tempus3 del INE (servicios.ine.es/wstempus), sin
scraping HTML ni sesión. Cada provincia tiene su propia tabla dentro de la
operación 22 ("Cifras Oficiales de Población...", Cod_IOE 30245 -- ver
OPERACION_PADRON_ID), con un identificador numérico PERMANENTE (a diferencia
de los ficheros de Hacienda, cuyo nombre de fichero cambia con la fecha de
publicación): cuando el INE publique el padrón del año siguiente, la misma
tabla añade el dato nuevo sola, sin tocar este script.

GENERALIZADO 2026-09-13 (a petición de César, tras comprobar que Alicante/
Castellón/Valencia y las provincias ya cargadas de Andalucía no mostraban
habitantes ni deuda/hab. en producción): antes este script tenía un dict
`TABLAS` hardcodeado a las 5 provincias originales (Murcia/Girona/Lleida/
Barcelona/Tarragona) -- cualquier provincia nueva conectada en
MUNICIPIOS_POR_PROVINCIA se quedaba sin población para siempre, por mucho
que el cron diario ya lanzara este script cada noche. Ahora el id de tabla
de cada provincia se resuelve EN VIVO contra `TABLAS_OPERACION/{id}` (ver
_tablas_padron_por_provincia) y la lista de provincias a procesar sale
directamente de MUNICIPIOS_POR_PROVINCIA/PROVINCIA_LABEL (app.py) -- una
provincia nueva que se añada ahí se recoge sola la próxima vez que corra
este script, sin tocar código aquí. Única excepción real: comunidades
autónomas que agrupan varias provincias INE bajo una sola clave de la app
(hoy solo "pais_vasco" = Araba + Gipuzkoa + Bizkaia) necesitan una entrada
en NOMBRES_INE_OVERRIDE, porque no hay forma de derivar eso solo del label.

?nult=1 devuelve solo el último dato publicado de cada serie. Cada serie es
una combinación municipio×sexo; se filtran las de "Total" (ambos sexos).

TRAMPA verificada a mano el 2026-08-04 con las dos tablas originales: la
SEGUNDA fila de "Nombre" (p.ej. "Girona. Total. Total habitantes. Personas.")
es en realidad el agregado de TODA la provincia, no un municipio -- comparte
literalmente el mismo nombre que la capital de esa provincia (que sí es un
municipio y aparece más abajo, en su posición alfabética real, con su
población mucho menor). Sin descartar esa primera fila, "Girona" en el
diccionario de salida acabaría teniendo el total provincial (832.026) en
vez de la población real de la capital (108.666) si el orden de iteración
cambiase alguna vez. Por eso se descarta explícitamente la primera entrada
de cada tabla y se valida el recuento final contra el número de municipios
esperado (esto sigue aplicando igual de bien a cualquier provincia nueva:
una tabla por provincia, un agregado por tabla).

Uso:  python actualizar_poblacion.py
(Solo usa 'requests', ya en requirements.txt.)
"""
import json
import re
import sys
import time

import requests

sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
from app import BASE_DIR, normalizar, MUNICIPIOS_POR_PROVINCIA, PROVINCIA_LABEL
from actualizar_alcaldes import _sin_apostrofes_curvos, _formas_nucleo_articulo, ALIAS_MUNICIPIO

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36"}

API_BASE = "https://servicios.ine.es/wstempus/js/ES"
API_URL = API_BASE + "/DATOS_TABLA/{tabla_id}?nult=1"
URL_TABLAS_OPERACION = API_BASE + "/TABLAS_OPERACION/{operacion_id}?det=0"
URL_TABLA_HTML = "https://www.ine.es/jaxiT3/Tabla.htm?t={tabla_id}"

# "Cifras Oficiales de Población de los Municipios Españoles: Revisión del
# Padrón Municipal" (Cod_IOE 30245) -- resuelto en vivo el 2026-09-13 contra
# OPERACIONES_DISPONIBLES, no hace falta rebuscarlo salvo que el INE lo
# reasigne (poco probable, es un id interno estable).
OPERACION_PADRON_ID = 22

# Prefijos que PROVINCIA_LABEL antepone al nombre real de la provincia --
# se quitan para obtener el nombre "pelado" que usa el INE en el título de
# cada tabla (p.ej. "Región de Murcia" -> "Murcia", "Provincia de Almería"
# -> "Almería"). Ampliado 2026-09-18: "Comunidad de "/"Principado de " no
# estaban -- madrid/asturias llevaban CERO población cargada desde que se
# conectaron (nadie había revisado la salida completa del script, que sí
# avisaba "no se encontró tabla INE para 'Comunidad de Madrid'"/'Principado
# de Asturias'" en cada ejecución).
_PREFIJOS_LABEL = ("Provincia de ", "Región de ", "Comunidad de ", "Principado de ")

# Comunidades autónomas que agrupan varias provincias INE reales bajo una
# sola clave de MUNICIPIOS_POR_PROVINCIA -- únicas que necesitan mapeo a
# mano, el resto se deriva solo de PROVINCIA_LABEL (ver docstring).
#
# Ampliado 2026-09-18: el INE cataloga sus tablas con el mismo patrón
# "Núcleo, Artículo" que ya se conocía para MUNICIPIOS (ver
# _RE_NUCLEO_ARTICULO en actualizar_alcaldes.py), pero también para el
# nombre de la PROVINCIA/CCAA en sí -- verificado contra el listado real
# de TABLAS_OPERACION/22: "Coruña, A" (no "A Coruña"), "Rioja, La" (no "La
# Rioja"), "Palmas, Las" (no "Las Palmas"), "Balears, Illes" (orden
# invertido, mismo patrón con "Illes" en el lugar del artículo). Solo 4
# casos entre las provincias/CCAA hoy conectadas -- se listan explícitos
# en vez de generalizar una heurística automática de reordenamiento para
# tan pocos casos, más fácil de verificar y sin riesgo de falsos positivos
# en provincias futuras con nombres que no sigan este patrón.
NOMBRES_INE_OVERRIDE = {
    "pais_vasco": ["Araba", "Gipuzkoa", "Bizkaia"],
    "la_rioja": ["Rioja, La"],
    "a_coruna": ["Coruña, A"],
    "las_palmas": ["Palmas, Las"],
    "baleares": ["Balears, Illes"],
    # Verificado 2026-09-18 contra el listado real de TABLAS_OPERACION/22:
    # el INE cataloga la tabla como "Navarra: Población por municipios y
    # sexo" (id 2884) -- "Navarra" a secas, no "Comunidad Foral de Navarra"
    # (el nombre completo que da _PREFIJOS_LABEL tras quitar "Comunidad
    # Foral de ").
    "navarra": ["Navarra"],
}


def _nombres_ine_provincia(clave):
    """Nombre(s) real(es) de provincia INE para una clave de
    MUNICIPIOS_POR_PROVINCIA -- normalmente una sola (ver _PREFIJOS_LABEL),
    salvo las de NOMBRES_INE_OVERRIDE."""
    if clave in NOMBRES_INE_OVERRIDE:
        return NOMBRES_INE_OVERRIDE[clave]
    label = PROVINCIA_LABEL.get(clave, "")
    for pref in _PREFIJOS_LABEL:
        if label.startswith(pref):
            return [label[len(pref):]]
    return [label] if label else []


def _tablas_padron_por_provincia(session):
    """Descubre en vivo (TABLAS_OPERACION/{OPERACION_PADRON_ID}) el id de
    tabla Tempus3 de "Población por municipios y sexo" de CADA provincia
    española, sin hardcodear ningún id. Algunos nombres de tabla son
    bilingües ("Alicante/Alacant", "Castellón/Castelló", "Araba/Álava"), así
    que se indexan ambas partes por si el nombre buscado coincide con
    cualquiera de las dos. Devuelve {nombre_normalizado: tabla_id}."""
    r = session.get(URL_TABLAS_OPERACION.format(operacion_id=OPERACION_PADRON_ID), timeout=30)
    r.raise_for_status()
    resultado = {}
    for t in r.json():
        nombre = t.get("Nombre", "")
        if "municipios y sexo" not in nombre.lower():
            continue
        prefijo = nombre.split(":")[0]
        for parte in prefijo.split("/"):
            resultado[normalizar(parte.strip())] = t["Id"]
    return resultado


def _emparejar_en_lista(nombre_oficial, lista_municipios):
    """Igual que _emparejar_municipio() de actualizar_alcaldes.py, pero
    contra una lista de municipios cualquiera en vez de MUNICIPIOS_POR_PROV_MIN
    (que solo cubre las 5 provincias originales, ver docstring del módulo) --
    así funciona igual de bien para cualquier provincia nueva de
    MUNICIPIOS_POR_PROVINCIA.
    Amplía también con el nombre bilingüe partido por "/" (el INE trae
    "Alcoi/Alcoy", "Ayala/Aiara"... y esta app solo guarda una de las dos
    formas, normalmente la castellana) -- detectado 2026-09-13 al generalizar
    a Comunitat Valenciana/País Vasco: sin esto, ~10-30% de cada provincia
    bilingüe se quedaba sin emparejar."""
    partes = nombre_oficial.split("/") if "/" in nombre_oficial else [nombre_oficial]
    candidatos = set()
    for parte in partes:
        candidatos.add(normalizar(_sin_apostrofes_curvos(parte)))
        for forma in _formas_nucleo_articulo(parte):
            candidatos.add(normalizar(_sin_apostrofes_curvos(forma)))
    for m in lista_municipios:
        if normalizar(_sin_apostrofes_curvos(m)) in candidatos:
            return m
        # Navarra (2026-09-18): a diferencia de Comunitat Valenciana/País
        # Vasco (donde esta app solo guarda UNA forma, la castellana), la
        # lista de Navarra guarda el nombre bilingüe completo "X/Y" tal
        # cual -- así que además de comparar el nombre_oficial partido
        # contra el `m` completo (de arriba), hace falta partir también
        # `m` y comparar cada mitad por separado (p.ej. INE trae
        # "Pamplona/Iruña" y esta lista también, pero normalizar() de la
        # cadena completa con "/" no coincide con ninguna candidata --
        # sin esto, ~1/3 de Navarra se quedaba sin emparejar).
        if "/" in m:
            for parte_m in m.split("/"):
                if normalizar(_sin_apostrofes_curvos(parte_m)) in candidatos:
                    return m
    for buscado in candidatos:
        alias = ALIAS_MUNICIPIO.get(buscado)
        if alias and alias in lista_municipios:
            return alias
    return None


OUT_FILE = f"{BASE_DIR}/poblacion.json"

# El INE llama "Castell-Platja d'Aro" (nombre oficial abreviado) al
# municipio que esta app tiene con su nombre largo completo -- único
# desajuste de nomenclátor encontrado al ejecutar este script por primera
# vez (2026-08-04); mismo patrón que ALIAS_ISPA en actualizar_retribuciones.py.
#
# NOTA 2026-09-18 (piloto Galicia): los alias de municipios gallegos
# detectados al generalizar a Galicia (Alfoz, Ribeira de Piquín, Castro
# Caldelas, Riós, Campo Lameiro, Cangas, Cerdedo-Cotobade, Mondariz-
# Balneario) se pusieron en ALIAS_MUNICIPIO (actualizar_alcaldes.py, dict
# compartido) en vez de aquí, para que beneficien también a
# actualizar_deuda_y_liquidaciones.py, que tiene el mismo tipo de
# desajuste con las mismas fuentes -- este script ya consulta
# ALIAS_MUNICIPIO como fallback dentro de _emparejar_en_lista, así que no
# hace falta duplicarlos aquí. "Cerdedo"/"Cotobade" sueltos SÍ aparecen
# catalogados por separado en el INE pero sin ninguna cifra publicada
# (verificado contra DATOS_TABLA/2890: Data=[] para ambos) -- correcto
# dejarlos sin emparejar, la población real y activa vive solo bajo la
# entrada fusionada "Cerdedo-Cotobade".
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

    print("Resolviendo tablas INE de 'Población por municipios y sexo' de cada provincia...")
    tablas_por_nombre = _tablas_padron_por_provincia(session)

    resultado = {}
    sin_match = []
    fuente_url_por_provincia = {}
    esperados_por_provincia = {}

    for clave, municipios in MUNICIPIOS_POR_PROVINCIA.items():
        nombres_ine = _nombres_ine_provincia(clave)
        if not nombres_ine:
            print(f"  [aviso] {clave}: sin nombre INE resuelto (PROVINCIA_LABEL vacío), se salta.")
            continue

        tabla_ids = []
        for nombre in nombres_ine:
            tabla_id = tablas_por_nombre.get(normalizar(nombre))
            if tabla_id is None:
                print(f"  [aviso] {clave}: no se encontró tabla INE para '{nombre}' -- "
                      f"revisar a mano contra TABLAS_OPERACION/{OPERACION_PADRON_ID}.")
                continue
            tabla_ids.append(tabla_id)
        if not tabla_ids:
            continue

        esperados_por_provincia[clave] = len(municipios)
        print(f"Descargando población de {PROVINCIA_LABEL.get(clave, clave)} (tablas {tabla_ids})...")
        fuente_url_por_provincia[clave] = URL_TABLA_HTML.format(tabla_id=tabla_ids[0])

        filas_provincia = []
        for tabla_id in tabla_ids:
            datos_json = _descargar_tabla(session, tabla_id)
            filas_provincia += _filas_total(datos_json)
            time.sleep(0.3)

        if len(filas_provincia) != esperados_por_provincia[clave]:
            print(f"  [aviso] {len(filas_provincia)} filas tras descartar agregado(s), "
                  f"se esperaban {esperados_por_provincia[clave]} municipios de {clave} -- "
                  f"revisar a mano si el INE cambió la estructura de la tabla.")

        for serie in filas_provincia:
            nombre_crudo = serie["Nombre"].split(".")[0].strip()
            nombre_crudo = ALIAS_POBLACION.get(nombre_crudo, nombre_crudo)
            muni = _emparejar_en_lista(nombre_crudo, municipios)
            if not muni:
                sin_match.append((clave, nombre_crudo))
                continue
            dato = serie["Data"][0]
            clave_normalizada = normalizar(muni)
            # Colisión real detectada al generalizar a más provincias
            # (2026-09-13): "Cabanes" existe en Girona Y Castellón, "Torrent"
            # en Girona Y Valencia -- resultado/POBLACION se indexan solo por
            # normalizar(municipio), sin provincia (mismo patrón en TODOS los
            # `POBLACION.get(normalizar(...))` de app.py), así que el segundo
            # en procesarse pisaría en silencio al primero con el pueblo
            # equivocado. Mejor dejar sin dato (estado ya conocido y seguro)
            # que un dato de OTRO municipio -- no se arregla aquí porque
            # requeriría cambiar la clave en app.py también (POBLACION,
            # DEUDA_VIVA, etc.), fuera de alcance de este encargo.
            if clave_normalizada in resultado and resultado[clave_normalizada]["provincia"] != clave:
                print(f"  [aviso] colisión de nombre: '{muni}' ya existe en "
                      f"{resultado[clave_normalizada]['provincia']} -- se descarta el de {clave} "
                      f"para no sobrescribir con el pueblo equivocado.")
                continue
            resultado[clave_normalizada] = {
                "municipio": muni,
                "provincia": clave,
                "poblacion": int(dato["Valor"]),
                "anio": dato["Anyo"],
            }
        print(f"  {len(filas_provincia)} filas procesadas.")

    salida = {
        "generado": time.strftime("%Y-%m-%d %H:%M:%S"),
        "fuente_url": fuente_url_por_provincia,
        "municipios": resultado,
    }
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=1)

    print()
    for clave, esperados in esperados_por_provincia.items():
        n = sum(1 for v in resultado.values() if v["provincia"] == clave)
        print(f"Población -- {clave}: {n}/{esperados}")
    if sin_match:
        print(f"\nSin emparejar ({len(sin_match)}): {sin_match}")
    print(f"\nGuardado en {OUT_FILE}")


if __name__ == "__main__":
    main()
