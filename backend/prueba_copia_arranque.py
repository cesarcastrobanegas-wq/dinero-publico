# encoding: utf-8
"""Prueba de la copia de arranque (16-11-2026). Sin red: base vacía en una carpeta temporal, sin hilos de fondo.
Guarda la copia, simula un reinicio vaciando lo calculado y la vuelve a cargar; comprueba que no se usa si cambia
lo que decide qué nombres se enseñan, si es vieja o de otra versión, y que se borra al cargar administradores.

    python backend/prueba_copia_arranque.py      (proceso pesado: importa la web; de uno en uno, ~2 min)
"""
import gzip
import json
import os
import sys
import tempfile
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)


def main():
    os.environ.update(DATA_DIR=tempfile.mkdtemp(prefix="copia_arranque_"), HTTP_PROXY="http://127.0.0.1:9",
                      HTTPS_PROXY="http://127.0.0.1:9", DINERO_HILOS_EN_POST_FORK="1")
    os.environ.pop("EXCLUSION_CLAVE", None)
    import app
    app._DISCO_CONFIABLE = True
    mal, bien = [], [0]

    def comprobar(cond, texto):
        if cond:
            bien[0] += 1
        else:
            mal.append(texto)

    def reiniciar():
        """Lo que hay en memoria justo después de un reinicio."""
        with app._indice_transparencia_cache_lock:
            app._INDICE_TRANSPARENCIA_CACHE.update(filas=None, ts=0.0)
        app._rk_empresas.update(ts=0.0, nacional=([], []), provincias={})
        with app._paginas_lock:
            app._paginas_cache.clear()
            app._paginas_cerrojos.clear()
        app._copia_arranque_estado.update(cargada=False, motivo="")

    # ── Sin copia ───────────────────────────────────────────────────────────────────────────────────────────────
    app._copia_arranque_borrar()
    app._copia_arranque_cargar()
    comprobar(not app._copia_arranque_estado["cargada"] and app._copia_arranque_estado["motivo"] == "no hay copia",
              f"sin copia: {app._copia_arranque_estado}")

    # ── Guardar: lo que deja el precálculo ──────────────────────────────────────────────────────────────────────
    filas = app._calcular_indice_transparencia()
    with app._indice_transparencia_cache_lock:
        app._INDICE_TRANSPARENCIA_CACHE.update(filas=filas, ts=time.time())
    with app._rk_empresas_lock:
        app._rk_empresas_calcular()
    app._calentar_portada()
    with app._paginas_lock:
        fijas = {k: e["gz"] for k, e in app._paginas_cache.items() if app._pagina_fija(k)}
    comprobar(len(fijas) >= 3, f"páginas fijas montadas: {len(fijas)}")
    app._copia_arranque_guardar()
    comprobar(os.path.exists(app.COPIA_ARRANQUE_FILE), "no se guardó la copia")
    with gzip.open(app.COPIA_ARRANQUE_FILE, "rt", encoding="utf-8") as f:
        guardada = json.load(f)
    comprobar(len(guardada["paginas"]) == len(fijas), f"páginas guardadas {len(guardada['paginas'])} de {len(fijas)}")
    comprobar(not os.path.exists(app.COPIA_ARRANQUE_FILE + ".tmp"), "queda el .tmp")

    # Una copia de otra copia no se guarda (el Índice de la copia tiene ts 0)
    reiniciar()
    app._copia_arranque_cargar()
    mtime = os.path.getmtime(app.COPIA_ARRANQUE_FILE)
    time.sleep(1.1)
    app._copia_arranque_guardar()
    comprobar(os.path.getmtime(app.COPIA_ARRANQUE_FILE) == mtime, "se guardó una copia de la copia")

    # ── Cargar tras un reinicio ─────────────────────────────────────────────────────────────────────────────────
    reiniciar()
    app._copia_arranque_cargar()
    est = app._copia_arranque_estado
    comprobar(est["cargada"], f"no se cargó: {est}")
    comprobar(app._INDICE_TRANSPARENCIA_CACHE["ts"] == 0.0 and app._indice_copia_de_arranque(), "Índice no marcado")
    comprobar(json.dumps(app._INDICE_TRANSPARENCIA_CACHE["filas"], sort_keys=True, ensure_ascii=False)
              == json.dumps(json.loads(json.dumps(filas, ensure_ascii=False)), sort_keys=True, ensure_ascii=False),
              "el Índice cargado no es el guardado")
    comprobar(app._rk_empresas["ts"] > 0 and isinstance(app._rk_empresas["nacional"], tuple), "top de empresas")
    with app._paginas_lock:
        cargadas = {k: e for k, e in app._paginas_cache.items()}
    comprobar(set(cargadas) == set(fijas), "no están las mismas páginas")
    comprobar(all(cargadas[k]["gz"] == fijas[k] and cargadas[k]["de_copia"] and cargadas[k]["refrescando"]
                  for k in fijas), "páginas distintas o sin marcar")

    # Se sirven sin montar nada ni lanzar recálculos
    hilos_antes = {h.name for h in threading.enumerate()}
    filas_c = app._indice_transparencia_cacheado()
    comprobar(filas_c is app._INDICE_TRANSPARENCIA_CACHE["filas"], "no sirve el Índice de la copia")
    comprobar(not app._indice_fondo["activo"], "el Índice de la copia lanzó un recálculo antes del feed")
    montadas = app._paginas_stats["montadas"]
    code, hdrs, cuerpo = app._route_get_i18n("/", {}, gzip_ok=True, query_string="")
    comprobar(code == 200 and cuerpo == fijas[("es", "/")], "la portada no sale de la copia")
    comprobar(app._paginas_stats["montadas"] == montadas, "montó la portada en la petición")
    nuevos = {h.name for h in threading.enumerate()} - hilos_antes
    comprobar("pagina-cache" not in nuevos and "indice-refresco" not in nuevos, f"hilos lanzados: {nuevos}")
    # Pasado COPIA_ARRANQUE_INDICE_MAX_S, vuelve a lo de siempre
    ts0 = app._ARRANQUE_TS
    app._ARRANQUE_TS = time.time() - app.COPIA_ARRANQUE_INDICE_MAX_S - 1
    comprobar(not app._indice_copia_de_arranque(), "la copia del Índice no caduca")
    app._ARRANQUE_TS = ts0

    # Tras el precálculo, _calentar_portada vuelve a montar las de la copia
    with app._indice_transparencia_cache_lock:
        app._INDICE_TRANSPARENCIA_CACHE.update(filas=filas, ts=time.time())
    app._calentar_portada()
    for h in threading.enumerate():
        if h.name == "pagina-cache":
            h.join(timeout=300)
    with app._paginas_lock:
        quedan = [k for k, e in app._paginas_cache.items() if e.get("de_copia")]
    comprobar(not quedan, f"siguen de la copia tras calentar: {quedan}")

    # ── Cuándo NO se usa ────────────────────────────────────────────────────────────────────────────────────────
    app._copia_arranque_guardar()

    def carga_tras(cambio, deshacer, motivo):
        reiniciar()
        cambio()
        try:
            app._copia_arranque_cargar()
        finally:
            deshacer()
        e = app._copia_arranque_estado
        comprobar(not e["cargada"] and motivo in e["motivo"] and app._INDICE_TRANSPARENCIA_CACHE["filas"] is None
                  and not app._paginas_cache, f"se usó la copia ({motivo}): {e}")

    def poner_clave():
        os.environ["EXCLUSION_CLAVE"] = "otra-clave-de-prueba"
    carga_tras(poner_clave, lambda: os.environ.pop("EXCLUSION_CLAVE", None), "supresiones")

    orig = app._cargos_suprimidos.SUPRESIONES_FILE
    falso = os.path.join(os.environ["DATA_DIR"], "supresiones_cambiadas.json")
    with open(falso, "w", encoding="utf-8") as f:
        f.write('{"supresiones": [{"huella": "x"}]}')

    def cambiar_supresiones():
        app._cargos_suprimidos.SUPRESIONES_FILE = falso

    def deshacer_supresiones():
        app._cargos_suprimidos.SUPRESIONES_FILE = orig
    carga_tras(cambiar_supresiones, deshacer_supresiones, "supresiones")

    def nuevo_admin():
        with open(app.ADMINISTRADORES_BORME_FILE, "w", encoding="utf-8") as f:
            f.write("{}")
    carga_tras(nuevo_admin, lambda: os.remove(app.ADMINISTRADORES_BORME_FILE), "administradores")

    def otra_version():
        app._COPIA_ARRANQUE_VERSION = 2

    def version_buena():
        app._COPIA_ARRANQUE_VERSION = 1
    carga_tras(otra_version, version_buena, "otra versión")

    viejo = time.time() - app.COPIA_ARRANQUE_MAX_EDAD - 60
    carga_tras(lambda: os.utime(app.COPIA_ARRANQUE_FILE, (viejo, viejo)), lambda: None, "vieja")

    # Copia estropeada: no rompe el arranque
    with open(app.COPIA_ARRANQUE_FILE, "wb") as f:
        f.write(b"no es gzip")
    carga_tras(lambda: None, lambda: None, "error")

    # Al cargar administradores nuevos se borra
    app._copia_arranque_guardar()
    src = open(os.path.join(BASE_DIR, "app.py"), encoding="utf-8").read()
    i = src.index("def _vaciar_caches_de_nombres")
    comprobar("_copia_arranque_borrar()" in src[i:i + 1500], "_vaciar_caches_de_nombres no borra la copia")

    print(f"{bien[0]} bien, {len(mal)} mal")
    for m in mal:
        print("  MAL:", m)
    sys.exit(1 if mal else 0)


if __name__ == "__main__":
    main()
