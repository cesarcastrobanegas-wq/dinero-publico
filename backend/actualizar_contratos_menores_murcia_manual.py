# encoding: utf-8
"""
Descarga contratos menores de fuentes municipales de Murcia cuyo formato
necesita librerías que NO están en requirements.txt de producción (odfpy para
ODS, openpyxl para XLSX, xlrd para XLS legado, pdfplumber para tablas en PDF)
-- mismo patrón manual/periódico que actualizar_alcaldes.py /
actualizar_retribuciones.py: se ejecuta a mano de vez en cuando (cada
trimestre/año, cuando el ayuntamiento publique un fichero nuevo) y genera
contratos_menores_murcia_manual.json, que app.py carga al arrancar y vuelca a
la tabla compartida contratos_menors_locales (ver
_cargar_contratos_menores_murcia_manual en app.py).

Fuente Álamo de Murcia NO está aquí: su fuente es CSV (módulo estándar `csv`,
sin dependencia nueva), así que se refresca sola en el cron diario --
ver buscar_en_fuentealamo_menores en app.py.

Ninguna de las fuentes de aquí tiene URL predecible por año/trimestre
(verificado 2026-08-03: la carpeta de subida no coincide con el periodo que
describe el fichero) -- por eso todas las funciones scrapean la página de
listado en cada ejecución en vez de adivinar la URL.

Molina de Segura publica los años 2022-2024 en XLS legado (formato binario
OLE2, Composite Document Format vía Apache POI) y solo 2025 en XLSX real
-- verificado con `file` sobre los bytes descargados, no basta con mirar la
extensión de la URL (2022 tiene ADEMÁS una copia en XLSX en un subdominio
distinto, `sedeelectronica.molinadesegura.es`, pero 2023/2024 no tienen
equivalente). Por eso hace falta `xlrd` (que dejó de soportar .xlsx en la
v2.0 pero sigue leyendo .xls perfectamente) además de `openpyxl`.

Lorquí publica un único PDF acumulativo (2015-2026, no por trimestre/año) con
una tabla real de 5 columnas (OBJETO/DURACIÓN/IMPORTE ADJUDICACIÓN/
ADJUDICATARIO/FECHA ADJUDICACIÓN). Aviso importante tras la investigación de
Albudeite (que resultó tener sobre todo anuncios/pliegos SIN adjudicatario,
no decretos de adjudicación): verificado que este PDF de Lorquí SÍ es una
tabla de contratos ya adjudicados de verdad (columna ADJUDICATARIO real en
todas las filas), no anuncios previos. `pdftotext -layout` no sirve aquí
porque las celdas envuelven a varias líneas y las columnas no quedan
alineadas de forma fiable entre filas -- `pdfplumber` sí reconstruye la
tabla real fila a fila. Aun así, la detección de rejilla de pdfplumber no es
perfecta en todas las páginas: algunas filas salen con columnas de más (con
huecos `None` intercalados) -- normalizar_fila_lorqui() los limpia y dedupa;
midiendo contra el documento completo esto recupera el 98,2% de las filas
(553 de 563) a un registro limpio de 5 campos. Sin NIF ni nº de expediente
(la fuente no los publica). Nombres de personas físicas ya en orden
correcto -- no hace falta ninguna variante invertida como en Molina de Segura.

Lorca publica un PDF POR TRIMESTRE (no acumulativo como Lorquí), pero con un
problema real descubierto al investigar (2026-08-03): **el formato de la
tabla ha cambiado al menos dos veces entre 2021 y 2026**:
- 2021-2023 (y los primeros trimestres de 2024): texto corrido SIN tabla
  real detectable por pdfplumber (0 tablas por página) -- los campos
  (Tercero/CIF, Denominación Social, Importe, Concepto, dos fechas de
  registro) vienen pegados sin separador fiable. NO soportado por este
  script.
- Desde algún trimestre de 2024 en adelante (confirmado en 4T-2024, 1T/2T-2026):
  tabla real de 5 columnas `CIF, RAZONSOCIAL, OBJETO, IMPORTE, DURACION`
  -- SIN columna de fecha por contrato (a diferencia del formato antiguo,
  que sí tenía fechas). Es el único formato que procesa este script.
- Por eso `actualizar_lorca()` NO filtra por año fijo como las demás fuentes:
  comprueba la cabecera real de cada PDF (¿la primera fila de la tabla es
  literalmente ['CIF', 'RAZONSOCIAL', 'OBJETO', 'IMPORTE', 'DURACION']?) y
  se salta entero cualquier fichero que no la tenga -- así se adapta solo
  si el ayuntamiento vuelve a cambiar el formato, en vez de producir basura.
  Al no haber fecha por contrato, se usa el primer día del trimestre (según
  el propio nombre del fichero) como fecha aproximada -- una limitación real
  de la fuente, no una decisión de diseño.
- Volumen medido: solo el 1T-2026 tiene 1.383 filas (tasa de normalización
  99,9%) -- mucho más grande que cualquier otra fuente de Murcia salvo Girona.
- Águilas se investigó también (2026-08-03) y se aparcó: la página real solo
  tiene un trimestre publicado (1T-2024, ~8 filas), congelado desde entonces
  -- no compensa el esfuerzo de un parser para ese volumen.

Uso:  pip install odfpy openpyxl xlrd pdfplumber && python actualizar_contratos_menores_murcia_manual.py
"""
import hashlib
import io
import json
import re
import sys
import time

import openpyxl
import pdfplumber
import requests
import xlrd
from bs4 import BeautifulSoup
from odf.opendocument import load as odf_load
from odf.table import Table, TableRow, TableCell
from odf.text import P as odf_P
from urllib.parse import urljoin

sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
from app import BASE_DIR

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "es-ES,es;q=0.9",
}
DESDE_ANY = 2021
OUT_FILE = f"{BASE_DIR}/contratos_menores_murcia_manual.json"

MULA_LISTADO_URL = "https://mula.es/web/transparencia/informacion-sobre-contratos-y-convenios/"
MOLINA_LISTADO_URL = ("https://transparencia.molinadesegura.es/publicidad-activa/"
                       "informacion-sobre-contratacion-convenios-y-subvenciones/contratos-formalizados/")
LORQUI_LISTADO_URL = "https://ayuntamientodelorqui.es/perfil-contratante/contratos-mayores-menores/"
LORCA_LISTADO_URL = "https://transparencia.lorca.es/contratos-menores/"


def _listar_enlaces(url, extension):
    """Devuelve URLs absolutas de los enlaces que acaban en `extension`. Usa
    urljoin porque no todas las fuentes traen href ya absoluto -- Lorca, por
    ejemplo, enlaza con rutas relativas ('pdf/2026/...') resueltas contra la
    URL de la propia página de listado, no contra el dominio raíz."""
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    return sorted({urljoin(url, a["href"]) for a in soup.find_all("a", href=True)
                   if a["href"].lower().endswith(extension)})


def _num_es(valor):
    """Convierte un importe en formato español ('1.020,03') a float."""
    try:
        return float(str(valor).replace("€", "").strip().replace(".", "").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _num_lorca(valor):
    """Lorca usa un formato de número DISTINTO al resto de fuentes: sin
    separador de miles, punto como decimal ('48278.97 €', no '48.278,97 €')
    -- detectado en producción 2026-08-04: usar _num_es() aquí borraba el
    punto decimal asumiéndolo separador de miles y convertía 48278.97 en
    4827897.0 (un "contrato menor" de 4,8 millones de euros, imposible por
    ley -- la pista de que algo iba mal). Si alguna fila trajera coma en vez
    de punto (proveedor extranjero, poco probable pero visto NIFs franceses
    en esta fuente), se interpreta como separador decimal también."""
    limpio = str(valor).replace("€", "").strip()
    if "," in limpio and "." not in limpio:
        limpio = limpio.replace(",", ".")
    try:
        return float(limpio)
    except (TypeError, ValueError):
        return 0.0


def actualizar_mula():
    """Mula: ODS acumulativo por año, columnas NÚMERO EXP/ÁREA/CIF/PROVEEDOR/
    TIPO/OBJETO/FECHA ADJUDICACIÓN/IMPORTE IVA INCL. Nombres de personas
    físicas ya en orden correcto -- sin problema de inversión.

    OJO -- la página de listado también enlaza OTROS ODS de transparencia sin
    relación (obras públicas en ejecución, concesiones, estadísticas de
    contratos), con columnas totalmente distintas -- confirmado en producción
    2026-08-03: sin este filtro, esas filas se colaban interpretadas con el
    esquema de contratos menores y producían basura (fechas de años
    disparatados, NIF vacío). Se exige 'menor' en la URL, igual que ya se
    hace para Fuente Álamo."""
    urls = [u for u in _listar_enlaces(MULA_LISTADO_URL, ".ods") if "menor" in u.lower()]
    print(f"Mula: {len(urls)} ficheros ODS de contratos menores encontrados en el listado")
    registros = {}
    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
        except Exception as e:
            print(f"  Mula: {url} no disponible ({type(e).__name__})")
            continue
        doc = odf_load(io.BytesIO(r.content))
        tablas = doc.spreadsheet.getElementsByType(Table)
        if not tablas:
            continue
        filas = tablas[0].getElementsByType(TableRow)
        cabecera = None
        for fila_odf in filas:
            celdas = fila_odf.getElementsByType(TableCell)
            valores = ["".join(str(p) for p in c.getElementsByType(odf_P)) for c in celdas]
            if cabecera is None:
                cabecera = [v.strip() for v in valores]
                continue
            fila = dict(zip(cabecera, valores))
            expediente = (fila.get("NÚMERO EXP") or "").strip()
            proveedor = (fila.get("PROVEEDOR") or "").strip()
            fecha_raw = (fila.get("FECHA ADJUDICACIÓN") or "").strip()
            if not expediente or not proveedor:
                continue
            m = re.match(r"(\d{2})/(\d{2})/(\d{4})", fecha_raw)
            if not m:
                continue
            dia, mes, anio = m.groups()
            anio_actual = int(time.strftime("%Y"))
            # Cordura: una fecha de adjudicación NUNCA puede ser futura (se
            # registra a posteriori) -- detectado en producción 2026-08-03: el
            # expediente 'COME/2024/0648' trae la fecha '28/11/2029', un typo
            # real de la fuente (mismo tipo de error visto en Fuente Álamo).
            # El propio formato de expediente de Mula no es fiable para sacar
            # el año de refuerzo (cambia de orden entre ficheros: unos años
            # usan 'COME/NNNN/AAAA', otros 'COME/AAAA/NNNN'), así que aquí solo
            # se aplica la cota de cordura sobre la fecha, no un año alternativo.
            if int(anio) < DESDE_ANY or int(anio) > anio_actual:
                continue
            registros[f"Mula::{expediente}"] = {
                "id":               f"Mula::{expediente}",
                "municipio":        "Mula",
                "provincia":        "murcia",
                "fuente":           "mula",
                "organisme":        "Ayuntamiento de Mula",
                "adjudicatari":     proveedor,
                "nif":              (fila.get("CIF") or "").strip(),
                "import_num":       _num_es(fila.get("IMPORTE IVA INCL") or ""),
                "data_adjudicacio": f"{anio}-{mes}-{dia}",
                "tipus_contracte":  (fila.get("TIPO") or "").strip(),
                "descripcio":       (fila.get("OBJETO") or "").strip(),
                "codi_cpv":         "",
                "exercici":         anio,
            }
    registros = list(registros.values())
    print(f"Mula: {len(registros)} contratos menores extraídos (desde {DESDE_ANY})")
    return registros


def _iter_hojas_workbook(contenido):
    """Devuelve una lista de listas de filas (tuplas de valores), una por
    hoja, funcionando igual para XLSX real (ZIP, firma 'PK') que para XLS
    legado OLE2 (firma '\\xd0\\xcf\\x11\\xe0') -- Molina de Segura publica
    ambos formatos según el año, y la extensión de la URL no es de fiar (ver
    docstring del módulo)."""
    if contenido[:2] == b"PK":
        wb = openpyxl.load_workbook(io.BytesIO(contenido), data_only=True)
        return [list(wb[ws].iter_rows(values_only=True)) for ws in wb.sheetnames]
    else:
        wb = xlrd.open_workbook(file_contents=contenido)
        return [[ws.row_values(i) for i in range(ws.nrows)] for ws in wb.sheets()]


def actualizar_molina_segura():
    """Molina de Segura: XLSX/XLS anual que mezcla 'Contrato Mayor' y
    'Contrato Menor' -- se filtra por la columna 'Tipo de contratación'. El
    campo 'Contratistas' viene 'NIF - NOMBRE' (varios separados por ' | ' si
    hay UTE; aquí solo se guarda el primero, igual que se hace con las UTE de
    PSCP en app.py). OJO: para personas físicas el NOMBRE viene invertido sin
    coma ('APELLIDOS NOMBRE') -- NO se corrige aquí a propósito (nunca se
    toca el texto que se muestra en pantalla); el detector de cargos públicos
    ya prueba esa variante en tiempo de render, ver
    _variantes_nombre_para_detector en app.py."""
    urls = _listar_enlaces(MOLINA_LISTADO_URL, (".xlsx", ".xls"))
    print(f"Molina de Segura: {len(urls)} ficheros XLSX/XLS encontrados en el listado")
    registros = {}
    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
        except Exception as e:
            print(f"  Molina de Segura: {url} no disponible ({type(e).__name__})")
            continue
        try:
            hojas = _iter_hojas_workbook(r.content)
        except Exception as e:
            print(f"  Molina de Segura: {url} no se pudo leer ({type(e).__name__})")
            continue
        for filas_hoja in hojas:
            cabecera = None
            for row in filas_hoja:
                if cabecera is None:
                    if row and len(row) > 1 and row[1] == "Entidad Contratante":
                        cabecera = row
                    continue
                if not row or len(row) < 2 or not row[1]:
                    continue
                fila = dict(zip(cabecera, row))
                if (fila.get("Tipo de contratación") or "").strip() != "Contrato Menor":
                    continue
                expediente = str(fila.get("Número de Referencia del Contrato") or "").strip()
                if not expediente:
                    continue
                fecha_raw = str(fila.get("Fecha formalización") or "").strip()
                m = re.match(r"(\d{2})-(\d{2})-(\d{4})", fecha_raw)
                if not m:
                    continue
                dia, mes, anio = m.groups()
                # Misma cota de cordura que Mula: una fecha de formalización
                # no puede ser futura.
                if int(anio) < DESDE_ANY or int(anio) > int(time.strftime("%Y")):
                    continue
                contratistas = str(fila.get("Contratistas") or "").strip()
                primero = contratistas.split(" | ")[0]
                nif, _, nombre = primero.partition(" - ")
                importe = (fila.get("Importe total ofertado (con impuestos) (en euros)")
                           or fila.get("Importe total ofertado (sin impuestos) (en euros)") or 0)
                registros[f"Molina de Segura::{expediente}"] = {
                    "id":               f"Molina de Segura::{expediente}",
                    "municipio":        "Molina de Segura",
                    "provincia":        "murcia",
                    "fuente":           "molina-segura",
                    "organisme":        (fila.get("Entidad Contratante") or "").strip(),
                    "adjudicatari":     (nombre.strip() or primero.strip()),
                    "nif":              nif.strip(),
                    "import_num":       _num_es(importe),
                    "data_adjudicacio": f"{anio}-{mes}-{dia}",
                    "tipus_contracte":  str(fila.get("Tipo de Contrato") or "").strip(),
                    "descripcio":       str(fila.get("Objeto del Contrato") or "").strip(),
                    "codi_cpv":         str(fila.get("Código CPV del objeto del contrato") or "").strip(),
                    "exercici":         anio,
                }
    registros = list(registros.values())
    print(f"Molina de Segura: {len(registros)} contratos menores extraídos (desde {DESDE_ANY})")
    return registros


def _normaliza_fila_lorqui(row):
    """Limpia una fila cruda de pdfplumber: quita celdas None/vacías y
    colapsa duplicados consecutivos (alguna fila trae el objeto repetido dos
    veces por un artefacto de la detección de rejilla de la tabla). Devuelve
    la fila limpia solo si quedan exactamente 5 campos (objeto, duración,
    importe, adjudicatario, fecha) -- si no, se descarta como no fiable."""
    vals = [(c or "").strip() for c in row if c and str(c).strip()]
    limpio = []
    for v in vals:
        if not limpio or limpio[-1] != v:
            limpio.append(v)
    return limpio if len(limpio) == 5 else None


def actualizar_lorqui():
    """Lorquí: PDF único acumulativo (2015-2026) con tabla real de contratos
    ya adjudicados -- ver docstring del módulo para el porqué de usar
    pdfplumber en vez de pdftotext y la tasa de recuperación medida (98,2%)."""
    urls = [u for u in _listar_enlaces(LORQUI_LISTADO_URL, ".pdf") if "menor" in u.lower()]
    print(f"Lorquí: {len(urls)} ficheros PDF de contratos menores encontrados en el listado")
    registros = {}
    anio_actual = int(time.strftime("%Y"))
    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=60)
            r.raise_for_status()
        except Exception as e:
            print(f"  Lorquí: {url} no disponible ({type(e).__name__})")
            continue
        with pdfplumber.open(io.BytesIO(r.content)) as pdf:
            for pagina in pdf.pages:
                for tabla in pagina.extract_tables():
                    for row in tabla:
                        if not row or not row[0] or "OBJETO" in (row[0] or ""):
                            continue
                        fila = _normaliza_fila_lorqui(row)
                        if not fila:
                            continue
                        objeto, duracion, importe, adjudicatario, fecha_raw = fila
                        m = re.match(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", fecha_raw)
                        if not m or not re.search(r"\d", importe):
                            continue
                        dia, mes, anio = m.groups()
                        if len(anio) == 2:
                            anio = f"20{anio}"
                        # Cordura: alguna celda de fecha trae dos fechas pegadas
                        # ("28/27/2025, Modif. 12/09/2225", un typo real de la
                        # fuente con mes=27 inexistente) -- se descarta si
                        # día/mes no son un calendario válido, igual que las
                        # cotas de cordura ya aplicadas a Fuente Álamo/Mula.
                        if not (anio.isdigit() and 1 <= int(mes) <= 12 and 1 <= int(dia) <= 31):
                            continue
                        if int(anio) < DESDE_ANY or int(anio) > anio_actual:
                            continue
                        # Sin nº de expediente en esta fuente -- id por hash
                        # de contenido (objeto+adjudicatario+fecha+importe),
                        # estable frente a re-ejecuciones mientras el PDF no
                        # cambie esa fila.
                        clave_hash = hashlib.md5(
                            f"{objeto}|{adjudicatario}|{fecha_raw}|{importe}".encode("utf-8")
                        ).hexdigest()[:12]
                        # Sin columna de "tipo de contrato" en esta fuente --
                        # se reutiliza esa columna para mostrar la duración
                        # (dato real que aporta la fuente), limpiando los
                        # placeholders "----"/"-----" que usa el propio PDF
                        # para "no aplica".
                        duracion_limpia = duracion.replace("\n", " ").strip()
                        if re.fullmatch(r"-{2,}", duracion_limpia):
                            duracion_limpia = ""
                        registros[f"Lorquí::{clave_hash}"] = {
                            "id":               f"Lorquí::{clave_hash}",
                            "municipio":        "Lorquí",
                            "provincia":        "murcia",
                            "fuente":           "lorqui",
                            "organisme":        "Ayuntamiento de Lorquí",
                            "adjudicatari":     adjudicatario.replace("\n", " ").strip(),
                            "nif":              "",
                            "import_num":       _num_es(importe),
                            "data_adjudicacio": f"{anio}-{mes.zfill(2)}-{dia.zfill(2)}",
                            "tipus_contracte":  duracion_limpia,
                            "descripcio":       objeto.replace("\n", " ").strip(),
                            "codi_cpv":         "",
                            "exercici":         anio,
                        }
    registros = list(registros.values())
    print(f"Lorquí: {len(registros)} contratos menores extraídos (desde {DESDE_ANY})")
    return registros


_LORCA_CABECERA = ("CIF", "RAZONSOCIAL", "OBJETO", "IMPORTE", "DURACION")

_LORCA_MESES_TRIMESTRE = {
    "primer": "01", "1": "01",
    "segundo": "04", "2": "04",
    "tercer": "07", "3": "07",
    "cuarto": "10", "4": "10",
}


def _lorca_fecha_aprox(nombre_fichero):
    """Sin fecha por contrato en el formato nuevo (ver docstring del módulo)
    -- se aproxima al primer día del trimestre, deducido del propio nombre
    del fichero ('Primer trimestre 2026', 'Cuarto_trimestre_2024',
    'Segundo-trimestre-2024', variantes con espacio/guion/guion bajo)."""
    m = re.search(r"(primer|segundo|tercer|cuarto)[\s_-]*trimestre[\s_-]*(\d{4})",
                  nombre_fichero, re.I)
    if not m:
        return "", ""
    mes = _LORCA_MESES_TRIMESTRE[m.group(1).lower()]
    anio = m.group(2)
    return f"{anio}-{mes}-01", anio


def actualizar_lorca():
    """Lorca: un PDF por trimestre (no acumulativo). Solo se procesan los
    ficheros cuya tabla tenga la cabecera nueva (CIF/RAZONSOCIAL/OBJETO/
    IMPORTE/DURACION) -- los de formato antiguo (texto corrido, sin tabla
    real) se detectan y se saltan, ver docstring del módulo."""
    urls = [u for u in _listar_enlaces(LORCA_LISTADO_URL, ".pdf") if "trimestre" in u.lower()]
    print(f"Lorca: {len(urls)} ficheros PDF de contratos menores encontrados en el listado")
    registros = {}
    saltados = 0
    for url in urls:
        fecha_aprox, anio = _lorca_fecha_aprox(url)
        if not anio or int(anio) < DESDE_ANY:
            continue
        try:
            r = requests.get(url, headers=HEADERS, timeout=60)
            r.raise_for_status()
        except Exception as e:
            print(f"  Lorca: {url} no disponible ({type(e).__name__})")
            continue
        try:
            with pdfplumber.open(io.BytesIO(r.content)) as pdf:
                primera_tabla = pdf.pages[0].extract_tables()
                cabecera_ok = bool(primera_tabla and primera_tabla[0] and tuple(
                    (c or "").strip().upper() for c in primera_tabla[0][0][0:5]
                ) == _LORCA_CABECERA)
                if not cabecera_ok:
                    saltados += 1
                    continue
                for pagina in pdf.pages:
                    for tabla in pagina.extract_tables():
                        for row in tabla:
                            if not row or not row[0] or row[0].strip().upper() == "CIF":
                                continue
                            fila = [(c or "").strip() for c in row]
                            if len(fila) != 5:
                                continue
                            cif, razonsocial, objeto, importe, duracion = fila
                            if not razonsocial or not re.search(r"\d", importe):
                                continue
                            clave_hash = hashlib.md5(
                                f"{cif}|{razonsocial}|{objeto}|{importe}|{fecha_aprox}".encode("utf-8")
                            ).hexdigest()[:12]
                            registros[f"Lorca::{clave_hash}"] = {
                                "id":               f"Lorca::{clave_hash}",
                                "municipio":        "Lorca",
                                "provincia":        "murcia",
                                "fuente":           "lorca",
                                "organisme":        "Ayuntamiento de Lorca",
                                "adjudicatari":     razonsocial.replace("\n", " ").strip(),
                                "nif":              cif,
                                "import_num":       _num_lorca(importe),
                                "data_adjudicacio": fecha_aprox,
                                "tipus_contracte":  duracion.replace("\n", " ").strip(),
                                "descripcio":       objeto.replace("\n", " ").strip(),
                                "codi_cpv":         "",
                                "exercici":         anio,
                            }
        except Exception as e:
            print(f"  Lorca: {url} no se pudo procesar ({type(e).__name__})")
            continue
    registros = list(registros.values())
    print(f"Lorca: {len(registros)} contratos menores extraídos "
          f"({saltados} ficheros con formato antiguo descartados, desde {DESDE_ANY})")
    return registros


# ─── MURCIA CAPITAL ──────────────────────────────────────────────────────────
# Retomado 2026-09-13 (ver memoria del proyecto): un intento anterior de
# adivinar las URLs de los PDF por año dio 404 dos veces seguidas. La fuente
# real y permanente es el propio indicador de transparencia D1-49 ("Se
# publican periódicamente los Contratos menores...") en
# https://transparencia.mimurcia.murcia.es/es/transparencia/65 -- esa página
# lista un enlace "AÑO NNNN" por cada PDF anual, con URLs que SÍ cambian
# (llevan la fecha de publicación en la ruta), así que hay que leer el
# índice en cada ejecución, igual que Lorca/Lorquí, no construir la URL a
# mano.
#
# Formato verificado descargando y parseando 2021-2024 con pdfplumber
# (además del de 2025 ya visto antes): NO hay <table> real detectable por
# extract_tables() (a diferencia de Lorca) -- hay que parsear línea a línea
# el texto plano de cada página, cada fila con columnas ADJUDICATARIO / TIPO
# (Servicios|Suministros|Obras) / F.ENTRADA (dd/mm/aaaa, sin espacio fijo
# antes de la descripción que sigue) / DESCRIPCIÓN / IMPORTE, más líneas de
# subtotal "<adjudicatario> Total <tipo> <importe>" que se descartan solas
# porque no tienen fecha. Sin NIF ni número de expediente en este formato.
#
# 2021 tiene un formato DISTINTO (columna extra "DOCUMENTO" con el NIF, y el
# nombre del adjudicatario envuelve a una segunda línea en el texto extraído)
# que este parser NO reconoce -- se salta explícitamente, mismo criterio que
# Lorca con su formato antiguo: mejor no procesarlo que arriesgarse a
# producir basura mezclando columnas.
#
# Aviso de rendimiento: cada PDF anual tiene 100-130 páginas y pdfplumber
# tarda varios minutos por año (~6 min medido con el de 2024) -- ejecutar
# este script completo (2022-2025) puede tardar 20-30 min solo en esta
# fuente. Coherente con que viva en el script manual/periódico y no en el
# cron diario (mismo motivo que Mula/Molina/Lorquí, ver docstring del
# módulo), aunque aquí la razón sea el tiempo de proceso y no una
# dependencia nueva.
MURCIA_CAPITAL_INDICE_URL = "https://transparencia.mimurcia.murcia.es/es/transparencia/65"
_MURCIA_CAPITAL_TIPOS = ("Servicios", "Suministros", "Obras")
_RE_MURCIA_CAPITAL_FILA = re.compile(
    r"^(?P<adj>.+?)\s+(?P<tipo>" + "|".join(_MURCIA_CAPITAL_TIPOS) + r")\s+"
    r"(?P<fecha>\d{2}/\d{2}/\d{4})(?P<desc>.*?)\s+"
    r"(?P<importe>[\d.]+,\d{2})\s*€?\s*$"
)


def _listar_anios_murcia_capital():
    """Lee el índice real de "Contratos menores" (indicador de transparencia
    D1-49, ver nota de arriba) y devuelve [(año, url_pdf), ...] para cada
    enlace de texto literal "AÑO NNNN" -- excluye de paso el enlace suelto
    de "Nueva instrucción de Contratos Menores" (mismo indicador, no es un
    listado de contratos) porque su texto no encaja ese patrón."""
    r = requests.get(MURCIA_CAPITAL_INDICE_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    resultado = []
    for a in soup.find_all("a", href=True):
        texto = a.get_text(strip=True)
        m = re.match(r"A[ÑN]O\s*(\d{4})$", texto, re.I)
        if m and a["href"].lower().endswith(".pdf"):
            resultado.append((int(m.group(1)), urljoin(MURCIA_CAPITAL_INDICE_URL, a["href"])))
    return sorted(set(resultado))


def _parsear_pdf_murcia_capital(contenido, anio):
    """Parsea un PDF anual de Murcia capital línea a línea (ver nota de
    arriba: sin tabla real detectable, columnas ADJUDICATARIO/TIPO/
    F.ENTRADA/DESCRIPCIÓN/IMPORTE). Sin expediente ni NIF en este formato,
    así que la clave es un hash del contenido de la fila (mismo patrón que
    Lorca)."""
    registros = {}
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        for pagina in pdf.pages:
            texto = pagina.extract_text() or ""
            for linea in texto.split("\n"):
                m = _RE_MURCIA_CAPITAL_FILA.match(linea.strip())
                if not m:
                    continue
                adjudicatario = m.group("adj").strip()
                descripcion = m.group("desc").strip()
                if not adjudicatario or not descripcion:
                    continue
                dia, mes, anio_fecha = m.group("fecha").split("/")
                clave_hash = hashlib.md5(
                    f"{adjudicatario}|{m.group('tipo')}|{m.group('fecha')}|"
                    f"{descripcion}|{m.group('importe')}".encode("utf-8")
                ).hexdigest()[:12]
                registros[f"MurciaCapital::{clave_hash}"] = {
                    "id":               f"MurciaCapital::{clave_hash}",
                    "municipio":        "Murcia",
                    "provincia":        "murcia",
                    "fuente":           "murcia-capital",
                    "organisme":        "Ayuntamiento de Murcia",
                    "adjudicatari":     adjudicatario,
                    "nif":              "",
                    "import_num":       _num_es(m.group("importe")),
                    "data_adjudicacio": f"{anio_fecha}-{mes}-{dia}",
                    "tipus_contracte":  m.group("tipo"),
                    "descripcio":       descripcion,
                    "codi_cpv":         "",
                    "exercici":         str(anio),
                }
    return registros


def actualizar_murcia_capital():
    anios_urls = [(a, u) for a, u in _listar_anios_murcia_capital()
                  if a >= DESDE_ANY and a != 2021]
    print(f"Murcia capital: {len(anios_urls)} PDF anuales encontrados en el índice real (transparencia/65)")
    registros = {}
    for anio, url in anios_urls:
        print(f"  Descargando y parseando {anio} (puede tardar varios minutos)...")
        try:
            r = requests.get(url, headers=HEADERS, timeout=120)
            r.raise_for_status()
        except Exception as e:
            print(f"  Murcia capital {anio}: {url} no disponible ({type(e).__name__})")
            continue
        try:
            filas_anio = _parsear_pdf_murcia_capital(r.content, anio)
        except Exception as e:
            print(f"  Murcia capital {anio}: no se pudo procesar ({type(e).__name__})")
            continue
        registros.update(filas_anio)
        print(f"  Murcia capital {anio}: {len(filas_anio)} contratos extraídos")
    registros = list(registros.values())
    print(f"Murcia capital: {len(registros)} contratos menores extraídos en total "
          f"(desde {DESDE_ANY}, excluido 2021 por formato distinto)")
    return registros


# San Pedro del Pinatar (añadido 2026-09-24): un PDF anual por ejercicio en
# el perfil del contratante (2022-2025 confirmados), con TABLA REAL detectable
# por pdfplumber.extract_tables() (a diferencia de Murcia capital). La
# estructura de columnas cambia entre años (9/10/11 columnas, con o sin fecha
# de formalización, con o sin "Canon anual"), así que las columnas se
# localizan por el texto de la cabecera, no por posición fija. Hechos
# verificados contra los PDFs reales:
# - El PDF de 2025 mezcla "Contrato Mayor" y "Contrato Menor" (los mayores
#   traen procedimiento abierto/negociado): solo se quedan las filas cuyo tipo
#   de contratación/procedimiento dice "menor".
# - 2022 y 2025 NO traen fecha por contrato (2023 y 2024 sí, "fecha
#   formalización") -- para esos dos ejercicios se usa el 1 de enero del año
#   del fichero como fecha aproximada (mismo criterio que Lorca).
# - ~10% de las filas tienen varios contratistas ("NIF - Nombre | NIF -
#   Nombre") con un desglose por lotes cuyo orden NO coincide con el de los
#   contratistas: no se puede atribuir un importe a cada uno sin adivinar, así
#   que se guarda UN registro por contrato con los nombres unidos con " / " y
#   sin NIF (importe total correcto, sin repartir).
# - Importe = "con impuestos" (mismo criterio que Mula: IVA incluido).
# - Referencias de expediente con formatos irregulares ("20226433A",
#   "2022/6644", "2025/4175f") -- por eso una fila de datos se reconoce por
#   "empieza por 4 dígitos + tiene objeto", no por un regex estricto de
#   referencia.
SAN_PEDRO_INDICE_URL = "https://www.sanpedrodelpinatar.es/ayuntamiento/perfil-del-contratante/"
_RE_SAN_PEDRO_NIF = re.compile(r"^([A-Z0-9]{8,10})\s*-\s*(.+)$")


def _sp_limpia(celda):
    """Texto de una celda del PDF en una sola línea, deshaciendo los guiones
    de fin de línea ('Jimé-\\nnez' -> 'Jiménez')."""
    t = re.sub(r"(?<=[a-záéíóúñü])-\s*\n\s*(?=[a-záéíóúñü])", "", celda or "")
    return re.sub(r"\s+", " ", t).strip()


def _sp_columnas(fila):
    """Mapa {campo: índice} a partir de una fila de cabecera, o None si no lo es."""
    norm = [re.sub(r"[^a-z]", "", (c or "").lower()
                   .replace("á", "a").replace("é", "e").replace("í", "i")
                   .replace("ó", "o").replace("ú", "u")) for c in fila]
    if not any(n.startswith("numerodereferencia") for n in norm):
        return None
    cols = {}
    for i, n in enumerate(norm):
        if n.startswith("numerodereferencia"):
            cols["ref"] = i
        elif n.startswith("objetodelcontrato"):
            cols["objeto"] = i
        elif n.startswith("tipodecontratacion"):
            cols["tipo_contratacion"] = i
        elif n.startswith("tipodecontrato"):
            cols["tipo"] = i
        elif n.startswith("tipodeprocedimiento"):
            cols["procedimiento"] = i
        elif n.startswith("fechaformalizacion"):
            cols["fecha"] = i
        elif n.startswith("importetotalofertadosinimpuestos"):
            cols["sin_iva"] = i
        elif n.startswith("importetotalofertadoconimpuestos"):
            cols["con_iva"] = i
        elif n.startswith("contra") and n.endswith("stas"):
            cols["contratistas"] = i
    if not {"ref", "objeto", "contratistas", "con_iva"} <= set(cols):
        return None
    return cols


def _listar_pdfs_san_pedro():
    """{año: url} de los PDF de contratos menores del ayuntamiento (excluye
    el del Patronato Universidad Popular y la instrucción de tramitación),
    leyendo el índice real -- el año se saca del nombre del fichero."""
    r = requests.get(SAN_PEDRO_INDICE_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    resultado = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        nombre = href.rsplit("/", 1)[-1].lower()
        if not nombre.endswith(".pdf") or "menores" not in nombre:
            continue
        if any(x in nombre for x in ("patronato", "universidad", "instruccion")):
            continue
        m = re.search(r"(20\d{2})", nombre)
        if m:
            resultado[int(m.group(1))] = urljoin(SAN_PEDRO_INDICE_URL, href)
    return resultado


def _parsear_pdf_san_pedro(contenido, anio):
    registros = {}
    cols = None
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        for pagina in pdf.pages:
            for tabla in pagina.extract_tables():
                for fila in tabla:
                    nuevas = _sp_columnas(fila)
                    if nuevas:
                        cols = nuevas
                        continue
                    if not cols or len(fila) <= max(cols.values()):
                        continue
                    ref = _sp_limpia(fila[cols["ref"]])
                    objeto = _sp_limpia(fila[cols["objeto"]])
                    if not re.match(r"^\d{4}", ref) or not objeto:
                        continue
                    clase = (_sp_limpia(fila[cols["tipo_contratacion"]]) if "tipo_contratacion" in cols else "") + " " + \
                            (_sp_limpia(fila[cols["procedimiento"]]) if "procedimiento" in cols else "")
                    clase = clase.lower()
                    if "menor" not in clase or "mayor" in clase:
                        continue
                    # Contratistas: dedupe por NIF (algunas filas repiten el mismo
                    # contratista una vez por lote).
                    vistos, nombres, nifs = set(), [], []
                    for parte in (fila[cols["contratistas"]] or "").split("|"):
                        parte = _sp_limpia(parte)
                        if not parte:
                            continue
                        m = _RE_SAN_PEDRO_NIF.match(parte)
                        nif, nombre = (m.group(1), m.group(2).strip()) if m else ("", parte)
                        clave = nif or nombre.lower()
                        if clave in vistos:
                            continue
                        vistos.add(clave)
                        nombres.append(nombre)
                        nifs.append(nif)
                    if not nombres:
                        continue
                    importe = _num_es(fila[cols["con_iva"]])
                    if not importe and "sin_iva" in cols:
                        importe = _num_es(fila[cols["sin_iva"]])
                    fecha = f"{anio}-01-01"
                    if "fecha" in cols:
                        m = re.match(r"^(\d{2})-(\d{2})-(\d{4})$", _sp_limpia(fila[cols["fecha"]]))
                        if m:
                            fecha = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
                    adjudicatario = " / ".join(nombres)
                    nif_unico = nifs[0] if len(nifs) == 1 else ""
                    tipo = _sp_limpia(fila[cols["tipo"]]) if "tipo" in cols else ""
                    clave_hash = hashlib.md5(
                        f"{ref}|{adjudicatario}|{importe}|{objeto}".encode("utf-8")
                    ).hexdigest()[:12]
                    registros[f"SanPedroPinatar::{clave_hash}"] = {
                        "id":               f"SanPedroPinatar::{clave_hash}",
                        "municipio":        "San Pedro del Pinatar",
                        "provincia":        "murcia",
                        "fuente":           "san-pedro-pinatar",
                        "organisme":        "Ayuntamiento de San Pedro del Pinatar",
                        "adjudicatari":     adjudicatario,
                        "nif":              nif_unico,
                        "import_num":       importe,
                        "data_adjudicacio": fecha,
                        "tipus_contracte":  tipo,
                        "descripcio":       objeto,
                        "codi_cpv":         "",
                        "exercici":         str(anio),
                    }
    return registros


def actualizar_san_pedro():
    pdfs = {a: u for a, u in _listar_pdfs_san_pedro().items() if a >= DESDE_ANY}
    print(f"San Pedro del Pinatar: {len(pdfs)} PDF anuales de menores en el índice real: {sorted(pdfs)}")
    registros = {}
    for anio, url in sorted(pdfs.items()):
        try:
            r = requests.get(url, headers=HEADERS, timeout=120)
            r.raise_for_status()
            filas_anio = _parsear_pdf_san_pedro(r.content, anio)
        except Exception as e:
            print(f"  San Pedro del Pinatar {anio}: no se pudo procesar ({type(e).__name__}: {e})")
            continue
        registros.update(filas_anio)
        print(f"  San Pedro del Pinatar {anio}: {len(filas_anio)} contratos extraídos")
    registros = list(registros.values())
    print(f"San Pedro del Pinatar: {len(registros)} contratos menores extraídos en total")
    return registros


# Torre Pacheco (añadido 2026-09-24): su portal de transparencia
# (transparencia.torrepacheco.es/contratos/) es un iframe de la plataforma
# Governalia que consume una API JSON REST pública, sin captcha ni login --
# solo exige la cookie JSESSIONID que da la propia página del módulo y las
# cabeceras X-Requested-With/Content-Type de una llamada AJAX (sin ellas
# devuelve 412). Con procurementMinor=true devuelve los contratos menores
# (procedimiento "Contrato menor", siempre con adjudicatario y NIF). Verificado
# 2026-09-24: 1.218 filas 2021-2026 (2022: 1, 2023: 4, 2024: 299, 2025: 615,
# 2026 en curso: 299), ids únicos, mismo total pidiendo por años o de una vez,
# sin solapamiento con los contratos PLACE que ya tenemos de este municipio.
# ATENCIÓN a los campos: `estimated_overall_contract_amount*` es el
# PRESUPUESTO DE LICITACIÓN (a menudo distinto de lo adjudicado); el importe
# adjudicado real es `tax_exclusive_amount` (= `amount`) y va SIN IVA -- a
# diferencia de Mula/San Pedro del Pinatar, que publican con IVA. Solo si el
# adjudicado viene a 0/nulo (unas 4 filas) se cae al presupuesto sin IVA.
# La fecha es `award_date` (algún registro trae un rango "2025-11-27/2026-04-30":
# se toma el primer día).
TORRE_PACHECO_PAGINA_URL = ("https://governalia.torrepacheco.es/gvn/web/section/modules/"
                            "transparency/egob/procurements/?idP=36813&lang=es")
# Cartagena (añadido 2026-09-24): cartagena.governalia.es/contratos/ es la
# misma plataforma, en el host compartido app.governalia.es (el ayuntamiento
# se identifica por idP en la URL del módulo). Es un ESPEJO de lo que Cartagena
# publica en PLACE (el "Importe de Adjudicación" de PLACE coincide con el campo
# de la API, verificado en 6 contratos), con dos consecuencias importantes:
# - Arrastra los errores de origen de PLACE: 1 "contrato menor" de 6.000.000 €
#   (feria de degustación, casi seguro un error de tecleo del ayuntamiento) y
#   ~7 % de filas con adjudicado 0 (el ayuntamiento no rellenó el importe). Aquí
#   se guardan tal cual, SIN sustituir el 0 por el presupuesto.
# - NO es la misma población que el portal propio cartagena.es (fuente
#   "cartagena", solo ejercicio en curso): se solapan ~62 % de las filas de
#   2026 (mismo NIF, importe = sin IVA x 1,00-1,21) y el resto de cada lado no
#   está en el otro. Por eso esta fuente solo aporta los ejercicios ANTERIORES
#   a CARTAGENA_GOVERNALIA_HASTA -- 2022-2025, que el portal propio ya no
#   devuelve -- y 2026 lo sigue dando el portal propio, sin duplicar.
# Ojo con la base del importe: el portal propio de Cartagena va CON IVA
# (ratio 1,21 dominante) y Governalia SIN IVA.
CARTAGENA_GOVERNALIA_PAGINA_URL = ("https://app.governalia.es/gvn/web/section/modules/"
                                   "transparency/egob/procurements/?idP=47226&lang=es")
CARTAGENA_GOVERNALIA_HASTA = 2025


def _sin_acentos(t):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", t or "") if unicodedata.category(c) != "Mn")


def _governalia_menores(pagina_url, municipio, fuente, prefijo_id, hasta_anio=None,
                        presupuesto_si_cero=True, provincia="murcia"):
    """Contratos menores de un ayuntamiento cuyo portal de transparencia corre
    sobre Governalia (ver notas de Torre Pacheco y Cartagena arriba). La API
    cuelga del mismo origen que la página del módulo. `presupuesto_si_cero`:
    si el importe adjudicado viene a 0/nulo, usar el presupuesto sin IVA (Torre
    Pacheco, ~4 filas) o dejarlo a 0 tal como lo publica el ayuntamiento
    (Cartagena, ~7 % de las filas: no se inventa un importe).

    Dos guardas descubiertas al ampliar a la Comunitat Valenciana (2026-09-24):
    - MUNICIPIO: cada fila trae en `site` el municipio real ("...?L01462567/
      Vilamarxant"). tolosa.governalia.es (un "Ayuntamiento de Tolosa") incrusta
      por error el módulo de Vilamarxant y devolvía 786 contratos de OTRO
      municipio: se descartan las filas cuyo `site` no acabe en `municipio`,
      y si no queda ninguna se aborta en vez de guardar datos ajenos.
    - PROCEDIMIENTO: el filtro procurementMinor=true de la API a veces deja
      pasar filas con otro procedimiento (Vilamarxant: 2 "Abierto simplificado"):
      solo se guardan las de procedimiento "Contrato menor".
    Los importes de la API traen 6 cifras significativas (615665,3 llega como
    615665,0): error <= 0,05 EUR en contratos normales, visible solo en obras
    de cientos de miles de euros."""
    origen = "/".join(pagina_url.split("/")[:3])
    api = (origen + "/gvn/rest/transparency/egob/procurements/dt/all?formatDate=YYYY-MM-DD"
           "&iniDate={ini}&endDate={fin}&procurementStatus=&procurementActivity="
           "&procurementProcedure=&procurementProcedureCode=Por%20-Procedimiento-"
           "&procurementType=&procurementMinor=true&procurementAdministration=")
    s = requests.Session()
    s.headers["User-Agent"] = HEADERS["User-Agent"]
    s.get(pagina_url, timeout=60).raise_for_status()   # solo para la cookie de sesión
    fin = min(hasta_anio, time.localtime().tm_year) if hasta_anio else time.localtime().tm_year
    r = s.get(api.format(ini=DESDE_ANY, fin=fin),
              headers={"X-Requested-With": "XMLHttpRequest", "Content-Type": "application/json",
                       "Accept": "application/json, text/javascript, */*; q=0.01",
                       "Referer": pagina_url}, timeout=300)
    r.raise_for_status()
    filas = r.json().get("data", [])
    registros = {}
    for x in filas:
        adjudicatario = (x.get("winningparty_name") or "").strip()
        fecha = (x.get("award_date") or x.get("date_issue") or "")[:10]
        if not adjudicatario or not re.match(r"^\d{4}-\d{2}-\d{2}$", fecha) or int(fecha[:4]) < DESDE_ANY:
            continue
        if hasta_anio and int(fecha[:4]) > hasta_anio:
            continue
        if _sin_acentos((x.get("site") or "").split("/")[-1]).lower() != _sin_acentos(municipio).lower():
            continue
        if (x.get("procedure_type") or "").strip().lower() != "contrato menor":
            continue
        importe = x.get("tax_exclusive_amount") or 0.0
        if not importe and presupuesto_si_cero:
            importe = x.get("estimated_overall_contract_amount_without_taxes") or 0.0
        registros[f"{prefijo_id}::{x['id']}"] = {
            "id":               f"{prefijo_id}::{x['id']}",
            "municipio":        municipio,
            "provincia":        provincia,
            "fuente":           fuente,
            "organisme":        f"Ayuntamiento de {municipio}",
            "adjudicatari":     adjudicatario,
            "nif":              (x.get("winningparty_nif") or "").strip(),
            "import_num":       float(importe),
            "data_adjudicacio": fecha,
            "tipus_contracte":  x.get("contract_type") or "",
            "descripcio":       re.sub(r"\s+", " ", x.get("title") or "").strip(),
            "codi_cpv":         "",
            "exercici":         fecha[:4],
        }
    registros = list(registros.values())
    if filas and not registros:
        raise RuntimeError(f"Governalia {municipio}: {len(filas)} filas pero ninguna es de este municipio "
                           f"(site distinto): el módulo de {pagina_url} no es suyo.")
    por_anio = {}
    for x in registros:
        por_anio[x["exercici"]] = por_anio.get(x["exercici"], 0) + 1
    print(f"{municipio}: {len(registros)} contratos menores (de {len(filas)} filas de la API): {dict(sorted(por_anio.items()))}")
    return registros


def actualizar_torre_pacheco():
    return _governalia_menores(TORRE_PACHECO_PAGINA_URL, "Torre Pacheco", "torre-pacheco", "TorrePacheco")


_GOVERNALIA_APP = "https://app.governalia.es/gvn/web/section/modules/transparency/egob/procurements/?idP={}&lang=es"


def actualizar_ibi():
    return _governalia_menores(_GOVERNALIA_APP.format(72584), "Ibi", "ibi-governalia", "IbiGov", provincia="alicante")


def actualizar_sax():
    return _governalia_menores(_GOVERNALIA_APP.format(54165), "Sax", "sax-governalia", "SaxGov", provincia="alicante")


def actualizar_vilamarxant():
    return _governalia_menores(_GOVERNALIA_APP.format(63100), "Vilamarxant", "vilamarxant-governalia",
                               "VilamarxantGov", provincia="valencia")


def actualizar_cartagena_governalia():
    return _governalia_menores(CARTAGENA_GOVERNALIA_PAGINA_URL, "Cartagena", "cartagena-governalia",
                               "CartagenaGov", hasta_anio=CARTAGENA_GOVERNALIA_HASTA,
                               presupuesto_si_cero=False)


# Fuente -> (función, valor del campo "fuente" de sus registros). Sirve para
# relanzar UNA sola fuente (`python ... san-pedro-pinatar`) conservando las
# demás del JSON existente, en vez de esperar los ~25 min de Murcia capital.
_FUENTES = {
    "mula":              actualizar_mula,
    "molina-segura":     actualizar_molina_segura,
    "lorqui":            actualizar_lorqui,
    "lorca":             actualizar_lorca,
    "murcia-capital":    actualizar_murcia_capital,
    "san-pedro-pinatar": actualizar_san_pedro,
    "torre-pacheco":     actualizar_torre_pacheco,
    "cartagena-governalia": actualizar_cartagena_governalia,
    "ibi-governalia":    actualizar_ibi,
    "sax-governalia":    actualizar_sax,
    "vilamarxant-governalia": actualizar_vilamarxant,
}


def main():
    pedidas = sys.argv[1:]
    desconocidas = [f for f in pedidas if f not in _FUENTES]
    if desconocidas:
        sys.exit(f"Fuente(s) desconocida(s): {desconocidas}. Válidas: {sorted(_FUENTES)}")
    if not pedidas:
        todos = []
        for fn in _FUENTES.values():
            todos += fn()
    else:
        with open(OUT_FILE, encoding="utf-8") as f:
            previos = json.load(f)["registros"]
        todos = [r for r in previos if r.get("fuente") not in pedidas]
        for nombre in pedidas:
            todos += _FUENTES[nombre]()
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump({"generado": time.strftime("%Y-%m-%d %H:%M:%S"), "registros": todos},
                   f, ensure_ascii=False, indent=1)
    print(f"\nTotal: {len(todos)} contratos menores guardados en {OUT_FILE}")


if __name__ == "__main__":
    main()
