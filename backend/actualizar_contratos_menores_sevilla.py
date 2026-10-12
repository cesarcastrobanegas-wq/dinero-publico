# encoding: utf-8
"""
Contratos MENORES del Ayuntamiento de Sevilla (~690.000 hab., Andalucía).

Fuente OFICIAL: sevilla.org > Servicios > Contratación > Contratos > <AÑO>
(https://www.sevilla.org/servicios/contratacion/contratos/<AÑO>): un PDF MENSUAL "Contratos adjudicados mediante
procedimiento menor. <MES> <AÑO>", con tabla real (pdfplumber la extrae limpia). Los nombres de fichero no siguen
un patrón (para-publicar-menores-abril.pdf, menores-enero-2025.pdf, borrador-agosto.pdf...), así que el script
lee la página de cada año y toma los PDF cuyo nombre contiene "menores", más los "borrador-<mes>.pdf" de 2026
(julio y agosto de 2026 se publicaron con ese nombre, sin la palabra "menores"). Se excluyen las "fe de errores".
Localizado en la auditoría de DATOS_PETICION_MENORES.md §5.

Verificado en crudo (2026-09-29): tres variantes de cabecera (14, 15 y 17 columnas) que se leen por NOMBRE:
UNIDAD TRAMITADORA / Nº EXPEDIENTE / OBJETO / FIGURA / Nº LICIT / ADJUDICATARIO / CIF / FECHA ADJUD /
APLICACIÓN / DURAC / IMPORTE LICITAC. / IVA LICITAC. / IMPORTE ADJUD. (SIN IVA) / IVA ADJUD. ...
El importe adjudicado es SIN IVA, con el IVA en columna aparte (p.ej. 3.955,00 + 831,00 = 21 %): la fuente entra
en _FUENTES_CM_SIN_IVA. Las filas de agrupación ("DIRECCIÓN GENERAL DE ...", sin expediente) se ignoran. Fecha real
de adjudicación por contrato y CIF del adjudicatario.

Uso (desde backend/):
    python actualizar_contratos_menores_sevilla.py

Genera contratos_menores_sevilla.json.gz, que app.py carga al arrancar (_cargar_contratos_menores_sevilla)."""
import gzip
import io
import json
import os
import re
import time
import unicodedata
import urllib.request
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "contratos_menores_sevilla.json.gz")
from alcance import alcance_desde
MENORES_DESDE_FECHA = alcance_desde()   # ventana móvil de 5 años (alcance.py), la misma que usa app.py
PAGINA_ANIO = "https://www.sevilla.org/servicios/contratacion/contratos/{anio}"
_UA = "Mozilla/5.0 (compatible; dinero-publico-bot/1.0)"
_MESES = ("enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre")


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def _norm(txt):
    t = unicodedata.normalize("NFD", str(txt or "").lower())
    return " ".join("".join(c for c in t if unicodedata.category(c) != "Mn").split())


def _limpiar(txt):
    return " ".join(str(txt or "").split())


def _enlaces(anio):
    pagina = _get(PAGINA_ANIO.format(anio=anio)).decode("utf-8", errors="replace")
    urls = set(re.findall(r'href="(https://www\.sevilla\.org/servicios/contratacion/contratos/%d/[^"]+\.pdf)"' % anio,
                          pagina))
    buenos = []
    for u in sorted(urls):
        nombre = u.rsplit("/", 1)[-1].lower()
        if "errores" in nombre:
            continue
        if "menores" in nombre or re.match(r"^borrador-(%s)\.pdf$" % _MESES, nombre):
            buenos.append(u)
    return buenos


def _importe(txt):
    """La fuente mezcla '14.880,00' (español) con '3000.00' (punto decimal, varios PDF de 2026) en el MISMO
    fichero. Bug real encontrado al conectar: quitar siempre los puntos convertía 3.000,00 € en 300.000 €."""
    t = str(txt or "").replace("€", "").replace(" ", "").strip()
    if not t:
        return None
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", t):     # '14.880' = miles sin decimales
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return None


def _fecha(txt):
    """Cuatro formatos reales en la fuente: '14/06/2021', '12-12-2024', '03/07/24' y '2025-01-15' (ISO)."""
    t = str(txt or "")
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", t)
    if m:
        y, mo, d = m.groups()
    else:
        m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4}|\d{2})(?!\d)", t)
        if not m:
            return ""
        d, mo, y = m.groups()
        if len(y) == 2:                  # '03/07/24' (varios PDF de 2024-2026)
            y = "20" + y
    try:
        return datetime(int(y), int(mo), int(d)).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _mapa(cab):
    col = {}
    for i, c in enumerate(cab):
        n = _norm(c)
        if n.startswith("unidad tramitadora"):
            col.setdefault("uni", i)
        elif n.rstrip(".") in ("exp", "expte", "expediente") or (n.startswith("n") and "exp" in n):   # "EXP", "EXP."
            col.setdefault("exp", i)
        elif n.startswith("objeto"):
            col.setdefault("obj", i)
        elif n.startswith("figura"):
            col.setdefault("fig", i)
        elif n.startswith("adjudicat"):          # agosto 2024 escribe "ADJUDICATORIO"
            col.setdefault("adj", i)
        elif n.startswith("cif"):
            col.setdefault("cif", i)
        elif n.startswith("fecha adj"):
            col.setdefault("fec", i)
        elif n.startswith("importe adj"):          # "IMPORTE ADJUD. (SIN IVA)" o "IMPORTE ADJ SIN IVA" (2021)
            col.setdefault("imp", i)
    return col if {"exp", "adj", "fec", "imp"} <= set(col) else None


def _parsear(crudo, url):
    import pdfplumber
    filas, mapa = [], None
    with pdfplumber.open(io.BytesIO(crudo)) as pdf:
        for p in pdf.pages:
            for t in p.extract_tables():
                if not t:
                    continue
                # la cabecera puede no ser la 1.ª fila: los PDF de 2025 llevan antes una fila de letras de
                # columna ("A B C ... Q", la hoja de cálculo exportada tal cual)
                m, cuerpo = None, t
                for k, fila in enumerate(t[:3]):
                    m = _mapa(fila)
                    if m:
                        cuerpo = t[k + 1:]
                        break
                if m:
                    mapa = m
                if not mapa:
                    continue
                for f in cuerpo:
                    get = lambda k: f[mapa[k]] if k in mapa and mapa[k] < len(f) else ""
                    exp = _limpiar(get("exp"))
                    if not re.match(r"^\d{4}/", exp):          # filas de agrupación ("DIRECCIÓN GENERAL DE ...")
                        continue
                    filas.append({"uni": _limpiar(get("uni")), "exp": exp, "obj": _limpiar(get("obj")),
                                  "fig": _limpiar(get("fig")), "adj": _limpiar(get("adj")),
                                  "cif": _limpiar(get("cif")), "fec": _fecha(get("fec")), "imp": _importe(get("imp"))})
    return filas


def main():
    registros, repetidos, sin_fecha, sin_filas = {}, 0, 0, []
    anio_actual = int(time.strftime("%Y"))
    for anio in range(2021, anio_actual + 1):
        enlaces = _enlaces(anio)
        n_anio = 0
        for url in enlaces:
            leidas = _parsear(_get(url), url)
            if not leidas:
                sin_filas.append(url)
            for f in leidas:
                if not f["fec"] or f["imp"] is None:
                    sin_fecha += 1
                    continue
                if f["fec"] < MENORES_DESDE_FECHA:
                    continue
                rid = f"sevilla::{f['exp']}::{_norm(f['adj'])[:40]}"
                if rid in registros:
                    repetidos += 1
                    continue
                registros[rid] = {
                    "id":               rid,
                    "municipio":        "Sevilla",
                    "provincia":        "sevilla",
                    "fuente":           "sevilla",
                    "organisme":        f["uni"] or "Ayuntamiento de Sevilla",
                    "adjudicatari":     f["adj"] or "No localizada",
                    "nif":              f["cif"],
                    "import_num":       round(f["imp"], 2),
                    "data_adjudicacio": f["fec"],
                    "tipus_contracte":  f["fig"],
                    "descripcio":       f["obj"],
                    "codi_cpv":         "",
                    "exercici":         f["fec"][:4],
                }
                n_anio += 1
            time.sleep(0.2)
        print(f"  {anio}: {len(enlaces)} PDF, {n_anio} contratos en ventana", flush=True)
    if sin_filas:
        print(f"  !! {len(sin_filas)} PDF sin ninguna fila reconocible: {sin_filas}", flush=True)
    if len(registros) < 700:              # ~250 contratos/año publicados (955 en 5 años al conectarlo)
        raise SystemExit(f"!! Solo {len(registros)} contratos: posible fallo del origen. No se toca {FICHERO}.")
    tmp = f"{FICHERO}.tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump({
            "generado": time.strftime("%Y-%m-%d"),
            "descripcion": ("Contratos menores del Ayuntamiento de Sevilla, PDF mensuales oficiales de sevilla.org "
                            "(tabla real). Fecha real de adjudicación, CIF. Importe adjudicado SIN IVA. Ver "
                            "actualizar_contratos_menores_sevilla.py."),
            "registros": list(registros.values()),
        }, fh, ensure_ascii=False)
    os.replace(tmp, FICHERO)
    print(f"Hecho: {len(registros)} contratos ({repetidos} repetidos colapsados, {sin_fecha} filas sin fecha o sin "
          f"importe descartadas) -> {FICHERO}")


if __name__ == "__main__":
    main()
