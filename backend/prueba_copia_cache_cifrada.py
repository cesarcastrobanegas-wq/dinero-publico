# encoding: utf-8
"""
Prueba de la copia semanal CIFRADA de cache.db, con una base INVENTADA (no toca la base local ni la web ni GitHub):

    python backend/prueba_copia_cache_cifrada.py

  1. Saca del flujo .github/workflows/backup-cache-db-semanal.yml los pasos «¿Están el token...?» y «Comprimir y
     cifrar» y los ejecuta TAL CUAL con bash (el de Git para Windows sirve: trae gpg, gzip y shred), con una clave de
     prueba y un cache.db inventado. Así se prueba el código real del flujo, no una imitación.
  2. Descifra el resultado con backend/descifrar_copia_cache.py y pasa integrity_check; compara las filas.
  3. Casos que deben fallar: clave equivocada, copia dañada, sobrescribir un fichero, flujo sin clave.

Usa un GNUPGHOME temporal para no tocar el llavero del usuario. Necesita PyYAML (ya está en el PC del titular).
"""
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(BASE_DIR)
FLUJO = os.path.join(RAIZ, ".github", "workflows", "backup-cache-db-semanal.yml")
sys.path.insert(0, BASE_DIR)
import descifrar_copia_cache as D   # noqa: E402

import yaml   # noqa: E402

CLAVE = "clave-solo-para-esta-prueba-1234567890"
fallos = []


def ok(cond, txt):
    print(("OK   " if cond else "FALLO") + " " + txt)
    if not cond:
        fallos.append(txt)


def buscar_bash():
    for ruta in (r"C:\Program Files\Git\bin\bash.exe", shutil.which("bash")):
        if ruta and os.path.exists(ruta) and "system32" not in ruta.lower():   # no el bash de WSL
            return ruta
    sys.exit("No encuentro el bash de Git para Windows.")


def pasos_del_flujo():
    with open(FLUJO, encoding="utf-8") as f:
        flujo = yaml.safe_load(f)
    pasos = {p["name"]: p for p in flujo["jobs"]["copia-cache-db"]["steps"]}
    comprobar = next(p for n, p in pasos.items() if n.startswith("¿Están el token"))
    cifrar = pasos["Comprimir y cifrar"]
    subir = next(p for n, p in pasos.items() if n.startswith("Subir al repositorio privado"))
    return flujo, comprobar, cifrar, subir


def ejecutar(bash, script, carpeta, entorno):
    env = dict(os.environ)
    env.update(entorno)
    # como en Actions: bash --noprofile --norc -eo pipefail
    return subprocess.run([bash, "--noprofile", "--norc", "-eo", "pipefail", "-c", script], cwd=carpeta, env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def base_inventada(ruta):
    con = sqlite3.connect(ruta)
    con.execute("CREATE TABLE municipios (clave TEXT PRIMARY KEY, nombre TEXT, datos TEXT)")
    filas = [("villaprueba%04d|valencia" % i, "Villaprueba %d" % i, "x" * 500 + str(i)) for i in range(3000)]
    con.executemany("INSERT INTO municipios VALUES (?, ?, ?)", filas)
    con.execute("CREATE TABLE autonomos (nif TEXT, nombre TEXT)")
    con.executemany("INSERT INTO autonomos VALUES (?, ?)", [("00000000T", "PERSONA INVENTADA UNO"),
                                                             ("99999999R", "PERSONA INVENTADA DOS")])
    con.commit()
    con.close()
    return len(filas)


# gh falso: la release es un fichero con un nombre de adjunto por línea; las órdenes que borran solo lo apuntan.
GH_FALSO = """#!/bin/bash
activos="$GH_FALSO_ACTIVOS"
case "$1 $2" in
  "release view")
    if [[ " $* " == *" --json "* ]]; then cat "$activos"; fi ;;
  "release upload")
    shift 3
    while [ $# -gt 0 ]; do
      case "$1" in --repo) shift ;; --*) ;; *) grep -qxF "$1" "$activos" || echo "$1" >> "$activos" ;; esac
      shift
    done ;;
  "release delete-asset")
    grep -vxF "$4" "$activos" > "$activos.n" || true; mv "$activos.n" "$activos"; echo "$4" >> "$GH_FALSO_BORRADOS" ;;
  "release create") ;;
  *) echo "gh falso: orden inesperada $*" >&2; exit 9 ;;
esac
"""


def probar_subida(bash, script, tmp):
    carpeta = os.path.join(tmp, "subida")
    binario = os.path.join(carpeta, "bin")
    os.makedirs(binario)
    with open(os.path.join(binario, "gh"), "w", newline="\n") as f:
        f.write(GH_FALSO)
    nuevo = "cache_2026-11-09_0500.db.gz.gpg"
    viejas = ["cache_2026-10-26_0500.db.gz", "cache_2026-11-02_0500.db.gz"]

    def con_sha(nombres):
        return [x for n in nombres for x in (n, n + ".sha256")]

    casos = [
        # (descripción, adjuntos que ya hay, conservar_todas, adjuntos que deben quedar)
        ("primera copia cifrada: se conservan las dos viejas sin cifrar",
         con_sha(viejas), "false", con_sha(viejas + [nuevo])),
        ("segunda cifrada: se borran las dos sin cifrar",
         con_sha(viejas + ["cache_2026-11-03_1200.db.gz.gpg"]), "false",
         con_sha(["cache_2026-11-03_1200.db.gz.gpg", nuevo])),
        ("tercera cifrada: se borra la cifrada más antigua",
         con_sha(["cache_2026-10-26_0500.db.gz.gpg", "cache_2026-11-02_0500.db.gz.gpg"]), "false",
         con_sha(["cache_2026-11-02_0500.db.gz.gpg", nuevo])),
        ("conservar_todas: no se borra nada",
         con_sha(viejas + ["cache_2026-11-02_0500.db.gz.gpg"]), "true",
         con_sha(viejas + ["cache_2026-11-02_0500.db.gz.gpg", nuevo])),
    ]
    for desc, hay, conservar, quedan in casos:
        activos = os.path.join(carpeta, "activos.txt")
        borrados = os.path.join(carpeta, "borrados.txt")
        with open(activos, "w", newline="\n") as f:
            f.write("".join(n + "\n" for n in hay))
        open(borrados, "w").close()
        for n in (nuevo, nuevo + ".sha256"):
            open(os.path.join(carpeta, n), "w").close()
        bin_posix = "/" + binario[0].lower() + binario[2:].replace("\\", "/")
        r = ejecutar(bash, 'export PATH="%s:$PATH"\n' % bin_posix
                     + script.replace("${{ inputs.conservar_todas }}", conservar), carpeta,
                     {"GH_FALSO_ACTIVOS": activos.replace("\\", "/"), "GH_FALSO_BORRADOS": borrados.replace("\\", "/"),
                      "ETIQUETA": "copia-semanal", "DESTINO": "prueba/dinero-publico-copias", "nombre": nuevo,
                      "GH_TOKEN": "token-falso"})
        final = [line for line in open(activos).read().splitlines() if line]
        ok(r.returncode == 0 and sorted(final) == sorted(quedan), "subida, " + desc)
        if r.returncode != 0 or sorted(final) != sorted(quedan):
            print("   quedan:", sorted(final), "\n   salida:", r.stdout[-1500:], r.stderr[-1500:])
        ok(not os.path.exists(os.path.join(carpeta, nuevo)), "subida, borra la copia local tras subirla")


def main():
    bash = buscar_bash()
    gpg = D.buscar_gpg()
    flujo, comprobar, cifrar, subir = pasos_del_flujo()
    tmp = tempfile.mkdtemp(prefix="prueba_copia_cache_")
    try:
        gnupg = os.path.join(tmp, "gnupg")
        os.makedirs(gnupg)
        # también para el gpg que lanza descifrar_copia_cache; en forma /c/... porque el gpg de Git toma "C:\..." como
        # una ruta relativa
        unidad, resto = os.path.splitdrive(gnupg)
        os.environ["GNUPGHOME"] = ("/" + unidad[0].lower() if unidad else "") + resto.replace("\\", "/")
        trabajo = os.path.join(tmp, "actions")
        os.makedirs(trabajo)

        # --- comprobaciones del texto del flujo ---------------------------------------------------------------
        texto = open(FLUJO, encoding="utf-8").read()
        ok("ALERTAS_COPIA_CLAVE" in comprobar["env"] and "ALERTAS_COPIA_CLAVE" in cifrar["env"],
           "el flujo usa el secreto ALERTAS_COPIA_CLAVE")
        ok("--cipher-algo AES256" in cifrar["run"] and "--s2k-digest-algo SHA512" in cifrar["run"],
           "mismos parámetros de cifrado que la copia de alertas.db")
        ok("cache.db.gz" not in texto.replace("cache.db.gz.gpg", "") and "> \"$nombre\"" not in cifrar["run"],
           "no queda ningún .gz sin cifrar escrito en disco")
        ok('upload "$ETIQUETA" "$nombre" "${nombre}.sha256"' in subir["run"] and "$GITHUB_ENV" in cifrar["run"],
           "se sube solo $nombre (el .gpg) y su .sha256")
        ok(cifrar.get("if") == subir.get("if") == "steps.token.outputs.hay == 'si'",
           "cifrar y subir solo corren si están los dos secretos")

        # --- paso «¿Están...?» sin clave, con clave corta y con clave buena -------------------------------------
        for clave, esperado, codigo in (("", "hay=no", 0), ("corta", None, 1), (CLAVE, "hay=si", 0)):
            salida = os.path.join(trabajo, "salida.txt")
            open(salida, "w").close()
            r = ejecutar(bash, comprobar["run"], trabajo, {"COPIAS_TOKEN": "token-falso", "ALERTAS_COPIA_CLAVE": clave,
                                                          "GITHUB_OUTPUT": salida})
            contenido = open(salida).read()
            ok(r.returncode == codigo and (esperado is None or esperado in contenido),
               "comprobación de secretos con clave %r -> código %d %s" % ("*" * len(clave), r.returncode, contenido.strip()))

        # --- paso «Comprimir y cifrar» con la base inventada -------------------------------------------------------
        filas = base_inventada(os.path.join(trabajo, "cache.db"))
        genv = os.path.join(trabajo, "github_env.txt")
        open(genv, "w").close()
        r = ejecutar(bash, cifrar["run"], trabajo, {"ALERTAS_COPIA_CLAVE": CLAVE, "GITHUB_ENV": genv})
        ok(r.returncode == 0, "el paso «Comprimir y cifrar» del flujo termina bien")
        if r.returncode != 0:
            print(r.stdout[-2000:], r.stderr[-2000:])
            return
        ok(CLAVE not in r.stdout + r.stderr, "la clave no sale en el registro")
        nombre = open(genv).read().strip().split("=", 1)[1]
        copia = os.path.join(trabajo, nombre)
        ok(nombre.startswith("cache_") and nombre.endswith(".db.gz.gpg") and os.path.exists(copia),
           "deja la copia cifrada " + nombre)
        ok(not os.path.exists(os.path.join(trabajo, "cache.db")), "borra (shred) el cache.db sin cifrar")
        ok(sorted(os.listdir(trabajo)) == sorted(["github_env.txt", "salida.txt", nombre, nombre + ".sha256"]),
           "no queda ningún otro fichero: %s" % sorted(os.listdir(trabajo)))
        datos = open(copia, "rb").read()
        ok(b"SQLite format 3" not in datos and b"PERSONA INVENTADA" not in datos and b"Villaprueba" not in datos
           and datos[:2] != b"\x1f\x8b", "la copia no lleva nada legible (ni SQLite ni gzip ni nombres)")

        # --- descifrar -> integrity_check ------------------------------------------------------------------------
        destino = os.path.join(tmp, "restaurada", "cache.db")
        os.makedirs(os.path.dirname(destino))
        D.comprobar_sha256(copia)          # sale con sys.exit si no cuadra
        ok(True, "la huella .sha256 cuadra")
        resultado = D.descifrar(copia, destino, CLAVE, gpg)
        ok(resultado == "ok", "descifrar -> integrity_check: " + resultado)
        con = sqlite3.connect(destino)
        n = con.execute("SELECT COUNT(*) FROM municipios").fetchone()[0]
        nombres = [f[0] for f in con.execute("SELECT nombre FROM autonomos ORDER BY nif")]
        con.close()
        ok(n == filas and nombres == ["PERSONA INVENTADA UNO", "PERSONA INVENTADA DOS"],
           "la base restaurada tiene las mismas filas (%d fichas)" % n)
        ok(not os.path.exists(destino + ".descifrando"), "no queda el temporal")

        # --- lo que debe fallar ------------------------------------------------------------------------------------
        otra = os.path.join(tmp, "restaurada", "otra.db")
        try:
            D.descifrar(copia, otra, "clave-equivocada-0000000000", gpg)
            ok(False, "con una clave equivocada no se descifra")
        except RuntimeError:
            ok(not os.path.exists(otra) and not os.path.exists(otra + ".descifrando"),
               "con una clave equivocada no se descifra ni deja ficheros")

        danada = os.path.join(tmp, "danada.db.gz.gpg")
        b = bytearray(datos)
        b[len(b) // 2] ^= 0xFF
        open(danada, "wb").write(bytes(b))
        try:
            D.descifrar(danada, otra, CLAVE, gpg)
            ok(False, "una copia dañada no se da por buena")
        except RuntimeError:
            ok(not os.path.exists(otra) and not os.path.exists(otra + ".descifrando"),
               "una copia dañada falla (gpg/gzip) y no deja ficheros")

        # --- paso «Subir...» con un gh FALSO: qué copias se conservan y cuáles se borran ----------------------------
        probar_subida(bash, subir["run"], tmp)

        # el script de verdad, como lo lanzaría el titular: no sobrescribe y con la clave buena funciona
        cli = [sys.executable, os.path.join(BASE_DIR, "descifrar_copia_cache.py"), copia, "--salida", destino]
        env = dict(os.environ, COPIA_CLAVE=CLAVE)
        r = subprocess.run(cli, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        ok(r.returncode != 0 and "no lo sobrescribo" in (r.stderr + r.stdout), "el script no sobrescribe una base que ya existe")
        r = subprocess.run(cli[:-1] + [os.path.join(tmp, "restaurada", "cli.db")], env=env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        ok(r.returncode == 0 and "integrity_check: ok" in r.stdout and "SHA-256: ok" in r.stdout,
           "el script por línea de órdenes: " + (r.stdout + r.stderr).strip().replace(tmp, "<tmp>"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("TODO BIEN" if not fallos else "%d FALLOS" % len(fallos))
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()
