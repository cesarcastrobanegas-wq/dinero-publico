# encoding: utf-8
"""Prueba de la FASE 1 de los ficheros con nombres de personas (18-11-2026, ver datos_personales.py). Sin red: DATA_DIR
en una carpeta temporal (hace de disco de Render), sin hilos de fondo. Nunca imprime nombres. Comprueba que:
  - con un fichero en DATA_DIR/datos_personales/ la web lo lee de ahí; sin él, de backend/ como siempre;
  - el feed de PLACE junta disco y repositorio sin repetir y la huella no cambia si los bytes son los mismos;
  - el histórico de formales por provincia también junta los dos sitios;
  - POST /admin/datos-personales: 403 sin token; 400 con un fichero no permitido, una ruta con «..» o contenido roto;
    200 con uno válido (guardado en el disco, mismos bytes que el repositorio); 409 si baja demasiado y 200 con
    &forzar=si (queda .anterior); un .json.gz que llega sin comprimir se guarda en gzip;
  - GET /admin/datos-personales dice de dónde sale cada fichero, sin nombres.

    python backend/prueba_datos_personales.py      (proceso pesado: importa la web; de uno en uno, ~1 min)
"""
import gzip
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
TOKEN = "token-de-prueba-datos-personales"


def main():
    datos = tempfile.mkdtemp(prefix="datos_personales_")
    disco = os.path.join(datos, "datos_personales")
    os.makedirs(os.path.join(disco, "backfill_formales_place_prov"))
    # Antes de importar la web: en el «disco», alcaldes (mismos bytes que el repositorio), un mes del feed de PLACE y
    # una provincia del histórico de formales.
    shutil.copy(os.path.join(BASE_DIR, "alcaldes_concejales.json"), disco)
    feed = sorted(f for f in os.listdir(BASE_DIR) if f.startswith("contratos_menores_place_") and f.endswith(".json.gz"))
    shutil.copy(os.path.join(BASE_DIR, feed[0]), disco)
    shutil.copy(os.path.join(BASE_DIR, "backfill_formales_place_prov", "segovia.json.gz"),
                os.path.join(disco, "backfill_formales_place_prov"))
    os.environ.update(DATA_DIR=datos, HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9",
                      DINERO_HILOS_EN_POST_FORK="1", ADMIN_TOKEN=TOKEN)
    os.environ.pop("RESEND_API_KEY", None)
    import app
    import datos_personales as dp
    mal, bien = [], [0]

    def comprobar(cond, texto):
        if cond:
            bien[0] += 1
        else:
            mal.append(texto)

    # ── De dónde se lee ───────────────────────────────────────────────────────────────────────────────────────────
    comprobar(app.ALCALDES_FILE == os.path.join(disco, "alcaldes_concejales.json"), "alcaldes no se lee del disco")
    comprobar(app.SUELDOS_CONCEJALES_FILE == os.path.join(BASE_DIR, "sueldos_concejales.json"),
              "sueldos (no está en el disco) no se lee de backend/")
    comprobar(app.CONTRATOS_MENORES_EUSKADI_FILE == os.path.join(BASE_DIR, "contratos_menores_euskadi.json.gz"),
              "Euskadi no se lee de backend/")
    comprobar(len(app.ALCALDES_CONCEJALES) > 8000, f"alcaldes desde el disco: {len(app.ALCALDES_CONCEJALES)} municipios")

    rutas = app._rutas_feed_place()
    nombres = [os.path.basename(r) for r in rutas]
    comprobar(nombres == feed, "el feed de PLACE no junta disco y repositorio en orden de nombre, sin repetir")
    comprobar(rutas[0] == os.path.join(disco, feed[0]) and all(r.startswith(BASE_DIR) for r in rutas[1:]),
              "el feed de PLACE no toma del disco el mes que está en el disco")

    def huella(lista):
        h = hashlib.sha256()
        for r in lista:
            with open(r, "rb") as f:
                h.update(f.read())
        return h.hexdigest()[:16]
    comprobar(huella(rutas) == huella([os.path.join(BASE_DIR, f) for f in feed]),
              "la huella del feed cambia con los mismos bytes (repetiría la carga de ~1M de filas)")

    prov = dp.rutas_patron("backfill_formales_place_prov", "", ".json.gz")
    comprobar(len(prov) == len([f for f in os.listdir(os.path.join(BASE_DIR, "backfill_formales_place_prov"))
                                if f.endswith(".json.gz")]), "el histórico por provincia pierde o repite ficheros")
    comprobar(os.path.join(disco, "backfill_formales_place_prov", "segovia.json.gz") in prov,
              "el histórico por provincia no toma Segovia del disco")

    # ── Subida ────────────────────────────────────────────────────────────────────────────────────────────────────
    def post(fichero, cuerpo, token=TOKEN, extra=""):
        env = {"REQUEST_METHOD": "POST", "PATH_INFO": "/admin/datos-personales",
               "QUERY_STRING": f"fichero={fichero}{extra}", "REMOTE_ADDR": "127.0.0.1", "SERVER_NAME": "localhost",
               "SERVER_PORT": "80", "wsgi.url_scheme": "http", "CONTENT_LENGTH": str(len(cuerpo)),
               "wsgi.input": io.BytesIO(cuerpo), "HTTP_USER_AGENT": "prueba"}
        if token:
            env["HTTP_X_ADMIN_TOKEN"] = token
        estado = {}
        b = b"".join(app.app(env, lambda s, h, e=None: estado.update(s=s)))
        return int(estado["s"][:3]), json.loads(b.decode("utf-8"))

    with open(os.path.join(BASE_DIR, "sueldos_concejales.json"), "rb") as f:
        sueldos = f.read()
    cod, _ = post("sueldos_concejales.json", sueldos, token="")
    comprobar(cod == 403, f"sin token: {cod}")
    cod, _ = post("sueldos_concejales.json", sueldos, token="otro")
    comprobar(cod == 403, f"token malo: {cod}")
    for rel in ("cache.db", "../app.py", "backfill_formales_place_prov/../../app.py", "poblacion.json"):
        cod, _ = post(rel, sueldos)
        comprobar(cod == 400, f"fichero no permitido {rel}: {cod}")
    cod, _ = post("sueldos_concejales.json", b"{roto")
    comprobar(cod == 400, f"contenido roto: {cod}")
    cod, _ = post("sueldos_concejales.json", json.dumps({"registros": [{"x": 1}]}).encode())
    comprobar(cod == 400, f"forma equivocada: {cod}")
    cod, r = post("sueldos_concejales.json", sueldos)
    comprobar(cod == 200 and r.get("registros") == r.get("antes") and r.get("origen_antes") == "repositorio"
              and r.get("mismos_bytes_que_antes") is True, f"subida válida: {cod} {r}")
    en_disco = os.path.join(disco, "sueldos_concejales.json")
    comprobar(os.path.isfile(en_disco) and open(en_disco, "rb").read() == sueldos, "no quedó en el disco tal cual")
    comprobar(not os.path.exists(en_disco + ".nuevo"), "queda el temporal .nuevo")
    comprobar(set(r) == {"fichero", "registros", "antes", "origen_antes", "sha256", "mismos_bytes_que_antes", "efecto"},
              f"la respuesta trae otros campos: {sorted(r)}")

    pocos = json.loads(sueldos)
    pocos["registros"] = pocos["registros"][:100]
    pocos = json.dumps(pocos, ensure_ascii=False).encode("utf-8")
    cod, r = post("sueldos_concejales.json", pocos)
    comprobar(cod == 409, f"bajada del 89 % aceptada sin forzar: {cod}")
    comprobar(open(en_disco, "rb").read() == sueldos, "la subida rechazada tocó el fichero")
    cod, r = post("sueldos_concejales.json", pocos, extra="&forzar=si")
    comprobar(cod == 200 and r.get("origen_antes") == "disco" and r.get("mismos_bytes_que_antes") is False,
              f"con forzar=si: {cod} {r}")
    comprobar(os.path.isfile(en_disco + ".anterior") and open(en_disco + ".anterior", "rb").read() == sueldos,
              "no quedó el .anterior")

    with gzip.open(os.path.join(BASE_DIR, "contratos_menores_arona.json.gz"), "rb") as f:
        arona_plano = f.read()
    cod, r = post("contratos_menores_arona.json.gz", arona_plano)
    guardado = os.path.join(disco, "contratos_menores_arona.json.gz")
    comprobar(cod == 200 and open(guardado, "rb").read()[:2] == b"\x1f\x8b"
              and gzip.decompress(open(guardado, "rb").read()) == arona_plano, f".json.gz sin comprimir: {cod}")
    with open(os.path.join(BASE_DIR, "backfill_formales_place_prov", "soria.json.gz"), "rb") as f:
        soria = f.read()
    cod, r = post("backfill_formales_place_prov/soria.json.gz", soria)
    comprobar(cod == 200 and r.get("mismos_bytes_que_antes") is True, f"histórico de Soria: {cod} {r}")

    env = {"REQUEST_METHOD": "GET", "PATH_INFO": "/admin/datos-personales", "QUERY_STRING": "",
           "REMOTE_ADDR": "127.0.0.1", "SERVER_NAME": "localhost", "SERVER_PORT": "80", "wsgi.url_scheme": "http",
           "HTTP_X_ADMIN_TOKEN": TOKEN, "HTTP_USER_AGENT": "prueba"}
    estado = {}
    b = b"".join(app.app(env, lambda s, h, e=None: estado.update(s=s)))
    lista = {x["fichero"]: x["origen"] for x in json.loads(b.decode("utf-8")).get("ficheros", [])}
    comprobar(estado["s"].startswith("200") and lista.get("sueldos_concejales.json") == "disco"
              and lista.get("contratos_menores_euskadi.json.gz") == "repositorio"
              and lista.get("backfill_formales_place_prov/soria.json.gz") == "disco",
              f"GET estado: {estado.get('s')}")
    comprobar(len(lista) >= 130, f"GET estado solo lista {len(lista)} ficheros")
    env.pop("HTTP_X_ADMIN_TOKEN")
    estado = {}
    b"".join(app.app(env, lambda s, h, e=None: estado.update(s=s)))
    comprobar(estado["s"].startswith("403"), f"GET estado sin token: {estado.get('s')}")

    print(f"{bien[0]} bien, {len(mal)} mal")
    for m in mal:
        print("  MAL:", m)
    sys.stdout.flush()
    shutil.rmtree(datos, ignore_errors=True)
    os._exit(1 if mal else 0)


if __name__ == "__main__":
    main()
