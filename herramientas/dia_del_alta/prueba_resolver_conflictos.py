# encoding: utf-8
"""Prueba de resolver_conflictos.py (reglas «22», «26» y «59» del 19-11-2026). Sin red: monta un repositorio git de
juguete en una carpeta temporal, provoca los choques de verdad con «git merge» y ejecuta el script como el día de la
SLU. Comprueba también que cualquier bloque distinto sigue dando «NO CONOZCO» y deja el fichero sin tocar.
  python herramientas/dia_del_alta/prueba_resolver_conflictos.py"""
import os
import shutil
import subprocess
import sys
import tempfile

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resolver_conflictos.py")
bien, mal = [0], []


def comprobar(cond, texto):
    if cond:
        bien[0] += 1
    else:
        mal.append(texto)


def git(carpeta, *args):
    return subprocess.run(["git", "-c", "user.name=prueba", "-c", "user.email=prueba@ejemplo.test",
                           "-c", "core.autocrlf=false", *args], cwd=carpeta, capture_output=True, text=True,
                          encoding="utf-8")


def escribir(carpeta, ruta, texto):
    p = os.path.join(carpeta, ruta)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(texto)


def leer(carpeta, ruta):
    with open(os.path.join(carpeta, ruta), encoding="utf-8", newline="") as f:
        return f.read()


BASE_APP = '''try:
    from . import filtro_embudo as FEMB
except ImportError:
    import filtro_embudo as FEMB
try:
    from .alcance import ARCHIVO_HASTA
except ImportError:
    from alcance import ARCHIVO_HASTA


def _header_html():
    return "<header></header>"


def _footer_html():
    return "<footer></footer>"
'''
IMPORT_GUIA = '''try:
    from . import licitaciones_guia as _LIC_GUIA
except ImportError:
    import licitaciones_guia as _LIC_GUIA
'''
IMPORT_FP = '''try:
    from . import forma_pago as FP
except ImportError:
    import forma_pago as FP
'''
REDES = '''# ─── PERFILES EN REDES (ficticio, para la prueba) ───
PERFILES_REDES = (
    ("Ejemplo", "@ejemplo", "https://red.ejemplo.test/ejemplo"),
)


def _perfiles_redes():
    return [p for p in PERFILES_REDES if p[2]]
'''
VENTA = '''# ─── ENLACES DE VENTA (ficticio, para la prueba) ───
_VENTA_PRECIOS = False
_VENTA_TEXTOS_LEGALES = False


def _venta_pie_extra():
    return ""
'''
BASE_PO = '''msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\\n"

msgid "Portada"
msgstr "Portada"
'''
PO_MAIN = '''
msgid "Sueldos de concejales"
msgstr "Soldos de concelleiros"

msgid ""
"Texto largo de dos "
"líneas"
msgstr "Texto longo"
'''
PO_RAMA = '''
msgid "Precios"
msgstr "Prezos"

msgid "Condiciones de contratación"
msgstr "Condicións de contratación"
'''


def montar(cambios_main, cambios_rama):
    """Repositorio de juguete: base, una rama «main» con `cambios_main` y una «rama» con `cambios_rama`; fusiona main
    en la rama (como el día de la SLU) y devuelve la carpeta, con los choques sin resolver."""
    d = tempfile.mkdtemp(prefix="prueba_resolver_")
    git(d, "init", "-q", "-b", "main")
    escribir(d, "backend/app.py", BASE_APP)
    escribir(d, "backend/locale/gl.po", BASE_PO)
    escribir(d, ".gitignore", "*.pyc\n")
    git(d, "add", "-A")
    git(d, "commit", "-qm", "base")
    git(d, "checkout", "-qb", "rama")
    for ruta, f in cambios_rama.items():
        escribir(d, ruta, f(leer(d, ruta)))
    git(d, "commit", "-qam", "rama")
    git(d, "checkout", "-q", "main")
    for ruta, f in cambios_main.items():
        escribir(d, ruta, f(leer(d, ruta)))
    git(d, "commit", "-qam", "main")
    git(d, "checkout", "-q", "rama")
    git(d, "merge", "-q", "main")
    return d


def resolver(d, n):
    r = subprocess.run([sys.executable, SCRIPT, n], cwd=d, capture_output=True, text=True, encoding="utf-8",
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return r.returncode, r.stdout + r.stderr


def tras(ancla, nuevo):
    return lambda t: t.replace(ancla, ancla + nuevo, 1)


ANCLA_IMPORT = "    import filtro_embudo as FEMB\n"
ANCLA_HEADER = '    return "<header></header>"\n\n\n'


def main():
    # ── regla 22: los dos import, primero el de main ──
    d = montar({"backend/app.py": tras(ANCLA_IMPORT, IMPORT_GUIA)}, {"backend/app.py": tras(ANCLA_IMPORT, IMPORT_FP)})
    comprobar("backend/app.py" in git(d, "diff", "--name-only", "--diff-filter=U").stdout, "22: no hubo choque")
    codigo, salida = resolver(d, "22")
    t = leer(d, "backend/app.py")
    comprobar(codigo == 0, f"22: salida {codigo}: {salida}")
    comprobar("<<<<<<<" not in t and ">>>>>>>" not in t, "22: quedan marcas")
    comprobar(t.find("licitaciones_guia") < t.find("forma_pago") and t.count("try:") == 4,
              "22: no están los dos import en orden con su try")
    comprobar(BASE_APP.replace(ANCLA_IMPORT, ANCLA_IMPORT + IMPORT_GUIA + IMPORT_FP) == t, "22: el resultado no es el esperado")
    shutil.rmtree(d, ignore_errors=True)

    # ── regla 22 ante un import distinto: NO CONOZCO y el fichero sin tocar ──
    otro = IMPORT_GUIA.replace("licitaciones_guia as _LIC_GUIA", "otra_cosa as OTRA")
    d = montar({"backend/app.py": tras(ANCLA_IMPORT, otro)}, {"backend/app.py": tras(ANCLA_IMPORT, IMPORT_FP)})
    antes = leer(d, "backend/app.py")
    codigo, salida = resolver(d, "22")
    comprobar(codigo != 0 and "NO CONOZCO" in salida, f"22 distinto: debería decir NO CONOZCO: {salida}")
    comprobar(leer(d, "backend/app.py") == antes, "22 distinto: ha tocado el fichero")
    shutil.rmtree(d, ignore_errors=True)

    # ── regla 26: bloque de redes (main) + bloque de venta (rama), y los .po con las dos tandas sin repetidas ──
    d = montar({"backend/app.py": tras(ANCLA_HEADER, REDES + "\n\n"), "backend/locale/gl.po": lambda t: t + PO_MAIN},
               {"backend/app.py": tras(ANCLA_HEADER, VENTA + "\n\n"), "backend/locale/gl.po": lambda t: t + PO_RAMA})
    choques = git(d, "diff", "--name-only", "--diff-filter=U").stdout.split()
    comprobar(set(choques) == {"backend/app.py", "backend/locale/gl.po"}, f"26: choques {choques}")
    codigo, salida = resolver(d, "26")
    comprobar(codigo == 0, f"26: salida {codigo}: {salida}")
    t = leer(d, "backend/app.py")
    comprobar("<<<<<<<" not in t and t.find("PERFILES_REDES = (") < t.find("_VENTA_PRECIOS = "),
              "26: app.py sin los dos bloques en orden")
    comprobar(t.count("def _venta_pie_extra") == 1 and t.count("def _perfiles_redes") == 1, "26: bloques repetidos")
    po = leer(d, "backend/locale/gl.po")
    comprobar("<<<<<<<" not in po, "26: quedan marcas en el .po")
    comprobar('msgid "Precios"' in po and '"Texto largo de dos "' in po and 'msgid "Sueldos de concejales"' in po
              and 'msgid "Condiciones de contratación"' in po, "26: falta alguna traducción")
    comprobar(po.count('msgid ""') == 2, "26: los msgid de varias líneas se han confundido")
    shutil.rmtree(d, ignore_errors=True)

    # ── r_po directamente: una entrada que está en los dos lados no se repite; los msgid de varias líneas no se
    #    confunden entre sí (git no siempre los deja así, pero la regla tiene que aguantarlo) ──
    sys.path.insert(0, os.path.dirname(SCRIPT))
    import resolver_conflictos as R
    a = ['msgid "A"', 'msgstr "a"', '', 'msgid ""', '"largo uno"', 'msgstr "l1"', '']
    b = ['msgid "B"', 'msgstr "b"', '', 'msgid "A"', 'msgstr "a"', '', 'msgid ""', '"largo dos"', 'msgstr "l2"']
    r = R.r_po((a, b))
    comprobar(r.count('msgid "A"') == 1 and 'msgid "B"' in r and '"largo uno"' in r and '"largo dos"' in r,
              f"r_po: {r}")
    try:
        R.r_po((a, ["def f():", "    pass"]))
        comprobar(False, "r_po: aceptó un bloque que no es de .po")
    except LookupError:
        comprobar(True, "")

    # ── regla 26 ante otro bloque de app.py: NO CONOZCO ──
    d = montar({"backend/app.py": tras(ANCLA_HEADER, "def _otra_cosa():\n    return 1\n\n\n")},
               {"backend/app.py": tras(ANCLA_HEADER, VENTA + "\n\n")})
    antes = leer(d, "backend/app.py")
    codigo, salida = resolver(d, "26")
    comprobar(codigo != 0 and "NO CONOZCO" in salida and leer(d, "backend/app.py") == antes,
              f"26 distinto: debería decir NO CONOZCO sin tocar: {salida}")
    shutil.rmtree(d, ignore_errors=True)

    # ── regla 59: solo los .po; un app.py en conflicto es NO CONOZCO ──
    d = montar({"backend/locale/gl.po": lambda t: t + PO_MAIN}, {"backend/locale/gl.po": lambda t: t + PO_RAMA})
    codigo, salida = resolver(d, "59")
    comprobar(codigo == 0 and "<<<<<<<" not in leer(d, "backend/locale/gl.po"), f"59: {salida}")
    shutil.rmtree(d, ignore_errors=True)
    d = montar({"backend/app.py": tras(ANCLA_IMPORT, IMPORT_GUIA)}, {"backend/app.py": tras(ANCLA_IMPORT, IMPORT_FP)})
    codigo, salida = resolver(d, "59")
    comprobar(codigo != 0 and "NO CONOZCO el conflicto de backend/app.py" in salida, f"59 con app.py: {salida}")
    shutil.rmtree(d, ignore_errors=True)

    # ── reglas 15 y 69: el bloque del PR en .gitignore detrás del del #20 (ya en main) ──
    BLOQUE_20 = "# Nombres que vigila la prueba de los textos legales\nbackend/prueba_nombres_prohibidos.txt\n"
    for n, bloque in (("15", "# FTS (ficticio)\n*fts*.ndjson*\nfts_descargas/\n"),
                      ("69", "# datos personales (ficticio)\nbackend/datos_personales/\n")):
        d = montar({".gitignore": lambda t: t + BLOQUE_20}, {".gitignore": lambda t, b=bloque: t + b})
        codigo, salida = resolver(d, n)
        g = leer(d, ".gitignore")
        comprobar(codigo == 0 and "<<<<<<<" not in g and g.find("prueba_nombres_prohibidos") < g.find(bloque.split("\n")[1]),
                  f"{n}: .gitignore con los dos bloques en orden: {salida} {g!r}")
        shutil.rmtree(d, ignore_errors=True)
    d = montar({".gitignore": lambda t: t + "otra_cosa/\n"}, {".gitignore": lambda t: t + "backend/datos_personales/\n"})
    antes = leer(d, ".gitignore")
    codigo, salida = resolver(d, "69")
    comprobar(codigo != 0 and "NO CONOZCO" in salida and leer(d, ".gitignore") == antes,
              f"69 con otro .gitignore: debería decir NO CONOZCO sin tocar: {salida}")
    shutil.rmtree(d, ignore_errors=True)

    # ── un .po con algo que no es una traducción dentro del choque: NO CONOZCO ──
    d = montar({"backend/locale/gl.po": lambda t: t + PO_MAIN},
               {"backend/locale/gl.po": lambda t: t + "\nesto no es una entrada de po\n" + PO_RAMA})
    antes = leer(d, "backend/locale/gl.po")
    codigo, salida = resolver(d, "26")
    comprobar(codigo != 0 and "NO CONOZCO" in salida and leer(d, "backend/locale/gl.po") == antes,
              f".po raro: debería decir NO CONOZCO sin tocar: {salida}")
    shutil.rmtree(d, ignore_errors=True)

    for m in mal:
        print("MAL:", m)
    print(f"{bien[0]} bien, {len(mal)} mal")
    sys.exit(1 if mal else 0)


if __name__ == "__main__":
    main()
