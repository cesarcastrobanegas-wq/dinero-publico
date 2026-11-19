# encoding: utf-8
"""Prueba sin red y sin arrancar la web de las correcciones del aviso legal publicado (04-11-2026).

Comprueba que en app.py y en los catálogos gl/ca/eu ya no quedan las tres frases inexactas (art. 9.2.e del RGPD,
«no guarda direcciones IP» del contador, Resend «solo» con la dirección), que las nuevas están en el aviso legal y
que cada una tiene traducción que carga el mismo lector de .po que usa la web (_po_leer, sacado de app.py con ast).
Uso: python backend/aviso_legal_prueba.py
"""
import ast
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
FALLOS = []


def ok(cond, txt):
    print(("OK   " if cond else "FALLO") + " " + txt)
    if not cond:
        FALLOS.append(txt)


fuente = open(os.path.join(BASE, "app.py"), encoding="utf-8").read()
arbol = ast.parse(fuente, feature_version=(3, 11))
ok(True, "app.py compila con la gramática de Python 3.11")

# el lector de .po de la web, tal cual
funcs = [n for n in arbol.body if isinstance(n, ast.FunctionDef) and n.name in ("_po_leer", "_po_unescape")]
espacio = {"re": re}
exec(compile(ast.Module(body=funcs, type_ignores=[]), "app.py", "exec"), espacio)
_po_leer = espacio["_po_leer"]

# literales _t("...") de render_aviso_legal_html
render = next(n for n in arbol.body if isinstance(n, ast.FunctionDef) and n.name == "render_aviso_legal_html")
textos = [n.args[0].value for n in ast.walk(render) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_t"
          and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)]

VIEJAS = ["art. 9.2.e", "ni guarda direcciones IP. Para", "recibe tu dirección solo para entregar los mensajes"]
NUEVAS = ["art. 6.1.f del Reglamento General de Protección de Datos",
          "ni guarda direcciones IP completas",
          "recibe tu dirección y el contenido de cada mensaje"]
for v in VIEJAS:
    ok(v not in fuente, f"app.py ya no dice «{v}»")
for n in NUEVAS:
    ok(sum(n in t for t in textos) == 1, f"el aviso legal dice «{n}»")
ok(any("192.0.2.0/24" in t and "100 redes" in t and "30 días" in t for t in textos),
   "el contador explica la red /24, las 100 redes y los 30 días")
# las cifras del texto son las del código
m_redes = re.search(r"^_VISITAS_REDES_POR_DIA = (\d+)", fuente, re.M)
m_dias = re.search(r"^_VISITAS_REDES_DIAS = (\d+)", fuente, re.M)
ok(m_redes and m_redes.group(1) == "100" and m_dias and m_dias.group(1) == "30",
   "100 redes y 30 días coinciden con _VISITAS_REDES_POR_DIA y _VISITAS_REDES_DIAS")

for lang in ("gl", "ca", "eu"):
    ruta = os.path.join(BASE, "locale", f"{lang}.po")
    crudo = open(ruta, encoding="utf-8").read()
    cat = _po_leer(ruta)
    for v in VIEJAS:
        ok(v not in crudo, f"{lang}.po ya no tiene «{v}»")
    for n in NUEVAS:
        t = next(t for t in textos if n in t)
        ok(bool(cat.get(t)) and cat[t] != t, f"{lang}: traducción cargada para «{n[:40]}…»")
    ok("6.1.f" in crudo and "9.2.e" not in crudo, f"{lang}: cita el 6.1.f y no el 9.2.e")

print(f"\n{'TODO BIEN' if not FALLOS else str(len(FALLOS)) + ' FALLOS'}")
sys.exit(1 if FALLOS else 0)
