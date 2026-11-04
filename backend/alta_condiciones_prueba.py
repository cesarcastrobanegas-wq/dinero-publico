# encoding: utf-8
"""
Prueba sin red de la aceptación de las condiciones y del aviso de pago del filtro de licitaciones (2026-11-04).

Parte 1 (funciones, sin la web): casilla obligatoria (sin ella, error y nada en socios.db), fecha + versión guardadas,
migración suave de una socios.db de antes, cambio de un perfil ya confirmado (la aceptación se apunta al confirmar),
precio puesto / no puesto / con HTML, correo de confirmación con los enlaces y la versión, y que no queda en el código
el ancla inexistente del aviso legal.

Parte 2 (la web, en un proceso aparte): importa app.py con FILTRO_FORMULARIO=1 SOLO en ese proceso, con un DATA_DIR
temporal VACÍO (nunca el cache.db real), sin red (las conexiones de red dan error) y Resend simulado (requests.post
falso que guarda lo que se habría enviado). Formulario, envío sin casilla, envío con casilla y correo de confirmación.

Uso: python backend/alta_condiciones_prueba.py            (las dos partes)
     python backend/alta_condiciones_prueba.py funciones  (solo la parte 1, sin importar app.py)
Correos INVENTADOS (ejemplo.test).
"""
import glob
import io
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlencode

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

FALLOS = []


def ok(cond, txt, parte="funciones"):
    print(f"[{parte}] " + ("OK   " if cond else "FALLO") + " " + txt, flush=True)
    if not cond:
        FALLOS.append(txt)


def envio_valido(con_casilla=True, correo="empresa@ejemplo.test"):
    import filtro_licitaciones as F
    import licitaciones_place as LIC
    d = {"sector": [sorted(LIC.CPV_DIVISIONES)[0]], "provincia": [sorted(F.NOMBRE_PROVINCIA)[0]], "trabajadores": ["5"],
         "facturacion": [list(F.TRAMOS_TEXTO)[0]], "experiencia": ["si"], "ute": ["no"], "correo": [correo]}
    if con_casilla:
        d["condiciones"] = ["1"]
    return d


def sin_entorno_precio():
    for k in ("PRECIO_FILTRO", "PRECIO_FILTRO_PERIODO"):
        os.environ.pop(k, None)


# ── parte 1 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def funciones():
    import filtro_formulario as FF
    import socios as SOC
    sin_entorno_precio()
    V = FF.CONDICIONES_VERSION
    ok(V == "borrador-2026-11-04", f"versión de las condiciones: {V}")
    tmp = tempfile.mkdtemp(prefix="alta_condiciones_")
    try:
        alm = SOC.Almacen(os.path.join(tmp, "socios.db"))
        filas = lambda: alm.db.execute("SELECT count(*) FROM perfiles").fetchone()[0]     # noqa: E731
        guardados = []

        def guardar(correo, perfil):
            guardados.append(correo)
            return alm.alta(correo, perfil, condiciones=V)["resultado"]

        # sin casilla
        _, _, err = FF.leer_envio(envio_valido(False))
        ok(any(e.startswith("condiciones:") for e in err), "sin casilla: leer_envio da el error de las condiciones")
        _, _, err = FF.leer_envio(dict(envio_valido(False), condiciones=["0"]))
        ok(any(e.startswith("condiciones:") for e in err), "casilla con otro valor que «1»: error")
        pag = FF.responder("POST", envio_valido(False), lambda: [], guardar=guardar)
        ok(not guardados and filas() == 0, "sin casilla: no se llama a guardar y socios.db sigue vacía")
        ok("aceptar las condiciones de contratación" in pag and 'name="condiciones"' in pag,
           "sin casilla: la página vuelve con el error y la casilla")
        r = alm.alta("otra@ejemplo.test", {"cpvs": ["90"]})
        ok(r["resultado"] == "sin_condiciones" and filas() == 0, "socios.alta sin versión aceptada: no guarda nada")
        r = alm.alta("otra@ejemplo.test", {"cpvs": ["90"]}, condiciones="   ")
        ok(r["resultado"] == "sin_condiciones" and filas() == 0, "socios.alta con versión en blanco: no guarda nada")

        # con casilla
        _, _, err = FF.leer_envio(envio_valido(True))
        ok(err == [], f"con casilla y datos válidos: sin errores ({err})")
        antes = time.time()
        FF.responder("POST", envio_valido(True), lambda: [], guardar=guardar)
        p = alm.por_correo("empresa@ejemplo.test")
        ok(guardados == ["empresa@ejemplo.test"] and filas() == 1, "con casilla: se guarda (sin confirmar)")
        ok(p and p["condiciones_version"] == V and p["condiciones_aceptadas"] and p["condiciones_aceptadas"] >= antes - 1,
           f"con casilla: guarda la fecha de aceptación y la versión ({p and p['condiciones_version']})")
        cols = [f[1] for f in alm.db.execute("PRAGMA table_info(perfiles)")]
        ok(not any(c for c in cols if "ip" == c.lower() or "nombre" in c.lower() or "telefono" in c.lower()),
           "ni IP ni nombre ni teléfono en la tabla")

        # alta repetida sin confirmar: la aceptación se renueva
        alm.db.execute("UPDATE perfiles SET condiciones_aceptadas=1, condiciones_version='vieja'")
        alm.db.execute("DELETE FROM envios")
        alm.db.commit()
        alm.alta("empresa@ejemplo.test", {"cpvs": ["91"]}, condiciones=V)
        p = alm.por_correo("empresa@ejemplo.test")
        ok(p["condiciones_version"] == V and p["condiciones_aceptadas"] > 1, "alta repetida sin confirmar: aceptación nueva")

        # confirmar el alta; después un cambio: la aceptación no cambia hasta confirmar el cambio
        pid = p["id"]
        alm.confirmar(pid, alm.firma("confirmar", pid, SOC.huella(alm.a_confirmar(p))), condiciones=V)
        alm.db.execute("UPDATE perfiles SET condiciones_aceptadas=5, condiciones_version='anterior'")
        alm.db.execute("DELETE FROM envios")
        alm.db.commit()
        alm.alta("empresa@ejemplo.test", {"cpvs": ["92"]}, condiciones=V)
        p = alm.perfil(pid)
        ok(p["condiciones_version"] == "anterior" and p["condiciones_aceptadas"] == 5,
           "cambio de un perfil confirmado: la aceptación no se toca hasta confirmar el cambio")
        alm.confirmar(pid, alm.firma("confirmar", pid, SOC.huella(alm.a_confirmar(p))), condiciones=V)
        p = alm.perfil(pid)
        ok(p["perfil"]["cpvs"] == ["92"] and p["condiciones_version"] == V and p["condiciones_aceptadas"] > 5,
           "al confirmar el cambio: aceptación con la versión actual")
        alm.db.close()

        # migración desde una socios.db de antes (sin las dos columnas), con una fila dentro
        ruta = os.path.join(tmp, "vieja.db")
        db = sqlite3.connect(ruta)
        db.executescript("""
CREATE TABLE ajustes (clave TEXT PRIMARY KEY, valor TEXT);
CREATE TABLE perfiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT, correo TEXT NOT NULL UNIQUE, perfil TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendiente', alta REAL NOT NULL, confirmado REAL, ultimo_uso REAL,
    perfil_pendiente TEXT, pendiente_desde REAL, revisado REAL, ultimo_envio REAL, intentado REAL,
    aviso_inactividad REAL);
INSERT INTO perfiles (correo, perfil, estado, alta, confirmado) VALUES ('antigua@ejemplo.test', '{"cpvs": ["90"]}',
    'activo', 1000, 1000);
""")
        db.commit()
        db.close()
        vieja = SOC.Almacen(ruta)
        cols = [f[1] for f in vieja.db.execute("PRAGMA table_info(perfiles)")]
        p = vieja.por_correo("antigua@ejemplo.test")
        ok("condiciones_aceptadas" in cols and "condiciones_version" in cols, "migración: se añaden las dos columnas")
        ok(p and p["estado"] == "activo" and p["condiciones_version"] is None and p["condiciones_aceptadas"] is None,
           "migración: la fila de antes sigue, sin aceptación (no se inventa)")
        vieja.db.close()
        vieja = SOC.Almacen(ruta)                                     # abrirla otra vez no falla
        ok(vieja.por_correo("antigua@ejemplo.test") is not None, "migración: abrir dos veces no falla")
        vieja.db.close()
    finally:
        for f in glob.glob(os.path.join(tmp, "*")):
            os.remove(f)
        os.rmdir(tmp)

    # precio
    perfil_ok = FF.leer_envio(envio_valido(True))[0]
    ok(FF.precio_texto({}) == "precio por confirmar", "sin PRECIO_FILTRO: «precio por confirmar»")
    ok(FF.precio_texto({"PRECIO_FILTRO": "  "}) == "precio por confirmar", "PRECIO_FILTRO vacía: «precio por confirmar»")
    ok(FF.precio_texto({"PRECIO_FILTRO": "9"}) == "9 €/mes", f"PRECIO_FILTRO=9: {FF.precio_texto({'PRECIO_FILTRO': '9'})}")
    ok(FF.precio_texto({"PRECIO_FILTRO": "90", "PRECIO_FILTRO_PERIODO": "año"}) == "90 €/año", "periodo año")
    ok(FF.precio_texto({"PRECIO_FILTRO": "9,90 €", "PRECIO_FILTRO_PERIODO": "raro"}) == "9,90 €/mes",
       "importe con € y periodo desconocido: /mes")
    sin_entorno_precio()
    f0 = FF.formulario_html()
    ok("El servicio es de pago: precio por confirmar. Te escribiremos para el pago antes de empezar." in f0,
       "formulario sin precio: aviso de pago con «precio por confirmar»")
    ok(f0.count("El servicio es de pago") == 2, "el aviso de pago sale en la caja y en el texto de protección de datos")
    ok('href="/legal/condiciones"' in f0 and 'href="/legal/privacidad"' in f0, "enlaces a /legal/condiciones y /legal/privacidad")
    ok('type="checkbox" name="condiciones" value="1"' in f0 and "He leído y acepto" in f0 and
       'name="condiciones" value="1" required>' in f0, "casilla sin marcar por defecto")
    ok('name="condiciones" value="1" required checked' in FF.formulario_html(envio_valido(True)),
       "al volver con errores, la casilla sigue marcada si se marcó")
    os.environ["PRECIO_FILTRO"] = "12"
    ok("El servicio es de pago: 12 €/mes." in FF.formulario_html(), "formulario con PRECIO_FILTRO=12")
    os.environ["PRECIO_FILTRO"] = '<b>9</b>"<script>'
    f1 = FF.formulario_html()
    ok("<b>9</b>" not in f1 and "<script>" not in f1 and "&lt;b&gt;9&lt;/b&gt;&quot;&lt;script&gt;" in f1,
       "precio con HTML: sale escapado")
    a, t, h = FF.correo_confirmacion(perfil_ok, "https://x.test/c", "https://x.test/b")
    ok("<script>" not in h and "&lt;script&gt;" in h and '<b>9</b>"<script>' in t,
       "precio con HTML en el correo: escapado en el HTML, tal cual en el texto llano")
    sin_entorno_precio()

    # correo de confirmación
    for es_cambio in (False, True):
        a, t, h = FF.correo_confirmacion(perfil_ok, "https://dp.test/confirmar?p=1&k=x", "https://dp.test/baja",
                                         es_cambio=es_cambio, enlace_condiciones="https://dp.test/legal/condiciones",
                                         enlace_privacidad="https://dp.test/legal/privacidad", version=V)
        ok("https://dp.test/legal/condiciones" in t and "https://dp.test/legal/privacidad" in t and V in t,
           f"correo de confirmación ({'cambio' if es_cambio else 'alta'}), texto: enlaces y versión")
        ok('href="https://dp.test/legal/condiciones"' in h and 'href="https://dp.test/legal/privacidad"' in h and V in h,
           f"correo de confirmación ({'cambio' if es_cambio else 'alta'}), HTML: enlaces y versión")
        ok("El servicio es de pago: precio por confirmar" in t and "El servicio es de pago" in h,
           "el correo de confirmación avisa de que es de pago")
    ok(FF.url_completa("/legal/condiciones", "https://dp.test") == "https://dp.test/legal/condiciones"
       and FF.url_completa("https://otra.test/c", "https://dp.test") == "https://otra.test/c", "url_completa")

    # ancla inexistente
    ancla = "#filtro-" + "licitaciones"
    con_ancla = []
    for ruta in glob.glob(os.path.join(AQUI, "*.py")):
        with io.open(ruta, encoding="utf-8", errors="replace") as fh:
            if ancla in fh.read():
                con_ancla.append(os.path.basename(ruta))
    ok(not con_ancla, f"no queda «{ancla}» en el código de backend ({con_ancla})")
    ok(not hasattr(FF, "ANCLA_AVISO_LEGAL"), "ANCLA_AVISO_LEGAL eliminada")


# ── parte 2: la web, en un proceso hijo ─────────────────────────────────────────────────────────────────────────────
def web_hijo(datos):
    import socket

    def sin_red(*a, **k):
        raise OSError("prueba sin red")
    socket.socket.connect = sin_red
    socket.create_connection = sin_red
    os.chdir(AQUI)
    from wsgiref.util import setup_testing_defaults
    import app  # noqa: E402
    enviados = []

    class _Resp:
        status_code, text = 200, '{"id":"simulado"}'

    class _Requests:                                                   # Resend simulado: nada sale del proceso
        @staticmethod
        def post(url, json=None, **k):
            enviados.append((url, json))
            return _Resp()
    app.requests = _Requests
    parte = "web"

    def peticion(metodo, ruta, campos=None):
        b = urlencode(campos or {}, doseq=True).encode("utf-8")
        env = {"REQUEST_METHOD": metodo, "PATH_INFO": ruta, "QUERY_STRING": "", "CONTENT_LENGTH": str(len(b)),
               "CONTENT_TYPE": "application/x-www-form-urlencoded", "wsgi.input": io.BytesIO(b)}
        setup_testing_defaults(env)
        estado = {}
        cuerpo = b"".join(app.app(env, lambda s, h, e=None: estado.update(s=s)))
        return int(estado["s"].split()[0]), cuerpo.decode("utf-8", "replace")

    def esperar_hilos():
        for h in threading.enumerate():
            if h.name == "socios-confirmacion":
                h.join(10)

    ok(os.path.abspath(app.DATA_DIR) == os.path.abspath(datos), f"DATA_DIR temporal ({app.DATA_DIR})", parte)
    c, pag = peticion("GET", "/filtro-licitaciones")
    ok(c == 200 and 'name="condiciones"' in pag and 'href="/legal/condiciones"' in pag
       and "precio por confirmar" in pag, f"GET: casilla, enlaces y «precio por confirmar» ({c})", parte)
    alm = app._socios_almacen()
    filas = lambda: alm.db.execute("SELECT count(*) FROM perfiles").fetchone()[0]   # noqa: E731
    c, pag = peticion("POST", "/filtro-licitaciones", envio_valido(False))
    esperar_hilos()
    ok(c == 200 and "aceptar las condiciones" in pag and filas() == 0 and not enviados,
       f"POST sin casilla: error, nada en socios.db y ningún correo ({c}, {filas()}, {len(enviados)})", parte)
    c, pag = peticion("POST", "/filtro-licitaciones", envio_valido(True))
    esperar_hilos()
    p = alm.por_correo("empresa@ejemplo.test")
    ok(c == 200 and "Revisa tu correo" in pag and p and p["condiciones_version"] == app.FFORM.CONDICIONES_VERSION
       and p["condiciones_aceptadas"], f"POST con casilla: guarda fecha y versión ({c})", parte)
    ok(len(enviados) == 1 and enviados[0][0] == "https://api.resend.com/emails", "un correo de confirmación (simulado)", parte)
    if enviados:
        carga = enviados[0][1]
        base = app.SITE_URL
        ok(carga["to"] == ["empresa@ejemplo.test"] and f"{base}/legal/condiciones" in carga["text"]
           and f"{base}/legal/privacidad" in carga["text"] and app.FFORM.CONDICIONES_VERSION in carga["text"],
           "correo: enlaces completos a condiciones y privacidad y la versión (texto)", parte)
        ok(f'href="{base}/legal/condiciones"' in carga["html"] and app.FFORM.CONDICIONES_VERSION in carga["html"],
           "correo: enlaces y versión (HTML)", parte)
    # confirmar desde el enlace firmado
    pid = p["id"] if p else 0
    k = alm.firma("confirmar", pid, app.SOC.huella(alm.a_confirmar(alm.perfil(pid)))) if p else ""
    c, pag = peticion("POST", "/filtro-licitaciones/confirmar", {"p": str(pid), "k": k})
    ok(c == 200 and alm.perfil(pid)["estado"] == "activo"
       and alm.perfil(pid)["condiciones_version"] == app.FFORM.CONDICIONES_VERSION, "confirmar: activo, con la versión", parte)
    os.environ["PRECIO_FILTRO"] = "<i>15</i>"
    c, pag = peticion("GET", "/filtro-licitaciones")
    ok("&lt;i&gt;15&lt;/i&gt; €/mes" not in pag and "&lt;i&gt;15&lt;/i&gt;/mes" in pag and "<i>15</i>" not in pag,
       "GET con PRECIO_FILTRO con HTML: escapado", parte)
    # panel: fecha y versión aceptadas; aviso si falta o si es de una versión anterior
    with alm.lock:
        alm.db.execute("INSERT INTO perfiles (correo, perfil, estado, alta) VALUES (?, ?, 'activo', 1)",
                       ("antigua@ejemplo.test", '{"provincias": []}'))
        alm.db.execute("INSERT INTO perfiles (correo, perfil, estado, alta, condiciones_aceptadas, condiciones_version) "
                       "VALUES (?, ?, 'activo', 1, 1700000000, 'version-vieja')", ("vieja@ejemplo.test", '{"provincias": []}'))
        alm.db.commit()
    _c, _h, cuerpo = app._socios_panel_html("cookie-de-prueba")       # (código, cabeceras, bytes)
    panel = cuerpo.decode("utf-8")
    vigente = app.FFORM.CONDICIONES_VERSION
    ok("<th>Condiciones aceptadas</th>" in panel, "panel: columna «Condiciones aceptadas»", parte)
    ok(f" · {vigente}</td>" in panel, "panel: fecha y versión vigente del perfil confirmado", parte)
    ok("<b>NO</b> (perfil anterior al 04-11: sin aceptación)" in panel, "panel: perfil sin aceptación marcado", parte)
    ok("version-vieja <b>(versión anterior" in panel and "14/11/2023" in panel, "panel: versión anterior avisada", parte)
    ok(f"{vigente} · 1 perfil(es) sin aceptación" in panel, "panel: recuento de perfiles sin aceptación", parte)
    alm.db.close()
    print(f"[{parte}] FALLOS: {len(FALLOS)}", flush=True)
    return FALLOS


def web():
    datos = tempfile.mkdtemp(prefix="alta_condiciones_web_")
    try:
        # DATA_DIR vacío: un cache.db vacío y el marcador de disco (así el arranque no espera 60 s a que «monte»).
        open(os.path.join(datos, "cache.db"), "wb").close()
        open(os.path.join(datos, ".disco_inicializado"), "w").close()
        quitar = ("RESEND_API_KEY", "SOCIOS_SOLO_CORREOS", "FILTRO_FORMULARIO", "FILTRO_EMBUDO", "ALERTAS_ACTIVAS",
                  "PRECIO_FILTRO", "PRECIO_FILTRO_PERIODO", "PRECIOS_VISIBLE", "FORMA_PAGO", "TEXTOS_LEGALES_NUEVOS",
                  "SITE_URL", "ADMIN_TOKEN")
        env = {k: v for k, v in os.environ.items() if k not in quitar}
        env.update(FILTRO_FORMULARIO="1", DATA_DIR=datos, RESEND_API_KEY="re_prueba_inventada_sin_red",
                   DINERO_HILOS_EN_POST_FORK="1", PYTHONIOENCODING="utf-8")
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "--web-hijo", datos], env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
        lineas = [l for l in r.stdout.splitlines() if l.startswith("[web]")]
        print("\n".join(lineas), flush=True)
        if r.returncode and not any("FALLOS:" in l for l in lineas):
            print(r.stdout[-1500:] + r.stderr[-3000:], flush=True)
        return 0 if r.returncode == 0 else 1
    finally:
        for _ in range(5):                                             # socios.db, cache.db y place_cache/
            shutil.rmtree(datos, ignore_errors=True)
            if not os.path.exists(datos):
                break
            time.sleep(1)
        ok(not os.path.exists(datos), "la carpeta temporal de datos queda borrada", "web")


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--web-hijo":
        sys.exit(1 if web_hijo(sys.argv[2]) else 0)
    funciones()
    n_funciones = len(FALLOS)
    print(f"\n[funciones] FALLOS: {n_funciones}", flush=True)
    n_web = 0
    if not (len(sys.argv) == 2 and sys.argv[1] == "funciones"):
        n_web = web()
        n_web += len(FALLOS) - n_funciones                             # la limpieza de la carpeta temporal
    print(f"\nRESULTADO: funciones {n_funciones} fallos; web {'con fallos' if n_web else 'sin fallos'}")
    sys.exit(1 if (n_funciones or n_web) else 0)


if __name__ == "__main__":
    main()
