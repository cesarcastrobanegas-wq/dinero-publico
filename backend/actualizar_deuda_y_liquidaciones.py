# encoding: utf-8
"""
Descarga, para cada municipio de CUALQUIER provincia que
MUNICIPIOS_POR_PROVINCIA (app.py) cubra, la deuda viva municipal y el saldo
presupuestario no financiero (superávit/déficit) publicados por el
Ministerio de Hacienda, y genera backend/hacienda_eell.json.

GENERALIZADO 2026-09-13 (a petición de César, ver docstring de
actualizar_poblacion.py para el contexto completo del problema y la misma
solución aplicada aquí): el fichero de Hacienda YA cubre los 8.133
municipios de España en una sola descarga (no hace falta un fichero por
provincia, a diferencia de las tablas del INE) -- el filtro real estaba en
PROVINCIA_MAYUS_A_TITULO, hardcodeado a las 5 provincias originales. Ahora
ese filtro se deriva en vivo de PROVINCIA_LABEL (ver _provincia_mayus_a_clave
más abajo), así que cualquier provincia nueva en MUNICIPIOS_POR_PROVINCIA se
recoge sola. Verificado en vivo (2026-09-13) que la columna "Provincia" del
XLSX usa nombres en MAYÚSCULAS SIN ACENTOS de una sola palabra para el caso
general ("ALICANTE", "ALMERIA", "CASTELLON", "CORDOBA", "JAEN", "MALAGA") --
coincide exactamente con normalizar(nombre).upper() a partir de
PROVINCIA_LABEL, sin necesitar ningún alias. Única excepción real: el fichero
trae el País Vasco con las 3 provincias reales por separado bajo nombres
compuestos ("ARABA/ALAVA", "GIPUZKOA", "BIZKAIA"), que la app agrupa en una
sola clave "pais_vasco" -- ver NOMBRES_MAYUS_OVERRIDE.

Dos ficheros oficiales, mismo ministerio, mismo patrón de descarga directa
(XLSX público, sin sesión ni formulario) -- a diferencia de rendiciondecuentas.es,
aquí el importe SÍ está disponible: son ficheros distintos, no el mismo
portal cuyo visualizador Java ya se descartó en actualizar_cuentas_anuales.py.

1) DEUDA VIVA DE LAS ENTIDADES LOCALES (anual, foto a 31/12)
   https://www.hacienda.gob.es/es-ES/CDI/Paginas/SistemasFinanciacionDeuda/InformacionEELLs/DeudaViva.aspx
   Un único fichero "Ayuntamientos" cubre los 8.133 municipios de España
   (verificado a mano el 2026-08-04: 45/45 Murcia y 221/221 Girona presentes,
   incluidos los municipios con deuda 0 -- no son ausencias, es el valor real).

2) LIQUIDACIONES DEL PRESUPUESTO -- ESTABILIDAD PRESUPUESTARIA, SALDOS NO
   FINANCIEROS (anual, un fichero por ejercicio)
   https://www.hacienda.gob.es/es-ES/CDI/Paginas/EstabilidadPresupuestaria/InformacionCCLLs/Cumplimiento_objetivoestabilidad_EELL.aspx
   Trae, por municipio, el "Importe saldo no financiero (criterio
   presupuestario)" en euros -- el superávit/déficit real del ejercicio,
   decisión de César (2026-08-04): esta es la cifra que se muestra como
   "importe de las cuentas". No todos los municipios han remitido el
   ejercicio más reciente en el momento de la publicación (verificado con
   el fichero de 2024: 218/221 Girona, 40/45 Murcia con dato remitido) --
   por eso se prueban varios ejercicios en orden descendente y se toma el
   primero que sí tenga dato para cada municipio (misma idea que
   "último ejercicio rendido" en actualizar_cuentas_anuales.py, pero
   autocontenida en esta única fuente para no mezclar el año de un fichero
   con el importe de otro).

NINGUNA de las dos URLs de descarga es 100% predecible por patrón: el
nombre de fichero incluye la fecha de publicación, que cambia varias veces
al año a medida que llegan más remisiones -- por eso este script primero
lee las páginas índice (arriba) y extrae por regex el enlace .xlsx vigente,
en vez de construir la URL a mano (a diferencia de ISPA/actualizar_retribuciones.py,
donde sí hace falta tocar una constante a mano cada edición).

Reutiliza el mismo normalizado de acentos/apóstrofes/orden "Núcleo,
Artículo" de actualizar_alcaldes.py (_sin_apostrofes_curvos/
_formas_nucleo_articulo/ALIAS_MUNICIPIO) a través de _emparejar_en_lista()
(ver más abajo, variante local que no depende de MUNICIPIOS_POR_PROV_MIN)
porque el Ministerio de Hacienda usa la misma convención de nomenclátor del
INE que ya resolvía el listado del Ministerio de Política Territorial.

Uso:  pip install openpyxl && python actualizar_deuda_y_liquidaciones.py
(openpyxl no está en requirements.txt por el mismo motivo que en los otros
scripts de este directorio: solo la usa este script, no el servidor.)
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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "es-ES,es;q=0.9",
}

BASE_HACIENDA = "https://www.hacienda.gob.es"
PAGINA_DEUDA_VIVA = (f"{BASE_HACIENDA}/es-ES/CDI/Paginas/SistemasFinanciacionDeuda/"
                     "InformacionEELLs/DeudaViva.aspx")
PAGINA_ESTABILIDAD = (f"{BASE_HACIENDA}/es-ES/CDI/Paginas/EstabilidadPresupuestaria/"
                       "InformacionCCLLs/Cumplimiento_objetivoestabilidad_EELL.aspx")

# Cuántos ejercicios probar (en orden descendente) para el saldo no
# financiero antes de dar por "sin dato" a un municipio -- 3 cubre de sobra
# el retraso de remisión observado (unos pocos municipios cada año).
EJERCICIOS_A_PROBAR = 3

OUT_FILE = f"{BASE_DIR}/hacienda_eell.json"

# Prefijos que PROVINCIA_LABEL antepone al nombre real de la provincia --
# se quitan para obtener el nombre "pelado" (ver actualizar_poblacion.py,
# misma idea). Ampliado 2026-09-18: "Comunidad de "/"Principado de "/
# "Ciudad Autónoma de " no estaban -- madrid/asturias/ceuta/melilla
# llevaban CERO deuda/saldo cargados desde que se conectaron (mismo
# hallazgo que en actualizar_poblacion.py, mismo día: nadie había revisado
# la salida completa "Deuda viva: N/N, Saldo no financiero: N/N" con
# atención hasta auditar Aragón/Galicia).
_PREFIJOS_LABEL = ("Provincia de ", "Región de ", "Comunidad de ",
                   "Principado de ", "Ciudad Autónoma de ")

# Comunidades autónomas que agrupan varias provincias reales bajo una sola
# clave de MUNICIPIOS_POR_PROVINCIA, MÁS provincias/CCAA cuyo nombre en el
# fichero de Hacienda no se deriva de forma directa (abreviado, con
# artículo pospuesto, o con orden distinto al de PROVINCIA_LABEL) -- el
# fichero de Hacienda SÍ las trae desglosadas por su provincia real.
# Verificado en vivo 2026-09-13 para pais_vasco (columna "Provincia" trae
# literalmente "ARABA/ALAVA", "GIPUZKOA", "BIZKAIA", no "PAIS VASCO") y
# 2026-09-18, al auditar por qué A Coruña/La Rioja/Las Palmas/Baleares/
# Santa Cruz de Tenerife llevaban cero deuda/saldo, para el resto:
# inspeccionado el XLSX real (columna "Provincia", hoja "Datos") con
# openpyxl -- "CORUÑA, A" (con tilde real en el fichero), "RIOJA, LA",
# "PALMAS, LAS" (mismo patrón "Núcleo, Artículo" que en
# actualizar_poblacion.py, pero aquí NO se reutiliza esa lógica porque solo
# son 5 casos entre provincias, más simple y verificable listarlos a mano
# que generalizar una transformación automática), "I. BALEARS" (abreviado,
# no "ILLES BALEARS") y "S.C.TENERIFE" (abreviado, no "SANTA CRUZ DE
# TENERIFE").
NOMBRES_MAYUS_OVERRIDE = {
    "pais_vasco": ["ARABA/ALAVA", "GIPUZKOA", "BIZKAIA"],
    "a_coruna": ["CORUÑA, A"],
    "la_rioja": ["RIOJA, LA"],
    "las_palmas": ["PALMAS, LAS"],
    "baleares": ["I. BALEARS"],
    "santa_cruz_tenerife": ["S.C.TENERIFE"],
    # Verificado 2026-09-18 inspeccionando el XLSX real de deuda viva
    # (columna "Provincia", hoja "Datos"): "NAVARRA" a secas, no "COMUNIDAD
    # FORAL DE NAVARRA". El fichero de Liquidaciones/Estabilidad SÍ excluye
    # a Navarra (igual que a País Vasco, ver _procesar_liquidaciones más
    # abajo) -- pero el de Deuda Viva no, Navarra sí aparece ahí.
    "navarra": ["NAVARRA"],
}


def _nombres_mayus_provincia(clave):
    """Nombre(s) tal como aparecen en MAYÚSCULAS en los ficheros de Hacienda
    para una clave de MUNICIPIOS_POR_PROVINCIA -- derivado de PROVINCIA_LABEL
    salvo las claves de NOMBRES_MAYUS_OVERRIDE."""
    if clave in NOMBRES_MAYUS_OVERRIDE:
        return NOMBRES_MAYUS_OVERRIDE[clave]
    label = PROVINCIA_LABEL.get(clave, "")
    for pref in _PREFIJOS_LABEL:
        if label.startswith(pref):
            label = label[len(pref):]
            break
    return [normalizar(label).upper()] if label else []


def _provincia_mayus_a_clave():
    """{nombre en MAYÚSCULAS del fichero de Hacienda: clave interna de la
    app} para TODAS las provincias de MUNICIPIOS_POR_PROVINCIA -- este dict
    es ahora el filtro real (antes era PROVINCIA_MAYUS_A_TITULO, hardcodeado
    a 5 provincias). Cualquier provincia nueva en MUNICIPIOS_POR_PROVINCIA/
    PROVINCIA_LABEL se recoge sola, sin tocar este script."""
    resultado = {}
    for clave in MUNICIPIOS_POR_PROVINCIA:
        for nombre_mayus in _nombres_mayus_provincia(clave):
            resultado[nombre_mayus] = clave
    return resultado


def _emparejar_en_lista(nombre_oficial, lista_municipios):
    """Igual que _emparejar_municipio() de actualizar_alcaldes.py, pero
    contra una lista de municipios cualquiera en vez de MUNICIPIOS_POR_PROV_MIN
    (que solo cubre las 5 provincias originales) -- así funciona igual de
    bien para cualquier provincia nueva de MUNICIPIOS_POR_PROVINCIA.
    Amplía también con el nombre bilingüe partido por "/" (mismo problema y
    mismo fix que en actualizar_poblacion.py, ver ahí el detalle)."""
    partes = nombre_oficial.split("/") if "/" in nombre_oficial else [nombre_oficial]
    candidatos = set()
    for parte in partes:
        candidatos.add(normalizar(_sin_apostrofes_curvos(parte)))
        for forma in _formas_nucleo_articulo(parte):
            candidatos.add(normalizar(_sin_apostrofes_curvos(forma)))
    for m in lista_municipios:
        if normalizar(_sin_apostrofes_curvos(m)) in candidatos:
            return m
        # Navarra (2026-09-18): esta lista guarda el nombre bilingüe
        # completo "X/Y" tal cual (a diferencia de Comunitat Valenciana/
        # País Vasco, que solo guardan la forma castellana) -- hace falta
        # partir también `m` y comparar cada mitad, ver detalle en
        # actualizar_poblacion.py._emparejar_en_lista.
        if "/" in m:
            for parte_m in m.split("/"):
                if normalizar(_sin_apostrofes_curvos(parte_m)) in candidatos:
                    return m
    for buscado in candidatos:
        alias = ALIAS_MUNICIPIO.get(buscado)
        if alias and alias in lista_municipios:
            return alias
    return None

# Los ficheros de Hacienda escriben el artículo catalán/castellano como
# sufijo entre paréntesis ("Far d'Empordà (El)", "Torres de Cotillas
# (Las)"), mientras que el nomenclátor que ya usa esta app (MUNICIPIOS_GIRONA
# y los alias de actualizar_alcaldes.py) lo pone como sufijo con coma
# ("Far d'Empordà, el", "torres de cotillas, las") -- verificado a mano el
# 2026-08-04 al ejecutar este script por primera vez (20 municipios sin
# emparejar solo por esto). Además, el apóstrofe de nombres como "Castell
# d'Aro" llega como el carácter U+00B4 (´, ACUTE ACCENT) en vez de un
# apóstrofe recto o curvo -- ninguno de los dos está cubierto por
# _sin_apostrofes_curvos() (pensada para ’‘\`), así que se resuelve aquí.
# re.IGNORECASE + "Es"/"Ets" (artículo aranés) añadidos 2026-08-09 al
# ejecutar sobre Lleida/Barcelona/Tarragona: Hacienda no siempre capitaliza
# el artículo entre paréntesis ("Esquirol (l')", "Bòrdes (Es)").
_RE_PARENTESIS_ARTICULO = re.compile(r"^(.*)\s\((L'|El|La|Los|Las|Els|Les|Es|Ets)\)$", re.IGNORECASE)


def _limpiar_nombre_hacienda(nombre):
    nombre = (nombre or "").replace("´", "'").strip()
    m = _RE_PARENTESIS_ARTICULO.match(nombre)
    if m:
        base, articulo = m.groups()
        return f"{base}, {articulo.lower()}"
    return nombre


def _descargar_xlsx(session, url):
    r = session.get(url, timeout=60)
    r.raise_for_status()
    return openpyxl.load_workbook(io.BytesIO(r.content), data_only=True)


def _url_absoluta(href):
    if href.startswith("http"):
        return href
    # Los espacios del path real ("sist financiacion y deuda") a veces
    # llegan ya %20-codificados en el HTML y a veces literales -- quote()
    # solo la parte de path, respetando los que ya estén codificados.
    from urllib.parse import quote
    return BASE_HACIENDA + quote(href, safe="/%")


def _descubrir_url_deuda_viva(session):
    """Busca en la página índice el primer enlace a
    'deuda-viva-ayuntamientos-*.xlsx' (o .xls) -- la página los lista con el
    año más reciente primero, verificado a mano el 2026-08-04."""
    r = session.get(PAGINA_DEUDA_VIVA, timeout=30)
    r.raise_for_status()
    m = re.search(r'href="([^"]*deuda-viva-ayuntamientos-\d+\.xlsx?)"', r.text, re.I)
    if not m:
        raise RuntimeError("no se encontró el enlace de Deuda Viva Ayuntamientos en la página índice")
    return _url_absoluta(m.group(1))


def _descubrir_urls_liquidaciones(session, n_ejercicios):
    """Busca en la página índice los N enlaces más recientes a
    'liquidacion{año}eell-estabilidadpresupuestariasaldosnofinanciero*.xlsx',
    devuelve [(ejercicio, url), ...] en orden descendente de año."""
    r = session.get(PAGINA_ESTABILIDAD, timeout=30)
    r.raise_for_status()
    encontrados = re.findall(
        r'href="([^"]*liquidacion(\d{4})eell-estabilidadpresupuestariasaldosnofinanciero[^"]*\.xlsx)"',
        r.text, re.I)
    vistos = set()
    resultado = []
    for href, anio in encontrados:
        anio = int(anio)
        if anio in vistos:
            continue
        vistos.add(anio)
        resultado.append((anio, _url_absoluta(href)))
        if len(resultado) >= n_ejercicios:
            break
    if not resultado:
        raise RuntimeError("no se encontraron enlaces de Liquidaciones/Estabilidad Presupuestaria")
    return resultado


def _procesar_deuda_viva(wb, provincia_mayus_a_clave):
    """Hoja 'Datos': fila de cabecera empieza por 'Ejercicio'; columnas
    (Ejercicio, Código CCAA, CCAA, Código Provincia, Provincia, Código
    Municipio, Municipio, Deuda viva (miles de euros))."""
    ws = wb["Datos"]
    filas = ws.iter_rows(values_only=True)
    for row in filas:
        if row and row[0] == "Ejercicio":
            break
    else:
        raise RuntimeError("no se encontró la fila de cabecera 'Ejercicio' en Deuda Viva")

    resultado = {}
    sin_match = []
    for row in filas:
        if not row or not row[4]:
            continue
        provincia_mayus = str(row[4]).strip().upper()
        clave = provincia_mayus_a_clave.get(provincia_mayus)
        if not clave:
            continue
        nombre_crudo = _limpiar_nombre_hacienda(row[6])
        deuda_miles = row[7]
        if deuda_miles is None:
            continue
        muni = _emparejar_en_lista(nombre_crudo, MUNICIPIOS_POR_PROVINCIA[clave])
        if not muni:
            sin_match.append((clave, nombre_crudo))
            continue
        clave_normalizada = normalizar(muni)
        # Colisión de nombre entre provincias (ver actualizar_poblacion.py
        # para el detalle completo: "Cabanes" en Girona/Castellón, "Torrent"
        # en Girona/Valencia) -- mejor sin dato que un dato de otro municipio.
        if clave_normalizada in resultado and resultado[clave_normalizada]["provincia"] != clave:
            print(f"  [aviso] colisión de nombre: '{muni}' ya existe en "
                  f"{resultado[clave_normalizada]['provincia']} -- se descarta el de {clave}.")
            continue
        resultado[clave_normalizada] = {
            "municipio": muni,
            "provincia": clave,
            "deuda_eur": round(float(deuda_miles) * 1000, 2),
        }
    return resultado, sin_match


def _procesar_liquidaciones(wb, ejercicio, provincia_mayus_a_clave):
    """Hoja 'Ayuntamientos': fila de cabecera empieza por 'Código de la
    entidad local'; columnas de interés: [4]=Nombre, [5]=Provincia,
    [7]=Importe saldo no financiero (€), [9]=Remisión de información (Sí/No).

    OJO -- este fichero trae explícito en su propia cabecera (fila 8 del
    XLSX real, verificado 2026-09-18): "No se incluyen los ayuntamientos de
    País Vasco y Navarra". No es un desajuste de nomenclátor ni un fallo de
    _provincia_mayus_a_clave -- pais_vasco puede tener Deuda Viva completa
    (fichero distinto, sí lo cubre) y Saldo no financiero en 0 a la vez, y
    eso es el comportamiento correcto. No "arreglar" esto buscando un
    override de nombre que no existe."""
    ws = wb["Ayuntamientos"]
    filas = ws.iter_rows(values_only=True)
    for row in filas:
        if row and row[0] == "Código de la entidad local":
            break
    else:
        raise RuntimeError(f"no se encontró la fila de cabecera en Liquidaciones {ejercicio}")

    resultado = {}
    sin_match = []
    for row in filas:
        if not row or not row[5]:
            continue
        provincia_mayus = str(row[5]).strip().upper()
        clave = provincia_mayus_a_clave.get(provincia_mayus)
        if not clave:
            continue
        if row[9] != "Si":
            continue  # no remitido todavía este ejercicio -- se prueba el anterior
        importe = row[7]
        if not isinstance(importe, (int, float)):
            continue
        nombre_crudo = _limpiar_nombre_hacienda(row[4])
        muni = _emparejar_en_lista(nombre_crudo, MUNICIPIOS_POR_PROVINCIA[clave])
        if not muni:
            sin_match.append((clave, nombre_crudo))
            continue
        clave_normalizada = normalizar(muni)
        # Misma colisión de nombre entre provincias que en _procesar_deuda_viva.
        if clave_normalizada in resultado and resultado[clave_normalizada]["provincia"] != clave:
            print(f"  [aviso] colisión de nombre: '{muni}' ya existe en "
                  f"{resultado[clave_normalizada]['provincia']} -- se descarta el de {clave}.")
            continue
        resultado[clave_normalizada] = {
            "municipio": muni,
            "provincia": clave,
            "ejercicio": ejercicio,
            "importe_eur": round(float(importe), 2),
        }
    return resultado, sin_match


def main():
    session = requests.Session()
    session.headers.update(HEADERS)

    provincia_mayus_a_clave = _provincia_mayus_a_clave()

    print("Localizando fichero vigente de Deuda Viva...")
    url_deuda = _descubrir_url_deuda_viva(session)
    print(f"  -> {url_deuda}")
    wb_deuda = _descargar_xlsx(session, url_deuda)
    deuda_por_muni, sin_match_deuda = _procesar_deuda_viva(wb_deuda, provincia_mayus_a_clave)
    print(f"Deuda viva: {len(deuda_por_muni)} municipios emparejados"
          f"{f' (sin emparejar: {sin_match_deuda})' if sin_match_deuda else ''}")

    print(f"\nLocalizando los últimos {EJERCICIOS_A_PROBAR} ficheros de Liquidaciones/Estabilidad...")
    urls_liquidaciones = _descubrir_urls_liquidaciones(session, EJERCICIOS_A_PROBAR)
    for anio, url in urls_liquidaciones:
        print(f"  {anio} -> {url}")

    saldo_por_muni = {}
    fuente_url_por_muni = {}
    for ejercicio, url in urls_liquidaciones:
        print(f"Descargando Liquidaciones {ejercicio}...")
        wb = _descargar_xlsx(session, url)
        datos_ejercicio, sin_match_ejercicio = _procesar_liquidaciones(wb, ejercicio, provincia_mayus_a_clave)
        nuevos = 0
        for clave, info in datos_ejercicio.items():
            if clave not in saldo_por_muni:  # ya cubierto por un ejercicio más reciente
                saldo_por_muni[clave] = info
                fuente_url_por_muni[clave] = url
                nuevos += 1
        print(f"  {nuevos} municipios nuevos con dato remitido en {ejercicio}"
              f" (acumulado: {len(saldo_por_muni)})"
              f"{f' -- sin emparejar: {sin_match_ejercicio}' if sin_match_ejercicio else ''}")

    for clave, info in saldo_por_muni.items():
        info["fuente_url"] = fuente_url_por_muni[clave]

    salida = {
        "generado": time.strftime("%Y-%m-%d %H:%M:%S"),
        "deuda_viva": {
            "fuente_url": url_deuda,
            "municipios": deuda_por_muni,
        },
        "saldo_no_financiero": {
            "municipios": saldo_por_muni,
        },
    }
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=1)

    print()
    for clave, municipios in MUNICIPIOS_POR_PROVINCIA.items():
        esperados = len(municipios)
        n_deuda = sum(1 for v in deuda_por_muni.values() if v["provincia"] == clave)
        n_saldo = sum(1 for v in saldo_por_muni.values() if v["provincia"] == clave)
        print(f"{PROVINCIA_LABEL.get(clave, clave)} -- Deuda viva: {n_deuda}/{esperados}, "
              f"Saldo no financiero: {n_saldo}/{esperados}")
    print(f"\nGuardado en {OUT_FILE}")


if __name__ == "__main__":
    main()
