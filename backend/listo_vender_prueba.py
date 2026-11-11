# encoding: utf-8
"""
Prueba SIN RED del modo «listo para vender» (2026-11-04): enlaces del pie y redirección del aviso legal.

  apagado   (sin PRECIOS_VISIBLE ni TEXTOS_LEGALES_NUEVOS): el pie, el aviso de cookies, /aviso-legal y el sitemap como
            siempre; ninguna página enlaza a /precios ni a /legal/.
            Con --comparar-con <carpeta backend de otra copia> compara además, byte a byte, las páginas fijas con las
            de esa copia (p. ej. origin/main): «la web queda exactamente como hoy».
  encendido (PRECIOS_VISIBLE=1, TEXTOS_LEGALES_NUEVOS=1 y TITULAR_* de prueba): el pie enlaza a Precios, Aviso legal
            nuevo, Privacidad, Condiciones y Cookies; /aviso-legal redirige (302) a /legal/aviso-legal, también bajo
            /gl/; /aviso-legal fuera del sitemap. Si la copia tiene ya los PR #19 y #20 (prueba de integración), además:
            /precios y los textos nuevos responden 200 y llevan los datos del titular sin corchetes.
Cada modo arranca en un proceso aparte (las variables se leen al importar) con un DATA_DIR TEMPORAL que solo tiene un
cache.db VACÍO. Sin RESEND_API_KEY ni hilos de fondo.
Uso: python backend/listo_vender_prueba.py [--comparar-con RUTA\\backend]
"""
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
FIJAS = ("/", "/convocatorias", "/aviso-legal", "/quien-soy", "/metodologia", "/casos", "/rankings", "/fondos-ue",
         "/mapa-cobertura", "/sitemap.xml", "/robots.txt", "/gl/", "/gl/aviso-legal", "/ca/quien-soy")
TITULAR_PRUEBA = {"TITULAR_NOMBRE": "EMPRESA DE PRUEBA SL", "TITULAR_NIF": "B00000000",
                  "TITULAR_DOMICILIO": "Calle de la Prueba 1, 30001 Murcia", "TITULAR_REGISTRO": "no"}
VARIABLES = ("PRECIOS_VISIBLE", "TEXTOS_LEGALES_NUEVOS", "RESEND_API_KEY", "FILTRO_FORMULARIO", "FILTRO_EMBUDO",
             "ALERTAS_ACTIVAS", "ADMIN_TOKEN", "I18N_PUBLICADOS", "FORMA_PAGO", "PRECIOS_CONTACTO")
PIE_HOY = ('<a href="/aviso-legal">Aviso Legal</a>\n    <a href="#" id="cookie-preferencias">')
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def ok(fallos, modo, cond, txt):
    print(f"[{modo}] " + ("OK   " if cond else "FALLO") + " " + txt, flush=True)
    if not cond:
        fallos.append(txt)


def _cliente(carpeta):
    sys.path.insert(0, carpeta)
    os.chdir(carpeta)
    from wsgiref.util import setup_testing_defaults
    import app  # noqa: E402

    def get(ruta):
        ruta, _, query = ruta.partition("?")
        env = {"REQUEST_METHOD": "GET", "PATH_INFO": ruta, "QUERY_STRING": query, "wsgi.input": io.BytesIO(b""),
               "HTTP_USER_AGENT": "Mozilla/5.0 (prueba listo para vender)"}
        setup_testing_defaults(env)
        estado = {}
        cuerpo = b"".join(app.app(env, lambda s, h, e=None: estado.update(s=s, h=dict(h))))
        return int(estado["s"].split()[0]), estado["h"], cuerpo.decode("utf-8", "replace")
    return app, get


_RE_T_JS = re.compile(r"window\.__T__=(\{.*?\});window\.__LP__=", re.S)


def _normalizar(cuerpo):
    """El diccionario de traducciones para el navegador (window.__T__, bajo /gl/, /ca/, /eu/) sale en un orden que cambia
    en cada arranque (viene de un set): se compara ordenado. Nada más se toca."""
    def ordenar(m):
        try:
            return ("window.__T__=" + json.dumps(json.loads(m.group(1)), ensure_ascii=False, sort_keys=True)
                    + ";window.__LP__=")
        except ValueError:
            return m.group(0)
    return _RE_T_JS.sub(ordenar, cuerpo)


def volcar(carpeta, salida):
    """Proceso hijo: guarda en `salida` (JSON) el código y el cuerpo de las páginas fijas de la copia `carpeta`."""
    _, get = _cliente(carpeta)
    datos = {}
    for r in FIJAS:
        c, h, b = get(r)
        datos[r] = [c, h.get("Location", ""), _normalizar(b)]
    with open(salida, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False)


def caso(modo):
    app, get = _cliente(AQUI)
    fallos = []
    encendido = modo == "encendido"
    ok(fallos, modo, app._VENTA_PRECIOS == encendido and app._VENTA_TEXTOS_LEGALES == encendido,
       f"variables leídas al arrancar ({app._VENTA_PRECIOS}, {app._VENTA_TEXTOS_LEGALES})")
    c, h, portada = get("/")
    ok(fallos, modo, c == 200, f"/: 200 ({c})")
    c, h, sitemap = get("/sitemap.xml")
    ok(fallos, modo, c == 200, f"/sitemap.xml: 200 ({c})")
    if not encendido:
        ok(fallos, modo, PIE_HOY in portada, "el pie como siempre: «Aviso Legal» -> /aviso-legal y nada más detrás")
        ok(fallos, modo, '— <a href="/aviso-legal">más información</a>' in portada, "aviso de cookies -> /aviso-legal")
        c, h, b = get("/aviso-legal")
        ok(fallos, modo, c == 200 and "Aviso Legal" in b, f"/aviso-legal: el de siempre, 200 ({c})")
        ok(fallos, modo, "/aviso-legal</loc>" in sitemap, "/aviso-legal sigue en el sitemap")
        for r in FIJAS:
            c, h, b = get(r)
            ok(fallos, modo, 'href="/precios' not in b and not re.search(r'href="(?:/(?:gl|ca|eu))?/legal/', b),
               f"{r}: ningún enlace a /precios ni a /legal/ ({c})")
        return fallos
    for href, texto in (("/legal/aviso-legal", "Aviso Legal"), ("/legal/privacidad", "Privacidad"),
                        ("/legal/condiciones", "Condiciones de contratación"),
                        ("/legal/privacidad#cookies", "Cookies"), ("/precios", "Precios")):
        ok(fallos, modo, f'<a href="{href}">{texto}</a>' in portada, f"pie: «{texto}» -> {href}")
    ok(fallos, modo, 'href="/aviso-legal"' not in portada, "la portada ya no enlaza al aviso legal viejo")
    ok(fallos, modo, '<a href="/legal/privacidad#cookies">más información</a>' in portada,
       "aviso de cookies -> /legal/privacidad#cookies")
    c, h, gl = get("/gl/")
    ok(fallos, modo, '<a href="/gl/legal/privacidad">Privacidade</a>' in gl and '<a href="/gl/precios">Prezos</a>' in gl,
       "pie en gallego: enlaces con /gl/ y traducidos")
    for r, destino in (("/aviso-legal", "/legal/aviso-legal"), ("/gl/aviso-legal", "/gl/legal/aviso-legal"),
                       ("/eu/aviso-legal", "/eu/legal/aviso-legal")):
        c, h, b = get(r)
        ok(fallos, modo, c == 302 and h.get("Location") == destino and "no-store" in h.get("Cache-Control", ""),
           f"{r}: 302 -> {destino} ({c}, {h.get('Location')})")
    ok(fallos, modo, "/aviso-legal</loc>" not in sitemap and "/legal/" not in sitemap and "/precios" not in sitemap,
       "sitemap: sin /aviso-legal (redirige) y sin las páginas noindex")
    integracion = os.path.exists(os.path.join(AQUI, "textos_legales.py")) and os.path.exists(
        os.path.join(AQUI, "precios.py"))
    print(f"[{modo}] {'integración: con los PR #19 y #20' if integracion else 'sin los PR #19 y #20 (solo el pie)'}",
          flush=True)
    if integracion:
        huecos = ("[NOMBRE Y APELLIDOS O RAZÓN SOCIAL DEL TITULAR]", "[NIF DEL TITULAR]", "[DOMICILIO]",
                  "[DATOS DE INSCRIPCIÓN EN UN REGISTRO PÚBLICO, SI PROCEDEN]")
        for r in ("/legal/aviso-legal", "/legal/privacidad", "/legal/condiciones", "/gl/legal/aviso-legal"):
            c, h, b = get(r)
            ok(fallos, modo, c == 200 and not any(x in b for x in huecos) and "faltan datos del titular" not in b,
               f"{r}: 200 y datos del titular sin corchetes ({c})")
        c, h, b = get("/legal/aviso-legal")
        ok(fallos, modo, "EMPRESA DE PRUEBA SL" in b and "B00000000" in b and "Calle de la Prueba 1" in b,
           "aviso legal nuevo: nombre, NIF y domicilio de las variables")
        c, h, b = get("/precios")
        ok(fallos, modo, c == 200 and 'class="precio-plan"' in b, f"/precios: 200 ({c})")
        for r in FIJAS:
            c, h, b = get(r)
            if c == 200:
                rotos = [u for u in re.findall(r'href="((?:/(?:gl|ca|eu))?/(?:legal/[^"#?]*|precios))', b)
                         if get(u)[0] != 200]
                ok(fallos, modo, not rotos, f"{r}: los enlaces de venta funcionan ({rotos[:2]})")
    return fallos


def _hijo(args, extra):
    datos = tempfile.mkdtemp(prefix="listo_vender_")
    sqlite3.connect(os.path.join(datos, "cache.db")).close()          # cache.db VACÍO, nunca el real
    open(os.path.join(datos, ".disco_inicializado"), "w").close()
    env = {k: v for k, v in os.environ.items() if k not in VARIABLES and not k.startswith(("TITULAR_", "PRECIO_"))}
    env.update(extra, DATA_DIR=datos, DINERO_HILOS_EN_POST_FORK="1", PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, os.path.abspath(__file__)] + args, env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    shutil.rmtree(datos, ignore_errors=True)
    return r


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--caso":
        fallos = caso(sys.argv[2])
        print(f"[{sys.argv[2]}] FALLOS: {len(fallos)}", flush=True)
        sys.exit(1 if fallos else 0)
    if len(sys.argv) == 4 and sys.argv[1] == "--volcar":
        volcar(sys.argv[2], sys.argv[3])
        sys.exit(0)
    total = 0
    for modo, extra in (("apagado", {}), ("encendido", dict(TITULAR_PRUEBA, PRECIOS_VISIBLE="1",
                                                             TEXTOS_LEGALES_NUEVOS="1"))):
        r = _hijo(["--caso", modo], extra)
        lineas = [l for l in r.stdout.splitlines() if l.startswith(f"[{modo}]")]
        print("\n".join(lineas), flush=True)
        if r.returncode and not any("FALLOS:" in l for l in lineas):
            print(r.stdout[-1500:] + r.stderr[-3000:], flush=True)
        total += 0 if r.returncode == 0 else 1
    if len(sys.argv) == 3 and sys.argv[1] == "--comparar-con":
        otra = os.path.abspath(sys.argv[2])
        tmp = tempfile.mkdtemp(prefix="listo_vender_cmp_")
        volcados = []
        for carpeta in (AQUI, otra):
            salida = os.path.join(tmp, f"{len(volcados)}.json")
            r = _hijo(["--volcar", carpeta, salida], {})
            if r.returncode:
                print(r.stdout[-1500:] + r.stderr[-3000:], flush=True)
            volcados.append(json.load(open(salida, encoding="utf-8")) if os.path.exists(salida) else {})
        fallos = []
        for ruta in FIJAS:
            a, b = volcados[0].get(ruta), volcados[1].get(ruta)
            ok(fallos, "comparar", a is not None and a == b,
               f"{ruta}: igual que en {otra} ({a[0] if a else '-'}, {len(a[2]) if a else 0} bytes)")
            if a and b and a != b:
                import difflib
                dif = [l for l in difflib.unified_diff(b[2].splitlines(), a[2].splitlines(), lineterm="", n=0)
                       if l[:1] in "+-" and l[:3] not in ("+++", "---")]
                print("\n".join("    " + l[:300] for l in dif[:6]), flush=True)
        shutil.rmtree(tmp, ignore_errors=True)
        total += len(fallos)
    print(f"\nCASOS CON FALLOS + DIFERENCIAS: {total}")
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
