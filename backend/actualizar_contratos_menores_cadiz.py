# encoding: utf-8
"""
Contratos MENORES del Ayuntamiento de Cádiz (~110.000 hab., Andalucía) -- SOLO 2023.

Fuente OFICIAL: https://transparencia.cadiz.es/contratos-menores/ -- "Listado de contratos menores del
Ayuntamiento, ejercicio 2023": un PDF (157 páginas) con tabla real de 6 columnas (OBJETO DEL CONTRATO / Código
completo / FECHA ADJUDICACIÓN / TIPO CONTRATO MENOR / ADJUDICATARIO / IMPORTE ADJUDICACIÓN (IVA incl.)). Es el
ÚNICO listado propio que publica el Ayuntamiento: para el resto de años la página remite a la Plataforma de
Contratación del Estado ("Toda la información en la Plataforma de Contratación del Estado > Junta de Gobierno del
Ayuntamiento de Cádiz"). Localizado en la auditoría de DATOS_PETICION_MENORES.md §5.

Verificado en crudo (2026-09-29): pdfplumber extrae la tabla limpia en todas las páginas, con la cabecera
repetida en cada una. Fecha real por contrato (aaaa/mm/dd; algunos contratos del expediente 2023 se adjudican en
enero de 2024). Importe con IVA. Sin NIF. Clave: "Código completo" (2023/NNN).

Uso (desde backend/):
    python actualizar_contratos_menores_cadiz.py

Genera contratos_menores_cadiz.json.gz, que app.py carga al arrancar (_cargar_contratos_menores_cadiz)."""
import gzip
import io
import json
import os
import re
import time
import unicodedata
import urllib.request
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "contratos_menores_cadiz.json.gz")
MENORES_DESDE_FECHA = "2021-09-01"   # mismo corte que MENORES_DESDE_FECHA en app.py -- mantener sincronizado a mano
PDF_2023 = "https://transparencia.cadiz.es/wp-content/uploads/2024/05/Contratos-Menores-Ayuntamiento-Cadiz-2023.pdf"
_UA = "Mozilla/5.0 (compatible; dinero-publico-bot/1.0)"


def _norm(txt):
    t = unicodedata.normalize("NFD", str(txt or "").lower())
    return " ".join("".join(c for c in t if unicodedata.category(c) != "Mn").split())


def _limpiar(txt):
    return " ".join(str(txt or "").split())


def _importe(txt):
    t = str(txt or "").replace("€", "").replace(" ", "").strip()
    if not t:
        return None
    t = t.replace(".", "").replace(",", ".") if "," in t else t
    try:
        return float(t)
    except ValueError:
        return None


def _fecha(txt):
    m = re.search(r"(\d{4})/(\d{1,2})/(\d{1,2})", str(txt or ""))
    if not m:
        return ""
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def main():
    import pdfplumber
    req = urllib.request.Request(PDF_2023, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        crudo = r.read()
    registros, filas_datos, descartadas = {}, 0, 0
    with pdfplumber.open(io.BytesIO(crudo)) as pdf:
        texto = " ".join(p.extract_text() or "" for p in pdf.pages)
        for p in pdf.pages:
            for t in p.extract_tables():
                for f in t:
                    if not f or _norm(f[0]).startswith("objeto del contrat"):
                        continue
                    if len(f) < 6 or not re.match(r"^20\d\d/\d+$", _limpiar(f[1])):
                        continue
                    filas_datos += 1
                    codigo, fecha, imp = _limpiar(f[1]), _fecha(f[2]), _importe(f[5])
                    adj = _limpiar(f[4])
                    if not fecha or imp is None or not adj:
                        descartadas += 1
                        continue
                    rid = f"cadiz::{codigo}::{_norm(adj)[:30]}"
                    registros[rid] = {
                        "id":               rid,
                        "municipio":        "Cádiz",
                        "provincia":        "cadiz",
                        "fuente":           "cadiz",
                        "organisme":        "Ayuntamiento de Cádiz",
                        "adjudicatari":     adj,
                        "nif":              "",
                        "import_num":       round(imp, 2),
                        "data_adjudicacio": fecha,
                        "tipus_contracte":  _limpiar(f[3]),
                        "descripcio":       _limpiar(f[0]),
                        "codi_cpv":         "",
                        "exercici":         fecha[:4],
                    }
    codigos_texto = len(set(re.findall(r"\b20\d\d/\d{1,5}\b", texto)))
    print(f"{filas_datos} filas de datos, {len(registros)} contratos, {descartadas} descartadas; códigos 20XX/NNN "
          f"distintos en el texto: {codigos_texto}")
    if len(registros) < 800 or abs(filas_datos - codigos_texto) > 0.05 * codigos_texto:
        raise SystemExit(f"!! Recuento incoherente o insuficiente. No se toca {FICHERO}.")
    tmp = f"{FICHERO}.tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump({
            "generado": time.strftime("%Y-%m-%d"),
            "descripcion": ("Contratos menores del Ayuntamiento de Cádiz, ejercicio 2023 (único listado propio "
                            "publicado). Fecha real, importe con IVA, sin NIF. Ver actualizar_contratos_menores_cadiz.py."),
            "registros": list(registros.values()),
        }, fh, ensure_ascii=False)
    os.replace(tmp, FICHERO)
    print(f"Hecho -> {FICHERO}")


if __name__ == "__main__":
    main()
