# encoding: utf-8
"""Prueba SIN RED del módulo del bot de redes (redes_sociales.py): textos, controles, tarjeta, firma de X y los tres
publicadores con las APIs simuladas.

    python backend/redes_sociales_prueba.py
"""
import io
import json
import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import redes_sociales as R  # noqa: E402

LETRAS = "TRWAGMYFPDXBNJZSQVHLCKE"
DNI_INVENTADO = "87654321" + LETRAS[87654321 % 23]          # se construye aquí: ningún DNI escrito en el repositorio
ENV = {"X_API_KEY": "clave-x-0001", "X_API_SECRET": "secreto-x-0002", "X_ACCESS_TOKEN": "token-x-0003",
       "X_ACCESS_SECRET": "secreto-token-x-0004", "FB_PAGE_ID": "1234567890", "FB_PAGE_TOKEN": "TOKENPAGINA-fb-0005",
       "IG_USER_ID": "17840000000000000", "REDES_ACTIVAS": "1"}
ENTRADA = {"tipo": "licitaciones", "tema": "licitaciones:murcia:45",
           "titulo": "128 licitaciones abiertas de obras de construcción en la Región de Murcia",
           "titulo_tarjeta": "de obras de construcción en la Región de Murcia",
           "frase": "Cada una con su plazo, su importe y el órgano que contrata. Datos a 10 de noviembre.",
           "ruta": "/convocatorias?provincia=murcia&sector=45", "etiqueta": "Licitaciones abiertas", "cifra": "128"}


class Resp:
    def __init__(self, codigo, datos):
        self.status_code, self._datos = codigo, datos
        self.text = json.dumps(datos)

    def json(self):
        return self._datos


class HttpFalso:
    """Sustituye a requests.Session: apunta cada llamada y contesta lo que diga `respuestas` (url -> lista)."""

    def __init__(self, respuestas):
        self.respuestas, self.llamadas = respuestas, []

    def _contestar(self, metodo, url, kw):
        self.llamadas.append((metodo, url, kw))
        for patron, lista in self.respuestas.items():
            if patron in url:
                r = lista.pop(0) if len(lista) > 1 else lista[0]
                if isinstance(r, Exception):
                    raise r
                return r
        return Resp(404, {"error": {"message": "no simulado"}})

    def post(self, url, **kw):
        return self._contestar("POST", url, kw)

    def get(self, url, **kw):
        return self._contestar("GET", url, kw)


class Textos(unittest.TestCase):
    def test_x_cabe_siempre(self):
        largo = dict(ENTRADA, frase="Una frase muy larga " * 30)
        e = R.componer(largo, "https://dinero-publico.com")
        self.assertLessEqual(R.largo_x(e["textos"]["x"]), 280)
        self.assertTrue(e["textos"]["x"].endswith(e["url"]))
        self.assertIn("…", e["textos"]["x"])

    def test_cada_red(self):
        e = R.componer(ENTRADA, "https://dinero-publico.com")
        url = "https://dinero-publico.com/convocatorias?provincia=murcia&sector=45"
        self.assertEqual(e["url"], url)
        self.assertIn(url, e["textos"]["facebook"])
        ig = e["textos"]["instagram"]
        self.assertNotIn("https://", ig)
        self.assertIn("Enlace: dinero-publico.com/convocatorias?provincia=murcia&sector=45", ig)
        self.assertIn("#DineroPúblico", ig)
        self.assertEqual(e["tarjeta"]["titulo"], ENTRADA["titulo_tarjeta"])

    def test_nunca_un_dni(self):
        for campo in ("titulo", "frase", "cifra"):
            with self.assertRaises(ValueError, msg=campo):
                R.componer(dict(ENTRADA, **{campo: f"Adjudicado a {DNI_INVENTADO}"}), "https://dinero-publico.com")
        with self.assertRaises(ValueError):
            R.componer(dict(ENTRADA, frase="NIE X" + "1234567" + LETRAS[1234567 % 23]), "https://dinero-publico.com")
        R.componer(dict(ENTRADA, frase="Expediente 12345678A con letra que no cuadra"), "https://dinero-publico.com")

    def test_solo_paginas_de_la_web(self):
        with self.assertRaises(ValueError):
            R.componer(dict(ENTRADA, ruta="https://otra.web/x"), "https://dinero-publico.com")
        with self.assertRaises(ValueError):
            R.componer(dict(ENTRADA, titulo=""), "https://dinero-publico.com")

    def test_dos_frases(self):
        self.assertEqual(R.dos_frases("Uno. Dos. Tres."), "Uno. Dos.")
        self.assertTrue(R.dos_frases("palabra " * 80).endswith("…"))
        self.assertLessEqual(len(R.dos_frases("palabra " * 80)), 261)


class Configuracion(unittest.TestCase):
    def test_apagado_y_ensayo_por_defecto(self):
        self.assertFalse(R.activas({}))
        self.assertTrue(R.ensayo({}))
        self.assertFalse(R.ensayo({"REDES_ENSAYO": "0"}))
        self.assertEqual(R.redes_configuradas({}), [])
        self.assertEqual(R.redes_configuradas(ENV), ["x", "facebook", "instagram"])
        self.assertEqual(R.redes_configuradas(dict(ENV, X_ACCESS_SECRET="")), ["facebook", "instagram"])
        self.assertEqual(R.redes_configuradas(dict(ENV, REDES_SOLO="facebook")), ["facebook"])


class Tarjeta(unittest.TestCase):
    def test_png_1080x1350(self):
        from PIL import Image
        for e in (ENTRADA, dict(ENTRADA, tipo="caso", cifra="", etiqueta="Caso", titulo="Un título " * 12)):
            png = R.dibujar_tarjeta(R.componer(e, "https://dinero-publico.com")["tarjeta"])
            img = Image.open(io.BytesIO(png))
            self.assertEqual((img.format, img.size), ("PNG", (1080, 1350)))


class FirmaX(unittest.TestCase):
    def test_ejemplo_oficial_de_x(self):
        # Ejemplo de la documentación de X («Creating a signature»): los parámetros van en la dirección en vez de en
        # el cuerpo, que para la firma es lo mismo. Firma esperada: hCtSmYh+iHYCEqBWrE7C7hYmtUk=
        env = {"X_API_KEY": "xvz1evFS4wEEPTGEFPHBog", "X_API_SECRET": "kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw",
               "X_ACCESS_TOKEN": "370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb",
               "X_ACCESS_SECRET": "LswwdoUaIvS8ltyTt5jkRh4J50vUPVVHtR2YPi5kE"}
        url = ("https://api.twitter.com/1.1/statuses/update.json?include_entities=true&"
               "status=Hello%20Ladies%20%2B%20Gentlemen%2C%20a%20signed%20OAuth%20request%21")
        cab = R.oauth1_cabecera("POST", url, env, nonce="kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg", ts=1318622958)
        self.assertIn('oauth_signature="hCtSmYh%2BiHYCEqBWrE7C7hYmtUk%3D"', cab)


class Publicadores(unittest.TestCase):
    def test_x(self):
        http = HttpFalso({"/2/media/upload": [Resp(200, {"data": {"id": "999"}})],
                          "/2/tweets": [Resp(201, {"data": {"id": "1855"}})]})
        self.assertEqual(R.publicar("x", http, ENV, "hola https://dinero-publico.com", "", b"png"), "1855")
        (m1, u1, k1), (m2, u2, k2) = http.llamadas
        self.assertIn("/2/media/upload", u1)
        self.assertTrue(k1["headers"]["Authorization"].startswith("OAuth "))
        self.assertEqual(json.loads(k2["data"])["media"]["media_ids"], ["999"])

    def test_facebook(self):
        http = HttpFalso({"/1234567890/photos": [Resp(200, {"id": "1", "post_id": "1234567890_77"})]})
        self.assertEqual(R.publicar("facebook", http, ENV, "texto", "https://dinero-publico.com/redes/tarjeta/1-ab.png",
                                    b""), "1234567890_77")
        datos = http.llamadas[0][2]["data"]
        self.assertEqual(datos["url"], "https://dinero-publico.com/redes/tarjeta/1-ab.png")
        self.assertEqual(datos["caption"], "texto")

    def test_instagram_espera_al_contenedor(self):
        http = HttpFalso({"/17840000000000000/media_publish": [Resp(200, {"id": "IGPOST"})],
                          "/17840000000000000/media": [Resp(200, {"id": "CONT1"})],
                          "/CONT1": [Resp(200, {"status_code": "IN_PROGRESS"}), Resp(200, {"status_code": "FINISHED"})]})
        esperas = []
        self.assertEqual(R.publicar("instagram", http, ENV, "texto", "https://x/t.png", b"", esperar=esperas.append),
                         "IGPOST")
        self.assertEqual(len(esperas), 1)
        self.assertEqual(http.llamadas[-1][2]["data"]["creation_id"], "CONT1")

    def test_instagram_contenedor_con_error(self):
        http = HttpFalso({"/17840000000000000/media": [Resp(200, {"id": "C2"})],
                          "/C2": [Resp(200, {"status_code": "ERROR"})]})
        with self.assertRaises(R.ErrorRed):
            R.publicar("instagram", http, ENV, "t", "https://x/t.png", b"", esperar=lambda s: None)

    def test_errores_sin_claves(self):
        http = HttpFalso({"/photos": [Resp(400, {"error": {"message": "Invalid token TOKENPAGINA-fb-0005"}})]})
        with self.assertRaises(R.ErrorRed) as ctx:
            R.publicar("facebook", http, ENV, "t", "https://x/t.png", b"")
        self.assertNotIn("TOKENPAGINA-fb-0005", str(ctx.exception))
        self.assertIn("HTTP 400", str(ctx.exception))
        http = HttpFalso({"/2/media/upload": [ConnectionError("caída access_token=TOKENPAGINA-fb-0005")]})
        with self.assertRaises(R.ErrorRed) as ctx:
            R.publicar("x", http, ENV, "t", "", b"png")
        self.assertNotIn("TOKENPAGINA-fb-0005", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
