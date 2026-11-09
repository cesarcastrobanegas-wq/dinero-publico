# encoding: utf-8
"""Prueba SIN RED de los arreglos del flujo semanal de contratos menores (09-11-2026).

  - Una fuente en la que fallan TODAS las descargas (el generador avisa «error de descarga» y no escribe su fichero)
    cuenta como PROBLEMA («fallan las descargas»), no como «sin cambios», y el resumen dice desde qué fecha está sin
    actualizar (la «generado» del fichero que se conserva).
  - Si solo falla alguna descarga y el generador escribe, se decide como siempre (actualizada / menos contratos).
  - Un fallo normal del generador también dice desde cuándo está sin actualizar.
  - Alicante y Santa Cruz de Tenerife quedan fuera del flujo (manuales, con menores_desde_pc.py).
  - Fuenlabrada: del listado de la API del portal nuevo se cogen solo los informes trimestrales del Ayuntamiento y
    OO.AA dentro de la ventana, y del mismo trimestre el más reciente.

Monta un repositorio git de juguete en una carpeta temporal con generadores inventados; no descarga nada.

    python backend/flujo_menores_semanal_prueba.py
"""
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import flujo_menores_semanal as fm  # noqa: E402


def contratos(n, fecha="2025-05-01"):
    return [{"id": f"c{i}", "data_adjudicacio": fecha, "importe": i} for i in range(n)]


def fichero(registros, generado):
    return gzip.compress(json.dumps({"generado": generado, "registros": registros}).encode("utf-8"))


# Generadores inventados: cada uno imprime lo que diría el de verdad y escribe (o no) su fichero.
GENERADORES = {
    # todas las descargas fallan y no escribe nada (Alicante y Fuenlabrada, 08-11-2026)
    "todasfallan": '''
print("Descargando 2025T1...")
print("  !! 2025T1: error de descarga (URLError: <urlopen error timed out>)")
print("Descargando 2025T2...")
print("  !! 2025T2: error de descarga (HTTPError: HTTP Error 404: Not Found)")
print("Hecho: 0 registros.")
''',
    # falla una de dos descargas, pero la otra trae todo y escribe (con un contrato nuevo)
    "unafalla": '''
import gzip, json
regs = [{"id": f"c{i}", "data_adjudicacio": "2025-05-01", "importe": i} for i in range(31)]
print("  !! 2025T1: error de descarga (URLError: timed out)")
with gzip.open("contratos_menores_unafalla.json.gz", "wt", encoding="utf-8") as f:
    json.dump({"generado": "2026-11-09", "registros": regs}, f)
''',
    # el generador revienta
    "revienta": '''
raise SystemExit(1)
''',
    # todo bien y nada nuevo: sigue siendo «sin cambios»
    "igual": '''
import gzip, json
regs = [{"id": f"c{i}", "data_adjudicacio": "2025-05-01", "importe": i} for i in range(30)]
with gzip.open("contratos_menores_igual.json.gz", "wt", encoding="utf-8") as f:
    json.dump({"generado": "2026-11-09", "registros": regs}, f)
''',
}


class Flujo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="flujo_menores_")
        back = os.path.join(cls.tmp, "backend")
        os.makedirs(back)
        for f in ("flujo_menores_semanal.py", "alcance.py"):
            shutil.copy(os.path.join(BASE_DIR, f), back)
        for nombre, codigo in GENERADORES.items():
            with open(os.path.join(back, f"actualizar_contratos_menores_{nombre}.py"), "w", encoding="utf-8") as fh:
                fh.write(codigo)
            with open(os.path.join(back, f"contratos_menores_{nombre}.json.gz"), "wb") as fh:
                fh.write(fichero(contratos(30), "2026-10-25"))
        git = ["git", "-C", cls.tmp, "-c", "user.name=prueba", "-c", "user.email=prueba@ejemplo.test"]
        subprocess.run(git[:3] + ["init", "-q"], check=True)
        subprocess.run(git + ["add", "-A"], check=True)
        subprocess.run(git + ["commit", "-q", "-m", "inicial"], check=True)
        salida = os.path.join(cls.tmp, "salida.txt")
        resumen = os.path.join(cls.tmp, "resumen.md")
        env = dict(os.environ, GITHUB_OUTPUT=salida, GITHUB_STEP_SUMMARY=resumen, PYTHONIOENCODING="utf-8")
        p = subprocess.run([sys.executable, os.path.join(back, "flujo_menores_semanal.py"), "--solo",
                            ",".join(GENERADORES)], cwd=cls.tmp, env=env, capture_output=True, text=True,
                           encoding="utf-8")
        cls.registro = p.stdout + p.stderr
        assert p.returncode == 0, cls.registro
        cls.salida = dict(l.split("=", 1) for l in open(salida, encoding="utf-8").read().splitlines() if "=" in l)
        cls.resumen = open(resumen, encoding="utf-8").read()
        cls.filas = {l.split("|")[1].strip(): [c.strip() for c in l.split("|")[2:4]]
                     for l in cls.resumen.splitlines() if l.startswith("| ") and not l.startswith("| Fuente")}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_todas_las_descargas_fallan_es_problema(self):
        estado, detalle = self.filas["todasfallan"]
        self.assertEqual(estado, "fallan las descargas", self.resumen)
        self.assertIn("fallaron las 2 descargas", detalle)
        self.assertIn("sin actualizar desde el 2026-10-25", detalle)

    def test_una_descarga_fallida_no_basta(self):
        self.assertEqual(self.filas["unafalla"][0], "actualizada", self.resumen)

    def test_fallo_dice_desde_cuando(self):
        estado, detalle = self.filas["revienta"]
        self.assertEqual(estado, "fallo")
        self.assertIn("sin actualizar desde el 2026-10-25", detalle)

    def test_sin_cambios_sigue_siendo_sin_cambios(self):
        self.assertEqual(self.filas["igual"][0], "sin cambios", self.resumen)

    def test_salidas_para_el_flujo(self):
        self.assertEqual(self.salida["problemas"], "2")
        self.assertEqual(sorted(self.salida["fuentes_problema"].split(", ")), ["revienta", "todasfallan"])
        self.assertEqual(self.salida["cambios"], "1")
        self.assertIn("2 con problemas", self.resumen)

    def test_el_fichero_anterior_se_conserva(self):
        crudo = open(os.path.join(self.tmp, "backend", "contratos_menores_todasfallan.json.gz"), "rb").read()
        self.assertEqual(len(fm.registros_de(crudo)), 30)
        self.assertEqual(fm.generado_de(crudo), "2026-10-25")


class Decidir(unittest.TestCase):
    def test_reglas(self):
        antes = contratos(30)
        nuevo = fichero(antes, "2026-11-09")
        self.assertEqual(fm.decidir(30, antes, 0, nuevo, errores_descarga=3, escribio=False)[0],
                         "fallan las descargas")
        self.assertEqual(fm.decidir(30, antes, 0, nuevo, errores_descarga=0, escribio=False)[0], "sin cambios")
        self.assertEqual(fm.decidir(30, antes, 0, nuevo, errores_descarga=1, escribio=True)[0], "sin cambios")
        self.assertEqual(fm.decidir(30, antes, 1, nuevo, errores_descarga=3, escribio=False)[0], "fallo")
        self.assertEqual(fm.errores_de_descarga("a\n  !! 2024: error de descarga (x)\n!! otro aviso\n"), 1)

    def test_manuales(self):
        for f in ("alicante", "santa_cruz"):
            self.assertIn(f, fm.EXCLUIDOS)
            self.assertIn("menores_desde_pc.py", fm.EXCLUIDOS[f])
        self.assertTrue(os.path.exists(os.path.join(BASE_DIR, "menores_desde_pc.py")))
        self.assertTrue(os.path.exists(os.path.join(os.path.dirname(BASE_DIR), "MENORES_DESDE_PC.md")))


class Fuenlabrada(unittest.TestCase):
    def test_lista_del_portal(self):
        import actualizar_contratos_menores_fuenlabrada as fu
        fu.MENORES_DESDE_FECHA = "2021-11-01"
        ayto = "Ayuntamiento y Organismos Autónomos"

        def reg(titulo, imagen, cat=ayto, actualizado="26/06/2026"):
            return {"updated_at": actualizado, "data": {"builderInputComponent1": {"es": titulo},
                    "builderInputComponent2": {"es": cat}, "documentUploadComponent1": {"image": imagen}}}
        lista = [
            reg("3er Trimestre 2026", "/download/3T-2026.xls"),
            reg("2º Trimestre 2026", "/download/2T-2026-viejo.xls", actualizado="01/07/2026"),
            reg("2º Trimestre 2026", "/download/2T-2026-nuevo.xls", actualizado="15/07/2026"),
            reg("4º Trimestre 2021", "/download/4T-2021.xls_746..xls"),
            reg("3er Trimestre del 2021", "/download/3T-2021.xls"),                 # antes de la ventana
            reg("Contratos Menores FUMECO 1er Trimestre 2026", "/download/f.xlsx", cat="Sociedades Mercantiles"),
            reg("Información complementaria financiación UE-Next Generation 2021-2025", "/download/ng.xlsx"),
            reg("1er Trimestre 2019 – PMD", "/download/pmd.ods"),
        ]
        fx = fu.ficheros_del_portal(lista)
        base = "https://transparencia.ayto-fuenlabrada.es/download/"
        self.assertEqual(fx, {(2021, 4): base + "4T-2021.xls_746..xls", (2026, 2): base + "2T-2026-nuevo.xls",
                              (2026, 3): base + "3T-2026.xls"})
        self.assertFalse(hasattr(fu, "FICHEROS"))       # ya no hay direcciones fijas del portal viejo


if __name__ == "__main__":
    unittest.main(verbosity=2)
