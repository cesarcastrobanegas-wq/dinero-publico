# encoding: utf-8
"""Prueba (sin red) de la búsqueda de ayuntamientos de /api/buscar (19-11-2026): el camino rápido (sin leer las 8.000
fichas) tiene que dar EXACTAMENTE lo mismo que el de antes, que se conserva aquí como referencia.

    python backend/prueba_buscar_ayuntamiento.py
        fichas inventadas en una base vacía (con importes, sin contratos, sin total_contratos, homónimos...)

    python backend/prueba_buscar_ayuntamiento.py RUTA_A_UNA_CARPETA_CON_cache.db
        con una COPIA de la base de producción (la carpeta hace de DATA_DIR: usar siempre una copia, nunca el
        original): compara cientos de búsquedas reales y mide el tiempo de cada camino.

Proceso pesado (importa la web): de uno en uno.
"""
import io
import json
import os
import sys
import tempfile
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)


def referencia_por_muni(app):
    """Lo que hacía antes en cada búsqueda: leer todas las fichas (se calcula una vez y se reutiliza)."""
    return {app.clave_municipio(d.get("municipio", ""), d.get("provincia")):
            (d.get("total_contratos", 0), sum(c.get("importe_num", 0.0) for c in d.get("contratos", [])))
            for d in app._db_iter_municipios()}


def referencia(app, q, por_muni):
    """El código de antes del 19-11-2026, tal cual, con por_muni ya calculado."""
    q = (q or "").strip()
    if len(q) < 2:
        return {"tipo": "ayuntamiento", "query": q, "error": "Escribe al menos 2 caracteres."}
    q_norm = app.normalizar(q)
    resultados = []
    for prov, lista_muni in app.MUNICIPIOS_POR_PROVINCIA.items():
        nombres = list(app._pseudos_de_provincia(prov)) + list(lista_muni)
        for muni in nombres:
            if q_norm not in app.normalizar(muni):
                continue
            d = por_muni.get(app.clave_municipio(muni, prov))
            cached = d is not None
            total_imp = d[1] if cached else 0.0
            resultados.append({
                "municipio": muni, "provincia": prov, "provincia_label": app.PROVINCIA_LABEL.get(prov, prov),
                "cached": cached, "total_contratos": d[0] if cached else 0,
                "total_importe": app.fmt_eur(str(total_imp)) if cached else "",
            })
    resultados.sort(key=lambda r: (not r["cached"], app.normalizar(r["municipio"])))
    return {"tipo": "ayuntamiento", "query": q, "resultados": resultados[:60]}


def fichas_inventadas(app):
    provs = [p for p, l in app.MUNICIPIOS_POR_PROVINCIA.items() if len(l) > 3][:4]
    n = 0
    for i, prov in enumerate(provs):
        for j, muni in enumerate(list(app.MUNICIPIOS_POR_PROVINCIA[prov])[:3]):
            contratos = [{"empresa": "Empresa de prueba SL", "importe_num": 1000.5 * (k + 1) + j, "titulo": "Obra"}
                         for k in range((i + j) % 4)]          # alguno sin contratos
            ficha = {"municipio": muni, "total_contratos": len(contratos) + 7, "contratos": contratos}
            if i == 1 and j == 1:
                ficha.pop("total_contratos")                     # ficha antigua sin el campo
            if i == 2 and j == 0:
                ficha["contratos"] = [{"importe_num": 3}, {"importe_num": 4}]   # importes enteros
            app._db_set_municipio(muni, ficha, prov)
            n += 1
    return n


def main():
    real = len(sys.argv) > 1
    os.environ.update(DATA_DIR=sys.argv[1] if real else tempfile.mkdtemp(prefix="buscar_ayto_"),
                      HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9", DINERO_HILOS_EN_POST_FORK="1")
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

    if not real:
        comprobar(fichas_inventadas(app) >= 10, "no se pudieron crear las fichas de prueba")
    t = time.perf_counter()
    por_muni = referencia_por_muni(app)
    t_ref = time.perf_counter() - t
    # consultas: los principios de nombre (2, 3 y 5 letras) de todos los municipios, unos nombres enteros, con
    # acentos y mayúsculas, y unas que no dan nada
    nombres = sorted({m for l in app.MUNICIPIOS_POR_PROVINCIA.values() for m in l})
    consultas = set()
    for m in nombres:
        base = m.strip()
        for k in (2, 3, 5):
            if len(base) >= k:
                consultas.add(base[:k])
    consultas = sorted(consultas)
    if real:
        consultas = consultas[::7] + nombres[::97]
    consultas += ["Ávila", "a coruña", "SAN", "  vill  ", "zzqx", "x", "", "ÑÑ"]
    tiempos = []
    for q in consultas:
        esperado = referencia(app, q, por_muni)
        t = time.perf_counter()
        obtenido = app.api_buscar("ayuntamiento", q, app._db_iter_municipios())
        tiempos.append(time.perf_counter() - t)
        comprobar(obtenido == esperado, f"distinto para una consulta de {len(q)} letras: "
                  f"{json.dumps(obtenido, ensure_ascii=False)[:200]} != {json.dumps(esperado, ensure_ascii=False)[:200]}")
    con_datos = sum(1 for q in consultas[:200] for r in referencia(app, q, por_muni).get("resultados", []) if r["cached"])
    comprobar(con_datos > 0, "ninguna consulta encuentra un municipio con datos: la prueba no prueba nada")
    tiempos.sort()
    print(f"{len(consultas)} consultas comparadas; fichas en la base: {len(por_muni)}")
    print(f"antes: leer todas las fichas {t_ref:.2f} s en CADA búsqueda; ahora: mediana "
          f"{tiempos[len(tiempos) // 2] * 1000:.0f} ms, la más lenta {tiempos[-1] * 1000:.0f} ms")
    print(f"{bien[0]} bien, {len(mal)} mal")
    for m in mal[:10]:
        print("  MAL:", m)
    sys.stdout.flush()
    os._exit(1 if mal else 0)


if __name__ == "__main__":
    main()
