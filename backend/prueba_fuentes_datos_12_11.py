# encoding: utf-8
"""Pruebas de los arreglos de fuentes y datos del 12-11-2026 (rama wip/fuentes-datos-12-11), una clase por punto:

  1. Sin notas por suposición junto a un sueldo de 0 € («posible renuncia por doble cargo»): ni en la ficha de
     Hinojosa del Campo ni en ninguna otra, ni en la pieza /casos/sueldo-cero-barcelona (4 idiomas), ni en los .po.
  2. El sueldo del alcalde lleva SIEMPRE el enlace a su fuente oficial (ISPA); sin ejercicio, «sin fuente oficial»
     y sin la cifra. Comprobado en Badalona, Hinojosa del Campo y Vitoria-Gasteiz y en todos los municipios.
  3. Ningún nombre de alcalde o concejal enlaza a un buscador (Badalona y todos los municipios).
  4. Fechas futuras: aviso «Fecha según la fuente, posible error» sin cambiar la fecha, fuera de la «última fecha»
     del Índice, y comprobación general (comprobar_fechas_futuras.py).
  5. La portada usa la misma fecha y las mismas cifras en todos los idiomas.
  6. Existe /sueldos-concejales y se llega desde /rankings y desde la ficha.

    python backend/prueba_fuentes_datos_12_11.py

Importa app.py con la red cortada (proxy a un puerto cerrado) y DATA_DIR en una carpeta temporal, para no tocar el
cache.db local. Proceso pesado (~1-2 min): de uno en uno.
"""
import os
import re
import sqlite3
import sys
import tempfile
import time
import unittest
from datetime import date

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

ISPA = "https://digital.gob.es/funcion-publica/dgfp/espacio-ispa/estadisticas/informac_estad_"
RE_BUSCADOR = re.compile(r"google\.[a-z.]+/search|bing\.com/search|duckduckgo\.com/\?|search\.yahoo\.", re.I)
RE_SUPOSICION = re.compile(r"renuncia|doble cargo|dobre cargo|doble càrrec|bikoitz|renúncia|uko egin", re.I)


def setUpModule():
    global app, TMP
    TMP = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)    # app deja abierto cache.db
    os.environ.update(DATA_DIR=TMP.name, HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9",
                      I18N_PUBLICADOS="gl,ca,eu", I18N_CASOS_PUBLICADOS="gl,ca,eu")
    import app as _app
    app = _app


def en_idioma(lang, f, *a, **k):
    tk = app._I18N_IDIOMA.set(lang)
    try:
        return f(*a, **k)
    finally:
        app._I18N_IDIOMA.reset(tk)


def ruta(path, lang="es"):
    code, _h, body = en_idioma(lang, app._route_get, path, {}, gzip_ok=False)
    return code, body.decode("utf-8")


def todos_los_bloques():
    """(clave, municipio, provincia, html) del bloque de alcalde y concejales de cada municipio, en castellano."""
    for clave, info in app.ALCALDES_CONCEJALES.items():
        muni, prov = info.get("municipio") or clave, info.get("provincia")
        yield clave, muni, prov, app.alcalde_concejales_html(muni, prov)


class P1SinSuposiciones(unittest.TestCase):
    def test_hinojosa_del_campo(self):
        r = app.RETRIBUCIONES_ISPA[app.clave_municipio("Hinojosa del Campo", "soria")]
        self.assertEqual(r["importe"], 0)
        for lang in ("es", "gl", "ca", "eu"):
            h = en_idioma(lang, app.alcalde_concejales_html, "Hinojosa del Campo", "soria")
            self.assertNotRegex(h, RE_SUPOSICION, lang)
            self.assertIn(f'href="{ISPA}{r["anio"]}"', h, lang)
        h = app.alcalde_concejales_html("Hinojosa del Campo", "soria")
        self.assertIn("0 €/año (retribuciones de 2024) según", h)

    def test_ningun_sueldo_cero_con_suposicion(self):
        n = 0
        for clave, muni, prov, h in todos_los_bloques():
            r = app.RETRIBUCIONES_ISPA.get(app.clave_municipio(muni, prov))
            if r and r.get("importe") == 0 and h:
                n += 1
                self.assertNotRegex(h, RE_SUPOSICION, muni)
                self.assertIn("según <a", h, muni)
        self.assertGreater(n, 1000)        # 2.291 alcaldes con 0 € en ISPA 2024

    def test_pieza_de_casos_en_los_cuatro_idiomas(self):
        for lang in ("es", "gl", "ca", "eu"):
            code, h = ruta("/casos/sueldo-cero-barcelona", lang)
            self.assertEqual(code, 200)
            self.assertNotRegex(re.sub(r"<[^>]+>", " ", h), RE_SUPOSICION, lang)
            self.assertIn(f'href="{ISPA}2024"', h, lang)
            if lang != "es":       # la traducción se sirve (si las cifras no cuadraran, saldría el castellano)
                self.assertIn(f'lang="{lang}"', h)
                ok, faltan, sobran = app._comparar_cifras_caso("sueldo-cero-barcelona", lang)
                self.assertTrue(ok, (lang, faltan, sobran))

    def test_po_sin_las_notas(self):
        for lang in ("gl", "ca", "eu"):
            cat = app._I18N_CATALOGOS[lang]
            self.assertNotIn("(posible renuncia por doble cargo ℹ️)", cat)
            self.assertFalse([k for k in cat if k.startswith("Un sueldo de 0 € en ISPA")])


class P2SueldoAlcaldeConFuente(unittest.TestCase):
    def test_tres_municipios_citados(self):
        for muni, prov in (("Badalona", "barcelona"), ("Hinojosa del Campo", "soria"),
                           ("Vitoria-Gasteiz", "pais_vasco")):
            h = app.alcalde_concejales_html(muni, prov)
            m = re.search(r'<span class="pol-retrib"[^>]*>💰(.*?)</span>', h, re.S)
            self.assertTrue(m, muni)
            self.assertIn(f'href="{ISPA}2024"', m.group(1), muni)

    def test_todos_los_sueldos_con_enlace(self):
        n = 0
        for clave, muni, prov, h in todos_los_bloques():
            for m in re.finditer(r'<span class="pol-retrib"[^>]*>💰(.*?)</span>', h, re.S):
                n += 1
                self.assertIn(f'href="{ISPA}', m.group(1), muni)
        self.assertGreater(n, 6000)

    def test_sin_ejercicio_no_hay_cifra(self):
        h = app._sueldo_alcalde_html({"importe": 51234.5, "anio": ""})
        self.assertIn("sin fuente oficial", h)
        self.assertNotIn("51.234", h)
        self.assertIn("sin datos de retribución", app._sueldo_alcalde_html(None))
        h = app._sueldo_alcalde_html({"importe": 51234.5, "anio": 2024, "regimen_dedicacion": "Exclusiva"})
        self.assertIn("51.234,50 €/año (retribuciones de 2024)", h)
        self.assertIn(f'href="{ISPA}2024"', h)
        self.assertIn('title="Régimen de dedicación según ISPA: Exclusiva"', h)

    def test_presidentes_de_diputacion_con_enlace(self):
        h = app.render_rankings_html(None, None, "murcia", "todas", None, None)
        for m in re.finditer(r'<div class="top1-directivo">💰(.*?)</div>', h, re.S):
            self.assertIn(f'href="{ISPA}', m.group(1))


class P3SinBuscadores(unittest.TestCase):
    def test_badalona(self):
        h = app.alcalde_concejales_html("Badalona", "barcelona") + app.sueldos_concejales_html("Badalona", "barcelona")
        self.assertTrue(h)
        self.assertNotRegex(h, RE_BUSCADOR)
        self.assertIsNone(re.search(r'<a [^>]*>\s*<b class="pol-nombre"', h))

    def test_todos_los_municipios(self):
        for clave, muni, prov, h in todos_los_bloques():
            self.assertNotRegex(h, RE_BUSCADOR, muni)
            self.assertIsNone(re.search(r'<a [^>]*>[^<]*<b class="pol-nombre"', h), muni)
        for clave, regs in app.SUELDOS_CONCEJALES.items():
            r = regs[0]
            h = app.sueldos_concejales_html(r["municipio"], r["provincia"] or None)
            self.assertNotRegex(h, RE_BUSCADOR, clave)
            self.assertFalse([u for u in re.findall(r'href="([^"]+)"', h)
                              if u.startswith("http") and not u.startswith("https://")], clave)


class P4FechasFuturas(unittest.TestCase):
    FILA = {"id": "Vitoria-Gasteiz::EUSKADI::2025$CO_MSUM$00771121_00001", "municipio": "Vitoria-Gasteiz",
            "provincia": "pais_vasco", "fuente": "euskadi", "adjudicatari": "BROKER KIROL, S.L.", "nif": "B95764999",
            "import_num": 10230.5, "data_adjudicacio": "2026-12-16", "tipus_contracte": "Suministros",
            "descripcio": "Retirada y transporte con descarga e instalación de una red de protección"}

    def test_detector(self):
        hoy = date(2026, 11, 12)
        self.assertTrue(app._fecha_posterior_a_hoy("2026-12-16", hoy))
        self.assertTrue(app._fecha_posterior_a_hoy("2926-09-24T00:00:00", hoy))
        self.assertFalse(app._fecha_posterior_a_hoy("2026-11-12", hoy))
        self.assertFalse(app._fecha_posterior_a_hoy("2026-11-11", hoy))
        self.assertFalse(app._fecha_posterior_a_hoy("", hoy))
        self.assertFalse(app._fecha_posterior_a_hoy("2026-13-45", hoy))

    def test_fila_con_aviso_y_la_fecha_de_la_fuente(self):
        if not app._fecha_posterior_a_hoy("2026-12-16"):
            self.skipTest("el 16-12-2026 ya no es futuro")
        h = app._render_fila_contrato_menor(dict(self.FILA))
        self.assertIn('<div class="lid">2026-12-16</div>', h)          # la fecha no se cambia
        self.assertIn("Fecha según la fuente, posible error", h)
        h = app._render_fila_contrato_menor(dict(self.FILA, data_adjudicacio="2025-12-16"))
        self.assertNotIn("posible error", h)
        h = en_idioma("gl", app._render_fila_contrato_menor, dict(self.FILA))
        self.assertIn("Data segundo a fonte, posible erro", h)

    def test_indice_no_usa_la_fecha_futura(self):
        hoy = app._ahora_madrid().date()
        filas = [("p1", "Pueblo Prueba Fechas", "alava", "euskadi", "2099-01-01"),
                 ("p2", "Pueblo Prueba Fechas", "alava", "euskadi", hoy.isoformat()),
                 ("p3", "Pueblo Prueba Fechas", "alava", "euskadi", "2025-03-01")]
        with app._db_lock:
            app._db.executemany("INSERT INTO contratos_menors_locales (id, municipio, provincia, fuente, "
                                "adjudicatari, data_adjudicacio, ts) VALUES (?,?,?,?,'X SL',?,0)", filas)
            app._db.commit()
        try:
            det = app._indice_menores_detalle_por_municipio()
            d = next(v for (m, _p), v in det.items() if m == app.normalizar("Pueblo Prueba Fechas"))
            self.assertEqual(d["ultima"], hoy.isoformat())
            self.assertEqual(d["total"], 3)                        # el contrato sigue contando como contrato
        finally:
            with app._db_lock:
                app._db.execute("DELETE FROM contratos_menors_locales WHERE municipio = 'Pueblo Prueba Fechas'")
                app._db.commit()

    def test_comprobacion_general(self):
        import comprobar_fechas_futuras as cff
        ruta_db = os.path.join(TMP.name, "fechas_prueba.db")
        con = sqlite3.connect(ruta_db)
        con.execute("CREATE TABLE contratos_menors_locales (id TEXT, municipio TEXT, fuente TEXT, "
                    "data_adjudicacio TEXT, adjudicatari TEXT)")
        con.execute("CREATE TABLE municipios (municipio TEXT, data TEXT, ts REAL)")
        con.executemany("INSERT INTO contratos_menors_locales VALUES (?,?,?,?,?)", [
            ("a", "Vitoria-Gasteiz", "euskadi", "2026-12-16", "BROKER KIROL, S.L."),
            ("b", "Vitoria-Gasteiz", "euskadi", "2026-11-12", "HOY SL"),
            ("c", "Reus", "rpc-tarragona", "2029-09-18", "FUTURA SL")])
        con.execute("INSERT INTO municipios VALUES ('x', ?, 0)",
                    ('{"municipio": "X", "contratos": [{"fuente": "PSCP", "fecha": "2033-12-22"}, '
                     '{"fuente": "PSCP", "fecha": "2024-01-01"}]}',))
        con.commit()
        con.close()
        res = cff.comprobar(ruta_db, date(2026, 11, 12))
        self.assertEqual(sorted(f["id"] for f in res["menores"]), ["a", "c"])     # el de hoy no es futuro
        self.assertEqual([f["fecha"] for f in res["formales"]], ["2033-12-22"])
        self.assertEqual(set(res["menores"][0]), set(cff.CAMPOS))


class P5PortadaIgualEnTodosLosIdiomas(unittest.TestCase):
    def test_misma_fecha_y_cifras(self):
        datos = app._db_municipios_ligeros()
        res = {}
        for lang in ("es", "gl", "ca", "eu"):
            h = en_idioma(lang, app.render_landing_nacional_html, datos)
            stats = re.search(r'<div class="stats-bar">(.*?)</div>\s*(?:<div class="portada-actualizado">([^<]*)|<)',
                              h, re.S)
            res[lang] = (re.findall(r"<span>([^<]+)</span>", stats.group(1)), re.findall(r"\d{2}-\d{2}-\d{4}",
                                                                                          stats.group(2) or ""))
        self.assertEqual(len({str(v) for v in res.values()}), 1, res)

    def test_un_cambio_vuelve_a_montar_los_otros_idiomas(self):
        llamadas = []
        original = app._calentar_portada
        app._calentar_portada = lambda: llamadas.append(1)
        try:
            with app._paginas_lock:
                for lang in ("es", "gl", "ca"):
                    app._paginas_cache[(lang, "/")] = {"gz": b"", "ts": time.time(), "refrescando": False,
                                                       "grupo": None}
            app._portada_cabecera_memo.update(ts=0.0, valor=None)
            t0 = time.time()
            self.assertEqual(en_idioma("es", app._portada_cabecera, lambda: (1, 2, 3, 4, 5.0, "10-11-2026"), t0),
                             (1, 2, 3, 4, 5.0, "10-11-2026"))
            # dentro del plazo, la misma cuenta para gl aunque la suya fuera otra
            self.assertEqual(en_idioma("gl", app._portada_cabecera, lambda: (9, 9, 9, 9, 9.0, "11-11-2026"), t0 + 5),
                             (1, 2, 3, 4, 5.0, "10-11-2026"))
            self.assertEqual(llamadas, [])
            # caduca y cambia: las portadas de los otros idiomas pasan a viejas y se vuelven a montar
            en_idioma("es", app._portada_cabecera, lambda: (1, 2, 6, 4, 5.0, "11-11-2026"),
                      t0 + app._PORTADA_CABECERA_TTL + 1)
            time.sleep(0.2)
            self.assertEqual(llamadas, [1])
            ahora = time.time()
            with app._paginas_lock:
                edad = {k[0]: ahora - e["ts"] for k, e in app._paginas_cache.items() if k[1:] == ("/",)}
            self.assertGreaterEqual(edad["gl"], app._PAGINAS_TTL)
            self.assertGreaterEqual(edad["ca"], app._PAGINAS_TTL)
            self.assertLess(edad["es"], app._PAGINAS_TTL)
        finally:
            app._calentar_portada = original
            app._portada_cabecera_memo.update(ts=0.0, valor=None)
            with app._paginas_lock:
                app._paginas_cache.clear()


class P6PaginaSueldosConcejales(unittest.TestCase):
    def test_pagina(self):
        for lang in ("es", "gl"):
            code, h = ruta("/sueldos-concejales", lang)
            self.assertEqual(code, 200, lang)
            n_munis = len({(r["municipio"], r["provincia"]) for regs in app.SUELDOS_CONCEJALES.values() for r in regs})
            self.assertGreater(n_munis, 40)
            self.assertEqual(len(re.findall(r'<tr><td><a href="(?:/gl)?/\?muni=', h)), n_munis, lang)
            self.assertNotRegex(h, RE_BUSCADOR)
        self.assertIn("Soldos de concelleiros", h)

    def test_enlaces_desde_rankings_y_ficha(self):
        h = app.render_rankings_html(None, None, "murcia", "todas", None, None)
        self.assertIn('href="/sueldos-concejales"', h)
        r = next(iter(app.SUELDOS_CONCEJALES.values()))[0]
        self.assertIn('href="/sueldos-concejales"', app.sueldos_concejales_html(r["municipio"], r["provincia"] or None))
        code, h = ruta("/sitemap.xml")
        self.assertIn("/sueldos-concejales</loc>", h)


if __name__ == "__main__":
    unittest.main(verbosity=2)
