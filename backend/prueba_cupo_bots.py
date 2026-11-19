# encoding: utf-8
"""Prueba del freno a rastreadores del 16-11-2026: robots.txt y 403 para los que no traen visitas, cupo por hora para
el resto, reparto de Google/Bing en las fichas de empresa y la tabla «qué páginas pide cada bot». Sin red: base vacía
en una carpeta temporal y DNS inverso simulado (66.249.66.x es Google; las demás IP son de documentación).

    python backend/prueba_cupo_bots.py      (proceso pesado: importa la web; de uno en uno, ~2 min)
"""
import io
import os
import re
import socket
import sys
import tempfile
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

NAV = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
GBOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
OAI = "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; OAI-SearchBot/1.3; +https://openai.com/searchbot"
CHATGPT_USER = "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ChatGPT-User/1.0; +https://openai.com/bot"
AHREFS = "Mozilla/5.0 (compatible; AhrefsBot/7.0; +http://ahrefs.com/robot/)"
QLYZE = "Mozilla/5.0 (compatible; QlyzeBot/1.0)"
FB = "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)"


def _inverso(ip):
    if ip.startswith("66.249.66."):
        return (f"crawl-{ip.replace('.', '-')}.googlebot.com", [], [ip])
    raise socket.herror("sin nombre")


def _directo(nombre):
    m = re.match(r"crawl-(\d+)-(\d+)-(\d+)-(\d+)\.googlebot\.com$", nombre)
    return (nombre, [], [".".join(m.groups())] if m else [])


def main():
    os.environ.update(DATA_DIR=tempfile.mkdtemp(prefix="cupo_bots_"), HTTP_PROXY="http://127.0.0.1:9",
                      HTTPS_PROXY="http://127.0.0.1:9")
    import app
    for hilo in threading.enumerate():
        if hilo.name == "carga-place-menores":
            hilo.join(timeout=1800)
    socket.gethostbyaddr, socket.gethostbyname_ex = _inverso, _directo
    app._FRENO_PAGINAS_HORA = 10 ** 6          # que el freno por red (B) no se meta en medio
    mal, bien = [], [0]

    def comprobar(cond, texto):
        if cond:
            bien[0] += 1
        else:
            mal.append(texto)

    def peticion(ruta, ip, ua, metodo="GET"):
        path, _, query = ruta.partition("?")
        env = {"REQUEST_METHOD": metodo, "PATH_INFO": path, "QUERY_STRING": query, "HTTP_USER_AGENT": ua,
               "HTTP_X_FORWARDED_FOR": ip, "wsgi.input": io.BytesIO(b""), "CONTENT_LENGTH": "0"}
        res = {}

        def sr(estado, cab, exc=None):
            res["estado"], res["cab"] = estado, dict(cab)
        cuerpo = b"".join(app.app(env, sr))
        return res["estado"][:3], res["cab"], cuerpo

    # ── robots.txt y 403 ─────────────────────────────────────────────────────────────────────────────────────────
    _e, _c, robots = peticion("/robots.txt", "192.0.2.1", NAV)
    robots = robots.decode("utf-8") if not _c.get("Content-Encoding") else ""
    grupo = robots.split("\n\n")[0]
    for b in ("AhrefsBot", "DotBot", "QlyzeBot", "ExaSearchBot", "ElevenlabsCrawler"):
        comprobar(f"User-agent: {b}\n" in grupo, f"robots.txt sin {b} en el grupo «Disallow: /»")
    for b in ("Googlebot", "bingbot", "OAI-SearchBot", "PerplexityBot"):
        comprobar(b not in grupo, f"robots.txt echa a {b}")
    for ua in (AHREFS, QLYZE, "Mozilla/5.0 (compatible; DotBot/1.2; +https://opensiteexplorer.org/dotbot)"):
        est, _c, _b = peticion("/quien-soy", "192.0.2.2", ua)
        comprobar(est == "403", f"403: {ua[:40]} da {est}")
    est, _c, _b = peticion("/quien-soy", "192.0.2.2", "Mozilla/5.0 (compatible; ExaSearchBot/1.0)")
    comprobar(est == "200", f"ExaSearchBot (solo robots.txt) da {est}")

    # ── Cupo por hora ────────────────────────────────────────────────────────────────────────────────────────────
    comprobar(app._BOTS_PAGINAS_HORA == 300, f"cupo por hora {app._BOTS_PAGINAS_HORA}, esperaba 300")
    comprobar(app._BOTS_PAGINAS_HORA_IA_CITAN == 1500, f"cupo IA que citan {app._BOTS_PAGINAS_HORA_IA_CITAN}")
    app._BOTS_PAGINAS_HORA, app._BOTS_PAGINAS_HORA_IA_CITAN = 3, 5
    app._bots_hora.clear()
    res = [peticion("/quien-soy", "198.51.100.7", OAI)[0] for _ in range(7)]
    comprobar(res == ["200"] * 5 + ["429"] * 2, f"OAI-SearchBot (cupo de IA que cita): {res}")
    amz = "Mozilla/5.0 (compatible; Amzn-SearchBot/0.1)"
    res = [app._bot_frenado_por_hora(app._familia_ua(amz), "/quien-soy", "198.51.100.20", amz) for _ in range(4)]
    comprobar(res[:3] == [None] * 3 and res[3] and res[3][0].startswith("429"), f"Amzn-SearchBot (cupo normal): {res}")
    ppx = "Mozilla/5.0 (compatible; PerplexityBot/1.0)"
    res = [app._bot_frenado_por_hora(app._familia_ua(ppx), "/quien-soy", "198.51.100.21", ppx) for _ in range(6)]
    comprobar(res[:5] == [None] * 5 and res[5], f"PerplexityBot (cupo de IA que cita): {res}")
    est, cab, cuerpo = peticion("/quien-soy", "198.51.100.8", OAI)          # otra IP, misma familia
    comprobar(est == "429" and cab.get("Retry-After") == "600" and len(cuerpo) < 80, f"429: {est} {cab}")
    est, _c, cuerpo = peticion("/quien-soy", "198.51.100.8", OAI, metodo="HEAD")
    comprobar(est == "429" and cuerpo == b"", "429 con HEAD lleva cuerpo")
    for ruta in ("/robots.txt", "/sitemap.xml", "/static/style.css", "/api/diagnostico-arranque", "/manifest.json"):
        comprobar(app._bot_frenado_por_hora("OAI-SearchBot", ruta, "198.51.100.7", OAI) is None, f"frena {ruta}")
    comprobar(app._bots_frenadas_hora["OAI-SearchBot"] == 4, f"frenadas {dict(app._bots_frenadas_hora)}")
    app._bots_hora.clear()
    comprobar(app._bot_frenado_por_hora("Amzn-SearchBot", "/quien-soy", "198.51.100.9", amz) is None,
              "una familia gasta el cupo de otra")
    # sin cupo: navegadores, peticiones que hace una persona (ChatGPT-User), vistas previas, clientes sin nombre
    for _ in range(10):
        comprobar(peticion("/quien-soy", "198.51.100.7", NAV)[0] == "200", "navegador frenado")
        comprobar(app._bot_frenado_por_hora(app._familia_ua(CHATGPT_USER), "/quien-soy", "198.51.100.7",
                                            CHATGPT_USER) is None, "ChatGPT-User frenado")
        comprobar(app._bot_frenado_por_hora(app._familia_ua(FB), "/quien-soy", "198.51.100.7", FB) is None,
                  "facebookexternalhit frenado")
    comprobar(app._familia_ua(FB) == "otro_cliente", f"familia de facebookexternalhit: {app._familia_ua(FB)}")

    # ── Google y Bing ────────────────────────────────────────────────────────────────────────────────────────────
    app._buscadores_verificados.clear()
    for i in range(20):                         # fichas de municipio y portada: nunca
        comprobar(app._bot_frenado_por_hora("Googlebot", "/", f"66.249.66.{i % 5 + 1}", GBOT) is None,
                  "Googlebot verificado frenado fuera de las fichas de empresa")
    app._BUSCADOR_EMPRESA_CUPO, app._BUSCADOR_EMPRESA_POR_MIN = 3, 1
    app._buscador_empresa.clear()
    res = [app._bot_frenado_por_hora("Googlebot", f"/gl/empresa/B{i:08d}", "66.249.66.1", GBOT) for i in range(5)]
    comprobar(res[:3] == [None] * 3 and res[3] == ("503 Service Unavailable", "120") and res[4], f"empresa: {res}")
    est, cab, _b = peticion("/empresa/B00000099", "66.249.66.2", GBOT)
    comprobar(est == "503" and cab.get("Retry-After") == "120", f"Googlebot en ficha de empresa: {est}")
    # un Googlebot falso (sin DNS de Google) va al cupo por hora como cualquier otro
    app._bots_hora.clear()
    res = [app._bot_frenado_por_hora("Googlebot", "/", "198.51.100.66", GBOT) for _ in range(6)]
    comprobar(res[:3] == [None] * 3 and res[3] and res[3][0].startswith("429"), f"Googlebot falso: {res}")

    # ── Páginas ya guardadas para Google, Bing, OAI-SearchBot y PerplexityBot ───────────────────────────────────
    app._BOTS_PAGINAS_HORA = app._BOTS_PAGINAS_HORA_IA_CITAN = 10 ** 6
    app._bots_hora.clear()
    clave = app._bots_cache_clave
    comprobar(clave("/", "muni=Palma&provincia=illes_balears") == ("/", (("muni", "Palma"), ("provincia", "illes_balears"))),
              "clave de la ficha")
    comprobar(clave("/ca/", "provincia=x&muni=y") is not None and clave("/gl/entidad", "id=7") is not None
              and clave("/empresa/B12345678", "") is not None, "fichas sin clave")
    for ruta, q in (("/", "muni=a&pag=2"), ("/", "q=hola"), ("/", ""), ("/rankings", "x=1"), ("/entidad", ""),
                    ("/empresa/B1", "x=1"), ("/admin/visitas", ""), ("/quien-soy", "")):
        comprobar(clave(ruta, q) is None, f"con clave de caché: {ruta}?{q}")
    import gzip as _gz
    montadas = []
    original = app._route_get_i18n

    def falsa(path, qs, gzip_ok=False, query_string=""):
        montadas.append(path + "?" + query_string)
        html_ = ("<html>ficha %d</html>" % len(montadas)).encode()
        cab = {"Content-Type": "text/html; charset=utf-8"}
        if gzip_ok:
            cab["Content-Encoding"] = "gzip"
            html_ = _gz.compress(html_)
        if "cookie" in query_string:
            cab["Set-Cookie"] = "x=1"
        return 200, cab, html_
    app._route_get_i18n = falsa
    try:
        def gzpet(ruta, ua, gz=True, metodo="GET"):
            path, _, query = ruta.partition("?")
            env = {"REQUEST_METHOD": metodo, "PATH_INFO": path, "QUERY_STRING": query, "HTTP_USER_AGENT": ua,
                   "HTTP_X_FORWARDED_FOR": "192.0.2.50", "wsgi.input": io.BytesIO(b""), "CONTENT_LENGTH": "0"}
            if gz:
                env["HTTP_ACCEPT_ENCODING"] = "gzip"
            res = {}
            cuerpo = b"".join(app.app(env, lambda e, c, x=None: res.update(e=e, c=dict(c))))
            if res["c"].get("Content-Encoding") == "gzip":
                cuerpo = _gz.decompress(cuerpo)
            return res["e"][:3], res["c"], cuerpo
        app._bots_cache_vaciar()
        F = "/ca/?muni=Palma&provincia=illes_balears"
        a = gzpet(F, OAI)
        b = gzpet(F, OAI)
        c = gzpet(F, GBOT)
        d = gzpet(F, GBOT, gz=False)
        comprobar(len(montadas) == 1 and a[2] == b[2] == c[2] == d[2] == b"<html>ficha 1</html>",
                  f"bots: montadas {len(montadas)} {a[2]} {b[2]} {d[2]}")
        comprobar(d[1].get("Content-Encoding") is None and d[1]["Content-Length"] == str(len(d[2])), "sin gzip")
        gzpet(F, NAV)
        gzpet(F, NAV)
        comprobar(len(montadas) == 3, f"personas servidas de la caché de bots: {len(montadas)}")
        gzpet(F, "Mozilla/5.0 (compatible; Amzn-SearchBot/0.1)")
        comprobar(len(montadas) == 4, "otro bot servido de la caché de los buscadores")
        gzpet("/?muni=X&provincia=y&cookie=1", OAI)
        gzpet("/?muni=X&provincia=y&cookie=1", OAI)
        comprobar(len(montadas) == 6, "guardada una respuesta con cookie")
        # cualquier POST o /admin la vacía
        app._app_wsgi({"REQUEST_METHOD": "POST", "PATH_INFO": "/api/evento", "QUERY_STRING": "",
                       "wsgi.input": io.BytesIO(b""), "CONTENT_LENGTH": "0", "HTTP_USER_AGENT": NAV}, lambda *x: None)
        gzpet(F, OAI)
        comprobar(len(montadas) == 7, "un POST no vacía la caché de bots")
        gzpet("/admin/revision", NAV)
        gzpet(F, OAI)
        comprobar(len(montadas) == 8, f"/admin no vacía la caché de bots ({len(montadas)})")
        src = open(os.path.join(BASE_DIR, "app.py"), encoding="utf-8").read()
        i = src.index("def _vaciar_caches_de_nombres")
        comprobar("_bots_cache_vaciar()" in src[i:i + 1500], "_vaciar_caches_de_nombres no vacía la caché de bots")
        # tope de tamaño
        app._BOTS_CACHE_MAX_MB = 0.0001
        app._bots_cache_guardar(("/", (("muni", "z"),)), 200, {"Content-Type": "text/html", "Content-Encoding": "gzip"},
                                b"x" * 500)
        comprobar(app._bots_cache_estado()["mb"] <= 0.0001 * 1.01, f"tope: {app._bots_cache_estado()}")
        app._BOTS_CACHE_MAX_MB = 48
    finally:
        app._route_get_i18n = original
    # _pagina_cacheada: copia de 5 horas -> el bot la recibe sin montar nada; una persona lanza el remontaje
    with app._paginas_lock:
        app._paginas_cache[("es", "/prueba-bot")] = {"gz": _gz.compress(b"<html>vieja</html>"),
                                                    "ts": time.time() - 5 * 3600, "refrescando": False, "grupo": None}
    n_m = []
    tk = app._BOT_PREFIERE_CACHE.set(True)
    try:
        r = app._pagina_cacheada("/prueba-bot", [], lambda: n_m.append(1) or "<html>nueva</html>")
    finally:
        app._BOT_PREFIERE_CACHE.reset(tk)
    comprobar(r[2] == b"<html>vieja</html>" and not n_m and not app._paginas_cache[("es", "/prueba-bot")]["refrescando"],
              "bot: no recibe la copia vieja o lanza el montaje")
    r = app._pagina_cacheada("/prueba-bot", [], lambda: n_m.append(1) or "<html>nueva</html>")
    comprobar(r[2] == b"<html>nueva</html>" and n_m, "persona: recibe una copia de 5 h (más de _PAGINAS_MAX_VIEJA)")

    # ── Qué páginas pide cada bot ────────────────────────────────────────────────────────────────────────────────
    with app._visitas_lock:
        filas = {n: v[0] for (d, c, n), v in app._visitas_pend.items() if c == "bot_ruta"}
    comprobar(filas.get("OAI-SearchBot /quien-soy", 0) >= 7, f"bot_ruta: {filas}")
    comprobar(not any(n.startswith("personas") for n in filas), "personas en bot_ruta")
    comprobar(all(not re.search(r"\d{5,}", n) for n in filas), f"bot_ruta con un NIF: {filas}")
    app._visitas_volcar()
    with app._db_lock:
        n = app._db.execute("SELECT count(*) FROM visitas_dia WHERE clase='bot_ruta'").fetchone()[0]
    comprobar(n >= 1, "bot_ruta no llega a la base")

    print(f"{bien[0]} bien, {len(mal)} mal")
    for m in mal:
        print("  MAL:", m)
    sys.exit(1 if mal else 0)


if __name__ == "__main__":
    main()
