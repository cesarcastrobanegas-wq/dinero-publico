# encoding: utf-8
"""
Descarga contratos menores de fuentes municipales de Murcia cuyo formato
necesita librerías que NO están en requirements.txt de producción (odfpy para
ODS, openpyxl para XLSX, xlrd para XLS legado, pdfplumber para tablas en PDF)
-- mismo patrón manual/periódico que actualizar_alcaldes.py /
actualizar_retribuciones.py: se ejecuta a mano de vez en cuando (cada
trimestre/año, cuando el ayuntamiento publique un fichero nuevo) y genera
contratos_menores_murcia_manual.json.gz, que app.py carga al arrancar y vuelca a
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
import gzip
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.parse

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
OUT_FILE = f"{BASE_DIR}/contratos_menores_murcia_manual.json.gz"   # comprimido desde 2026-09-24 (52,8 MB -> ~7 MB)


def _leer_registros_previos():
    """Registros del fichero de salida (o del .json sin comprimir si es lo único que hay)."""
    for ruta in (OUT_FILE, OUT_FILE[:-3]):
        if os.path.exists(ruta):
            with (gzip.open(ruta, "rt", encoding="utf-8") if ruta.endswith(".gz")
                  else open(ruta, encoding="utf-8")) as f:
                return json.load(f)["registros"]
    return []


def _escribir_registros(registros):
    """Escritura determinista (mtime=0): dos ejecuciones con los mismos datos dan el mismo fichero."""
    contenido = json.dumps({"generado": time.strftime("%Y-%m-%d %H:%M:%S"), "registros": registros},
                           ensure_ascii=False, indent=1).encode("utf-8")
    with open(OUT_FILE, "wb") as crudo:
        with gzip.GzipFile(filename="", mode="wb", fileobj=crudo, compresslevel=9, mtime=0) as z:
            z.write(contenido)

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
# diferencia de Mula/San Pedro del Pinatar, que publican con IVA. Si el
# adjudicado viene a 0/nulo se deja a 0 (antes se usaba el presupuesto: 3 filas, corregido).
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
                        presupuesto_si_cero=False, provincia="murcia"):
    """Contratos menores de un ayuntamiento cuyo portal de transparencia corre
    sobre Governalia (ver notas de Torre Pacheco y Cartagena arriba). La API
    cuelga del mismo origen que la página del módulo. `presupuesto_si_cero`
    (por defecto False, criterio unificado 2026-09-24): si el importe adjudicado
    viene a 0/nulo se deja a 0 tal como lo publica el ayuntamiento, sin inventar
    un importe (Cartagena ~7 % de filas; 2-4 filas en los demás). Torre Pacheco e
    Ibi usaron antes el presupuesto como respaldo en 4 filas en total
    (3 y 1), lo que contradecía la nota "importe adjudicado" de la ficha.

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


# A Coruña (añadido 2026-09-24): un fichero por trimestre (y un "Anexo" anual) en
# coruna.gal/transparencia/.../contratos-menores, descargables con requests
# siempre que se envíe un Referer de la propia página (sin él, 403). El formato
# CAMBIA por época (verificado abriendo los 40 ficheros):
# - 2014-2017 (.xls): imputaciones de FACTURAS ("FRA. Nº 58/2016"), sin NIF,
#   4.600-5.500 filas: no son contratos -> fuera (además, anteriores a DESDE_ANY).
# - 2018-2019 (.xlsx/.ods): otro esquema ("Expediente. Código Entidad", "Imp. Adj.
#   c/imp.") -> fuera de alcance (< DESDE_ANY).
# - 2021-2026 (.ods): título, (nota), cabecera, UNA FILA DESCRIPTIVA extra, y datos
#   Referencia / Tipo (A,E,C,Z,O o "Obras/Servicios/Suministro") / Objeto / Fecha
#   adjudicación / NIF / Nombre adjudicatario / Precio adjudicación / Negociado.
#   Las cabeceras varían (castellano/gallego, "Fecha adj."/"Fecha adjud."/"Data adx.",
#   "*Tipo Contrato") y el importe llega a veces como número y a veces como texto
#   español ("48.338,05 €"): se localizan por nombre normalizado, no por posición.
# - Importe = precio de adjudicación CON IVA (lo dice la fila descriptiva; el
#   máximo es exactamente 48.400 EUR = 40.000 + 21 % de IVA, y ninguno lo supera).
# - NIF de personas físicas enmascarado ("***2693**", o "*"): se guarda vacío.
#   Nombres de persona en formato "APELLIDOS , NOMBRE" (se normaliza el espacio).
# - Los "Anexo_*_AAAA" contienen filas tardías que a veces se repiten en un
#   trimestral (5 duplicadas exactas en 2024): se colapsan por (referencia,
#   adjudicatario, importe, fecha). La referencia SOLA no es única (32 repetidas:
#   pagos periódicos bajo el mismo expediente).
# - 2 filas de ~13.000 no se pueden leer como importe ("9.399.28 EUR", una errata, y
#   "22.209,07 EUR (2023). 31.882,29 EUR (2024)", contrato plurianual) y se descartan.
CORUNA_LISTADO_URL = ("https://www.coruna.gal/transparencia/es/claridad-en-la-gestion/"
                      "contratacion/contratos-menores")
_CORUNA_TIPOS = {"a": "Obras", "obras": "Obras", "e": "Servicios", "servicios": "Servicios",
                 "c": "Suministros", "suministro": "Suministros", "suministros": "Suministros",
                 "z": "Otros", "o": "Otros"}


def _ac_norm(t):
    import unicodedata
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFD", str(t).lower()).encode("ascii", "ignore").decode())


def _ac_columnas(fila):
    m = {}
    for i, c in enumerate(fila):
        n = _ac_norm(c)
        if n == "referencia":
            m["ref"] = i
        elif n.startswith("tipo") and "tipo" not in m:
            m["tipo"] = i
        elif n in ("objeto", "obxecto"):
            m["objeto"] = i
        elif n.startswith("fechaadj") or n.startswith("dataadx"):
            m["fecha"] = i
        elif n == "nif":
            m["nif"] = i
        elif n.startswith("nombreadjudicatario") or n.startswith("nomeadxudicatari"):
            m["nombre"] = i
        elif n.startswith("precioadjudicacion") or n.startswith("prezoadxudicacion"):
            m["precio"] = i
    return m if {"ref", "fecha", "nif", "nombre", "precio"} <= set(m) else None


def _ac_num(v):
    """Número de la hoja, o texto: formato español ('48.338,05 EUR', '150,00') si trae
    coma; si no, decimal con punto ('4301.67'). None si no se puede leer."""
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).strip().replace("€", "").replace("EUR", "").strip()
    try:
        return float(t.replace(".", "").replace(",", ".")) if "," in t else float(t)
    except ValueError:
        return None


def _ac_fecha(v):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(v))
    if m:
        return m.group(0)
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", str(v))
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def _leer_ods_filas(contenido):
    """Filas (listas de valores) de la hoja más grande de un ODS. A diferencia del lector de
    Mula, respeta number-columns-repeated / number-rows-repeated y usa el valor tipado de
    la celda (fecha ISO / número) cuando existe."""
    from odf.namespaces import TABLENS, OFFICENS
    doc = odf_load(io.BytesIO(contenido))
    mejor = []
    for tb in doc.spreadsheet.getElementsByType(Table):
        filas = []
        for tr in tb.getElementsByType(TableRow):
            rep = int(tr.getAttrNS(TABLENS, "number-rows-repeated") or 1)
            vals = []
            for c in tr.childNodes:
                if c.qname[1] not in ("table-cell", "covered-table-cell"):
                    continue
                r = int(c.getAttrNS(TABLENS, "number-columns-repeated") or 1)
                texto = "".join(str(p) for p in c.getElementsByType(odf_P)).strip()
                dv = c.getAttrNS(OFFICENS, "date-value")
                vv = c.getAttrNS(OFFICENS, "value")
                val = dv if dv else (vv if vv is not None else texto)
                vals.extend([val if (r < 50 or val) else ""] * min(r, 50))
            if any(str(x).strip() for x in vals):
                filas.extend([vals] * min(rep, 1000))
        if len(filas) > len(mejor):
            mejor = filas
    return mejor


def actualizar_a_coruna():
    hdr = dict(HEADERS, Referer=CORUNA_LISTADO_URL)
    r = requests.get(CORUNA_LISTADO_URL + "?argIdioma=es", headers=hdr, timeout=60)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    ficheros = []
    for a in soup.find_all("a", href=True):
        nombre = a.get_text(" ", strip=True)
        m = re.match(r"^(20\d{2})\d{0,2}[_-].*\.ods$", nombre, re.I)
        if "descarga.jsp" in a["href"] and m and int(m.group(1)) >= DESDE_ANY:
            ficheros.append((nombre, urljoin(CORUNA_LISTADO_URL, a["href"])))
    print(f"A Coruña: {len(ficheros)} ficheros ODS de {DESDE_ANY} en adelante en el listado")
    registros, descartadas = {}, 0
    for nombre, url in ficheros:
        try:
            rr = requests.get(url, headers=hdr, timeout=120)
            rr.raise_for_status()
            filas = _leer_ods_filas(rr.content)
        except Exception as e:
            print(f"  A Coruña: {nombre} no se pudo procesar ({type(e).__name__})")
            continue
        c = None
        for fila in filas:
            if c is None:
                c = _ac_columnas(fila)
                continue

            def g(k):
                return fila[c[k]] if k in c and c[k] < len(fila) else ""
            ref = str(g("ref")).strip()
            adjudicatario = re.sub(r"\s+", " ", str(g("nombre"))).replace(" ,", ",").strip()
            if not ref or not adjudicatario or _ac_norm(ref).startswith("codigo"):
                continue
            fecha, importe = _ac_fecha(g("fecha")), _ac_num(g("precio"))
            if fecha is None or importe is None:
                descartadas += 1
                continue
            nif = str(g("nif")).strip()
            tipo = str(g("tipo")).strip()
            clave = hashlib.md5(f"{ref}|{adjudicatario}|{importe}|{fecha}".encode("utf-8")).hexdigest()[:12]
            if f"ACoruna::{clave}" in registros:
                continue
            registros[f"ACoruna::{clave}"] = {
                "id":               f"ACoruna::{clave}",
                "municipio":        "A Coruña",
                "provincia":        "a_coruna",
                "fuente":           "a-coruna",
                "organisme":        "Ayuntamiento de A Coruña",
                "adjudicatari":     adjudicatario,
                "nif":              "" if "*" in nif else nif,
                "import_num":       importe,
                "data_adjudicacio": fecha,
                "tipus_contracte":  _CORUNA_TIPOS.get(tipo.lower(), tipo),
                "descripcio":       re.sub(r"\s+", " ", str(g("objeto"))).strip(),
                "codi_cpv":         "",
                "exercici":         fecha[:4],
            }
        if c is None:
            print(f"  A Coruña: {nombre}: NO se encontró la cabecera, fichero saltado")
    registros = list(registros.values())
    por_anio = {}
    for x in registros:
        por_anio[x["exercici"]] = por_anio.get(x["exercici"], 0) + 1
    print(f"A Coruña: {len(registros)} contratos menores ({descartadas} filas con importe ilegible descartadas): "
          f"{dict(sorted(por_anio.items()))}")
    return registros


# Vigo (añadido 2026-09-24): un PDF por año, "informe generado de forma automática desde la
# aplicación de Xestión de Expedientes Municipais" (220-280 páginas, SIN tabla real). El
# índice de transparencia.vigo.org solo enlaza hasta 2022, pero los ficheros de 2023-2026
# existen con el mismo patrón de nombre (/docs/ContratosMenores_AA.pdf): se prueba el
# patrón año a año y se exige que la respuesta sea de verdad un PDF.
# Estructura verificada (validada contra proveedores de negocio inequívoco: con la hipótesis
# "el nombre precede a sus contratos" la descripción es coherente en el 92-100 % de los casos
# claros -prensa, ópticas, seguros-; con la contraria, solo en el 13 %):
#     NOMBRE DEL ADJUDICATARIO            <- cabecera de grupo, vale hasta el siguiente nombre
#     descripción (1 o más líneas)
#     Data Importe Expediente
#     dd/mm/aa  1.234,56 €  10933/307
#     [otra descripción + cabecera + datos del mismo adjudicatario...]
# - El nombre se distingue de la descripción por no llevar minúsculas: por eso 2021 y anteriores
#   quedan FUERA (sus descripciones van en mayúsculas y se confundirían con nombres: 1.281
#   proveedores distintos frente a ~750 en el resto de años).
# - Importe CON IVA (3.025,00 = 2.500 x 1,21); ninguno supera 48.400 EUR (= 40.000 + 21 %).
# - Sin NIF (el informe no lo publica). Desde 2024 los nombres de persona vienen con "*" en
#   lugar de espacio entre apellidos ("GARCIA*DIAZ,ESTHER"): se normaliza a "GARCIA DIAZ, ESTHER".
# - Un mismo registro puede repetirse entre ficheros de años contiguos (fechas del año anterior
#   registradas tarde): se colapsa por hash de expediente+nombre+importe+fecha+descripción.
# - Tipo de contrato: no hay columna; solo se rellena si la descripción lo dice
#   explícitamente ("Contrato menor de obras/servizos/suministros").
VIGO_PDF_URL = "https://transparencia.vigo.org/docs/ContratosMenores_{aa}.pdf"
VIGO_DESDE = 2022
_RE_VIGO_DATO = re.compile(r"^(\d{2})/(\d{2})/(\d{2})\s+([\d.]+,\d{2})\s*€\s+(\S+)$")
_RE_VIGO_RUIDO = re.compile(r"^(CONTRATOS MENORES|\(\*\) Este informe|Expedientes Municipais)|P[aá]xina \d+ de \d+$")


def _vigo_es_nombre(linea):
    return (bool(linea) and not re.search(r"[a-záéíóúñü]", linea)
            and not linea.startswith("Data Importe") and not re.match(r"^\d", linea))


def _vigo_parsear(contenido):
    lineas = []
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        for pagina in pdf.pages:
            for linea in (pagina.extract_text() or "").split("\n"):
                linea = linea.strip()
                if linea and not _RE_VIGO_RUIDO.search(linea):
                    lineas.append(linea)
    salida, nombre, desc, k = [], None, [], 0
    while k < len(lineas):
        linea = lineas[k]
        if linea.startswith("Data Importe"):
            k += 1
            continue
        m = _RE_VIGO_DATO.match(linea)
        if m:
            d, mm, aa, imp, exp = m.groups()
            salida.append((nombre, " ".join(desc).strip(), f"20{aa}-{mm}-{d}",
                           float(imp.replace(".", "").replace(",", ".")), exp))
            desc = []
            k += 1
            continue
        if _vigo_es_nombre(linea) and not desc:
            nombre = linea
            k += 1
            while k < len(lineas) and _vigo_es_nombre(lineas[k]):    # nombre largo en varias líneas
                nombre += " " + lineas[k]
                k += 1
            continue
        desc.append(linea)
        k += 1
    return salida


def actualizar_vigo():
    registros = {}
    for anio in range(VIGO_DESDE, time.localtime().tm_year + 1):
        url = VIGO_PDF_URL.format(aa=str(anio)[2:])
        try:
            r = requests.get(url, headers=HEADERS, timeout=180)
            r.raise_for_status()
            if r.content[:4] != b"%PDF":
                print(f"  Vigo {anio}: {url} no es un PDF, saltado")
                continue
            filas = _vigo_parsear(r.content)
        except Exception as e:
            print(f"  Vigo {anio}: no se pudo procesar ({type(e).__name__}: {e})")
            continue
        n0 = len(registros)
        for nombre, desc, fecha, importe, exp in filas:
            if not nombre or int(fecha[:4]) < DESDE_ANY:
                continue
            nombre = re.sub(r"\s+", " ", nombre.replace("*", " ")).strip()
            nombre = re.sub(r",\s*", ", ", nombre)
            desc = re.sub(r"\s*NUM\.LICITADORES:\s*\d+\.?", "", desc)
            desc = re.sub(r"\s*FIN CONTRATO:\s*[\d/]+\.?", "", desc)
            desc = re.sub(r"\s+", " ", desc).strip(" .")
            desc = desc[:1].upper() + desc[1:]
            tipo = ""
            mt = re.search(r"contrato menor (?:privado )?(?:de |para )?(obras?|servi[zc]os?|sub?ministros?)", desc, re.I)
            if mt:
                t = mt.group(1).lower()
                tipo = "Obras" if t.startswith("obra") else ("Servicios" if t.startswith("serv") else "Suministros")
            clave = hashlib.md5(f"{exp}|{nombre}|{importe}|{fecha}|{desc[:80]}".encode("utf-8")).hexdigest()[:12]
            registros[f"Vigo::{clave}"] = {
                "id":               f"Vigo::{clave}",
                "municipio":        "Vigo",
                "provincia":        "pontevedra",
                "fuente":           "vigo",
                "organisme":        "Ayuntamiento de Vigo",
                "adjudicatari":     nombre,
                "nif":              "",
                "import_num":       importe,
                "data_adjudicacio": fecha,
                "tipus_contracte":  tipo,
                "descripcio":       desc,
                "codi_cpv":         "",
                "exercici":         fecha[:4],
            }
        print(f"  Vigo {anio}: {len(registros) - n0} contratos nuevos ({len(filas)} bloques en el PDF)")
    registros = list(registros.values())
    print(f"Vigo: {len(registros)} contratos menores extraídos en total (desde {VIGO_DESDE})")
    return registros


# Ferrol (añadido 2026-09-24): www.ferrol.gal/Transparencia/ContratosMenores es una tabla HTML
# ESTÁTICA con TODOS los registros (2.762 de 2015-2026, ~1,8 MB) -- la paginación de 25 en 25 es
# de la propia librería de tablas en el navegador, no del servidor: con un único GET con requests
# llegan todas las filas. Columnas: Data adxudicación / Asunto / Adxudicatario / Tipo de expediente /
# Importe total / "Ampliar" (enlace al detalle del expediente).
# Verificado 2026-09-24 contra el detalle de un expediente reciente: "Importe licitación 12050 ->
# Importe total 14580,5 EUR" = x 1,21, o sea el importe es CON IVA; desde 2021 el máximo es
# 48.387,90 EUR (<= 48.400 = 40.000 + 21 %). Los importes por encima de 48.400 son todos de
# 2015-2017 (otros límites legales; fuera de alcance de todos modos por DESDE_ANY).
# - La lista NO trae NIF (el detalle sí, en la tabla de "Ofertas"): con nombre solo, igual que Vigo.
#   Rastrear los 1.575 detalles (~26 min) para sacar el NIF queda como mejora opcional.
# - "Tipo de expediente" es "Contrato menor" + el ÁREA municipal (Cultura, Festas, Emprego...), no el
#   tipo de contrato: solo cuando dice "obras" se rellena el tipo ("Obras"); el resto queda vacío.
# - El identificador del detalle NO es único por fila (68 de 1.575 desde 2021 lo comparten con otra),
#   así que la clave combina identificador, fecha, adjudicatario, importe y asunto: 25 de ellas son
#   duplicados EXACTOS (mismo identificador y mismos campos) y se colapsan (quedan 1.550 contratos);
#   las otras 43 difieren en algún campo (lotes / varios adjudicatarios del mismo expediente) y se
#   conservan.
# - Importes: formato "14180,65 EUR" o "18029 EUR" (coma decimal, sin separador de miles);
#   6 filas desde 2021 vienen a 0 (se dejan a 0) y 7 sin asunto.
FERROL_URL = "https://www.ferrol.gal/Transparencia/ContratosMenores"


def _ferrol_importe(v):
    t = str(v).replace("€", "").replace("EUR", "").strip()
    try:
        return float(t.replace(".", "").replace(",", ".")) if "," in t and "." in t else float(t.replace(",", "."))
    except ValueError:
        return None


def actualizar_ferrol():
    r = requests.get(FERROL_URL, headers=dict(HEADERS, **{"Accept-Language": "gl,es;q=0.9"}), timeout=120)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    registros, sin_importe = {}, 0
    n_filas = 0
    for tr in soup.select("table tbody tr"):
        td = [re.sub(r"\s+", " ", c.get_text(" ", strip=True)) for c in tr.find_all("td")]
        enlace = tr.find("a", href=True)
        if len(td) < 5:
            continue
        n_filas += 1
        m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", td[0])
        importe = _ferrol_importe(td[4])
        if not m or int(m.group(3)) < DESDE_ANY or not td[2]:
            continue
        if importe is None:
            sin_importe += 1
            continue
        fecha = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        ref = enlace["href"].rsplit("/", 1)[-1] if enlace else ""
        tipo = "Obras" if re.search(r"\bobras\b", td[3], re.I) else ""
        clave = hashlib.md5(f"{ref}|{fecha}|{td[2]}|{importe}|{td[1][:80]}".encode("utf-8")).hexdigest()[:12]
        registros[f"Ferrol::{clave}"] = {
            "id":               f"Ferrol::{clave}",
            "municipio":        "Ferrol",
            "provincia":        "a_coruna",
            "fuente":           "ferrol",
            "organisme":        "Ayuntamiento de Ferrol",
            "adjudicatari":     td[2],
            "nif":              "",
            "import_num":       importe,
            "data_adjudicacio": fecha,
            "tipus_contracte":  tipo,
            "descripcio":       td[1],
            "codi_cpv":         "",
            "exercici":         fecha[:4],
        }
    if n_filas == 0:
        raise RuntimeError("Ferrol: la tabla no trae filas (¿cambió la página?)")
    registros = list(registros.values())
    por_anio = {}
    for x in registros:
        por_anio[x["exercici"]] = por_anio.get(x["exercici"], 0) + 1
    print(f"Ferrol: {len(registros)} contratos menores de {n_filas} filas de la tabla "
          f"({sin_importe} con importe ilegible descartadas): {dict(sorted(por_anio.items()))}")
    return registros


# Pontevedra (añadido 2026-09-24): la sede (sede.pontevedra.gal) tiene una "Consulta de contratos"
# JSF/PrimeFaces con filtro de tipo de procedimiento y una tabla paginada por AJAX (20 filas/página,
# ~470 páginas de "Contrato menor"). Se puede reproducir SIN navegador: GET de la página (cookie de
# sesión + ViewState) -> POST de búsqueda con tipoprocedementoSelect=6 ("Contrato menor") -> POST de
# paginación con contratosTable_first=0 y contratosTable_rows=20000, que devuelve las ~9.400 filas de una
# vez (~10 MB, ~5 s). El código y el tamaño de página son los que envía la propia página.
# Verificado 2026-09-24:
# - Idéntico al recorrido página a página con navegador (9.411 filas), y las estadísticas del propio portal
#   (contratos-estatisticas.xhtml, "Importe adxudicación (con IVE)" del tipo "Contrato menor") coinciden AL
#   CÉNTIMO con las sumas por trimestre de estos datos (2024-T4, 2025-T1, 2025-T2, 2026-T2 y 2026-T3).
# - Importe = adjudicación CON IVA; el máximo es 48.398,79 (<= 48.400 = 40.000 + 21 %), el adjudicado nunca
#   supera al presupuesto y no hay duplicados. Los datos empiezan en el 2T-2023 (aunque el filtro ofrece 2022).
# - La celda del adjudicatario es "NOMBRE NIF Pyme": el NIF va al final (a veces extranjero: PT..., ESA...) y
#   "Pyme" es una marca. Solo se guarda como NIF el que tiene formato español; el resto se deja vacío.
#   10 filas (67.631,55 EUR, 0,17 %) traen solo "Pyme" (sin adjudicatario) y se descartan: por eso los
#   totales de este conector son esas 10 filas menores que los de las estadísticas del portal.
# - El título del procedimiento lleva pegado el código de expediente ("... 2022/DOCCMV5/000518"): se separa.
PONTEVEDRA_URL = "https://sede.pontevedra.gal/public/contratos/contratos-index.xhtml"
_RE_PONT_EXP = re.compile(r"\s+(\d{4}/[A-Z0-9]+/\d+)$")
_RE_PONT_NIF_ES = re.compile(r"^([A-Z]\d{7}[A-Z0-9]|\d{8}[A-Z]|[XYZ]\d{7}[A-Z])$")


def _pont_campos(html):
    """Campos del formulario contratosForm tal como los enviaría el navegador."""
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form", id="contratosForm")
    datos = {}
    for el in form.find_all(["input", "select"]):
        nombre = el.get("name")
        if not nombre:
            continue
        if el.name == "select":
            op = el.find("option", selected=True)
            datos[nombre] = op["value"] if op else ""
        elif el.get("type") in ("checkbox", "radio") and not el.has_attr("checked"):
            continue
        else:
            datos[nombre] = el.get("value", "")
    vs = soup.find("input", {"name": "javax.faces.ViewState"})
    datos["javax.faces.ViewState"] = vs["value"] if vs else ""
    return datos


def actualizar_pontevedra():
    s = requests.Session()
    s.headers.update({"User-Agent": HEADERS["User-Agent"], "Accept-Language": "gl,es;q=0.9"})
    cab = {"Faces-Request": "partial/ajax", "X-Requested-With": "XMLHttpRequest",
           "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "Referer": PONTEVEDRA_URL}
    r = s.get(PONTEVEDRA_URL, timeout=60)
    r.raise_for_status()
    datos = _pont_campos(r.text)
    datos["contratosForm:tipoprocedementoSelect_input"] = "6"      # 6 = "Contrato menor"
    busqueda = dict(datos, **{"javax.faces.partial.ajax": "true", "javax.faces.source": "contratosForm:search",
                              "javax.faces.partial.execute": "@all", "javax.faces.partial.render": "contratosForm",
                              "contratosForm:search": "contratosForm:search"})
    r1 = s.post(PONTEVEDRA_URL, data=busqueda, headers=cab, timeout=120)
    r1.raise_for_status()
    vs = re.search(r'<update id="[^"]*ViewState[^"]*"><!\[CDATA\[([^\]]+)\]\]>', r1.text)
    if vs:
        datos["javax.faces.ViewState"] = vs.group(1)
    paginacion = dict(datos, **{
        "javax.faces.partial.ajax": "true", "javax.faces.source": "contratosForm:contratosTable",
        "javax.faces.partial.execute": "contratosForm:contratosTable",
        "javax.faces.partial.render": "contratosForm:contratosTable",
        "javax.faces.behavior.event": "page", "javax.faces.partial.event": "page",
        "contratosForm:contratosTable_pagination": "true", "contratosForm:contratosTable_first": "0",
        "contratosForm:contratosTable_rows": "20000", "contratosForm:contratosTable_encodeFeature": "true"})
    r2 = s.post(PONTEVEDRA_URL, data=paginacion, headers=cab, timeout=300)
    r2.raise_for_status()
    m = re.search(r'<update id="contratosForm:contratosTable"><!\[CDATA\[(.*?)\]\]></update>', r2.text, re.S)
    if not m:
        raise RuntimeError("Pontevedra: la respuesta AJAX no trae la tabla (¿cambió el formulario?)")
    filas = [[re.sub(r"\s+", " ", c.get_text(" ", strip=True)) for c in tr.find_all("td")]
             for tr in BeautifulSoup(m.group(1), "html.parser").select("tr[data-ri]")]
    if not filas:
        raise RuntimeError("Pontevedra: la tabla no trae filas")
    registros, sin_adjudicatario = {}, 0
    for td in filas:
        if len(td) != 9 or td[5].lower() != "contrato menor":
            continue
        titulo, celda, fecha_txt, importe_txt = td[0], td[1], td[2], td[4]
        mf = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", fecha_txt)
        try:
            importe = float(importe_txt.replace("€", "").strip().replace(".", "").replace(",", "."))
        except ValueError:
            continue
        if not mf or int(mf.group(3)) < DESDE_ANY:
            continue
        celda = re.sub(r"\s*Pyme$", "", celda).strip()
        mn = re.match(r"^(.*?)\s*\b([A-Z0-9]{8,12})$", celda)
        if mn and sum(ch.isdigit() for ch in mn.group(2)) >= 6:
            nombre, nif = mn.group(1).strip(), mn.group(2)
        else:
            nombre, nif = celda, ""
        if not nombre or nombre.lower() == "pyme":
            sin_adjudicatario += 1
            continue
        me = _RE_PONT_EXP.search(titulo)
        exp = me.group(1) if me else ""
        desc = _RE_PONT_EXP.sub("", titulo).strip()
        fecha = f"{mf.group(3)}-{mf.group(2)}-{mf.group(1)}"
        clave = hashlib.md5(f"{exp}|{nombre}|{importe}|{fecha}|{desc[:80]}".encode("utf-8")).hexdigest()[:12]
        registros[f"Pontevedra::{clave}"] = {
            "id":               f"Pontevedra::{clave}",
            "municipio":        "Pontevedra",
            "provincia":        "pontevedra",
            "fuente":           "pontevedra",
            "organisme":        "Ayuntamiento de Pontevedra",
            "adjudicatari":     nombre,
            "nif":              nif if _RE_PONT_NIF_ES.match(nif) else "",
            "import_num":       importe,
            "data_adjudicacio": fecha,
            "tipus_contracte":  td[6],
            "descripcio":       desc,
            "codi_cpv":         "",
            "exercici":         fecha[:4],
        }
    registros = list(registros.values())
    por_anio = {}
    for x in registros:
        por_anio[x["exercici"]] = por_anio.get(x["exercici"], 0) + 1
    print(f"Pontevedra: {len(registros)} contratos menores de {len(filas)} filas ({sin_adjudicatario} sin "
          f"adjudicatario descartadas): {dict(sorted(por_anio.items()))}")
    return registros


# Ames (añadido 2026-09-24): un ZIP por año en concellodeames.gal/es/transparencia/contratos ("Contratos
# menores formalizados en AAAA") con dos PDF semestrales cada uno (~20 páginas). Descarga directa con
# requests. Tabla de 7 columnas (Nº / EXPEDIENTE / TIPO / OBXECTO / DECRETO APROBACIÓN / IMPORTE /
# ADXUDICATARIO), igual en 2021-2025, ~700-770 contratos al año.
# Verificado abriendo los 10 PDF de 2021-2025:
# - pdfplumber.extract_tables() da 7 columnas en el ~93 % de las filas; el resto sale con 8-9 columnas
#   (celdas vacías extra) y hay líneas sueltas de 1 columna (duplicados de texto ya contenido en la fila).
#   Por eso cada fila se interpreta por ANCLAS de contenido (nº, expediente, importe, nombre a continuación)
#   y no por posición.
# - Los saltos de numeración (277, 144, 314, 266, 244...) NO son filas perdidas: tampoco están en el texto
#   del PDF (la fuente los salta); y un nº repetido (134 en 2024-S2) son dos contratos distintos.
# - El importe se escribe de muchas formas: "17.278,80 €", "449.09 €", "4.480 euros", "1569,20", "85,00 €,",
#   "4.829.99". num_es() las cubre. Un decreto sin la barra ("21612024" en vez de "2161/2024") se leía como un
#   importe de 21,6 M EUR: el importe es la celda numérica más a la derecha CON símbolo/separadores.
# - Importe CON IVA (17.278,80 = 14.280 x 1,21); el máximo es 48.350,23 (<= 48.400) y ninguno lo supera.
# - La fuente NO trae fecha por contrato (solo el nº de decreto) ni NIF: se usa el inicio del semestre como
#   fecha aproximada (1 de enero / 1 de julio) -- limitación real de la fuente, avisada en la ficha.
# - Descartadas: 3 filas de importe ilegible (importe = expediente, celda vacía, "6,315,96 EUR") y 9 sin
#   adjudicatario (21.854,30 EUR en total).
# - Expedientes de 2021-S2 sin año ("8021"): por eso el expediente solo se exige no vacío.
AMES_LISTADO_URL = "https://www.concellodeames.gal/es/transparencia/contratos"
_RE_AMES_NUM = re.compile(r"^[\d.,\s]+(?:€|euros?)?[,.]?$", re.I)


def _am_tipo(t):
    """El tipo viene con erratas de la fuente ('Servzo', 'Subminitro', 'Servizos.', 'Obra'): se normaliza por
    prefijo; los mixtos ('Servizo e subministro') y las subvenciones se dejan tal cual."""
    x = t.lower().strip(" .")
    if " e " in x or "subvenc" in x:
        return t.strip(" .").capitalize()
    if x.startswith("privad") or x.startswith("contrato privado"):
        return "Privado"
    if x.startswith("obra"):
        return "Obras"
    if x.startswith("serv"):
        return "Servicios"
    if x.startswith("sub"):
        return "Suministros"
    return t.strip(" .").capitalize()


def _am_txt(c):
    return re.sub(r"\s+", " ", (c or "")).strip()


def _am_num(txt):
    t = re.sub(r"(?i)euros?|€", "", txt).replace(" ", "").rstrip(",.")
    if not t or not re.search(r"\d", t):
        return None
    try:
        if "," in t:
            return float(t.replace(".", "").replace(",", "."))
        if re.match(r"^\d{1,3}(\.\d{3})+$", t):
            return float(t.replace(".", ""))
        if re.match(r"^\d{1,3}(\.\d{3})+\.\d{2}$", t):
            return float(t.replace(".", "", t.count(".") - 1))
        return float(t)
    except ValueError:
        return None


def _am_parsear_pdf(contenido):
    filas, descartadas = [], 0
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        for pagina in pdf.pages:
            for tabla in pagina.extract_tables():
                for r in tabla:
                    if not r:
                        continue
                    c = [_am_txt(x) for x in r]
                    if len(c) < 6 or not re.match(r"^\d+$", c[0]):
                        continue
                    if not c[1]:
                        continue                                      # fila espuria (solo el número)
                    cand = [i for i in range(3, len(c)) if c[i] and "/" not in c[i]
                            and _RE_AMES_NUM.match(c[i]) and _am_num(c[i]) is not None]
                    fuertes = [i for i in cand if re.search(r"€|euro|[,.]", c[i], re.I)]
                    ii = (fuertes or cand or [None])[-1]
                    if ii is None:
                        descartadas += 1
                        continue
                    decreto = c[ii - 1] if ii - 1 >= 3 and re.match(r"^\d+/\d{4}$", c[ii - 1]) else ""
                    fin = ii - 1 if decreto else ii
                    filas.append({"n": int(c[0]), "exp": c[1], "tipo": c[2],
                                  "objeto": " ".join(x for x in c[3:fin] if x),
                                  "importe": _am_num(c[ii]), "adj": " ".join(x for x in c[ii + 1:] if x)})
    return filas, descartadas


def actualizar_ames():
    import zipfile
    r = requests.get(AMES_LISTADO_URL, headers=HEADERS, timeout=60)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    zips = {}
    for a in soup.find_all("a", href=True):
        m = re.search(r"Contratos menores formalizados en (\d{4})", a.get_text(" ", strip=True))
        if m and a["href"].lower().endswith(".zip") and int(m.group(1)) >= DESDE_ANY:
            zips[int(m.group(1))] = urljoin(AMES_LISTADO_URL, a["href"])
    print(f"Ames: {len(zips)} ZIP anuales desde {DESDE_ANY} en el listado oficial: {sorted(zips)}")
    registros, sin_adj, desc_imp = {}, 0, 0
    for anio, url in sorted(zips.items()):
        try:
            z = zipfile.ZipFile(io.BytesIO(requests.get(url, headers=HEADERS, timeout=120).content))
        except Exception as e:
            # estricto: un ZIP que falla dejaria medio año fuera sin que se note (ver _fusionar_fuente)
            raise RuntimeError(f"Ames {anio}: {url} no disponible ({type(e).__name__}: {e})")
        for nombre in sorted(n for n in z.namelist() if n.lower().endswith(".pdf")):
            sem = 1 if "primeiro" in nombre.lower() else (2 if "segundo" in nombre.lower() else None)
            if sem is None:
                print(f"  Ames {anio}: {nombre} no es un PDF semestral reconocible, saltado")
                continue
            try:
                filas, desc = _am_parsear_pdf(z.read(nombre))
            except Exception as e:
                raise RuntimeError(f"Ames {anio} S{sem}: no se pudo procesar ({type(e).__name__}: {e})")
            desc_imp += desc
            fecha = f"{anio}-01-01" if sem == 1 else f"{anio}-07-01"
            n0 = len(registros)
            for f in filas:
                if not f["adj"]:
                    sin_adj += 1
                    continue
                clave = hashlib.md5(f"{anio}|{sem}|{f['n']}|{f['exp']}|{f['adj']}|{f['importe']}".encode("utf-8")).hexdigest()[:12]
                registros[f"Ames::{clave}"] = {
                    "id":               f"Ames::{clave}",
                    "municipio":        "Ames",
                    "provincia":        "a_coruna",
                    "fuente":           "ames",
                    "organisme":        "Ayuntamiento de Ames",
                    "adjudicatari":     f["adj"],
                    "nif":              "",
                    "import_num":       f["importe"],
                    "data_adjudicacio": fecha,
                    "tipus_contracte":  _am_tipo(f["tipo"]),
                    "descripcio":       f["objeto"],
                    "codi_cpv":         "",
                    "exercici":         str(anio),
                }
            print(f"  Ames {anio} S{sem}: {len(registros) - n0} contratos")
    registros = list(registros.values())
    print(f"Ames: {len(registros)} contratos menores ({sin_adj} sin adjudicatario y {desc_imp} con importe "
          f"ilegible descartados)")
    return registros


# Santiago de Compostela (añadido 2026-09-24): santiagodecompostela.gal/gl/transparencia/contratacion/
# relacion-de-contratos-menores enlaza una página por año (2014-2026, "actualización mensual") con los XLS
# trimestrales. Los órganos de contratación de Santiago en PLACE ("Xunta de Goberno do Concello de Santiago de
# Compostela") NO publican menores (procedimientos 1/3/8/9) y no existe ningún órgano "(CONTRATOS MENORES)" en
# PLACE -- ese dato venía de un agregador: la fuente real es esta.
# Verificado abriendo los 22 ficheros de 2021 a 2T-2026:
# - 2021 -> 1T-2026: informe "DETALLE POR ADJUDICATARIOS" del sistema contable, hoja "Contratos", cabecera
#   DOCUMENTO(NIF) / ADJUDICATARIO / TIPO / [NÚMERO] / F.ENTRADA / DESCRIPCIÓN / IMPORTE, con filas de subtotal
#   "Total Servicios/Suministros/Obras" intercaladas (se saltan). La fecha es un número de serie de Excel y es la
#   FECHA DE ENTRADA del documento, no la de adjudicación.
# - 2T-2026 en adelante: tabla plana del "Registro Central de Contratos" (Núm. expediente / Tipo / Objeto /
#   Adj. Nombre / Fecha adjudicación / Importe adj (con impuestos)) y SIN NIF.
# - Importe CON IVA (14.399 = 11.900 x 1,21; 2.541 = 2.100 x 1,21).
# - El listado agrupado mezcla contratos menores con OTROS documentos contables: los 30 importes por encima de
#   48.400 EUR (= 40.000 + 21 %) son convenios con el Consorcio (hasta 3,5 M EUR), "entregas a cuenta" a la UTE de
#   autobuses, liquidaciones o "documentos pre-AD" -- no son contratos menores y se EXCLUYEN (el máximo legal
#   descarta cualquier duda). Por debajo de ese tope no hay forma fiable de distinguirlos (el prefijo "CM-" solo
#   existe en parte de las filas), así que se conservan.
# - El 1T-2026 solo cubre del 1 al 8 de enero y el 2T-2026 empieza el 1 de abril: la fuente no publica el resto
#   del 1T-2026.
# - Los ficheros trimestrales se solapan (2022-T4 desde el 1-sep, 2023-T4 desde el 1-sep, 2023-T3 hasta el 2-oct):
#   se deduplica por (NIF, adjudicatario, fecha, importe, descripción).
# - NIF de personas físicas enmascarado ("***8151**"): se guarda vacío.
SANTIAGO_INDICE_URL = "https://santiagodecompostela.gal/gl/transparencia/contratacion/relacion-de-contratos-menores"
_RE_SC_NIF_ES = re.compile(r"^([A-Z]\d{7}[A-Z0-9]|\d{8}[A-Z]|[XYZ]\d{7}[A-Z])$")
_SC_TIPOS = {"servicios": "Servicios", "servicio": "Servicios", "suministros": "Suministros",
             "suministro": "Suministros", "obras": "Obras", "obra": "Obras"}


def _sc_txt(c):
    return re.sub(r"\s+", " ", str(c or "")).strip()


def _sc_fecha(v, datemode):
    try:
        f = float(v)
        if f < 30000:
            return None
        return xlrd.xldate_as_datetime(f, datemode).date().isoformat()
    except (TypeError, ValueError):
        return None


def _sc_parsear_xls(contenido):
    """Filas (dict) de un XLS de Santiago, en cualquiera de sus dos formatos. (filas, n_sobre_tope)."""
    wb = xlrd.open_workbook(file_contents=contenido)
    filas, sobre_tope = [], 0
    for hoja in wb.sheets():
        cab = None
        for i in range(min(15, hoja.nrows)):
            f = [_sc_txt(c).lower() for c in hoja.row_values(i)]
            if "adjudicatario" in f and "importe" in f:
                cab = ("agrupado", i, f)
                break
            if any(x.startswith("núm. expediente") or x.startswith("num. expediente") for x in f) \
                    and any(x.startswith("importe adj") for x in f):
                cab = ("plano", i, f)
                break
        if not cab:
            continue
        formato, i0, f = cab

        def ix(pref):
            return next((k for k, x in enumerate(f) if x.startswith(pref)), None)
        if formato == "agrupado":
            c = {"doc": ix("documento"), "adj": ix("adjudicatario"), "tipo": ix("tipo"),
                 "fecha": ix("f.entrada"), "desc": ix("descrip"), "imp": ix("importe")}
        else:
            c = {"doc": None, "adj": ix("adj. nombre"), "tipo": ix("tipo"), "fecha": ix("fecha adj"),
                 "desc": ix("objeto"), "imp": ix("importe adj")}
        for r in range(i0 + 1, hoja.nrows):
            v = hoja.row_values(r)

            def g(k):
                return v[c[k]] if c.get(k) is not None and c[k] < len(v) else ""
            tipo = _sc_txt(g("tipo"))
            adj = _sc_txt(g("adj"))
            if not adj or (formato == "agrupado" and tipo.lower().startswith("total")):
                continue
            fecha = _sc_fecha(g("fecha"), wb.datemode)
            try:
                importe = float(g("imp"))
            except (TypeError, ValueError):
                continue
            if not fecha:
                continue
            if importe > 48400:
                sobre_tope += 1
                continue
            filas.append({"nif": _sc_txt(g("doc")) if c["doc"] is not None else "", "adj": adj, "tipo": tipo,
                          "fecha": fecha, "desc": _sc_txt(g("desc")), "importe": importe})
    return filas, sobre_tope


def actualizar_santiago():
    r = requests.get(SANTIAGO_INDICE_URL, headers=HEADERS, timeout=60)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    paginas = {}
    for a in soup.find_all("a", href=True):
        m = re.search(r"relacion-de-contratos-menores-ano-(\d{4})", a["href"])
        if m and int(m.group(1)) >= DESDE_ANY:
            paginas[int(m.group(1))] = urljoin(SANTIAGO_INDICE_URL, a["href"])
    if not paginas:
        raise RuntimeError("Santiago: no se encontraron las páginas anuales (¿cambió el índice?)")
    print(f"Santiago: {len(paginas)} páginas anuales desde {DESDE_ANY}: {sorted(paginas)}")
    registros, sobre_tope_total, n_ficheros = {}, 0, 0
    for anio, url in sorted(paginas.items()):
        # La web a veces sirve la página del año SIN los enlaces (visto 2026-09-24: 2024 falló en dos ejecuciones y
        # funcionó en la siguiente petición idéntica): se reintenta antes de rendirse.
        enlaces = []
        for intento in range(4):
            rp = requests.get(url, headers=HEADERS, timeout=60)
            rp.raise_for_status()
            # Se aceptan los enlaces de sites/default/files que digan "trimestre" O terminen en .xls: algunos no
            # terminan en .xls (".../Segundo_trimestre_2024.1") y otros no dicen "trimestre" ("RCR2E5.xls" es el
            # 1T-2022; un selector solo por nombre lo dejó fuera sin avisar). Cada descarga se valida por su firma
            # binaria de hoja de cálculo.
            for a in BeautifulSoup(rp.text, "html.parser").find_all("a", href=True):
                h = urllib.parse.unquote(a["href"])
                if ("sites/default/files" in h and not re.search(r"\.(pdf|png|jpe?g|gif)$", h, re.I)
                        and ("trimestre" in h.lower() or h.lower().endswith(".xls"))):
                    if urljoin(url, a["href"]) not in enlaces:
                        enlaces.append(urljoin(url, a["href"]))
            if enlaces:
                break
            time.sleep(3 * (intento + 1))
        if not enlaces:
            raise RuntimeError(f"Santiago {anio}: la página no enlaza ningún XLS")
        for enlace in enlaces:
            # estricto: un fichero perdido dejaría un trimestre fuera sin que se note (ver _fusionar_fuente)
            d = requests.get(enlace, headers=HEADERS, timeout=120)
            d.raise_for_status()
            if d.content[:4] != b"\xd0\xcf\x11\xe0":       # OLE2: XLS clásico
                raise RuntimeError(f"Santiago {anio}: {enlace} no es un XLS (firma {d.content[:4]!r})")
            filas, sobre_tope = _sc_parsear_xls(d.content)
            sobre_tope_total += sobre_tope
            n_ficheros += 1
            for f in filas:
                if int(f["fecha"][:4]) < DESDE_ANY:
                    continue
                desc = re.sub(r"^CM-\s*", "", f["desc"], flags=re.I)
                clave = hashlib.md5(f"{f['nif']}|{f['adj']}|{f['fecha']}|{f['importe']}|{desc[:80]}".encode("utf-8")).hexdigest()[:12]
                nif = f["nif"] if _RE_SC_NIF_ES.match(f["nif"]) else ""
                registros[f"Santiago::{clave}"] = {
                    "id":               f"Santiago::{clave}",
                    "municipio":        "Santiago de Compostela",
                    "provincia":        "a_coruna",
                    "fuente":           "santiago",
                    "organisme":        "Ayuntamiento de Santiago de Compostela",
                    "adjudicatari":     f["adj"],
                    "nif":              nif,
                    "import_num":       f["importe"],
                    "data_adjudicacio": f["fecha"],
                    "tipus_contracte":  _SC_TIPOS.get(f["tipo"].lower(), f["tipo"]),
                    "descripcio":       desc,
                    "codi_cpv":         "",
                    "exercici":         f["fecha"][:4],
                }
    registros = list(registros.values())
    por_anio = {}
    for x in registros:
        por_anio[x["exercici"]] = por_anio.get(x["exercici"], 0) + 1
    print(f"Santiago: {len(registros)} contratos menores de {n_ficheros} ficheros XLS ({sobre_tope_total} filas por "
          f"encima de 48.400 EUR excluidas): {dict(sorted(por_anio.items()))}")
    return registros


# Lugo (añadido 2026-09-25): la página de transparencia "Contratos menores" de datosabertos.lugo.gal
# (NO el node/969, que es una plantilla con texto de relleno "Curabitur eget...") lista un PDF por trimestre desde
# 2020. El último es el 3T-2025: Lugo dejó de publicar (a 2026-09-25 no existen los de 4T-2025 ni 2026: 404).
# Verificado abriendo los 20 PDF de 2021-2025:
# - Tabla de 6 columnas en todos: Núm. expediente / Asunto / Precio adjudicación (IVE incluido) / Adjudicatario /
#   Fecha adjudicación / Sección iniciadora. Importe CON IVA; SIN NIF; la "sección iniciadora" es el departamento,
#   no un tipo de contrato (el tipo queda vacío).
# - Formatos de fecha distintos: dd/mm/aaaa (2021, 2022-T1/T2, 2023-2025) y dd-mm-aa (2022-T3 y T4). Los
#   expedientes a veces salen con espacios ("2021/C001 /000333").
# - El PDF del 1T-2022 tiene ~31 % de filas ilegibles en origen (celdas con texto solapado: "Jordi Pedrós4 7M7",
#   fechas "REVIRAVOL0T3A/ 0D1E/2 L0"): se descartan y el trimestre queda incompleto (262 de ~379 filas).
# - Los listados se solapan (el de abril-junio 2021 repite el 31-03; "2022-2023" repite filas de trimestrales) y
#   algunas filas de 2024-T1 son de 2022-2023 (registradas tarde): se deduplica por (expediente, adjudicatario,
#   importe, fecha). Un mismo expediente puede tener varias filas (varios adjudicatarios / lotes).
# - Dos filas (68.476,32 EUR, "48 botes de aglomerado", 2023 y 2024) superan el máximo legal de un menor (48.400
#   = 40.000 + 21 %): se conservan y llevan nota visible (_NOTAS_CONTRATO_MENOR), como el resto de importes
#   imposibles de origen.
LUGO_LISTADO_URL = ("https://datosabertos.lugo.gal/es/content/transparencia-informaci%C3%B3n-para-la-ciudadan%C3%ADa-"
                    "contrataciones-y-servicios-contrataci%C3%B3n-de-bienes-y-servicios/contratos-menores")
_RE_LUGO_EXP = re.compile(r"^\d{4}/[A-Z]\d{3}/\d+$")
_RE_LUGO_FECHA = re.compile(r"^(\d{2})[/-](\d{2})[/-](\d{4}|\d{2})$")


def _lu_txt(c):
    return re.sub(r"\s+", " ", (c or "")).strip()


def _lu_num(txt):
    x = re.sub(r"(?i)euros?|€", "", txt).replace(" ", "").rstrip(",.")
    if not x or not re.search(r"\d", x) or re.search(r"[A-Za-z]", x):
        return None
    try:
        if "," in x:
            return float(x.replace(".", "").replace(",", "."))
        if re.match(r"^\d{1,3}(\.\d{3})+$", x):
            return float(x.replace(".", ""))
        return float(x)
    except ValueError:
        return None


def _lu_fecha(txt):
    m = _RE_LUGO_FECHA.match(txt.replace(" ", ""))
    if not m:
        return None
    d, mo, y = m.groups()
    y = ("20" + y) if len(y) == 2 else y
    if not (1 <= int(mo) <= 12 and 1 <= int(d) <= 31 and 2019 <= int(y) <= 2030):
        return None
    return f"{y}-{mo}-{d}"


def _lu_parsear_pdf(contenido):
    filas, descartadas = [], 0
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        for pagina in pdf.pages:
            for tabla in pagina.extract_tables():
                for r in tabla:
                    if not r or len(r) != 6:
                        continue
                    c = [_lu_txt(x) for x in r]
                    c[0] = re.sub(r"\s+", "", c[0])
                    if c[0].lower().startswith(("núm", "num")) or not _RE_LUGO_EXP.match(c[0]):
                        continue
                    imp, fecha = _lu_num(c[2]), _lu_fecha(c[4])
                    if imp is None or fecha is None or not c[3]:
                        descartadas += 1
                        continue
                    filas.append({"exp": c[0], "asunto": c[1], "importe": imp, "adj": c[3], "fecha": fecha})
    return filas, descartadas


def actualizar_lugo():
    r = requests.get(LUGO_LISTADO_URL, headers=HEADERS, timeout=60)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    pdfs = []
    for a in soup.find_all("a", href=True):
        titulo = a.get_text(" ", strip=True)
        if a["href"].lower().endswith(".pdf") and re.search(r"CONTRATOS MENORES", titulo, re.I):
            if re.search(r"2020", titulo) and not re.search(r"2021", titulo):
                continue                                                     # anteriores a DESDE_ANY
            enlace = urljoin(LUGO_LISTADO_URL, a["href"])
            if enlace not in [p[1] for p in pdfs]:
                pdfs.append((titulo, enlace))
    if len(pdfs) < 15:
        raise RuntimeError(f"Lugo: solo {len(pdfs)} PDF en el listado (¿cambió la página?)")
    print(f"Lugo: {len(pdfs)} PDF de menores desde {DESDE_ANY} en el listado oficial")
    registros, descartadas = {}, 0
    for titulo, enlace in pdfs:
        # estricto: un PDF perdido dejaría un trimestre fuera sin que se note (ver _fusionar_fuente)
        d = requests.get(enlace, headers=HEADERS, timeout=120)
        d.raise_for_status()
        if d.content[:4] != b"%PDF":
            raise RuntimeError(f"Lugo: {enlace} no es un PDF")
        filas, desc = _lu_parsear_pdf(d.content)
        descartadas += desc
        for f in filas:
            if int(f["fecha"][:4]) < DESDE_ANY:
                continue
            clave = hashlib.md5(f"{f['exp']}|{f['adj']}|{f['importe']}|{f['fecha']}".encode("utf-8")).hexdigest()[:12]
            registros[f"Lugo::{clave}"] = {
                "id":               f"Lugo::{clave}",
                "municipio":        "Lugo",
                "provincia":        "lugo",
                "fuente":           "lugo",
                "organisme":        "Ayuntamiento de Lugo",
                "adjudicatari":     f["adj"],
                "nif":              "",
                "import_num":       f["importe"],
                "data_adjudicacio": f["fecha"],
                "tipus_contracte":  "",
                "descripcio":       f["asunto"],
                "codi_cpv":         "",
                "exercici":         f["fecha"][:4],
            }
    registros = list(registros.values())
    por_anio = {}
    for x in registros:
        por_anio[x["exercici"]] = por_anio.get(x["exercici"], 0) + 1
    print(f"Lugo: {len(registros)} contratos menores ({descartadas} filas ilegibles descartadas): "
          f"{dict(sorted(por_anio.items()))}")
    return registros


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
    "a-coruna":          actualizar_a_coruna,
    "vigo":              actualizar_vigo,
    "ferrol":            actualizar_ferrol,
    "pontevedra":        actualizar_pontevedra,
    "ames":              actualizar_ames,
    "santiago":          actualizar_santiago,
    "lugo":              actualizar_lugo,
    "cartagena-governalia": actualizar_cartagena_governalia,
    "ibi-governalia":    actualizar_ibi,
    "sax-governalia":    actualizar_sax,
    "vilamarxant-governalia": actualizar_vilamarxant,
}


def _fusionar_fuente(previos, nombre, funcion, forzar=False):
    """Registros de la fuente `nombre` tras ejecutar `funcion`, con una salvaguarda (2026-09-24): si la
    ejecución falla, o devuelve menos del 90 % de las filas que esa fuente ya tenía en el JSON, se CONSERVAN
    las anteriores y se avisa. Sin esto, una descarga que falla a medias (Ames devolvió 1.896 de 3.387 filas
    en una ejecución, sin ningún error) reemplazaba la fuente por un resultado parcial en silencio.
    Con --forzar se acepta el resultado nuevo aunque sea más pequeño."""
    antes = [r for r in previos if r.get("fuente") == nombre]
    try:
        nuevos = funcion()
    except Exception as e:
        print(f"  !! {nombre}: FALLÓ ({type(e).__name__}: {e}); se conservan las {len(antes)} filas anteriores.")
        return antes
    if antes and not forzar and len(nuevos) < 0.9 * len(antes):
        print(f"  !! {nombre}: devolvió {len(nuevos)} filas frente a las {len(antes)} que ya había (< 90 %); "
              f"se conservan las anteriores. Revisa la fuente o usa --forzar si es correcto.")
        return antes
    return nuevos


def main():
    args = sys.argv[1:]
    forzar = "--forzar" in args
    pedidas = [a for a in args if not a.startswith("--")]
    desconocidas = [f for f in pedidas if f not in _FUENTES]
    if desconocidas:
        sys.exit(f"Fuente(s) desconocida(s): {desconocidas}. Válidas: {sorted(_FUENTES)}")
    previos = _leer_registros_previos()
    if not pedidas:
        todos = []
        for nombre, fn in _FUENTES.items():
            todos += _fusionar_fuente(previos, nombre, fn, forzar)
    else:
        todos = [r for r in previos if r.get("fuente") not in pedidas]
        for nombre in pedidas:
            todos += _fusionar_fuente(previos, nombre, _FUENTES[nombre], forzar)
    _escribir_registros(todos)
    print(f"\nTotal: {len(todos)} contratos menores guardados en {OUT_FILE}")


if __name__ == "__main__":
    main()
