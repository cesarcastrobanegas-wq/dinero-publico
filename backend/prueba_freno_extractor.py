# encoding: utf-8
"""Prueba del freno de extractores (A y B) y de /rankings sin combinaciones (C), 08-11-2026. Sin red: base vacía en una
carpeta temporal, el DNS inverso simulado (nada sale a internet) y la función WSGI de verdad (app.app). Las IP son de
los rangos de documentación (192.0.2.x, 198.51.100.x, 203.0.113.x), de Alibaba Cloud (47.x, las que se bloquean) y
66.249.66.x (Google), solo como texto.

    python backend/prueba_freno_extractor.py      (proceso pesado: importa la web; de uno en uno, ~2 min)
"""
import io
import os
import re
import socket
import sys
import tempfile
import threading
from urllib.parse import parse_qs, urlsplit

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

NAV = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
GBOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
TOKEN = "token-de-prueba-0123456789abcdef"

# DNS inverso simulado: 66.249.66.x es de Google (y resuelve de vuelta); 203.0.113.66 dice ser de Google pero su nombre
# no resuelve a ella; el resto no tiene nombre. Se cuentan las consultas.
CONSULTAS = []


def _inverso(ip):
    CONSULTAS.append(ip)
    if ip.startswith("66.249.66."):
        return (f"crawl-{ip.replace('.', '-')}.googlebot.com", [], [ip])
    if ip == "203.0.113.66":
        return ("crawl-1-2-3-4.googlebot.com", [], [ip])
    raise socket.herror("sin nombre")


def _directo(nombre):
    m = re.match(r"crawl-(\d+)-(\d+)-(\d+)-(\d+)\.googlebot\.com$", nombre)
    return (nombre, [], [".".join(m.groups())] if m else [])


def main():
    os.environ.update(DATA_DIR=tempfile.mkdtemp(prefix="freno_"), HTTP_PROXY="http://127.0.0.1:9",
                      HTTPS_PROXY="http://127.0.0.1:9", ADMIN_TOKEN=TOKEN)
    for v in ("FRENO_REDES_BLOQUEADAS", "FRENO_PAGINAS_HORA_RED"):
        os.environ.pop(v, None)
    import app
    for hilo in threading.enumerate():
        if hilo.name == "carga-place-menores":
            hilo.join(timeout=1800)
    socket.gethostbyaddr, socket.gethostbyname_ex = _inverso, _directo
    mal, bien = [], [0]

    def comprobar(cond, texto):
        if cond:
            bien[0] += 1
        else:
            mal.append(texto)

    def peticion(ruta, ip, ua=NAV, metodo="GET", token=None):
        path, _, query = ruta.partition("?")
        env = {"REQUEST_METHOD": metodo, "PATH_INFO": path, "QUERY_STRING": query, "HTTP_USER_AGENT": ua,
               "HTTP_X_FORWARDED_FOR": ip, "wsgi.input": io.BytesIO(b""), "CONTENT_LENGTH": "0"}
        if token:
            env["HTTP_X_ADMIN_TOKEN"] = token
        res = {}

        def sr(estado, cab, exc=None):
            res["estado"], res["cab"] = estado, dict(cab)
        cuerpo = b"".join(app.app(env, sr))
        return res["estado"][:3], res["cab"], cuerpo

    def frenadas(nombre):
        with app._visitas_lock:
            return sum(v[0] for (d, c, n), v in app._visitas_pend.items() if c == "freno" and n == nombre)

    def personas():
        with app._visitas_lock:
            return sum(v[0] for (d, c, n), v in app._visitas_pend.items() if c == "persona")

    # ── A: redes de Alibaba Cloud ─────────────────────────────────────────────────────────────────────────────────
    comprobar(app._FRENO_PAGINAS_HORA == 600, f"límite B por defecto {app._FRENO_PAGINAS_HORA}, esperaba 600")
    comprobar([str(r) for r in app._FRENO_REDES] == ["47.74.0.0/15", "47.76.0.0/14", "47.80.0.0/13"], "redes de A")
    antes = personas()
    for ip in ("47.79.10.5", "47.82.8.200", "47.74.0.1", "47.87.255.254"):
        est, cab, cuerpo = peticion("/rankings?pag_alc=2&pag_idx=3", ip)
        comprobar(est == "403" and len(cuerpo) < 20 and cab.get("Cache-Control") == "no-store", f"A: {ip} da {est}")
    comprobar(frenadas("A_bloqueada") == 4, f"A: contadas {frenadas('A_bloqueada')}, esperaba 4")
    comprobar(personas() == antes, "A: lo bloqueado cuenta como visita")
    for ip in ("47.73.255.255", "47.88.0.1"):
        comprobar(app._freno_extractores({"PATH_INFO": "/", "HTTP_X_FORWARDED_FOR": ip, "HTTP_USER_AGENT": NAV}) is None,
                  f"A: {ip} (fuera del rango) bloqueada")
    est, _c, cuerpo = peticion("/", "47.79.10.5", metodo="HEAD")
    comprobar(est == "403" and cuerpo == b"", "A: HEAD con cuerpo")
    # Nunca: /admin, el diagnóstico, el token y Google/Bing verificados.
    for ruta in ("/admin/revision", "/admin/cache-db", "/api/diagnostico-arranque"):
        comprobar(app._freno_extractores({"PATH_INFO": ruta, "HTTP_X_FORWARDED_FOR": "47.79.10.5",
                                          "HTTP_USER_AGENT": NAV}) is None, f"A: frena {ruta}")
    comprobar(app._freno_extractores({"PATH_INFO": "/rankings", "HTTP_X_FORWARDED_FOR": "47.79.10.5",
                                      "HTTP_USER_AGENT": "curl/8", "HTTP_X_ADMIN_TOKEN": TOKEN}) is None,
              "A: frena una petición con el token")
    comprobar(app._freno_extractores({"PATH_INFO": "/rankings", "HTTP_X_FORWARDED_FOR": "47.79.10.5",
                                      "HTTP_USER_AGENT": "curl/8", "HTTP_X_ADMIN_TOKEN": "otro"}) is not None,
              "A: un token falso pasa")
    comprobar(app._freno_extractores({"PATH_INFO": "/", "HTTP_X_FORWARDED_FOR": "47.79.10.5", "HTTP_USER_AGENT": GBOT})
              is not None, "A: un Googlebot falso (sin DNS de Google) pasa")

    # ── Verificación de buscadores por DNS inverso ───────────────────────────────────────────────────────────────
    app._buscadores_verificados.clear()
    comprobar(app._buscador_verificado("66.249.66.1", GBOT), "Googlebot verdadero no verificado")
    comprobar(not app._buscador_verificado("66.249.66.2", NAV), "con exigir_ua (por defecto) verifica un navegador")
    comprobar(app._buscador_verificado("66.249.66.2", NAV, exigir_ua=False), "Google con nombre de navegador no verificado")
    comprobar(not app._buscador_verificado("203.0.113.66", GBOT), "nombre de Google que no resuelve a la IP, verificado")
    comprobar(not app._buscador_verificado("198.51.100.9", GBOT), "IP sin nombre verificada como Google")

    # ── B: límite por red y hora ─────────────────────────────────────────────────────────────────────────────────
    app._FRENO_PAGINAS_HORA = 5
    T = 1_800_000_000.0                                   # una hora fija (en segundos)
    f = lambda ip, ruta="/rankings", ua=NAV, t=T, **extra: app._freno_extractores(
        dict({"PATH_INFO": ruta, "REQUEST_METHOD": "GET", "HTTP_X_FORWARDED_FOR": ip, "HTTP_USER_AGENT": ua}, **extra), t)
    res = [f(f"198.51.100.{i}") for i in range(1, 8)]     # 7 IP distintas de la MISMA red
    comprobar(res[:5] == [None] * 5 and all(r and r[0].startswith("429") for r in res[5:]), f"B: {[r and r[0] for r in res]}")
    espera = dict(res[5][2]).get("Retry-After")
    comprobar(espera == str(int(T // 3600 + 1) * 3600 - int(T)) or int(espera) >= 60, f"B: Retry-After {espera}")
    comprobar(f("192.0.2.1") is None, "B: frena a otra red")
    comprobar(all(f("198.51.100.3", ruta=r) is None for r in ("/static/style.css", "/sw.js", "/manifest.json",
                                                            "/robots.txt", "/api/evento", "/admin/revision")),
              "B: frena estáticos o /admin")
    comprobar(f("198.51.100.3", HTTP_X_ADMIN_TOKEN=TOKEN) is None, "B: frena con el token (flujos de Actions)")
    comprobar(f("198.51.100.3", ua="DineroPublico-RevisionPrivacidad/1.0", HTTP_X_ADMIN_TOKEN=TOKEN) is None,
              "B: frena la revisión de privacidad con token")
    comprobar(f("198.51.100.3", t=T + 3600) is None, "B: no se reinicia a la hora siguiente")
    comprobar(frenadas("B_redes") == 1, f"B: redes frenadas {frenadas('B_redes')}, esperaba 1")
    # Google verificado (aunque diga ser navegador) nunca se frena; y como mucho una consulta DNS fallida por red y hora.
    T2 = T + 7200
    for i in range(1, 30):
        r = f(f"66.249.66.{i}", t=T2)
        if r:
            mal.append(f"B: frena a Google verificado (66.249.66.{i}, {r[0]})")
            break
    else:
        bien[0] += 1
    comprobar(frenadas("B_buscador_verificado") >= 20, f"B: Google verificado contado {frenadas('B_buscador_verificado')}")
    CONSULTAS.clear()
    for i in range(1, 40):
        f(f"192.0.2.{i}", t=T2)
    comprobar(len(CONSULTAS) == 1, f"B: {len(CONSULTAS)} consultas DNS para una red que no es buscador, esperaba 1")
    # Sin IP guardada en ningún sitio.
    texto = repr(app._freno_estado) + repr(app._visitas_pend)
    comprobar(not any(x in texto for x in ("198.51.100", "192.0.2.", "66.249.66", "47.79.10")), "B: hay IP guardadas")
    app._FRENO_PAGINAS_HORA = 600

    # ── Panel → Visitas y diagnóstico ───────────────────────────────────────────────────────────────────────────
    _c, _h, b = app._visitas_pagina({"dias": ["7"]}, autorizado=True)
    pag = b.decode("utf-8") if isinstance(b, bytes) else str(b)
    comprobar("Frenos contra extractores (A y B)" in pag, "panel: falta la tabla de frenos")
    fila = re.search(r"<tr><td>\d{4}-\d\d-\d\d</td>((?:<td>[^<]*</td>){5})</tr>", pag[pag.find("Frenos contra"):])
    nums = re.findall(r"<td>([^<]*)</td>", fila.group(1)) if fila else []
    # A: 4 GET + 1 HEAD + el token falso + el Googlebot falso = 7; B: 2 + 34 de la red sin buscador = 36; redes: 3.
    comprobar(nums[:3] == ["7", "36", "3"], f"panel: A/B/redes de hoy {nums[:3]}, esperaba 7, 36, 3")
    comprobar("freno_extractores" in app._bots_diagnostico(), "diagnóstico: faltan los frenos")

    # ── C: /rankings sin combinaciones ───────────────────────────────────────────────────────────────────────────
    canon = app._rk_direccion_canonica
    q = lambda s: parse_qs(s)
    casos = [("provincia=murcia&pag_alc=3&pag_idx=2&comunidad_deuda=murcia", "/rankings?pag_alc=3"),
             ("provincia=murcia&comunidad_alc=murcia", "/rankings?comunidad_alc=murcia"),
             ("comunidad_alc=andalucia&comunidad_deuda=murcia", "/rankings?comunidad_alc=andalucia"),
             ("comunidad=murcia&pag_deuda=2", "/rankings?pag_deuda=2"),
             ("comunidad=murcia&comunidad_deuda=murcia&pag_idx=4", "/rankings?comunidad=murcia&pag_idx=4"),
             ("provincia=girona", None), ("comunidad=murcia&pag_idx=2", None), ("pag_alc=2", None),
             ("comunidad_alc=murcia&pag_alc=5", None), ("", None), ("pag_alc=x&pag_idx=1", None)]
    for qs_, esperado in casos:
        r = canon(q(qs_))
        comprobar(r == esperado, f"C: {qs_!r} -> {r!r}, esperaba {esperado!r}")
    est, cab, _b = peticion("/rankings?provincia=murcia&pag_alc=3&pag_idx=2", "203.0.113.10")
    comprobar(est == "301" and cab.get("Location") == "/rankings?pag_alc=3", f"C: {est} {cab.get('Location')}")
    est, cab, _b = peticion("/gl/rankings?provincia=murcia&pag_deuda=2&comunidad_alc=murcia", "203.0.113.11")
    comprobar(est == "301" and cab.get("Location") == "/gl/rankings?pag_deuda=2", f"C gl: {est} {cab.get('Location')}")
    est, cab, html_ = peticion("/rankings?pag_alc=2", "203.0.113.12")
    comprobar(est == "200", f"C: /rankings?pag_alc=2 da {est}")
    html_ = html_.decode("utf-8", "replace")
    enlaces = [h.replace("&amp;", "&") for h in re.findall(r'href="(/rankings\?[^"#]*)', html_)]
    grupos = lambda u: {g for g, pc, pp in app._RK_GRUPOS for k in parse_qs(urlsplit(u).query) if k in (pc, pp)} | (
        {"prov"} if "provincia" in parse_qs(urlsplit(u).query) else set())
    combinados = [u for u in enlaces if len(grupos(u)) > 1]
    comprobar(enlaces and not combinados, f"C: enlaces con varias tablas: {combinados[:3]} (de {len(enlaces)})")
    comprobar(all(canon(parse_qs(urlsplit(u).query)) is None for u in enlaces), "C: un enlace de la página redirige")
    est, _c, _b = peticion("/rankings?pag_alc=99999&comunidad_alc=noexiste", "203.0.113.13")
    comprobar(est in ("200", "301"), f"C: dirección rara da {est} (nunca 404)")

    # ── Revisión de privacidad: el token solo va a nuestra web ──────────────────────────────────────────────────
    import revision_privacidad as rp
    vistas = []

    class _R:
        status = 200

        def read(self):
            return b"ok"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    rp.urllib.request.urlopen = lambda req, timeout=0: (vistas.append((req.full_url, req.get_header("X-admin-token"))), _R())[1]
    rp.time.sleep = lambda s: None
    for base in ("https://dinero-publico.com", "https://otro-sitio.example"):
        rp.Web(base, pausa=0).pedir("/")
    comprobar(vistas[0][1] == TOKEN and vistas[1][1] is None, f"revisión: token enviado a {vistas}")

    print(f"{bien[0]} bien, {len(mal)} mal")
    for m in mal:
        print("  MAL:", m)
    sys.exit(1 if mal else 0)


if __name__ == "__main__":
    main()
