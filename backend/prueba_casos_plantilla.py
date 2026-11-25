# encoding: utf-8
"""Prueba sin red y sin arrancar la web de la plantilla de casos para la tanda del 30-11-2026.

Comprueba, sacando las funciones de app.py con ast (no importa la web):
  - _tabla_contratos_caso da EXACTAMENTE el mismo HTML que antes con las filas de siempre (las piezas publicadas no
    cambian), y admite columnas de texto de más (calle y adjudicataria) con el total en su sitio;
  - _caso_fraccionamiento_pagina sigue poniendo «14 de octubre de 2026» por defecto y acepta otra fecha;
  - _caso_version_ayuntamiento: frase de espera sin respuesta, la respuesta tal cual si la hay;
  - la lista _CASOS_PUBLICAR_20261130 se engancha a _CASOS y _CASOS_RENDER_POR_SLUG. Antes de publicar está VACÍA
    (ningún texto de caso sin publicar en el repositorio); el día de publicar, cada pieza tiene slug, titulo, resumen
    y su función render definida.
Uso: python backend/prueba_casos_plantilla.py
"""
import ast
import html
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
FALLOS = []


def ok(cond, txt):
    print(("OK   " if cond else "FALLO") + " " + txt)
    if not cond:
        FALLOS.append(txt)


def sacar(fuente, nombres, espacio):
    arbol = ast.parse(fuente, feature_version=(3, 11))
    nodos = [n for n in arbol.body if isinstance(n, ast.FunctionDef) and n.name in nombres]
    exec(compile(ast.Module(body=nodos, type_ignores=[]), "app.py", "exec"), espacio)
    return arbol


fuente = open(os.path.join(BASE, "app.py"), encoding="utf-8").read()
NOMBRES = ("_eur_caso", "_tabla_contratos_caso", "_caso_fraccionamiento_pagina", "_caso_version_ayuntamiento")
paginas = []
nuevo = {"esc": lambda s: html.escape(str(s or ""), quote=True),
         "_caso_pagina": lambda og, t, cuerpo, d: paginas.append(cuerpo) or cuerpo}
arbol = sacar(fuente, NOMBRES, nuevo)
ok(True, "app.py compila con la gramática de Python 3.11")

# la versión de antes, de origin/main (si no se puede leer, se compara con una copia fija de las filas de siempre)
try:
    viejo_txt = subprocess.run(["git", "show", "origin/main:backend/app.py"], cwd=BASE, capture_output=True,
                               check=True).stdout.decode("utf-8")
    viejo = {"esc": nuevo["esc"]}
    sacar(viejo_txt, ("_eur_caso", "_tabla_contratos_caso"), viejo)
except Exception as e:                                    # sin git: se salta solo esta comparación
    viejo = None
    print(f"AVISO no se pudo leer origin/main ({type(e).__name__}); se salta la comparación con la versión anterior")

filas = [("06/05/2026", "1/2026", "Obra de prueba «uno»", 38095.81, "https://ejemplo.invalid/a?x=1&y=2"),
         ("06/05/2026", "2/2026", "Obra <dos>", 1000.0, "")]
t = nuevo["_tabla_contratos_caso"]
if viejo:
    for kw in ({}, {"total": False}, {"etiqueta": "listado oficial", "impuesto": "IGIC"}):
        ok(t(filas, **kw) == viejo["_tabla_contratos_caso"](filas, **kw), f"tabla igual que antes con {kw or 'lo de siempre'}")
h = t(filas)
ok("39.095,81 €" in h and 'colspan="3"' in h, "total y colspan de siempre")
ok("&lt;dos&gt;" in h and "&amp;y=2" in h, "objeto y enlace escapados")

filas6 = [("29/11/2024", "10/2024", "Calle A", "Empresa Uno, S.L.", 100.5, "https://ejemplo.invalid/1"),
          ("26/12/2024", "11/2024", "Calle B", "Empresa Dos, S.L.", 200.25, "")]
h6 = t(filas6, columnas=("Calle", "Adjudicataria"))
ok("<th style=\"text-align:left\">Calle</th><th style=\"text-align:left\">Adjudicataria</th>" in h6,
   "cabeceras de las columnas de más")
ok('colspan="4"' in h6 and "300,75 €" in h6, "total con dos columnas de texto (colspan 4, suma bien)")
ok("<td>Calle A</td><td>Empresa Uno, S.L.</td>" in h6 and "100,50 €" in h6, "celdas en su sitio")
ok(h6.count("<tr>") == 4, "cabecera + 2 filas + total")

p = nuevo["_caso_fraccionamiento_pagina"]
ok("comprobados el 14 de octubre de 2026" in p("/casos/x", "T", "<p>c</p>", "d"), "fecha de siempre por defecto")
ok("comprobados el 15 de noviembre de 2026" in p("/casos/x", "T", "<p>c</p>", "d", comprobado="15 de noviembre de 2026"),
   "otra fecha de comprobación")

v = nuevo["_caso_version_ayuntamiento"]
ok("Pedimos su versión al Ayuntamiento el 16 de noviembre de 2026. La añadiremos en cuanto la recibamos." in
   v("16 de noviembre de 2026"), "frase de espera sin respuesta")
r = v("16 de noviembre de 2026", "<p>El Ayuntamiento explica que…</p>")
ok("<h2>La versión del Ayuntamiento</h2>" in r and "explica que" in r and "La añadiremos" not in r,
   "con respuesta: la respuesta y sin la frase de espera")

# la lista de la tanda está vacía en el repositorio y enganchada
lista = [n for n in arbol.body if isinstance(n, ast.Assign) and any(getattr(x, "id", "") == "_CASOS_PUBLICAR_20261130"
                                                                     for x in n.targets)]
ok(len(lista) == 1 and isinstance(lista[0].value, ast.List), "_CASOS_PUBLICAR_20261130 es una lista, una sola vez")
elementos = lista[0].value.elts if lista and isinstance(lista[0].value, ast.List) else []
if not elementos:
    ok(True, "_CASOS_PUBLICAR_20261130 = [] (antes de publicar: ningún caso sin publicar en el repositorio)")
else:                                  # el día de publicar: cada pieza completa y con su función definida
    funciones = {n.name for n in arbol.body if isinstance(n, ast.FunctionDef)}
    for e in elementos:
        claves = {k.value: v for k, v in zip(e.keys, e.values)} if isinstance(e, ast.Dict) else {}
        ok(set(claves) == {"slug", "render", "titulo", "resumen"}
           and getattr(claves.get("render"), "id", "") in funciones,
           f"pieza {getattr(claves.get('slug'), 'value', '?')}: slug, render (definida), titulo y resumen")
ok("_CASOS[1:1] = [{k: v for k, v in c.items() if k != \"render\"} for c in _CASOS_PUBLICAR_20261130]" in fuente
   and "_CASOS_RENDER_POR_SLUG.update({c[\"slug\"]: c[\"render\"] for c in _CASOS_PUBLICAR_20261130})" in fuente,
   "la lista se engancha a _CASOS y _CASOS_RENDER_POR_SLUG")

print("\nTODO BIEN" if not FALLOS else f"\n{len(FALLOS)} FALLOS")
sys.exit(1 if FALLOS else 0)
