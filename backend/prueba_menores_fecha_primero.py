# encoding: utf-8
"""Prueba sin red y sin arrancar la web (25-11-2026): en la tabla de contratos menores del municipio la FECHA es la
primera columna, en la cabecera y en cada fila, y en el móvil la tabla tiene sus propias reglas de tarjeta
(table.t-menores: fecha arriba en su línea, nombre e importe debajo). Motivo: en la ficha de Vitoria-Gasteiz la fecha
de una fila, al ser la última columna, quedaba encima del nombre de la siguiente y parecía suya.
Uso: python backend/prueba_menores_fecha_primero.py
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

# cabecera
m = re.search(r'<table class="t-tarjeta t-menores">\s*<tr>(.*?)</tr>', fuente, re.S)
cabecera = re.findall(r'<th>\{_t\("([^"]+)"\)\}</th>', m.group(1)) if m else []
ok(cabecera == ["Fecha", "Adjudicatario / Objeto", "Importe", "Directivo", "Tipo"],
   f"cabecera en orden: {cabecera}")

# fila: el texto del return de _render_fila_contrato_menor
f = next(n for n in arbol.body if isinstance(n, ast.FunctionDef) and n.name == "_render_fila_contrato_menor")
ret = ast.get_source_segment(fuente, [n for n in ast.walk(f) if isinstance(n, ast.Return)][-1])
celdas = re.findall(r"<td[^>]*>", ret)
ok(len(celdas) == len(cabecera), f"la fila tiene {len(celdas)} celdas, como la cabecera")
primera = ret.split("<td", 2)[1]
ok('class="cm-fecha"' in primera and "data_adjudicacio" in primera and "fecha_nota" in primera,
   "la primera celda es la fecha, con su aviso de fecha futura")
ok(ret.count("data_adjudicacio") == 1, "la fecha sale una sola vez en la fila")
ok('class="cm-importe"' in ret.split("<td", 4)[3], "el importe es la tercera celda")

# móvil
css = re.findall(r"table\.t-menores td:nth-child\((\d)\)\{([^}]*)\}", fuente)
reglas = {n: r for n, r in css}
ok(set(reglas) == {"1", "2", "3"}, "reglas de tarjeta para las celdas 1, 2 y 3 de t-menores")
ok("flex:1 1 100%" in reglas.get("1", ""), "móvil: la fecha ocupa su propia línea, arriba")
ok("text-align:right" in reglas.get("3", "") and "nowrap" in reglas.get("3", ""), "móvil: el importe, a la derecha")
pos_gen = fuente.find("table.t-tarjeta td:nth-child(2){")
pos_men = fuente.find("table.t-menores td:nth-child(1){")
ok(0 < pos_gen < pos_men, "las reglas de t-menores van después de las generales (misma especificidad: ganan ellas)")

print("\nTODO BIEN" if not FALLOS else f"\n{len(FALLOS)} FALLOS")
sys.exit(1 if FALLOS else 0)
