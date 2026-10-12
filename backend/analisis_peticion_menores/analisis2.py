import sqlite3
import json

import os, sys
DB = sys.argv[1] if len(sys.argv) > 1 else "cache_analisis.db"   # copia de trabajo de cache.db (ver DATOS_PETICION_MENORES.md, Apéndice)
VENTANA = "2021-09-01"

db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row


def q(sql, params=()):
    return db.execute(sql, params).fetchall()


FUENTES_SIN_IVA = {"torre-pacheco", "cartagena-governalia", "ibi-governalia", "sax-governalia",
                   "vilamarxant-governalia", "castello-governalia", "xirivella-governalia",
                   "santabrigida-governalia", "alzira-governalia", "valencia_capital", "alicante",
                   "leganes", "torrent", "la_laguna",
                   # 2026-09-30: sincronizado con _FUENTES_CM_SIN_IVA de app.py (Sevilla y Torrejón confirmadas sin IVA
                   # el 29-09; feed de PLACE: TaxExclusiveAmount del adjudicado, base explícita)
                   "sevilla", "torrejon", "place-menores"}
FUENTES_CON_IVA_VERIFICADA = {"mula", "san-pedro-pinatar", "cartagena"}   # importe CON iva, hay que /1.21
IVA = 1.21

OUT = {}

# Fuentes presentes en ESTA tabla (recordar: torrent/la_laguna aun no estan en este corte de cache.db)
fuentes_presentes = {row["fuente"] for row in q("SELECT DISTINCT fuente FROM contratos_menors_locales")}
fuentes_normalizables = (FUENTES_SIN_IVA | FUENTES_CON_IVA_VERIFICADA) & fuentes_presentes
fuentes_excluidas = fuentes_presentes - fuentes_normalizables
OUT["fuentes_normalizables"] = sorted(fuentes_normalizables)
OUT["fuentes_excluidas_iva_no_verificada"] = sorted(fuentes_excluidas)

r = q("SELECT COUNT(*) n, SUM(import_num) s FROM contratos_menors_locales WHERE data_adjudicacio >= ? "
      f"AND fuente IN ({','.join('?' * len(fuentes_normalizables))})",
      (VENTANA, *fuentes_normalizables))[0]
OUT["n_en_subconjunto_normalizable"] = r["n"]
OUT["importe_bruto_subconjunto_normalizable"] = r["s"]

r = q("SELECT COUNT(*) n FROM contratos_menors_locales WHERE data_adjudicacio >= ?", (VENTANA,))[0]
OUT["n_total_ventana"] = r["n"]
OUT["pct_cubierto_por_normalizacion"] = round(100.0 * OUT["n_en_subconjunto_normalizable"] / r["n"], 2)

# Traer solo el subconjunto normalizable, calcular importe SIN IVA fila a fila
filas = q(
    "SELECT fuente, import_num, tipus_contracte FROM contratos_menors_locales WHERE data_adjudicacio >= ? "
    f"AND fuente IN ({','.join('?' * len(fuentes_normalizables))}) AND import_num IS NOT NULL AND import_num > 0",
    (VENTANA, *fuentes_normalizables)
)
sin_iva = []
for f in filas:
    v = f["import_num"]
    if f["fuente"] in FUENTES_CON_IVA_VERIFICADA:
        v = v / IVA
    sin_iva.append(v)

OUT["n_filas_con_importe_positivo"] = len(sin_iva)


def tramo(desde, hasta):
    return sum(1 for v in sin_iva if desde <= v < hasta)


# Umbral servicios/suministros: 15.000 sin IVA. Tramos de igual anchura (1000) inmediatamente por debajo/por encima
OUT["umbral_15000_tramo_13000_14999"] = tramo(13000, 15000)
OUT["umbral_15000_tramo_11000_12999"] = tramo(11000, 13000)
OUT["umbral_15000_tramo_15000_16999"] = tramo(15000, 17000)
# Ventana estrecha de 500 justo pegada al umbral (14500-14999 vs 12500-12999 vs 15000-15499)
OUT["umbral_15000_estrecho_14500_14999"] = tramo(14500, 15000)
OUT["umbral_15000_estrecho_12500_12999"] = tramo(12500, 13000)
OUT["umbral_15000_estrecho_15000_15499"] = tramo(15000, 15500)

# Umbral obras: 40.000 sin IVA
OUT["umbral_40000_tramo_38000_39999"] = tramo(38000, 40000)
OUT["umbral_40000_tramo_36000_37999"] = tramo(36000, 38000)
OUT["umbral_40000_tramo_40000_41999"] = tramo(40000, 42000)
OUT["umbral_40000_estrecho_39000_39999"] = tramo(39000, 40000)
OUT["umbral_40000_estrecho_37000_37999"] = tramo(37000, 38000)
OUT["umbral_40000_estrecho_40000_40999"] = tramo(40000, 41000)

# top municipios por concentracion en la franja 13000-14999 (sin IVA), solo fuentes normalizables
filas2 = q(
    "SELECT municipio, fuente, import_num FROM contratos_menors_locales WHERE data_adjudicacio >= ? "
    f"AND fuente IN ({','.join('?' * len(fuentes_normalizables))}) AND import_num IS NOT NULL AND import_num > 0",
    (VENTANA, *fuentes_normalizables)
)
from collections import defaultdict
por_muni_total = defaultdict(int)
por_muni_franja = defaultdict(int)
for f in filas2:
    v = f["import_num"]
    if f["fuente"] in FUENTES_CON_IVA_VERIFICADA:
        v = v / IVA
    por_muni_total[f["municipio"]] += 1
    if 13000 <= v < 15000:
        por_muni_franja[f["municipio"]] += 1

top = []
for m, n_franja in sorted(por_muni_franja.items(), key=lambda x: -x[1])[:15]:
    tot = por_muni_total[m]
    top.append({"municipio": m, "n_en_franja_13000_14999": n_franja, "n_total_municipio": tot,
                "pct": round(100.0 * n_franja / tot, 1) if tot else None})
OUT["top_municipios_franja_13000_14999"] = top

json.dump(OUT, open("resultado_seccion3.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2, default=str)
print("OK seccion 3 escrita")
