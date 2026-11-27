# encoding: utf-8
"""Prueba de las páginas guardadas y el cambio de día (27-11-2026). Sin red: base vacía en una carpeta temporal.
Comprueba que una página montada otro día (hora peninsular) no se sirve a las personas, que a los rastreadores de
_BOT_PREFIERE_CACHE sí pero se vuelve a montar, que el cambio de día vuelve a montar las fijas una sola vez, que la copia
de arranque no restaura páginas de otro día, el <meta name="dp-montada"> y las portadas del diagnóstico público.

    python backend/prueba_paginas_dia.py      (proceso pesado: importa la web; de uno en uno)
"""
import base64
import contextvars
import gzip
import json
import os
import sys
import tempfile
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)


def main():
    os.environ.update(DATA_DIR=tempfile.mkdtemp(prefix="paginas_dia_"), HTTP_PROXY="http://127.0.0.1:9",
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

    dia_real = app._paginas_dia
    falso = {"dia": "2026-11-26"}
    app._paginas_dia = lambda ts=None: falso["dia"]
    calentadas = []
    app._calentar_portada = lambda: calentadas.append(falso["dia"])
    montajes = []

    def montar():
        montajes.append(falso["dia"])
        return f"<!doctype html><html><head><title>p</title></head><body>montaje {len(montajes)}</body></html>"

    def pedir(bot=False, lang="es"):
        def _una():
            app._I18N_IDIOMA.set(lang)
            app._BOT_PREFIERE_CACHE.set(bot)
            return app._pagina_cacheada("/prueba-dia", [], montar)
        code, hdrs, cuerpo = contextvars.copy_context().run(_una)
        return cuerpo.decode("utf-8")

    def esperar_montajes(n, max_s=10):
        fin = time.time() + max_s
        while len(montajes) < n and time.time() < fin:
            time.sleep(0.05)

    # ── Sello ────────────────────────────────────────────────────────────────────────────────────────────────────
    s = app._paginas_sello("<html><head><title>x</title></head></html>", 0)
    comprobar(s.startswith('<html><head><meta name="dp-montada" content="1970-01-01T00:00:00Z"><title>'), f"sello: {s}")
    comprobar(app._paginas_sello("sin cabecera", 0) == "sin cabecera", "sello sin <head>")

    # ── Mismo día: se monta una vez ──────────────────────────────────────────────────────────────────────────────
    t1 = pedir()
    comprobar(len(montajes) == 1 and "montaje 1" in t1, f"primer montaje: {montajes}")
    comprobar('<meta name="dp-montada" content="' in t1, "la página guardada no lleva dp-montada")
    t1b = pedir()
    comprobar(len(montajes) == 1 and t1b == t1, "el mismo día se volvió a montar")
    comprobar(not calentadas, "se calentó sin cambiar el día")

    # ── Cambio de día: las personas no reciben la de ayer ────────────────────────────────────────────────────────
    falso["dia"] = "2026-11-27"
    t2 = pedir()
    comprobar(len(montajes) == 2 and "montaje 2" in t2, f"de otro día servida a una persona: {montajes}")
    time.sleep(0.3)
    comprobar(calentadas == ["2026-11-27"], f"cambio de día sin calentar las fijas: {calentadas}")
    pedir(lang="gl")                                   # otra página de otro idioma: el aviso ya se dio hoy
    time.sleep(0.3)
    comprobar(calentadas == ["2026-11-27"], f"se calentó dos veces el mismo día: {calentadas}")
    n = len(montajes)
    pedir()
    comprobar(len(montajes) == n, "la de hoy se volvió a montar")

    # ── Rastreador: recibe la de ayer, pero se vuelve a montar ───────────────────────────────────────────────────
    falso["dia"] = "2026-11-28"
    n = len(montajes)
    tb = pedir(bot=True)
    comprobar(tb == t2, "el rastreador no recibió la copia que había")
    esperar_montajes(n + 1)
    comprobar(len(montajes) == n + 1, f"la visita del rastreador no la mandó montar: {len(montajes)} de {n + 1}")
    with app._paginas_lock:
        e = app._paginas_cache.get(("es", "/prueba-dia"))
    comprobar(e and e.get("dia") == "2026-11-28" and not e["refrescando"], f"tras volver a montar: {e and e.get('dia')}")
    n = len(montajes)
    pedir()
    comprobar(len(montajes) == n, "tras el montaje del rastreador, la persona hizo montar otra vez")

    # ── Copia de arranque: solo las páginas montadas hoy ─────────────────────────────────────────────────────────
    ahora = time.time()
    corte = ahora - 3600
    app._paginas_dia = lambda ts=None: "AYER" if ts is not None and ts < corte else "HOY"
    gz = base64.b64encode(gzip.compress(b"<html><head></head><body>copia</body></html>")).decode("ascii")
    datos = {"version": app._COPIA_ARRANQUE_VERSION, "huella": app._copia_arranque_huella(), "guardada": ahora,
             "indice": [], "indice_ts": ahora, "rk_empresas": {},
             "paginas": [[["es", "/"], gz, ahora - 7200], [["gl", "/"], gz, ahora - 60]]}
    with gzip.open(app.COPIA_ARRANQUE_FILE, "wt", encoding="utf-8") as f:
        json.dump(datos, f)
    with app._paginas_lock:
        app._paginas_cache.clear()
        app._paginas_cerrojos.clear()
    with app._indice_transparencia_cache_lock:
        app._INDICE_TRANSPARENCIA_CACHE.update(filas=None, ts=0.0)
    app._copia_arranque_cargar()
    with app._paginas_lock:
        claves = set(app._paginas_cache)
    comprobar(claves == {("gl", "/")}, f"copia de arranque: {claves}")
    comprobar("1 de otro día" in app._copia_arranque_estado["motivo"], f"motivo: {app._copia_arranque_estado}")

    # ── Diagnóstico público ──────────────────────────────────────────────────────────────────────────────────────
    app._paginas_dia = dia_real
    d = app._diagnostico_arranque_publico()
    p = d.get("portadas") or {}
    comprobar(set(p) == {"gl"} and p["gl"]["de_copia"], f"portadas del diagnóstico: {p}")
    comprobar(p.get("gl", {}).get("montada_utc") == time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ahora - 60)),
              f"montada_utc: {p}")
    json.dumps(d)                                        # que se pueda servir como JSON

    print(f"{bien[0]} OK, {len(mal)} MAL")
    for m in mal:
        print("  MAL:", m)
    print("TODO BIEN" if not mal else "HAY FALLOS")
    sys.exit(1 if mal else 0)


if __name__ == "__main__":
    main()
