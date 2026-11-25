# encoding: utf-8
"""Prueba sin red y sin arrancar la web: las cargas de menores de fuentes propias se saltan si nada ha cambiado.

Saca de app.py con ast (no importa la web) _MENORES_PROPIOS y las funciones de la huella y comprueba:
  - la lista tiene TODAS las cargas de fuentes propias (_cargar_contratos_menores_*, menos la del feed de PLACE), una
    vez cada una, en el orden de antes, cada una con el fichero que lee de verdad, y _inicializar_datos ya no las
    llama una a una;
  - con una base de mentira (sqlite en memoria) y cargas de mentira: el primer arranque carga todas y guarda su huella;
    el segundo no carga ninguna; si cambia un fichero, solo esa; si cambia el código de una carga, solo esa; si cambia
    lo común (una lista de importes con aviso), todas; si una carga falla, no se marca; sin disco fiable, siempre todas.
Uso: python backend/prueba_menores_sin_cambios.py
"""
import ast
import hashlib
import os
import sqlite3
import sys
import tempfile
import textwrap
import threading
import time

BASE = os.path.dirname(os.path.abspath(__file__))
FALLOS = []


def ok(cond, txt):
    print(("OK   " if cond else "FALLO") + " " + txt, file=sys.__stdout__)    # también dentro de redirect_stdout
    if not cond:
        FALLOS.append(txt)


fuente = open(os.path.join(BASE, "app.py"), encoding="utf-8").read()
arbol = ast.parse(fuente, feature_version=(3, 11))
funcs = {n.name: n for n in arbol.body if isinstance(n, ast.FunctionDef)}
ok(True, "app.py compila con la gramática de Python 3.11")

# 1) la lista, completa y en orden
cargas = [n for n in funcs if n.startswith("_cargar_contratos_menores_") and n != "_cargar_contratos_menores_place"]
lista = next(n for n in arbol.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "_MENORES_PROPIOS")
entradas = [(e.elts[0].value, e.elts[1].id, e.elts[2]) for e in lista.value.elts]
ok([f for _, f, _ in entradas] == cargas, f"_MENORES_PROPIOS tiene las {len(cargas)} cargas, una vez cada una y en el orden de antes")
ok(len({n for n, _, _ in entradas}) == len(entradas), "nombres de fuente distintos")
for nombre, f, rutas in entradas:
    primera = next((n for n in ast.walk(funcs[f]) if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "ruta"), None)
    leida = ast.unparse(primera.value) if primera else "?"
    ok(ast.unparse(rutas.elts[0]) == leida, f"{nombre}: la huella mira el fichero que lee la carga ({leida})")
llamadas = {n.func.id for n in ast.walk(funcs["_inicializar_datos"]) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
ok(not (llamadas & set(cargas)) and "_cargar_menores_propios" in llamadas,
   "_inicializar_datos llama a _cargar_menores_propios y ya no a cada carga")

# 2) el comportamiento, con una base y cargas de mentira
tmp = tempfile.mkdtemp(prefix="prueba_menores_")
llamadas_hechas = []
espacio = {"hashlib": hashlib, "os": os, "time": time, "_db_lock": threading.Lock(), "_DISCO_CONFIABLE": True,
           "_MENORES_PROPIOS_VERSION": "v1", "_MENORES_PROPIOS_CLAVE": "menores_propios_huella:",
           "_MENORES_PROPIOS_ARRANQUE": {}, "_MENORES_AVISO_MANUAL": {}, "_MENORES_IMPORTE_VERIFICADO": {},
           "ARCHIVO_HASTA": "2021-09-01", "_RE_NOMBRE_DNI": __import__("re").compile("x")}
espacio["_db"] = sqlite3.connect(":memory:", check_same_thread=False)
espacio["_db"].execute("CREATE TABLE settings (clave TEXT PRIMARY KEY, valor TEXT)")
# las funciones comunes de la huella: de mentira, pero con su código fuente (inspect.getsource necesita un fichero)
modulo = os.path.join(tmp, "comunes_falsos.py")
codigo_cargas = "\n".join(textwrap.dedent(f"""
    def carga_{i}():
        LLAMADAS.append({i})
        if FALLA.get({i}):
            raise RuntimeError("falla")
    """) for i in range(3))
with open(modulo, "w", encoding="utf-8") as f:
    f.write("LLAMADAS = []\nFALLA = {}\n" + codigo_cargas + "\n"
            "def _guardar_contratos_menors_locales(r): pass\ndef _menor_importe_fiable(r): pass\n"
            "def nombre_sin_dni(n): return n\ndef enmascarar_nombres_dni(o): return 0\n")
sys.path.insert(0, tmp)
import comunes_falsos as cf  # noqa: E402
for n in ("_guardar_contratos_menors_locales", "_menor_importe_fiable", "nombre_sin_dni", "enmascarar_nombres_dni"):
    espacio[n] = getattr(cf, n)
nodos = [funcs[n] for n in ("_menores_propios_codigo", "_menores_propios_huella", "_cargar_menores_propios")]
exec(compile(ast.Module(body=nodos, type_ignores=[]), "app.py", "exec"), espacio)
ficheros = []
for i in range(3):
    ficheros.append(os.path.join(tmp, f"menores_{i}.json.gz"))
    with open(ficheros[-1], "wb") as f:
        f.write(f"contenido {i}".encode())
espacio["_MENORES_PROPIOS"] = tuple((f"fuente{i}", getattr(cf, f"carga_{i}"), (ficheros[i], ficheros[i] + ".no_existe"))
                                    for i in range(3))


def arrancar():
    del cf.LLAMADAS[:]
    espacio["_cargar_menores_propios"]()
    return list(cf.LLAMADAS)


import io, contextlib  # noqa: E401,E402
with contextlib.redirect_stdout(io.StringIO()):
    r1, r2 = arrancar(), arrancar()
ok(r1 == [0, 1, 2], "primer arranque: carga las tres")
ok(r2 == [], "segundo arranque sin cambios: no carga ninguna")
ok(espacio["_MENORES_PROPIOS_ARRANQUE"].get("saltadas") == 3, "el diagnóstico cuenta 3 sin cambios")
with open(ficheros[1], "ab") as f:
    f.write(b" y algo nuevo")
with contextlib.redirect_stdout(io.StringIO()):
    r3, r4 = arrancar(), arrancar()
ok(r3 == [1] and r4 == [], "cambia un fichero: solo esa fuente, y una sola vez")
with open(ficheros[2] + ".no_existe", "wb") as f:            # aparece el fichero de respaldo (como el .json de Murcia)
    f.write(b"respaldo")
with contextlib.redirect_stdout(io.StringIO()):
    ok(arrancar() == [2], "aparece el fichero de respaldo: solo esa fuente")
espacio["_MENORES_AVISO_MANUAL"]["Loiu::EUSKADI::x"] = ("tres-ceros", 1.0)
with contextlib.redirect_stdout(io.StringIO()):
    ok(arrancar() == [0, 1, 2], "cambia una lista de importes con aviso: todas")
cf.FALLA[0] = True
with contextlib.redirect_stdout(io.StringIO()):
    try:
        with open(ficheros[0], "ab") as f:
            f.write(b"!")
        arrancar()
        ok(False, "una carga que falla corta el arranque, como antes")
    except RuntimeError:
        ok(True, "una carga que falla corta el arranque, como antes")
    cf.FALLA.clear()
    ok(arrancar() == [0], "la carga que falló no quedó marcada: se repite en el arranque siguiente")
espacio["_DISCO_CONFIABLE"] = False
with contextlib.redirect_stdout(io.StringIO()):
    ok(arrancar() == [0, 1, 2], "sin disco fiable: siempre todas")
espacio["_DISCO_CONFIABLE"] = True
# cambiar el código de una carga (otro módulo con carga_1 distinta)
with open(os.path.join(tmp, "otra_carga.py"), "w", encoding="utf-8") as f:
    f.write("def carga_1():\n    import comunes_falsos\n    comunes_falsos.LLAMADAS.append(1)  # versión nueva\n")
import otra_carga  # noqa: E402
espacio["_MENORES_PROPIOS"] = (espacio["_MENORES_PROPIOS"][0], ("fuente1", otra_carga.carga_1, espacio["_MENORES_PROPIOS"][1][2]),
                               espacio["_MENORES_PROPIOS"][2])
with contextlib.redirect_stdout(io.StringIO()):
    ok(arrancar() == [1], "cambia el código de una carga: solo esa")

espacio["_db"].close()
__import__("shutil").rmtree(tmp, ignore_errors=True)
print("\nTODO BIEN" if not FALLOS else f"\n{len(FALLOS)} FALLOS")
sys.exit(1 if FALLOS else 0)
