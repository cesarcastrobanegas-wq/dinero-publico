# encoding: utf-8
"""Prueba del fallo del refresco de población en «Actualizar contratos diariamente» (13-11-2026).

Del 06-11 al 12-11 el paso «Refrescar población oficial» fallaba todas las noches al importar app.py:
    sqlite3.OperationalError: no such table: contratos_menors_archivo
(_cargar_contratos_menores_murcia_manual -> _guardar_contratos_menors_locales -> _retirar_duplicados_place ->
_retirar_feed_antes_de_propia). Esa tabla solo la creaba _archivar_filas_cm la primera vez que archivaba algo. Con una
cache.db que ya tenía contratos menores del feed y de una fuente propia (Torre Pacheco, Cartagena...) pero en la que
todavía no se había archivado nada, la consulta del archivo rompía el arranque entero. El 13-11 pasó porque la
cache.db restaurada ya traía la tabla: el fallo dependía de la base, no del código del día.

Reproduce esa base (filas del feed y de Torre Pacheco, sin la tabla del archivo) y comprueba que la regla funciona.
    python backend/prueba_flujo_nocturno_tablas.py      (proceso pesado: importa la web; ~3 min, de uno en uno)
"""
import os
import sys
import tempfile
import time
import unittest

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)


class TablaArchivoDeMenores(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        os.environ.update(DATA_DIR=cls.tmp.name, HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9")
        import app
        cls.app = app

    def _base_de_la_noche_del_12(self):
        """Filas del feed de PLACE y de la fuente propia de Torre Pacheco, y SIN contratos_menors_archivo."""
        app = self.app
        cols = ("id", "municipio", "provincia", "fuente", "organisme", "adjudicatari", "nif", "import_num",
                "data_adjudicacio", "tipus_contracte", "descripcio", "codi_cpv", "exercici", "ts")
        filas = [
            ("place-menores::prueba1", "Torre Pacheco", "murcia", app.FUENTE_CM_PLACE, "Ayuntamiento", "EMPRESA X SL",
             "B00000000", 1000.0, "2026-10-20", "Servicios", "Prueba", "", "2026", time.time()),
            ("torre-pacheco::prueba1", "Torre Pacheco", "murcia", "torre-pacheco", "Ayuntamiento", "EMPRESA X SL",
             "B00000000", 1000.0, "2026-10-01", "Servicios", "Prueba", "", "2026", time.time()),
        ]
        with app._db_lock:
            app._db.execute("DROP TABLE IF EXISTS contratos_menors_archivo")
            app._db.executemany(f"INSERT OR REPLACE INTO contratos_menors_locales ({', '.join(cols)}) VALUES "
                                f"({', '.join('?' * len(cols))})", filas)
            app._db.commit()
        app._EQUIV_PLACE_CACHE = None

    def _hay_tabla(self):
        with self.app._db_lock:
            return self.app._db.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND "
                                        "name='contratos_menors_archivo'").fetchone()[0] == 1

    def test_regla_del_feed_sin_tabla_de_archivo(self):
        self._base_de_la_noche_del_12()
        self.app._retirar_feed_antes_de_propia({"torre-pacheco"})     # antes: OperationalError: no such table
        self.assertTrue(self._hay_tabla())

    def test_retirar_duplicados_sin_tabla_de_archivo(self):
        # el camino del traceback del 12-11 (lo que hace la carga de una fuente propia al importar la app)
        self._base_de_la_noche_del_12()
        self.app._retirar_duplicados_place([{
            "id": "torre-pacheco::prueba1", "municipio": "Torre Pacheco", "provincia": "murcia",
            "fuente": "torre-pacheco", "adjudicatari": "EMPRESA X SL", "nif": "B00000000", "import_num": 1000.0,
            "data_adjudicacio": "2026-10-01", "exercici": "2026", "descripcio": "Prueba"}])
        self.assertTrue(self._hay_tabla())

    def test_la_base_nueva_trae_la_tabla(self):
        # la tabla se crea al abrir la base, no la primera vez que se archiva algo
        self.assertTrue(self._hay_tabla())


if __name__ == "__main__":
    unittest.main(verbosity=2)
