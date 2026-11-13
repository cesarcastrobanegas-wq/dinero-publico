# encoding: utf-8
"""Prueba SIN RED de los tres arreglos del vigilante diario del 09-11-2026.

  5. /fondos-ue: un contrato adjudicado antes del 1-2-2020 no cuenta como del Plan de Recuperación aunque PLACE lo
     marque (Reglamento (UE) 2021/241, art. 17.2): ni en la tabla de los 10 mayores ni en las sumas; queda como
     «Fondos UE». El resumen se rehace al arrancar (la huella lleva la versión).
  6. Portada: «Licitaciones abiertas» es la misma cifra en todos los idiomas; cuando cambia, las portadas guardadas de
     los demás idiomas se dan por viejas para que se vuelvan a montar.
  7. Contratos menores: el nombre del adjudicatario y la insignia de la fuente van separados por un espacio
     («CANTERAS BLOCONA SL PLACE», no «…SLPLACE»).

    python backend/prueba_vigilante_09_11.py      (proceso pesado: importa la web; de uno en uno, ~2-3 min)
"""
import json
import os
import re
import sys
import tempfile
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main():
    os.environ.update(DATA_DIR=tempfile.mkdtemp(prefix="vigilante_"), HTTP_PROXY="http://127.0.0.1:9",
                      HTTPS_PROXY="http://127.0.0.1:9")
    import app
    for hilo in threading.enumerate():
        if hilo.name == "carga-place-menores":
            hilo.join(timeout=1800)
    mal, bien = [], [0]

    def comprobar(cond, texto):
        if cond:
            bien[0] += 1
        else:
            mal.append(texto)

    # ── 5. Plan de Recuperación solo desde el 1-2-2020 ──────────────────────────────────────────────────────────────
    f = app._fondos_ue_contrato
    comprobar(f({"fondos_ue": ["EU", "PRTR"], "fecha": "1999-11-30"}) == ["EU"], "1999 con PRTR debe quedar en EU")
    comprobar(f({"fondos_ue": ["PRTR"], "fecha": "2007-01-12"}) == ["EU"], "solo PRTR antiguo debe quedar en EU")
    comprobar(f({"fondos_ue": ["PRTR", "FEDER"], "fecha": "2015-05-19"}) == ["FEDER"], "PRTR+FEDER antiguo -> FEDER")
    comprobar(f({"fondos_ue": ["EU", "PRTR"], "fecha": "2020-02-01"}) == ["EU", "PRTR"], "el 1-2-2020 ya cuenta")
    comprobar(f({"fondos_ue": ["EU", "PRTR"], "fecha": "2023-05-16"}) == ["EU", "PRTR"], "2023 sigue en el Plan")
    comprobar(f({"fondos_ue": ["EU", "PRTR"]}) == ["EU", "PRTR"], "sin fecha se deja como viene")
    comprobar(f({"fondos_ue": ["FEDER"], "fecha": "2010-01-01"}) == ["FEDER"], "otros fondos no se tocan")

    def contrato(n, fecha, importe, cods):
        return {"fuente": "PLACE", "titulo": f"Contrato {n}", "organo": "Órgano de prueba", "empresa": "EMPRESA SL",
                "nif": "B12345678", "importe_num": importe, "fecha": fecha, "fondos_ue": cods,
                "url": f"https://contrataciondelestado.es/wps/poc?uri=deeplink:detalle_licitacion&idEvl=prueba{n}"}
    ficha = {"municipio": "Villaprueba", "provincia": "leon", "contratos": [
        contrato(1, "1999-11-30", 45984998.20, ["EU", "PRTR"]),       # León, residuos
        contrato(2, "2007-01-12", 126223954.79, ["EU", "PRTR"]),      # Plan Zonal 5
        contrato(3, "2023-05-16", 85382000.0, ["EU", "PRTR"]),
        contrato(4, "2025-03-28", 1000.0, ["EU", "PRTR"]),
        contrato(5, "2024-01-10", 500.0, ["FEDER"])]}
    with app._db_lock:
        # con DATA_DIR vacío la base no trae la tabla de entidades locales (en producción sí)
        app._db.execute("CREATE TABLE IF NOT EXISTS entidades_locales (clave TEXT PRIMARY KEY, tipo TEXT, nombre TEXT, "
                        "provincia TEXT, data TEXT, n INTEGER, importe REAL, ts REAL)")
        app._db.execute("INSERT OR REPLACE INTO municipios (municipio, data, ts, provincia) VALUES (?, ?, ?, ?)",
                        ("villaprueba|leon", json.dumps(ficha, ensure_ascii=False), time.time(), "leon"))
        app._db.commit()
    disco = app._DISCO_CONFIABLE
    app._DISCO_CONFIABLE = True
    try:
        app._aplicar_fondos_ue_place(forzar=True)
    finally:
        app._DISCO_CONFIABLE = disco
    res = app._fondos_ue_place_resumen() or {}
    esp = res.get("espana", {})
    comprobar(esp.get("PRTR", [0])[0] == 2 and abs(esp["PRTR"][1] - 85383000.0) < 0.01,
              f"PRTR debe ser 2 contratos y 85.383.000 €: {esp.get('PRTR')}")
    comprobar(esp.get("UE", [0])[0] == 5, f"UE debe seguir con los 5: {esp.get('UE')}")
    comprobar(res.get("por_fondo", {}).get("EU", [0])[0] == 2, f"los 2 antiguos pasan a «Fondos UE»: {res.get('por_fondo')}")
    fechas_top = sorted(x["fecha"] for x in res.get("top", []))
    comprobar(fechas_top == ["2023-05-16", "2025-03-28"], f"la tabla de los mayores solo lleva del Plan: {fechas_top}")
    with app._db_lock:
        huella = app._db.execute("SELECT valor FROM settings WHERE clave=?", (app._FONDOS_UE_PLACE_CLAVE,)).fetchone()
    comprobar(huella and huella[0].endswith(app._FONDOS_UE_VERSION), f"la huella lleva la versión: {huella}")
    tok = app._I18N_IDIOMA.set("es")
    try:
        html_fue = app.render_fondos_ue_html({}) if hasattr(app, "render_fondos_ue_html") else ""
    except Exception as e:
        html_fue = ""
        print(f"  (no se pudo montar /fondos-ue: {type(e).__name__}: {e})")
    finally:
        app._I18N_IDIOMA.reset(tok)
    comprobar("2023-05-16" in html_fue, "/fondos-ue enseña la tabla de los mayores contratos del Plan")
    comprobar("1999-11-30" not in html_fue and "2007-01-12" not in html_fue,
              "/fondos-ue no debe enseñar los contratos de 1999 y 2007 entre los del Plan")

    # ── 6. La misma cifra de licitaciones abiertas en todos los idiomas ─────────────────────────────────────────────
    lanzados = []
    calentar = app._calentar_portada
    app._calentar_portada = lambda: lanzados.append(1)
    try:
        def lic(i, dias):
            fin = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() + dias * 86400))
            return (f"lic{i}", "PUB", fin, f"Licitación {i}")
        with app._db_lock:
            app._db.execute("DELETE FROM licitaciones")
            app._db.executemany("INSERT INTO licitaciones (id, estado, fin_plazo, titulo) VALUES (?, ?, ?, ?)",
                                [lic(i, 10) for i in range(7)] + [lic(99, -3)])
            app._db.commit()
        app._portada_contadores_memo.update(ts=0.0, valor=None)
        t0 = time.time()
        n1 = app._portada_contadores(t0)[0]
        comprobar(n1 == 7, f"7 licitaciones abiertas: {n1}")
        cifras = {}
        for lang in ("es", "gl", "ca", "eu"):
            tok = app._I18N_IDIOMA.set(lang)
            try:
                cifras[lang] = re.findall(r'href="/convocatorias"><span>([\d.]+)</span>', app._portada_cifras_secciones_html())
            finally:
                app._I18N_IDIOMA.reset(tok)
        comprobar(len({tuple(v) for v in cifras.values()}) == 1 and cifras["es"] == ["7"],
                  f"la misma cifra en los cuatro idiomas: {cifras}")
        # entra una licitación nueva: hasta que pasa el TTL, la cifra no cambia en ningún idioma
        with app._db_lock:
            app._db.execute("INSERT INTO licitaciones (id, estado, fin_plazo, titulo) VALUES (?, ?, ?, ?)", lic(8, 5))
            app._db.commit()
        comprobar(app._portada_contadores(t0 + 60)[0] == 7, "dentro del TTL, la cifra no cambia")
        # portadas guardadas frescas en dos idiomas (y otra página que no se toca)
        ahora = time.time()
        with app._paginas_lock:
            for clave in (("es", "/"), ("gl", "/"), ("ca", "/", ("rk_comunidad", "galicia")), ("es", "/mapa-cobertura")):
                app._paginas_cache[clave] = {"gz": b"", "ts": ahora, "refrescando": False, "grupo": None}
        n2 = app._portada_contadores(t0 + app._PORTADA_CONTADORES_TTL + 1)[0]
        comprobar(n2 == 8, f"pasado el TTL, la cifra nueva: {n2}")
        with app._paginas_lock:
            viejas = {k: time.time() - e["ts"] >= app._PAGINAS_TTL for k, e in app._paginas_cache.items()
                      if k in (("es", "/"), ("gl", "/"), ("ca", "/", ("rk_comunidad", "galicia")), ("es", "/mapa-cobertura"))}
        comprobar(viejas.get(("es", "/")) and viejas.get(("gl", "/")) and viejas.get(("ca", "/", ("rk_comunidad", "galicia"))),
                  f"las portadas de todos los idiomas pasan a viejas: {viejas}")
        comprobar(viejas.get(("es", "/mapa-cobertura")) is False, "las demás páginas no se tocan")
        time.sleep(0.5)
        comprobar(len(lanzados) == 1, f"se vuelven a montar en segundo plano una vez: {len(lanzados)}")
        n3 = app._portada_contadores(t0 + 2 * app._PORTADA_CONTADORES_TTL + 2)[0]
        time.sleep(0.3)
        comprobar(n3 == 8 and len(lanzados) == 1, "si la cifra no cambia, no se remonta nada")
    finally:
        app._calentar_portada = calentar
        with app._paginas_lock:
            for k in [k for k in app._paginas_cache if k[1] in ("/", "/mapa-cobertura")]:
                del app._paginas_cache[k]

    # ── 7. Espacio entre el adjudicatario y la insignia de la fuente ────────────────────────────────────────────────
    tok = app._I18N_IDIOMA.set("es")
    try:
        fila = app._render_fila_contrato_menor({"adjudicatari": "CANTERAS BLOCONA SL", "fuente": "place-menores",
                                                "import_num": 1200.0, "data_adjudicacio": "2026-03-01",
                                                "descripcio": "Suministro de piedra", "municipio": "hinojosa del campo"})
    finally:
        app._I18N_IDIOMA.reset(tok)
    texto = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", fila))
    comprobar("CANTERAS BLOCONA SL " in texto and "SLPLACE" not in texto.replace(" ", "x"),
              f"nombre e insignia separados: {texto[:120]!r}")
    comprobar(re.search(r"CANTERAS BLOCONA SL\s+<span class=\"fuente-badge", fila) is not None,
              "hay espacio antes de la insignia en el HTML")

    print(f"{bien[0]} bien, {len(mal)} mal")
    for m in mal:
        print("  MAL:", m)
    return 1 if mal else 0


if __name__ == "__main__":
    sys.exit(main())
