"""Genera/amplía backend/backfill_nombres_place.json.gz: contratos formales de PLACE que el patrón anclado VIGENTE de
app.py asigna a un municipio y el patrón ANTERIOR al arreglo de nombres del 2026-09-29 no le asignaba.

Contexto (2026-09-29, auditoría de órganos contra la jerarquía oficial de PLACE, ZIP de agosto de 2026): 251 de 6.555
contratos con órgano municipal no se asignaban a su municipio -- sobre todo porque las listas de la app usan el
formato INE con el artículo al final ("Ejido, El") y PLACE escribe "Ayuntamiento de El Ejido"; también guiones
("Rivas Vaciamadrid"), "Ayuntamiento Dénia" sin "de", fórmulas honoríficas ("de la Leal Villa de El Escorial") y
"Concello Soutomaior". Resultado en producción: El Ejido, Rivas-Vaciamadrid, Dénia, El Campello, La Rinconada, La
Línea o El Puerto de Santa María con CERO contratos formales. El arreglo de _regex_anclado solo actúa sobre los ZIP
que se procesen a partir de ahora: los meses anteriores se recuperan con este script (EN LOCAL, nunca en
producción), y app.py los fusiona al arrancar (_aplicar_backfill_nombres_place, fusión aditiva).

"Patrón anterior" = el de app.py en el commit de98df9 (main antes del arreglo): se reconstruye ejecutando ese
tramo de código fuente (de `CIUDADES_AUTONOMAS = {` a `def _nombre_organismo_municipal`) leído con `git show`, así la
comparación es exacta y no una imitación a mano. Se puede fijar otro commit con --commit-anterior.

Uso (desde backend/):
    python generar_backfill_nombres_place.py 202609 202109
    python generar_backfill_nombres_place.py 202608 202608 --zip-local C:/ruta/con/zips

Incremental y reanudable (se guarda tras cada mes). Mismas cautelas que generar_backfill_ajuntament_place.py (RSS,
tiempo de escaneo, desviación de la mediana) salvo que descarga hasta DESCARGAS_PARALELAS ZIP por adelantado: a
~200 KB/s por conexión, 61 ZIP de ~160 MB uno a uno serían más de 13 horas."""
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
import subprocess
import sys
import tempfile
import threading
import time
import traceback

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "backfill_nombres_place.json.gz")
LOG_PATH = os.path.join(tempfile.gettempdir(), "backfill_nombres_place.log")
_log_fh = open(LOG_PATH, "a", encoding="utf-8")


def log(msg):
    _log_fh.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    _log_fh.flush()


PLACE_ZIP_URL = ("https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_643/"
                 "licitacionesPerfilesContratanteCompleto3_{m}.zip")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36"}
LIM_RSS_MB = 3000
LIM_ESCANEO_S = 600
DESCARGA_INTENTOS = 4
DESCARGA_PLAZO_S = 2400
DESCARGAS_PARALELAS = 3
MES_MINIMO = "202109"
COMMIT_ANTERIOR = "de98df9"   # último commit de main antes del arreglo de nombres


def meses_atras(desde, hasta):
    y, m = int(desde[:4]), int(desde[4:])
    while f"{y}{m:02d}" >= hasta:
        yield f"{y}{m:02d}"
        m -= 1
        if m == 0:
            y, m = y - 1, 12


def clave(c):
    return c.get("url") or c.get("titulo", "")[:80]


def leer(ruta):
    if os.path.exists(ruta):
        return json.loads(gzip.decompress(open(ruta, "rb").read()).decode("utf-8"))
    return {"generado": "", "meses": [], "municipios": {}}


def escribir(ruta, datos):
    contenido = json.dumps(datos, ensure_ascii=False, sort_keys=True).encode("utf-8")
    with open(ruta, "wb") as crudo:
        with gzip.GzipFile(filename="", mode="wb", fileobj=crudo, compresslevel=9, mtime=0) as z:
            z.write(contenido)


_SESION = requests.Session()
_SESION.trust_env = False     # ignora HTTP(S)_PROXY: el proxy "muerto" es solo para el hilo de enriquecimiento de app.py


def descargar(mes, destino):
    """Devuelve (ruta, 200) o (None, estado)."""
    for intento in range(1, DESCARGA_INTENTOS + 1):
        t_ini = time.time()
        try:
            r = _SESION.get(PLACE_ZIP_URL.format(m=mes), headers=HEADERS, stream=True, timeout=(15, 60))
            if r.status_code != 200:
                return None, r.status_code
            with open(destino, "wb") as f:
                for trozo in r.iter_content(1 << 20):
                    f.write(trozo)
                    if time.time() - t_ini > DESCARGA_PLAZO_S:
                        raise requests.exceptions.Timeout(f"plazo total de {DESCARGA_PLAZO_S}s superado")
            log(f"{mes}: descargado ({os.path.getsize(destino) >> 20} MB, {time.time() - t_ini:.0f} s)")
            return destino, 200
        except requests.exceptions.RequestException as e:
            log(f"{mes}: descarga cortada (intento {intento}/{DESCARGA_INTENTOS}, {time.time() - t_ini:.0f}s): "
                f"{type(e).__name__}")
            time.sleep(15 * intento)
    return None, "sin descarga"


def regex_anterior(A, commit):
    """_regex_anclado tal como estaba en `commit`, ejecutado sobre los datos (listas de municipios) de este app.py."""
    fuente = subprocess.run(["git", "show", f"{commit}:backend/app.py"], cwd=BASE_DIR, capture_output=True,
                            check=True).stdout.decode("utf-8")
    ini = fuente.index("CIUDADES_AUTONOMAS = {")
    fin = fuente.index("def _nombre_organismo_municipal")
    ns = dict(vars(A))
    exec(compile(fuente[ini:fin], f"{commit}:app.py", "exec"), ns)
    return ns["_regex_anclado"], ns["_CP_ESPERADO_ANCLAJE"]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("desde")
    ap.add_argument("hasta")
    ap.add_argument("--salida", default=FICHERO)
    ap.add_argument("--zip-local", default="", help="directorio con place_AAAAMM.zip o formales_AAAAMM.zip ya descargados")
    ap.add_argument("--commit-anterior", default=COMMIT_ANTERIOR)
    args = ap.parse_args()
    if args.hasta < MES_MINIMO:
        args.hasta = MES_MINIMO
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

    tmp = tempfile.mkdtemp(prefix="backfill_nombres_")
    sqlite3.connect(os.path.join(tmp, "cache.db")).close()
    os.environ["DATA_DIR"] = tmp
    sys.path.insert(0, BASE_DIR)
    sys.argv = [sys.argv[0]]
    # Sin red para app.py (su hilo de enriquecimiento consultaría webs externas): proxy inexistente en el entorno
    # durante TODO el proceso; las descargas de este script usan _SESION, que lo ignora (trust_env=False).
    os.environ["HTTP_PROXY"] = os.environ["HTTPS_PROXY"] = "http://127.0.0.1:9"
    sys.stdout = sys.stderr = open(os.devnull, "w")
    import app as A
    log("app.py importado.")

    rx_ant_f, cp_ant = regex_anterior(A, args.commit_anterior)
    objetivo = [(p, m) for p, lst in A.MUNICIPIOS_POR_PROVINCIA.items() if p != "murcia" for m in lst]
    idx = collections.defaultdict(list)
    for p, m in objetivo:
        n = A.normalizar(m)
        for v in A._variantes_nombre_municipio(n):
            palabras = re.findall(r"[a-z0-9]+", v)
            k = max(palabras, key=len) if palabras else v
            if (p, m) not in idx[k]:
                idx[k].append((p, m))
    rx_nuevo, rx_viejo = {}, {}

    datos = leer(args.salida)
    vistos = {(m, clave(c)) for m, v in datos["municipios"].items() for c in v["contratos"]}
    meses = [m for m in meses_atras(args.desde, args.hasta) if m not in datos["meses"]]
    log(f"{len(meses)} meses pendientes: {meses[:3]}...{meses[-3:]}")

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
    hilos = [threading.Thread(target=trabajador, daemon=True) for _ in range(DESCARGAS_PARALELAS)]
    for h in hilos:
        h.start()

    tiempos, rams = [], []
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
            anadidos = collections.Counter()
            for c in todos:
                on = A.normalizar(c.get("organo", ""))
                toks = set(re.findall(r"[a-z0-9]+", on)) | set(re.findall(r"[a-z0-9]+", on.replace("-", "")))
                for t in toks:
                    for p, m in idx.get(t, ()):
                        if (p, m) not in rx_nuevo:
                            rx_nuevo[(p, m)] = A._regex_anclado(m)
                            rx_viejo[(p, m)] = rx_ant_f(m)
                        if not rx_nuevo[(p, m)].search(on):
                            continue
                        cpn = A._cp_esperado_anclaje(m)
                        if cpn and not c.get("cp", "").startswith(cpn):
                            continue
                        if A._cp_de_otra_provincia(c, m):
                            continue                     # CP de otra provincia (Sant Joan <- Sant Joan d'Alacant)
                        cpv = cp_ant.get(A.normalizar(m))
                        if rx_viejo[(p, m)].search(on) and not (cpv and not c.get("cp", "").startswith(cpv)):
                            continue                     # ya lo asignaba el patrón anterior
                        k = (m, clave(c))
                        if k in vistos:
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
            datos["meses"] = sorted(set(datos["meses"]) | {mes})
            datos["generado"] = time.strftime("%Y-%m-%d")
            escribir(args.salida, datos)
            rss = pico[0] - base
            log(f"{mes}: escaneo {t_scan:.0f} s | RSS +{rss:.0f} MB (pico {pico[0]:.0f}) | {n_zip} contratos en el ZIP | "
                f"+{sum(anadidos.values())} nuevos en {len(anadidos)} municipios | top {anadidos.most_common(6)}")
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
    tot = sum(len(v["contratos"]) for v in datos["municipios"].values())
    log(f"FIN {args.salida}: {tot} contratos en {len(datos['municipios'])} municipios; "
        f"meses {datos['meses'][0] if datos['meses'] else '-'}..{datos['meses'][-1] if datos['meses'] else '-'}")
    os._exit(0)


if __name__ == "__main__":
    main()
