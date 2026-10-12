# encoding: utf-8
"""Genera/amplía backend/fechas_formales_place.json.gz: la FECHA DE ADJUDICACIÓN de los contratos formales de PLACE que
ya están guardados en producción sin fecha.

Contexto (2026-10-10): el analizador de PLACE (_entry_to_contratos en app.py) nunca guardó la fecha de adjudicación,
aunque la fuente la trae (<cbc:AwardDate>). Sin fecha no se puede aplicar el alcance de 5 años ni al Índice ni a lo
que entra. Desde hoy el analizador la guarda para lo nuevo; lo ya guardado se completa con este fichero, que app.py
aplica una vez al arrancar (_aplicar_fechas_formales_place). SOLO rellena la fecha: no añade, quita ni cambia nada más.

Qué hace: recorre los ZIP mensuales de PLACE (licitacionesPerfilesContratanteCompleto3_AAAAMM.zip), de más nuevo a más
viejo, y de cada licitación que esté guardada en producción sin fecha (--cache: una copia de cache.db) apunta la
primera <cbc:AwardDate> de su versión más reciente -- la misma que guarda el analizador nuevo. Clave = idEvl de la URL
de PLACE (los contratos de una misma licitación, uno por adjudicatario, comparten fecha). No importa app.py ni
necesita la web: lee los ZIP con expresiones regulares.

Formato: {"generado", "meses": [...], "fechas": {idEvl: "AAAA-MM-DD"}}. Sin datos personales: identificadores de
licitación y fechas.

Uso (desde backend/, EN LOCAL):
    python generar_fechas_formales_place.py 202609 202109 --cache copia_de_cache.db
    python generar_fechas_formales_place.py 202609 202607 --cache copia.db --zip-local place_cache --salida prueba.json.gz

Incremental y reanudable (se guarda tras cada mes; los meses ya hechos se saltan). Descargas como
generar_backfill_nombres_place.py (una cada vez con --una-descarga)."""
import argparse
import gzip
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import zipfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
FICHERO = os.path.join(BASE_DIR, "fechas_formales_place.json.gz")
RE_IDEVL = re.compile(r"idEvl=([^&#\s\"<]+)")
RE_ENTRY = re.compile(rb"<entry>.*?</entry>", re.S)
RE_IDEVL_B = re.compile(rb"idEvl=([^&#\s\"<]+)")
RE_AWARD_B = re.compile(rb"<cbc:AwardDate>\s*(\d{4}-\d{2}-\d{2})")


def id_evl(url):
    m = RE_IDEVL.search(url or "")
    return m.group(1) if m else ""


def pendientes_de(cache):
    """(idEvl de los contratos de PLACE guardados sin fecha, nº de contratos sin fecha, nº total de PLACE)."""
    ids, sin, total = set(), 0, 0
    con = sqlite3.connect(f"file:{cache}?mode=ro", uri=True)
    for (data,) in con.execute("SELECT data FROM municipios"):
        try:
            d = json.loads(data)
        except Exception:
            continue
        for c in d.get("contratos", []):
            if c.get("fuente") != "PLACE":
                continue
            total += 1
            if not c.get("fecha"):
                sin += 1
                k = id_evl(c.get("url"))
                if k:
                    ids.add(k)
    con.close()
    return ids, sin, total


def leer(ruta):
    if os.path.exists(ruta):
        return json.loads(gzip.decompress(open(ruta, "rb").read()).decode("utf-8"))
    return {"generado": "", "meses": [], "fechas": {}}


def escribir(ruta, datos):
    contenido = json.dumps(datos, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    tmp = ruta + ".tmp"
    with open(tmp, "wb") as crudo:
        with gzip.GzipFile(filename="", mode="wb", fileobj=crudo, compresslevel=9, mtime=0) as z:
            z.write(contenido)
    os.replace(tmp, ruta)


def meses_atras(desde, hasta):
    y, m = int(desde[:4]), int(desde[4:])
    while f"{y}{m:02d}" >= hasta:
        yield f"{y}{m:02d}"
        m -= 1
        if m == 0:
            y, m = y - 1, 12


def procesar_zip(ruta, pendientes, fechas):
    """Añade a `fechas` las de las licitaciones pendientes que trae este ZIP. Devuelve (licitaciones leídas, nuevas)."""
    leidas = nuevas = 0
    with zipfile.ZipFile(ruta) as z:
        nombres = [n for n in z.namelist() if n.endswith(".atom")]
        principal = [n for n in nombres if not re.search(r"_\d{8}_\d{6}", n)]
        vistos = set()
        for nombre in principal + sorted((n for n in nombres if n not in principal), reverse=True):   # lo más nuevo primero
            raw = z.read(nombre)
            for m in RE_ENTRY.finditer(raw):
                e = m.group(0)
                mk = RE_IDEVL_B.search(e)
                if not mk:
                    continue
                k = mk.group(1).decode("ascii", "replace")
                if k in vistos:
                    continue
                vistos.add(k)
                leidas += 1
                if k not in pendientes or k in fechas:
                    continue
                mf = RE_AWARD_B.search(e)
                if mf and mf.group(1)[:4] >= b"1990":          # fechas absurdas en origen ("0026-..."): no se apuntan
                    fechas[k] = mf.group(1).decode("ascii")
                    nuevas += 1
            del raw
    return leidas, nuevas


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("desde")
    ap.add_argument("hasta")
    ap.add_argument("--cache", required=True, help="copia de cache.db de producción (de ahí salen los contratos sin fecha)")
    ap.add_argument("--salida", default=FICHERO)
    ap.add_argument("--zip-local", default="", help="directorio con place_AAAAMM.zip o formales_AAAAMM.zip ya descargados")
    ap.add_argument("--una-descarga", action="store_true", help="descargar de uno en uno (por defecto, como los otros generadores)")
    args = ap.parse_args()
    t_ini = time.time()
    pendientes, sin, total = pendientes_de(args.cache)
    print(f"contratos de PLACE guardados: {total:,}; sin fecha: {sin:,} en {len(pendientes):,} licitaciones ({time.time() - t_ini:.0f} s)", flush=True)
    datos = leer(args.salida)
    fechas = datos.setdefault("fechas", {})
    meses = [m for m in meses_atras(args.desde, args.hasta) if m not in datos["meses"]]
    print(f"{len(meses)} meses pendientes; ya apuntadas: {len(fechas):,}", flush=True)
    tmp = tempfile.mkdtemp(prefix="fechas_place_")
    for mes in meses:
        ruta, propio = "", False
        for nombre in (f"place_{mes}.zip", f"formales_{mes}.zip"):
            cand = os.path.join(args.zip_local, nombre) if args.zip_local else ""
            if cand and os.path.exists(cand) and os.path.getsize(cand) > 1_000_000:
                ruta = cand
        t0 = time.time()
        if not ruta:
            import generar_backfill_nombres_place as G
            G.DESCARGA_PLAZO_S = 7200
            ruta, estado = G.descargar(mes, os.path.join(tmp, f"place_{mes}.zip"))
            propio = True
            if not ruta or not zipfile.is_zipfile(ruta):
                print(f"{mes}: ZIP no disponible ({estado}); paro. Al relanzar continúa donde lo dejó.", flush=True)
                break
        t_desc = time.time() - t0
        t0 = time.time()
        mb = os.path.getsize(ruta) / 1048576
        leidas, nuevas = procesar_zip(ruta, pendientes, fechas)
        if propio:
            os.remove(ruta)
        datos["meses"] = sorted(set(datos["meses"]) | {mes})
        datos["generado"] = time.strftime("%Y-%m-%d")
        escribir(args.salida, datos)
        print(f"{mes}: ZIP de {mb:.0f} MB, descarga {t_desc:.0f} s, lectura {time.time() - t0:.0f} s | {leidas:,} licitaciones leídas | "
              f"+{nuevas:,} fechas | acumulado {len(fechas):,} de {len(pendientes):,} licitaciones pendientes "
              f"({100 * len(fechas) / max(1, len(pendientes)):.1f} %)", flush=True)
    con_fecha = sum(1 for k in pendientes if k in fechas)
    print(f"FIN: {con_fecha:,} de {len(pendientes):,} licitaciones pendientes con fecha ({100 * con_fecha / max(1, len(pendientes)):.1f} %); "
          f"fichero {os.path.getsize(args.salida) / 1048576:.1f} MB; {time.time() - t_ini:.0f} s", flush=True)


if __name__ == "__main__":
    main()
