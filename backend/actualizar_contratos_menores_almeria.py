# encoding: utf-8
"""
Contratos MENORES del Ayuntamiento de Almería (~205.000 hab., Andalucía).

Fuente OFICIAL: https://almeriaciudad.es/transparencia/contratos-menores/ -- un fichero por año "Contratos
menores AAAA (Versión XLS)" (XLSX, o XLS en 2023) más su PDF. Los nombres de fichero no siguen ningún patrón
(menores.xlsx = 2024, menores-2024-02-12.xls = 2023...), así que el script lee la página en cada ejecución y
toma cada enlace por su TEXTO. Localizado en la auditoría de DATOS_PETICION_MENORES.md §5.

Verificado en crudo (2026-09-29):
- Columnas iguales todos los años: EXPTE / ADJUDICATARIO / OBJETO / DURACIÓN / PRESUPUESTO BASE LICITACIÓN /
  IMPORTE DE ADJUDICACIÓN CON IVA / FECHA ADJUDICACIÓN / Nº LICITADORES / ... Fecha real por contrato (datetime,
  o número de serie de Excel en el .xls de 2023, o texto dd/mm/aaaa en algunas filas). Sin NIF.
- ERROR DE LA FUENTE: el enlace "Contratos menores 2025 (Version XLS)" apunta a contratos-abiertos-2025_0.xlsx
  (contratos ABIERTOS). Se detecta y se descarta solo: un fichero con más del 10 % de importes por encima de
  48.400 € (máximo legal de un menor incluso con IVA) no es de menores -- el de 2025 tiene un 36 % (37 de 104);
  los ficheros de menores reales, un 0 %. (La mediana NO sirve: la del de abiertos es ~30.700 €.) 2025 solo existe en PDF, y ese PDF no se puede reconstruir con fiabilidad (celdas
  centradas en vertical que mezclan dos contratos en la misma línea) -> 2025 queda SIN datos, avisado en la ficha.
- Filas casi duplicadas del mismo contrato (mismo expediente, adjudicatario, importe y fecha con pequeñas
  diferencias de texto) se colapsan; un expediente con VARIOS adjudicatarios distintos se mantiene (son contratos
  distintos). Importe escrito a veces como texto con formatos rotos ("12,000,01" = 12.000,01).

Uso (desde backend/):
    python actualizar_contratos_menores_almeria.py

Genera contratos_menores_almeria.json.gz, que app.py carga al arrancar (_cargar_contratos_menores_almeria)."""
import gzip
import html
import io
import json
import os
import re
import statistics
import time
import unicodedata
import urllib.request
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "contratos_menores_almeria.json.gz")
MENORES_DESDE_FECHA = "2021-09-01"   # mismo corte que MENORES_DESDE_FECHA en app.py -- mantener sincronizado a mano
INDICE = "https://almeriaciudad.es/transparencia/contratos-menores/"
BASE = "https://almeriaciudad.es"
_UA = "Mozilla/5.0 (compatible; dinero-publico-bot/1.0)"


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def _norm(txt):
    t = unicodedata.normalize("NFD", str(txt or "").lower())
    return " ".join("".join(c for c in t if unicodedata.category(c) != "Mn").split())


def _limpiar(txt):
    return " ".join(str(txt or "").split())


def _enlaces():
    """{año: url} de los enlaces 'Contratos menores AAAA (Versión XLS)' de la página índice."""
    pagina = _get(INDICE).decode("utf-8", errors="replace")
    res = {}
    for href, texto in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', pagina, re.S):
        t = _norm(re.sub(r"<[^>]+>", "", html.unescape(texto)))
        m = re.search(r"contratos menores (20\d\d) \(vers?i?on xls\)", t)
        if m and int(m.group(1)) >= 2021:
            res[int(m.group(1))] = href if href.startswith("http") else BASE + href
    return res


def _importe(v):
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v or "").replace("€", "").replace(" ", "").strip()
    if not t:
        return None
    if t.count(",") > 1:                      # "12,000,01": comas de miles + coma decimal
        partes = t.split(",")
        t = "".join(partes[:-1]) + "." + partes[-1]
    elif "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _fecha(v):
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, (int, float)) and 30000 < v < 60000:     # número de serie de Excel (.xls de 2023)
        return (datetime(1899, 12, 30) + timedelta(days=int(v))).strftime("%Y-%m-%d")
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})", str(v or "").strip())
    if m:
        d, mo, y = m.groups()
        y = int(y) + 2000 if len(y) == 2 else int(y)
        try:
            return datetime(y, int(mo), int(d)).strftime("%Y-%m-%d")
        except ValueError:
            return ""
    return ""


def _filas(crudo, url):
    if url.lower().endswith(".xls") and crudo[:2] != b"PK":
        import xlrd
        sh = xlrd.open_workbook(file_contents=crudo).sheet_by_index(0)
        filas = [sh.row_values(i) for i in range(sh.nrows)]
    else:
        import openpyxl
        filas = list(openpyxl.load_workbook(io.BytesIO(crudo), data_only=True).worksheets[0].iter_rows(values_only=True))
    filas = [f for f in filas if any(c not in (None, "") for c in f)]
    cab = [_norm(c) for c in filas[0]]
    col = {}
    for i, c in enumerate(cab):
        if c == "expte" and "exp" not in col:
            col["exp"] = i
        elif c == "adjudicatario" and "adj" not in col:
            col["adj"] = i
        elif c == "objeto" and "obj" not in col:
            col["obj"] = i
        elif c.startswith("importe de adjudicacion") and "imp" not in col:
            col["imp"] = i
        elif c.startswith("fecha adjudicacion") and "fec" not in col:
            col["fec"] = i
    if set(col) != {"exp", "adj", "obj", "imp", "fec"}:
        raise ValueError(f"cabecera no reconocida: {filas[0][:10]}")
    return [{k: f[i] if i < len(f) else None for k, i in col.items()} for f in filas[1:]]


def main():
    enlaces = _enlaces()
    print(f"Enlaces XLS encontrados: {sorted(enlaces)}", flush=True)
    registros, descartes = {}, {}
    for anio in sorted(enlaces):
        url = enlaces[anio]
        filas = _filas(_get(url), url)
        importes = [x for x in (_importe(f["imp"]) for f in filas) if x]
        altos = sum(1 for x in importes if x > 48400)
        if importes and altos > 0.10 * len(importes):
            descartes[anio] = (f"{altos} de {len(importes)} importes > 48.400 € "
                               f"(mediana {statistics.median(importes):,.0f} €): no son menores ({url})")
            print(f"  !! {anio}: DESCARTADO -- {descartes[anio]}", flush=True)
            continue
        n_ok = sin_fecha = 0
        for f in filas:
            fecha, imp = _fecha(f["fec"]), _importe(f["imp"])
            exp, adj = _limpiar(f["exp"]), _limpiar(f["adj"])
            if not exp or imp is None:
                continue
            if not fecha:
                sin_fecha += 1
                continue
            if fecha < MENORES_DESDE_FECHA:
                continue
            rid = f"almeria::{exp}::{_norm(adj)[:40]}::{imp:.2f}::{fecha}"
            if rid in registros:
                continue
            registros[rid] = {
                "id":               rid,
                "municipio":        "Almería",
                "provincia":        "almeria",
                "fuente":           "almeria",
                "organisme":        "Ayuntamiento de Almería",
                "adjudicatari":     adj or "No localizada",
                "nif":              "",
                "import_num":       round(imp, 2),
                "data_adjudicacio": fecha,
                "tipus_contracte":  "",
                "descripcio":       _limpiar(f["obj"]),
                "codi_cpv":         "",
                "exercici":         fecha[:4],
            }
            n_ok += 1
        print(f"  {anio}: {len(filas)} filas, {n_ok} contratos nuevos en ventana, {sin_fecha} sin fecha", flush=True)
        time.sleep(0.2)
    if len(registros) < 800:
        raise SystemExit(f"!! Solo {len(registros)} contratos: posible fallo del origen. No se toca {FICHERO}.")
    tmp = f"{FICHERO}.tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump({
            "generado": time.strftime("%Y-%m-%d"),
            "descripcion": ("Contratos menores del Ayuntamiento de Almería, XLSX/XLS anuales del portal de "
                            "transparencia. Fecha real de adjudicación. Importe con IVA. 2025 sin datos (solo PDF; "
                            "el enlace XLS de 2025 lleva a contratos abiertos). Ver actualizar_contratos_menores_almeria.py."),
            "descartes": descartes,
            "registros": list(registros.values()),
        }, fh, ensure_ascii=False)
    os.replace(tmp, FICHERO)
    por_anio = {}
    for r in registros.values():
        por_anio[r["exercici"]] = por_anio.get(r["exercici"], 0) + 1
    print(f"Hecho: {len(registros)} contratos {dict(sorted(por_anio.items()))} -> {FICHERO}")


if __name__ == "__main__":
    main()
