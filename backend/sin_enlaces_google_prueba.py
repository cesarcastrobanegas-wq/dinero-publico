# encoding: utf-8
"""
Prueba SIN RED de que ninguna página ni informe enlaza a una búsqueda de Google (ni de otro buscador) con el nombre de
una persona (05-11-2026). Hasta el 02-11 cada alcalde y concejal de la ficha enlazaba a
google.com/search?q=<ayuntamiento>+transparencia (quitado en 031bf9d); esta prueba evita que vuelva, por ejemplo al
fusionar una rama vieja que aún lo lleva.

  1. el código: ningún .py, .js ni .html de backend/ ni frontend/ construye una dirección de búsqueda de Google, Bing,
     DuckDuckGo o Yahoo (google.xx/search, /url?q=, bing.com/search...). Rápido, sin importar app.py;
  2. con PRUEBA_CON_APP=1, además, la web de verdad: importa app.py (DATA_DIR temporal, red cortada con un proxy a un
     puerto cerrado) y genera el bloque de alcalde y concejales de TODOS los municipios con datos, en castellano y en
     gl/ca/eu. Ningún enlace a un buscador y ningún nombre de cargo dentro de un <a>. Proceso pesado: de uno en uno.

    python backend/sin_enlaces_google_prueba.py
    PRUEBA_CON_APP=1 python backend/sin_enlaces_google_prueba.py
"""
import glob
import os
import re
import sys
import tempfile
import unittest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(BASE_DIR)
sys.path.insert(0, BASE_DIR)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# direcciones de búsqueda de un buscador (con o sin https, con www. o sin él, cualquier dominio de Google)
RE_BUSCADOR = re.compile(r"(?:google\.[a-z.]{2,6}/(?:search|url)\b|google\.[a-z.]{2,6}/\?q=|bing\.com/search|"
                         r"duckduckgo\.com/\?q=|search\.yahoo\.com)", re.I)
_YO = os.path.abspath(__file__)


def fuentes():
    rutas = []
    for patron in ("backend/**/*.py", "backend/**/*.js", "backend/**/*.html", "frontend/**/*.js", "frontend/**/*.html",
                   "frontend/**/*.jsx", "frontend/**/*.ts", "frontend/**/*.tsx"):
        rutas += glob.glob(os.path.join(RAIZ, patron), recursive=True)
    return sorted({os.path.abspath(r) for r in rutas if "node_modules" not in r and os.path.abspath(r) != _YO})


class Codigo(unittest.TestCase):
    def test_la_expresion_detecta_los_enlaces_de_antes(self):
        for malo in ('f"https://www.google.com/search?q={quote_plus(organismo + \' transparencia\')}"',
                     "https://google.es/search?q=x", "http://www.google.com/url?q=x", "https://www.bing.com/search?q=x",
                     "https://duckduckgo.com/?q=x"):
            self.assertTrue(RE_BUSCADOR.search(malo), malo)
        for bueno in ("https://www.googletagmanager.com/gtag/js?id=X", "https://fonts.googleapis.com/css2?family=X",
                      "pagead2.googlesyndication.com/pagead/js/adsbygoogle.js", "/?q=garcia"):
            self.assertFalse(RE_BUSCADOR.search(bueno), bueno)

    def test_ningun_fichero_construye_una_busqueda(self):
        hallados = []
        for ruta in fuentes():
            with open(ruta, encoding="utf-8", errors="replace") as f:
                for n, linea in enumerate(f, 1):
                    if RE_BUSCADOR.search(linea):
                        hallados.append(f"{os.path.relpath(ruta, RAIZ)}:{n}: {linea.strip()[:120]}")
        self.assertEqual(hallados, [], "enlaces a un buscador en el código:\n" + "\n".join(hallados))


@unittest.skipUnless(os.environ.get("PRUEBA_CON_APP") == "1", "PRUEBA_CON_APP=1 para probar las fichas con app.py")
class FichasWeb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)   # app deja abierto cache.db
        os.environ.update(DATA_DIR=cls.tmp.name, HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9",
                          I18N_PUBLICADOS="gl,ca,eu")
        for v in ("RESEND_API_KEY", "ADMIN_TOKEN"):
            os.environ.pop(v, None)
        import app
        cls.app = app

    def test_alcalde_y_concejales_de_todos_los_municipios(self):
        app = self.app
        municipios = list(app.ALCALDES_CONCEJALES.values())
        self.assertGreater(len(municipios), 1000, "no se han cargado los alcaldes y concejales")
        con_enlace, con_buscador, vistos = [], [], 0
        idiomas = ("es", "gl", "ca", "eu")
        for info in municipios:
            nombres = {app.esc(app._capitalizar_nombre(p.get("nombre") or ""))
                       for p in [info.get("alcalde") or {}] + list(info.get("concejales") or []) if p.get("nombre")}
            nombres.discard("")
            for idioma in idiomas:
                tok = app._I18N_IDIOMA.set(idioma)
                try:
                    html_ = app.alcalde_concejales_html(info["municipio"], info.get("provincia"))
                finally:
                    app._I18N_IDIOMA.reset(tok)
                vistos += 1
                if RE_BUSCADOR.search(html_):
                    con_buscador.append(info["municipio"])
                anclas = " ".join(re.findall(r"<a\b[^>]*>(.*?)</a>", html_, re.S))
                if any(n and n in anclas for n in nombres):
                    con_enlace.append(info["municipio"])
        print(f"  {vistos} bloques de alcalde y concejales revisados")
        self.assertEqual(con_buscador, [], f"enlaces a un buscador en {len(con_buscador)} fichas")
        self.assertEqual(con_enlace, [], f"nombres de cargos dentro de un enlace en {len(con_enlace)} fichas")


if __name__ == "__main__":
    unittest.main(verbosity=2)
