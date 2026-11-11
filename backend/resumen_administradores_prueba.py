# encoding: utf-8
"""
Prueba SIN RED del resumen de adjudicatarios para el flujo de administradores del BORME (06-11-2026).

  - leer(escribir(base)) da EXACTAMENTE lo mismo que administradores_borme.adjudicatarios(base): mismos
    adjudicatarios, mismo orden, mismas grafías en el mismo orden, misma tabla de directores;
  - --comprobar rechaza lo que no es un resumen (una página HTML, un JSON cualquiera, uno casi vacío);
  - servir_web: 202 mientras se prepara, 200 con el fichero después, 500 si falla (y luego lo reintenta).

Con PRUEBA_CON_APP=1 también importa app.py (red cortada, DATA_DIR temporal) y prueba la ruta
/admin/resumen-administradores: 403 sin token, 202 y después 200. Proceso pesado: de uno en uno.

    python backend/resumen_administradores_prueba.py
Todos los nombres son INVENTADOS.
"""
import gzip
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import administradores_borme as AB  # noqa: E402
import resumen_adjudicatarios as RA  # noqa: E402


def base_de_juguete(ruta, n_extra=0):
    c = sqlite3.connect(ruta)
    c.execute("CREATE TABLE municipios (municipio TEXT, data TEXT)")
    c.execute("CREATE TABLE contratos_menors_locales (adjudicatari TEXT, nif TEXT, import_num REAL)")
    c.execute("CREATE TABLE directores (clave TEXT, nombre TEXT, cargo TEXT)")
    contratos = [
        {"empresa": "OBRAS DE PRUEBA ALFA, S.L.", "nif": "B12345678", "importe_num": "1000.5",
         "directivo": "PRUEBA ÁLFA UNO", "cargo": "Administrador único"},
        {"empresa": "Obras de Prueba Alfa SL", "nif": "B12345678", "importe_num": 250},
        {"empresa": "SERVICIOS INVENTADOS BETA SA", "nif": "", "importe_num": None, "directivo": "Ficticio Béta Dos",
         "cargo": "Apoderado"},
        {"empresa": "No localizada", "nif": "", "importe_num": 5},
        {"empresa": "Asociación Gamma de Ejemplo", "nif": "G87654321", "importe_num": "no es un número"},
    ]
    c.execute("INSERT INTO municipios VALUES (?, ?)", ("uno", json.dumps({"contratos": contratos})))
    c.execute("INSERT INTO municipios VALUES (?, ?)", ("roto", "{esto no es json"))
    c.execute("INSERT INTO municipios VALUES (?, ?)", ("dos", json.dumps({"contratos": contratos[:2]})))
    for i in range(n_extra):
        c.execute("INSERT INTO contratos_menors_locales VALUES (?, ?, ?)", (f"EMPRESA FICTICIA {i} SL", f"B{i:08d}", i))
    c.executemany("INSERT INTO contratos_menors_locales VALUES (?, ?, ?)", [
        ("OBRAS DE PRUEBA ALFA, S.L.", "B12345678", 100.0), ("Obras de Prueba Alfa S.L.", "b12345678", 50.0),
        ("Taller Delta de Ejemplo", None, 30.0), ("", "B00000000", 1.0)])
    c.executemany("INSERT INTO directores VALUES (?, ?, ?)", [
        ("B12345678", "PRUEBA ÁLFA UNO", "Administrador único"), ("servicios inventados beta sa", "", "")])
    c.commit()
    c.close()


class Resumen(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="prueba_resumen_adm_")
        self.base = os.path.join(self.dir, "cache.db")
        base_de_juguete(self.base, n_extra=1200)
        self.sal = os.path.join(self.dir, "resumen.json.gz")

    def test_mismo_resultado_que_la_base(self):
        a1, d1 = AB.adjudicatarios(self.base)
        RA.escribir(self.base, self.sal)
        a2, d2 = RA.leer(self.sal)
        self.assertEqual(a1, a2)
        self.assertEqual(list(a1), list(a2))
        for k in a1:
            self.assertEqual(list(a1[k]["nombres"]), list(a2[k]["nombres"]))
        self.assertEqual(d1, d2)
        self.assertIsInstance(next(iter(d2.values())), tuple)
        self.assertEqual(list(a2["B12345678"]["nombres"])[:2], ["OBRAS DE PRUEBA ALFA, S.L.", "Obras de Prueba Alfa SL"])
        # gzip sin fecha: dos resúmenes de la misma base son idénticos salvo la hora de "generado"
        with open(self.sal, "rb") as f:
            self.assertEqual(f.read(2), b"\x1f\x8b")

    def test_comprobar(self):
        RA.escribir(self.base, self.sal)
        self.assertTrue(RA.comprobar(self.sal))
        self.assertFalse(RA.comprobar(self.sal, minimo=10 ** 6))
        malo = os.path.join(self.dir, "malo")
        for contenido in (b"<html>404</html>", gzip.compress(b'{"hola": 1}'), b"", gzip.compress(b"\xff\xfe")):
            with open(malo, "wb") as f:
                f.write(contenido)
            self.assertFalse(RA.comprobar(malo), contenido[:20])
        self.assertFalse(RA.comprobar(os.path.join(self.dir, "no_existe")))
        # por la línea de órdenes, como en el flujo
        r = subprocess.run([sys.executable, os.path.join(BASE_DIR, "resumen_adjudicatarios.py"), "--comprobar", malo],
                           capture_output=True)
        self.assertEqual(r.returncode, 1)
        r = subprocess.run([sys.executable, os.path.join(BASE_DIR, "resumen_adjudicatarios.py"), "--comprobar", self.sal],
                           capture_output=True)
        self.assertEqual(r.returncode, 0)

    def test_generador_con_resumen(self):
        """administradores_borme.py --resumen llega a cruzar sin abrir la base (que aquí ni existe)."""
        RA.escribir(self.base, self.sal)
        adj, directores = RA.leer(self.sal)
        situacion = {k: "no consta" for k in adj}
        self.assertIsInstance(AB.resumen_cola(adj, situacion, directores), dict)

    def esperar(self, data_dir, base, segundos=120):
        fin = time.time() + segundos
        while time.time() < fin:
            code, cab, cuerpo = RA.servir_web(base, data_dir)
            if code != 202:
                return code, cab, cuerpo
            time.sleep(0.5)
        self.fail("seguía en 202")

    def test_servir_web(self):
        datos = tempfile.mkdtemp(prefix="prueba_resumen_web_")
        code, cab, cuerpo = RA.servir_web(self.base, datos)
        self.assertEqual(code, 202)
        self.assertEqual(json.loads(cuerpo)["estado"], "preparando")
        code, cab, cuerpo = self.esperar(datos, self.base)
        self.assertEqual(code, 200)
        self.assertEqual(cab["Content-Type"], "application/gzip")
        with open(os.path.join(datos, "r.json.gz"), "wb") as f:
            f.write(cuerpo)
        self.assertEqual(RA.leer(os.path.join(datos, "r.json.gz")), AB.adjudicatarios(self.base))
        # reciente: se reutiliza sin volver a prepararlo
        self.assertEqual(RA.servir_web(self.base, datos)[0], 200)

    def test_servir_web_fallo(self):
        datos = tempfile.mkdtemp(prefix="prueba_resumen_web_")
        no_hay = os.path.join(datos, "no_existe.db")
        self.assertEqual(RA.servir_web(no_hay, datos)[0], 202)
        code, cab, cuerpo = self.esperar(datos, no_hay)
        self.assertEqual(code, 500)
        self.assertIn("No se pudo preparar", json.loads(cuerpo)["error"])
        self.assertEqual(RA.servir_web(no_hay, datos)[0], 202)          # la siguiente lo reintenta
        self.esperar(datos, no_hay)


@unittest.skipUnless(os.environ.get("PRUEBA_CON_APP") == "1", "PRUEBA_CON_APP=1 para probar también la ruta de app.py")
class RutaDeLaWeb(unittest.TestCase):
    def test_ruta(self):
        datos = tempfile.mkdtemp(prefix="prueba_resumen_app_")
        sqlite3.connect(os.path.join(datos, "cache.db")).close()     # la app crea sus tablas y carga lo del repo
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            os.environ[k] = "http://127.0.0.1:9"
        os.environ.update(DATA_DIR=datos, ADMIN_TOKEN="token-de-prueba-" + "y" * 20, NO_PROXY="", no_proxy="")
        import app

        def pedir(token):
            environ = {"REQUEST_METHOD": "GET", "PATH_INFO": "/admin/resumen-administradores", "QUERY_STRING": "",
                       "REMOTE_ADDR": "127.0.0.1", "HTTP_USER_AGENT": "curl/8 (prueba)", "wsgi.input": io.BytesIO(b"")}
            if token:
                environ["HTTP_X_ADMIN_TOKEN"] = os.environ["ADMIN_TOKEN"]
            visto = {}

            def sr(estado, cab, exc_info=None):
                visto["estado"] = estado
            cuerpo = b"".join(app.app(environ, sr))
            return int(visto["estado"].split()[0]), cuerpo
        self.assertEqual(pedir(False)[0], 403)
        self.assertEqual(pedir(True)[0], 202)
        fin = time.time() + 300
        while time.time() < fin:
            code, cuerpo = pedir(True)
            if code != 202:
                break
            time.sleep(1)
        self.assertEqual(code, 200)
        self.assertEqual(cuerpo[:2], b"\x1f\x8b")
        self.assertEqual(json.loads(gzip.decompress(cuerpo))["version"], RA.VERSION)


if __name__ == "__main__":
    unittest.main(verbosity=2)
