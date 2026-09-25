"""Genera/amplia backend/backfill_galicia_place.json.gz (backfill de contratos formales de PLACE de municipios gallegos).

Contexto (2026-09-25): antes del fix de _regex_anclado ("Concello de X", "Concello da/do X") los contratos cuyo organo
era un Concello no se asignaban al municipio. El fix solo actua sobre los ZIP que se procesen a partir de ahora, asi que
los meses anteriores hay que recuperarlos: este script descarga los ZIP mensuales de PLACE UNO A UNO (nunca en
produccion, siempre en local), y guarda solo los contratos que el patron NUEVO asigna a un municipio gallego y el
ANTIGUO no. app.py los fusiona al arrancar (_aplicar_backfill_galicia_place, fusion aditiva: no pisa lo ya guardado).

Uso (desde backend/):
    python generar_backfill_galicia_place.py 202609 202512          # del mas reciente al mas antiguo, inclusive
    python generar_backfill_galicia_place.py 202511 202506 --salida otro.json.gz

Es INCREMENTAL: lee el fichero de salida si ya existe y le anade los meses pedidos (un contrato ya presente no se
sustituye: gana el de un mes mas reciente, que es el estado mas avanzado del expediente). Se puede repetir sin miedo.

Cautelas (la lección de A Coruña, 7,9 GB de RAM): un ZIP cada vez, el ZIP se borra al terminar, se mide tiempo y RSS por
mes y el proceso se PARA si un mes tarda mas de LIM_ESCANEO_S, si el RSS supera LIM_RSS_MB o si se desvia mucho de la
mediana de los meses ya procesados. Medido 2026-09-25 (10 meses): escaneo 10-74 s, pico 479 MB.

`import app` arranca en segundo plano el enriquecimiento de directivos sobre el cache.db de DATA_DIR: aqui se apunta
DATA_DIR a un directorio temporal con un SQLite vacio para no tocar el cache.db local (ni hacer peticiones de red)."""
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

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "backfill_galicia_place.json.gz")
PLACE_ZIP_URL = ("https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_643/"
                 "licitacionesPerfilesContratanteCompleto3_{m}.zip")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36"}
LIM_RSS_MB = 2500
LIM_ESCANEO_S = 180
DESCARGA_INTENTOS = 4
# Alcance del proyecto (decision de Cesar, 2026-09-25): solo contratos de los ULTIMOS 5 ANOS = desde septiembre de 2021
# (a esa fecha). El generador no baja de aqui aunque se le pida; si pasa el tiempo se sube el suelo a mano.
MES_MINIMO = "202109"


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
        print(f"'hasta' {args.hasta} queda fuera del alcance de 5 anos: se usa {MES_MINIMO}.", flush=True)
        args.hasta = MES_MINIMO

    import psutil
    proc = psutil.Process()
    pico = [proc.memory_info().rss / 1048576]

    def vigilar():
        while True:
            r = proc.memory_info().rss / 1048576
            pico[0] = max(pico[0], r)
            if r > LIM_RSS_MB:
                print(f"!!! RSS {r:.0f} MB > {LIM_RSS_MB} MB: aborto", flush=True)
                os._exit(3)
            time.sleep(0.25)
    threading.Thread(target=vigilar, daemon=True).start()

    tmp = tempfile.mkdtemp(prefix="backfill_place_")
    sqlite3.connect(os.path.join(tmp, "cache.db")).close()       # SQLite vacio: app.py no espera 60 s a que aparezca el disco
    os.environ["DATA_DIR"] = tmp
    sys.path.insert(0, BASE_DIR)
    sys.argv = [sys.argv[0]]
    import app as A

    A._es_municipio_gallego("x")                                  # inicializa A._MUNICIPIOS_GALICIA_NORM
    nuevas = set(A._MUNICIPIOS_GALICIA_NORM)
    gal = [(m, prov) for prov, lst in (("a_coruna", A.MUNICIPIOS_A_CORUNA), ("lugo", A.MUNICIPIOS_LUGO),
                                       ("ourense", A.MUNICIPIOS_OURENSE), ("pontevedra", A.MUNICIPIOS_PONTEVEDRA))
           for m in lst]
    rx_nuevo, rx_viejo = {}, {}
    for m, _p in gal:
        A._MUNICIPIOS_GALICIA_NORM = nuevas
        rx_nuevo[m] = A._regex_anclado(m)
        A._MUNICIPIOS_GALICIA_NORM = set()
        rx_viejo[m] = A._regex_anclado(m)                         # el patron de antes del fix
    A._MUNICIPIOS_GALICIA_NORM = nuevas

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
                # PLACE corta a veces la conexion a mitad de un ZIP de ~200 MB (visto 2026-09-25: ConnectionReset,
                # dos veces): se reintenta desde cero hasta 4 veces antes de rendirse. Un 404 no se reintenta.
                estado = None
                for intento in range(1, DESCARGA_INTENTOS + 1):
                    try:
                        r = requests.get(PLACE_ZIP_URL.format(m=mes), headers=HEADERS, stream=True, timeout=(20, 120))
                        if r.status_code != 200:
                            estado = r.status_code
                            break
                        with open(ruta, "wb") as f:
                            for trozo in r.iter_content(1 << 20):
                                f.write(trozo)
                        estado = 200
                        break
                    except requests.exceptions.RequestException as e:
                        print(f"{mes}: descarga cortada (intento {intento}/{DESCARGA_INTENTOS}): {type(e).__name__}", flush=True)
                        time.sleep(15 * intento)
                if estado != 200:
                    print(f"{mes}: ZIP no disponible (HTTP {estado}); paro.", flush=True)
                    break
            t_desc = time.time() - t0
            t0 = time.time()
            todos = A._extraer_contratos_zip(ruta)
            t_scan = time.time() - t0
            orgs = [A.normalizar(c.get("organo", "")) for c in todos]
            anadidos = 0
            for m, prov in gal:
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
            print(f"{mes}: descarga {t_desc:.0f} s | escaneo {t_scan:.0f} s | RSS +{rss:.0f} MB (pico {pico[0]:.0f}) | "
                  f"{n_zip} contratos en el ZIP | +{anadidos} nuevos", flush=True)
            if t_scan > LIM_ESCANEO_S:
                print(f"!!! {mes}: escaneo de {t_scan:.0f} s > {LIM_ESCANEO_S} s. Paro para revisar.", flush=True)
                break
            if len(tiempos) >= 3 and (t_scan > 2.5 * max(statistics.median(tiempos), 5)
                                      or rss > 2.0 * max(statistics.median(rams), 100)):
                print(f"!!! {mes}: se desvia de la mediana ({t_scan:.0f} s, +{rss:.0f} MB). Paro para revisar.", flush=True)
                break
            tiempos.append(t_scan)
            rams.append(rss)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    tot = sum(len(v["contratos"]) for v in datos["municipios"].values())
    print(f"{args.salida}: {tot} contratos en {len(datos['municipios'])} municipios; meses {datos['meses'][0]}..{datos['meses'][-1]}",
          flush=True)
    os._exit(0)                                                    # el enriquecimiento de app.py deja hilos vivos


if __name__ == "__main__":
    main()
