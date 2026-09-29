# encoding: utf-8
"""
Contratos MENORES del Ayuntamiento de Torrejón de Ardoz (~143.000 hab., Comunidad de Madrid).

Fuente OFICIAL: https://www.ayto-torrejon.es/concejalias/contratacion/contratos-formalizados -- un "LISTADO
CONTRATOS MENORES <TRIMESTRE> <AÑO>" por trimestre: PDF con tabla real de 1T-2022 a 4T-2024 y XLSX desde 1T-2025.
El script lee la página en cada ejecución y toma los enlaces cuyo nombre contiene "contratos menores"; los nombres
no siguen un patrón (prefijos numéricos, "_0", "DE 2022", "3er Trimestre"...). 1T-2023 NO está enlazado en la
página actual pero sigue publicado en su URL original: se añade a mano (ENLACES_EXTRA). Localizado en la
auditoría de DATOS_PETICION_MENORES.md §5.

Verificado en crudo (2026-09-29): las MISMAS 10 columnas en PDF y XLSX -- Nombre/Apellidos o Denominación Social /
CIF o NIF del adjudicatario / Código expediente / Duración / Base imponible / Importe del IVA / Importe IVA incluido
/ Tipo contrato / Objeto del Expediente / Fecha Adjudicación. Se guarda la BASE IMPONIBLE (sin IVA): la fuente
separa base e IVA, así que entra en _FUENTES_CM_SIN_IVA. Fecha real por contrato en tres formatos (2023/06/14,
30/09/2024, datetime de Excel). No hay listados de 2021. Tres variantes reales de la fuente:
- 3T-2023 escribe "Importe IVA inluido" (errata): la columna del total con IVA no se usa, así que no importa.
- 4T-2024 imprime la hoja partida en dos: 16 páginas con 9 columnas y 16 páginas SOLO con la fecha. Se
  reconstruye emparejando tabla a tabla (ver _pegar_columna_fecha; 215 contratos con fecha real oct-dic 2024).
  Si un fichero futuro no tuviera fecha en absoluto, se usaría el primer día del trimestre (nombre del fichero).
- 1T-2022 NO publica la base imponible, solo el total con IVA: ese trimestre se EXCLUYE entero (mezclarlo
  rompería la base sin IVA de toda la fuente), avisado en la ficha.

Uso (desde backend/):
    python actualizar_contratos_menores_torrejon.py

Genera contratos_menores_torrejon.json.gz, que app.py carga al arrancar (_cargar_contratos_menores_torrejon)."""
import gzip
import html
import io
import json
import os
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "contratos_menores_torrejon.json.gz")
MENORES_DESDE_FECHA = "2021-09-01"   # mismo corte que MENORES_DESDE_FECHA en app.py -- mantener sincronizado a mano
INDICE = "https://www.ayto-torrejon.es/concejalias/contratacion/contratos-formalizados"
BASE = "https://www.ayto-torrejon.es"
ENLACES_EXTRA = ["https://www.ayto-torrejon.es/sites/default/files/LISTADO%20CONTRATOS%20MENORES%20PRIMER%20TRIMESTRE%202023.pdf"]
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
    pagina = _get(INDICE).decode("utf-8", errors="replace")
    urls = []
    for h in re.findall(r'href="([^"]+\.(?:pdf|xlsx))"', pagina, re.I):
        h = html.unescape(h)
        if "contratos menores" in _norm(urllib.parse.unquote(h)):
            urls.append(h if h.startswith("http") else BASE + h)
    for extra in ENLACES_EXTRA:
        if urllib.parse.unquote(extra).lower() not in {urllib.parse.unquote(u).lower() for u in urls}:
            urls.append(extra)
    return sorted(set(urls))


def _importe(v):
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v or "").replace("€", "").replace(" ", "").strip()
    if not t:
        return None
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return None


def _fecha(v):
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d")
    t = str(v or "")
    m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", t)
    if m:
        y, mo, d = m.groups()
    else:
        m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", t)
        if not m:
            return ""
        d, mo, y = m.groups()
    try:
        return datetime(int(y), int(mo), int(d)).strftime("%Y-%m-%d")
    except ValueError:
        return ""


CAMPOS = {"adj": "nombre/apellidos", "cif": "cif o nif", "exp": "codigo expediente", "base": "base imponible",
          "tipo": "tipo contrato", "obj": "objeto del expediente", "fec": "fecha adjudicacion"}
OBLIGATORIOS = {"adj", "cif", "exp", "tipo", "obj"}     # "base" y "fec" faltan en 1T-2022 y 4T-2024 respectivamente
_ORD = {"primer": 1, "1er": 1, "segundo": 2, "2o": 2, "tercer": 3, "3er": 3, "cuarto": 4, "4o": 4}


def _trimestre(nombre):
    """'LISTADO CONTRATOS MENORES CUARTO TRIMESTRE 2024.pdf' -> (2024, 4)."""
    n = _norm(urllib.parse.unquote(nombre))
    y = re.search(r"(20\d\d)", n)
    q = next((v for k, v in _ORD.items() if re.search(r"\b" + k + r"\b", n)), None)
    return (int(y.group(1)), q) if y and q else None


def _mapa(cab):
    n = [_norm(c) for c in cab]
    m = {}
    for k, pref in CAMPOS.items():
        for i, c in enumerate(n):
            if c.startswith(pref):
                m[k] = i
                break
    return m if OBLIGATORIOS <= set(m) else None


def _pegar_columna_fecha(tablas):
    """En 4T-2024 la hoja se imprimió partida en dos: las 16 primeras páginas llevan 9 columnas (sin fecha) y las 16
    últimas SOLO la columna "Fecha Adjudicación" (tablas de 1 columna). Verificado: 218 contratos y 234 - 16
    cabeceras = 218 fechas. Se empareja la i-ésima tabla principal con la i-ésima tabla de fechas, en orden, SOLO si
    hay el mismo número de tablas de cada tipo y cada pareja tiene exactamente el mismo número de filas de datos.
    Si algo no cuadra no se toca nada (el trimestre cae en la fecha de inicio de trimestre, ver main)."""
    fechas = [t for t in tablas if t and len(t[0]) == 1 and _norm(t[0][0]).startswith("fecha adjudicacion")]
    principales = [t for t in tablas if t and len(t[0]) > 1]
    if not fechas or len(fechas) != len(principales):
        return tablas
    pegadas = []
    for principal, tf in zip(principales, fechas):
        i_cab = next((i for i, f in enumerate(principal) if _mapa(f)), None)
        if i_cab is None or "fec" in _mapa(principal[i_cab]):
            return tablas
        datos_p, datos_f = principal[i_cab + 1:], tf[1:]
        if len(datos_p) != len(datos_f):
            return tablas
        cab = list(principal[i_cab]) + ["Fecha Adjudicación"]
        pegadas.append(principal[:i_cab] + [cab] + [list(f) + [d[0]] for f, d in zip(datos_p, datos_f)])
    return pegadas


def _filas(crudo, url):
    tablas = []
    if crudo[:4] == b"%PDF":
        import pdfplumber
        with pdfplumber.open(io.BytesIO(crudo)) as pdf:
            for p in pdf.pages:
                tablas.extend(p.extract_tables())
        tablas = _pegar_columna_fecha(tablas)
    else:
        import openpyxl
        ws = openpyxl.load_workbook(io.BytesIO(crudo), data_only=True).worksheets[0]
        tablas.append([list(r) for r in ws.iter_rows(values_only=True)])
    salida, mapa = [], None
    for t in tablas:
        for fila in t:
            m = _mapa(fila)
            if m:
                mapa = m
                continue
            if not mapa or not any(c not in (None, "") for c in fila):
                continue
            g = lambda k: fila[mapa[k]] if k in mapa and mapa[k] < len(fila) else None
            salida.append({k: g(k) for k in CAMPOS})
    return salida


def main():
    registros, por_fichero, descartadas, avisos = {}, {}, 0, []
    for url in _enlaces():
        nombre = urllib.parse.unquote(url.rsplit("/", 1)[-1])
        filas = _filas(_get(url), url)
        if filas and all(f["base"] in (None, "") for f in filas):
            avisos.append(f"{nombre}: sin base imponible, trimestre excluido ({len(filas)} filas)")
            print(f"  !! {avisos[-1]}", flush=True)
            continue
        fecha_trimestre = ""
        if filas and all(f["fec"] in (None, "") for f in filas):
            tq = _trimestre(nombre)
            if not tq:
                raise SystemExit(f"!! {nombre}: sin columna de fecha y sin trimestre reconocible en el nombre")
            fecha_trimestre = f"{tq[0]}-{3 * (tq[1] - 1) + 1:02d}-01"
            avisos.append(f"{nombre}: sin fecha por contrato, se usa {fecha_trimestre}")
            print(f"  !! {avisos[-1]}", flush=True)
        n = 0
        for f in filas:
            fecha, base = (_fecha(f["fec"]) or fecha_trimestre), _importe(f["base"])
            adj = _limpiar(f["adj"])
            if not fecha or base is None or not adj:
                descartadas += 1
                continue
            if fecha < MENORES_DESDE_FECHA:
                continue
            exp = _limpiar(f["exp"])
            rid = f"torrejon::{fecha[:4]}::{exp}::{_limpiar(f['cif'])}::{base:.2f}"
            if rid in registros:
                continue
            registros[rid] = {
                "id":               rid,
                "municipio":        "Torrejón de Ardoz",
                "provincia":        "madrid",
                "fuente":           "torrejon",
                "organisme":        "Ayuntamiento de Torrejón de Ardoz",
                "adjudicatari":     adj,
                "nif":              _limpiar(f["cif"]),
                "import_num":       round(base, 2),
                "data_adjudicacio": fecha,
                "tipus_contracte":  _limpiar(f["tipo"]).capitalize(),
                "descripcio":       _limpiar(f["obj"]),
                "codi_cpv":         "",
                "exercici":         fecha[:4],
            }
            n += 1
        por_fichero[urllib.parse.unquote(url.rsplit("/", 1)[-1])] = n
        print(f"  {urllib.parse.unquote(url.rsplit('/', 1)[-1])[:70]}: {len(filas)} filas, {n} contratos", flush=True)
        time.sleep(0.2)
    if len(registros) < 2000:
        raise SystemExit(f"!! Solo {len(registros)} contratos: posible fallo del origen. No se toca {FICHERO}.")
    tmp = f"{FICHERO}.tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump({
            "generado": time.strftime("%Y-%m-%d"),
            "avisos": avisos,
            "descripcion": ("Contratos menores del Ayuntamiento de Torrejón de Ardoz, listados trimestrales oficiales "
                            "(PDF 2022-2024, XLSX desde 2025). Fecha real, CIF. Importe = base imponible SIN IVA. Ver "
                            "actualizar_contratos_menores_torrejon.py."),
            "registros": list(registros.values()),
        }, fh, ensure_ascii=False)
    os.replace(tmp, FICHERO)
    por_anio = {}
    for r in registros.values():
        por_anio[r["exercici"]] = por_anio.get(r["exercici"], 0) + 1
    print(f"Hecho: {len(registros)} contratos {dict(sorted(por_anio.items()))}, {descartadas} filas sin fecha/importe/"
          f"adjudicatario descartadas -> {FICHERO}")


if __name__ == "__main__":
    main()
