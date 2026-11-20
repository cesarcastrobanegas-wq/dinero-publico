# encoding: utf-8
"""El año que acompaña a los sueldos de ISPA es el del EJERCICIO de los datos, no el nombre de una edición (07-11-2026).

La edición «ISPA 2025» publica las retribuciones de 2024. Antes la cabecera de /rankings decía «ISPA 2025» y las filas y
las fichas «ISPA 2024», que parecía otra edición. Ahora las filas y las fichas dicen «retribuciones de 2024», como la
cabecera, y la cabecera sigue nombrando la edición (ISPA 2025) con su enlace.

    python backend/prueba_ispa_anio.py

Importa app.py con la red cortada (proxy a un puerto cerrado) y DATA_DIR en una carpeta temporal, para no tocar el
cache.db local. Proceso pesado: de uno en uno.
"""
import os
import re
import sys
import tempfile
import unittest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)


class AnioIspa(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)   # app deja abierto cache.db
        os.environ.update(DATA_DIR=cls.tmp.name, HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9",
                          I18N_PUBLICADOS="gl,ca,eu")
        import app
        cls.app = app
        cls.ranking = app._calcular_ranking_alcaldes()
        cls.anio = next(str(f["anio"]) for f in cls.ranking if str(f.get("anio", "")).isdigit())
        cls.html_rk = app.render_rankings_html(None, None, "murcia", "todas", None, None)

    def test_las_filas_dicen_el_ejercicio(self):
        self.assertIn(f'<span class="pol-retrib-nota">retribuciones de {self.anio}</span>', self.html_rk)
        self.assertNotIn(f"ISPA {self.anio}", self.html_rk)        # ni en las filas ni en las fichas de provincia

    def test_la_cabecera_nombra_la_edicion_y_el_ejercicio(self):
        self.assertIn(f"ISPA {int(self.anio) + 1},", self.html_rk)
        self.assertIn(f"retribuciones de {self.anio}", self.html_rk)

    def test_ficha_del_municipio(self):
        f = self.ranking[0]                                        # el primero del ranking, que tiene sueldo
        html_ = self.app.alcalde_concejales_html(f["municipio"], f["provincia"])
        self.assertIn(f"(retribuciones de {f['anio']})", html_)
        self.assertIsNone(re.search(r"\(ISPA \d{4}\)", html_))

    def test_traducido(self):
        f = self.ranking[0]
        token = self.app._I18N_IDIOMA.set("gl")
        try:
            self.assertIn(f"(retribucións de {f['anio']})", self.app.alcalde_concejales_html(f["municipio"],
                                                                                         f["provincia"]))
        finally:
            self.app._I18N_IDIOMA.reset(token)


if __name__ == "__main__":
    unittest.main(verbosity=2)
