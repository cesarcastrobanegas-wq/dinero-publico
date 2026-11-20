# encoding: utf-8
"""
Borra de una COPIA de cache.db lo caducado de la PAC (publicación del FEGA + 2 años, art. 98.4 del Reglamento (UE)
2021/2116), igual que hace la web con su propia base (_pac_purgar en app.py), y compacta el fichero para que no queden
restos de las filas borradas en las páginas libres de SQLite.

Para qué: la web borra lo caducado de su base, pero las copias (la semanal del repositorio privado y las que se bajan a
mano a un ordenador) se quedarían con ello. El flujo backup-cache-db-semanal.yml lo pasa a cada copia antes de
comprimirla; las copias locales hay que pasarlas a mano:

    python backend/pac_purgar_copia.py ruta/a/la/copia.db [--hoy AAAA-MM-DD]

Solo imprime recuentos (nunca el contenido). Sin tablas de la PAC, no hace nada. Código de salida 0 si todo va bien.
"""
import argparse
import datetime as dt
import os
import sqlite3
import sys

TABLAS = ("pac_meta", "pac_provincia", "pac_municipio", "pac_pj")


def hoy_madrid():
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("Europe/Madrid")).strftime("%Y-%m-%d")
    except Exception:
        return dt.date.today().isoformat()


def purgar(ruta, hoy=None, compactar=True):
    """Devuelve {tabla: filas borradas}. Borra con secure_delete (sobrescribe con ceros) y, si se ha borrado algo,
    hace VACUUM para que el fichero no guarde páginas libres con restos."""
    hoy = hoy or hoy_madrid()
    con = sqlite3.connect(ruta)
    try:
        existentes = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        tablas = [t for t in TABLAS if t in existentes]
        if not tablas:
            return {}
        con.execute("PRAGMA secure_delete=ON")
        borradas = {}
        for t in tablas:
            n = con.execute(f"DELETE FROM {t} WHERE caduca <= ?", (hoy,)).rowcount
            if n:
                borradas[t] = n
        con.commit()
        if borradas and compactar:
            con.execute("VACUUM")
        return borradas
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n\n")[0])
    ap.add_argument("ruta")
    ap.add_argument("--hoy", help="AAAA-MM-DD (por defecto, hoy en Madrid)")
    a = ap.parse_args()
    if not os.path.exists(a.ruta):
        sys.exit(f"No existe {a.ruta}")
    hoy = a.hoy or hoy_madrid()
    borradas = purgar(a.ruta, hoy)
    if borradas:
        print(f"PAC: borrado lo caducado a {hoy}: {borradas}")
    else:
        print(f"PAC: nada caducado a {hoy}")


if __name__ == "__main__":
    main()
