# encoding: utf-8
"""Pruebas de la revisión de fichas de municipio del 23-11-2026, una clase por punto, con un municipio inventado:

  1. El sueldo del alcalde enlaza a su fuente oficial; sin ejercicio guardado no hay enlace ni cifra.
  2. Un sueldo de 0 € no lleva ninguna suposición sobre la persona, en ningún idioma.
  3. La ficha no enlaza a buscadores y app.py no contiene direcciones de búsqueda de Google.
  4. Una fecha futura dice que es de adjudicación solo en las fuentes donde consta.
  5. Las cuatro versiones de idioma de un mismo bloque llevan las mismas cifras y fechas.

    python backend/prueba_fichas_municipio_23_11.py

Importa app.py con la red cortada y DATA_DIR en una carpeta temporal. Proceso pesado: de uno en uno.
"""
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

ISPA = "https://digital.gob.es/funcion-publica/dgfp/espacio-ispa/estadisticas/informac_estad_"
RE_BUSCADOR = re.compile(r"google\.[a-z.]+/search|bing\.com/search|duckduckgo\.com/\?", re.I)
RE_SUPOSICION = re.compile(r"renuncia|doble cargo|dobre cargo|doble càrrec|bikoitz|renúncia|uko egin", re.I)
RE_CIFRAS = re.compile(r"\d{4}-\d{2}-\d{2}|\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+,\d+")
IDIOMAS = ("es", "gl", "ca", "eu")
MUNI, PROV = "Villaejemplo de Prueba", "soria"


def setUpModule():
    global app, TMP
    TMP = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    os.environ.update(DATA_DIR=TMP.name, HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9",
                      I18N_PUBLICADOS="gl,ca,eu")
    import app as _app
    app = _app


def en_idioma(lang, f, *a, **k):
    tk = app._I18N_IDIOMA.set(lang)
    try:
        return f(*a, **k)
    finally:
        app._I18N_IDIOMA.reset(tk)


def bloque(retrib, lang="es"):
    clave = app.clave_municipio(MUNI, PROV)
    info = {"municipio": MUNI, "provincia": PROV,
            "alcalde": {"nombre": "PERSONA INVENTADA EJEMPLO", "partido": "XX"}, "concejales": []}
    with mock.patch.dict(app.ALCALDES_CONCEJALES, {clave: info}), \
            mock.patch.dict(app.RETRIBUCIONES_ISPA, {clave: retrib}):
        return en_idioma(lang, app.alcalde_concejales_html, MUNI, PROV)


def fila(fuente, fecha="2099-01-01"):
    return {"id": "ejemplo", "municipio": MUNI, "provincia": PROV, "fuente": fuente, "adjudicatari": "EMPRESA EJEMPLO SL",
            "nif": "", "import_num": 1000.5, "data_adjudicacio": fecha, "tipus_contracte": "Servicios",
            "descripcio": "Contrato de ejemplo"}


class P1FuenteDelSueldo(unittest.TestCase):
    def test_con_ejercicio_enlaza_a_ispa(self):
        h = bloque({"importe": 12345.67, "anio": 2024})
        self.assertIn(f'href="{ISPA}2024"', h)

    def test_sin_ejercicio_ni_enlace_ni_cifra(self):
        h = bloque({"importe": 12345.67, "anio": ""})
        self.assertNotIn("href=", h)
        self.assertNotIn("12.345", h)


class P2SinSuposiciones(unittest.TestCase):
    def test_sueldo_cero_en_los_cuatro_idiomas(self):
        for lang in IDIOMAS:
            h = bloque({"importe": 0, "anio": 2024}, lang)
            self.assertNotRegex(h, RE_SUPOSICION, lang)
            self.assertIn(f'href="{ISPA}2024"', h, lang)


class P3SinBuscadores(unittest.TestCase):
    def test_bloque(self):
        self.assertNotRegex(bloque({"importe": 100.0, "anio": 2024}), RE_BUSCADOR)

    def test_codigo(self):
        with open(os.path.join(BASE_DIR, "app.py"), encoding="utf-8") as f:
            self.assertIsNone(re.search(r"google\.[a-z.]+/search", f.read()))


class P4EtiquetaDeFecha(unittest.TestCase):
    HOY = date(2026, 11, 23)

    def test_fuentes_con_adjudicacion(self):
        for fuente in ("euskadi", "EUSKADI", "PSCP", "rpc-girona"):
            self.assertIn("Fecha de adjudicación", app._nota_fecha_futura_txt("2026-12-16", fuente, self.HOY), fuente)

    def test_otra_fuente_no_afirma_que_fecha_es(self):
        t = app._nota_fecha_futura_txt("2026-12-16", "fuente-alamo", self.HOY)
        self.assertTrue(t.startswith("Fecha según la fuente"))

    def test_fecha_pasada_sin_aviso(self):
        self.assertEqual(app._nota_fecha_futura_txt("2026-11-23", "euskadi", self.HOY), "")
        self.assertNotIn("posible error", app._render_fila_contrato_menor(fila("euskadi", "2025-01-01")))

    def test_fila_y_traducciones(self):
        h = app._render_fila_contrato_menor(fila("euskadi"))
        self.assertIn('<div class="lid">2099-01-01</div>', h)      # la fecha de la fuente no se cambia
        self.assertIn("Fecha de adjudicación según la fuente", h)
        esperado = {"gl": "Data de adxudicación", "ca": "Data d'adjudicació", "eu": "Esleipen-data"}
        for lang, txt in esperado.items():
            self.assertIn(txt, app._I18N_CATALOGOS[lang]["Fecha de adjudicación según la fuente, posible error: "
                                                         "es posterior a hoy."], lang)


    def test_ficha_de_empresa(self):
        con = sqlite3.connect(":memory:")
        con.executescript("""
            CREATE TABLE organos (id INTEGER PRIMARY KEY, organo TEXT, municipio TEXT, provincia TEXT, entidad TEXT);
            CREATE TABLE c (clave TEXT, tipo TEXT, fecha TEXT, importe REAL, suma REAL, nota TEXT, iva TEXT,
                            org INTEGER, titulo TEXT, url TEXT, fuente TEXT, estado TEXT, con_nif INTEGER);
            CREATE TABLE variantes (clave TEXT, nombre TEXT, n INTEGER);
            CREATE TABLE alias (nkey TEXT, clave TEXT);
            CREATE TABLE nombre_nif (nkey TEXT, nif TEXT);
            CREATE TABLE empresas (clave TEXT PRIMARY KEY, nombre TEXT, n INTEGER, nf INTEGER, nm INTEGER,
                                   imp_sin REAL, imp_con REAL, imp_nd REAL, sociedad INTEGER);""")
        clave = "n:empresa ejemplo"
        con.execute("INSERT INTO organos VALUES (1, 'Organo de ejemplo', ?, ?, '')", (MUNI, PROV))
        con.execute("INSERT INTO variantes VALUES (?, 'EMPRESA EJEMPLO', 3)", (clave,))
        con.execute("INSERT INTO alias VALUES ('empresa ejemplo', ?)", (clave,))
        con.execute("INSERT INTO empresas VALUES (?, 'EMPRESA EJEMPLO', 3, 2, 1, 300, 0, 0, 0)", (clave,))
        filas = [("F", "2099-01-01", "PSCP"), ("F", "2025-01-01", "PLACE"), ("M", "2099-02-02", "fuente-alamo")]
        for tipo, fecha, fuente in filas:
            con.execute("INSERT INTO c VALUES (?, ?, ?, 100, 100, NULL, 'sin', 1, 'Objeto de ejemplo', '', ?, '', 0)",
                        (clave, tipo, fecha, fuente))
        r = app._render_empresa(con, "n-empresa-ejemplo", {})
        h = r[0] if isinstance(r, tuple) else r
        self.assertEqual(h.count("Fecha de adjudicación según la fuente, posible error"), 1)   # PSCP
        self.assertEqual(h.count("Fecha según la fuente, posible error"), 1)                   # Fuente Álamo
        self.assertIn("01/01/2099", h)                                                         # la fecha no se cambia
        con.close()


class P5MismosDatosEnCadaIdioma(unittest.TestCase):
    def test_bloque_y_fila(self):
        def cifras(h):
            return sorted(RE_CIFRAS.findall(re.sub(r"<[^>]+>", " ", h)))
        retrib = {"importe": 12345.67, "anio": 2024}
        base_b, base_f = cifras(bloque(retrib)), cifras(app._render_fila_contrato_menor(fila("euskadi")))
        self.assertTrue(base_b and base_f)
        for lang in IDIOMAS[1:]:
            self.assertEqual(cifras(bloque(retrib, lang)), base_b, lang)
            self.assertEqual(cifras(en_idioma(lang, app._render_fila_contrato_menor, fila("euskadi"))), base_f, lang)


if __name__ == "__main__":
    unittest.main(verbosity=1)
