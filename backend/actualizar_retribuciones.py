# encoding: utf-8
"""
Descarga las retribuciones de alcaldes/alcaldesas publicadas anualmente por
el Portal MTDFP - Espacio ISPA (Información Salarial de Puestos de la
Administración, Ministerio para la Transformación Digital y de la Función
Pública, https://digital.gob.es/funcion-publica/dgfp/espacio-ispa) y genera
backend/retribuciones_ispa.json para CUALQUIER provincia que
MUNICIPIOS_POR_PROVINCIA (app.py) cubra.

GENERALIZADO 2026-09-21 (a petición de César, componente de sueldos ISPA
del Índice de Transparencia -- ver docstring de
actualizar_deuda_y_liquidaciones.py para el mismo patrón aplicado aquí): el
XLSX de ISPA YA cubre 6.934 ayuntamientos de toda España en una sola
descarga -- el filtro real estaba en PROVINCIAS_CUBIERTAS, hardcodeado a
las 5 provincias originales. Ahora se deriva en vivo de PROVINCIA_LABEL
(ver _provincia_ispa_a_clave más abajo), así que cualquier provincia nueva
de MUNICIPIOS_POR_PROVINCIA se recoge sola. Verificado en vivo (2026-09-21,
descarga real del XLSX vigente) que la columna PROVINCIA usa 50 nombres
distintos -- faltan Ceuta y Melilla (no aparecen en el fichero de ISPA,
sin más explicación de la fuente; el resultado sale con 0/1 para esas dos,
no es un fallo de emparejamiento). El resto son en su mayoría el nombre
"pelado" tal cual (mismo criterio que Hacienda), salvo: 3 casos bilingües
("Alacant/Alicante", "Castelló/Castellón", "València/Valencia"), 3 casos
con el artículo pospuesto tras coma ("Coruña, A", "Palmas, Las",
"Rioja, La") y País Vasco desglosado en sus 3 provincias reales
("Araba/Alava", "Gipuzkoa", "Bizkaia") -- ver PROVINCIA_ISPA_OVERRIDE.

NOTA -- por qué esto NO reutiliza PROV_A_KEY/_emparejar_municipio de
actualizar_alcaldes.py (a diferencia de como hacía este script antes de
generalizarse): ese módulo define su propio MUNICIPIOS_POR_PROV_MIN
hardcodeado a las mismas 5 provincias originales (es el listado que usa el
propio script de alcaldes/concejales, con un alcance distinto al de este
script -- generalizarlo no entra en el encargo de hoy), así que
_emparejar_municipio() lanzaría KeyError con cualquier provincia nueva.
En su lugar se usa aquí _emparejar_en_lista(), la misma variante local
"contra una lista de municipios cualquiera" que ya introdujo
actualizar_deuda_y_liquidaciones.py -- copiada literal de ahí (mismo
comentario, mismo motivo).

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
from app import BASE_DIR, normalizar, MUNICIPIOS_POR_PROVINCIA, PROVINCIA_LABEL
from actualizar_alcaldes import _sin_apostrofes_curvos, _formas_nucleo_articulo, ALIAS_MUNICIPIO

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
    # Detectados 2026-09-21 al generalizar a toda España, ejecutando sobre
    # el XLSX real -- convenciones propias del nomenclátor vasco que no
    # encaja ningún patrón genérico de _formas_nucleo_articulo (ese es para
    # "Núcleo, Artículo", esto es un prefijo institucional distinto: solo 2
    # municipios de todo el País Vasco llevan "la Anteiglesia de", no vale
    # la pena generalizar un prefijo para tan pocos casos).
    "Abadiño": "la Anteiglesia de Abadiño",
    "Erandio": "la Anteiglesia de Erandio",
    # Guion en vez de espacio antes del último término.
    "Munitibar-Arbatzegi Gerrikaitz": "Munitibar-Arbatzegi-Gerrikaitz",
    # ISPA usa el nombre bilingüe completo; la app solo guarda la forma
    # corta en castellano.
    "Abanto y Ciérvana-Abanto Zierbena": "Abanto Zierbena",
    "Karrantza Harana/Valle de Carranza": "Carranza",
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

# Prefijos que PROVINCIA_LABEL antepone al nombre real de la provincia --
# se quitan para obtener el nombre "pelado" que usa ISPA (mismo patrón que
# actualizar_deuda_y_liquidaciones.py; aquí se añade "Comunidad Foral de "
# porque ISPA trae Navarra como "Navarra" a secas, no bajo ningún override).
_PREFIJOS_LABEL = ("Provincia de ", "Región de ", "Comunidad de ",
                    "Principado de ", "Ciudad Autónoma de ", "Comunidad Foral de ")

# Provincias cuyo nombre en la columna PROVINCIA del XLSX de ISPA no se
# deriva de forma directa de PROVINCIA_LABEL -- verificado en vivo
# (2026-09-21, descarga real del XLSX vigente) inspeccionando los 50
# nombres distintos de la columna. Ver docstring del módulo para el detalle
# de cada caso.
PROVINCIA_ISPA_OVERRIDE = {
    "pais_vasco": ["Araba/Alava", "Gipuzkoa", "Bizkaia"],
    "alicante": ["Alacant/Alicante"],
    "castellon": ["Castelló/Castellón"],
    "valencia": ["València/Valencia"],
    "a_coruna": ["Coruña, A"],
    "las_palmas": ["Palmas, Las"],
    "la_rioja": ["Rioja, La"],
}


def _provincia_ispa_a_clave():
    """{nombre normalizado tal como aparece en la columna PROVINCIA del
    XLSX de ISPA: clave interna de la app} para TODAS las provincias de
    MUNICIPIOS_POR_PROVINCIA -- este dict es ahora el filtro real (antes
    era PROVINCIAS_CUBIERTAS, hardcodeado a 5 provincias). Cualquier
    provincia nueva en MUNICIPIOS_POR_PROVINCIA/PROVINCIA_LABEL se recoge
    sola, sin tocar este script (salvo que ISPA use para ella un nombre
    irregular, ver PROVINCIA_ISPA_OVERRIDE)."""
    resultado = {}
    for clave in MUNICIPIOS_POR_PROVINCIA:
        if clave in PROVINCIA_ISPA_OVERRIDE:
            nombres = PROVINCIA_ISPA_OVERRIDE[clave]
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


def _emparejar_en_lista(nombre_oficial, lista_municipios):
    """Igual que _emparejar_municipio() de actualizar_alcaldes.py, pero
    contra una lista de municipios cualquiera en vez de MUNICIPIOS_POR_PROV_MIN
    (que solo cubre las 5 provincias originales) -- copiado literal de
    actualizar_deuda_y_liquidaciones.py (mismo motivo: funciona igual de
    bien para cualquier provincia nueva de MUNICIPIOS_POR_PROVINCIA)."""
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
    for buscado in candidatos:
        alias = ALIAS_MUNICIPIO.get(buscado)
        if alias and alias in lista_municipios:
            return alias
    return None


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

    provincia_ispa_a_clave = _provincia_ispa_a_clave()

    print(f"Descargando retribuciones de alcaldes (ISPA, ejercicio {RETRIB_ANIO})...")
    wb = _descargar_xlsx(session, RETRIB_URL_ALCALDES)

    resultado = {}  # clave normalizada de municipio -> datos de retribución
    n_match = 0
    sin_match = []
    n_sin_provincia = 0  # provincia de la fila no reconocida (no en MUNICIPIOS_POR_PROVINCIA)

    for ayuntamiento, provincia, regimen, importe in _filas_alcaldes(wb.active):
        clave = provincia_ispa_a_clave.get(normalizar(str(provincia or "")))
        if not clave:
            n_sin_provincia += 1
            continue
        nombre_limpio = _limpiar_nombre_ispa(str(ayuntamiento).strip())
        nombre_limpio = ALIAS_ISPA.get(nombre_limpio, nombre_limpio)
        muni = _emparejar_en_lista(nombre_limpio, MUNICIPIOS_POR_PROVINCIA[clave])
        if not muni:
            sin_match.append((provincia, ayuntamiento))
            continue
        try:
            importe_num = float(importe)
        except (TypeError, ValueError):
            continue
        clave_normalizada = normalizar(muni)
        # Colisión de nombre entre provincias (mismo caso que
        # actualizar_deuda_y_liquidaciones.py/actualizar_poblacion.py) --
        # mejor sin dato que un dato de otro municipio.
        if clave_normalizada in resultado and resultado[clave_normalizada]["provincia"] != clave:
            print(f"  [aviso] colisión de nombre: '{muni}' ya existe en "
                  f"{resultado[clave_normalizada]['provincia']} -- se descarta el de {clave}.")
            continue
        resultado[clave_normalizada] = {
            "municipio": muni,
            "provincia": clave,
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
    print(f"Filas con provincia no reconocida: {n_sin_provincia}")
    if sin_match:
        print(f"\nSin emparejar ({len(sin_match)}): {sin_match[:20]}")

    print()
    for clave, municipios in MUNICIPIOS_POR_PROVINCIA.items():
        esperados = len(municipios)
        n_prov = sum(1 for v in resultado.values() if v["provincia"] == clave)
        print(f"{PROVINCIA_LABEL.get(clave, clave)}: {n_prov}/{esperados}")

    print(f"\nGuardado en {OUT_FILE}")


if __name__ == "__main__":
    main()
