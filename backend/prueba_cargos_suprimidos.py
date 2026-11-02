# encoding: utf-8
"""
Pruebas de cargos_suprimidos.py (lista de exclusión de cargos públicos por huella HMAC).
Usan una clave fija de prueba en EXCLUSION_CLAVE (no la de Render), así que no comprueban la entrada real del
repositorio: eso se mira con "python backend/cargos_suprimidos.py comprobar" y la clave de verdad.

    python backend/prueba_cargos_suprimidos.py            # solo el módulo: rápido, sin importar app.py
    PRUEBA_CON_APP=1 python backend/prueba_cargos_suprimidos.py
        también la ficha de la web: importa app.py con una supresión de prueba, la red cortada (proxy a un puerto
        cerrado) y DATA_DIR en una carpeta temporal, para no tocar el cache.db local. Proceso pesado: de uno en uno.

Con nombres inventados. La prueba sobre los datos reales elige a la persona por posición, sin escribir su nombre.
"""
import copy
import json
import os
import sys
import tempfile
import unittest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
CLAVE_PRUEBA = "clave-solo-para-las-pruebas-unitarias"
os.environ["EXCLUSION_CLAVE"] = CLAVE_PRUEBA      # antes de importar nada que la lea
import cargos_suprimidos as cs


def _texto(ruta):
    with open(ruta, encoding="utf-8") as f:
        return f.read()


def _municipios():
    return {
        "villaprueba|valencia": {"municipio": "Villaprueba", "provincia": "valencia",
                                 "alcalde": {"nombre": "ANA PÉREZ RUIZ", "partido": "AAA", "fecha_posesion": "17/06/2023"},
                                 "concejales": [{"nombre": "ANA PÉREZ RUIZ", "cargo": "Alcalde", "partido": "AAA"},
                                                {"nombre": "Luis Gómez Sanz", "cargo": "Teniente de Alcalde", "partido": "AAA"},
                                                {"nombre": "MARÍA LÓPEZ DÍAZ", "cargo": "Concejal", "partido": "BBB"}]},
        # mismo nombre en otro municipio y en un homónimo de otra provincia: no se tocan
        "otropueblo": {"municipio": "Otropueblo", "provincia": "valencia", "alcalde": None,
                       "concejales": [{"nombre": "Luis Gómez Sanz", "cargo": "Concejal", "partido": "CCC"}]},
        "villaprueba|murcia": {"municipio": "Villaprueba", "provincia": "murcia", "alcalde": None,
                               "concejales": [{"nombre": "Luis Gómez Sanz", "cargo": "Concejal", "partido": "CCC"}]},
    }


class Huella(unittest.TestCase):
    def test_indiferente_a_tildes_mayusculas_y_espacios(self):
        self.assertEqual(cs.huella("Villaprueba", "valencia", "Luis Gómez Sanz"),
                         cs.huella(" VILLAPRUEBA ", "Valencia", "luis  gomez   SANZ"))

    def test_distingue_municipio_y_provincia(self):
        h = cs.huella("Villaprueba", "valencia", "Luis Gómez Sanz")
        self.assertNotEqual(h, cs.huella("Otropueblo", "valencia", "Luis Gómez Sanz"))
        self.assertNotEqual(h, cs.huella("Villaprueba", "murcia", "Luis Gómez Sanz"))

    def test_depende_de_la_clave_y_no_es_un_sha256_sin_clave(self):
        import hashlib
        h = cs.huella("Villaprueba", "valencia", "Luis Gómez Sanz")
        self.assertEqual(len(h), 64)
        self.assertNotEqual(h, cs.huella("Villaprueba", "valencia", "Luis Gómez Sanz", b"otra-clave"))
        for prefijo in ("dp-supresion-v1|", "dp-exclusion-v2|", ""):
            sin_clave = hashlib.sha256((prefijo + "villaprueba|valencia|luis gomez sanz").encode()).hexdigest()
            self.assertNotEqual(h, sin_clave)


class SinClave(unittest.TestCase):
    """Sin EXCLUSION_CLAVE: nada se rompe, se avisa una vez en el registro y la lista no se aplica."""

    def setUp(self):
        os.environ.pop("EXCLUSION_CLAVE", None)
        cs._avisado_sin_clave = False

    def tearDown(self):
        os.environ["EXCLUSION_CLAVE"] = CLAVE_PRUEBA

    def test_aplicar_no_rompe_y_avisa(self):
        import contextlib
        import io
        sup = {"0" * 64: "quitar"}
        m = _municipios()
        regs = [{"municipio": "Villaprueba", "provincia": "valencia", "nombre": "Luis Gómez Sanz", "importe": 1.0}]
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(cs.aplicar_alcaldes(m, sup), set())
            self.assertEqual(cs.aplicar_sueldos(regs, sup), (regs, set()))
        self.assertEqual(m, _municipios())
        self.assertEqual(err.getvalue().count("EXCLUSION_CLAVE"), 1)

    def test_huella_y_ordenes_piden_la_clave(self):
        with self.assertRaises(cs.SinClave):
            cs.huella("Villaprueba", "valencia", "Luis Gómez Sanz")
        import contextlib
        import io
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cs.main(["comprobar"]), 2)

    def test_lista_vacia_sin_clave_no_avisa(self):
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            cs.aplicar_alcaldes(_municipios(), {})
        self.assertEqual(err.getvalue(), "")


class AplicarAlcaldes(unittest.TestCase):
    def test_quitar_concejal_solo_afecta_a_esa_persona(self):
        m, original = _municipios(), _municipios()
        sup = {cs.huella("Villaprueba", "valencia", "Luis Gómez Sanz"): "quitar"}
        self.assertEqual(cs.aplicar_alcaldes(m, sup), set(sup))
        self.assertEqual([c["nombre"] for c in m["villaprueba|valencia"]["concejales"]],
                         ["ANA PÉREZ RUIZ", "MARÍA LÓPEZ DÍAZ"])
        self.assertEqual(m["villaprueba|valencia"]["alcalde"], original["villaprueba|valencia"]["alcalde"])
        self.assertEqual(m["otropueblo"], original["otropueblo"])
        self.assertEqual(m["villaprueba|murcia"], original["villaprueba|murcia"])

    def test_ocultar_nombre_deja_cargo_y_partido(self):
        m = _municipios()
        cs.aplicar_alcaldes(m, {cs.huella("Villaprueba", "valencia", "Luis Gómez Sanz"): "ocultar_nombre"})
        fila = m["villaprueba|valencia"]["concejales"][1]
        self.assertEqual(fila, {"nombre": "", "cargo": "Teniente de Alcalde", "partido": "AAA", "suprimido": True})
        self.assertEqual(len(m["villaprueba|valencia"]["concejales"]), 3)

    def test_alcalde_quitar_y_ocultar(self):
        h = cs.huella("Villaprueba", "valencia", "Ana Pérez Ruiz")
        m = _municipios()
        cs.aplicar_alcaldes(m, {h: "quitar"})
        self.assertIsNone(m["villaprueba|valencia"]["alcalde"])
        self.assertNotIn("ANA PÉREZ RUIZ", [c["nombre"] for c in m["villaprueba|valencia"]["concejales"]])
        m = _municipios()
        cs.aplicar_alcaldes(m, {h: "ocultar_nombre"})
        self.assertEqual(m["villaprueba|valencia"]["alcalde"], {"nombre": "", "partido": "AAA", "suprimido": True})

    def test_sin_supresiones_no_cambia_nada_y_es_idempotente(self):
        m = _municipios()
        self.assertEqual(cs.aplicar_alcaldes(m, {}), set())
        self.assertEqual(m, _municipios())
        sup = {cs.huella("Villaprueba", "valencia", "Luis Gómez Sanz"): "quitar"}
        cs.aplicar_alcaldes(m, sup)
        una = copy.deepcopy(m)
        self.assertEqual(cs.aplicar_alcaldes(m, sup), set())
        self.assertEqual(m, una)

    def test_datos_reales_solo_cambia_una_fila(self):
        """Sobre el alcaldes_concejales.json del repositorio, en memoria: se suprime a la tercera persona del primer
        municipio con 3 o más (elegida por posición) y no cambia nada más en ninguno de los ~8.000 municipios."""
        with open(os.path.join(BASE_DIR, "alcaldes_concejales.json"), encoding="utf-8") as f:
            reales = json.load(f)["municipios"]
        clave, info = next((k, v) for k, v in reales.items() if len(v.get("concejales") or []) >= 3)
        persona = info["concejales"][2]
        antes = copy.deepcopy(reales)
        h = cs.huella(info["municipio"], info["provincia"], persona["nombre"])
        for modo, esperado in (("quitar", len(info["concejales"]) - 1), ("ocultar_nombre", len(info["concejales"]))):
            m = copy.deepcopy(antes)
            self.assertEqual(cs.aplicar_alcaldes(m, {h: modo}), {h})
            self.assertEqual(len(m[clave]["concejales"]), esperado)
            self.assertNotIn(persona["nombre"], [c["nombre"] for c in m[clave]["concejales"]])
            self.assertEqual([k for k in m if m[k] != antes[k]], [clave])


class AplicarSueldos(unittest.TestCase):
    def test_los_dos_modos_quitan_el_registro(self):
        regs = [{"municipio": "Villaprueba", "provincia": "valencia", "nombre": "Luis Gómez Sanz", "importe": 1.0},
                {"municipio": "Villaprueba", "provincia": "valencia", "nombre": "María López Díaz", "importe": 2.0}]
        for modo in cs.MODOS:
            out, usadas = cs.aplicar_sueldos(regs, {cs.huella("Villaprueba", "valencia", "LUIS GOMEZ SANZ"): modo})
            self.assertEqual([r["nombre"] for r in out], ["María López Díaz"])
            self.assertEqual(len(usadas), 1)


class FicheroYOrden(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.sup, self.alc, self.sue = (os.path.join(d, n) for n in ("sup.json", "alc.json", "sue.json"))
        with open(self.alc, "w", encoding="utf-8") as f:
            json.dump({"generado": "x", "municipios": _municipios()}, f, ensure_ascii=False)
        with open(self.sue, "w", encoding="utf-8") as f:
            json.dump({"registros": [{"municipio": "Villaprueba", "provincia": "valencia",
                                      "nombre": "Luis Gómez Sanz", "importe": 1.0}]}, f, ensure_ascii=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_excluir_no_guarda_el_nombre_y_limpia_los_json(self):
        h, usadas = cs.excluir("Villaprueba", "valencia", "Luis Gómez Sanz", "quitar",
                               ruta=self.sup, alcaldes_file=self.alc, sueldos_file=self.sue)
        self.assertEqual(usadas, {h})
        texto = _texto(self.sup)
        self.assertNotIn("mez", texto.lower())        # ni "Gómez" ni "Gomez"
        self.assertNotIn("villaprueba", texto.lower())
        self.assertNotIn("fecha", texto)
        self.assertNotIn("ref", texto)
        self.assertEqual(cs.cargar(self.sup), {h: "quitar"})
        alc = json.loads(_texto(self.alc))["municipios"]
        self.assertEqual(len(alc["villaprueba|valencia"]["concejales"]), 2)
        self.assertEqual(len(alc["otropueblo"]["concejales"]), 1)        # mismo nombre, otro municipio
        self.assertEqual(json.loads(_texto(self.sue))["registros"], [])
        # repetir con otro modo cambia la entrada, no la duplica
        cs.excluir("Villaprueba", "valencia", "Luis Gómez Sanz", "ocultar_nombre",
                   ruta=self.sup, alcaldes_file=self.alc, sueldos_file=self.sue)
        self.assertEqual(cs.cargar(self.sup), {h: "ocultar_nombre"})

    def test_fichero_ausente_o_roto_no_rompe(self):
        self.assertEqual(cs.cargar(os.path.join(self.tmp.name, "no_existe.json")), {})
        with open(self.sup, "w", encoding="utf-8") as f:
            f.write("{roto")
        self.assertEqual(cs.cargar(self.sup), {})

    def test_modo_desconocido(self):
        with self.assertRaises(ValueError):
            cs.excluir("Villaprueba", "valencia", "X Y", "borrar", ruta=self.sup,
                        alcaldes_file=self.alc, sueldos_file=self.sue)

    def test_fichero_del_repositorio_es_valido_y_sin_nombres(self):
        with open(cs.SUPRESIONES_FILE, encoding="utf-8") as f:
            d = json.load(f)
        for e in d["entradas"]:
            self.assertEqual(set(e), {"huella", "modo"})            # ni fecha ni referencia
            self.assertEqual(len(e["huella"]), 64)
            self.assertIn(e["modo"], cs.MODOS)


@unittest.skipUnless(os.environ.get("PRUEBA_CON_APP") == "1", "PRUEBA_CON_APP=1 para probar la ficha con app.py")
class FichaWeb(unittest.TestCase):
    """La ficha, el índice del detector de coincidencias y la traducción, con app.py de verdad."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(BASE_DIR, "alcaldes_concejales.json"), encoding="utf-8") as f:
            reales = json.load(f)["municipios"]
        # dos personas de municipios distintos (elegidas por posición): una se quita, a otra se le oculta el nombre
        con3 = [v for v in reales.values() if len(v.get("concejales") or []) >= 3]
        cls.quitar, cls.ocultar = (con3[0], con3[0]["concejales"][2]), (con3[1], con3[1]["concejales"][2])
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)   # app deja abierto cache.db
        sup = os.path.join(cls.tmp.name, "sup.json")
        with open(sup, "w", encoding="utf-8") as f:
            json.dump({"entradas": [
                {"huella": cs.huella(i["municipio"], i["provincia"], p["nombre"]), "modo": modo}
                for (i, p), modo in ((cls.quitar, "quitar"), (cls.ocultar, "ocultar_nombre"))]}, f)
        os.environ.update(CARGOS_SUPRIMIDOS_FILE=sup, DATA_DIR=cls.tmp.name, HTTP_PROXY="http://127.0.0.1:9",
                          HTTPS_PROXY="http://127.0.0.1:9", I18N_PUBLICADOS="gl,ca,eu")
        import app
        cls.app = app

    def _ficha(self, info):
        return self.app.alcalde_concejales_html(info["municipio"], info["provincia"])

    def test_quitar(self):
        info, persona = self.quitar
        html_ = self._ficha(info)
        nombre = self.app.esc(self.app._capitalizar_nombre(persona["nombre"]))
        self.assertNotIn(nombre, html_)
        self.assertIn(f"({len(info['concejales']) - 1})", html_)
        self.assertNotIn("Nombre no mostrado", html_)
        self.assertIn(self.app.esc(self.app._capitalizar_nombre(info["concejales"][1]["nombre"])), html_)   # el resto sigue
        self.assertIsNone(self.app._detectar_coincidencia_cargo(persona["nombre"], info["municipio"], info["provincia"]))

    def test_ocultar_nombre(self):
        info, persona = self.ocultar
        html_ = self._ficha(info)
        nombre = self.app.esc(self.app._capitalizar_nombre(persona["nombre"]))
        self.assertNotIn(nombre, html_)
        self.assertIn(f"({len(info['concejales'])})", html_)
        self.assertIn("Nombre no mostrado", html_)
        self.assertIsNone(self.app._detectar_coincidencia_cargo(persona["nombre"], info["municipio"], info["provincia"]))
        token = self.app._I18N_IDIOMA.set("gl")
        try:
            self.assertIn("Nome non amosado", self._ficha(info))
        finally:
            self.app._I18N_IDIOMA.reset(token)

    def test_otro_municipio_intacto(self):
        tocados = {(i["municipio"], i["provincia"]) for i in (self.quitar[0], self.ocultar[0])}
        info = next(v for v in self.app.ALCALDES_CONCEJALES.values()
                    if (v["municipio"], v["provincia"]) not in tocados and len(v.get("concejales") or []) >= 3)
        html_ = self._ficha(info)
        for c in info["concejales"]:
            self.assertIn(self.app.esc(self.app._capitalizar_nombre(c["nombre"])), html_)
        self.assertNotIn("Nombre no mostrado", html_)


if __name__ == "__main__":
    unittest.main(verbosity=2)
