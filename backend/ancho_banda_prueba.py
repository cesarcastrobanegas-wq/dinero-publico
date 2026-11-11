# encoding: utf-8
"""
Prueba SIN RED de los ahorros de ancho de banda (06-11-2026):

  - /admin/cache-db?formato=gz sirve la MISMA copia comprimida (y reanudable con Range), con su huella en ?info=1;
  - ETag en las páginas y 304 cuando el cliente ya la tiene (nunca en /admin ni en respuestas no-store);
  - redirección 301 de las direcciones con «&amp;» copiado tal cual;
  - robots.txt: fuera los rastreadores de entrenamiento de IA, dentro Google, Bing y los buscadores de IA;
  - coordenadas del mapa con un decimal.

Importa app.py con la red cortada (proxy a un puerto cerrado), DATA_DIR en una carpeta temporal con un cache.db de
juguete y un ADMIN_TOKEN de prueba. Proceso pesado: de uno en uno.

    python backend/ancho_banda_prueba.py
"""
import gzip
import hashlib
import io
import os
import sqlite3
import sys
import tempfile
import unittest
import urllib.robotparser

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATOS = tempfile.mkdtemp(prefix="prueba_ancho_banda_")
TOKEN = "token-de-prueba-" + "x" * 20
_c = sqlite3.connect(os.path.join(DATOS, "cache.db"))
_c.execute("CREATE TABLE juguete (n INTEGER, t TEXT)")
_c.executemany("INSERT INTO juguete VALUES (?, ?)", [(i, "fila de ejemplo %d" % i) for i in range(20000)])
_c.commit()
_c.close()
for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ[k] = "http://127.0.0.1:9"
os.environ.update(DATA_DIR=DATOS, ADMIN_TOKEN=TOKEN, NO_PROXY="", no_proxy="")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, BASE_DIR)
import app  # noqa: E402


def wsgi(ruta, consulta="", cabeceras=None):
    """(estado, cabeceras, cuerpo) de una petición GET por el callable WSGI."""
    environ = {"REQUEST_METHOD": "GET", "PATH_INFO": ruta, "QUERY_STRING": consulta, "REMOTE_ADDR": "127.0.0.1",
               "HTTP_USER_AGENT": "Mozilla/5.0 (prueba)", "wsgi.input": io.BytesIO(b"")}
    environ.update(cabeceras or {})
    visto = {}

    def start_response(estado, cab, exc_info=None):
        visto["estado"], visto["cab"] = estado, dict(cab)
    cuerpo = b"".join(app.app(environ, start_response))
    return visto["estado"], visto["cab"], cuerpo


class CacheDbComprimida(unittest.TestCase):
    def test_gz_es_la_misma_copia(self):
        tok = {"HTTP_X_ADMIN_TOKEN": TOKEN}
        estado, _, crudo = wsgi("/admin/cache-db", "", tok)
        self.assertTrue(estado.startswith("200"))
        estado, cab, comprimido = wsgi("/admin/cache-db", "formato=gz", tok)
        self.assertTrue(estado.startswith("200"))
        self.assertEqual(comprimido[:2], b"\x1f\x8b")
        self.assertEqual(gzip.decompress(comprimido), crudo)
        self.assertLess(len(comprimido), len(crudo))
        self.assertIn("cache.db.gz", cab["Content-Disposition"])
        self.assertEqual(cab["X-Cache-Db-Sha256"], hashlib.sha256(comprimido).hexdigest())
        # reanudación: el trozo final es exactamente el final del mismo fichero
        estado, cab, resto = wsgi("/admin/cache-db", "formato=gz", dict(tok, HTTP_RANGE="bytes=100-"))
        self.assertTrue(estado.startswith("206"))
        self.assertEqual(resto, comprimido[100:])
        # ?info=1 da la huella del fichero comprimido
        estado, _, info = wsgi("/admin/cache-db", "formato=gz&info=1", tok)
        self.assertIn(hashlib.sha256(comprimido).hexdigest().encode(), info)
        # sin token, nada
        self.assertTrue(wsgi("/admin/cache-db", "formato=gz")[0].startswith("403"))


class Etag(unittest.TestCase):
    def test_304_si_ya_la_tiene(self):
        gz = {"HTTP_ACCEPT_ENCODING": "gzip"}
        estado, cab, cuerpo = wsgi("/robots.txt", "", gz)
        self.assertTrue(estado.startswith("200"))
        etag = cab["ETag"]
        self.assertTrue(etag.startswith('W/"') and etag.endswith('-gz"'))
        self.assertIn("Accept-Encoding", cab["Vary"])
        # el mismo cuerpo da el mismo ETag (gzip sin fecha dentro)
        self.assertEqual(wsgi("/robots.txt", "", gz)[1]["ETag"], etag)
        estado, cab, cuerpo = wsgi("/robots.txt", "", dict(gz, HTTP_IF_NONE_MATCH=etag))
        self.assertTrue(estado.startswith("304"))
        self.assertEqual(cuerpo, b"")
        self.assertEqual(cab["ETag"], etag)
        # sin gzip el ETag es otro (son bytes distintos)
        self.assertNotEqual(wsgi("/robots.txt")[1]["ETag"], etag)
        self.assertTrue(wsgi("/robots.txt", "", {"HTTP_IF_NONE_MATCH": '"otro"'})[0].startswith("200"))

    def test_no_toca_admin_ni_no_store(self):
        self.assertEqual(app._con_etag("/admin/x", "*", 200, {}, b"hola"), (200, {}, b"hola"))
        cab = {"Cache-Control": "no-store"}
        self.assertEqual(app._con_etag("/x", "*", 200, cab, b"hola"), (200, cab, b"hola"))
        self.assertEqual(app._con_etag("/x", "*", 404, {}, b"hola")[0], 404)
        trozos = iter([b"a"])
        self.assertIs(app._con_etag("/x", "*", 200, {}, trozos)[2], trozos)


class AmpCopiado(unittest.TestCase):
    def test_redirige_a_la_buena(self):
        estado, cab, cuerpo = wsgi("/gl/", "muni=Casas+Altas&amp;provincia=valencia")
        self.assertTrue(estado.startswith("301"))
        self.assertEqual(cab["Location"], "/gl/?muni=Casas+Altas&provincia=valencia")
        self.assertEqual(cuerpo, b"")
        self.assertEqual(wsgi("/", "amp;provincia=x&muni=Y")[1]["Location"], "/?provincia=x&muni=Y")

    def test_no_toca_lo_normal(self):
        self.assertIsNone(app._RE_QS_AMP.search("muni=Casas+Altas&provincia=valencia"))
        self.assertIsNone(app._RE_QS_AMP.search("q=campamento%3Bx&tipo=empresa"))
        self.assertIsNone(app._RE_QS_AMP.search("q=lamp%3B"))


class Robots(unittest.TestCase):
    def test_ia_fuera_buscadores_dentro(self):
        texto = wsgi("/robots.txt")[2].decode("utf-8")
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(texto.splitlines())
        url = "https://dinero-publico.com/?muni=Murcia&provincia=murcia"
        for bot in ("GPTBot", "CCBot", "ClaudeBot", "Google-Extended", "Applebot-Extended", "meta-externalagent",
                    "Bytespider", "Amazonbot", "ElevenlabsCrawler", "ShapBot"):
            self.assertFalse(rp.can_fetch(bot, url), bot)
        for bot in ("Googlebot", "bingbot", "OAI-SearchBot", "ChatGPT-User", "Claude-SearchBot", "PerplexityBot",
                    "Applebot", "DuckDuckBot", "YandexBot", "ElevenlabsBot"):
            self.assertTrue(rp.can_fetch(bot, url), bot)
            self.assertFalse(rp.can_fetch(bot, "https://dinero-publico.com/admin/revision"), bot)
            self.assertFalse(rp.can_fetch(bot, "https://dinero-publico.com/rankings?pag_alc=2"), bot)
        self.assertIn("Sitemap: ", texto)


class Mapa(unittest.TestCase):
    def test_un_decimal(self):
        self.assertEqual(app._redondear_trazado("M391.269,407.862L-0.04,12.001Z"), "M391.3,407.9L0,12Z")
        for geo in app.MAPA_COBERTURA_CCAA_GEO + app.MAPA_COBERTURA_PROVINCIAS_GEO:
            self.assertNotRegex(geo["d"], r"\d\.\d\d")


if __name__ == "__main__":
    unittest.main(verbosity=2)
