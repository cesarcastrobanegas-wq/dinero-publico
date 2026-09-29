# encoding: utf-8
"""
Contratos MENORES del Ayuntamiento de Telde (~104.000 hab., Canarias) -- SOLO 2025.

Fuente OFICIAL: https://www.telde.es/transparencia/contratos-convenios-concesiones-y-subvenciones/contratos-menores/
-- "RELACIÓN DE CONTRATOS MENORES AÑO: 2025" en ODS (y PDF). Es el único listado propio publicado en esa página
(no hay años anteriores enlazados; para el detalle, la página remite a la Plataforma de Contratación del Estado,
órgano "Concejalía Delegada de Contratación del Ayuntamiento de Telde"). Localizado en la auditoría de
DATOS_PETICION_MENORES.md §5.

Verificado en crudo (2026-09-29): cada contrato ocupa DOS filas del ODS -- la primera con Expediente / Tipo /
Objeto / Estado / Importe / Adjudicatario, y la siguiente con "Adjudicación:dd/mm/aaaa" -- y se emparejan en
orden. 93 contratos con adjudicación entre enero y diciembre de 2025. Algunas celdas arrastran una anotación de
la hoja de cálculo ("No ordenado, pulse…") que se recorta, y algunos expedientes van con guion ("18364-2025") o
truncados ("11864/202"). El importe usa punto decimal y coma de
miles ("3,500.00"). La fuente no dice si el importe lleva impuestos (IGIC): no se afirma nada sobre la base.
Se lee el ODS sin dependencias (es un ZIP con content.xml).

Uso (desde backend/):
    python actualizar_contratos_menores_telde.py

Genera contratos_menores_telde.json.gz, que app.py carga al arrancar (_cargar_contratos_menores_telde)."""
import gzip
import html
import io
import json
import os
import re
import time
import urllib.request
import zipfile
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "contratos_menores_telde.json.gz")
MENORES_DESDE_FECHA = "2021-09-01"   # mismo corte que MENORES_DESDE_FECHA en app.py -- mantener sincronizado a mano
ODS_URL = "https://www.telde.es/wp-content/uploads/2026/04/transparencia-contratosmenores.ods"
_UA = "Mozilla/5.0 (compatible; dinero-publico-bot/1.0)"


def _limpiar(txt):
    t = " ".join(html.unescape(str(txt or "")).split())
    return re.split(r"\s*No ordenado,", t)[0].strip()      # anotación de la hoja de cálculo pegada a la celda


def _filas_ods(crudo):
    xml = zipfile.ZipFile(io.BytesIO(crudo)).read("content.xml").decode("utf-8")
    filas = []
    for fila in re.findall(r"<table:table-row[^>]*>(.*?)</table:table-row>", xml, re.S):
        celdas = []
        for attrs, cont in re.findall(r"<table:table-cell([^>]*)>(.*?)</table:table-cell>", fila, re.S):
            texto = _limpiar(re.sub(r"<[^>]+>", " ", cont))
            rep = re.search(r'table:number-columns-repeated="(\d+)"', attrs)
            celdas.extend([texto] * min(int(rep.group(1)) if rep else 1, 20))
        celdas = [c for c in celdas]
        if any(celdas):
            filas.append([c for c in celdas if c])
    return filas


def _importe(txt):
    t = str(txt or "").replace("€", "").replace(" ", "").strip()
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def main():
    req = urllib.request.Request(ODS_URL, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        filas = _filas_ods(r.read())
    registros, pendiente, huerfanas = {}, None, 0
    for f in filas:
        if len(f) >= 6 and re.match(r"^\d+[/-]\d{2,4}$", f[0]):
            if pendiente:
                huerfanas += 1
            pendiente = f
            continue
        m = re.match(r"^Adjudicaci[oó]n:\s*(\d{2})/(\d{2})/(\d{4})", " ".join(f))
        if m and pendiente:
            fecha = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).strftime("%Y-%m-%d")
            exp, tipo, obj, _estado, imp, adj = pendiente[:6]
            importe = _importe(imp)
            if importe is not None and fecha >= MENORES_DESDE_FECHA:
                rid = f"telde::{exp}"
                registros[rid] = {
                    "id":               rid,
                    "municipio":        "Telde",
                    "provincia":        "las_palmas",
                    "fuente":           "telde",
                    "organisme":        "Ayuntamiento de Telde",
                    "adjudicatari":     adj,
                    "nif":              "",
                    "import_num":       round(importe, 2),
                    "data_adjudicacio": fecha,
                    "tipus_contracte":  tipo,
                    "descripcio":       obj,
                    "codi_cpv":         "",
                    "exercici":         fecha[:4],
                }
            pendiente = None
    print(f"{len(registros)} contratos ({huerfanas} filas de contrato sin su línea de adjudicación)")
    if len(registros) < 80:              # 93 contratos en 2025 al conectarlo
        raise SystemExit(f"!! Solo {len(registros)} contratos: posible fallo del origen. No se toca {FICHERO}.")
    tmp = f"{FICHERO}.tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump({
            "generado": time.strftime("%Y-%m-%d"),
            "descripcion": ("Contratos menores del Ayuntamiento de Telde, relación del año 2025 (único listado propio "
                            "publicado, ODS). Fecha real de adjudicación, sin NIF. Ver actualizar_contratos_menores_telde.py."),
            "registros": list(registros.values()),
        }, fh, ensure_ascii=False)
    os.replace(tmp, FICHERO)
    print(f"Hecho -> {FICHERO}")


if __name__ == "__main__":
    main()
