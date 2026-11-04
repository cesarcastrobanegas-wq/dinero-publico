# encoding: utf-8
"""
Prueba SIN RED de los textos legales nuevos (textos_legales.py y su enrutado en app.py, 2026-11-04):
  1. el módulo: tres documentos, rutas /legal/..., marca de borrador, ninguna nota para el abogado en el texto;
  2. app.py con TEXTOS_LEGALES_NUEVOS apagado: las tres rutas dan 404;
  3. encendido: 200, <meta name="robots" content="noindex"> y cabecera X-Robots-Tag: noindex (también bajo /gl/);
  4. versiones: la foto de la versión vigente está guardada y al día, /legal/condiciones?v=<versión> enseña esa
     versión exacta (también una antigua inventada), versión desconocida o nombre raro: 404;
  5. en los dos casos, ninguna página fija (portada, convocatorias, mapa, aviso legal, quién soy, metodología, casos,
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
        otros = [u for u in re.findall(r'href="(/legal/[^"?]*)', cuerpo) if u != doc["ruta"]]
        ok(fallos, "modulo", not otros, f"{clave}: no enlaza a otras páginas /legal/ ({otros[:2]})")
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
    fallos += prueba_versiones(T)
    return fallos


def prueba_versiones(T):
    """Versiones: la actual guardada y al día; ?v= de una antigua la enseña tal cual; nombres raros, None."""
    import json
    fallos = []
    v = T.VERSION_ID
    ok(fallos, "modulo", T.version_al_dia(), f"la foto de la versión {v} está guardada y al día "
       "(si falla: python backend/textos_legales.py --guardar-version)")
    ok(fallos, "modulo", T.enlace_version("condiciones") == f"/legal/condiciones?v={v}", "enlace a la versión exacta")
    for clave in T.VERSIONADOS:
        c = T.cuerpo_html(clave, v)
        ok(fallos, "modulo", c is not None and f"versión «{v}»" in c and "version-antigua" not in c,
           f"{clave}?v={v}: la vigente, con su versión a la vista")
    for raro in ("no-existe", "../textos_legales", "..", "A B", "x" * 90, ""):
        ok(fallos, "modulo", T.version_guardada(raro) is None, f"version_guardada({raro[:12]!r}) = None")
    ok(fallos, "modulo", T.cuerpo_html("condiciones", "no-existe") is None, "versión que no existe: None (404)")
    ok(fallos, "modulo", T.cuerpo_html("aviso-legal", v) is None, "el aviso legal no tiene versiones: None (404)")
    # una versión antigua inventada, en una carpeta temporal: sigue publicada tal cual se aceptó
    real, tmp = T.DIR_VERSIONES, tempfile.mkdtemp(prefix="textos_legales_versiones_")
    try:
        T.DIR_VERSIONES = tmp
        ok(fallos, "modulo", T.guardar_version() == "guardada" and T.version_al_dia(), "guardar_version() guarda")
        ok(fallos, "modulo", T.guardar_version() == "sin cambios", "guardar_version() sin cambios no reescribe")
        foto = T.version_guardada(v)
        foto["version"], foto["borrador"] = "2025-01-01", False
        foto["documentos"]["condiciones"]["bloques"][1][1] = "TEXTO ANTIGUO QUE SE ACEPTÓ"
        with open(os.path.join(tmp, "2025-01-01.json"), "w", encoding="utf-8") as f:
            json.dump(foto, f, ensure_ascii=False)
        antigua = T.cuerpo_html("condiciones", "2025-01-01")
        ok(fallos, "modulo", antigua is not None and "TEXTO ANTIGUO QUE SE ACEPTÓ" in antigua
           and "version-antigua" in antigua and 'href="/legal/condiciones"' in antigua
           and T.MARCA_BORRADOR not in antigua, "versión antigua: su texto, aviso y enlace a la vigente")
        vigente = T.cuerpo_html("condiciones")
        ok(fallos, "modulo", "TEXTO ANTIGUO" not in vigente and 'href="/legal/condiciones?v=2025-01-01"' in vigente,
           "la vigente enlaza a la versión anterior")
        ok(fallos, "modulo", T.cuerpo_html("privacidad", "2025-01-01") is not None, "privacidad antigua publicada")
        # publicada (no borrador) y con otro texto: no se sobrescribe nunca
        borr = T.BORRADOR
        try:
            T.BORRADOR = False
            foto2 = T.version_guardada(v)
            foto2["borrador"] = False
            foto2["documentos"]["privacidad"]["bloques"][1][1] = "OTRO"
            with open(os.path.join(tmp, v + ".json"), "w", encoding="utf-8") as f:
                json.dump(foto2, f, ensure_ascii=False)
            try:
                T.guardar_version()
                ok(fallos, "modulo", False, "una versión publicada no se sobrescribe")
            except SystemExit:
                ok(fallos, "modulo", "OTRO" in open(os.path.join(tmp, v + ".json"), encoding="utf-8").read(),
                   "una versión publicada no se sobrescribe")
        finally:
            T.BORRADOR = borr
    finally:
        T.DIR_VERSIONES = real
        shutil.rmtree(tmp, ignore_errors=True)
    return fallos


def caso(modo):
    """Proceso hijo: importa la app con la variable del modo y pide las páginas."""
    sys.path.insert(0, AQUI)
    os.chdir(AQUI)
    from wsgiref.util import setup_testing_defaults
    import app  # noqa: E402
    fallos = []

    def get(ruta):
        ruta, _, query = ruta.partition("?")
        env = {"REQUEST_METHOD": "GET", "PATH_INFO": ruta, "QUERY_STRING": query, "wsgi.input": io.BytesIO(b""),
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
    import textos_legales as T
    v = T.VERSION_ID
    for ruta, esperado in ((f"/legal/condiciones?v={v}", 200), (f"/legal/privacidad?v={v}", 200),
                           (f"/gl/legal/condiciones?v={v}", 200), ("/legal/condiciones?v=no-existe", 404),
                           ("/legal/condiciones?v=../../app", 404), (f"/legal/aviso-legal?v={v}", 404)):
        c, h, b = get(ruta)
        if not encendido:
            ok(fallos, modo, c == 404, f"{ruta}: 404 ({c})")
            continue
        ok(fallos, modo, c == esperado, f"{ruta}: {esperado} ({c})")
        if esperado == 200:
            ok(fallos, modo, f"versión «{v}»" in b and "noindex" in h.get("X-Robots-Tag", ""),
               f"{ruta}: enseña la versión y noindex")
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
