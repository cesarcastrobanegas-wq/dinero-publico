# Diagnostico de cobertura por comunidad (2026-10-02). Arranca app.py sobre una COPIA de la base de produccion
# (DATA_DIR del scratchpad), sin red, y vuelca una fila por municipio con los componentes del indice y el detalle
# de contratos menores. La agregacion por comunidad se hace aparte (diag_tabla.py) para no repetir el arranque.
import os, sys, json, time, threading, traceback

AQUI = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(AQUI, "diag_ccaa.log")
SALIDA = os.path.join(AQUI, "diag_municipios.json")


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + str(msg) + "\n")


os.environ["DATA_DIR"] = os.path.join(AQUI, "datadir")
for v in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ[v] = "http://127.0.0.1:9"          # sin red: el hilo de enriquecimiento no sale a ninguna parte
os.environ.pop("NO_PROXY", None)
sys.stdout = open(os.devnull, "w")
sys.stderr = open(os.devnull, "w")
sys.path.insert(0, r"C:\Users\cesar.DESKTOP-HV3CEL7\Desktop\app_dinero_publico\backend")

try:
    log("importando app...")
    t0 = time.time()
    import app as A
    log(f"app importada en {time.time() - t0:.0f} s; DATA_DIR={A.DATA_DIR}")
    for t in threading.enumerate():
        if t.name == "carga-place-menores":
            log("esperando a la carga del feed de menores de PLACE...")
            t.join()
    log(f"feed cargado a los {time.time() - t0:.0f} s")

    filas = A._calcular_indice_transparencia()
    det = A._indice_menores_detalle_por_municipio()
    formales = {A.clave_municipio(d.get("municipio", ""), d.get("provincia")): len(d.get("contratos", []))
                for d in A._db_all_municipios()}
    out = []
    for f in filas:
        clave = A.clave_municipio(f["municipio"], f["provincia"])
        d = det.get((A.normalizar(f["municipio"]), f["provincia"]))
        comp = f["componentes"]
        out.append({
            "municipio": f["municipio"], "provincia": f["provincia"], "ccaa": f["comunidad_autonoma"],
            "hab": f["habitantes"], "indice": f["indice"], "n_comp": f["n_componentes"],
            "comp": {k: (round(v["puntos"], 2) if v["disponible"] else None) for k, v in comp.items()},
            "men_total": d["total"] if d else 0,
            "men_fuentes": sorted(x for x in d["fuentes"] if x) if d else [],
            "men_anios": sorted(d["anios"]) if d else [],
            "men_ultima": d["ultima"] if d else "",
            "men_con_adj": d["con_adj"] if d else 0,
            "formales": formales.get(clave),
            "sueldos_regs": len([r for r in (A.SUELDOS_CONCEJALES.get(clave) or [])
                                 if not r["provincia"] or r["provincia"] == f["provincia"]]),
            "sueldos_revisado_sin_tabla": clave in A._SUELDOS_CONCEJALES_SIN_TABLA,
            "ispa": A.RETRIBUCIONES_ISPA.get(clave, {}).get("importe") is not None,
            "cuentas_ult": (A.CUENTAS_ANUALES.get(clave) or {}).get("ultimo_ejercicio_rendido"),
            "concejales_lista": len(((A.ALCALDES_CONCEJALES.get(clave) or {}).get("concejales")) or []),
        })
    with open(SALIDA, "w", encoding="utf-8") as fh:
        json.dump({"generado": time.strftime("%Y-%m-%d %H:%M"), "labels": A.COMUNIDAD_AUTONOMA_LABEL,
                   "municipios": out}, fh, ensure_ascii=False)
    log(f"HECHO: {len(out)} municipios en {time.time() - t0:.0f} s")
except Exception:
    log(traceback.format_exc())
os._exit(0)
