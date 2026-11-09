# encoding: utf-8
"""Prueba SIN RED del bot de redes dentro de la web (bloque «REDES SOCIALES» de app.py), con las tres APIs simuladas.

  - Apagado (por defecto): /admin/redes-diario contesta {"activas": false} y no hace nada.
  - Al encenderlo, los casos que ya había quedan como «anteriores» y no se publican; un caso nuevo sí entra.
  - Ejemplo de uso: uno al día, con la misma cifra y el mismo enlace que la página; sin repetir tema.
  - Modo ensayo: todo espera en /admin/redes; nada sale sin aprobar; rechazado no se publica.
  - Publicar: cada red una sola vez; si una red falla, las otras salen y la que falla se reintenta como mucho 3 veces;
    una red caída no tira nada.
  - La tarjeta se sirve en una dirección pública con llave; mal la llave o rechazada: 404.
  - Ningún DNI/NIE pasa: un caso con uno no se prepara.

    python backend/prueba_redes_sociales.py      (proceso pesado: importa la web; de uno en uno, ~2-3 min)
"""
import io
import json
import os
import re
import sys
import tempfile
import threading
import time
from datetime import date, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TOKEN = "token-de-prueba-0123456789abcdef"
CLAVES = {"X_API_KEY": "clave-x-0001", "X_API_SECRET": "secreto-x-0002", "X_ACCESS_TOKEN": "token-x-0003",
          "X_ACCESS_SECRET": "secreto-token-x-0004", "FB_PAGE_ID": "1234567890", "FB_PAGE_TOKEN": "TOKENPAGINA-fb-0005",
          "IG_USER_ID": "17840000000000000"}
LETRAS = "TRWAGMYFPDXBNJZSQVHLCKE"


class Resp:
    def __init__(self, codigo, datos):
        self.status_code, self._datos, self.text = codigo, datos, json.dumps(datos)

    def json(self):
        return self._datos


class RedesFalsas:
    """Las tres APIs simuladas. `falla` = redes que contestan error; `caida` = redes que lanzan una excepción."""

    def __init__(self, falla=(), caida=()):
        self.falla, self.caida, self.llamadas = set(falla), set(caida), []

    def _red(self, url):
        return "x" if "api.x.com" in url else "instagram" if "17840000000000000" in url or "/CONT" in url else "facebook"

    def _r(self, metodo, url, kw):
        red = self._red(url)
        self.llamadas.append((red, metodo, url, kw))
        if red in self.caida:
            raise ConnectionError("sin conexión")
        if red in self.falla:
            return Resp(500, {"error": {"message": "fallo simulado"}})
        if "/2/media/upload" in url:
            return Resp(200, {"data": {"id": "M1"}})
        if "/2/tweets" in url:
            return Resp(201, {"data": {"id": f"X{len(self.llamadas)}"}})
        if url.endswith("/photos"):
            return Resp(200, {"post_id": f"FB{len(self.llamadas)}"})
        if url.endswith("/media_publish"):
            return Resp(200, {"id": f"IG{len(self.llamadas)}"})
        if url.endswith("/media"):
            return Resp(200, {"id": "CONT1"})
        if "/CONT1" in url:
            return Resp(200, {"status_code": "FINISHED"})
        return Resp(404, {})

    def post(self, url, **kw):
        return self._r("POST", url, kw)

    def get(self, url, **kw):
        return self._r("GET", url, kw)

    def cuenta(self, red, final):
        return sum(1 for r, m, u, k in self.llamadas if r == red and u.endswith(final))


def main():
    os.environ.update(DATA_DIR=tempfile.mkdtemp(prefix="redes_"), HTTP_PROXY="http://127.0.0.1:9",
                      HTTPS_PROXY="http://127.0.0.1:9", ADMIN_TOKEN=TOKEN)
    for k in list(CLAVES) + ["REDES_ACTIVAS", "REDES_ENSAYO", "REDES_SOLO"]:
        os.environ.pop(k, None)
    import app
    for hilo in threading.enumerate():
        if hilo.name == "carga-place-menores":
            hilo.join(timeout=1800)
    mal, bien = [], [0]

    def comprobar(cond, texto):
        if cond:
            bien[0] += 1
        else:
            mal.append(texto)

    def peticion(ruta, metodo="GET", token=None):
        path, _, query = ruta.partition("?")
        env = {"REQUEST_METHOD": metodo, "PATH_INFO": path, "QUERY_STRING": query, "HTTP_USER_AGENT": "prueba",
               "REMOTE_ADDR": "127.0.0.1", "wsgi.input": io.BytesIO(b""), "CONTENT_LENGTH": "0"}
        if token:
            env["HTTP_X_ADMIN_TOKEN"] = token
        res = {}

        def sr(estado, cab, exc=None):
            res["estado"], res["cab"] = estado, dict(cab)
        cuerpo = b"".join(app.app(env, sr))
        return res["estado"][:3], res["cab"], cuerpo

    def filas(where="1=1", args=()):
        with app._db_lock:
            cur = app._db.execute(f"SELECT id, tipo, tema, estado, textos, llave, redes, url FROM redes_publicaciones "
                                  f"WHERE {where} ORDER BY id", args)
            return [dict(zip(("id", "tipo", "tema", "estado", "textos", "llave", "redes", "url"), f)) for f in cur]

    # ── 1. Apagado por defecto ──────────────────────────────────────────────────────────────────────────────────────
    est, _, cuerpo = peticion("/admin/redes-diario", "POST", TOKEN)
    comprobar(est == "200" and json.loads(cuerpo) == {"activas": False}, f"apagado: {est} {cuerpo[:100]!r}")
    est, _, _ = peticion("/admin/redes-diario", "POST")
    comprobar(est == "403", f"sin token debe dar 403: {est}")
    est, cab, _ = peticion("/admin/redes")
    comprobar(est == "303" and cab.get("Location") == "/admin/revision/redes", f"/admin/redes no lleva al panel: {est}")
    comprobar("redes-arranque" not in [h.name for h in threading.enumerate()], "apagado no debe lanzar el hilo")

    # ── 2. Encendido en modo ensayo ─────────────────────────────────────────────────────────────────────────────────
    os.environ.update(CLAVES, REDES_ACTIVAS="1")
    redes = RedesFalsas()
    app._redes_http = lambda: redes
    n_casos = len([c for c in app._CASOS if c.get("slug") not in app._CASOS_BORRADOR_POR_SLUG])
    comprobar(app._redes_casos_nuevos() == [], "al encender no debe haber casos «nuevos»")
    comprobar(len(filas("estado='anterior'")) == n_casos, f"los {n_casos} casos de antes quedan como anteriores")
    app._CASOS.append({"slug": "caso-de-prueba-redes", "titulo": "Un caso de prueba para las redes",
                       "resumen": "Primera frase del caso. Segunda frase con 12.345 €. Tercera frase que no va."})
    app._CASOS.append({"slug": "caso-con-dni", "titulo": "Caso con un DNI",
                       "resumen": "Adjudicado a " + "87654321" + LETRAS[87654321 % 23] + "."})
    nuevos = app._redes_casos_nuevos()
    caso = filas("tema='caso:caso-de-prueba-redes'")
    comprobar(len(nuevos) == 1 and caso and caso[0]["estado"] == "pendiente", f"caso nuevo pendiente: {nuevos} {caso}")
    comprobar(not filas("tema='caso:caso-con-dni'"), "un caso con DNI no debe prepararse")
    tx = json.loads(caso[0]["textos"]) if caso else {}
    comprobar("Segunda frase" in tx.get("facebook", "") and "Tercera" not in tx.get("facebook", ""),
              "el caso lleva título y dos frases")
    comprobar(tx.get("x", "").endswith("/casos/caso-de-prueba-redes"), "el texto de X termina en el enlace del caso")
    comprobar(app._redes_casos_nuevos() == [], "un caso no se prepara dos veces")

    # ── 3. Ejemplo de uso del día ───────────────────────────────────────────────────────────────────────────────────
    ahora = app._ahora_madrid()
    fin = (ahora + timedelta(days=9)).strftime("%Y-%m-%d %H:%M")
    with app._db_lock:
        app._db.execute("DELETE FROM licitaciones")
        app._db.executemany("INSERT INTO licitaciones (id, estado, fin_plazo, titulo, provincia, cpv2) "
                            "VALUES (?, 'PUB', ?, ?, 'murcia', '45')", [(f"R{i}", fin, f"Obra {i}") for i in range(6)])
        app._db.execute("INSERT INTO licitaciones (id, estado, fin_plazo, titulo, provincia, cpv2) "
                        "VALUES ('R99', 'PUB', '2020-01-01 10:00', 'Cerrada', 'murcia', '45')")
        app._db.commit()
    dia = date(2026, 11, 12)
    while dia.toordinal() % 4 != 0:            # un día que toca «licitaciones»
        dia += timedelta(days=1)
    id_lic = app._redes_ejemplo_del_dia(dia)
    lic = filas("id=?", (id_lic,)) if id_lic else []
    comprobar(lic and lic[0]["tipo"] == "licitaciones", f"el ejemplo de ese día es de licitaciones: {lic}")
    if lic:
        tx = json.loads(lic[0]["textos"])
        comprobar(tx["facebook"].startswith("6 licitaciones abiertas de"), f"cifra de la página: {tx['facebook'][:60]}")
        comprobar(lic[0]["url"].endswith("/convocatorias?provincia=murcia&sector=45"), f"enlace exacto: {lic[0]['url']}")
        pagina = app.render_convocatorias_html({"provincia": ["murcia"], "sector": ["45"]})
        comprobar(re.search(r"\b6\b", re.sub(r"<[^>]+>", " ", pagina)) is not None, "la página enlazada enseña 6")
    comprobar(app._redes_ejemplo_del_dia(dia) is None, "dos ejemplos el mismo día")
    temas = []
    for i in range(1, 5):
        id_ = app._redes_ejemplo_del_dia(dia + timedelta(days=i))
        if id_:
            temas.append(filas("id=?", (id_,))[0]["tema"])
    comprobar(len(temas) == len(set(temas)) and "licitaciones:murcia:45" not in temas,
              f"ningún tema se repite en 60 días: {temas}")
    for f in filas("tipo!='caso' AND estado='pendiente'"):
        t = " ".join(json.loads(f["textos"]).values())
        comprobar(not app.REDES_MOD.tiene_dni(t), f"DNI en {f['tema']}")
        comprobar(f["url"].startswith(app.SITE_URL + "/"), f"enlace fuera de la web: {f['url']}")

    # ── 4. Tarjeta pública ─────────────────────────────────────────────────────────────────────────────────────────
    c = caso[0] if caso else {"id": 0, "llave": "0" * 16}
    est, cab, png = peticion(f"/redes/tarjeta/{c['id']}-{c['llave']}.png")
    comprobar(est == "200" and cab.get("Content-Type") == "image/png" and png[:8] == b"\x89PNG\r\n\x1a\n",
              f"tarjeta: {est} {cab.get('Content-Type')}")
    est, _, _ = peticion(f"/redes/tarjeta/{c['id']}-{'0' * 16}.png")
    comprobar(est == "404", f"llave mala debe dar 404: {est}")

    # ── 5. Ensayo: nada sale sin aprobar ───────────────────────────────────────────────────────────────────────────
    comprobar(app._redes_publicar_pendientes(http=redes) == 0 and not redes.llamadas, "sin aprobar no sale nada")
    cookie = "galleta"
    app._revision_csrf = lambda ck: "csrf-prueba"
    codigo, _, panel = app._redes_panel_html(cookie)
    panel = panel.decode("utf-8") if isinstance(panel, bytes) else panel
    comprobar(codigo == 200, f"panel: {codigo}")
    comprobar("modo ensayo" in panel and "Aprobar y publicar" in panel and "<img src=\"/redes/tarjeta/" in panel,
              "el panel enseña las pendientes con su tarjeta y el botón")
    comprobar(TOKEN not in panel and "TOKENPAGINA" not in panel, "el panel no enseña claves")
    # aprobar el caso: sale en las tres redes, una vez cada una
    comprobar(app._redes_accion("aprobar", str(c["id"])) == "aprobar", "aprobar")
    for h in threading.enumerate():
        if h.name == "redes-publicar":
            h.join(timeout=60)
    f = filas("id=?", (c["id"],))[0]
    rd = json.loads(f["redes"])
    comprobar(f["estado"] == "publicada" and all(rd.get(r, {}).get("estado") == "publicada"
                                                 for r in ("x", "facebook", "instagram")), f"publicada en las tres: {f}")
    comprobar(redes.cuenta("x", "/2/tweets") == 1 and redes.cuenta("facebook", "/photos") == 1
              and redes.cuenta("instagram", "/media_publish") == 1, "una vez en cada red")
    url_img = [k["data"]["image_url"] for r, m, u, k in redes.llamadas if u.endswith("/media")][0]
    comprobar(url_img == f"{app.SITE_URL}/redes/tarjeta/{c['id']}-{c['llave']}.png", f"imagen pública: {url_img}")
    app._redes_publicar_pendientes(http=redes)
    app._redes_publicar_una(c["id"], http=redes)
    comprobar(redes.cuenta("x", "/2/tweets") == 1, "lo publicado no se vuelve a publicar")
    # rechazar: no se publica y su tarjeta deja de servirse
    otra = filas("estado='pendiente'")[0]
    comprobar(app._redes_accion("rechazar", str(otra["id"])) == "rechazar", "rechazar")
    est, _, _ = peticion(f"/redes/tarjeta/{otra['id']}-{otra['llave']}.png")
    comprobar(est == "404", f"tarjeta de una rechazada: {est}")
    comprobar(app._redes_accion("aprobar", str(otra["id"])) == "", "una rechazada no se puede aprobar después")

    # ── 6. Una red falla, las otras salen; reintentos limitados; una red caída no tira nada ─────────────────────────
    pend = filas("estado='pendiente'")
    if pend:
        id_f = pend[0]["id"]
        with app._db_lock:
            app._db.execute("UPDATE redes_publicaciones SET estado='aprobada' WHERE id=?", (id_f,))
            app._db.commit()
        fallos = RedesFalsas(falla={"x"}, caida={"instagram"})
        app._redes_publicar_una(id_f, http=fallos)
        f = filas("id=?", (id_f,))[0]
        rd = json.loads(f["redes"])
        comprobar(f["estado"] == "parcial" and rd["facebook"]["estado"] == "publicada" and rd["x"]["estado"] == "error"
                  and rd["instagram"]["estado"] == "error", f"una falla y las otras siguen: {f['estado']} {rd}")
        comprobar("TOKENPAGINA" not in f["redes"] and "secreto" not in f["redes"], "los errores no llevan claves")
        for _ in range(4):
            app._redes_publicar_pendientes(http=fallos)
        f = filas("id=?", (id_f,))[0]
        rd = json.loads(f["redes"])
        comprobar(rd["x"]["intentos"] == 3 and fallos.cuenta("x", "/2/media/upload") == 3,
                  f"como mucho 3 intentos: {rd['x']}")
        comprobar(fallos.cuenta("facebook", "/photos") == 1, "Facebook no se repite al reintentar las otras")
        comprobar(f["estado"] == "publicada", f"acabados los intentos queda como publicada (con errores): {f['estado']}")
    else:
        mal.append("no quedaba ninguna pendiente para probar los fallos")

    # ── 7. La pasada diaria por la web: solo recuentos ─────────────────────────────────────────────────────────────
    est, _, cuerpo = peticion("/admin/redes-diario", "POST", TOKEN)
    d = json.loads(cuerpo) if est == "200" else {}
    comprobar(d.get("activas") is True and d.get("ensayo") is True and d.get("redes") == ["x", "facebook", "instagram"],
              f"pasada diaria: {est} {d}")
    comprobar(set(d) <= {"activas", "ensayo", "redes", "ejemplo", "casos_nuevos", "intentadas", "pendientes_de_aprobar",
                         "error"} and "licitaciones" not in cuerpo.decode(), "la respuesta solo trae recuentos")
    # sin modo ensayo, lo nuevo sale aprobado
    os.environ["REDES_ENSAYO"] = "0"
    app._CASOS.append({"slug": "caso-sin-ensayo", "titulo": "Otro caso de prueba", "resumen": "Una frase."})
    app._redes_casos_nuevos()
    comprobar(filas("tema='caso:caso-sin-ensayo'")[0]["estado"] == "aprobada", "sin ensayo, aprobada directamente")
    # una excepción dentro de la pasada no la tira
    orig = app._redes_ejemplo_del_dia
    app._redes_ejemplo_del_dia = lambda *a: 1 / 0
    try:
        d = app._redes_pasada_diaria(http=RedesFalsas())
        comprobar(d.get("error") == "ZeroDivisionError", f"error controlado en la pasada: {d}")
    finally:
        app._redes_ejemplo_del_dia = orig
    os.environ["REDES_ACTIVAS"] = "0"
    comprobar(app._redes_publicar_una(c["id"], http=redes) == {}, "apagado no publica nada")

    print(f"{bien[0]} bien, {len(mal)} mal")
    for m in mal:
        print("  MAL:", m)
    return 1 if mal else 0


if __name__ == "__main__":
    sys.exit(main())
