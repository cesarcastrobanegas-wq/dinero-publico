# encoding: utf-8
"""PRUEBA QUE BLOQUEA (08-11-2026, RGPD): ninguna respuesta de la web lleva un DNI/NIE completo con su letra correcta.

Recorre una muestra amplia de la web con la función WSGI de verdad (app.app, la que sirve gunicorn en Render; así pasa
por el filtro de salida, como en producción) y FALLA si en una sola respuesta aparece un DNI (8 cifras + letra) o un NIE
(X/Y/Z + 7 cifras + letra), con o sin «ES», espacio, punto o guion, cuya letra de control sea la correcta.

Qué se pide:
  - portada, rankings, fondos UE, convocatorias, casos, páginas legales, sitemap, robots, búsquedas (en castellano y en
    otro idioma);
  - dos fichas de municipio de CADA provincia, con sus contratos formales, sus menores (y la página 2 si la hay), su
    alcalde y sus concejales;
  - los JSON públicos: /api/buscar (empresa y persona), /api/rankings-municipio, /api/diagnostico-arranque.
Con qué datos: los que vienen en el repositorio, sin red y en una base vacía en una carpeta temporal: los contratos
menores, los concejales y, en cada provincia, las dos fichas con más contratos formales de las semillas de PLACE
(backfill_formales_place_prov, que traen también el directivo del BORME de cada adjudicataria); más unas TRAMPAS con DNI/NIE inventados escondidos donde ninguna otra protección
los mira (el título de un contrato formal, la descripción de un contrato menor, el nombre de un adjudicatario con
«ES» delante). Las trampas tienen que salir tapadas: si no salieran, la prueba no estaría mirando de verdad.
El fichero completo de administradores del BORME no está en el repositorio (solo en el disco de Render): de los
administradores, esta prueba solo ve los que traen las semillas.

Además, sin fallar, dice cuántos DNI/NIE habría tapado el filtro (informativo, para encontrar el origen).

    python backend/prueba_salida_sin_dni.py          (proceso pesado: de uno en uno; unos minutos)

Código de salida 1 si hay algún DNI/NIE a la vista. La lanza el flujo salida-sin-dni.yml en cada PR a main y en cada
subida a main. Nunca imprime un DNI: solo la ruta y cuántos.
"""
import datetime
import glob
import gzip
import io
import json
import os
import re
import sys
import tempfile
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

_LETRAS = "TRWAGMYFPDXBNJZSQVHLCKE"
# Independiente de la de app.py a propósito: si alguien estropea la del filtro, esta sigue viendo los DNI.
_RE = re.compile(r"(?<![0-9A-Za-z])(?:[Ee][Ss][ .-]?)?(?:(\d{8})[ .-]?([A-Za-z])|([XYZxyz])[ .-]?(\d{7})[ .-]?([A-Za-z]))"
                 r"(?![0-9A-Za-z])")


def dni_a_la_vista(texto):
    n = 0
    for m in _RE.finditer(texto):
        if m.group(1):
            n += _LETRAS[int(m.group(1)) % 23] == m.group(2).upper()
        else:
            n += _LETRAS[("XYZ".index(m.group(3).upper()) * 10000000 + int(m.group(4))) % 23] == m.group(5).upper()
    return n


def con_letra(numero):
    return f"{numero:08d}{_LETRAS[numero % 23]}"


# Trampas: inventados, con su letra correcta
T_TITULO = con_letra(12345678)                       # 12345678Z
T_MENOR = "X" + "1234567" + _LETRAS[1234567 % 23]    # X1234567L
T_NOMBRE = "ES" + con_letra(23)                      # ES00000023T


def comprobar_filtro(app):
    """El filtro de salida por dentro, con casos inventados. Devuelve la lista de lo que no cumple."""
    mal = []
    f = app._filtro_salida_dni
    html_ = (f"<p>{T_TITULO} · {T_MENOR} · {T_NOMBRE} · P4109000B · B12345678 · ***4567** · 12345678A · "
             f"ref1234567890</p>").encode()
    c, h, b = f("/x", 200, {"Content-Type": "text/html; charset=utf-8", "Content-Length": str(len(html_)), "ETag": '"e"'},
                html_)
    txt = b.decode()
    if dni_a_la_vista(txt):
        mal.append("HTML: queda algún DNI")
    for igual in ("P4109000B", "B12345678", "***4567**", "12345678A", "ref1234567890"):
        if igual not in txt:
            mal.append(f"HTML: ha tocado «{igual}», que no es un DNI con su letra")
    if h.get("Content-Length") != str(len(b)) or "ETag" in h:
        mal.append("HTML: Content-Length o ETag sin rehacer")
    gz = gzip.compress(json.dumps({"x": T_TITULO}).encode())
    c, h, b = f("/api", 200, {"Content-Type": "application/json; charset=utf-8", "Content-Encoding": "gzip"}, gz)
    if dni_a_la_vista(gzip.decompress(b).decode()):
        mal.append("JSON en gzip: queda el DNI")
    for tipo, cod in (("application/octet-stream", 200), ("text/html; charset=utf-8", 206)):
        cuerpo = T_TITULO.encode()
        if f("/bin", cod, {"Content-Type": tipo}, cuerpo)[2] != cuerpo:
            mal.append(f"ha tocado una respuesta {tipo} {cod}, que no debe mirar")
    trozos = (x for x in [T_TITULO.encode()])
    if f("/trozos", 200, {"Content-Type": "text/plain"}, trozos)[2] is not trozos:
        mal.append("ha tocado una respuesta por trozos")
    limpio = b"<p>nada que tapar 2026</p>" * 100
    antes = app._FILTRO_SALIDA_ESTADO["ya_revisadas"]
    f("/l", 200, {"Content-Type": "text/html"}, limpio)
    f("/l", 200, {"Content-Type": "text/html"}, limpio)
    if app._FILTRO_SALIDA_ESTADO["ya_revisadas"] != antes + 1:
        mal.append("un cuerpo ya revisado se ha vuelto a revisar")
    return mal


def main():
    tmp = tempfile.mkdtemp(prefix="salida_sin_dni_")
    os.environ.update(DATA_DIR=tmp, HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9",
                      I18N_PUBLICADOS="gl,ca,eu", FILTRO_SALIDA_DNI="1")
    import app
    for hilo in threading.enumerate():               # que termine la carga de los menores del repositorio
        if hilo.name == "carga-place-menores":
            hilo.join(timeout=1800)

    # Las fichas de la muestra: en cada provincia, las dos con más contratos formales en las semillas de PLACE; donde
    # no hay semilla, una ficha vacía, para que se vean igual sus menores, su alcalde y sus concejales.
    semillas = {}
    for ruta in glob.glob(os.path.join(BASE_DIR, "backfill_formales_place_prov", "*.json.gz")):
        with gzip.open(ruta, "rt", encoding="utf-8") as f:
            d = json.load(f)
        semillas[d.get("provincia") or os.path.basename(ruta)[:-8]] = d.get("municipios") or {}
    muestra = []
    for prov, munis in sorted(app.MUNICIPIOS_POR_PROVINCIA.items()):
        sem = semillas.get(prov, {})
        elegidos = sorted((m for m in munis if m in sem), key=lambda m: -len(sem[m]))[:2] or sorted(munis)[:2]
        for m in elegidos:
            contratos = list(sem.get(m, []))
            app._db_set_municipio(m, {"municipio": m, "contratos": contratos, "total_contratos": len(contratos),
                                      "timestamp": time.time()}, prov)
            muestra.append((prov, m))
    mal_filtro = comprobar_filtro(app)
    prov_trampa = "sevilla" if "sevilla" in app.MUNICIPIOS_POR_PROVINCIA else sorted(app.MUNICIPIOS_POR_PROVINCIA)[0]
    muni_trampa = next(m for p_, m in muestra if p_ == prov_trampa)
    ficha = app._db_get_municipio(muni_trampa, prov_trampa)
    hoy = datetime.date.today().isoformat()
    ficha["contratos"] = [
        {"empresa": "SERVICIOS DE PRUEBA SL", "nif": "B00000000", "titulo": f"Asesoramiento (expediente {T_TITULO})",
         "importe": "1.000,00 €", "importe_num": 1000.0, "estado": "ADJ", "fuente": "place", "fecha": hoy},
        {"empresa": T_NOMBRE, "nif": "", "titulo": "Servicio de prueba", "importe": "2.000,00 €",
         "importe_num": 2000.0, "estado": "ADJ", "fuente": "place", "fecha": hoy}] + ficha.get("contratos", [])
    ficha["total_contratos"] = len(ficha["contratos"])
    app._db_set_municipio(muni_trampa, ficha, prov_trampa)
    app._db.execute("INSERT INTO contratos_menors_locales (id, municipio, provincia, fuente, organisme, adjudicatari, "
                    "nif, import_num, data_adjudicacio, tipus_contracte, descripcio, codi_cpv, exercici, ts) VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("trampa-salida-1", muni_trampa, prov_trampa, "place", "Ayuntamiento", "SUMINISTROS DE PRUEBA SL",
                     "B00000000", 300.0, hoy, "Suministros", f"Material (factura de {T_MENOR})", "",
                     datetime.date.today().year, 1.0))
    app._db.commit()
    with app._cache_lock:
        app._result_cache.clear()                    # que la ficha se vuelva a montar con las trampas

    def pedir(ruta, comprimir=True):
        path, _, query = ruta.partition("?")
        estado = {}
        entorno = {"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": query, "REMOTE_ADDR": "",
                   "HTTP_USER_AGENT": "Mozilla/5.0 (prueba salida-sin-dni)", "wsgi.input": io.BytesIO(b""),
                   "HTTP_ACCEPT_ENCODING": "gzip" if comprimir else ""}
        partes = app.app(entorno, lambda s, h, e=None: estado.update(s=s, h=dict(h)))
        cuerpo = b"".join(partes)
        if estado["h"].get("Content-Encoding") == "gzip":
            cuerpo = gzip.decompress(cuerpo)
        return int(estado["s"].split()[0]), cuerpo.decode("utf-8", "replace")

    rutas = ["/", "/rankings", "/rankings?provincia=sevilla", "/fondos-ue", "/fondos-ue?pag=3", "/convocatorias",
             "/convocatorias?tab=subvenciones", "/casos", "/quien-soy", "/aviso-legal", "/metodologia",
             "/mapa-cobertura", "/sitemap.xml", "/robots.txt", "/?q=garcia", "/?q=martinez+lopez", "/gl/", "/ca/rankings",
             "/eu/?q=garcia", "/api/buscar?tipo=empresa&q=garcia", "/api/buscar?tipo=persona&q=garcia",
             "/api/rankings-municipio?q=murcia", "/api/diagnostico-arranque"]
    for prov, m in muestra:
        rutas.append(f"/?muni={app.quote_plus(m)}&provincia={prov}")
    ruta_trampa = f"/?muni={app.quote_plus(muni_trampa)}&provincia={prov_trampa}"
    rutas += [ruta_trampa, "/gl" + ruta_trampa, ruta_trampa + "&pag_cm=2"]

    t0 = time.time()
    fallos, errores, pedidas, cuerpos = [], [], 0, {}
    for ruta in dict.fromkeys(rutas):
        for comprimir in (True, False):
            codigo, texto = pedir(ruta, comprimir)
            pedidas += 1
            if codigo >= 500:
                errores.append(f"{ruta} ({codigo})")
            n = dni_a_la_vista(texto)
            if n:
                fallos.append(f"{ruta}{' (gzip)' if comprimir else ''}: {n}")
            cuerpos[ruta] = texto
        if "pag_cm=" in cuerpos[ruta] and "pag_cm" not in ruta and ruta.startswith("/?muni="):
            codigo, texto = pedir(ruta + "&pag_cm=2")
            pedidas += 1
            if dni_a_la_vista(texto):
                fallos.append(f"{ruta}&pag_cm=2: {dni_a_la_vista(texto)}")

    # Las trampas tienen que haber salido, y tapadas: si no, la prueba no estaría mirando de verdad
    trampa = cuerpos.get(ruta_trampa, "")
    vistas = {"título de un contrato formal": "***4567**" in trampa and "expediente" in trampa,
              "nombre «ES…» de un adjudicatario": "***0002**" in trampa,
              "descripción de un contrato menor": "****4567*" in trampa}
    no_vistas = [k for k, v in vistas.items() if not v]

    # Informativo: cuántos habría tapado el filtro (se repiten unas cuantas páginas sin él)
    app.FILTRO_SALIDA_DNI = False
    sin_filtro = {}
    for ruta in dict.fromkeys(rutas):
        n = dni_a_la_vista(pedir(ruta, False)[1])
        if n:
            sin_filtro[ruta] = n
    app.FILTRO_SALIDA_DNI = True

    vacias = sum(1 for r in rutas if r.startswith("/?muni=") and "Municipio no encontrado" in cuerpos.get(r, ""))
    formales = sum(len(semillas.get(p_, {}).get(m, [])) for p_, m in muestra)
    print(f"Fichas de la muestra: {len(muestra)} ({formales} contratos formales de semilla); sin datos: {vacias}")
    print(f"Respuestas revisadas: {pedidas} ({len(dict.fromkeys(rutas))} rutas) en {time.time() - t0:.0f} s. "
          f"Estado del filtro: {json.dumps(app._FILTRO_SALIDA_ESTADO)}")
    print("Sin el filtro (informativo; las trampas son 3): "
          + (", ".join(f"{r}: {n}" for r, n in sin_filtro.items()) or "ninguno"))
    if errores:
        print("Páginas con error 5xx: " + ", ".join(errores))
    if mal_filtro:
        print("FALLO en el filtro por dentro: " + "; ".join(mal_filtro))
    if no_vistas:
        print("FALLO: las trampas no han salido (tapadas) en " + ", ".join(no_vistas))
    if fallos:
        print("FALLO: DNI/NIE completos a la vista en " + "; ".join(fallos))
    if fallos or no_vistas or errores or mal_filtro:
        return 1
    print("TODO BIEN: ningún DNI/NIE a la vista")
    return 0


if __name__ == "__main__":
    sys.exit(main())
