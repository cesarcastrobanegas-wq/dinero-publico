# encoding: utf-8
"""
Prueba SIN RED del titular de la web (20-11-2026, wip/titular-slu): hoy la persona; con las variables TITULAR_* de la
sociedad (S.L.U.), la sociedad. Datos INVENTADOS y claramente ficticios («Ejemplo Datos S.L.U.», B00000000).

  apagado     sin TITULAR_*: la web como hoy. Con --comparar-con <carpeta backend de una copia de origin/main> compara
              además, byte a byte, las páginas con las de esa copia: «exactamente como hoy».
  incompleto  TITULAR_* sin el registro mercantil (o con un NIF que no vale): igual que apagado, y lo dice el registro.
  encendido   las cuatro TITULAR_* de la sociedad: el aviso legal de siempre dice que la titular es la sociedad (NIF,
              domicilio social y datos registrales) y ya no la persona; la cuenta de las donaciones va a nombre de la
              sociedad; «Quién soy» sigue siendo la página del fundador pero dice que la web es de la sociedad y ya no
              que «no hay una organización detrás»; el JSON-LD lleva legalName y taxID. En los cuatro idiomas.
Cada modo arranca en un proceso aparte (las variables se leen al importar) con un DATA_DIR TEMPORAL que solo tiene un
cache.db VACÍO. Uso: python backend/prueba_titular_slu.py [--comparar-con RUTA\\backend]
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
PAGINAS = ("/", "/aviso-legal", "/quien-soy", "/gl/aviso-legal", "/gl/quien-soy", "/ca/aviso-legal", "/ca/quien-soy",
           "/eu/aviso-legal", "/eu/quien-soy", "/convocatorias", "/casos", "/metodologia", "/sitemap.xml")
SOCIEDAD = {"TITULAR_NOMBRE": "Ejemplo Datos S.L.U.", "TITULAR_NIF": "B00000000",
            "TITULAR_DOMICILIO": "Calle Inventada 1, 30001 Murcia",
            "TITULAR_REGISTRO": "Registro Mercantil de Murcia, tomo 0000, folio 0, hoja MU-00000, inscripción 1.ª",
            "DONACIONES_IBAN": "ES00 0000 0000 0000 0000 0000"}
VARIABLES = ("RESEND_API_KEY", "FILTRO_FORMULARIO", "FILTRO_EMBUDO", "ALERTAS_ACTIVAS", "ADMIN_TOKEN", "I18N_PUBLICADOS",
             "TEXTOS_LEGALES_NUEVOS", "PRECIOS_VISIBLE", "DONACIONES_IBAN", "DONACIONES_BIZUM")
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
    salida, sys.stdout = sys.stdout, io.StringIO()       # la carga de la web escribe mucho
    try:
        import app  # noqa: E402
    finally:
        registro, sys.stdout = sys.stdout.getvalue(), salida

    def get(ruta):
        ruta, _, query = ruta.partition("?")
        env = {"REQUEST_METHOD": "GET", "PATH_INFO": ruta, "QUERY_STRING": query, "wsgi.input": io.BytesIO(b""),
               "HTTP_USER_AGENT": "Mozilla/5.0 (prueba titular SLU)"}
        setup_testing_defaults(env)
        estado = {}
        cuerpo = b"".join(app.app(env, lambda s, h, e=None: estado.update(s=s, h=dict(h))))
        return int(estado["s"].split()[0]), estado["h"], cuerpo.decode("utf-8", "replace")
    return app, get, registro


_RE_T_JS = re.compile(r"window\.__T__=(\{.*?\});window\.__LP__=", re.S)


def _normalizar(cuerpo):
    """window.__T__ (traducciones para el navegador) sale en un orden que cambia en cada arranque: se compara ordenado."""
    def ordenar(m):
        try:
            return ("window.__T__=" + json.dumps(json.loads(m.group(1)), ensure_ascii=False, sort_keys=True)
                    + ";window.__LP__=")
        except ValueError:
            return m.group(0)
    return _RE_T_JS.sub(ordenar, cuerpo)


def volcar(carpeta, salida):
    _, get, _ = _cliente(carpeta)
    datos = {}
    for r in PAGINAS:
        c, h, b = get(r)
        datos[r] = [c, h.get("Location", ""), _normalizar(b)]
    with open(salida, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False)


def _jsonld(b):
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', b, re.S)
    try:
        return json.loads(m.group(1).replace("<\\/", "</")) if m else {}
    except ValueError:
        return {}


def caso(modo):
    fallos = []
    app, get, registro = _cliente(AQUI)
    persona = app.DONACIONES_TITULAR                      # el nombre no se escribe en la prueba: se lee de la web
    encendido = modo == "encendido"
    ok(fallos, modo, (app.TITULAR_SOCIEDAD is not None) == encendido, f"TITULAR_SOCIEDAD: {app.TITULAR_SOCIEDAD}")
    ok(fallos, modo, ("[titular]" in registro) == (modo == "incompleto"),
       "aviso en el registro solo si hay variables pero no valen")
    for pre in ("", "/gl", "/ca", "/eu"):
        c, h, av = get(pre + "/aviso-legal")
        c2, h2, qs = get(pre + "/quien-soy")
        ok(fallos, modo, c == 200 and c2 == 200, f"{pre or '/'}: aviso legal y «Quién soy» responden ({c}, {c2})")
        if encendido:
            ok(fallos, modo, "Ejemplo Datos S.L.U." in av and "B00000000" in av and "Calle Inventada 1" in av
               and "hoja MU-00000" in av, f"{pre}/aviso-legal: denominación, NIF, domicilio social y registro")
            ok(fallos, modo, persona not in av, f"{pre}/aviso-legal: la persona ya no figura como titular")
            ok(fallos, modo, persona in qs and "Ejemplo Datos S.L.U." in qs,
               f"{pre}/quien-soy: sigue siendo la página del fundador y dice de quién es la web")
            cuenta = qs.split('id="iban-numero"')[0].rsplit('class="bizum-caja"', 1)[-1] if 'id="iban-numero"' in qs else ""
            ok(fallos, modo, "Ejemplo Datos S.L.U." in cuenta and persona not in cuenta,
               f"{pre}/quien-soy: la cuenta de las donaciones, a nombre de la sociedad y no de la persona")
        else:
            ok(fallos, modo, persona in av and "S.L.U." not in av, f"{pre}/aviso-legal: el titular es la persona (hoy)")
            ok(fallos, modo, persona in qs and "S.L.U." not in qs, f"{pre}/quien-soy: como hoy")
    c, h, qs = get("/quien-soy")
    ok(fallos, modo, ("No hay una organización detrás" in qs) != encendido,
       "«No hay una organización detrás» solo sin la sociedad")
    ld = _jsonld(get("/")[2])
    ok(fallos, modo, ld.get("@type") == "Organization", "JSON-LD de la organización en la portada")
    if encendido:
        ok(fallos, modo, ld.get("legalName") == "Ejemplo Datos S.L.U." and ld.get("taxID") == "B00000000",
           f"JSON-LD: legalName y taxID ({ld.get('legalName')}, {ld.get('taxID')})")
        ok(fallos, modo, "Datos rexistrais:" in get("/gl/aviso-legal")[2] and "Dades registrals:" in
           get("/ca/aviso-legal")[2] and "Erregistroko datuak:" in get("/eu/aviso-legal")[2], "traducciones")
    else:
        ok(fallos, modo, "legalName" not in ld and "taxID" not in ld, "JSON-LD como hoy")
    # comprobaciones de las funciones, sin arrancar otra vez
    e = dict(SOCIEDAD)
    ok(fallos, modo, app._titular_sociedad(e) is not None, "con los cuatro datos, sociedad")
    for var, valor in (("TITULAR_REGISTRO", "no"), ("TITULAR_REGISTRO", "Registro Mercantil de Murcia"),
                       ("TITULAR_NIF", "00000000T"), ("TITULAR_NOMBRE", " ")):
        ok(fallos, modo, app._titular_sociedad(dict(e, **{var: valor})) is None, f"{var}={valor!r}: no vale")
    return fallos


def _hijo(args, extra):
    datos = tempfile.mkdtemp(prefix="titular_slu_")
    sqlite3.connect(os.path.join(datos, "cache.db")).close()          # cache.db VACÍO, nunca el real
    open(os.path.join(datos, ".disco_inicializado"), "w").close()
    env = {k: v for k, v in os.environ.items() if k not in VARIABLES and not k.startswith("TITULAR_")}
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
    incompleto = {k: v for k, v in SOCIEDAD.items() if k != "TITULAR_REGISTRO"}
    for modo, extra in (("apagado", {}), ("incompleto", incompleto), ("encendido", SOCIEDAD)):
        r = _hijo(["--caso", modo], extra)
        lineas = [l for l in r.stdout.splitlines() if l.startswith(f"[{modo}]")]
        print("\n".join(lineas), flush=True)
        if r.returncode and not any("FALLOS:" in l for l in lineas):
            print(r.stdout[-1500:] + r.stderr[-3000:], flush=True)
        total += 0 if r.returncode == 0 else 1
    if len(sys.argv) == 3 and sys.argv[1] == "--comparar-con":
        otra = os.path.abspath(sys.argv[2])
        tmp = tempfile.mkdtemp(prefix="titular_slu_cmp_")
        volcados = []
        for carpeta in (AQUI, otra):
            salida = os.path.join(tmp, f"{len(volcados)}.json")
            r = _hijo(["--volcar", carpeta, salida], {})
            if r.returncode:
                print(r.stdout[-1500:] + r.stderr[-3000:], flush=True)
            volcados.append(json.load(open(salida, encoding="utf-8")) if os.path.exists(salida) else {})
        fallos = []
        for ruta in PAGINAS:
            a, b = volcados[0].get(ruta), volcados[1].get(ruta)
            ok(fallos, "comparar", a is not None and a == b,
               f"{ruta}: igual que en la otra copia ({a[0] if a else '-'}, {len(a[2]) if a else 0} bytes)")
            if a and b and a != b:
                import difflib
                dif = [l for l in difflib.unified_diff(b[2].splitlines(), a[2].splitlines(), lineterm="", n=0)
                       if l[:1] in "+-" and l[:3] not in ("+++", "---")]
                print("\n".join("    " + l[:200] for l in dif[:6]), flush=True)
        total += len(fallos)
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nCASOS CON FALLOS + DIFERENCIAS: {total}")
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
