# encoding: utf-8
"""FRENO DEL DESPLIEGUE (08-11-2026, RGPD): Render no publica una versión de la web sin el filtro de salida de DNI/NIE.

Para que frene, Render tiene que lanzarla en la compilación (Build Command), detrás de la instalación:

    pip install -r requirements.txt && python backend/comprobar_despliegue.py

Si sale con error, la compilación falla y Render NO despliega: la versión anterior sigue en marcha, como con cualquier
fallo de compilación. Vale para TODOS los despliegues: los PR fusionados, los auto-commits de los flujos nocturnos
(que con GITHUB_TOKEN no lanzan comprobaciones de GitHub) y el «Manual Deploy». No depende de GitHub.

Por qué no la prueba entera (prueba_salida_sin_dni.py) aquí: importar la web carga todos los datos y tarda ~2 min, y la
prueba entera ~4 min; eso alargaría cada despliegue y el refresco nocturno solo espera 4 min a que la web se reinicie
(esperar_web 240 en actualizar-diario.yml). Esta comprobación NO importa la web: lee backend/app.py, tarda unos
segundos y casi no gasta memoria. La prueba entera sigue en GitHub Actions en cada PR (salida-sin-dni.yml).

Qué comprueba (si falla una sola cosa, sale con 1):
  1. El filtro existe y funciona: se sacan de app.py sus definiciones (FILTRO_SALIDA_DNI ... _filtro_salida_dni), se
     ejecutan aparte y se les pasan los casos inventados de prueba_salida_sin_dni.comprobar_filtro (DNI, NIE, «ES»
     delante, gzip, JSON; y que NO toque CIF, binarios, 206 ni respuestas por trozos) y unas trampas más.
  2. Está ENCENDIDO por defecto: sin la variable FILTRO_SALIDA_DNI, queda activo.
  3. Está en la salida única: en _app_wsgi, la línea del filtro va a nivel de la función, justo antes del único
     start_response, y no hay ningún return antes de ella; y la función app (la que sirve gunicorn) devuelve lo de
     _app_wsgi. Fuera de esas, solo puede haber start_response con un estado fijo escrito en el código (los 403/429
     de app, con un texto fijo).
Si en Render está puesta FILTRO_SALIDA_DNI=0 (el interruptor de emergencia, decisión de César), lo avisa bien a la
vista pero NO para el despliegue: así se puede desplegar el arreglo con el filtro apagado.

PRIVACIDAD: no usa red, ni claves, ni la base de datos; solo DNI inventados; no imprime ningún dato.

    python backend/comprobar_despliegue.py               (desde la raíz del repositorio o desde backend)
    python backend/comprobar_despliegue.py --app OTRO.py (otra copia de app.py; lo usa prueba_comprobar_despliegue.py)
"""
import ast
import gzip
import os
import re
import sys
import time
import types
from urllib.parse import parse_qs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# Las definiciones del filtro, de la primera a la última, tal como están en app.py.
PRIMERA = "FILTRO_SALIDA_DNI"
ULTIMA = "_filtro_salida_dni"
NECESARIAS = ("FILTRO_SALIDA_DNI", "_RE_DNI_SALIDA", "_LETRAS_DNI", "_TABLA_CIFRAS", "_TIPOS_FILTRO_SALIDA",
              "_FILTRO_SALIDA_LIMPIOS", "_FILTRO_SALIDA_ESTADO", "_dni_tapado", "enmascarar_dni_en_bytes",
              "_filtro_salida_dni")


def _nombres(nodo):
    if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {nodo.name}
    if isinstance(nodo, ast.Assign):
        return {n.id for t in nodo.targets for n in ast.walk(t) if isinstance(n, ast.Name)}
    if isinstance(nodo, (ast.AnnAssign, ast.AugAssign)) and isinstance(nodo.target, ast.Name):
        return {nodo.target.id}
    return set()


def _es_llamada(nodo, nombre):
    return (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name) and nodo.func.id == nombre)


def _filtro_aparte(arbol, fallos):
    """Ejecuta en un espacio aparte las definiciones del filtro sacadas de app.py. Devuelve el espacio o None."""
    cuerpo = arbol.body
    ini = next((i for i, n in enumerate(cuerpo) if PRIMERA in _nombres(n)), None)
    fin = next((i for i, n in enumerate(cuerpo) if ULTIMA in _nombres(n) and isinstance(n, ast.FunctionDef)), None)
    if ini is None or fin is None or fin < ini:
        fallos.append(f"no encuentro en app.py el bloque del filtro de salida ({PRIMERA} ... def {ULTIMA})")
        return None
    modulo = ast.Module(body=cuerpo[ini:fin + 1], type_ignores=[])
    espacio = {"__name__": "filtro_salida_aparte", "os": os, "re": re, "time": time, "_gzip": gzip,
               "parse_qs": parse_qs}
    entorno = os.environ.pop("FILTRO_SALIDA_DNI", None)     # para ver el valor POR DEFECTO del código
    try:
        exec(compile(modulo, "app.py (filtro de salida)", "exec"), espacio)
    except Exception as e:
        fallos.append(f"el bloque del filtro de salida no se ejecuta: {type(e).__name__}: {e}")
        return None
    finally:
        if entorno is not None:
            os.environ["FILTRO_SALIDA_DNI"] = entorno
    faltan = [n for n in NECESARIAS if n not in espacio]
    if faltan:
        fallos.append("al filtro de salida le falta: " + ", ".join(faltan))
        return None
    return espacio


def _comprobar_funcionamiento(espacio, fallos):
    from prueba_salida_sin_dni import comprobar_filtro, dni_a_la_vista, con_letra, T_TITULO, T_MENOR, T_NOMBRE
    if espacio["FILTRO_SALIDA_DNI"] is not True:
        fallos.append("el filtro de salida NO está encendido por defecto (sin la variable FILTRO_SALIDA_DNI)")
        espacio["FILTRO_SALIDA_DNI"] = True                  # para seguir comprobando el resto
    fn = espacio["_filtro_salida_dni"]
    fallos += ["filtro: " + m for m in comprobar_filtro(types.SimpleNamespace(
        _filtro_salida_dni=fn, _FILTRO_SALIDA_ESTADO=espacio["_FILTRO_SALIDA_ESTADO"]))]
    # Más trampas, en las formas que salen de verdad en los textos de PLACE (todas inventadas).
    otras = [con_letra(87654321), con_letra(1).lower(), "ES-" + con_letra(99999999), "Y" + "7654321" + "Z",
             con_letra(11223344)[:8] + " " + con_letra(11223344)[8], "Z" + "0000001" + "B"]
    otras = [o for o in otras if dni_a_la_vista(o)]          # solo las que de verdad tienen la letra correcta
    if len(otras) < 4:
        fallos.append("comprobación interna: las trampas inventadas no son DNI/NIE válidos")
    texto = " | ".join([T_TITULO, T_MENOR, T_NOMBRE] + otras)
    for tipo, comprimir in (("text/html; charset=utf-8", False), ("application/json", True), ("text/csv", False),
                            ("application/xml", True), ("text/plain", False)):
        cuerpo = ("<td>" + texto + "</td>").encode("utf-8")
        cab = {"Content-Type": tipo}
        if comprimir:
            cuerpo, cab["Content-Encoding"] = gzip.compress(cuerpo), "gzip"
        _, _, b = fn("/comprobar-despliegue", 200, cab, cuerpo)
        b = gzip.decompress(b) if comprimir else b
        if dni_a_la_vista(b.decode("utf-8", "replace")):
            fallos.append(f"filtro: queda algún DNI/NIE a la vista en una respuesta {tipo}{' en gzip' if comprimir else ''}")


def _comprobar_cableado(arbol, fallos):
    funciones = {n.name: n for n in arbol.body if isinstance(n, ast.FunctionDef)}
    wsgi, app = funciones.get("_app_wsgi"), funciones.get("app")
    if wsgi is None or app is None:
        fallos.append("no encuentro en app.py las funciones app y _app_wsgi")
        return
    # _app_wsgi: [... , code, headers, body = _filtro_salida_dni(...), ..., start_response(...), ...]
    i_filtro = next((i for i, n in enumerate(wsgi.body)
                     if isinstance(n, ast.Assign) and _es_llamada(n.value, "_filtro_salida_dni")), None)
    llamadas_sr = [n for n in ast.walk(wsgi) if _es_llamada(n, "start_response")]
    i_sr = next((i for i, n in enumerate(wsgi.body)
                 if isinstance(n, ast.Expr) and _es_llamada(n.value, "start_response")), None)
    if i_filtro is None:
        fallos.append("_app_wsgi no pasa la respuesta por _filtro_salida_dni (a nivel de la función)")
    elif len(llamadas_sr) != 1 or i_sr is None or i_sr <= i_filtro:
        fallos.append("en _app_wsgi tiene que haber UN solo start_response, después del filtro de salida")
    else:
        destino = wsgi.body[i_filtro].targets[0]
        nombres = [e.id for e in getattr(destino, "elts", []) if isinstance(e, ast.Name)]
        if nombres != ["code", "headers", "body"]:
            fallos.append("en _app_wsgi el filtro de salida no rehace (code, headers, body)")
        intermedio = wsgi.body[i_filtro + 1:i_sr]
        for n in intermedio:
            if {"code", "headers", "body"} & _nombres(n):
                fallos.append("en _app_wsgi se cambia la respuesta DESPUÉS del filtro de salida")
        lineas_filtro = wsgi.body[i_filtro].lineno
        if any(isinstance(n, ast.Return) and n.lineno < lineas_filtro for n in ast.walk(wsgi)):
            fallos.append("en _app_wsgi hay un return ANTES del filtro de salida (esa respuesta no se revisaría)")
        if any(isinstance(n, (ast.Yield, ast.YieldFrom)) for n in ast.walk(wsgi)):
            fallos.append("_app_wsgi no puede ser un generador (sus trozos no pasarían por el filtro)")
    # app: tiene que devolver lo de _app_wsgi.
    if not any(_es_llamada(n, "_app_wsgi") for n in ast.walk(app)):
        fallos.append("la función app (la de gunicorn) no llama a _app_wsgi")
    # Todo start_response del módulo con un estado que no sea un texto fijo: solo el de _app_wsgi y el reenvío de app.
    permitidos = {id(n) for n in llamadas_sr}
    reenvio = next((n for n in ast.walk(app) if isinstance(n, ast.FunctionDef)), None)
    if reenvio is not None:
        permitidos |= {id(n) for n in ast.walk(reenvio) if _es_llamada(n, "start_response")}
    for n in ast.walk(arbol):
        if _es_llamada(n, "start_response") and id(n) not in permitidos:
            fijo = n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)
            if not fijo:
                fallos.append(f"app.py, línea {n.lineno}: start_response fuera de _app_wsgi con un estado no fijo "
                              "(esa respuesta no pasaría por el filtro de salida)")


def comprobar(ruta_app):
    """Lista de fallos (vacía si todo está bien)."""
    fallos = []
    try:
        with open(ruta_app, encoding="utf-8") as f:
            arbol = ast.parse(f.read(), filename=ruta_app)
    except (OSError, SyntaxError, ValueError) as e:
        return [f"no se puede leer {ruta_app}: {type(e).__name__}: {e}"]
    espacio = _filtro_aparte(arbol, fallos)
    if espacio is not None:
        _comprobar_funcionamiento(espacio, fallos)
    _comprobar_cableado(arbol, fallos)
    return fallos


def main(argv):
    t0 = time.time()
    ruta = os.path.join(BASE_DIR, "app.py")
    if "--app" in argv:
        ruta = argv[argv.index("--app") + 1]
    try:
        fallos = comprobar(ruta)
    except Exception as e:                                   # cualquier cosa rara: mejor no desplegar
        fallos = [f"la comprobación ha fallado por dentro: {type(e).__name__}: {e}"]
    if os.environ.get("FILTRO_SALIDA_DNI", "1").strip() == "0":
        print("[privacidad] AVISO: FILTRO_SALIDA_DNI=0 en este entorno: la web se desplegará con el filtro de salida "
              "APAGADO (interruptor de emergencia). Vuelve a quitarlo en cuanto se pueda.", flush=True)
    if fallos:
        print(f"[privacidad] DESPLIEGUE PARADO: {len(fallos)} fallo(s) en el filtro de salida de DNI/NIE:", flush=True)
        for m in fallos:
            print("  - " + m, flush=True)
        print("  Render no publica esta versión; la anterior sigue en marcha. Ver backend/comprobar_despliegue.py.",
              flush=True)
        return 1
    print(f"[privacidad] filtro de salida de DNI/NIE comprobado: bien ({time.time() - t0:.1f} s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
