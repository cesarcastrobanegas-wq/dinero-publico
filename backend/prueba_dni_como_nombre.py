# encoding: utf-8
"""Un adjudicatario cuyo «nombre» es solo un DNI/NIE nunca sale entero (07-11-2026, RGPD).

PLACE publica a veces al adjudicatario sin nombre, con su DNI/NIE en el campo del nombre. Ahora se guarda y se enseña
como «Persona física · ***4567**», igual que el NIF: al leer PLACE, al guardar, al leer de la base, en el repaso del
arranque y al pintar las filas. Los DNI/NIE de esta prueba son inventados (los de ejemplo de siempre).

    python backend/prueba_dni_como_nombre.py

Importa app.py con la red cortada (proxy a un puerto cerrado) y DATA_DIR en una carpeta temporal con un cache.db
vacío, para no tocar el local. Proceso pesado: de uno en uno.
"""
import json
import os
import sys
import tempfile
import unittest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import enmascarar_nif as en  # noqa: E402

DNI, NIE = "12345678Z", "X1234567L"          # inventados
DNI_OK, NIE_OK = "Persona física · ***4567**", "Persona física · ****4567*"


class SinApp(unittest.TestCase):
    def test_enmascarar_nif_tambien_los_nombres(self):
        datos = {"contratos": [{"adj": DNI, "nif_adj": DNI}, {"adjudicatari": f"ES{NIE}"}, {"adj": "12345678 Z"},
                               {"adj": "123 SERVICIOS SL"}, {"empresa": "B12345678"}, {"adj": "Persona física · ***4567**"}]}
        self.assertEqual(en.enmascarar_estructura(datos), 4)          # 3 nombres y un NIF
        c = datos["contratos"]
        self.assertEqual((c[0]["adj"], c[1]["adjudicatari"], c[2]["adj"]), (DNI_OK, NIE_OK, DNI_OK))
        self.assertEqual((c[3]["adj"], c[4]["empresa"]), ("123 SERVICIOS SL", "B12345678"))   # empresas, intactas
        self.assertNotIn(DNI, json.dumps(datos))


class ConApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)   # app deja abierto cache.db
        os.environ.update(DATA_DIR=cls.tmp.name, HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9",
                          I18N_PUBLICADOS="gl,ca,eu")
        import threading
        import app
        cls.app = app
        # Al importar, app.py arranca el hilo del feed de menores, que empieza con su propio _purgar_nombres_dni: se
        # espera a que acabe para que su repaso no se cruce con el de las pruebas (si no, el recuento sale 0 a veces).
        for hilo in threading.enumerate():
            if hilo.name == "carga-place-menores":
                hilo.join(timeout=900)

    def test_nombre_sin_dni(self):
        f = self.app.nombre_sin_dni
        self.assertEqual(f(DNI), DNI_OK)
        self.assertEqual(f(NIE), NIE_OK)
        self.assertEqual(f(" 12.345.678-z "), DNI_OK)
        self.assertEqual(f("ES" + DNI), DNI_OK)
        for igual in ("B12345678", "123 SERVICIOS SL", "Ana", "", None, "No localizada", DNI_OK, "12345678"):
            self.assertEqual(f(igual), igual)

    def test_al_leer_place(self):
        bloque = ('<cac:WinningParty><cac:PartyIdentification><cbc:ID schemeName="NIF">' + DNI + '</cbc:ID>'
                  '</cac:PartyIdentification><cac:PartyName><cbc:Name>' + DNI + '</cbc:Name></cac:PartyName>'
                  '</cac:WinningParty>')
        empresa, _ = self.app._ganador_tender_result(bloque)
        self.assertEqual(empresa, DNI_OK)

    def _contrato(self, empresa):
        return {"empresa": empresa, "nif": "", "titulo": "Asesoramiento de prueba", "importe": "22.680,00 €",
                "importe_num": 22680.0, "importe_tipo": "adjudicado", "estado": "ADJ", "fuente": "place",
                "fecha": "2023-05-01", "organo": "Ayuntamiento de prueba"}

    def test_al_guardar_y_al_leer(self):
        a = self.app
        a._db_set_municipio("Saucejo, El", {"contratos": [self._contrato(DNI)], "timestamp": 1.0}, "sevilla")
        crudo = a._db.execute("SELECT data FROM municipios WHERE municipio=?",
                              (a.clave_municipio("Saucejo, El", "sevilla"),)).fetchone()[0]
        self.assertNotIn(DNI, crudo)
        self.assertIn(DNI_OK, crudo)
        # una fila vieja, escrita antes del arreglo: al leerla ya sale enmascarada, y el repaso la arregla en la base
        clave = a.clave_municipio("Osuna", "sevilla")
        a._db.execute("INSERT INTO municipios (municipio, data, ts, provincia) VALUES (?,?,?,?)",
                      (clave, json.dumps({"contratos": [self._contrato(NIE)]}, ensure_ascii=False), 1.0, "sevilla"))
        a._db.commit()
        self.assertEqual(a._db_get_municipio(clave)["contratos"][0]["empresa"], NIE_OK)
        self.assertNotIn(NIE, json.dumps([d for d in a._db_all_municipios("sevilla")], ensure_ascii=False))
        r = a._purgar_nombres_dni()
        self.assertEqual((r["fichas"], r["contratos_formales"]), (1, 1))
        crudo = a._db.execute("SELECT data FROM municipios WHERE municipio=?", (clave,)).fetchone()[0]
        self.assertNotIn(NIE, crudo)
        self.assertEqual(a._purgar_nombres_dni()["contratos_formales"], 0)      # idempotente

    def test_contratos_menores(self):
        a = self.app
        a._db.execute("INSERT INTO contratos_menors_locales (id, municipio, provincia, fuente, organisme, adjudicatari, "
                      "nif, import_num, data_adjudicacio, tipus_contracte, descripcio, codi_cpv, exercici, ts) VALUES "
                      "('prueba-dni-1','Osuna','sevilla','place','Ayto','" + DNI + "','',100,'2025-01-01','Servicios',"
                      "'x','',2025,1)")
        a._db.commit()
        self.assertEqual(a._purgar_nombres_dni()["contratos_menores"], 1)
        fila = a._db.execute("SELECT adjudicatari FROM contratos_menors_locales WHERE id='prueba-dni-1'").fetchone()
        self.assertEqual(fila[0], DNI_OK)

    def test_al_pintar_la_fila_formal(self):
        html_ = self.app._render_fila_contrato(self._contrato(DNI), municipio="Saucejo, El", provincia="sevilla")
        self.assertNotIn(DNI, html_)                            # ni en la ficha ni en el título del enlace al registro
        self.assertIn("Persona física · ***4567**", html_)
        token = self.app._I18N_IDIOMA.set("gl")
        try:
            html_gl = self.app._render_fila_contrato(self._contrato(DNI), municipio="Saucejo, El", provincia="sevilla")
        finally:
            self.app._I18N_IDIOMA.reset(token)
        self.assertIn("Persoa física · ***4567**", html_gl)
        self.assertNotIn(DNI, html_gl)

    def test_al_pintar_la_fila_menor(self):
        r = {"id": "x", "adjudicatari": NIE, "nif": NIE, "fuente": "place", "organisme": "Ayto", "import_num": 100.0,
             "data_adjudicacio": "2025-01-01", "tipus_contracte": "Servicios", "descripcio": "x", "codi_cpv": "",
             "exercici": 2025, "municipio": "Osuna", "provincia": "sevilla"}
        html_ = self.app._render_fila_contrato_menor(r)
        self.assertNotIn(NIE, html_)
        self.assertIn("Persona física · ****4567*", html_)
        self.assertEqual(html_.count("****4567*"), 2)           # el nombre y el NIF; el «directivo» no lo repite


if __name__ == "__main__":
    unittest.main(verbosity=2)
