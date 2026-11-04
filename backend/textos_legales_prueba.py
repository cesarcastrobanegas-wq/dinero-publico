# encoding: utf-8
"""
Prueba SIN RED de los textos legales nuevos (textos_legales.py y su enrutado en app.py, 2026-11-04):
  1. el módulo: tres documentos, rutas /legal/..., marca de borrador, ninguna nota para el abogado en el texto;
  2. app.py con TEXTOS_LEGALES_NUEVOS apagado: las tres rutas dan 404;
  3. encendido: 200, <meta name="robots" content="noindex"> y cabecera X-Robots-Tag: noindex (también bajo /gl/);
  4. en los dos casos, ninguna página fija (portada, convocatorias, mapa, aviso legal, quién soy, metodología, casos,
     sitemap, robots.txt...) enlaza a /legal/, y el sitemap no las lleva.
Llama a app.app (la entrada WSGI de gunicorn) dentro del propio proceso, sin servidor. Cada caso arranca en un proceso
aparte, uno detrás de otro (la variable se lee al importar), con un DATA_DIR TEMPORAL que solo tiene un cache.db VACÍO
recién creado: nunca el de producción. Sin RESEND_API_KEY y sin hilos de fondo.
Uso: python backend/textos_legales_prueba.py
"""
import io
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
RUTAS = ("/legal/aviso-legal", "/legal/privacidad", "/legal/condiciones")
FIJAS = ("/", "/convocatorias", "/mapa-cobertura", "/aviso-legal", "/quien-soy", "/metodologia", "/casos",
         "/rankings", "/fondos-ue", "/entidades", "/sitemap.xml", "/robots.txt", "/no-existe-esta-pagina")
OBLIGATORIAS = ("/", "/aviso-legal", "/quien-soy", "/sitemap.xml", "/robots.txt")
_RE_ENLACE_LEGAL = re.compile(r"""(?:href|action|src)\s*=\s*["'][^"']*/legal/|<loc>[^<]*/legal/|llow:\s*/legal/""")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def ok(fallos, modo, cond, txt):
    print(f"[{modo}] " + ("OK   " if cond else "FALLO") + " " + txt, flush=True)
    if not cond:
        fallos.append(txt)


def prueba_modulo():
    sys.path.insert(0, AQUI)
    import textos_legales as T
    fallos = []
    ok(fallos, "modulo", set(T.RUTAS) == set(RUTAS), f"tres rutas /legal/ ({sorted(T.RUTAS)})")
    for clave, doc in T.DOCUMENTOS.items():
        cuerpo = T.cuerpo_html(clave)
        ok(fallos, "modulo", T.MARCA_BORRADOR in cuerpo, f"{clave}: lleva la marca de borrador")
        ok(fallos, "modulo", "Notas para el abogado" not in cuerpo and "NOTAS PARA EL ABOGADO" not in cuerpo,
           f"{clave}: sin notas para el abogado")
        ok(fallos, "modulo", "/legal/" not in cuerpo, f"{clave}: no enlaza a otras páginas /legal/")
        ok(fallos, "modulo", len(doc["bloques"]) > 10 and doc["bloques"][0][0] == "h2", f"{clave}: tiene contenido")
        ok(fallos, "modulo", cuerpo.count("<mark") == cuerpo.count("</mark>") > 0, f"{clave}: huecos resaltados")
    # ningún nombre propio de persona física: el titular va como hueco
    todo = " ".join(str(b) for d in T.DOCUMENTOS.values() for b in d["bloques"])
    ok(fallos, "modulo", "[NOMBRE Y APELLIDOS O RAZÓN SOCIAL DEL TITULAR]" in todo, "el titular va como hueco")
    ok(fallos, "modulo", "Castro" not in todo and "Banegas" not in todo, "sin el nombre del titular escrito")
    # app.py: el literal /legal/ solo aparece en comentarios (el enrutado va por textos_legales.RUTAS)
    with open(os.path.join(AQUI, "app.py"), encoding="utf-8") as f:
        lineas = [l for l in f if "/legal/" in l and not l.lstrip().startswith("#")]
    ok(fallos, "modulo", not lineas, f"app.py no escribe /legal/ fuera de comentarios ({lineas[:2]})")
    return fallos


def caso(modo):
    """Proceso hijo: importa la app con la variable del modo y pide las páginas."""
    sys.path.insert(0, AQUI)
    os.chdir(AQUI)
    from wsgiref.util import setup_testing_defaults
    import app  # noqa: E402
    fallos = []

    def get(ruta):
        env = {"REQUEST_METHOD": "GET", "PATH_INFO": ruta, "QUERY_STRING": "", "wsgi.input": io.BytesIO(b""),
               "HTTP_USER_AGENT": "Mozilla/5.0 (prueba textos legales)"}
        setup_testing_defaults(env)
        estado = {}

        def start(s, h, e=None):
            estado.update(s=s, h=dict(h))
        cuerpo = b"".join(app.app(env, start))
        return int(estado["s"].split()[0]), estado["h"], cuerpo.decode("utf-8", "replace")

    encendido = modo == "encendido"
    ok(fallos, modo, app.TEXTOS_LEGALES_NUEVOS == encendido, f"TEXTOS_LEGALES_NUEVOS = {app.TEXTOS_LEGALES_NUEVOS}")
    for ruta in RUTAS + tuple("/gl" + r for r in RUTAS):
        c, h, b = get(ruta)
        if not encendido:
            ok(fallos, modo, c == 404, f"{ruta}: 404 ({c})")
            ok(fallos, modo, "BORRADOR PARA REVISIÓN" not in b, f"{ruta}: no enseña el texto")
            continue
        ok(fallos, modo, c == 200, f"{ruta}: 200 ({c})")
        ok(fallos, modo, '<meta name="robots" content="noindex">' in b, f"{ruta}: meta robots noindex")
        ok(fallos, modo, 'content="index, follow"' not in b, f"{ruta}: sin «index, follow»")
        ok(fallos, modo, "noindex" in h.get("X-Robots-Tag", ""), f"{ruta}: cabecera X-Robots-Tag noindex")
        ok(fallos, modo, "BORRADOR PARA REVISIÓN JURÍDICA" in b, f"{ruta}: marca de borrador visible")
        ok(fallos, modo, "Notas para el abogado" not in b, f"{ruta}: sin notas para el abogado")
    for ruta in FIJAS:
        c, h, b = get(ruta)
        if ruta in OBLIGATORIAS:
            ok(fallos, modo, c == 200, f"{ruta}: responde 200 ({c})")
        elif c != 200:
            print(f"[{modo}] aviso {ruta}: {c} con la base vacía (no cuenta como fallo)", flush=True)
        ok(fallos, modo, not _RE_ENLACE_LEGAL.search(b), f"{ruta}: ningún enlace a /legal/")
    return fallos


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--caso":
        fallos = caso(sys.argv[2])
        print(f"[{sys.argv[2]}] FALLOS: {len(fallos)}", flush=True)
        sys.exit(1 if fallos else 0)
    total = len(prueba_modulo())
    for modo, extra in (("apagado", {}), ("encendido", {"TEXTOS_LEGALES_NUEVOS": "1"})):
        datos = tempfile.mkdtemp(prefix=f"textos_legales_{modo}_")
        sqlite3.connect(os.path.join(datos, "cache.db")).close()          # cache.db VACÍO, nunca el real
        open(os.path.join(datos, ".disco_inicializado"), "w").close()
        env = {k: v for k, v in os.environ.items() if k not in (
            "RESEND_API_KEY", "TEXTOS_LEGALES_NUEVOS", "FILTRO_FORMULARIO", "ALERTAS_ACTIVAS", "FILTRO_EMBUDO",
            "ADMIN_TOKEN", "I18N_PUBLICADOS")}
        env.update(extra, DATA_DIR=datos, DINERO_HILOS_EN_POST_FORK="1", PYTHONIOENCODING="utf-8")
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "--caso", modo], env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        lineas = [l for l in r.stdout.splitlines() if l.startswith(f"[{modo}]")]
        print("\n".join(lineas), flush=True)
        if r.returncode and not any("FALLOS:" in l for l in lineas):          # se cayó: enseñar el error
            print(r.stdout[-1500:] + r.stderr[-3000:], flush=True)
        total += 0 if r.returncode == 0 else 1
        shutil.rmtree(datos, ignore_errors=True)
    print(f"\nFALLOS (módulo) + CASOS CON FALLOS: {total}")
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
