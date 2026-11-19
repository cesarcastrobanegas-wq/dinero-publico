# encoding: utf-8
"""Prueba de las lecturas sin cerrojo de las peticiones web (17-11-2026, ver _db_leer). Sin red: base vacía en una
carpeta temporal, sin hilos de fondo. Comprueba que:
  - fuera de una petición web se lee como siempre (conexión compartida y _db_lock cogido);
  - dentro de una petición se usa una conexión de solo lectura propia del hilo, sin coger _db_lock;
  - una ficha completa sale aunque otro hilo tenga _db_lock cogido (antes esperaba a que lo soltara);
  - con LECTURA_SIN_CERROJO apagado vuelve a esperar;
  - lo confirmado por la conexión compartida se ve desde la de lectura; la conexión de lectura no puede escribir;
  - cada hilo tiene la suya y la reutiliza.

    python backend/prueba_lectura_sin_cerrojo.py      (proceso pesado: importa la web; de uno en uno, ~1 min)
"""
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)


def main():
    os.environ.update(DATA_DIR=tempfile.mkdtemp(prefix="lectura_sin_cerrojo_"), HTTP_PROXY="http://127.0.0.1:9",
                      HTTPS_PROXY="http://127.0.0.1:9", DINERO_HILOS_EN_POST_FORK="1")
    os.environ.pop("LECTURA_SIN_CERROJO", None)
    import app
    mal, bien = [], [0]

    def comprobar(cond, texto):
        if cond:
            bien[0] += 1
        else:
            mal.append(texto)

    clave = app.clave_municipio("Villaprueba", "murcia")
    datos = {"municipio": "Villaprueba", "provincia": "murcia", "contratos": [], "ts": time.time()}
    with app._db_lock:
        app._db.execute("INSERT OR REPLACE INTO municipios (municipio, data, ts, provincia) VALUES (?,?,?,?)",
                        (clave, json.dumps(datos), time.time(), "murcia"))
        app._db.commit()

    def en_peticion(funcion, *args):
        t = app._EN_PETICION_WEB.set(True)
        try:
            return funcion(*args)
        finally:
            app._EN_PETICION_WEB.reset(t)

    # ── Fuera de una petición web: como siempre ───────────────────────────────────────────────────────────────────
    with app._db_leer() as con:
        comprobar(con is app._db, "fuera de petición: no es la conexión compartida")
        comprobar(app._db_lock.locked(), "fuera de petición: no tiene _db_lock cogido")
    comprobar(not app._db_lock.locked(), "fuera de petición: _db_lock no se suelta")

    # ── Dentro de una petición: conexión propia, sin cerrojo ──────────────────────────────────────────────────────
    def dentro():
        with app._db_leer() as con:
            return con, app._db_lock.locked()
    con1, cogido = en_peticion(dentro)
    comprobar(con1 is not app._db and not cogido, f"en petición: compartida={con1 is app._db} cerrojo={cogido}")
    con2, _ = en_peticion(dentro)
    comprobar(con1 is con2, "en petición: el mismo hilo no reutiliza su conexión")
    otro = {}
    th = threading.Thread(target=lambda: otro.update(con=en_peticion(dentro)[0]))
    th.start(); th.join()
    comprobar(otro.get("con") is not None and otro["con"] is not con1, "otro hilo no tiene su propia conexión")
    try:
        con1.execute("UPDATE settings SET valor='x' WHERE clave='nada'")
        comprobar(False, "la conexión de lectura deja escribir")
    except sqlite3.OperationalError:
        comprobar(True, "")

    # ── Lo confirmado se ve ───────────────────────────────────────────────────────────────────────────────────────
    with app._db_lock:
        app._db.execute("INSERT OR REPLACE INTO settings (clave, valor) VALUES ('prueba_lectura', '42')")
        app._db.commit()
    comprobar(en_peticion(app._settings_get, "prueba_lectura") == "42", "no se ve lo confirmado")
    comprobar((en_peticion(app._db_get_municipio, "Villaprueba", "murcia") or {}).get("municipio") == "Villaprueba",
              "_db_get_municipio en petición no encuentra el municipio")

    # ── Con otro hilo con _db_lock cogido ─────────────────────────────────────────────────────────────────────────
    def con_cerrojo_cogido(funcion, segundos=3.0):
        """Coge _db_lock en otro hilo durante `segundos` y mide cuánto tarda `funcion` en este."""
        cogido, soltar = threading.Event(), threading.Event()

        def retener():
            with app._db_lock:
                cogido.set()
                soltar.wait(segundos)
        th = threading.Thread(target=retener)
        th.start()
        cogido.wait()
        t0 = time.time()
        r = funcion()
        dt = time.time() - t0
        soltar.set()
        th.join()
        return r, dt

    _, dt = con_cerrojo_cogido(lambda: en_peticion(app._db_get_municipio, "Villaprueba", "murcia"))
    comprobar(dt < 1.0, f"en petición, con el cerrojo cogido por otro, tardó {dt:.1f} s")

    estado = {}

    def ficha():
        env = {"REQUEST_METHOD": "GET", "PATH_INFO": "/", "QUERY_STRING": "muni=Villaprueba&provincia=murcia",
               "REMOTE_ADDR": "127.0.0.1", "SERVER_NAME": "localhost", "SERVER_PORT": "80", "wsgi.url_scheme": "http",
               "HTTP_USER_AGENT": "Mozilla/5.0 (Windows NT 10.0) Chrome/130 Safari/537.36"}
        cuerpo = b"".join(app.app(env, lambda s, h, e=None: estado.update(s=s)))
        return cuerpo
    app._visitas_estado["ultimo_volcado"] = time.time() + 10 ** 6     # el volcado del contador escribe: aparte
    ficha()                                                            # cachés de módulo ya montadas
    cuerpo, dt = con_cerrojo_cogido(ficha, 5.0)
    comprobar(estado.get("s", "").startswith("200") and b"Villaprueba" in cuerpo,
              f"ficha con el cerrojo cogido: {estado.get('s')}")
    comprobar(dt < 2.0, f"ficha con el cerrojo cogido por otro: tardó {dt:.1f} s (antes esperaba al cerrojo)")

    # ── Contador de visitas: el volcado no se hace dentro de la petición ──────────────────────────────────────────
    env_v = {"REQUEST_METHOD": "GET", "PATH_INFO": "/", "QUERY_STRING": "", "REMOTE_ADDR": "127.0.0.9",
             "HTTP_USER_AGENT": "Mozilla/5.0 (Windows NT 10.0) Chrome/130 Safari/537.36"}
    app._visitas_estado["ultimo_volcado"] = 0.0                        # toca volcar ya
    _, dt = con_cerrojo_cogido(lambda: app._visitas_anotar(env_v, "200 OK", [("Content-Type", "text/html")], [b"x"], 0.1),
                               3.0)
    comprobar(dt < 1.0, f"anotar una visita con el cerrojo cogido por otro tardó {dt:.1f} s (el volcado era en la petición)")
    for _ in range(100):                                               # el hilo del volcado termina al soltar el cerrojo
        if not app._visitas_estado.get("volcando"):
            break
        time.sleep(0.05)
    comprobar(not app._visitas_estado.get("volcando"), "el volcado en segundo plano no termina")
    with app._db_lock:
        n = app._db.execute("SELECT COALESCE(SUM(peticiones), 0) FROM visitas_dia WHERE clase='persona'").fetchone()[0]
    comprobar(n >= 1, f"la visita no llegó a la base ({n})")
    app._visitas_estado.update(ultimo_volcado=0.0, volcando=True)      # con un volcado en marcha no se lanza otro
    antes = threading.active_count()
    app._visitas_anotar(env_v, "200 OK", [("Content-Type", "text/html")], [b"x"], 0.1)
    comprobar(threading.active_count() == antes, "se lanzó un segundo volcado con otro en marcha")
    app._visitas_estado["volcando"] = False

    # ── Interruptor apagado: vuelve a esperar ─────────────────────────────────────────────────────────────────────
    app._LECTURA_SIN_CERROJO = False
    _, dt = con_cerrojo_cogido(lambda: en_peticion(app._db_get_municipio, "Villaprueba", "murcia"), 1.5)
    comprobar(dt >= 1.0, f"con LECTURA_SIN_CERROJO=0 no esperó al cerrojo ({dt:.1f} s)")
    with app._db_leer() as con:
        comprobar(con is app._db, "con el interruptor apagado no usa la conexión compartida")
    app._LECTURA_SIN_CERROJO = True

    print(f"{bien[0]} bien, {len(mal)} mal")
    for m in mal:
        print("  MAL:", m)
    sys.stdout.flush()
    os._exit(1 if mal else 0)


if __name__ == "__main__":
    main()
