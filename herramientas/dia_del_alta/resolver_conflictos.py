# encoding: utf-8
"""
Resuelve los conflictos de las fusiones del DÍA DEL ALTA (ensayados el 05-11-2026 en una copia local).

Se usa DENTRO de la carpeta de la rama del PR, después de «git merge origin/main» cuando git dice CONFLICT:
    python herramientas/dia_del_alta/resolver_conflictos.py 22
(el número es el del PR: 22, 25, 20 o 19; el 20 solo si el #16, la PAC, ya está en main). Da igual qué lado sea «el tuyo» y cuál «el de main»: cada bloque se reconoce
por lo que lleva. Si encuentra un bloque que no conoce, NO toca ese fichero y lo dice: entonces hay que resolverlo a
mano (lo de cada bloque está explicado en «DIA DEL ALTA - pasos.txt»).
Al acabar: comprueba la sintaxis, y tú solo tienes que pasar las pruebas, «git add -A» y «git commit».
"""
import ast
import os
import re
import subprocess
import sys


def bloques(texto, nl):
    """Parte el fichero en trozos: str (fuera de conflicto) o (lado1, lado2) (listas de líneas)."""
    lin = texto.split(nl)
    out, i = [], 0
    while i < len(lin):
        if lin[i].startswith("<<<<<<< "):
            m = i
            while lin[m] != "=======" and not lin[m].startswith("||||||| "):
                m += 1
            b = m
            while lin[b] != "=======":
                b += 1
            e = b
            while not lin[e].startswith(">>>>>>> "):
                e += 1
            out.append((lin[i + 1:m], lin[b + 1:e]))
            i = e + 1
        else:
            out.append(lin[i])
            i += 1
    return out


def con(lados, aguja):
    """El lado que contiene `aguja` y el otro."""
    a, b = lados
    if any(aguja in x for x in a):
        return a, b
    if any(aguja in x for x in b):
        return b, a
    raise LookupError(aguja)


# ── reglas por PR: para cada fichero, una función que recibe (lado1, lado2) y devuelve las líneas resueltas ──

def r22_prueba_web(lados):
    # #24 llama a orden(...) al final del caso; #22 añade las pruebas del formulario del panel. Se dejan los dos:
    # primero la llamada a orden(...) y detrás el bloque del formulario.
    o, f = con(lados, "orden(alm, ok, post, ahora)")
    return o + f


def r25_socios(lados):
    t = "\n".join(lados[0] + lados[1])
    if "pagado_hasta (31-10" in t:                      # docstring: las dos explicaciones
        p, c = con(lados, "pagado_hasta (31-10")
        return p + c
    if t.lstrip().startswith('"revisado"') or '"revisado", "ultimo_envio"' in t:       # _CAMPOS
        return ['           "revisado", "ultimo_envio", "intentado", "aviso_inactividad", "pagado_hasta", "aviso_pago",',
                '           "condiciones_aceptadas", "condiciones_version")']
    if "aviso_inactividad REAL" in t:                   # esquema de la tabla
        return ["    aviso_inactividad REAL, pagado_hasta REAL, aviso_pago REAL, condiciones_aceptadas REAL, "
                "condiciones_version TEXT);"]
    if "ALTER TABLE perfiles ADD COLUMN" in t:          # migración de un socios.db viejo
        return ['            for col, tipo in (("pagado_hasta", "REAL"), ("aviso_pago", "REAL"),             # socios.db de antes del 31-10',
                '                              ("condiciones_aceptadas", "REAL"), ("condiciones_version", "TEXT")):   # y del 04-11',
                '                if col not in columnas:',
                '                    self.db.execute(f"ALTER TABLE perfiles ADD COLUMN {col} {tipo}")']
    raise LookupError("socios.py")


def r25_filtro(lados):
    # forma_pago_texto/forma_pago_puesta (#13/#22) + condiciones y precio (#25). Sin ANCLA_AVISO_LEGAL (la quita el #25).
    p, c = con(lados, "def forma_pago_texto")
    return [x for x in p if not x.startswith("ANCLA_AVISO_LEGAL")] + [""] + c


def r25_app(lados):
    t = "\n".join(lados[0] + lados[1])
    if "Condiciones vigentes" in t:                     # resumen del panel: las filas de pago y la de condiciones
        p, c = con(lados, "con_pago_vigente")
        filas = [x for x in p if x.strip() != "f'{cupo}</table>')"]
        corte = next(i for i, x in enumerate(filas) if x.lstrip().startswith("_estado_txt"))
        return filas[:corte] + c + filas[corte:]
    if "{esc(pagado(p))}" in t:                         # fila de cada perfil: columna de pago y de condiciones
        p, _ = con(lados, "{esc(pagado(p))}")
        return [p[0].replace("<td>{esc(pagado(p))}</td>'", "<td>{esc(pagado(p))}</td><td>{condiciones(p)}</td>'")] + p[1:]
    if "<th>Pagado hasta</th>" in t:                    # cabecera de la tabla: 11 columnas
        p, _ = con(lados, "<th>Pagado hasta</th>")
        return [p[0].replace("<th>Pagado hasta</th>", "<th>Pagado hasta</th><th>Condiciones aceptadas</th>")
                .replace("vacio(10)", "vacio(11)")] + p[1:]
    raise LookupError("app.py")


def r19_app(lados):
    t = "\n".join(lados[0] + lados[1])
    if "import precios as PRECIOS" in t:                # imports: los dos, cada uno con su try
        f, p = con(lados, "forma_pago as FP")
        return f + ["try:"] + p
    if "/precios" in t:                                 # rutas detrás de /aviso-legal: las dos
        p, l = con(lados, "/precios")
        return l + [""] + p
    raise LookupError("app.py")


def r20_gitignore(lados):
    # 07-11: con el #16 (PAC) ya en main, el #20 choca en .gitignore: los dos añaden su bloque al final. Se dejan los
    # dos: primero el de la PAC, una línea en blanco y el de los nombres que vigila la prueba de los textos legales.
    p, t = con(lados, "fega")
    if not any("prueba_nombres_prohibidos" in x for x in t):
        raise LookupError(".gitignore")
    return p + [""] + t


REGLAS = {
    "20": {".gitignore": r20_gitignore},
    "22": {"backend/socios_pagado_prueba_web.py": r22_prueba_web},
    "25": {"backend/socios.py": r25_socios, "backend/filtro_formulario.py": r25_filtro, "backend/app.py": r25_app},
    "19": {"backend/app.py": r19_app},
}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in REGLAS:
        sys.exit(__doc__)
    reglas = REGLAS[sys.argv[1]]
    en_conflicto = subprocess.run(["git", "diff", "--name-only", "--diff-filter=U"], capture_output=True, text=True,
                                  check=True).stdout.split()
    if not en_conflicto:
        print("No hay ningún fichero en conflicto: nada que hacer.")
        return
    mal = 0
    for ruta in en_conflicto:
        if ruta not in reglas:
            print(f"NO CONOZCO el conflicto de {ruta}: resuélvelo a mano.")
            mal += 1
            continue
        s = open(ruta, encoding="utf-8", newline="").read()
        nl = "\r\n" if "\r\n" in s else "\n"
        trozos = bloques(s, nl)
        try:
            lineas, n = [], 0
            for t in trozos:
                if isinstance(t, tuple):
                    lineas += reglas[ruta](t)
                    n += 1
                else:
                    lineas.append(t)
        except (LookupError, StopIteration) as ex:
            print(f"NO CONOZCO un bloque de {ruta} ({ex}): no lo he tocado. Resuélvelo a mano.")
            mal += 1
            continue
        nuevo = nl.join(lineas)
        if ruta.endswith("filtro_formulario.py"):
            nuevo = re.sub(r"(?m)^ANCLA_AVISO_LEGAL = .*(\r?\n)", "", nuevo)
        if ruta.endswith(".py"):                        # .gitignore y demás no son Python
            try:
                ast.parse(nuevo, feature_version=(3, 11))
            except SyntaxError as ex:
                print(f"{ruta}: la resolución no compila ({ex}); no lo he tocado.")
                mal += 1
                continue
        open(ruta, "w", encoding="utf-8", newline="").write(nuevo)
        print(f"{ruta}: {n} bloque(s) resuelto(s)")
    if mal:
        sys.exit(f"\n{mal} fichero(s) sin resolver: míralos a mano.")
    print("\nListo. Ahora: pasa las pruebas (ver «DIA DEL ALTA - pasos.txt»), luego git add -A y git commit.")


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    main()
