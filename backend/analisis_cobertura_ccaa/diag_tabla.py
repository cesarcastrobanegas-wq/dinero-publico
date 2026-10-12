# Agrega diag_municipios.json por comunidad autonoma -> diag_tabla.json + tablas en texto.
import json, os, statistics, sys

AQUI = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(AQUI, "diag_municipios.json"), encoding="utf-8"))
LABEL = D["labels"]
M = D["municipios"]
HACE_12M = "2025-10-02"
REF = ["murcia", "cataluna", "pais_vasco"]


def pct(a, b):
    return round(100.0 * a / b, 1) if b else None


def media(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


def resumen(ms):
    n = len(ms)
    hab = sum(m["hab"] or 0 for m in ms)
    con_men = [m for m in ms if m["men_total"]]
    propia = [m for m in con_men if set(m["men_fuentes"]) - {"place-menores"}]
    recientes = [m for m in con_men if (m["men_ultima"] or "")[:10] >= HACE_12M and (m["men_ultima"] or "")[:4] <= "2026"]
    g20 = [m for m in ms if (m["hab"] or 0) >= 20000]
    con_tabla = [m for m in ms if m["sueldos_regs"]]
    cu_eval = [m for m in ms if m["comp"]["cuentas"] is not None]
    con_ficha = [m for m in ms if m["formales"] is not None]
    con_formal = [m for m in ms if m["formales"]]
    idx = [m["indice"] for m in ms if m["indice"] is not None]
    return {
        "municipios": n, "habitantes": hab,
        # contratos menores
        "men_pct_munis": pct(len(con_men), n),
        "men_pct_pob": pct(sum(m["hab"] or 0 for m in con_men), hab),
        "men_pct_munis_fuente_propia": pct(len(propia), n),
        "men_pct_pob_fuente_propia": pct(sum(m["hab"] or 0 for m in propia), hab),
        "men_pct_munis_ult12m": pct(len(recientes), n),
        "men_contratos": sum(m["men_total"] for m in ms),
        "men_por_1000hab": round(1000.0 * sum(m["men_total"] for m in ms) / hab, 1) if hab else None,
        "men_g20_con": len([m for m in g20 if m["men_total"]]), "g20": len(g20),
        "men_g20_propia": len([m for m in g20 if set(m["men_fuentes"]) - {"place-menores"}]),
        "men_puntos_medios": media(m["comp"]["menores"] for m in ms),
        # sueldos
        "sue_munis_tabla": len(con_tabla), "sue_registros": sum(m["sueldos_regs"] for m in ms),
        "sue_pct_pob": pct(sum(m["hab"] or 0 for m in con_tabla), hab),
        "sue_g20_tabla": len([m for m in g20 if m["sueldos_regs"]]),
        "sue_g20_revisado_sin_tabla": len([m for m in g20 if m["sueldos_revisado_sin_tabla"] and not m["sueldos_regs"]]),
        "ispa_pct_munis": pct(len([m for m in ms if m["ispa"]]), n),
        "concejales_lista_pct": pct(len([m for m in ms if m["concejales_lista"]]), n),
        # cuentas
        "cu_evaluable": bool(cu_eval),
        "cu_pct_al_dia": pct(len([m for m in cu_eval if m["comp"]["cuentas"] == 100]), len(cu_eval)),
        "cu_pct_1_anio": pct(len([m for m in cu_eval if m["comp"]["cuentas"] == 50]), len(cu_eval)),
        "cu_pct_sin_dato": pct(len([m for m in cu_eval if m["cuentas_ult"] is None]), len(cu_eval)),
        "cu_pct_con_dato_total": pct(len([m for m in ms if m["cuentas_ult"] is not None]), n),
        "deuda_pct": pct(len([m for m in ms if m["comp"]["deuda_pub"] == 100]), n),
        "saldo_pct": pct(len([m for m in ms if m["comp"]["saldo_pub"] == 100]), n),
        # formales
        "for_pct_ficha": pct(len(con_ficha), n), "for_pct_con_contratos": pct(len(con_formal), n),
        "for_contratos": sum(m["formales"] or 0 for m in ms),
        "for_por_1000hab": round(1000.0 * sum(m["formales"] or 0 for m in ms) / hab, 2) if hab else None,
        "adj_medio": media(m["comp"]["adjudicatario"] for m in ms),
        "dir_medio": media(m["comp"]["directivo"] for m in ms),
        "formato_clasificados": len([m for m in ms if m["comp"]["formato"] is not None]),
        # indice
        "idx_pct_con": pct(len(idx), n), "idx_mediana": round(statistics.median(idx), 1) if idx else None,
        "n_comp_medio": media(m["n_comp"] for m in ms),
    }


por = {}
for m in M:
    por.setdefault(m["ccaa"], []).append(m)
out = {c: dict(resumen(ms), label=LABEL.get(c, c)) for c, ms in por.items()}
out["_espana"] = dict(resumen(M), label="España")
out["_referencia"] = dict(resumen([m for m in M if m["ccaa"] in REF]), label="Referencia (Murcia+Cataluña+PV)")
out["_girona"] = dict(resumen([m for m in M if m["provincia"] == "girona"]), label="Girona (provincia)")
json.dump(out, open(os.path.join(AQUI, "diag_tabla.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

orden = REF + sorted((c for c in por if c not in REF), key=lambda c: -out[c]["habitantes"]) + ["_girona", "_espana"]
cols = sys.argv[1:] or ["municipios", "men_pct_munis", "men_pct_pob", "men_pct_pob_fuente_propia", "men_pct_munis_ult12m",
                        "men_por_1000hab", "men_g20_con", "men_g20_propia", "g20", "sue_munis_tabla", "sue_g20_tabla",
                        "sue_pct_pob", "ispa_pct_munis", "cu_pct_al_dia", "cu_pct_sin_dato", "deuda_pct", "saldo_pct",
                        "for_pct_con_contratos", "for_por_1000hab", "adj_medio", "dir_medio", "idx_pct_con",
                        "idx_mediana", "n_comp_medio"]
print("ccaa\t" + "\t".join(cols))
for c in orden:
    print(out[c]["label"][:22] + "\t" + "\t".join(str(out[c][k]) for k in cols))
