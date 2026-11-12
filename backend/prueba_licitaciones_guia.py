# encoding: utf-8
"""Pruebas de la guía «Cómo presentarse a una licitación» y de la lista de comprobación (12-11-2026).

  Parte A, guía (punto 2 del encargo), sin la app: los 4 idiomas tienen las mismas secciones, los mismos enlaces y las
  mismas cifras; cada sección enlaza a una fuente oficial; solo se enlaza a BOE, PLACSP y FNMT, y en el BOE solo a
  anclas comprobadas a mano el 12-11-2026.
  Parte B, lista de comprobación (punto 3), sin la app y con licitaciones INVENTADAS: qué dice en cada caso y que sale
  en la ficha del embudo, la del formulario, el correo semanal y el PDF.
  Parte C, con la app (--con-app, 2-3 min, sin red y con DATA_DIR temporal): la página en los 4 idiomas, el sitemap y
  el enlace a la guía en el correo de las alertas diarias de licitaciones (no en las de subvenciones).

    python backend/prueba_licitaciones_guia.py [--con-app]
"""
import collections
import html as H
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import filtro_embudo as E  # noqa: E402
import filtro_formulario as FF  # noqa: E402
import filtro_licitaciones as F  # noqa: E402
import licitaciones_guia as G  # noqa: E402
import licitaciones_place as LP  # noqa: E402

DIR = os.path.join(BASE, "guia_licitaciones")
IDIOMAS = ("es", "gl", "ca", "eu")
BOE = "https://www.boe.es/buscar/act.php?id=BOE-A-2017-12902#"
# Anclas del BOE comprobadas el 12-11-2026 en la página consolidada (cada una lleva al artículo que se cita)
ANCLAS_BOE = {"da-15": "DA 15ª", "a9-8": "art. 96", "a3-49": "art. 337", "a1-71": "art. 159", "a1-50": "art. 138",
              "a1-52": "art. 140", "a1-53": "art. 141", "a1-69": "art. 157", "a1-18": "art. 106",
              "a1-19": "art. 107", "a1-68": "art. 156", "a1-61": "art. 149", "a1-62": "art. 150",
              "a1-63": "art. 151", "a1-65": "art. 153", "a4-6": "art. 44", "a2-2": "art. 20", "a1-47": "art. 135",
              "a8-10": "art. 88", "a8-11": "art. 89", "a9-2": "art. 90", "a6-11": "art. 69", "a7-9": "art. 77"}
DOMINIOS = ("https://www.boe.es/", "https://www.contrataciondelestado.es/", "https://www.sede.fnmt.gob.es/")
SECCIONES = ("certificado", "alta", "pliegos", "preguntas", "deuc", "sobres", "garantias", "plazo", "apertura",
             "casos", "sumario", "sara", "ute", "clasificacion")
RE_CIFRA = re.compile(r"\d+(?:[.,]\d+)*")


def leer(lang):
    with open(os.path.join(DIR, f"{lang}.html"), encoding="utf-8") as f:
        return f.read()


def texto(h):
    return re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", "", h)))


class A_Guia(unittest.TestCase):
    def test_existen_con_descripcion_y_titulo(self):
        for lang in IDIOMAS:
            s = leer(lang)
            self.assertRegex(s, r"^<!-- description: .{40,} -->", lang)
            self.assertEqual(s.count("<h1>"), 1, lang)

    def test_mismas_secciones_enlaces_y_cifras(self):
        es = leer("es")
        ids_es = re.findall(r'<h[23] id="([a-z]+)"', es)
        self.assertEqual(set(ids_es), set(SECCIONES))
        for lang in IDIOMAS[1:]:
            s = leer(lang)
            self.assertEqual(re.findall(r'<h[23] id="([a-z]+)"', s), ids_es, lang)
            self.assertEqual(collections.Counter(re.findall(r'href="([^"]+)"', s)),
                             collections.Counter(re.findall(r'href="([^"]+)"', es)), lang)
            c_es = collections.Counter(RE_CIFRA.findall(texto(es)))
            c_tr = collections.Counter(RE_CIFRA.findall(texto(s)))
            self.assertEqual((c_es - c_tr, c_tr - c_es), (collections.Counter(), collections.Counter()), lang)

    def test_cada_seccion_tiene_fuente_oficial(self):
        for lang in IDIOMAS:
            s = leer(lang)
            trozos = re.split(r'(?=<h[23] id=")', s)[1:]
            for t in trozos:
                sec = re.match(r'<h[23] id="([a-z]+)"', t).group(1)
                if sec == "casos":            # el 10 solo agrupa: las fuentes van en cada subapartado
                    continue
                fuente = re.search(r'<p class="guia-fuente">(.*?)</p>', t, re.S)
                self.assertTrue(fuente, (lang, sec))
                self.assertTrue(any(u.startswith(DOMINIOS) for u in re.findall(r'href="([^"]+)"', fuente.group(1))),
                                (lang, sec))

    def test_solo_fuentes_oficiales_y_anclas_comprobadas(self):
        for lang in IDIOMAS:
            for u in re.findall(r'href="([^"]+)"', leer(lang)):
                if u.startswith("#"):
                    self.assertIn(u[1:], SECCIONES, (lang, u))
                    continue
                self.assertTrue(u.startswith(DOMINIOS), (lang, u))
                if u.startswith("https://www.boe.es/"):
                    self.assertTrue(u.startswith(BOE) and u[len(BOE):] in ANCLAS_BOE, (lang, u))
                if u.startswith("https://www.contrataciondelestado.es/"):
                    self.assertIn("?MOD=AJPERES", u, u)          # sin él, el servidor de PLACSP da 404

    def test_lo_que_pide_el_encargo(self):
        t = texto(leer("es"))
        for frase in ("certificado electrónico", "PCAP", "PPT", "DEUC", "sobre", "garantía provisional", "definitiva",
                      "Preguntar", "hora", "Apertura", "adjudica", "159.6", "SARA", "Diario Oficial de la Unión",
                      "UTE", "lo que manda en cada contrato es su pliego"):
            self.assertIn(frase.lower(), t.lower(), frase)
        # cifras legales comprobadas en el BOE el 12-11-2026
        for frase in ("80.000 euros", "60.000 euros", "10 días hábiles", "35 días", "15 días (20 en obras)",
                      "26 en obras", "12 días", "6 días", "5 %", "3 %", "500.000 euros", "100.000 euros"):
            self.assertIn(frase, t, frase)


def lic(**k):
    base = {"id": "L1", "titulo": "Limpieza de colegios", "organo": "Ayuntamiento inventado",
            "url": "https://contrataciondelestado.es/wps/poc?uri=deeplink:detalle_licitacion&idEvl=inventado",
            "fin_plazo": "2026-11-27 14:00", "ambito": "local", "provincia": "murcia", "nuts": "ES620",
            "cpv": "90910000", "cpvs": ["90910000"], "tipo": "2", "procedimiento": "1", "presupuesto": 100_000,
            "valor_estimado": 100_000, "duracion_meses": 12, "req": {}, "lotes_detalle": [], "sara": False,
            "pliegos": {"pcap": "https://contrataciondelestado.es/FileSystem/pcap-inventado",
                        "ppt": "https://contrataciondelestado.es/FileSystem/ppt-inventado"}}
    base.update(k)
    return base


PERFIL = {"cpvs": ["909"], "provincias": ["murcia"], "trabajadores": 5, "facturacion": "150k-300k",
          "clasificacion": [], "ute": True, "experiencia_publica": False, "certificados": [], "tipos": [],
          "anio_constitucion": 2012}
AHORA = datetime(2026, 11, 12, 10, 0)


def lista(**k):
    res = F.evaluar(lic(**k), PERFIL, AHORA)
    return dict((e, (t, en)) for e, t, en in G.lineas(res[0]["comprobar"]))


class B_ListaDeComprobacion(unittest.TestCase):
    def test_abierto_normal(self):
        d = lista()
        self.assertEqual(d["Procedimiento"][0], "Abierto.")
        self.assertEqual(d["Normas europeas (SARA)"][0], "No.")
        self.assertIn("El anuncio no la pide", d["Clasificación"][0])
        self.assertIn("El anuncio no pide ninguno", d["Certificados"][0])
        self.assertEqual(d["Plazo"][0], "Cierra el 27/11/2026 a las 14:00 (hora del anuncio). Después no se admiten "
                                        "ofertas.")
        self.assertEqual([t for t, _ in d["Pliegos"][1]], ["Pliego administrativo (PCAP)", "Pliego técnico (PPT)"])
        self.assertTrue(d["Anuncio oficial"][1][0][1].startswith("https://"))

    def test_sumario_simplificado_y_sara(self):
        d = lista(procedimiento="9", presupuesto=30_000, valor_estimado=30_000)
        self.assertIn("159.6", d["Procedimiento"][0])
        self.assertIn("Compruebe en el PCAP", d["Procedimiento"][0])       # 159.6 dice «podrá»: no se da por hecho
        d = lista(procedimiento="9", presupuesto=200_000, valor_estimado=200_000)
        self.assertIn("ROLECE", d["Procedimiento"][0])
        self.assertIn("Diario Oficial", lista(sara=True)["Normas europeas (SARA)"][0])
        self.assertEqual(lista(sara=None)["Normas europeas (SARA)"][0], "El anuncio no lo dice.")
        self.assertEqual(lista(procedimiento="")["Procedimiento"][0], "El anuncio no lo dice.")

    def test_clasificacion_y_certificados(self):
        perfil_obras = dict(PERFIL, cpvs=["45"], facturacion="3M-10M", trabajadores=40, clasificacion=["C2-4"])
        r = F.evaluar(lic(tipo="3", cpvs=["45000000"], presupuesto=900_000, valor_estimado=900_000,
                          req={"clas": ["C2-4"], "cert": ["ISO9001"]}), perfil_obras, AHORA)[0]
        d = dict((e, t) for e, t, _ in G.lineas(r["comprobar"]))
        self.assertTrue(d["Clasificación"].startswith("Pide: "), d["Clasificación"])
        self.assertIn("9001", d["Certificados"])
        r = F.evaluar(lic(tipo="3", cpvs=["45000000"], presupuesto=900_000, valor_estimado=900_000),
                      perfil_obras, AHORA)[0]
        d = dict((e, t) for e, t, _ in G.lineas(r["comprobar"]))
        self.assertIn("art. 77", d["Clasificación"])

    def test_plazo_sin_hora_y_sin_pliegos(self):
        d = lista(plazo_sin_hora=True, fin_plazo="2026-11-27 23:59", pliegos={}, url="")
        self.assertIn("El anuncio no da la hora", d["Plazo"][0])
        self.assertNotIn("23:59", d["Plazo"][0])                            # no se presenta una hora inventada
        self.assertIn("No vienen enlazados", d["Pliegos"][0])
        self.assertEqual(d["Anuncio oficial"][1], [])

    def test_lector_de_place(self):
        e = ('<entry><id>x</id><updated>2026-11-12T10:00:00+01:00</updated><cbc-place-ext:ContractFolderStatusCode>'
             'PUB</cbc-place-ext:ContractFolderStatusCode><cac:LegalDocumentReference><cbc:ID>pcap.pdf</cbc:ID>'
             '<cac:Attachment><cac:ExternalReference><cbc:URI>https://contrataciondelestado.es/a?x=1&amp;y=2</cbc:URI>'
             '</cac:ExternalReference></cac:Attachment></cac:LegalDocumentReference><cac:TenderingProcess>'
             '<cac:TenderSubmissionDeadlinePeriod><cbc:EndDate>2026-11-30</cbc:EndDate>'
             '</cac:TenderSubmissionDeadlinePeriod></cac:TenderingProcess></entry>')
        r = LP.analizar_entrada(e)
        self.assertEqual(r["pliegos"], {"pcap": "https://contrataciondelestado.es/a?x=1&y=2"})
        self.assertTrue(r["plazo_sin_hora"])
        self.assertIn('"plazo_sin_hora":true', LP.requisitos_json(r))
        self.assertIn('"pliegos"', LP.requisitos_json(r))

    def test_en_las_cuatro_salidas(self):
        res = F.filtrar([lic()], PERFIL, AHORA)
        r = next(x for g in F.GRUPOS for x in res[g])
        guia = G.guia_url(G.SITIO)
        # ficha del formulario (vista previa y «mis licitaciones»)
        h = FF._ficha_html(r)
        self.assertIn("Lista de comprobación", h)
        self.assertIn(f'href="{G.GUIA_RUTA}"', h)
        # correo semanal
        asunto, txt, html_, _n, _t = FF.correo_semanal(res, "https://x.test/ver", "https://x.test/baja", AHORA)
        self.assertIn("Lista de comprobación", html_)
        self.assertIn(guia, html_)
        self.assertIn(guia, txt)
        self.assertIn("Pliego administrativo (PCAP): https://", txt)
        # embudo
        p, err = E.leer({"cpv": ["90"], "ambito": ["murcia"], "facturacion": ["150k-300k"], "trabajadores": ["1-5"],
                         "clasificacion": ["no"]})
        self.assertFalse(err)
        re_e = E.evaluar(lic(), p, AHORA)
        self.assertTrue(re_e)
        h = E._ficha_html(re_e[0])
        self.assertIn("Lista de comprobación", h)
        self.assertIn(f'href="{G.GUIA_RUTA}"', h)
        self.assertIn("pcap-inventado", h)
        # PDF (si reportlab está instalado; en producción no lo está)
        try:
            import filtro_licitaciones_informe as INF
        except ImportError:
            self.skipTest("sin reportlab: el PDF no se puede comprobar aquí")
        ruta = os.path.join(tempfile.mkdtemp(), "muestra.pdf")
        INF.informe_pdf(ruta, [("Sector", "Limpieza")], res, AHORA)
        from pypdf import PdfReader
        t = "".join(p.extract_text() or "" for p in PdfReader(ruta).pages)
        self.assertIn("Lista de comprobación", t)
        self.assertIn("como-presentarse", t.replace("\n", ""))


class C_ConLaApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if "--con-app" not in sys.argv:
            raise unittest.SkipTest("sin --con-app")
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        os.environ.update(DATA_DIR=cls.tmp.name, HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9",
                          I18N_PUBLICADOS="gl,ca,eu")
        import app
        cls.app = app

    def ruta(self, path, lang="es"):
        tk = self.app._I18N_IDIOMA.set(lang)
        try:
            code, _h, body = self.app._route_get(path, {}, gzip_ok=False)
        finally:
            self.app._I18N_IDIOMA.reset(tk)
        return code, body.decode("utf-8")

    def test_pagina_en_los_cuatro_idiomas(self):
        titulos = {"es": "Cómo presentarse a una licitación", "gl": "Como presentarse a unha licitación",
                   "ca": "Com presentar-se a una licitació", "eu": "Nola aurkeztu lizitazio batera"}
        for lang, tit in titulos.items():
            code, h = self.ruta(G.GUIA_RUTA, lang)
            self.assertEqual(code, 200, lang)
            self.assertIn(f"<h1>{tit}</h1>", h)
            self.assertIn('href="https://www.boe.es/buscar/act.php?id=BOE-A-2017-12902#a1-71"', h)
            if lang != "es":
                self.assertIn(f'lang="{lang}"', h)
        self.assertEqual(self.ruta(G.GUIA_RUTA + "/")[0], 200)
        self.assertIn(G.GUIA_RUTA + "</loc>", self.ruta("/sitemap.xml")[1])

    def test_alertas_diarias_solo_enlace(self):
        app = self.app

        class Alm:
            def firma(self, *a):
                return "f"
        s = {"id": 1, "idioma": "gl", "correo": "persona@ejemplo.test"}
        item = {"titulo": "Licitación inventada", "importe": 1000, "fecha": "2026-11-20", "detalle": "", "url": ""}
        sec_lic = [({"tipo": "licitaciones", "filtros": {}}, [item])]
        sec_sub = [({"tipo": "subvenciones", "filtros": {}}, [item])]
        pl, _n = app._alertas_en_idioma("gl", app._alertas_correo_novedades, Alm(), s, sec_lic)
        cuerpo = str(pl)
        self.assertIn("/gl" + G.GUIA_RUTA, cuerpo)
        self.assertIn("Como presentarse a unha licitación, paso a paso", cuerpo)
        self.assertNotIn("Lista de comprobación", cuerpo)                   # en las diarias, solo el enlace
        pl, _n = app._alertas_en_idioma("es", app._alertas_correo_novedades, Alm(), s, sec_sub)
        self.assertNotIn(G.GUIA_RUTA, str(pl))


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--con-app"]
    unittest.main(argv=argv, verbosity=2)
