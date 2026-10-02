"""Genera backend/backfill_formales_place/AAAAMM.json.gz: TODOS los contratos formales de PLACE que el patrón anclado
vigente de app.py asigna a un municipio, mes a mes, hacia atrás hasta septiembre de 2021.

Contexto (2026-10-02, diagnóstico de cobertura por comunidad, ver DIAGNOSTICO_COBERTURA_CCAA.md): las comunidades con
fuente regional (Cataluña/PSCP, País Vasco/Euskadi, Navarra) y Murcia tienen el histórico de 5 años de contratos
formales (4-7 por 1.000 habitantes); el resto solo tiene lo que traían los ZIP mensuales de PLACE procesados desde que
se conectó cada provincia (0,25-1,6 por 1.000). Este script recupera los meses anteriores EN LOCAL (nunca en
producción). A diferencia de generar_backfill_nombres_place.py (del que hereda el bucle y las cautelas), no compara
con un patrón anterior: guarda todo lo que el patrón vigente asigna.

Un fichero por mes (como el feed de menores de PLACE) en vez de uno solo: el volumen es de otro orden y reescribir un
único .json.gz tras cada mes no escala. Un contrato que ya salió en un mes más reciente no se repite en uno más
antiguo (gana el estado más avanzado del expediente): por eso se procesa SIEMPRE del más reciente al más antiguo y
los meses ya generados se releen al arrancar para reconstruir las claves vistas.

Uso (desde backend/):
    python generar_backfill_formales_place.py 202609 202109
    python generar_backfill_formales_place.py 202608 202608 --zip-local place_cache --salida C:/otra/carpeta

Fuera del objetivo: Murcia (patrón propio sin anclar e histórico ya completo) y las provincias con fuente regional.
Progreso en %TEMP%/backfill_formales_place.log (stdout queda mudo por `import app`)."""
import argparse
import collections
import gzip
import json
import os
import queue
import re
import shutil
import sqlite3
import statistics
import sys
import tempfile
import threading
import time
import traceback

from generar_backfill_nombres_place import (DESCARGAS_PARALELAS, LIM_ESCANEO_S, LIM_RSS_MB, MES_MINIMO, clave,
                                            descargar, meses_atras)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CARPETA = os.path.join(BASE_DIR, "backfill_formales_place")
LOG_PATH = os.path.join(tempfile.gettempdir(), "backfill_formales_place.log")
_log_fh = open(LOG_PATH, "a", encoding="utf-8")


def log(msg):
    _log_fh.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    _log_fh.flush()


def ruta_mes(carpeta, mes):
    return os.path.join(carpeta, f"{mes}.json.gz")


def leer_mes(carpeta, mes):
    return json.loads(gzip.decompress(open(ruta_mes(carpeta, mes), "rb").read()).decode("utf-8"))


def escribir_mes(carpeta, mes, datos):
    """Escritura determinista (mtime=0, claves ordenadas): mismos datos -> mismo fichero."""
    contenido = json.dumps(datos, ensure_ascii=False, sort_keys=True).encode("utf-8")
    tmp = ruta_mes(carpeta, mes) + ".tmp"
    with open(tmp, "wb") as crudo:
        with gzip.GzipFile(filename="", mode="wb", fileobj=crudo, compresslevel=9, mtime=0) as z:
            z.write(contenido)
    os.replace(tmp, ruta_mes(carpeta, mes))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("desde", help="mes mas reciente, AAAAMM")
    ap.add_argument("hasta", help="mes mas antiguo, AAAAMM")
    ap.add_argument("--salida", default=CARPETA, help="carpeta de salida (un AAAAMM.json.gz por mes)")
    ap.add_argument("--zip-local", default="", help="directorio con place_AAAAMM.zip ya descargados (no se borran)")
    args = ap.parse_args()
    if args.hasta < MES_MINIMO:
        args.hasta = MES_MINIMO
    os.makedirs(args.salida, exist_ok=True)
    log(f"=== arranque: {args.desde} -> {args.hasta}, salida={args.salida} ===")

    import psutil
    proc = psutil.Process()
    pico = [proc.memory_info().rss / 1048576]

    def vigilar():
        while True:
            r = proc.memory_info().rss / 1048576
            pico[0] = max(pico[0], r)
            if r > LIM_RSS_MB:
                log(f"!!! RSS {r:.0f} MB > {LIM_RSS_MB} MB: aborto")
                os._exit(3)
            time.sleep(0.25)
    threading.Thread(target=vigilar, daemon=True).start()

    tmp = tempfile.mkdtemp(prefix="backfill_formales_")
    sqlite3.connect(os.path.join(tmp, "cache.db")).close()
    # marcadores ya puestos (como depurar_formales_5anios.py): app.py no siembra desde el cache.db real
    for marcador in (".disco_inicializado", "recuperacion_historico_20260722.marker"):
        open(os.path.join(tmp, marcador), "w").write("x")
    os.environ["DATA_DIR"] = tmp
    sys.path.insert(0, BASE_DIR)
    sys.argv = [sys.argv[0]]
    # Sin red para app.py (su hilo de enriquecimiento consultaría webs externas): proxy inexistente durante TODO el
    # proceso; las descargas usan la sesión de generar_backfill_nombres_place, que lo ignora (trust_env=False).
    os.environ["HTTP_PROXY"] = os.environ["HTTPS_PROXY"] = "http://127.0.0.1:9"
    sys.stdout = sys.stderr = open(os.devnull, "w")
    import app as A
    log("app.py importado.")

    fuera = {"murcia"} | set(A.PROVINCIAS_CATALUNYA) | set(A.PROVINCIAS_PAIS_VASCO) | set(A.PROVINCIAS_NAVARRA)
    objetivo = [(p, m) for p, lst in A.MUNICIPIOS_POR_PROVINCIA.items() if p not in fuera for m in lst]
    log(f"{len(objetivo)} municipios objetivo; fuera: {sorted(fuera)}")
    idx = collections.defaultdict(list)
    for p, m in objetivo:
        for v in A._variantes_nombre_municipio(A.normalizar(m)):
            palabras = re.findall(r"[a-z0-9]+", v)
            k = max(palabras, key=len) if palabras else v
            if (p, m) not in idx[k]:
                idx[k].append((p, m))
    rx = {}

    todos_meses = list(meses_atras(args.desde, args.hasta))
    hechos = [m for m in todos_meses if os.path.exists(ruta_mes(args.salida, m))]
    # Claves ya vistas: las de CUALQUIER mes ya generado en la carpeta (también fuera del rango pedido).
    vistos = set()
    for f in sorted(os.listdir(args.salida)):
        if re.fullmatch(r"\d{6}\.json\.gz", f):
            for m, v in leer_mes(args.salida, f[:6])["municipios"].items():
                vistos.update((v["provincia"], m, clave(c)) for c in v["contratos"])
    meses = [m for m in todos_meses if m not in hechos]
    log(f"{len(hechos)} meses ya hechos ({len(vistos)} contratos vistos); {len(meses)} pendientes: "
        f"{meses[:3]}...{meses[-3:]}")

    # descargas por adelantado: como mucho DESCARGAS_PARALELAS ZIP descargándose o esperando en disco a la vez
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
            cand = os.path.join(args.zip_local, f"place_{mes}.zip") if args.zip_local else ""
            if cand and os.path.exists(cand) and os.path.getsize(cand) > 1_000_000:
                res = (cand, False, 200)
            else:
                r, estado = descargar(mes, os.path.join(tmp, f"place_{mes}.zip"))
                res = (r, True, estado)
            with cond:
                listos[mes] = res
                cond.notify_all()
    for _ in range(DESCARGAS_PARALELAS):
        threading.Thread(target=trabajador, daemon=True).start()

    tiempos, rams = [], []
    total = 0
    try:
        for mes in meses:
            with cond:
                cond.wait_for(lambda: mes in listos)
                ruta, propio, estado = listos[mes]
            if not ruta:
                log(f"{mes}: ZIP no disponible ({estado}); paro.")
                break
            base = proc.memory_info().rss / 1048576
            pico[0] = base
            t0 = time.time()
            todos = A._extraer_contratos_zip(ruta)
            datos = {"mes": mes, "generado": time.strftime("%Y-%m-%d"), "municipios": {}}
            anadidos = collections.Counter()
            repetidos = 0
            for c in todos:
                on = A.normalizar(c.get("organo", ""))
                toks = set(re.findall(r"[a-z0-9]+", on)) | set(re.findall(r"[a-z0-9]+", on.replace("-", "")))
                for t in toks:
                    for p, m in idx.get(t, ()):
                        if (p, m) not in rx:
                            rx[(p, m)] = A._regex_anclado(m)
                        if not rx[(p, m)].search(on):
                            continue
                        cpn = A._cp_esperado_anclaje(m)
                        if cpn and not c.get("cp", "").startswith(cpn):
                            continue
                        if A._cp_de_otra_provincia(c, m, p):
                            continue                     # mismas tres condiciones que buscar_en_zip (anclar=True)
                        k = (p, m, clave(c))
                        if k in vistos:
                            repetidos += 1
                            continue
                        vistos.add(k)
                        datos["municipios"].setdefault(m, {"provincia": p, "contratos": []})["contratos"].append(dict(c))
                        anadidos[m] += 1
            t_scan = time.time() - t0
            n_zip = len(todos)
            del todos
            if propio:
                os.remove(ruta)
            huecos.release()
            escribir_mes(args.salida, mes, datos)
            total += sum(anadidos.values())
            rss = pico[0] - base
            log(f"{mes}: escaneo {t_scan:.0f} s | RSS +{rss:.0f} MB (pico {pico[0]:.0f}) | {n_zip} contratos en el ZIP | "
                f"+{sum(anadidos.values())} nuevos en {len(anadidos)} municipios ({repetidos} ya vistos) | "
                f"{os.path.getsize(ruta_mes(args.salida, mes)) >> 10} KB | top {anadidos.most_common(6)}")
            del datos
            if t_scan > LIM_ESCANEO_S:
                log(f"!!! {mes}: escaneo de {t_scan:.0f} s > {LIM_ESCANEO_S} s. Paro para revisar.")
                break
            if len(tiempos) >= 3 and (t_scan > 2.5 * max(statistics.median(tiempos), 5)
                                      or rss > 2.0 * max(statistics.median(rams), 150)):
                log(f"!!! {mes}: se desvia de la mediana ({t_scan:.0f} s, +{rss:.0f} MB). Paro para revisar.")
                break
            tiempos.append(t_scan)
            rams.append(rss)
    except Exception:
        log("!!! EXCEPCION no esperada, paro:\n" + traceback.format_exc())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    log(f"FIN {args.salida}: +{total} contratos en esta ejecucion; {len(vistos)} en total")
    os._exit(0)


if __name__ == "__main__":
    main()
