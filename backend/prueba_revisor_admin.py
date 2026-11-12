# encoding: utf-8
"""El revisor de privacidad comprueba /admin/* SIN la clave de administración (12-11-2026).

La revisión del 11-11 avisó «Ruta de administración accesible sin clave» en /admin/cache-db, /admin/alertas-db y
/admin/aviso-comentarios-prueba. Era falsa: en vivo, sin clave, responden 403/404. El revisor mandaba la clave
(X-Admin-Token, añadida el 08-11 para el freno de extractores) también en esas comprobaciones, así que recibía 200
y además bajaba la base entera y disparaba el correo de prueba.

Esta prueba levanta un servidor local que imita a la web (las rutas /admin solo se abren con la clave) y comprueba:
  - sin hallazgos de /admin aunque ADMIN_TOKEN esté puesto;
  - la clave no llega nunca a /admin, y sí al resto de páginas (para que el freno no corte la revisión);
  - si una ruta /admin estuviera abierta de verdad, se avisa, y no se lee entera.

    python backend/prueba_revisor_admin.py      (sin red; unos segundos)
"""
import http.server
import os
import sys
import threading
import unittest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
import revision_privacidad as rp  # noqa: E402

TOKEN = "clave-de-prueba"


class Servidor(http.server.BaseHTTPRequestHandler):
    abiertas = set()          # rutas /admin abiertas sin clave (para simular un fallo de verdad)
    vistas = []               # (método, ruta, ¿llevaba la clave?)

    def _responder(self, metodo):
        if metodo == "POST":
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
        ruta = self.path.split("?")[0]
        con_clave = self.headers.get("X-Admin-Token") == TOKEN
        Servidor.vistas.append((metodo, ruta, con_clave))
        if ruta.startswith("/admin"):
            if con_clave or ruta in Servidor.abiertas:
                cuerpo = b"<table>" + b"x" * 500000      # p. ej. la base o una tabla de revisión
                codigo = 200
            else:
                cuerpo, codigo = b"No autorizado.", 403
        else:
            cuerpo, codigo = b"<html><body>bien</body></html>", 200
        self.send_response(codigo)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        self._responder("GET")

    def do_POST(self):
        self._responder("POST")

    def log_message(self, *a):
        pass


class RevisorAdmin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Servidor)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        os.environ["ADMIN_TOKEN"] = TOKEN
        rp.Web.__init__.__defaults__ = (0.0,)               # sin pausa entre peticiones en la prueba

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        Servidor.abiertas, Servidor.vistas = set(), []

    def test_sin_falsa_alarma_y_sin_clave_en_admin(self):
        hallazgos, _n = rp.revisar_web(self.base, 0)
        admin = [h for h in hallazgos if "/admin" in h["url"]]
        self.assertEqual(admin, [])
        self.assertTrue([v for v in Servidor.vistas if v[1].startswith("/admin")])
        self.assertFalse([v for v in Servidor.vistas if v[1].startswith("/admin") and v[2]], "la clave llegó a /admin")
        self.assertTrue([v for v in Servidor.vistas if not v[1].startswith("/admin") and v[2]],
                        "el resto de páginas debe seguir llevando la clave (freno de extractores)")

    def test_una_ruta_abierta_de_verdad_se_avisa(self):
        Servidor.abiertas = {"/admin/cache-db"}
        hallazgos, _n = rp.revisar_web(self.base, 0)
        self.assertEqual([h["url"] for h in hallazgos if h["tipo"] == "admin-abierto"], [self.base + "/admin/cache-db"])

    def test_no_se_lee_entera(self):
        Servidor.abiertas = {"/admin/cache-db"}
        codigo, cuerpo = rp.Web(self.base).pedir("/admin/cache-db", con_token=False, max_bytes=65536)
        self.assertEqual(codigo, 200)
        self.assertLessEqual(len(cuerpo), 65536)


if __name__ == "__main__":
    unittest.main(verbosity=2)
