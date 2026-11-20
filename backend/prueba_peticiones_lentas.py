# encoding: utf-8
"""Pruebas del registro de peticiones lentas (2026-11-16).

Sin red. Parte 1 (siempre): _ruta_lenta, sacada de app.py con ast, no deja datos de nadie en la ruta.
Parte 2 (PRUEBA_CON_APP=1, importa app.py entero: lento, pesado y escribe en la cache.db de DATA_DIR, así que úsese
con una COPIA): una petición lenta de mentira pasa por app() y se comprueba la fila guardada (campos, muestras de los
otros hilos, peticiones a la vez, sin IP ni user-agent ni valores personales) y el borrado a los 7 días.
Uso: python backend/prueba_peticiones_lentas.py
"""
import ast
import json
import os
import re
import sys
import threading
import time
from urllib.parse import parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))
FALLOS = []


def ok(cond, txt):
    print(("OK   " if cond else "FALLO") + " " + txt, flush=True)
    if not cond:
        FALLOS.append(txt)


fuente = open(os.path.join(BASE, "app.py"), encoding="utf-8").read()
arbol = ast.parse(fuente, feature_version=(3, 11))
nodos = [n for n in arbol.body if (isinstance(n, ast.FunctionDef) and n.name == "_ruta_lenta")
         or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "_LENTAS_PARAMS_CON_VALOR" for t in n.targets))]
ns = {"re": re, "parse_qs": parse_qs}
exec(compile(ast.Module(body=nodos, type_ignores=[]), "app.py", "exec"), ns)
rl = ns["_ruta_lenta"]
ok(rl("/ca/", "muni=Palma&provincia=illes_balears") == "/ca/?muni=Palma&provincia=illes_balears",
   "ficha: municipio y provincia con valor")
ok(rl("/empresa/12345678Z", "") == "/empresa/*", "un NIF en la dirección sale como *")
ok(rl("/", "q=Juan Pérez García&muni=Mula") == "/?muni=Mula&q", "la búsqueda (q) va sin su valor")
ok(rl("/rankings", "nif=B12345678&pag=3") == "/rankings?nif&pag=3", "otros parámetros, solo el nombre")
ok(len(rl("/x", "muni=" + "a" * 500)) <= 240, "longitud acotada")

if os.environ.get("PRUEBA_CON_APP") != "1":
    print("\n(parte 2 sin lanzar: PRUEBA_CON_APP=1 con DATA_DIR apuntando a una copia)")
    print(f"\n{'TODO BIEN' if not FALLOS else str(len(FALLOS)) + ' FALLOS'}")
    sys.exit(1 if FALLOS else 0)

os.environ.setdefault("DINERO_HILOS_EN_POST_FORK", "1")
sys.path.insert(0, BASE)
import app  # noqa: E402

app.PETICIONES_LENTAS_SEG = 1.0
app._LENTAS_MUESTRA_CADA_S = 0.4
original = app._app_wsgi
parar = threading.Event()


def ocupado_un_rato():                      # un hilo de fondo trabajando, para verlo en las muestras
    while not parar.is_set():
        sum(i * i for i in range(20000))


def falso(environ, start_response):
    ruta = environ.get("PATH_INFO", "")
    time.sleep(2.6 if "empresa" in ruta else 1.5)
    start_response("200 OK", [("Content-Type", "text/plain"), ("Content-Length", "2")])
    return [b"ok"]


app._app_wsgi = falso
threading.Thread(target=ocupado_un_rato, name="prueba-ocupado", daemon=True).start()
IP, UA = "203.0.113.77", "Mozilla/5.0 (Windows NT 10.0) PruebaNavegador/1.0"


def pedir(path, query, ua=UA):
    env = {"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": query, "HTTP_USER_AGENT": ua,
           "REMOTE_ADDR": IP, "HTTP_X_FORWARDED_FOR": IP}
    return b"".join(app.app(env, lambda s, h, e=None: None))


with app._db_lock:
    app._lentas_tabla()
    antes = app._db.execute("SELECT coalesce(max(id), 0) FROM peticiones_lentas").fetchone()[0]
otra = threading.Thread(target=pedir, args=("/gl/rankings", "pag=2", "Mozilla/5.0 (compatible; Googlebot/2.1)"))
otra.start()
pedir("/ca/empresa/12345678Z", "muni=Palma&provincia=illes_balears&q=Juan Perez")
otra.join()
parar.set()
with app._db_lock:
    filas = app._db.execute("SELECT ts, ruta, idioma, segundos, visitante, otros_hilos FROM peticiones_lentas "
                            "WHERE id > ? ORDER BY id", (antes,)).fetchall()
ok(len(filas) == 2, f"se guardan las 2 peticiones lentas ({len(filas)})")
f = next((x for x in filas if "empresa" in x[1]), None)
ok(f is not None, "está la petición de la ficha de empresa")
if f:
    ts, ruta, idioma, seg, vis, otros = f
    d = json.loads(otros)
    ok(ruta == "/ca/empresa/*?muni=Palma&provincia=illes_balears&q", f"ruta sin datos ({ruta})")
    ok(idioma == "ca" and vis == "navegador" and seg >= 2.5, f"idioma, visitante y segundos ({idioma}, {vis}, {seg})")
    ok(len(d["muestras"]) >= 1, f"hay muestras de los otros hilos ({len(d['muestras'])})")
    ok(any(h["hilo"] == "prueba-ocupado" for m in d["muestras"] for h in m["hilos"]),
       "las muestras ven el hilo de fondo ocupado")
    ok(any(x["ruta"] == "/gl/rankings?pag" and x["visitante"] == "Googlebot" for x in d["a_la_vez"]),
       "anota la otra petición que coincidió (ruta y nombre del bot)")
    texto = json.dumps(f, ensure_ascii=False)
    for prohibido in ("203.0.113", "PruebaNavegador", "Windows NT", "Juan", "Perez", "12345678"):
        ok(prohibido not in texto, f"la fila no lleva «{prohibido}»")
g = next((x for x in filas if "rankings" in x[1]), None)
ok(g is not None and g[2] == "gl" and g[4] == "Googlebot", "la del bot se guarda con su nombre")

# borrado a los 7 días: una fila de hace 8 días desaparece al guardar la siguiente
with app._db_lock:
    app._db.execute("INSERT INTO peticiones_lentas (ts, ruta, idioma, segundos, visitante, otros_hilos) "
                    "VALUES (?,?,?,?,?,?)", (time.time() - 8 * 86400, "/vieja", "es", 11.0, "navegador", "{}"))
    app._db.commit()
pedir("/eu/", "")
with app._db_lock:
    viejas = app._db.execute("SELECT count(*) FROM peticiones_lentas WHERE ruta='/vieja'").fetchone()[0]
ok(viejas == 0, "las de más de 7 días se borran solas")
leido = app._lentas_leer()
ok(leido.get("total", 0) >= 3 and leido["ultimas"][0]["ruta"] == "/eu/", "el diagnóstico las enseña, la última primero")
estado = app._estado_carga()
ok("peticiones_lentas" in estado, "/api/diagnostico-arranque lleva «peticiones_lentas»")

with app._db_lock:                         # deja la copia como estaba
    app._db.execute("DELETE FROM peticiones_lentas WHERE id > ?", (antes,))
    app._db.commit()
app._app_wsgi = original

# Acceso (16-11-2026): sin clave, solo lo básico; lo interno con X-Admin-Token o con la sesión de /admin/revision
os.environ["ADMIN_TOKEN"] = "clave-de-prueba-local"


def diag(path, query="", cabeceras=None):
    env = {"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": query, "HTTP_USER_AGENT": "curl/8",
           "REMOTE_ADDR": "127.0.0.1", "wsgi.input": None, **(cabeceras or {})}
    estado = {}
    cuerpo = b"".join(app.app(env, lambda s, h, e=None: estado.update(s=s, h=dict(h))))
    if estado["h"].get("Content-Encoding") == "gzip":
        import gzip
        cuerpo = gzip.decompress(cuerpo)
    return estado["s"][:3], cuerpo.decode("utf-8", "replace")


INTERNO = ("carga", "peticiones_lentas", "hilos", "ultimos_10_min", "data_dir", "memoria_desglose", "memoria_rss_mb")
cod, cuerpo = diag("/api/diagnostico-arranque")
d = json.loads(cuerpo)
ok(cod == "200" and "arrancado_utc" in d and "disco_confiable" in d, "sin clave: 200 con lo básico de arranque")
ok(not any(k in cuerpo for k in INTERNO), "sin clave: nada interno (carga, hilos, rutas, lentas, memoria, carpetas)")
cod, cuerpo = diag("/api/diagnostico-arranque", "token=clave-de-prueba-local")
ok(not any(k in cuerpo for k in INTERNO), "con ?token= en la URL: igual que sin clave")
cod, cuerpo = diag("/api/diagnostico-arranque", "", {"HTTP_X_ADMIN_TOKEN": "otra"})
ok(not any(k in cuerpo for k in INTERNO), "con una cabecera equivocada: igual que sin clave")
cod, cuerpo = diag("/api/diagnostico-arranque", "", {"HTTP_X_ADMIN_TOKEN": "clave-de-prueba-local"})
d = json.loads(cuerpo)
ok(cod == "200" and "peticiones_lentas" in d.get("carga", {}) and "hilos" in d["carga"]
   and "ultimos_10_min" in d["carga"], "con X-Admin-Token: completo (lentas, hilos, rutas)")
sesion = "dp_rev=" + app._revision_cookie_nueva()
cod, cuerpo = diag("/admin/revision/diagnostico", "", {"HTTP_COOKIE": sesion})
ok(cod == "200" and "peticiones_lentas" in json.loads(cuerpo).get("carga", {}),
   "con la sesión de /admin/revision: completo en /admin/revision/diagnostico")
cod, cuerpo = diag("/admin/revision/diagnostico")
ok("peticiones_lentas" not in cuerpo and "carga" not in cuerpo, "/admin/revision/diagnostico sin sesión: no da nada")
cod, cuerpo = diag("/api/diagnostico-arranque", "", {"HTTP_COOKIE": sesion})
ok("peticiones_lentas" in cuerpo, "la sesión también vale en /api/diagnostico-arranque si el navegador la manda")
print(f"\n{'TODO BIEN' if not FALLOS else str(len(FALLOS)) + ' FALLOS'}")
sys.exit(1 if FALLOS else 0)
