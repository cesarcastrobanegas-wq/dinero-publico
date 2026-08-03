# encoding: utf-8
"""
Descarga contratos menores de fuentes municipales de Murcia cuyo formato
necesita librerías que NO están en requirements.txt de producción (odfpy para
ODS, openpyxl para XLSX, xlrd para XLS legado) -- mismo patrón
manual/periódico que actualizar_alcaldes.py / actualizar_retribuciones.py: se
ejecuta a mano de vez en cuando (cada trimestre/año, cuando el ayuntamiento
publique un fichero nuevo) y genera contratos_menores_murcia_manual.json, que
app.py carga al arrancar y vuelca a la tabla compartida
contratos_menors_locales (ver _cargar_contratos_menores_murcia_manual en app.py).

Fuente Álamo de Murcia NO está aquí: su fuente es CSV (módulo estándar `csv`,
sin dependencia nueva), así que se refresca sola en el cron diario --
ver buscar_en_fuentealamo_menores en app.py.

Ninguna de las dos fuentes de aquí tiene URL predecible por año/trimestre
(verificado 2026-08-03: la carpeta de subida no coincide con el periodo que
describe el fichero) -- por eso ambas funciones scrapean la página de listado
en cada ejecución en vez de adivinar la URL.

Molina de Segura publica los años 2022-2024 en XLS legado (formato binario
OLE2, Composite Document Format vía Apache POI) y solo 2025 en XLSX real
-- verificado con `file` sobre los bytes descargados, no basta con mirar la
extensión de la URL (2022 tiene ADEMÁS una copia en XLSX en un subdominio
distinto, `sedeelectronica.molinadesegura.es`, pero 2023/2024 no tienen
equivalente). Por eso hace falta `xlrd` (que dejó de soportar .xlsx en la
v2.0 pero sigue leyendo .xls perfectamente) además de `openpyxl`.

Uso:  pip install odfpy openpyxl xlrd && python actualizar_contratos_menores_murcia_manual.py
"""
import io
import json
import re
import sys
import time

import openpyxl
import requests
import xlrd
from bs4 import BeautifulSoup
from odf.opendocument import load as odf_load
from odf.table import Table, TableRow, TableCell
from odf.text import P as odf_P

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


def _listar_enlaces(url, extension):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    return sorted({a["href"] for a in soup.find_all("a", href=True)
                   if a["href"].lower().endswith(extension)})


def _num_es(valor):
    """Convierte un importe en formato español ('1.020,03') a float."""
    try:
        return float(str(valor).replace("€", "").strip().replace(".", "").replace(",", "."))
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


def main():
    todos = actualizar_mula() + actualizar_molina_segura()
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump({"generado": time.strftime("%Y-%m-%d %H:%M:%S"), "registros": todos},
                   f, ensure_ascii=False, indent=1)
    print(f"\nTotal: {len(todos)} contratos menores guardados en {OUT_FILE}")


if __name__ == "__main__":
    main()
