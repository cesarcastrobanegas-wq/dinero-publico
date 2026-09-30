import sqlite3
import json
import time

import os, sys
DB = sys.argv[1] if len(sys.argv) > 1 else "cache_analisis.db"   # copia de trabajo de cache.db (ver DATOS_PETICION_MENORES.md, Apéndice)
VENTANA = "2021-09-01"
LEG_SERV = 15000.0
LEG_OBRA = 40000.0
LEG_MAX_SIN_IVA = 40000.0   # tope legal absoluto de un contrato menor (obras); el de servicios/suministros es 15000

db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

POBLACION = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "poblacion.json"), encoding="utf-8"))["municipios"]

OUT = {}


def q(sql, params=()):
    return db.execute(sql, params).fetchall()


# ============ SECCION 1: COBERTURA ============
OUT["total_filas_tabla"] = q("SELECT COUNT(*) c FROM contratos_menors_locales")[0]["c"]

r = q("SELECT COUNT(*) c, SUM(import_num) s FROM contratos_menors_locales WHERE data_adjudicacio >= ?", (VENTANA,))[0]
OUT["total_en_ventana_n"] = r["c"]
OUT["total_en_ventana_importe"] = r["s"]

r = q("SELECT COUNT(*) c FROM contratos_menors_locales WHERE data_adjudicacio < ? AND data_adjudicacio != ''", (VENTANA,))[0]
OUT["total_fuera_ventana_pasado"] = r["c"]

r = q("SELECT COUNT(*) c FROM contratos_menors_locales WHERE data_adjudicacio = '' OR data_adjudicacio IS NULL")[0]
OUT["total_fecha_vacia"] = r["c"]

OUT["n_municipios_total"] = q("SELECT COUNT(DISTINCT municipio) c FROM contratos_menors_locales")[0]["c"]
OUT["n_municipios_en_ventana"] = q(
    "SELECT COUNT(DISTINCT municipio) c FROM contratos_menors_locales WHERE data_adjudicacio >= ?", (VENTANA,)
)[0]["c"]

# por fuente (en ventana)
OUT["por_fuente"] = [dict(row) for row in q(
    "SELECT fuente, COUNT(*) n, SUM(import_num) importe, COUNT(DISTINCT municipio) n_municipios, "
    "MIN(data_adjudicacio) desde, MAX(data_adjudicacio) hasta "
    "FROM contratos_menors_locales WHERE data_adjudicacio >= ? GROUP BY fuente ORDER BY n DESC", (VENTANA,)
)]

# por provincia (en ventana)
OUT["por_provincia"] = [dict(row) for row in q(
    "SELECT provincia, COUNT(*) n, SUM(import_num) importe, COUNT(DISTINCT municipio) n_municipios "
    "FROM contratos_menors_locales WHERE data_adjudicacio >= ? GROUP BY provincia ORDER BY n DESC", (VENTANA,)
)]

# ============ SECCION 4: ANOMALIAS ============
r = q("SELECT COUNT(*) c FROM contratos_menors_locales WHERE data_adjudicacio >= ? AND (import_num IS NULL OR import_num = 0)", (VENTANA,))[0]
OUT["anom_importe_cero_o_null"] = r["c"]

OUT["anom_importe_cero_por_fuente"] = [dict(row) for row in q(
    "SELECT fuente, COUNT(*) n FROM contratos_menors_locales WHERE data_adjudicacio >= ? AND (import_num IS NULL OR import_num = 0) "
    "GROUP BY fuente ORDER BY n DESC", (VENTANA,)
)]

r = q("SELECT COUNT(*) c FROM contratos_menors_locales WHERE data_adjudicacio >= ? AND import_num > ?", (VENTANA, LEG_MAX_SIN_IVA))[0]
OUT["anom_importe_sobre_40000_bruto"] = r["c"]  # OJO: bruto, mezcla bases IVA -- ver informe

r = q("SELECT COUNT(*) c FROM contratos_menors_locales WHERE data_adjudicacio >= ? AND import_num > ?", (VENTANA, 15000.0))[0]
OUT["anom_importe_sobre_15000_bruto"] = r["c"]

OUT["anom_importe_sobre_40000_por_fuente"] = [dict(row) for row in q(
    "SELECT fuente, COUNT(*) n, MAX(import_num) maximo FROM contratos_menors_locales WHERE data_adjudicacio >= ? AND import_num > ? "
    "GROUP BY fuente ORDER BY n DESC", (VENTANA, LEG_MAX_SIN_IVA)
)]

json.dump(OUT, open("resultado_seccion1_4.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2, default=str)
print("OK seccion 1 y 4 escritas en resultado_seccion1_4.json")
