# encoding: utf-8
"""
Descifra una copia semanal de cache.db (cache_AAAA-MM-DD_HHMM.db.gz.gpg, de la release «copia-semanal» del
repositorio privado dinero-publico-copias) y comprueba que la base está sana.

    python backend/descifrar_copia_cache.py cache_2026-11-09_0500.db.gz.gpg
    python backend/descifrar_copia_cache.py COPIA.db.gz.gpg --salida C:/ruta/cache.db

Pide la clave (ALERTAS_COPIA_CLAVE, la misma de las copias de alertas.db y socios.db) sin mostrarla. Para las
pruebas automáticas se puede pasar en la variable de entorno COPIA_CLAVE; a mano, mejor que la pida.

Qué hace, en este orden:
  1. Si junto a la copia está su .sha256 (se descarga de la misma release), comprueba la huella.
  2. Descifra con gpg (el de Git para Windows sirve) y descomprime por tubería: el .gz descifrado no se escribe.
  3. Escribe en un fichero temporal al lado del destino y pasa PRAGMA integrity_check. Solo si da «ok» lo renombra
     al nombre final; si no, lo borra. Nunca sobrescribe un fichero que ya exista salvo con --forzar.

No imprime nada del contenido de la base: solo tamaños, el resultado de integrity_check y el número de fichas.
Hazlo en un ordenador de confianza: la base descifrada lleva los DNI/NIE de los autónomos.
"""
import argparse
import getpass
import gzip
import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import threading

GPG_GIT_WINDOWS = r"C:\Program Files\Git\usr\bin\gpg.exe"


def buscar_gpg():
    ruta = shutil.which("gpg")
    if ruta:
        return ruta
    if os.path.exists(GPG_GIT_WINDOWS):
        return GPG_GIT_WINDOWS
    sys.exit("No encuentro gpg. Instala Git para Windows (trae gpg) o GnuPG.")


def comprobar_sha256(copia):
    fichero = copia + ".sha256"
    if not os.path.exists(fichero):
        print("Aviso: no está " + os.path.basename(fichero) + " al lado de la copia; no compruebo la huella.")
        return
    with open(fichero, encoding="utf-8") as f:
        esperada = f.read().split()[0].lower()
    h = hashlib.sha256()
    with open(copia, "rb") as f:
        for trozo in iter(lambda: f.read(1 << 20), b""):
            h.update(trozo)
    if h.hexdigest() != esperada:
        sys.exit("La huella SHA-256 no coincide con " + os.path.basename(fichero) + ": la copia está dañada o no es esa.")
    print("SHA-256: ok")


def descifrar(copia, destino, clave, gpg=None):
    """Descifra y descomprime `copia` en `destino`. Devuelve el resultado de integrity_check ("ok" si está sana).
    Lanza RuntimeError si gpg o gzip fallan; en ese caso no queda ningún fichero a medias."""
    gpg = gpg or buscar_gpg()
    temporal = destino + ".descifrando"
    if os.path.exists(temporal):
        os.remove(temporal)
    # La clave va por la entrada estándar (--passphrase-fd 0) y el fichero cifrado por nombre, relativo a su carpeta
    # (cwd), para no depender de cómo traduce las rutas de Windows el gpg de Git.
    carpeta, nombre = os.path.split(os.path.abspath(copia))
    orden = [gpg, "--batch", "--quiet", "--no-symkey-cache", "--pinentry-mode", "loopback",
             "--passphrase-fd", "0", "--decrypt", nombre]
    proc = subprocess.Popen(orden, cwd=carpeta, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    errores = []
    lector_err = threading.Thread(target=lambda: errores.append(proc.stderr.read()), daemon=True)
    lector_err.start()
    proc.stdin.write(clave.encode("utf-8"))
    proc.stdin.close()
    fallo = None
    try:
        with gzip.GzipFile(fileobj=proc.stdout, mode="rb") as dentro, open(temporal, "wb") as fuera:
            shutil.copyfileobj(dentro, fuera, 1 << 20)
    except (OSError, EOFError, gzip.BadGzipFile) as e:
        fallo = e
    finally:
        proc.stdout.close()
        codigo = proc.wait()
        lector_err.join(5)
    if codigo != 0 or fallo is not None:
        if os.path.exists(temporal):
            os.remove(temporal)
        if codigo != 0:
            msg = (b"".join(errores)).decode("utf-8", "replace").strip()
            raise RuntimeError("gpg no pudo descifrar la copia (¿clave equivocada?): " + (msg or "código %d" % codigo))
        raise RuntimeError("Lo descifrado no es un gzip válido: " + str(fallo))
    con = sqlite3.connect(temporal)
    try:
        resultado = con.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        con.close()
    if resultado != "ok":
        os.remove(temporal)
        return resultado
    os.replace(temporal, destino)
    return resultado


def main():
    ap = argparse.ArgumentParser(description="Descifra una copia semanal cifrada de cache.db.")
    ap.add_argument("copia", help="fichero cache_AAAA-MM-DD_HHMM.db.gz.gpg")
    ap.add_argument("--salida", help="dónde dejar la base (por defecto cache.db en la carpeta de la copia)")
    ap.add_argument("--forzar", action="store_true", help="sobrescribir --salida si ya existe")
    a = ap.parse_args()
    if not os.path.isfile(a.copia):
        sys.exit("No existe " + a.copia)
    destino = os.path.abspath(a.salida or os.path.join(os.path.dirname(os.path.abspath(a.copia)), "cache.db"))
    if os.path.exists(destino) and not a.forzar:
        sys.exit("Ya existe " + destino + ": no lo sobrescribo (usa --salida con otro nombre, o --forzar).")
    comprobar_sha256(a.copia)
    clave = os.environ.get("COPIA_CLAVE") or getpass.getpass("Clave de las copias (ALERTAS_COPIA_CLAVE): ")
    if not clave:
        sys.exit("Sin clave no se puede descifrar.")
    try:
        resultado = descifrar(a.copia, destino, clave)
    except RuntimeError as e:
        sys.exit(str(e))
    if resultado != "ok":
        sys.exit("La base descifrada NO pasa integrity_check (" + resultado + "): no se ha dejado ningún fichero.")
    con = sqlite3.connect(destino)
    try:
        try:
            fichas = con.execute("SELECT COUNT(*) FROM municipios").fetchone()[0]
        except sqlite3.Error:
            fichas = "?"
    finally:
        con.close()
    print("integrity_check: ok -- %s fichas, %d bytes en %s" % (fichas, os.path.getsize(destino), destino))


if __name__ == "__main__":
    main()
