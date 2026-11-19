# encoding: utf-8
"""
Baja una copia ACTUAL de la base de producción para el material de venta (HERRAMIENTA LOCAL, 2026-11-05).

Usa la misma descarga de SOLO LECTURA que ya usan los flujos semanales de GitHub Actions: GET /admin/cache-db con la
cabecera X-Admin-Token. El servidor hace una copia consistente (sqlite3.backup, sin tocar la base viva) y la sirve
por trozos; si la conexión se corta, se reanuda (Range) sobre la MISMA copia. Al acabar se comprueba la huella
(sha256 que manda el servidor) y que la base se abre y tiene contratos de la Región de Murcia. Solo entonces:
  - la copia anterior pasa a llamarse cache_produccion_AAAA-MM-DD.db (no se borra; bórrala tú cuando quieras);
  - la nueva queda como <base>/cache_produccion.db.
El token NO se guarda en ningún sitio. Si no se pasa --token, se pide por teclado sin mostrarlo.

Uso: python backend/bajar_copia_base.py --base CARPETA [--token TOKEN] [--regenerar] [--contacto-tel "TELÉFONO"]
"""
import argparse
import getpass
import hashlib
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import date

URL = "https://dinero-publico.com/admin/cache-db"


def _sha256(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for trozo in iter(lambda: f.read(1 << 20), b""):
            h.update(trozo)
    return h.hexdigest()


def bajar(token, destino, intentos=30):
    """Descarga reanudable a `destino`. Devuelve la huella sha256 que dio el servidor."""
    parte = destino + ".part"
    huella_parte = parte + ".sha256"
    sha = open(huella_parte).read().strip() if os.path.exists(parte) and os.path.exists(huella_parte) else ""
    if not sha and os.path.exists(parte):
        os.remove(parte)
    t0, ultimo_aviso = time.time(), 0
    for i in range(1, intentos + 1):
        ya = os.path.getsize(parte) if os.path.exists(parte) else 0
        cab = {"X-Admin-Token": token, "User-Agent": "dinero-publico-copia-local"}
        if ya:
            cab["Range"] = f"bytes={ya}-"
        try:
            req = urllib.request.Request(URL, headers=cab)
            with urllib.request.urlopen(req, timeout=600) as r:
                sha_srv = r.headers.get("X-Cache-Db-Sha256", "")
                if ya and (r.status != 206 or sha_srv != sha):
                    print("  La copia del servidor ha cambiado: empiezo de cero.", flush=True)
                    os.remove(parte)
                    sha = ""
                    continue
                total = ya + int(r.headers.get("Content-Length") or 0)
                if not ya:
                    sha = sha_srv
                    with open(huella_parte, "w") as f:
                        f.write(sha)
                with open(parte, "ab") as f:
                    while True:
                        trozo = r.read(1 << 20)
                        if not trozo:
                            break
                        f.write(trozo)
                        if time.time() - ultimo_aviso > 30:
                            ultimo_aviso = time.time()
                            hecho = os.path.getsize(parte)
                            print(f"  {hecho / 1e6:,.0f} de {total / 1e6:,.0f} MB "
                                  f"({(time.time() - t0) / 60:.1f} min)", flush=True)
            if os.path.getsize(parte) >= total:
                break
        except urllib.error.HTTPError as ex:
            if ex.code == 403:
                raise SystemExit("El servidor dice 403: el token no es el correcto. No he cambiado nada.")
            if ex.code == 416 and ya:
                os.remove(parte)
                sha = ""
            print(f"  intento {i}: HTTP {ex.code}; reintento en {min(60, 5 * i)} s", flush=True)
            time.sleep(min(60, 5 * i))
        except OSError as ex:
            print(f"  intento {i}: {ex}; reanudo en {min(60, 5 * i)} s", flush=True)
            time.sleep(min(60, 5 * i))
    else:
        raise SystemExit(f"No se pudo completar la descarga. Lo bajado queda en {parte}: vuelve a lanzar la orden y "
                         "seguirá donde se quedó (si han pasado menos de 2 horas).")
    print("  Comprobando la huella...", flush=True)
    if not sha or _sha256(parte) != sha:
        os.remove(parte)
        raise SystemExit("La huella no coincide (la copia llegó mal). La he borrado: vuelve a lanzar la orden.")
    return parte, sha


def comprobar(ruta):
    c = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    try:
        n = c.execute("SELECT COUNT(*) FROM municipios WHERE provincia='murcia'").fetchone()[0]
        m = c.execute("SELECT COUNT(*) FROM contratos_menors_locales WHERE provincia='murcia'").fetchone()[0]
    finally:
        c.close()
    if not n or not m:
        raise SystemExit("La copia no tiene datos de la Región de Murcia. No la uso.")
    return n, m


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", required=True)
    ap.add_argument("--token", help="token de administración (si no, se pide sin mostrarlo)")
    ap.add_argument("--regenerar", action="store_true", help="al acabar, regenerar todo el material con la copia nueva")
    ap.add_argument("--contacto-tel", default="")
    a = ap.parse_args(argv)
    token = (a.token or "").strip() or getpass.getpass("Token de administración (no se ve al escribir): ").strip()
    if not token or token == "TU_TOKEN_AQUI":
        raise SystemExit("Falta el token: cambia TU_TOKEN_AQUI por el tuyo.")
    final = os.path.join(a.base, "cache_produccion.db")
    nueva = os.path.join(a.base, "cache_produccion_nueva.db")
    t = time.time()
    print("Bajando la copia de la base de producción (solo lectura; ~1,2 GB, unos 10-20 min)...", flush=True)
    parte, sha = bajar(token, nueva)
    os.replace(parte, nueva)
    os.remove(parte + ".sha256")
    n, m = comprobar(nueva)
    if os.path.exists(final):
        vieja = os.path.join(a.base, f"cache_produccion_{date.fromtimestamp(os.path.getmtime(final)).isoformat()}.db")
        if not os.path.exists(vieja):
            os.replace(final, vieja)
            print(f"  La copia anterior queda como {os.path.basename(vieja)} (bórrala cuando quieras).", flush=True)
        else:
            os.remove(final)
    os.replace(nueva, final)
    print(f"Copia nueva en {final}: {os.path.getsize(final) / 1e9:.2f} GB, huella {sha[:12]}…, {n} municipios y "
          f"{m:,} contratos menores de la Región. {(time.time() - t) / 60:.1f} min.", flush=True)
    if a.regenerar:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import regenerar_venta
        regenerar_venta.main(["--base", a.base] + (["--contacto-tel", a.contacto_tel] if a.contacto_tel else []))


if __name__ == "__main__":
    main()
