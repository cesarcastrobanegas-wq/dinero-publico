# encoding: utf-8
"""
Contratos MENORES del Ayuntamiento de Las Palmas de Gran Canaria (~382.000 hab., la mayor ciudad de Canarias).

Fuente OFICIAL: `transparencia.laspalmasgc.es` es una SPA moderna (Next.js) que NO sirve los datos en el HTML
inicial (ver LIMITACIONES_COBERTURA.md, intento previo con la técnica `/_next/data/...`, que solo trae
metadatos de sección, no las filas). **Se encontró la API real usando un navegador de verdad (Playwright,
2026-09-30)**: se interceptaron las peticiones de red mientras la página cargaba y, sobre todo, al pulsar el
botón "Descargar nuestros datos" (csv/ods/excel/json/xml) que la propia página ofrece -- eso reveló el patrón
real:

    https://transparencia.laspalmasgc.es/api/proxy/obligaciones/datos-multiples-registros-por-ano/88/1/<año>/csv

(88 = id interno de la obligación "Relación de contratos menores"; el "1" no parece afectar al resultado,
probado con "2" y devuelve el mismo total). Es una URL PÚBLICA normal: una vez encontrada, se descarga con
peticiones HTTP directas, sin necesidad de navegador para las descargas en sí.

**Sin fecha por contrato**: las columnas son importe, ejercicio, url_origen (enlace a PLACE), denominacion
(objeto), n_expediente, adjudicatario, tipo_contrato, cif_adjudicatario (no en todos los años, ver abajo),
organo_de_contratacion -- ninguna fecha de adjudicación real. La ventana de 5 años se aplica a nivel de AÑO
completo (ejercicio), igual que Toledo/Fuente Álamo: se excluye 2021 entero por ambiguo frente al corte de
2021-09-01 (podría incluir enero-agosto de 2021, anteriores a la ventana, sin forma de distinguirlo fila a
fila), y se incluyen 2022-2026 completos.

**El conjunto de columnas varía por año** (algunos años no traen `cif_adjudicatario` en absoluto -- verificado
en 2023, 0/619 filas con CIF; otros tienen `_idLocal`/`_identidad` en vez de `_idExterno`): se lee por NOMBRE
de columna con `csv.DictReader`, nunca por posición, y se usa `.get()` para los campos que pueden faltar.

Uso (desde backend/):
    python actualizar_contratos_menores_laspalmasgc.py

Genera contratos_menores_laspalmasgc.json.gz, que app.py carga al arrancar (ver
_cargar_contratos_menores_laspalmasgc)."""
import csv
import gzip
import io
import json
import os
import re
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "contratos_menores_laspalmasgc.json.gz")
MENORES_DESDE_FECHA = "2021-09-01"   # mismo corte que MENORES_DESDE_FECHA en app.py -- mantener sincronizado a mano

_ANOS = [2022, 2023, 2024, 2025, 2026]   # 2021 excluido por ambiguo (ver docstring)
_URL_BASE = ("https://transparencia.laspalmasgc.es/api/proxy/obligaciones/"
             "datos-multiples-registros-por-ano/88/1/{anio}/csv")
_UA = "Mozilla/5.0 (compatible; dinero-publico-bot/1.0)"


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _limpiar(txt):
    return re.sub(r"\s+", " ", str(txt or "")).strip()


def _importe(valor):
    t = re.sub(r"[^\d.,]", "", str(valor or ""))
    if not t:
        return 0.0
    if re.match(r"^\d+\.\d{2}$", t):   # formato inglés plano, por si acaso
        return float(t)
    m = re.match(r"^(.+)[.,](\d{2})$", t)
    if m:
        entero = re.sub(r"[.,]", "", m.group(1))
        try:
            return float(f"{entero}.{m.group(2)}")
        except ValueError:
            pass
    try:
        return float(re.sub(r"[.,]", "", t))
    except ValueError:
        return 0.0


def main():
    existentes = {}
    for anio in _ANOS:
        url = _URL_BASE.format(anio=anio)
        print(f"Descargando {anio}...", flush=True)
        try:
            crudo = _get(url)
        except Exception as e:
            print(f"  !! {anio}: error de descarga ({type(e).__name__}: {e})", flush=True)
            continue
        texto = crudo.decode("utf-8-sig")
        filas = list(csv.DictReader(io.StringIO(texto), delimiter=";"))
        registros = []
        for f in filas:
            adjudicatario = _limpiar(f.get("adjudicatario"))
            if not adjudicatario:
                continue
            expediente = _limpiar(f.get("n_expediente")) or f"{anio}-{len(registros)}"
            registros.append({
                "id":               f"laspalmasgc::{expediente}",
                "municipio":         "Las Palmas de Gran Canaria",
                "provincia":         "las_palmas",
                "fuente":            "laspalmasgc",
                "organisme":         "Ayuntamiento de Las Palmas de Gran Canaria",
                "adjudicatari":      adjudicatario,
                "nif":               _limpiar(f.get("cif_adjudicatario")),
                "import_num":        round(_importe(f.get("importe")), 2),
                "data_adjudicacio":  "",   # esta fuente no publica fecha por contrato, ver docstring
                "tipus_contracte":   _limpiar(f.get("tipo_contrato")),
                "descripcio":        _limpiar(f.get("denominacion")),
                "codi_cpv":          "",
                "exercici":          str(anio),
            })
        for r in registros:
            existentes[r["id"]] = r
        print(f"  {anio}: {len(registros)} contratos ({len(filas)} filas en el CSV de origen)", flush=True)

    tmp = f"{FICHERO}.tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump({
            "generado": time.strftime("%Y-%m-%d"),
            "descripcion": ("Contratos menores del Ayuntamiento de Las Palmas de Gran Canaria. Portal de "
                             "transparencia (Next.js), API de descarga CSV encontrada con un navegador real "
                             "(Playwright) interceptando la petición del botón de descarga. Sin fecha por "
                             "contrato (ventana de 5 años aplicada por ejercicio completo, 2021 excluido por "
                             "ambiguo). Importe con IVA (así lo indica la propia obligación de transparencia). "
                             "Ver actualizar_contratos_menores_laspalmasgc.py."),
            "registros": list(existentes.values()),
        }, f, ensure_ascii=False)
    os.replace(tmp, FICHERO)

    print(f"\nHecho: {len(existentes)} registros en {FICHERO}.")


if __name__ == "__main__":
    main()
