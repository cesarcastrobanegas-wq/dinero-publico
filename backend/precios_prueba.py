# encoding: utf-8
"""
Prueba de la página de precios (/precios, 2026-11-04), SIN RED.
  1) precios.py a secas (instantáneo): precios ausentes = «Consultar», escape HTML, periodos, nota del IVA, contacto.
  2) La web (si se pasa CARPETA_DATOS): llama a app.app (la entrada WSGI de gunicorn) dentro de un proceso hijo, con
     una COPIA temporal de esa carpeta como DATA_DIR, sin RESEND_API_KEY y sin arrancar hilos. Apagada (sin
     PRECIOS_VISIBLE): 404 en /precios y en /gl/, /ca/, /eu/. Encendida (la prueba cambia app.PRECIOS_VISIBLE en ese
     proceso, nada más): 200, noindex, los 3 planes, fuera del sitemap y sin enlaces en el código.
Uso: python backend/precios_prueba.py [CARPETA_DATOS]
  CARPETA_DATOS: una carpeta de datos de PRUEBA (con su cache.db, o vacía: la app crea una); nunca la de producción.
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
import precios as PR  # noqa: E402

VARIABLES = ("PRECIOS_VISIBLE", "PRECIO_ALERTAS", "PRECIO_FILTRO", "PRECIO_INFORME", "PRECIO_ALERTAS_PERIODO",
             "PRECIO_FILTRO_PERIODO", "PRECIO_INFORME_PERIODO", "PRECIOS_NOTA_IVA", "PRECIOS_CONTACTO")
fallos = []


def ok(cond, txt, grupo="modulo"):
    print(f"[{grupo}] " + ("OK   " if cond else "FALLO") + " " + txt, flush=True)
    if not cond:
        fallos.append(txt)


def prueba_modulo():
    h = PR.cuerpo_html({})
    ok(h.count('class="precio-plan"') == 3, "tres planes")
    for t in ("Alertas básicas", "Filtro de licitaciones", "Informe a medida"):
        ok(t in h, f"sale «{t}»")
    ok(h.count('<div class="precio">Consultar</div>') == 3, "sin variables: los tres dicen «Consultar»")
    ok("€" not in h, "sin variables no se inventa ningún precio")
    ok("IVA no incluido" in h, "nota del IVA por defecto")
    ok(h.count("Próximamente") == 3 and "mailto:" not in h, "sin contacto: «Próximamente» y ningún mailto")
    ok("<form" not in h and "<input" not in h, "ningún formulario")
    ok("Puede optar" in h and "Revisa el pliego" in h and "Solo en UTE" in h, "filtro: los tres grupos")
    ok("10 alertas" in h and "diario" in h, "alertas: 10 alertas y aviso diario (nivel «pago» de alertas.py)")

    h = PR.cuerpo_html({"PRECIO_ALERTAS": "9", "PRECIO_FILTRO": "29,90 €", "PRECIO_FILTRO_PERIODO": "año"})
    ok("9 € <small>/mes</small>" in h, "número suelto: « €» y /mes por defecto")
    ok("29,90 € <small>/año</small>" in h, "periodo «año» = /año")
    ok(h.count('<div class="precio">Consultar</div>') == 1, "el informe sin precio sigue en «Consultar»")

    h = PR.cuerpo_html({"PRECIO_INFORME": "<script>alert(1)</script>", "PRECIO_INFORME_PERIODO": "cada siglo"})
    ok("<script>" not in h and "&lt;script&gt;alert(1)&lt;/script&gt;" in h, "precio con HTML: escapado")
    ok("<small>por informe</small>" in h, "periodo desconocido: el de por defecto del plan")
    h = PR.cuerpo_html({"PRECIO_ALERTAS": '"><b>x</b>', "PRECIO_FILTRO": "   ", "PRECIO_INFORME": "x" * 500})
    ok("<b>x</b>" not in h and "&quot;&gt;&lt;b&gt;" in h, "comillas y etiquetas escapadas")
    ok(h.count('<div class="precio">Consultar</div>') == 1, "precio solo con espacios = «Consultar»")
    ok("x" * 41 not in h and "x" * 40 in h, "precio larguísimo recortado a 40 caracteres")
    ok(PR._periodo({"P": " POR INFORME "}, "P", "/mes") == "por informe", "periodo sin distinguir mayúsculas")

    ok(PR.cuerpo_html({"PRECIOS_NOTA_IVA": ""}).count("precios-nota") == 0, "nota vacía: sin nota")
    h = PR.cuerpo_html({"PRECIOS_NOTA_IVA": "IVA <21%> incluido"})
    ok("IVA &lt;21%&gt; incluido" in h and "IVA no incluido" not in h, "nota propia, escapada")

    h = PR.cuerpo_html({"PRECIOS_CONTACTO": "ventas@ejemplo.test"})
    ok(h.count('href="mailto:ventas@ejemplo.test?subject=Plan%20') == 3 and "Próximamente" not in h,
       "con contacto: «Escríbenos» con mailto en los tres")
    for raro in ('x@y.test"><script>', "no-es-un-correo", "a@b", "javascript:alert(1)"):
        h = PR.cuerpo_html({"PRECIOS_CONTACTO": raro})
        ok("mailto:" not in h and h.count("Próximamente") == 3, f"contacto no válido ({raro!r}): «Próximamente»")


def caso_web(datos):
    """En el proceso hijo."""
    os.chdir(AQUI)
    from wsgiref.util import setup_testing_defaults
    import app  # noqa: E402

    def get(ruta):
        env = {"REQUEST_METHOD": "GET", "PATH_INFO": ruta, "QUERY_STRING": ""}
        setup_testing_defaults(env)
        estado = {}
        cuerpo = b"".join(app.app(env, lambda s, h, e=None: estado.update(s=s, h=dict(h))))
        return int(estado["s"].split()[0]), estado["h"], cuerpo.decode("utf-8", "replace")

    rutas = ("/precios", "/precios/", "/gl/precios", "/ca/precios", "/eu/precios", "/gl/precios/")
    ok(app.PRECIOS_VISIBLE is False, "sin PRECIOS_VISIBLE la variable está apagada", "web")
    for r in rutas:
        c, _, _ = get(r)
        ok(c == 404, f"apagada: {r} -> 404 ({c})", "web")

    app.PRECIOS_VISIBLE = True                                  # solo en este proceso de prueba
    for r in rutas:
        c, h, b = get(r)
        ok(c == 200, f"encendida: {r} -> 200 ({c})", "web")
        ok('<meta name="robots" content="noindex">' in b and 'content="index, follow"' not in b
           and "noindex" in h.get("X-Robots-Tag", ""), f"encendida: {r} con noindex (etiqueta y cabecera)", "web")
        ok(b.count('class="precio-plan"') == 3 and b.count(">Consultar<") == 3, f"encendida: {r} 3 planes, «Consultar»",
           "web")
    os.environ["PRECIO_FILTRO"] = "<i>19</i>"
    os.environ["PRECIOS_CONTACTO"] = "ventas@ejemplo.test"
    c, _, b = get("/precios")
    ok("&lt;i&gt;19&lt;/i&gt;" in b and "<i>19</i>" not in b, "precio con HTML desde el entorno: escapado", "web")
    ok(b.count(">Consultar<") == 2 and "mailto:ventas@ejemplo.test" in b, "las variables se leen en cada petición",
       "web")
    c, _, b = get("/sitemap.xml")
    ok(c == 200 and "precios" not in b, f"fuera del sitemap ({c})", "web")
    fuente = io.open(os.path.join(AQUI, "app.py"), encoding="utf-8").read()
    ok('href="/precios' not in fuente and "href='/precios" not in fuente, "ninguna página enlaza /precios", "web")


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--web":
        caso_web(sys.argv[2])
        print(f"[web] FALLOS: {len(fallos)}", flush=True)
        sys.exit(1 if fallos else 0)
    prueba_modulo()
    total = len(fallos)
    if len(sys.argv) == 2:
        if not os.path.isdir(sys.argv[1]):
            sys.exit(__doc__)
        datos = tempfile.mkdtemp(prefix="precios_web_")
        for nombre in os.listdir(sys.argv[1]):
            origen = os.path.join(sys.argv[1], nombre)
            if os.path.isfile(origen) and not nombre.endswith(("-shm", "-wal")):
                shutil.copy2(origen, datos)
        env = {k: v for k, v in os.environ.items() if k not in VARIABLES + ("RESEND_API_KEY",)}
        env.update(DATA_DIR=datos, DINERO_HILOS_EN_POST_FORK="1", PYTHONIOENCODING="utf-8")
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "--web", datos], env=env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        lineas = [l for l in r.stdout.splitlines() if l.startswith("[web]")]
        print("\n".join(lineas), flush=True)
        if r.returncode and not any("FALLOS:" in l for l in lineas):
            print(r.stdout[-1500:] + r.stderr[-3000:], flush=True)
        total += 0 if r.returncode == 0 else 1
        shutil.rmtree(datos, ignore_errors=True)
    print(f"\nFALLOS: {total}")
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
