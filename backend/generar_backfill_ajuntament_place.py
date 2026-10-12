"""Genera/amplia backend/backfill_ajuntament_place.json.gz (backfill de contratos formales de PLACE de
municipios de Comunitat Valenciana / Illes Balears que publican como "Ajuntament de X").

Contexto (2026-10-01, verificación de cobertura de contratos formales por comunidad autónoma, misma clase de
bug que Galicia -- ver generar_backfill_galicia_place.py y _es_municipio_ajuntament en app.py): antes del fix
de _regex_anclado, los contratos cuyo órgano decía "Ajuntament de X" (en vez de "Ayuntamiento de X") no se
asignaban al municipio. Medido con los 4 meses más recientes ya en caché local (jun-sep 2026): 357 contratos
nuevos en 14 municipios, incluida Valencia capital (+141) -- confirma que el fix también hace falta hacia
atrás. El fix solo actúa sobre los ZIP que se procesen a partir de ahora, así que los meses anteriores hay que
recuperarlos: este script descarga los ZIP mensuales de PLACE UNO A UNO (nunca en producción, siempre en
local), y guarda solo los contratos que el patrón NUEVO asigna a un municipio de Alicante/Castellón/Valencia/
Baleares y el ANTIGUO no. app.py los fusiona al arrancar (_aplicar_backfill_ajuntament_place, fusión aditiva:
no pisa lo ya guardado).

Uso (desde backend/):
    python generar_backfill_ajuntament_place.py 202609 202512          # del mas reciente al mas antiguo, inclusive
    python generar_backfill_ajuntament_place.py 202511 202506 --salida otro.json.gz

Es INCREMENTAL: lee el fichero de salida si ya existe y le anade los meses pedidos (un contrato ya presente no se
sustituye: gana el de un mes mas reciente, que es el estado mas avanzado del expediente). Se puede repetir sin miedo.

Cautelas (la lección de A Coruña, ver generar_backfill_galicia_place.py): un ZIP cada vez, el ZIP se borra al
terminar, se mide tiempo y RSS por mes y el proceso se PARA si un mes tarda mas de LIM_ESCANEO_S, si el RSS
supera LIM_RSS_MB o si se desvia mucho de la mediana de los meses ya procesados.

`import app` arranca en segundo plano el enriquecimiento de directivos sobre el cache.db de DATA_DIR: aqui se apunta
DATA_DIR a un directorio temporal con un SQLite vacio para no tocar el cache.db local (ni hacer peticiones de red).
Prácticamente idéntico a generar_backfill_galicia_place.py salvo la lista de municipios objetivo y los nombres de
fichero/función -- ver ese script para más detalle de cada cautela."""
import argparse
import gzip
import json
import os
import shutil
import sqlite3
import statistics
import sys
import tempfile
import threading
import time
import traceback

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "backfill_ajuntament_place.json.gz")
# `import app` carga ~25 ficheros de menores y arranca un hilo de enriquecimiento de directivos (decenas de miles
# de "[n/N] ... No localizado" contra el Registro Mercantil) que comparte stdout y ahoga cualquier otra cosa que se
# imprima -- encontrado en vivo (2026-10-01) tras varios minutos sin ver progreso real. Por eso el propio progreso
# de este script se escribe a un fichero de log aparte (nunca a stdout) y, justo antes de `import app`, stdout/
# stderr del proceso se redirigen a devnull para siempre (el hilo de enriquecimiento sigue vivo de fondo, pero ya
# no escribe a ningun sitio visible).
LOG_PATH = os.path.join(tempfile.gettempdir(), "backfill_ajuntament_place.log")
_log_fh = open(LOG_PATH, "a", encoding="utf-8")


def log(msg):
    linea = f"[{time.strftime('%H:%M:%S')}] {msg}"
    _log_fh.write(linea + "\n")
    _log_fh.flush()
PLACE_ZIP_URL = ("https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_643/"
                 "licitacionesPerfilesContratanteCompleto3_{m}.zip")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36"}
LIM_RSS_MB = 2500
# Medido en vivo (2026-10-01): el escaneo real (no la descarga) de un ZIP grande puede legítimamente superar
# los 180 s iniciales (238 s en un mes concreto, sin que RSS ni tiempo se desviaran del resto) -- 180 s resultó
# un guardarraiel demasiado ajustado para el tamaño real de estos ZIP, no una señal de problema. Subido a 400 s;
# la comprobación de desviación respecto a la mediana (más abajo) sigue vigente como red de seguridad real.
LIM_ESCANEO_S = 400
DESCARGA_INTENTOS = 3
# Medido en vivo (2026-10-01): ~200 KB/s reales desde este entorno hacia PLACE -- un ZIP mensual de 150-250 MB
# tarda 13-21 min solo en descargar. El plazo tiene que acomodar eso; 150s (valor inicial, ingenuo) abortaba
# descargas que iban bien pero eran lentas, no atascadas.
DESCARGA_PLAZO_S = 1800   # plazo de reloj total por intento (protege contra un goteo lento que nunca corta la conexion)
# Alcance del proyecto (decision de Cesar, 2026-09-25): solo contratos de los ULTIMOS 5 ANOS = desde septiembre de 2021
# (a esa fecha). El generador no baja de aqui aunque se le pida; si pasa el tiempo se sube el suelo a mano.
from alcance import alcance_mes
MES_MINIMO = alcance_mes()             # primer mes de la ventana móvil de 5 años (alcance.py)


def meses_atras(desde, hasta):
    y, m = int(desde[:4]), int(desde[4:])
    while f"{y}{m:02d}" >= hasta:
        yield f"{y}{m:02d}"
        m -= 1
        if m == 0:
            y, m = y - 1, 12


def clave(c):
    return c.get("url") or c.get("titulo", "")[:80]     # la misma que _fusionar_historico_contratos


def leer(ruta):
    if os.path.exists(ruta):
        return json.loads(gzip.decompress(open(ruta, "rb").read()).decode("utf-8"))
    return {"generado": "", "meses": [], "municipios": {}}


def escribir(ruta, datos):
    """Escritura determinista (mtime=0, claves ordenadas): mismos datos -> mismo fichero -> mismo hash en app.py."""
    contenido = json.dumps(datos, ensure_ascii=False, sort_keys=True).encode("utf-8")
    with open(ruta, "wb") as crudo:
        with gzip.GzipFile(filename="", mode="wb", fileobj=crudo, compresslevel=9, mtime=0) as z:
            z.write(contenido)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("desde", help="mes mas reciente, AAAAMM")
    ap.add_argument("hasta", help="mes mas antiguo, AAAAMM")
    ap.add_argument("--salida", default=FICHERO)
    ap.add_argument("--zip-local", default="", help="directorio con place_AAAAMM.zip ya descargados (se reutilizan y NO se borran)")
    args = ap.parse_args()
    if args.hasta < MES_MINIMO:
        log(f"'hasta' {args.hasta} queda fuera del alcance de 5 anos: se usa {MES_MINIMO}.")
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

    tmp = tempfile.mkdtemp(prefix="backfill_ajuntament_")
    sqlite3.connect(os.path.join(tmp, "cache.db")).close()       # SQLite vacio: app.py no espera 60 s a que aparezca el disco
    os.environ["DATA_DIR"] = tmp
    sys.path.insert(0, BASE_DIR)
    sys.argv = [sys.argv[0]]
    log("importando app.py (carga ~25 ficheros de menores + arranca el hilo de enriquecimiento)...")
    # sys.stdout/stderr son atributos GLOBALES del modulo sys (no por hilo): restaurarlos tras el import
    # tambien "desmutearia" el hilo de enriquecimiento que sigue vivo de fondo (print() mira sys.stdout en
    # cada llamada, no guarda una referencia al arrancar el hilo) -- por eso se quedan en devnull para
    # SIEMPRE, y log() escribe a su propio fichero en vez de pasar por sys.stdout.
    sys.stdout = sys.stderr = open(os.devnull, "w")
    import app as A
    log("app.py importado.")

    A._es_municipio_ajuntament("x")                               # inicializa A._MUNICIPIOS_AJUNTAMENT_NORM
    nuevas = set(A._MUNICIPIOS_AJUNTAMENT_NORM)
    objetivo = [(m, prov) for prov, lst in (("alicante", A.MUNICIPIOS_ALICANTE), ("castellon", A.MUNICIPIOS_CASTELLON),
                                            ("valencia", A.MUNICIPIOS_VALENCIA), ("baleares", A.MUNICIPIOS_BALEARES))
                for m in lst]
    rx_nuevo, rx_viejo = {}, {}
    for m, _p in objetivo:
        A._MUNICIPIOS_AJUNTAMENT_NORM = nuevas
        rx_nuevo[m] = A._regex_anclado(m)
        A._MUNICIPIOS_AJUNTAMENT_NORM = set()
        rx_viejo[m] = A._regex_anclado(m)                         # el patron de antes del fix
    A._MUNICIPIOS_AJUNTAMENT_NORM = nuevas

    datos = leer(args.salida)
    vistos = {(m, clave(c)) for m, v in datos["municipios"].items() for c in v["contratos"]}
    tiempos, rams = [], []
    try:
        for mes in meses_atras(args.desde, args.hasta):
            base = proc.memory_info().rss / 1048576
            pico[0] = base
            ruta = os.path.join(args.zip_local, f"place_{mes}.zip") if args.zip_local else ""
            propio = False
            t0 = time.time()
            if not (ruta and os.path.exists(ruta) and os.path.getsize(ruta) > 1_000_000):
                ruta, propio = os.path.join(tmp, f"place_{mes}.zip"), True
                # PLACE corta a veces la conexion a mitad de un ZIP de ~200 MB: se reintenta desde cero hasta 4
                # veces antes de rendirse. Un 404 no se reintenta. El timeout de requests solo cuenta el hueco
                # ENTRE trozos, asi que un servidor que gotea muy despacio sin cortar nunca podria alargar la
                # descarga indefinidamente sin violar ese timeout -- por eso ademas hay un plazo de reloj total
                # (DESCARGA_PLAZO_S) comprobado en cada trozo recibido.
                estado = None
                for intento in range(1, DESCARGA_INTENTOS + 1):
                    t_ini = time.time()
                    try:
                        r = requests.get(PLACE_ZIP_URL.format(m=mes), headers=HEADERS, stream=True, timeout=(15, 45))
                        if r.status_code != 200:
                            estado = r.status_code
                            break
                        with open(ruta, "wb") as f:
                            for trozo in r.iter_content(1 << 20):
                                f.write(trozo)
                                if time.time() - t_ini > DESCARGA_PLAZO_S:
                                    raise requests.exceptions.Timeout(f"plazo total de {DESCARGA_PLAZO_S}s superado")
                        estado = 200
                        break
                    except requests.exceptions.RequestException as e:
                        log(f"{mes}: descarga cortada (intento {intento}/{DESCARGA_INTENTOS}, "
                            f"{time.time()-t_ini:.0f}s): {type(e).__name__}")
                        time.sleep(10 * intento)
                if estado != 200:
                    log(f"{mes}: ZIP no disponible (HTTP {estado}); paro.")
                    break
            t_desc = time.time() - t0
            t0 = time.time()
            todos = A._extraer_contratos_zip(ruta)
            t_scan = time.time() - t0
            orgs = [A.normalizar(c.get("organo", "")) for c in todos]
            anadidos = 0
            for m, prov in objetivo:
                cp = A._CP_ESPERADO_ANCLAJE.get(A.normalizar(m))
                for c, o in zip(todos, orgs):
                    if rx_nuevo[m].search(o) and not rx_viejo[m].search(o):
                        if cp and not c.get("cp", "").startswith(cp):
                            continue
                        k = (m, clave(c))
                        if k in vistos:
                            continue
                        vistos.add(k)
                        datos["municipios"].setdefault(m, {"provincia": prov, "contratos": []})["contratos"].append(dict(c))
                        anadidos += 1
            n_zip = len(todos)
            del todos, orgs
            if propio:
                os.remove(ruta)
            if mes not in datos["meses"]:
                datos["meses"] = sorted(datos["meses"] + [mes])
            datos["generado"] = time.strftime("%Y-%m-%d")
            escribir(args.salida, datos)                           # se guarda tras CADA mes: parar no pierde nada
            rss = pico[0] - base
            log(f"{mes}: descarga {t_desc:.0f} s | escaneo {t_scan:.0f} s | RSS +{rss:.0f} MB (pico {pico[0]:.0f}) | "
                f"{n_zip} contratos en el ZIP | +{anadidos} nuevos")
            if t_scan > LIM_ESCANEO_S:
                log(f"!!! {mes}: escaneo de {t_scan:.0f} s > {LIM_ESCANEO_S} s. Paro para revisar.")
                break
            if len(tiempos) >= 3 and (t_scan > 2.5 * max(statistics.median(tiempos), 5)
                                      or rss > 2.0 * max(statistics.median(rams), 100)):
                log(f"!!! {mes}: se desvia de la mediana ({t_scan:.0f} s, +{rss:.0f} MB). Paro para revisar.")
                break
            tiempos.append(t_scan)
            rams.append(rss)
    except Exception:
        log("!!! EXCEPCION no esperada, paro:\n" + traceback.format_exc())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    tot = sum(len(v["contratos"]) for v in datos["municipios"].values())
    log(f"{args.salida}: {tot} contratos en {len(datos['municipios'])} municipios; meses {datos['meses'][0]}..{datos['meses'][-1]}")
    os._exit(0)                                                    # el enriquecimiento de app.py deja hilos vivos


if __name__ == "__main__":
    main()
