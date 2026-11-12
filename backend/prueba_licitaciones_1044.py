# encoding: utf-8
"""Pruebas del feed 1044 de PLACSP (plataformas autonómicas agregadas), 12-11-2026.

  Sin la app: tipo de organismo de las plataformas autonómicas, clave de repetidos y lectura de un anuncio del 1044.
  Con la app (--con-app, 2-3 min, sin red: PLACE se simula): repetidos entre 643 y 1044 en los dos órdenes, marca del
  Atom por fuente, ZIP del 1044 de uno en uno y nunca con el refresco nocturno, hueco del Atom, filtro por
  ayuntamiento con Ajuntament/Udala/Concello, purga, interruptor LIC_AGREGADAS y texto de /convocatorias.

    python backend/prueba_licitaciones_1044.py [--con-app]
"""
import io
import os
import sys
import tempfile
import unittest
import zipfile

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import licitaciones_place as LP  # noqa: E402


def entrada(eid, organo, expediente="EXP-1", actualizado="2026-11-12T10:00:00+01:00", agente="Generalitat de Catalunya",
            padres=("Entitats de l'administració local",), nuts="ES511", fin="2099-01-01", estado="PUB", nif=""):
    """Un <entry> CODICE mínimo. Con `agente` es como los del feed 1044; con agente="" y padres de PLACE, del 643."""
    party_id = f'<cac:PartyIdentification><cbc:ID schemeName="NIF">{nif}</cbc:ID></cac:PartyIdentification>' if nif else ""
    agente_xml = (f"<cac:AgentParty><cac:PartyName><cbc:Name>{agente}</cbc:Name></cac:PartyName></cac:AgentParty>"
                  if agente else "")
    padres_xml = "".join(f"<cac-place-ext:ParentLocatedParty><cac:PartyName><cbc:Name>{p}</cbc:Name></cac:PartyName>"
                         for p in padres) + "</cac-place-ext:ParentLocatedParty>" * len(padres)
    return (f'<entry><id>{eid}</id><title>Obra de prueba {eid[-3:]}</title><updated>{actualizado}</updated>'
            f'<link href="https://contractaciopublica.cat/anunci/{eid[-3:]}"/>'
            f'<cac-place-ext:ContractFolderStatus><cbc:ContractFolderID>{expediente}</cbc:ContractFolderID>'
            f'<cbc-place-ext:ContractFolderStatusCode>{estado}</cbc-place-ext:ContractFolderStatusCode>'
            f'<cac-place-ext:LocatedContractingParty><cac:Party>{party_id}<cac:PartyName><cbc:Name>{organo}</cbc:Name>'
            f'</cac:PartyName>{agente_xml}</cac:Party>{padres_xml}</cac-place-ext:LocatedContractingParty>'
            f'<cac:ProcurementProject><cbc:Name>Obra</cbc:Name><cbc:TypeCode>3</cbc:TypeCode><cac:BudgetAmount>'
            f'<cbc:TaxExclusiveAmount>100000</cbc:TaxExclusiveAmount></cac:BudgetAmount><cac:RealizedLocation>'
            f'<cbc:CountrySubentityCode>{nuts}</cbc:CountrySubentityCode></cac:RealizedLocation></cac:ProcurementProject>'
            f'<cac:TenderingProcess><cbc:ProcedureCode>1</cbc:ProcedureCode><cac:TenderSubmissionDeadlinePeriod>'
            f'<cbc:EndDate>{fin}</cbc:EndDate><cbc:EndTime>14:00:00</cbc:EndTime></cac:TenderSubmissionDeadlinePeriod>'
            f'</cac:TenderingProcess></cac-place-ext:ContractFolderStatus></entry>')


def atom(*entradas, siguiente=""):
    sig = f'<link href="{siguiente}" rel="next"/>' if siguiente else ""
    return ("<feed>" + sig + "".join(entradas) + "</feed>").encode("utf-8")


def ambito(organo, agente="Generalitat de Catalunya", padres=()):
    return LP.analizar_entrada(entrada("x1", organo, agente=agente, padres=padres))["ambito"]


class A_SinApp(unittest.TestCase):
    def test_tipo_de_organismo_de_las_plataformas(self):
        self.assertEqual(ambito("Ajuntament de Barcelona", padres=("Entitats de l'administració local",)), "local")
        self.assertEqual(ambito("Institut Municipal d'Educació", padres=("Entitats de l'administració local",)),
                         "local")
        self.assertEqual(ambito("Ayuntamiento de Bilbao-Alcalde", agente="Gobierno Vasco",
                                padres=("Ayuntamiento de Bilbao",)), "local")
        self.assertEqual(ambito("Diputación Foral de Gipuzkoa", agente="Gobierno Vasco"), "local")
        self.assertEqual(ambito("Concello de Dozón", agente="Xunta de Galicia"), "local")
        self.assertEqual(ambito("Departament de Salut",
                                padres=("Departaments i sector públic de la Generalitat de Catalunya",)), "autonomico")
        self.assertEqual(ambito("Servicio Andaluz de Salud", agente="Junta de Andalucía",
                                padres=("Junta de Andalucía",)), "autonomico")
        self.assertEqual(ambito("OSAKIDETZA - Servicio Vasco de Salud", agente="Gobierno Vasco"), "autonomico")
        self.assertEqual(ambito("Universitat de Barcelona", padres=("Universitats",)), "otros")
        self.assertEqual(ambito("Consorci Sanitari de Terrassa", padres=("Altres ens",)), "otros")

    def test_el_643_no_cambia(self):
        # sin <cac:AgentParty> (643): las reglas nuevas no se aplican
        self.assertEqual(ambito("Ayuntamiento de Murcia", agente="", padres=("ENTIDADES LOCALES",)), "local")
        self.assertEqual(ambito("Ayuntamiento de Murcia", agente="", padres=()), "otros")
        self.assertEqual(ambito("Ministerio de Hacienda", agente="", padres=("ADMINISTRACIÓN GENERAL DEL ESTADO",)),
                         "estatal")

    def test_clave_de_repetidos(self):
        a = LP.clave_duplicado("2026/123-OB", "Ajuntament de Sant Adrià de Besòs")
        self.assertEqual(a, LP.clave_duplicado(" 2026 / 123 ob", "AJUNTAMENT DE SANT ADRIA DE BESOS"))
        self.assertNotEqual(a, LP.clave_duplicado("2026/124-OB", "Ajuntament de Sant Adrià de Besòs"))
        self.assertNotEqual(a, LP.clave_duplicado("2026/123-OB", "Ajuntament de Badalona"))
        self.assertEqual(LP.clave_duplicado("", "Ajuntament de Badalona"), "")       # sin expediente no se cruza

    def test_lectura_de_un_anuncio_del_1044(self):
        r = LP.analizar_entrada(entrada("https://x/1044/001", "Ajuntament de Barcelona"))
        self.assertEqual((r["organo"], r["expediente"], r["provincia"], r["comunidad"], r["ambito"]),
                         ("Ajuntament de Barcelona", "EXP-1", "barcelona", "cataluna", "local"))
        self.assertEqual(r["fin_plazo"], "2099-01-01 14:00")
        self.assertFalse(r["plazo_sin_hora"])


class Respuesta:
    def __init__(self, contenido, codigo=200):
        self.content, self.status_code = contenido, codigo

    def iter_content(self, n):
        for i in range(0, len(self.content), n):
            yield self.content[i:i + n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class SesionFalsa:
    """Sustituye a app.session: devuelve lo que diga `paginas` (url -> bytes) y anota cada petición."""
    def __init__(self, paginas):
        self.paginas, self.pedidas = paginas, []

    def get(self, url, **k):
        self.pedidas.append(url)
        return Respuesta(self.paginas[url]) if url in self.paginas else Respuesta(b"", 404)


class B_ConLaApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if "--con-app" not in sys.argv:
            raise unittest.SkipTest("sin --con-app")
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        os.environ.update(DATA_DIR=cls.tmp.name, HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9")
        import app
        cls.app = app

    def setUp(self):
        with self.app._db_lock:
            self.app._db.execute("DELETE FROM licitaciones")
            self.app._db.execute("DELETE FROM settings WHERE clave LIKE 'licitaciones_%'")
            self.app._db.commit()
        self.sesion_original = self.app.session

    def tearDown(self):
        self.app.session = self.sesion_original

    def filas(self):
        with self.app._db_lock:
            return {r[0]: r[1:] for r in self.app._db.execute(
                "SELECT id, estado, fuente, ambito, municipio FROM licitaciones")}

    def test_filas_con_todas_las_columnas(self):
        app = self.app
        self.assertEqual(len(app._licitacion_fila_cerrada("a", "b", "ADJ", "1044", 1.0)), len(app._LIC_COLUMNAS))
        r = LP.analizar_entrada(entrada("https://x/1044/001", "Ajuntament de Barcelona"))
        self.assertEqual(len(app._licitacion_fila(r, 1.0, "1044")), len(app._LIC_COLUMNAS))

    def test_repetidos_en_los_dos_ordenes(self):
        app = self.app
        # 1) llega primero la de PLACE (643), luego la misma en el 1044
        app._licitaciones_ingerir_atom(atom(entrada("https://x/643/001", "Ajuntament de Badalona", "EXP-9",
                                                    agente="", padres=("ENTIDADES LOCALES",), nif="P0801500J")))
        app._licitaciones_ingerir_atom(atom(entrada("https://x/1044/001", "AJUNTAMENT DE BADALONA", "exp 9")), "1044")
        # 2) al revés: primero el 1044 (se ve), luego el 643 (la pasada del final del ciclo la marca)
        app._licitaciones_ingerir_atom(atom(entrada("https://x/1044/002", "Ajuntament de Mataró", "EXP-10")), "1044")
        self.assertEqual(self.filas()["https://x/1044/002"][0], "PUB")
        app._licitaciones_ingerir_atom(atom(entrada("https://x/643/002", "Ajuntament de Mataró", "EXP-10",
                                                    agente="", padres=("ENTIDADES LOCALES",))))
        self.assertEqual(app._licitaciones_marcar_duplicadas(), 1)
        # 3) mismo expediente, otro órgano: no es la misma
        app._licitaciones_ingerir_atom(atom(entrada("https://x/1044/003", "Ajuntament de Lleida", "EXP-9")), "1044")
        f = self.filas()
        self.assertEqual(f["https://x/1044/001"][:2], ("DUP", "1044"))
        self.assertEqual(f["https://x/1044/002"][0], "DUP")
        self.assertEqual(f["https://x/1044/003"][0], "PUB")
        self.assertEqual(f["https://x/643/001"][:2], ("PUB", "643"))
        # 4) una actualización posterior del 1044 no la vuelve a enseñar
        app._licitaciones_ingerir_atom(atom(entrada("https://x/1044/001", "AJUNTAMENT DE BADALONA", "exp 9",
                                                    actualizado="2026-11-13T10:00:00+01:00")), "1044")
        self.assertEqual(self.filas()["https://x/1044/001"][0], "DUP")
        with app._db_lock:
            vigentes = app._db.execute("SELECT count(*) FROM licitaciones WHERE estado='PUB'").fetchone()[0]
        self.assertEqual(vigentes, 3)                           # 643/001, 643/002 y 1044/003

    def test_marca_del_atom_por_fuente(self):
        app = self.app
        # la del 643 es más reciente: si la marca no fuera por fuente, el 1044 pararía en la primera página
        app._licitaciones_ingerir_atom(atom(entrada("https://x/643/001", "Ministerio", agente="",
                                                    actualizado="2026-11-12T23:00:00+01:00")))
        app._licitaciones_ingerir_atom(atom(entrada("https://x/1044/000", "Ajuntament de Reus",
                                                    actualizado="2026-11-01T10:00:00+01:00")), "1044")
        p1, p2 = app.PLACE_AGREGADAS_FEED_LIVE, "https://contrataciondelsectorpublico.gob.es/p2.atom"
        app.session = SesionFalsa({
            p1: atom(entrada("https://x/1044/010", "Ajuntament de Reus", nuts="ES514",
                             actualizado="2026-11-10T10:00:00+01:00"),
                     siguiente=p2),
            p2: atom(entrada("https://x/1044/011", "Ajuntament de Reus", actualizado="2026-10-30T10:00:00+01:00"))})
        self.assertTrue(app._licitaciones_desde_atom(app.PLACE_AGREGADAS_FEED_LIVE, "1044"))
        self.assertEqual(app.session.pedidas, [p1, p2])
        f = self.filas()
        self.assertEqual(f["https://x/1044/010"][1], "1044")
        self.assertEqual(f["https://x/1044/010"][3], "reus")              # Ajuntament de Reus -> su ficha

    def test_hueco_en_el_atom(self):
        app = self.app
        app._licitaciones_ingerir_atom(atom(entrada("https://x/1044/000", "Ajuntament de Reus",
                                                    actualizado="2026-10-01T10:00:00+01:00")), "1044")
        p1, p2 = app.PLACE_AGREGADAS_FEED_LIVE, "https://contrataciondelsectorpublico.gob.es/p2.atom"
        app.session = SesionFalsa({p1: atom(entrada("https://x/1044/010", "Ajuntament de Reus",
                                                    actualizado="2026-11-10T10:00:00+01:00"), siguiente=p2)})
        maximo = app.LIC_MAX_PAGINAS_ATOM
        app.LIC_MAX_PAGINAS_ATOM = 1
        try:
            self.assertFalse(app._licitaciones_desde_atom(app.PLACE_AGREGADAS_FEED_LIVE, "1044"))
        finally:
            app.LIC_MAX_PAGINAS_ATOM = maximo

    def test_zips_del_1044_de_uno_en_uno(self):
        app = self.app
        meses = app._lic_meses_recientes(app.LIC_AGREGADAS_MESES)
        paginas = {}
        for i, anomes in enumerate(meses):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr("a.atom", atom(entrada(f"https://x/1044/z{i}", "Ajuntament de Girona", f"EXP-Z{i}"))
                           + b" " * 2000)
            paginas[app.PLACE_AGREGADAS_ZIP.format(anomes=anomes)] = buf.getvalue()
        app.session = SesionFalsa(paginas)
        with app._actualizando_todos_lock:                      # refresco nocturno: nada
            self.assertEqual(app._licitaciones_agregadas_zips(), 0)
        self.assertEqual(app.session.pedidas, [])
        self.assertEqual(app._licitaciones_agregadas_zips(), 1)
        self.assertEqual(app.session.pedidas, [app.PLACE_AGREGADAS_ZIP.format(anomes=meses[0])])   # el mes en curso
        self.assertEqual(app._licitaciones_agregadas_zips(), 1)
        self.assertEqual(app._licitaciones_agregadas_zips(), 0)    # ya están los dos
        self.assertEqual(len(app.session.pedidas), 2)
        self.assertEqual({k: v[1] for k, v in self.filas().items()}, {"https://x/1044/z0": "1044",
                                                                     "https://x/1044/z1": "1044"})
        self.assertFalse([f for f in os.listdir(app.CACHE_DIR) if f.startswith("place1044_")])   # temporal borrado

    def test_filtro_por_ayuntamiento(self):
        m = self.app._licitacion_municipio
        self.assertEqual(m("Ajuntament de Barcelona", "", "barcelona"), "barcelona")
        self.assertEqual(m("Ajuntament d'Alella", "", "barcelona"), "alella")
        self.assertEqual(m("Ajuntament de l'Hospitalet de Llobregat", "", "barcelona"),
                         self.app.clave_municipio("L'Hospitalet de Llobregat", "barcelona"))
        self.assertEqual(m("Ajuntament del Vendrell", "", "tarragona"),
                         self.app.clave_municipio("El Vendrell", "tarragona"))
        self.assertEqual(m("Ajuntament de Barcelona", "", "", "cataluna"), "barcelona")     # solo comunidad
        self.assertEqual(m("Ayuntamiento de Bilbao-Alcalde", "", "pais_vasco"), "bilbao")
        self.assertEqual(m("Concello de Dozón", "", "pontevedra"), "dozon")
        self.assertEqual(m("Concello do Porriño", "", "pontevedra"), self.app.clave_municipio("O Porriño", "pontevedra"))
        self.assertTrue(m("Ayuntamiento de Murcia", "30001", "murcia"))                  # el 643, igual que antes
        self.assertEqual(m("Departament de Salut", "", "barcelona"), "")
        # «Udala»: la palabra se reconoce, pero un nombre en euskera declinado («Bilboko») no se adivina
        self.assertEqual(m("Bilboko Udala", "", "pais_vasco"), "")

    def test_purga(self):
        app = self.app
        app._licitaciones_ingerir_atom(atom(entrada("https://x/643/001", "Ajuntament de Vic", "E1", agente="",
                                                    fin="2026-01-01")))
        app._licitaciones_ingerir_atom(atom(entrada("https://x/1044/001", "Ajuntament de Vic", "E1",
                                                    fin="2026-01-01")), "1044")
        app._licitaciones_ingerir_atom(atom(entrada("https://x/643/002", "Ajuntament de Vic", "E2", agente="")))
        app._licitaciones_ingerir_atom(atom(entrada("https://x/1044/002", "Ajuntament de Vic", "E2")), "1044")
        app._licitaciones_purgar()
        f = self.filas()
        self.assertNotIn("https://x/1044/001", f)                # repetida y vencida hace más de 2 meses: fuera
        self.assertEqual(f["https://x/1044/002"][0], "DUP")       # repetida y abierta: se queda marcada

    def test_interruptor_y_texto(self):
        app = self.app
        llamadas = []
        originales = (app._licitaciones_desde_zips, app._licitaciones_desde_atom, app._licitaciones_agregadas_zips)
        app._licitaciones_desde_zips = lambda *a, **k: 0
        app._licitaciones_desde_atom = lambda *a, **k: llamadas.append(a) or True
        app._licitaciones_agregadas_zips = lambda: llamadas.append("zip1044") or 0
        try:
            app.LIC_AGREGADAS = False
            app._licitaciones_ciclo()
            self.assertEqual(llamadas, [()])                     # solo el Atom del 643
            llamadas.clear()
            app.LIC_AGREGADAS = True
            app._licitaciones_ciclo()
            self.assertIn("zip1044", llamadas)
            self.assertIn((app.PLACE_AGREGADAS_FEED_LIVE, "1044"), llamadas)
        finally:
            app._licitaciones_desde_zips, app._licitaciones_desde_atom, app._licitaciones_agregadas_zips = originales
            app.LIC_AGREGADAS = True
        h = app.render_convocatorias_html({})
        self.assertIn("plataformas autonómicas que agrega", h)


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--con-app"]
    unittest.main(argv=argv, verbosity=2)
