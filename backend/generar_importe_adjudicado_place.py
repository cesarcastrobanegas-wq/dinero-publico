"""Genera/amplía backend/importe_adjudicado_place.json.gz: lo ADJUDICADO por lote y adjudicatario de cada licitación
de PLACE asignable a un municipio, para corregir el histórico ya guardado en producción.

Contexto (2026-10-01, ver _adjudicaciones_place en app.py): hasta hoy el importe de los contratos formales de PLACE era
el "Importe" del <summary>, es decir el PRESUPUESTO base de toda la licitación, y con varios adjudicatarios se
atribuía entero al primero. El parser nuevo (_entry_to_contratos) ya lee lo adjudicado lote a lote, pero solo para los
ZIP que se procesen a partir de ahora; lo ya guardado se corrige con este fichero, que app.py aplica una vez al
arrancar (_aplicar_importe_adjudicado_place).

Qué entra: toda licitación ADJ/RES/FOR cuyo órgano casa con el patrón anclado de algún municipio (_regex_anclado, sin
exigir CP: aquí sobra incluir de más, el arranque solo toca lo que ya esté guardado) o cuya URL ya esté en
--urls-extra (copia de producción, backfills). Clave = idEvl de la URL de PLACE. Por licitación se guarda la versión
más reciente: meses de más nuevo a más viejo y, dentro de cada ZIP, el .atom principal (el más nuevo) y después los
fechados de más nuevo a más viejo.

Formato: {"generado", "meses": [...], "lic": {idEvl: [presupuesto, tipo, [[empresa, nif, importe_num, lotes|null,
resultado_code], ...]]}} con tipo "adjudicado" (un registro por adjudicatario) o "presupuesto" (lo adjudicado no es
fiable: queda un solo registro, el primer adjudicatario, con el presupuesto).

Uso (desde backend/, EN LOCAL):
    python generar_importe_adjudicado_place.py 202609 202109 --urls-extra cache_real_prod_20260925.db
    python generar_importe_adjudicado_place.py 202608 202608 --zip-local place_cache

Incremental y reanudable (se guarda tras cada mes); descargas como generar_backfill_nombres_place.py."""
import argparse
import collections
import gzip
import json
import os
import queue
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import traceback
import zipfile

from generar_backfill_nombres_place import descargar, escribir, leer, log, meses_atras, DESCARGAS_PARALELAS, MES_MINIMO
import generar_backfill_nombres_place as _gbn

_gbn.DESCARGA_PLAZO_S = 7200   # a ~90 KB/s un ZIP de 160 MB tarda ~30 min: los 40 min del otro generador no bastan

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "importe_adjudicado_place.json.gz")
LIM_RSS_MB = 3000
RE_IDEVL = re.compile(r"idEvl=([^&#\s]+)")


def id_evl(url):
    m = RE_IDEVL.search(url or "")
    return m.group(1) if m else ""


def urls_extra(rutas):
    ids = set()
    for ruta in rutas:
        if ruta.endswith(".db"):
            con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
            for (data,) in con.execute("SELECT data FROM municipios"):
                try:
                    d = json.loads(data)
                except Exception:
                    continue
                ids.update(id_evl(c.get("url")) for c in d.get("contratos", []) if c.get("fuente") == "PLACE")
            con.close()
        else:
            datos = json.loads(gzip.decompress(open(ruta, "rb").read()).decode("utf-8"))
            for v in datos.get("municipios", {}).values():
                ids.update(id_evl(c.get("url")) for c in (v.get("contratos", []) if isinstance(v, dict) else v))
    ids.discard("")
    return ids


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("desde")
    ap.add_argument("hasta")
    ap.add_argument("--salida", default=FICHERO)
    ap.add_argument("--zip-local", default="", help="directorio con place_AAAAMM.zip o formales_AAAAMM.zip ya descargados")
    ap.add_argument("--urls-extra", nargs="*", default=[], help="cache.db y/o backfill_*.json.gz cuyas URL de PLACE entran siempre")
    args = ap.parse_args()
    if args.hasta < MES_MINIMO:
        args.hasta = MES_MINIMO
    log(f"=== importe adjudicado: {args.desde} -> {args.hasta}, salida={args.salida} ===")

    import psutil
    proc = psutil.Process()

    def vigilar():
        while True:
            if proc.memory_info().rss / 1048576 > LIM_RSS_MB:
                log(f"!!! RSS > {LIM_RSS_MB} MB: aborto")
                os._exit(3)
            time.sleep(0.5)
    threading.Thread(target=vigilar, daemon=True).start()

    tmp = tempfile.mkdtemp(prefix="importe_adj_")
    sqlite3.connect(os.path.join(tmp, "cache.db")).close()
    os.environ["DATA_DIR"] = tmp
    sys.path.insert(0, BASE_DIR)
    sys.argv = [sys.argv[0]]
    os.environ["HTTP_PROXY"] = os.environ["HTTPS_PROXY"] = "http://127.0.0.1:9"
    sys.stdout = sys.stderr = open(os.devnull, "w")
    import app as A
    log("app.py importado.")

    extra = urls_extra(args.urls_extra)
    log(f"{len(extra)} URL extra")
    idx = collections.defaultdict(list)
    for p, lst in A.MUNICIPIOS_POR_PROVINCIA.items():
        for m in lst:
            for v in A._variantes_nombre_municipio(A.normalizar(m)):
                palabras = re.findall(r"[a-z0-9]+", v)
                k = max(palabras, key=len) if palabras else v
                if m not in idx[k]:
                    idx[k].append(m)
    rx = {}
    cache_organo = {}

    def es_municipal(organo):
        on = A.normalizar(organo)
        if on in cache_organo:
            return cache_organo[on]
        ok = False
        toks = set(re.findall(r"[a-z0-9]+", on)) | set(re.findall(r"[a-z0-9]+", on.replace("-", "")))
        for t in toks:
            for m in idx.get(t, ()):
                if m not in rx:
                    rx[m] = A._regex_anclado(m)
                if rx[m].search(on):
                    ok = True
                    break
            if ok:
                break
        cache_organo[on] = ok
        return ok

    datos = leer(args.salida)
    datos.setdefault("lic", {})
    datos.pop("municipios", None)
    meses = [m for m in meses_atras(args.desde, args.hasta) if m not in datos["meses"]]
    log(f"{len(meses)} meses pendientes: {meses[:3]}...{meses[-3:]}")

    listos = {}
    cond = threading.Condition()
    huecos = threading.Semaphore(DESCARGAS_PARALELAS)
    cola = queue.Queue()
    for m in meses:
        cola.put(m)

    def trabajador():
        while True:
            huecos.acquire()
            try:
                mes = cola.get_nowait()
            except queue.Empty:
                huecos.release()
                return
            ruta = ""
            for nombre in (f"place_{mes}.zip", f"formales_{mes}.zip"):
                cand = os.path.join(args.zip_local, nombre) if args.zip_local else ""
                if cand and os.path.exists(cand) and os.path.getsize(cand) > 1_000_000:
                    ruta = cand
            if ruta:
                res = (ruta, False, 200)
            else:
                r, estado = descargar(mes, os.path.join(tmp, f"place_{mes}.zip"))
                res = (r, True, estado)
            with cond:
                listos[mes] = res
                cond.notify_all()
    for _ in range(DESCARGAS_PARALELAS):
        threading.Thread(target=trabajador, daemon=True).start()

    try:
        for mes in meses:
            with cond:
                cond.wait_for(lambda: mes in listos)
                ruta, propio, estado = listos[mes]
            if not ruta:
                log(f"{mes}: ZIP no disponible ({estado}); paro.")
                break
            t0 = time.time()
            with zipfile.ZipFile(ruta) as z:
                nombres = [n for n in z.namelist() if n.endswith(".atom")]
                principal = [n for n in nombres if not re.search(r"_\d{8}_\d{6}", n)]
                orden = principal + sorted((n for n in nombres if n not in principal), reverse=True)
                vistos_mes, nuevos, tipos = set(), 0, collections.Counter()
                for nombre in orden:
                    raw = z.read(nombre)
                    for entry_xml in A._entries_con_estado_todas_bytes(raw):
                        try:
                            filas = A._entry_to_contratos(entry_xml)
                        except Exception:
                            continue
                        if not filas:
                            continue
                        f0 = filas[0]
                        k = id_evl(f0.get("url"))
                        if not k or k in vistos_mes:
                            continue
                        vistos_mes.add(k)
                        if k in datos["lic"]:
                            continue                 # ya hay una versión más reciente (mes posterior)
                        if k not in extra and not es_municipal(f0.get("organo", "")):
                            continue
                        datos["lic"][k] = [f0.get("presupuesto_num", 0.0), f0.get("importe_tipo", "presupuesto"),
                                           [[f["empresa"], f["nif"], f["importe_num"], f.get("lotes"),
                                             f.get("resultado_code", "")] for f in filas]]
                        nuevos += 1
                        tipos[f0.get("importe_tipo")] += 1
                    del raw
            if propio:
                os.remove(ruta)
            huecos.release()
            datos["meses"] = sorted(set(datos["meses"]) | {mes})
            datos["generado"] = time.strftime("%Y-%m-%d")
            escribir(args.salida, datos)
            log(f"{mes}: {time.time() - t0:.0f} s | +{nuevos} licitaciones municipales {dict(tipos)} | "
                f"total {len(datos['lic'])} | RSS {proc.memory_info().rss >> 20} MB")
    except Exception:
        log("!!! EXCEPCION no esperada, paro:\n" + traceback.format_exc())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    log(f"FIN {args.salida}: {len(datos['lic'])} licitaciones; meses "
        f"{datos['meses'][0] if datos['meses'] else '-'}..{datos['meses'][-1] if datos['meses'] else '-'}")
    os._exit(0)


if __name__ == "__main__":
    main()
