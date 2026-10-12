"""Cifras de DATOS_PETICION_MENORES.md que no salen de analisis.py/analisis2.py/analisis3_cobertura20k.py: tabla por
comunidad autónoma, contratos por encima de 48.400 € por fuente y ranking de municipios por % de contratos en la franja
13.000-14.999 € sin IVA (mismo subconjunto normalizable que analisis2.py). Uso: python analisis4_extra.py <cache.db>"""
import ast, collections, json, os, sqlite3, sys

AQUI = os.path.dirname(os.path.abspath(__file__))
DB = sys.argv[1] if len(sys.argv) > 1 else "cache_analisis.db"
VENTANA = "2021-09-01"
db = sqlite3.connect(DB)
q = lambda s, *a: db.execute(s, a).fetchall()

src = open(os.path.join(AQUI, "..", "app.py"), encoding="utf-8").read()
i = src.index("COMUNIDAD_AUTONOMA_POR_PROVINCIA = {")
ccaa = ast.literal_eval(src[i + len("COMUNIDAD_AUTONOMA_POR_PROVINCIA = "):src.index("}", i) + 1])
ccaa.update({"illes_balears": ccaa.get("baleares"), "ciudad-real": ccaa.get("ciudad_real")})   # grafías de 2 fuentes propias
pob = json.load(open(os.path.join(AQUI, "..", "poblacion.json"), encoding="utf-8"))["municipios"]
total_ccaa = collections.Counter(ccaa.get(v["provincia"], v["provincia"]) for v in pob.values())

OUT = {"por_ccaa": []}
agg = collections.defaultdict(lambda: [0, set()])
for prov, muni, n in q("SELECT provincia, municipio, COUNT(*) FROM contratos_menors_locales WHERE data_adjudicacio >= ? "
                       "GROUP BY provincia, municipio", VENTANA):
    c = ccaa.get(prov, prov)
    agg[c][0] += n
    agg[c][1].add(muni)
for c, (n, ms) in sorted(agg.items(), key=lambda x: -x[1][0]):
    OUT["por_ccaa"].append({"ccaa": c, "contratos": n, "municipios_con_datos": len(ms), "municipios_ine": total_ccaa.get(c)})

OUT["sobre_48400"] = q("SELECT COUNT(*) FROM contratos_menors_locales WHERE data_adjudicacio >= ? AND import_num > 48400",
                       VENTANA)[0][0]
OUT["sobre_48400_por_fuente"] = [dict(fuente=f, n=n, maximo=m) for f, n, m in q(
    "SELECT fuente, COUNT(*), MAX(import_num) FROM contratos_menors_locales WHERE data_adjudicacio >= ? AND import_num > 48400 "
    "GROUP BY fuente ORDER BY 2 DESC", VENTANA)]

SIN = {"torre-pacheco", "cartagena-governalia", "ibi-governalia", "sax-governalia", "vilamarxant-governalia",
       "castello-governalia", "xirivella-governalia", "santabrigida-governalia", "alzira-governalia", "valencia_capital",
       "alicante", "leganes", "torrent", "la_laguna", "sevilla", "torrejon", "place-menores"}
CON = {"mula", "san-pedro-pinatar", "cartagena"}
tot, fr = collections.Counter(), collections.Counter()
for muni, prov, fu, imp in q("SELECT municipio, provincia, fuente, import_num FROM contratos_menors_locales "
                             "WHERE data_adjudicacio >= ? AND import_num > 0", VENTANA):
    if fu in SIN or fu in CON:
        v = imp / 1.21 if fu in CON else imp
        tot[(muni, prov)] += 1
        fr[(muni, prov)] += 13000 <= v < 15000
OUT["municipios_normalizables"] = len(tot)
OUT["ranking_pct_franja_min1000"] = [dict(municipio=k[0], provincia=k[1], pct=round(100 * fr[k] / tot[k], 1),
                                          en_franja=fr[k], total=tot[k])
                                     for k in sorted((k for k in tot if tot[k] >= 1000), key=lambda k: -fr[k] / tot[k])][:15]
json.dump(OUT, open("resultado_extra.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("OK extra")
