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
    app._BOTS_PAGINAS_HORA = 5
    app._bots_hora.clear()
    res = [peticion("/quien-soy", "198.51.100.7", OAI)[0] for _ in range(7)]
    comprobar(res == ["200"] * 5 + ["429"] * 2, f"OAI-SearchBot: {res}")
    est, cab, cuerpo = peticion("/quien-soy", "198.51.100.8", OAI)          # otra IP, misma familia
    comprobar(est == "429" and cab.get("Retry-After") == "600" and len(cuerpo) < 80, f"429: {est} {cab}")
    est, _c, cuerpo = peticion("/quien-soy", "198.51.100.8", OAI, metodo="HEAD")
    comprobar(est == "429" and cuerpo == b"", "429 con HEAD lleva cuerpo")
    for ruta in ("/robots.txt", "/sitemap.xml", "/static/style.css", "/api/diagnostico-arranque", "/manifest.json"):
        comprobar(app._bot_frenado_por_hora("OAI-SearchBot", ruta, "198.51.100.7", OAI) is None, f"frena {ruta}")
    comprobar(app._bots_frenadas_hora["OAI-SearchBot"] == 4, f"frenadas {dict(app._bots_frenadas_hora)}")
    comprobar(app._bot_frenado_por_hora("PerplexityBot", "/quien-soy", "198.51.100.9",
                                        "Mozilla/5.0 (compatible; PerplexityBot/1.0)") is None,
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
    comprobar(res[:5] == [None] * 5 and res[5] and res[5][0].startswith("429"), f"Googlebot falso: {res}")

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
