# encoding: utf-8
"""
Índice local de actos inscritos del BORME (sección A) a partir de los datos abiertos del BOE
(https://www.boe.es/datosabiertos/ -- API de sumarios + versión en texto de cada documento).

Para qué: saber quién administra hoy cada sociedad adjudicataria (nombramientos y ceses del órgano de
administración), sin depender de agregadores privados. El BORME no publica el NIF de las sociedades: el cruce con los
adjudicatarios es por denominación social normalizada (única por ley en España; ver normalizar_denominacion).

Uso:
    python backend/borme_actos.py descargar --desde 2026-09-30 --hasta 2025-10-01   # de la más reciente hacia atrás
    python backend/borme_actos.py estado

Guarda en BORME_DB (por defecto backend/borme_actos.db, fuera del repositorio): una fila por (documento, anuncio)
con la sociedad, la fecha y los actos ya separados; el texto crudo comprimido para poder re-analizar sin volver a
descargar. Es reanudable: los documentos ya descargados se saltan.

Ritmo: pocas peticiones concurrentes (WORKERS) y pausa entre peticiones -- es un servicio público.
"""
import argparse
import datetime as dt
import gzip
import html as htmlmod
import json
import os
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
BORME_DB = os.environ.get("BORME_DB", os.path.join(BASE, "borme_actos.db"))
API_SUMARIO = "https://www.boe.es/datosabiertos/api/borme/sumario/{fecha}"
WORKERS = 3
PAUSA = 0.25
UA = {"User-Agent": "DineroPublico/1.0 (transparencia; contacto@dinero-publico.com)", "Accept": "application/json"}

# ── Análisis del texto ─────────────────────────────────────────────────────────────────────────────────────────
# Cabecera de cada anuncio: "435054 - PALOMA PROPERTY EXPERTS SL."
RE_ANUNCIO = re.compile(r"^(\d{1,7}) - (.+?)\.?\s*$")
# Actos (cada uno termina donde empieza el siguiente o "Datos registrales").
ACTOS = ["Nombramientos", "Ceses/Dimisiones", "Revocaciones", "Reelecciones", "Cambio de denominación social",
         "Extinción", "Disolución", "Constitución", "Datos registrales", "Otros conceptos", "Modificaciones estatutarias",
         "Cambio de domicilio social", "Ampliación de capital", "Reducción de capital", "Declaración de unipersonalidad",
         "Sociedad unipersonal", "Pérdida del caracter de unipersonalidad", "Fusión por absorción",
         "Escisión parcial", "Transformación de sociedad", "Situación concursal", "Cierre provisional",
         "Reapertura hoja registral", "Cancelaciones de oficio de nombramientos", "Desembolso de dividendos pasivos",
         "Emisión de obligaciones", "Modificación de poderes", "Ampliacion del objeto social",
         "Cambio de objeto social", "Adaptación Ley 2/95", "Adaptación Ley 44/2015", "Depósito de libros",
         "Primera inscripción", "Anotación preventiva", "Rectificación de datos", "Fe de erratas", "Empresario Individual",
         "Página web de la sociedad", "Articulo 378.5 del Reglamento del Registro Mercantil", "Acuerdo de ampliación de capital",
         "Crédito incobrable", "Suspensión de pagos", "Quiebra", "Cesión global de activo y pasivo",
         "Segregación", "Fusión", "Escisión total", "Reactivación de la sociedad", "Unipersonalidad",
         "Sucursal", "Socio único"]
RE_ACTO = re.compile(r"(?:^|(?<=\.\s))(" + "|".join(re.escape(a) for a in sorted(ACTOS, key=len, reverse=True)) + r")\.?\s*:?\s*")
# Dentro de Nombramientos/Ceses: "Adm. Unico: X. Apoderado: Y;Z." -> cargos (etiqueta corta, puede llevar puntos)
RE_CARGO = re.compile(r"([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñü\.\s/&]{0,28}?):\s*")

# Cargos del órgano de administración (lo que se muestra como "administrador"); el resto (apoderados, auditores,
# secretarios no consejeros...) se guarda pero no cuenta como administrador.
CARGOS_ADMIN = {
    "adm. unico": ("Administrador Único", 1), "adm. solid.": ("Administrador Solidario", 2),
    "adm. mancom.": ("Administrador Mancomunado", 3), "con.delegado": ("Consejero Delegado", 4),
    "cons.del.man": ("Consejero Delegado Mancomunado", 5), "cons.del.sol": ("Consejero Delegado Solidario", 5),
    "presidente": ("Presidente del Consejo", 6), "consejero": ("Consejero", 8), "liquidador": ("Liquidador", 7),
    "liquidador m": ("Liquidador Mancomunado", 7), "liq.solid.": ("Liquidador Solidario", 7),
    "adm. concursal": ("Administrador Concursal", 9),
}


def texto_de_html(h):
    """Texto plano del cuerpo del documento (la versión TEXTO del BOE)."""
    m = re.search(r'<div id="textoxslt"[^>]*>(.*?)<!-- #textoxslt -->', h, re.S)
    if not m:
        return ""
    cuerpo = m.group(1)
    cuerpo = re.sub(r"<br\s*/?>|</p>|</div>", "\n", cuerpo)
    cuerpo = htmlmod.unescape(re.sub(r"<[^>]+>", "", cuerpo))
    return "\n".join(l.strip() for l in cuerpo.split("\n") if l.strip())


def analizar(texto):
    """[(numero, sociedad, {acto: contenido})] a partir del texto de un documento BORME-A."""
    anuncios, actual = [], None
    for linea in texto.split("\n"):
        m = RE_ANUNCIO.match(linea)
        if m and m.group(2).isupper() is not False and not linea.startswith("Datos registrales"):
            actual = [int(m.group(1)), m.group(2).strip().rstrip("."), ""]
            anuncios.append(actual)
        elif actual is not None:
            actual[2] += (" " if actual[2] else "") + linea
    out = []
    for num, soc, cuerpo in anuncios:
        partes = RE_ACTO.split(re.sub(r"\s+", " ", cuerpo))
        actos = {}
        for i in range(1, len(partes) - 1, 2):
            actos.setdefault(partes[i], []).append(partes[i + 1].strip().rstrip("."))
        out.append((num, soc, {k: " | ".join(v) for k, v in actos.items()}))
    return out


RE_ETIQUETA = re.compile(r"(?:^|(?<=\.\s))([A-ZÁÉÍÓÚÑ][^:;]{0,30}?):\s*")


def cargos(contenido):
    """'Adm. Unico: X. Apoderado: Y;Z' -> [(cargo, [personas])]. Las etiquetas de cargo llevan minúsculas ("Adm. Unico",
    "Apoderado", "Con.Delegado") y los nombres van en MAYÚSCULAS: así se distingue dónde acaba una persona y empieza el
    cargo siguiente ("GOULD JUDITH LEE. Adm. Unico: ...")."""
    contenido = contenido or ""
    etiquetas = [m for m in RE_ETIQUETA.finditer(contenido) if re.search(r"[a-záéíóúñ]", m.group(1))]
    res = []
    for i, m in enumerate(etiquetas):
        fin = etiquetas[i + 1].start() if i + 1 < len(etiquetas) else len(contenido)
        bloque = contenido[m.end():fin].strip().rstrip(".")
        personas = [p.strip().rstrip(".").strip() for p in bloque.split(";") if p.strip().rstrip(".").strip()]
        res.append((m.group(1).strip(), personas))
    return res


_SUF = [(r"\bSOCIEDAD LIMITADA LABORAL\b|\bS\.?\s?L\.?\s?L\.?(?=\s|$)", "SLL"),
        (r"\bSOCIEDAD LIMITADA UNIPERSONAL\b|\bS\.?\s?L\.?\s?U\.?(?=\s|$)", "SL"),
        (r"\bSOCIEDAD ANONIMA UNIPERSONAL\b|\bS\.?\s?A\.?\s?U\.?(?=\s|$)", "SA"),
        (r"\bSOCIEDAD LIMITADA PROFESIONAL\b|\bS\.?\s?L\.?\s?P\.?(?=\s|$)", "SLP"),
        (r"\bSOCIEDAD LIMITADA NUEVA EMPRESA\b|\bS\.?\s?L\.?\s?N\.?\s?E\.?(?=\s|$)", "SLNE"),
        (r"\bSOCIEDAD LIMITADA\b|\bS\.?\s?L\.?(?=\s|$)|\bS\.?\s?R\.?\s?L\.?(?=\s|$)", "SL"),
        (r"\bSOCIEDAD ANONIMA\b|\bS\.?\s?A\.?(?=\s|$)", "SA"),
        (r"\bSOCIEDAD COOPERATIVA\b|\bS\.?\s?COOP\.?(?=\s|$)", "SCOOP"),
        (r"\bUNIPERSONAL\b", "")]


def normalizar_denominacion(nombre):
    """Denominación social comparable: mayúsculas sin tildes, sin puntuación, forma jurídica abreviada ("SOCIEDAD
    LIMITADA", "S.L.", "SL", "S.L.U." -> SL). Dos sociedades no pueden tener la misma denominación (art. 7 RRM)."""
    s = (nombre or "").upper()
    for a, b in {"Á": "A", "É": "E", "Í": "I", "Ó": "O", "Ú": "U", "Ü": "U", "À": "A", "È": "E", "Ò": "O", "Ï": "I",
                 "Ç": "C", "Ñ": "N", "·": "", "'": " ", "’": " ", "´": " "}.items():
        s = s.replace(a, b)
    s = re.sub(r"\(.*?\)", " ", s)                       # "(EN LIQUIDACION)", "(EXTINGUIDA)"...
    s = re.sub(r"\bEN LIQUIDACION\b", " ", s)
    s = re.sub(r",", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    for pat, rep in _SUF:
        s = re.sub(pat, rep, s)
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# ── Base de datos local ────────────────────────────────────────────────────────────────────────────────────────
def conectar():
    db = sqlite3.connect(BORME_DB, check_same_thread=False, timeout=60)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS documentos (
        id TEXT PRIMARY KEY, fecha TEXT, provincia TEXT, n_anuncios INTEGER, crudo BLOB)""")
    db.execute("""CREATE TABLE IF NOT EXISTS anuncios (
        doc TEXT, numero INTEGER, fecha TEXT, sociedad TEXT, soc_norm TEXT, actos TEXT,
        PRIMARY KEY (doc, numero))""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_anuncios_soc ON anuncios(soc_norm)")
    db.execute("CREATE TABLE IF NOT EXISTS dias (fecha TEXT PRIMARY KEY, n_docs INTEGER)")
    db.commit()
    return db


_lock = threading.Lock()
_FALLO = object()  # error de red o del servidor, distinto de un 404 (dia sin BORME): ese dia se reintenta


def _get(sesion, url, **kw):
    for intento in range(4):
        try:
            r = sesion.get(url, timeout=60, **kw)
            if r.status_code == 200:
                return r
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        time.sleep(3 * (intento + 1))
    return _FALLO


def descargar_doc(sesion, db, fecha, item):
    doc_id = item["identificador"]
    with _lock:
        if db.execute("SELECT 1 FROM documentos WHERE id=?", (doc_id,)).fetchone():
            return 0
    r = _get(sesion, item["url_html"])
    time.sleep(PAUSA)
    if r is None or r is _FALLO:
        return -1
    r.encoding = "utf-8"
    texto = texto_de_html(r.text)
    anuncios = analizar(texto)
    with _lock:
        db.execute("INSERT OR REPLACE INTO documentos VALUES (?,?,?,?,?)",
                   (doc_id, fecha, item.get("titulo", ""), len(anuncios), gzip.compress(texto.encode("utf-8"))))
        db.executemany("INSERT OR REPLACE INTO anuncios VALUES (?,?,?,?,?,?)",
                       [(doc_id, n, fecha, soc, normalizar_denominacion(soc), json.dumps(actos, ensure_ascii=False))
                        for n, soc, actos in anuncios])
        db.commit()
    return len(anuncios)


def descargar(desde, hasta):
    db = conectar()
    sesion = requests.Session()
    sesion.headers.update(UA)
    d = desde
    t0 = time.time()
    total_docs = total_anuncios = 0
    while d >= hasta:
        f = d.strftime("%Y%m%d")
        if d.weekday() < 5 and not db.execute("SELECT 1 FROM dias WHERE fecha=?", (f,)).fetchone():
            r = _get(sesion, API_SUMARIO.format(fecha=f))
            items = []
            if r is not None and r is not _FALLO:
                try:
                    diario = r.json()["data"]["sumario"]["diario"]
                    for dia in (diario if isinstance(diario, list) else [diario]):
                        secs = dia.get("seccion") or []
                        for sec in (secs if isinstance(secs, list) else [secs]):
                            if sec.get("codigo") == "A":
                                its = sec.get("item") or []
                                items += its if isinstance(its, list) else [its]
                except Exception:
                    items = []
            with ThreadPoolExecutor(WORKERS) as ex:
                res = list(ex.map(lambda it: descargar_doc(sesion, db, f, it), items))
            # un dia reciente sin documentos puede ser que el BORME aun no haya salido: no se da por hecho
            if r is not _FALLO and all(x >= 0 for x in res) and (items or (dt.date.today() - d).days > 3):
                db.execute("INSERT OR REPLACE INTO dias VALUES (?,?)", (f, len(items)))
                db.commit()
            total_docs += len(items)
            total_anuncios += sum(x for x in res if x > 0)
            print(f"{f}: {len(items)} docs, {sum(x for x in res if x > 0)} anuncios"
                  f"{' (fallos: ' + str(sum(1 for x in res if x < 0)) + ')' if any(x < 0 for x in res) else ''}"
                  f" | acumulado {total_docs} docs, {total_anuncios} anuncios, {time.time() - t0:.0f} s", flush=True)
        d -= dt.timedelta(days=1)


def estado():
    db = conectar()
    print("días:", db.execute("SELECT count(*), min(fecha), max(fecha) FROM dias").fetchone())
    print("documentos:", db.execute("SELECT count(*), sum(n_anuncios) FROM documentos").fetchone())
    print("sociedades distintas:", db.execute("SELECT count(DISTINCT soc_norm) FROM anuncios").fetchone()[0])
    print("tamaño:", os.path.getsize(BORME_DB) // 1024 // 1024, "MB")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("descargar")
    p.add_argument("--desde", required=True)
    p.add_argument("--hasta", required=True)
    sub.add_parser("estado")
    a = ap.parse_args()
    if a.cmd == "descargar":
        descargar(dt.date.fromisoformat(a.desde), dt.date.fromisoformat(a.hasta))
    elif a.cmd == "estado":
        estado()
    else:
        ap.print_help()
