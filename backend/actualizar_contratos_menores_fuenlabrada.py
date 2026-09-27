# encoding: utf-8
"""
Contratos MENORES del Ayuntamiento de Fuenlabrada (~192.000 hab., Comunidad de Madrid).

Fuente OFICIAL: informes TRIMESTRALES del Ayuntamiento y sus Organismos Autónomos (OO.AA: CIFE, IMLS, OTAF,
PMC, PMD) en `transparencia.ayto-fuenlabrada.es/contratos/menores/` -- página PÚBLICA y SIN contraseña (a
diferencia del "visor de contratos" general de ese mismo portal, que sí está protegido; esta es una sección
distinta con ficheros descargables directos, encontrada navegando el menú completo de "Contratos y
Patrimonio").

Mezcla tres formatos de fichero según el trimestre (.xls legacy/OLE2, .xlsx, .ods) y light varía la cabecera
literal ("Denominación" vs "Título"+"Tipo de Contrato", "Fecha Aprobación" vs "Fecha Adj.") pero la POSICIÓN de
columna de cada campo real es estable en todos: 0=expediente, 1=organismo, 2=objeto, 3=fecha, 4=duración,
5=licitadores, 6=NIF/CIF, 7=adjudicatario, 8=importe. Cada fichero trae VARIAS hojas (una por organismo:
Ayuntamiento + los OO.AA) -- se recorren todas. Cada contrato aparece en dos filas: la de datos y una fila de
"Total <empresa>" justo debajo (subtotal) que hay que descartar -- se identifica exigiendo que la columna de
fecha (índice 3) contenga una fecha real, no por longitud de fila (la fila de "Total" tiene un desplazamiento
de columnas distinto según el formato, así que contarlas no sirve).

Uso (desde backend/):
    python actualizar_contratos_menores_fuenlabrada.py

Genera contratos_menores_fuenlabrada.json.gz, que app.py carga al arrancar (ver
_cargar_contratos_menores_fuenlabrada)."""
import gzip
import io
import json
import os
import re
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "contratos_menores_fuenlabrada.json.gz")
MENORES_DESDE_FECHA = "2021-09-01"   # mismo corte que MENORES_DESDE_FECHA en app.py -- mantener sincronizado a mano

_UPLOADS = "https://transparencia.ayto-fuenlabrada.es/wp-content/uploads"
# (año, trimestre) -> URL exacta (recogidas a mano de transparencia.ayto-fuenlabrada.es/contratos/menores/,
# 2026-09-29). Empieza en 2021T3 (el trimestre que contiene el inicio de la ventana de 5 años, 2021-09-01).
FICHEROS = {
    (2021, 3): f"{_UPLOADS}/2021/11/3o-TRIMESTRE-AYTO-Y-OOAA-contratos-menores-2021.xls",
    (2021, 4): f"{_UPLOADS}/2022/01/4o-TRIMESTRE-AYTO-Y-OOAA.-MENORES.xls",
    (2022, 1): f"{_UPLOADS}/2022/04/1T-2022-Contratos-menores-AYTO-Y-OO.AA_.xls",
    (2022, 2): f"{_UPLOADS}/2022/07/Contratos-menores-2T-2022-AYTO-Y-OO.AA_.xls",
    (2022, 3): f"{_UPLOADS}/2022/10/Contratos-menores-3T-2022-AYTO-Y-OO.AA_..xls",
    (2022, 4): f"{_UPLOADS}/2023/01/4-TR-2022-AYTO-Y-OO.AA_..xls",
    (2023, 1): f"{_UPLOADS}/2023/01/Contratos-Menores-1T-2023-AYTO-Y-OO.AA-1.xls",
    (2023, 2): f"{_UPLOADS}/2025/03/2T-2023-AYTO-Y-OOAA.ods",
    (2023, 3): f"{_UPLOADS}/2023/10/3T-2023-AYTO-Y-OOAA.ods",
    (2023, 4): f"{_UPLOADS}/2024/01/4T-2023-AYTO-Y-OO.AA_..xls",
    (2024, 1): f"{_UPLOADS}/2024/04/1-TR-2024-AYTO-Y-OO.AA_..ods",
    (2024, 2): f"{_UPLOADS}/2024/07/2-TR-2024-AYTO-Y-OO.AA_..ods",
    (2024, 3): f"{_UPLOADS}/2024/10/3T-2024-AYTO-Y-OO.AA_..ods",
    (2024, 4): f"{_UPLOADS}/2025/01/4T-2024-AYTO-Y-OO.AA_..ods",
    (2025, 1): f"{_UPLOADS}/2025/04/1T-2025-AYTO-Y-OO.AA_..xlsx",
    (2025, 2): f"{_UPLOADS}/2025/07/2T-2025-AYTO-Y-OO.AA_..xls",
    (2025, 3): f"{_UPLOADS}/2025/10/3T-2025-AYTO-Y-AA.OO_.xlsx",
    (2025, 4): f"{_UPLOADS}/2026/01/4T-2025-AYTO-Y-OO.AA_..xls",
    (2026, 1): f"{_UPLOADS}/2026/04/Contratos-menores-AYTO-Y-OO.AA-1T-2026.xls",
    (2026, 2): f"{_UPLOADS}/2026/08/Contratos-menores-AYTO-Y-OO.AA_.-2T-2026.xls",
}

_UA = "Mozilla/5.0 (compatible; dinero-publico-bot/1.0)"
_RE_FECHA = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$")


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _limpiar(txt):
    return re.sub(r"\s+", " ", str(txt or "")).strip()


def _fecha_iso(valor):
    if hasattr(valor, "strftime"):
        return valor.strftime("%Y-%m-%d")
    m = _RE_FECHA.match(str(valor or "").strip())
    if not m:
        return ""
    d, mo, y = m.groups()
    return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"


def _importe(valor):
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor or "").replace("€", "").strip()
    if re.match(r"^\d+\.\d{2}$", texto):
        try:
            return float(texto)
        except ValueError:
            pass
    limpio = texto.replace(".", "").replace(",", ".")
    try:
        return float(limpio)
    except ValueError:
        return 0.0


def _columnas(fila):
    """Localiza cada campo por el TEXTO de la cabecera -- comprobado en vivo (2026-09-29) que NO todos los
    ficheros tienen la misma posición de columna: los más antiguos (p.ej. 2022T1) traen una columna vacía de
    más al principio, desplazando todo una posición -- con índices fijos el expediente salía vacío (columna
    en blanco) y las 6 primeras entregas trimestrales se leían como 0 contratos, silenciosamente. Mismo tipo
    de bug ya visto y corregido en Móstoles/Palma."""
    idx = {}
    for i, celda in enumerate(fila):
        t = _limpiar(celda).lower()
        if "exp" in t and "expres" not in t:   # "Num. Expe.", "N.º Expte.", "Nº Expediente"... (abreviaturas
            idx["expediente"] = i             # dispares según el trimestre, ver docstring del módulo)
        elif "organismo" in t:
            idx["organismo"] = i
        elif "objeto" in t or "denomina" in t or "título" in t or "titulo" in t:
            idx["objeto"] = i
        elif "fecha" in t:
            idx["fecha"] = i
        elif "cif" in t or "nif" in t:
            idx["nif"] = i
        elif "adjudicatari" in t:
            idx["adjudicatari"] = i
        elif "import" in t:
            idx["importe"] = i
    return idx if {"expediente", "objeto", "fecha", "adjudicatari", "importe"} <= idx.keys() else None


def _filas_a_registros(filas_por_hoja, etiqueta):
    registros = []
    for hoja, filas in filas_por_hoja:
        idx = None
        for fila in filas:
            if idx is None:
                idx = _columnas(fila)
                continue   # tanto si esta fila era la cabecera como si no, nunca es un dato
            if len(fila) <= max(idx.values()):
                continue
            fecha = _fecha_iso(fila[idx["fecha"]])
            if not fecha or fecha < MENORES_DESDE_FECHA:
                continue   # también descarta de paso las filas "Total X" (esa columna no es una fecha real ahí)
            expediente = _limpiar(fila[idx["expediente"]])
            if not expediente:
                continue
            registros.append({
                "id":               f"fuenlabrada::{expediente}",
                "municipio":         "Fuenlabrada",
                "provincia":         "madrid",
                "fuente":            "fuenlabrada",
                "organisme":         _limpiar(fila[idx.get("organismo", -1)]) if "organismo" in idx else hoja,
                "adjudicatari":      _limpiar(fila[idx["adjudicatari"]]) or "No localizada",
                "nif":               _limpiar(fila[idx.get("nif", -1)]) if "nif" in idx else "",
                "import_num":        round(_importe(fila[idx["importe"]]), 2),
                "data_adjudicacio":  fecha,
                "tipus_contracte":   "",
                "descripcio":        _limpiar(fila[idx["objeto"]]),
                "codi_cpv":          "",
                "exercici":          fecha[:4],
            })
        if idx is None:
            print(f"  !! {etiqueta}/{hoja}: no se reconoció la cabecera de columnas, hoja omitida", flush=True)
    return registros


def _leer_xls(crudo):
    import xlrd
    from datetime import datetime
    libro = xlrd.open_workbook(file_contents=crudo)
    out = []
    for nombre in libro.sheet_names():
        hoja = libro.sheet_by_name(nombre)
        filas = []
        for i in range(hoja.nrows):
            fila = list(hoja.row_values(i))
            for c in range(hoja.ncols):
                # XL_CELL_DATE=3 -- se comprueba en CUALQUIER columna (no solo una posición fija: qué
                # columna es la fecha varía según el trimestre, ver docstring del módulo) y se convierte a
                # datetime real para que _fecha_iso la reconozca igual que en los ficheros xlsx/ods.
                if hoja.cell_type(i, c) == 3 and fila[c]:
                    y, mo, d, hh, mm, ss = xlrd.xldate_as_tuple(fila[c], libro.datemode)
                    fila[c] = datetime(y, mo, d)
            filas.append(tuple(fila))
        out.append((nombre, filas))
    return out


def _leer_xlsx(crudo):
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(crudo), data_only=True)
    return [(nombre, list(wb[nombre].iter_rows(values_only=True)))
            for nombre in wb.sheetnames if type(wb[nombre]).__name__ == "Worksheet"]


def _leer_ods(crudo):
    from odf.opendocument import load
    from odf.table import Table, TableRow, TableCell
    from odf.text import P
    doc = load(io.BytesIO(crudo))
    out = []
    for tabla in doc.spreadsheet.getElementsByType(Table):
        filas = []
        for row in tabla.getElementsByType(TableRow):
            celdas = row.getElementsByType(TableCell)
            filas.append(tuple("".join(str(p) for p in c.getElementsByType(P)) for c in celdas))
        out.append((tabla.getAttribute("name"), filas))
    return out


def _parsear(crudo, url, etiqueta):
    ext = url.rsplit(".", 1)[-1].lower()
    try:
        if ext == "xls":
            filas_por_hoja = _leer_xls(crudo)
        elif ext == "xlsx":
            filas_por_hoja = _leer_xlsx(crudo)
        elif ext == "ods":
            filas_por_hoja = _leer_ods(crudo)
        else:
            print(f"  !! {etiqueta}: extensión desconocida ({ext}), omitido", flush=True)
            return []
    except Exception as e:
        print(f"  !! {etiqueta}: error al parsear ({type(e).__name__}: {e}), omitido", flush=True)
        return []
    return _filas_a_registros(filas_por_hoja, etiqueta)


def _guardar(existentes):
    tmp = f"{FICHERO}.tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump({
            "generado": time.strftime("%Y-%m-%d"),
            "descripcion": ("Contratos menores del Ayuntamiento de Fuenlabrada y sus Organismos Autónomos "
                             "(CIFE/IMLS/OTAF/PMC/PMD), informes trimestrales oficiales en xls/xlsx/ods. "
                             "data_adjudicacio = 'Fecha Aprobación'/'Fecha Adj.' real. Ver "
                             "actualizar_contratos_menores_fuenlabrada.py."),
            "registros": list(existentes.values()),
        }, f, ensure_ascii=False)
    os.replace(tmp, FICHERO)


def main():
    existentes = {}
    for (anio, trimestre), url in sorted(FICHEROS.items()):
        etiqueta = f"{anio}T{trimestre}"
        print(f"Descargando {etiqueta}...", flush=True)
        try:
            crudo = _get(url)
        except Exception as e:
            print(f"  !! {etiqueta}: error de descarga ({type(e).__name__}: {e})", flush=True)
            continue
        registros = _parsear(crudo, url, etiqueta)
        for r in registros:
            existentes[r["id"]] = r
        print(f"  {etiqueta}: {len(registros)} contratos en ventana", flush=True)
        _guardar(existentes)

    print(f"\nHecho: {len(existentes)} registros en {FICHERO}.")


if __name__ == "__main__":
    main()
