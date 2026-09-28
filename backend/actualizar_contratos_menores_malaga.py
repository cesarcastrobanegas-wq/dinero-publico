# encoding: utf-8
"""
Contratos MENORES del Ayuntamiento de Málaga (~600.000 hab., Andalucía).

Fuente OFICIAL: portal de datos abiertos del Ayuntamiento (CKAN, datosabiertos.malaga.eu), un dataset por
trimestre ("contratos-menores-<n>-trimestre-<año>-ayuntamiento-de-malaga") con un XLSX (y PDF/ODS). Se
localizan en cada ejecución con la API de CKAN (package_search), sin guardar URLs a mano: los nombres de
fichero cambian de un trimestre a otro. Localizado en la auditoría de DATOS_PETICION_MENORES.md §5.

LIMITACIÓN REAL DE LA FUENTE -- sin fecha por contrato: ningún XLSX desde 2021 publica la fecha de adjudicación
(verificado fichero a fichero 2026-09-29; la única columna "Fecha" aparece en una hoja auxiliar casi vacía de
3T/4T 2023, no en la hoja publicada). Se usa como `data_adjudicacio` el PRIMER DÍA DEL TRIMESTRE del informe,
mismo criterio que Ames (inicio de semestre), con aviso visible en la ficha. Por eso 3T-2021 (jul-sep) se
excluye entero: no se puede saber qué contratos caen dentro de la ventana de 5 años (desde 2021-09-01).

Tres formatos de columnas (se leen por NOMBRE de cabecera, nunca por posición):
- 4T-2021 a 1T-2024: Expte. / (CC) / D / Descripción / importe|total adj.|Total Adjud. / (CIF) / tercero
- 2T-2024 a 4T-2025: Nº EXPEDIENTE / OBJETO / IMPORTE ADJUDICACIÓN / CIF / IDENTIDAD DEL ADJUDICATARIO / ...
- desde 1T-2026: Nº de contrato / Objeto del contrato / Importe adjudicación (IVA incluido) / CIF / Adjudicatario
Base de IVA NO homogénea: la cabecera de 2026 dice "IVA incluido" y en 3T-2021 "importe" es base + IVA, pero
el mismo contrato repetido en dos informes seguidos (2T y 3T de 2025, 17 casos) cambia a veces de importe
exactamente x1,21 (12.000 -> 14.520; 4.840 -> 4.000): cada informe no siempre usa la misma base. Se muestra tal
cual y la ficha lo avisa; la fuente NO entra en _FUENTES_CM_SIN_IVA. Un expediente repetido entre trimestres
se guarda UNA vez, con la primera aparición (trimestre de adjudicación). Sin CIF hasta 1T-2024.

Uso (desde backend/):
    python actualizar_contratos_menores_malaga.py

Genera contratos_menores_malaga.json.gz, que app.py carga al arrancar (_cargar_contratos_menores_malaga)."""
import gzip
import io
import json
import os
import re
import time
import unicodedata
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "contratos_menores_malaga.json.gz")
MENORES_DESDE_FECHA = "2021-09-01"   # mismo corte que MENORES_DESDE_FECHA en app.py -- mantener sincronizado a mano
PRIMER_TRIMESTRE = (2021, 4)         # 3T-2021 excluido: sin fecha por contrato, cae en parte antes de la ventana
API = ("https://datosabiertos.malaga.eu/api/3/action/package_search?q=title:%22contratos%20menores%22"
       "%20ayuntamiento&rows=200")
_UA = "Mozilla/5.0 (compatible; dinero-publico-bot/1.0)"


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def _norm(txt):
    t = unicodedata.normalize("NFD", str(txt or "").lower())
    return " ".join("".join(c for c in t if unicodedata.category(c) != "Mn").split())


def _limpiar(txt):
    return " ".join(str(txt or "").split())


def _periodo(nombre):
    """'contratos-menores-2o-trimestre-2026-...' / 'contratos-menores-primer-trimestre-2026-...' -> (2026, 2)."""
    y = re.search(r"(20\d\d)", nombre)
    if not y:
        return None
    if "primer-trimestre" in nombre:
        q = 1
    else:
        m = re.search(r"-(\d)o?-trimestre", nombre)
        if not m:
            return None
        q = int(m.group(1))
    return int(y.group(1)), q


def _importe(v):
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v or "").replace("€", "").strip()
    if not t:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _columnas(cab):
    """Índices de las columnas útiles a partir de la fila de cabecera normalizada."""
    idx = {}
    for i, c in enumerate(cab):
        n = _norm(c)
        if not n:
            continue
        if "exp" not in idx and (n.startswith("expte") or n.startswith("no expediente") or n.startswith("nº expediente")
                                 or n.startswith("n expediente") or n.startswith("nº de contrato")
                                 or n.startswith("no de contrato") or n.startswith("n de contrato")):
            idx["exp"] = i
        elif "obj" not in idx and (n.startswith("descrip") or n.startswith("descricp") or n.startswith("objeto")):
            idx["obj"] = i
        elif "imp" not in idx and (n == "importe" or n.startswith("total adj") or n.startswith("importe adjudicacion")):
            idx["imp"] = i
        elif "cif" not in idx and n == "cif":
            idx["cif"] = i
        elif "adj" not in idx and (n == "tercero" or n.startswith("identidad del adjudica") or n == "adjudicatario"):
            idx["adj"] = i
    return idx


def _parsear(crudo, etiqueta):
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(crudo), data_only=True)
    mejor = None
    for ws in wb.worksheets:
        filas = [f for f in ws.iter_rows(values_only=True) if any(c not in (None, "") for c in f)]
        for i, f in enumerate(filas[:12]):
            idx = _columnas(f)
            if {"exp", "obj", "imp", "adj"} <= set(idx):
                if mejor is None or len(filas) - i > len(mejor[0]):
                    mejor = (filas[i + 1:], idx)
                break
    if mejor is None:
        raise ValueError(f"{etiqueta}: no se encontró una hoja con cabecera reconocible")
    filas, idx = mejor
    salida = []
    for f in filas:
        exp = _limpiar(f[idx["exp"]] if idx["exp"] < len(f) else "")
        if not re.match(r"^\d{6,}", exp):        # pie de página ("jueves, 23 de julio de 2026 Página 1 de 1")
            continue
        imp = _importe(f[idx["imp"]] if idx["imp"] < len(f) else None)
        if imp is None:
            continue
        salida.append({
            "exp": exp,
            "obj": _limpiar(f[idx["obj"]]),
            "imp": imp,
            "cif": _limpiar(f[idx["cif"]]) if "cif" in idx and idx["cif"] < len(f) else "",
            "adj": _limpiar(f[idx["adj"]]) if idx["adj"] < len(f) else "",
        })
    return salida


def main():
    paquetes = json.loads(_get(API).decode("utf-8"))["result"]["results"]
    trimestres = {}
    for p in paquetes:
        per = _periodo(p["name"])
        if not per or per < PRIMER_TRIMESTRE:
            continue
        xl = [r for r in p["resources"] if (r.get("format") or "").upper() in ("XLSX", "XLS")]
        if xl:
            trimestres[per] = (p["name"], xl[0]["url"])
    registros, repetidos = {}, 0
    for (y, q) in sorted(trimestres):
        nombre, url = trimestres[(y, q)]
        filas = _parsear(_get(url), nombre)
        fecha = f"{y}-{3 * (q - 1) + 1:02d}-01"
        for f in filas:
            rid = f"malaga::{f['exp']}"
            if rid in registros:          # mismo contrato en un informe posterior: se queda la 1.ª aparición
                repetidos += 1
                continue
            registros[rid] = {
                "id":               rid,
                "municipio":        "Málaga",
                "provincia":        "malaga",
                "fuente":           "malaga",
                "organisme":        "Ayuntamiento de Málaga",
                "adjudicatari":     f["adj"] or "No localizada",
                "nif":              f["cif"],
                "import_num":       round(f["imp"], 2),
                "data_adjudicacio": fecha,
                "tipus_contracte":  "",
                "descripcio":       f["obj"],
                "codi_cpv":         "",
                "exercici":         str(y),
            }
        print(f"  {y}-T{q}: {len(filas)} contratos ({nombre})", flush=True)
        time.sleep(0.2)
    if len(trimestres) < 15 or len(registros) < 3000:
        raise SystemExit(f"!! Solo {len(trimestres)} trimestres / {len(registros)} contratos: posible fallo del "
                         f"origen. No se toca {FICHERO}.")
    tmp = f"{FICHERO}.tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump({
            "generado": time.strftime("%Y-%m-%d"),
            "descripcion": ("Contratos menores del Ayuntamiento de Málaga, XLSX trimestrales del portal de datos "
                            "abiertos (CKAN). SIN fecha por contrato: data_adjudicacio = primer día del trimestre. "
                            "Base de IVA no homogénea entre informes. Ver actualizar_contratos_menores_malaga.py."),
            "registros": list(registros.values()),
        }, fh, ensure_ascii=False)
    os.replace(tmp, FICHERO)
    print(f"Hecho: {len(registros)} contratos de {len(trimestres)} trimestres ({repetidos} expedientes repetidos "
          f"entre trimestres, se queda la primera aparición) -> {FICHERO}")


if __name__ == "__main__":
    main()
