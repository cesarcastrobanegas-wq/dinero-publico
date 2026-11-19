# encoding: utf-8
"""Prueba (sin red) del índice en memoria del buscador, pestañas Empresa y Directivo (19-11-2026): con el índice, el
resultado tiene que ser EXACTAMENTE el mismo (mismo JSON, carácter a carácter) que por el camino de siempre.

    python backend/prueba_buscar_indice.py
        fichas inventadas: empates de importe, acentos, importes enteros, filtro por provincia, una ficha que cambia,
        el BORME que cambia, el interruptor BUSCAR_INDICE_MEMORIA=0.

    python backend/prueba_buscar_indice.py RUTA_A_UNA_CARPETA_CON_UNA_COPIA_DE_cache.db
        con una COPIA de la base de producción (la carpeta hace de DATA_DIR; nunca el original): memoria del índice y
        del proceso, tiempo de construcción y comparación de búsquedas reales (empresas, NIF de sociedades, directivos
        con y sin tilde). Las búsquedas se sacan de la propia base y NO se imprimen: solo su tipo y los tiempos.

Proceso pesado (importa la web): de uno en uno.
"""
import collections
import gc
import io
import json
import os
import random
import re
import sys
import tempfile
import time
import tracemalloc

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)


def rss_mb():
    try:
        import psutil
        return psutil.Process().memory_info().rss / 1e6
    except Exception:
        return float("nan")


def main():
    real = len(sys.argv) > 1
    os.environ.update(DATA_DIR=sys.argv[1] if real else tempfile.mkdtemp(prefix="buscar_indice_"),
                      HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9", DINERO_HILOS_EN_POST_FORK="1")
    os.environ.pop("BUSCAR_INDICE_MEMORIA", None)
    salida = sys.stdout
    sys.stdout = io.StringIO()               # la carga de la web escribe mucho
    import app
    sys.stdout = salida
    mal, bien = [], [0]

    def comprobar(cond, texto):
        if cond:
            bien[0] += 1
        else:
            mal.append(texto)

    def de_siempre(tipo, q, prov=None):
        guardado = app._buscar_indice
        app._buscar_indice = None
        try:
            datos = app._db_iter_municipios(provincia=prov) if prov else app._db_iter_municipios()
            return app.api_buscar(tipo, q, datos, prov)
        finally:
            app._buscar_indice = guardado

    def con_indice(tipo, q, prov=None):
        antes = app._buscar_indice_estado["con_indice"]
        datos = app._db_iter_municipios(provincia=prov) if prov else app._db_iter_municipios()
        r = app.api_buscar(tipo, q, datos, prov)
        return r, app._buscar_indice_estado["con_indice"] == antes + 1

    def comparar(tipo, q, prov=None, etiqueta=""):
        t = time.perf_counter()
        a = de_siempre(tipo, q, prov)
        ta = time.perf_counter() - t
        t = time.perf_counter()
        b, usado = con_indice(tipo, q, prov)
        tb = time.perf_counter() - t
        ja, jb = json.dumps(a, ensure_ascii=False), json.dumps(b, ensure_ascii=False)
        comprobar(usado, f"{etiqueta or tipo}: no usó el índice")
        comprobar(ja == jb, f"{etiqueta or tipo} ({len(q)} letras{', ' + prov if prov else ''}): distinto "
                  f"({len(ja)} frente a {len(jb)} caracteres)")
        n = len(a.get("resultados") or a.get("grupos") or [])
        return ta, tb, n

    if not real:
        # ── fichas inventadas ─────────────────────────────────────────────────────────────────────────────────────
        provs = [p for p, l in app.MUNICIPIOS_POR_PROVINCIA.items() if len(l) > 3][:3]
        empresas = ["CONSTRUCCIONES FÍCTICAS SL", "Construcciones Ficticas S.L.", "SERVICIOS ÁGILES SA", "Limpiezas Ñandú SL",
                    "AYUNTAMIENTO", "", "Obras y Viales SAU"]
        directivos = [("Ánxel Fíctor Ñéqua", "Administrador único"), ("ANXEL FICTOR NEQUA", "Consejero"),
                      ("", ""), ("Mária Inventáda", "Apoderado"), ("Ána Péña Ficticia", "Administrador solidario")]
        rnd = random.Random(7)
        for i, prov in enumerate(provs):
            for j, muni in enumerate(list(app.MUNICIPIOS_POR_PROVINCIA[prov])[:3]):
                contratos = []
                for k in range(12):
                    e = empresas[(i + j + k) % len(empresas)]
                    dn, dc = directivos[(i * 3 + k) % len(directivos)]
                    imp = rnd.choice([1000.0, 1000.0, 2500.5, 3, 0, None, 99.99, 123456.78])   # empates y enteros
                    c = {"empresa": e, "nif": "B%08d" % (i * 100 + k) if k % 3 else "", "titulo": f"Obra {k}",
                         "importe": "1.000,00 €", "importe_num": imp, "estado": "ADJ", "url": "https://x/" + str(k),
                         "licitacion_id": f"L{i}{j}{k}", "directivo": dn, "cargo": dc}
                    if k == 5:
                        c.pop("importe_num")
                    contratos.append(c)
                app._db_set_municipio(muni, {"municipio": muni, "total_contratos": len(contratos),
                                             "contratos": contratos}, prov)
        comprobar(app._buscar_indice_construir() is not None, "no se construyó el índice")
        # el lector con posiciones: textos raros (espacios, claves repetidas, sin contratos, no es una ficha)
        for texto in ['{"a": 1, "contratos": [ {"x": "\\u00f1 , ]"} , {"y": [1, {"z": "}"}]} ] }',
                      '{"contratos": [{"x": 1}], "contratos": [{"x": 2}]}', '{"contratos": []}', '{}', ' { } ',
                      '{"contratos": {"no": "lista"}}', '{"municipio": "A", "contratos": [{"importe_num": 1e3}]}']:
            dp = app._ficha_y_posiciones(texto)
            d = json.loads(texto)
            comprobar(dp is not None and dp[0] == d, f"lector: {texto[:40]}")
            if dp and dp[1]:
                comprobar([json.loads(texto[a:b]) for a, b in dp[1]] == d["contratos"], f"trozos: {texto[:40]}")
        for texto in ["[1, 2]", "{\"a\": 1} x", "{\"a\" 1}", ""]:
            comprobar(app._ficha_y_posiciones(texto) is None, f"lector debería rechazar: {texto!r}")
        consultas = [("empresa", "construcciones"), ("empresa", "CONSTRUCCIONES FICTICAS"), ("empresa", "sl"),
                     ("empresa", "ñandu"), ("empresa", "nandú"), ("empresa", "zzqx"), ("empresa", "agiles"),
                     ("directivo", "anxel fictor"), ("directivo", "ÁNXEL FÍCTOR"), ("directivo", "ñéqua"),
                     ("directivo", "inventada"), ("directivo", "péña"), ("directivo", "pena"), ("directivo", "zzqx"),
                     ("directivo", "an")]
        for tipo, q in consultas:
            comparar(tipo, q)
            comparar(tipo, q, provs[1], f"{tipo} por provincia")
        # una ficha que cambia: hasta reconstruir, el camino de siempre (y el mismo resultado)
        muni0 = list(app.MUNICIPIOS_POR_PROVINCIA[provs[0]])[0]
        with app._db_lock:
            fila = app._db.execute("SELECT data FROM municipios WHERE municipio=?",
                                   (app.clave_municipio(muni0, provs[0]),)).fetchone()
        d = json.loads(fila[0])
        d["contratos"][0]["empresa"] = "CONSTRUCCIONES NUEVAS SL"
        d["contratos"][0]["importe_num"] = 5e6
        with app._db_lock:
            app._db.execute("UPDATE municipios SET data=? WHERE municipio=?",
                            (json.dumps(d, ensure_ascii=False), app.clave_municipio(muni0, provs[0])))
            app._db.commit()
        r, usado = con_indice("empresa", "construcciones")
        comprobar(not usado, "tras cambiar una ficha se siguió usando el índice viejo")
        comprobar(json.dumps(r) == json.dumps(de_siempre("empresa", "construcciones")), "resultado tras el cambio")
        comprobar(r["resultados"][0]["empresa"] == "CONSTRUCCIONES NUEVAS SL", "no se ve el cambio de la ficha")
        app._buscar_indice_construir()
        comparar("empresa", "construcciones", etiqueta="empresa tras reconstruir")
        # el BORME que cambia (se sustituye el diccionario entero, como al subirlo)
        viejo = app.ADMINISTRADORES_BORME
        app.ADMINISTRADORES_BORME = dict(viejo, **{"B00000001": {"nombre": "Nadie Inventado", "cargo": "Adm. único",
                                                                 "desde": "20200101", "fuente": "BORME-A-2020-1-30"}})
        r, usado = con_indice("directivo", "inventado")
        comprobar(not usado, "tras cambiar el BORME se siguió usando el índice viejo")
        app._buscar_indice_construir()
        comparar("directivo", "inventado", etiqueta="directivo con el BORME nuevo")
        app.ADMINISTRADORES_BORME = viejo
        # interruptor
        os.environ["BUSCAR_INDICE_MEMORIA"] = "0"
        app._buscar_indice_construir()
        r, usado = con_indice("empresa", "sl")
        comprobar(not usado and json.dumps(r) == json.dumps(de_siempre("empresa", "sl")), "el interruptor no lo apaga")
        os.environ.pop("BUSCAR_INDICE_MEMORIA")
        # sin construir: va como siempre
        app._buscar_indice = None
        r, usado = con_indice("directivo", "fictor")
        comprobar(not usado and r == de_siempre("directivo", "fictor"), "sin índice no va como siempre")
        # el hilo de fondo: no construye hasta el aviso del precálculo; luego, lo rehace si cambia una ficha o tras
        # otro precálculo
        import threading
        app.BUSCAR_INDICE_COMPROBAR_S, app.BUSCAR_INDICE_MIN_ENTRE_S = 0.2, 0
        app._buscar_indice_precalculo.clear()
        threading.Thread(target=app._buscar_indice_bg, daemon=True).start()
        time.sleep(1.5)
        comprobar(app._buscar_indice is None, "el hilo construyó antes del aviso del precálculo")

        def esperar(cond, s=20):
            fin = time.time() + s
            while time.time() < fin and not cond():
                time.sleep(0.1)
            return cond()
        app._buscar_indice_estado["precalculos"] += 1
        app._buscar_indice_precalculo.set()
        comprobar(esperar(lambda: app._buscar_indice is not None), "el hilo no construyó tras el precálculo")
        ix1 = app._buscar_indice
        with app._db_lock:
            app._db.execute("UPDATE municipios SET ts=ts WHERE rowid=(SELECT min(rowid) FROM municipios)")
            app._db.commit()
        comprobar(esperar(lambda: app._buscar_indice is not ix1), "el hilo no lo rehízo tras cambiar una ficha")
        ix2 = app._buscar_indice
        comprobar(ix2 is not None and ix2.firma == app._buscar_indice_firma(), "el índice nuevo no está al día")
        app._buscar_indice_estado["precalculos"] += 1
        comprobar(esperar(lambda: app._buscar_indice is not ix2), "el hilo no lo rehízo tras otro precálculo")
        comparar("empresa", "sl", etiqueta="empresa con el índice del hilo")
        # sin triggers (como si se hubiera vuelto a crear la tabla): la firma cambia y los triggers vuelven
        f1 = app._buscar_indice_firma()
        with app._db_lock:
            app._db.execute("DROP TRIGGER temp.buscar_indice_update")
            app._db.commit()
        f2 = app._buscar_indice_firma()
        with app._db_lock:
            n_trig = app._db.execute("SELECT count(*) FROM sqlite_temp_master WHERE type='trigger'").fetchone()[0]
        comprobar(f1 != f2 and n_trig == 3, f"sin triggers: firma {f1} -> {f2}, triggers {n_trig}")
    else:
        # ── copia de producción ───────────────────────────────────────────────────────────────────────────────────
        gc.collect()
        rss0 = rss_mb()
        tracemalloc.start()
        base, _ = tracemalloc.get_traced_memory()
        ix = app._buscar_indice_construir()
        gc.collect()
        ahora, pico = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        comprobar(ix is not None, "no se construyó el índice")
        print(f"índice: {(ahora - base) / 1e6:.1f} MB en memoria (pico durante la construcción {(pico - base) / 1e6:.0f}"
              f" MB); proceso: {rss0:.0f} MB antes, {rss_mb():.0f} MB después")
        app._buscar_indice = None
        gc.collect()
        t = time.perf_counter()
        ix = app._buscar_indice_construir()
        print(f"construcción (sin medir memoria): {time.perf_counter() - t:.1f} s; {len(ix.fic_rowid)} fichas, "
              f"{len(ix.ent_fic)} contratos, {len(ix.emp_raw)} empresas, {len(ix.dir_par)} directivos")
        print(f"proceso con el índice: {rss_mb():.0f} MB")
        # el lector con posiciones da lo mismo que json.loads, y cada trozo es su contrato
        with app._db_lock:
            textos = [r[0] for r in app._db.execute("SELECT data FROM municipios ORDER BY random() LIMIT 500")]
        iguales = trozos_ok = con_pos = 0
        for texto in textos:
            dp = app._ficha_y_posiciones(texto)
            d = json.loads(texto)
            if dp is not None and dp[0] == d:
                iguales += 1
                if dp[1] is not None:
                    con_pos += 1
                    trozos_ok += all(json.loads(texto[a:b]) == c for (a, b), c in zip(dp[1], d.get("contratos", [])))
        comprobar(iguales == len(textos) and trozos_ok == con_pos and con_pos > 0,
                  f"lector con posiciones: {iguales}/{len(textos)} iguales, {trozos_ok}/{con_pos} con los trozos bien")
        sin_pos = sum(1 for p in range(len(ix.ent_ini)) if ix.ent_ini[p] < 0)
        print(f"contratos sin posición (se leen con json_each): {sin_pos}")
        # búsquedas sacadas de la propia base (no se imprimen)
        rnd = random.Random(19)
        palabras_emp = collections.Counter(w for n in ix.emp_norm for w in set(re.findall(r"[a-z]{4,}", n)))
        comunes = [w for w, k in palabras_emp.most_common(60) if w not in ("sociedad", "limitada", "anonima")]
        with app._db_lock:
            muestras = app._db.execute("SELECT data FROM municipios ORDER BY random() LIMIT 40").fetchall()
        nif_soc, emp_enteras = [], []
        for (data,) in muestras:
            for c in json.loads(data).get("contratos", [])[:30]:
                n = (c.get("nif") or "").upper()
                if re.fullmatch(r"[AB]\d{8}", n):
                    nif_soc.append(n)
                if c.get("empresa") and len(c["empresa"]) > 8:
                    emp_enteras.append(c["empresa"])
        con_tilde = [p[0] for p in ix.dir_par if re.search(r"[áéíóúÁÉÍÓÚñÑ]", p[0])]
        apellidos = []
        for nombre in rnd.sample(con_tilde, min(400, len(con_tilde))):
            for w in nombre.split():
                if re.search(r"[áéíóúÁÉÍÓÚñÑ]", w) and len(w) >= 4:
                    apellidos.append(w)
        quitar = str.maketrans("áéíóúÁÉÍÓÚñÑ", "aeiouAEIOUnN")
        consultas = ([("empresa", "palabra común", w) for w in rnd.sample(comunes, 8)]
                     + [("empresa", "nombre entero", e) for e in rnd.sample(emp_enteras, 6)]
                     + [("empresa", "2 letras", "sl"), ("empresa", "2 letras", "sa")]
                     + [("empresa", "NIF de sociedad", n) for n in rnd.sample(nif_soc, 4)]
                     + [("directivo", "con tilde", a) for a in rnd.sample(apellidos, 5)]
                     + [("directivo", "sin tilde", a.translate(quitar)) for a in rnd.sample(apellidos, 5)]
                     + [("directivo", "mayúsculas", a.upper()) for a in rnd.sample(apellidos, 2)]
                     + [("directivo", "2 letras", "ma")])
        prov = next(p for p in ("madrid", "murcia", "barcelona") if p in app.MUNICIPIOS_POR_PROVINCIA)
        consultas += [("empresa", "por provincia", comunes[0]), ("directivo", "por provincia", apellidos[0])]
        print(f"{len(consultas)} búsquedas comparadas (la de siempre / con el índice):")
        por_tipo = collections.defaultdict(list)
        for i, (tipo, clase, q) in enumerate(consultas):
            p = prov if clase == "por provincia" else None
            ta, tb, n = comparar(tipo, q, p, f"{tipo} {clase}")
            por_tipo[f"{tipo} · {clase}"].append((ta, tb, n))
        for k, v in por_tipo.items():
            print(f"  {k:28s} x{len(v)}: {sum(a for a, _, _ in v) / len(v):6.2f} s -> "
                  f"{sum(b for _, b, _ in v) / len(v) * 1000:6.0f} ms  (resultados: {[n for _, _, n in v]})")
        todos = [b for v in por_tipo.values() for _, b, _ in v]
        print(f"con el índice: la más lenta {max(todos) * 1000:.0f} ms")
    print(f"{bien[0]} bien, {len(mal)} mal")
    for m in mal[:15]:
        print("  MAL:", m)
    sys.stdout.flush()
    os._exit(1 if mal else 0)


if __name__ == "__main__":
    main()
