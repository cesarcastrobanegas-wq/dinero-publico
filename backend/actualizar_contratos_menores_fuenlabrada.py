# encoding: utf-8
"""
Contratos MENORES del Ayuntamiento de Fuenlabrada (~192.000 hab., Comunidad de Madrid).

Fuente OFICIAL: informes TRIMESTRALES del Ayuntamiento y sus Organismos Autónomos (OO.AA: CIFE, IMLS, OTAF,
PMC, PMD) en `transparencia.ayto-fuenlabrada.es/contratos-menores` (portal nuevo desde
noviembre de 2026; antes, `/contratos/menores/` en WordPress) -- página PÚBLICA y SIN contraseña (a
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
from alcance import alcance_desde
MENORES_DESDE_FECHA = alcance_desde()   # ventana móvil de 5 años (alcance.py), la misma que usa app.py

_PORTAL = "https://transparencia.ayto-fuenlabrada.es"
# 09-11-2026: el ayuntamiento cambió de portal (los ficheros de wp-content/uploads dan 404 desde el 01-11). El nuevo
# carga la lista de ficheros de su API pública: la vista /contratos-menores es la entidad de abajo, y cada registro
# trae año, título («1er Trimestre 2026»), categoría y el fichero en «/download/...». Se cogen solo los informes
# trimestrales del Ayuntamiento y sus OO.AA (los mismos de antes); las sociedades mercantiles van aparte en el portal
# y no estaban en este generador.
_API_LISTA = (_PORTAL + "/api/v1/entity-record/index-all?dynamic_entity_uuid=d1f22c9c-eafc-4cc0-8064-c0309aae6484"
              "&active=1")
_CATEGORIA = "Ayuntamiento y Organismos Autónomos"
_RE_TRIMESTRE = re.compile(r"^([1-4])\s*(?:er|º|°|o|ª)?\s*Trimestre\s+(?:del?\s+)?(\d{4})$", re.I)


def _texto_es(v):
    return (v.get("es") if isinstance(v, dict) else v) or ""


def ficheros_del_portal(registros):
    """{(año, trimestre): URL} de los informes trimestrales del Ayuntamiento y OO.AA dentro de la ventana, a partir de
    la lista de la API. Si un trimestre sale dos veces, se queda el actualizado más tarde."""
    desde = (int(MENORES_DESDE_FECHA[:4]), (int(MENORES_DESDE_FECHA[5:7]) - 1) // 3 + 1)
    out, cuando = {}, {}
    for r in registros:
        d = r.get("data") or {}
        if _texto_es(d.get("builderInputComponent2")).strip() != _CATEGORIA:
            continue
        m = _RE_TRIMESTRE.match(_texto_es(d.get("builderInputComponent1")).strip())
        doc = d.get("documentUploadComponent1") or {}
        if not m or not str(doc.get("image") or "").startswith("/download/"):
            continue
        clave = (int(m.group(2)), int(m.group(1)))
        if clave < desde:
            continue
        actualizado = "/".join(reversed(str(r.get("updated_at") or "").split("/")))   # dd/mm/aaaa -> aaaa/mm/dd
        if clave not in out or actualizado >= cuando[clave]:
            out[clave], cuando[clave] = _PORTAL + doc["image"], actualizado
    return out


def _lista_del_portal():
    datos = json.loads(_get(_API_LISTA).decode("utf-8"))
    registros = datos.get("data") if isinstance(datos, dict) else None
    if not isinstance(registros, list):
        raise ValueError("la API del portal no trae la lista de ficheros")
    return registros

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
    try:
        ficheros = ficheros_del_portal(_lista_del_portal())
    except Exception as e:
        # sin la lista no se descarga nada: el flujo semanal lo cuenta como «fallan las descargas» y conserva el anterior
        print(f"  !! lista de ficheros del portal: error de descarga ({type(e).__name__}: {e})", flush=True)
        ficheros = {}
    print(f"{len(ficheros)} informes trimestrales en el portal desde {MENORES_DESDE_FECHA[:7]}", flush=True)
    for (anio, trimestre), url in sorted(ficheros.items()):
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
