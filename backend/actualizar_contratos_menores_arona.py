# encoding: utf-8
"""
Contratos MENORES del Ayuntamiento de Arona (~85.000 hab., Tenerife, Canarias).

Fuente OFICIAL: `transparencia.arona.org` es la MISMA plataforma (Next.js + API `/api/proxy/obligaciones/...`)
que `transparencia.laspalmasgc.es` (ver actualizar_contratos_menores_laspalmasgc.py) -- una vez conocido el
patrón de esa plataforma, localizar el endpoint aquí fue mucho más rápido: visitando con Playwright la página
`/contratos/relacion-contratos-menores` (enlace encontrado en el listado de la sección "Contratos" del propio
portal) se ve directamente la petición a la API real, sin necesidad de interceptar ningún botón de descarga:

    https://transparencia.arona.org/api/proxy/obligaciones/datos-multiples-registros-por-ano/124/1/<año>/csv

(124 = id interno de la obligación "Relación de contratos menores", distinto del 88 usado en Las Palmas de
Gran Canaria -- cada entidad tiene sus propios ids). Es una URL pública normal, descargable con peticiones
HTTP directas.

**Mismo esquema y mismas limitaciones que Las Palmas GC**: columnas importe, ejercicio, url_origen (enlace a
PLACE), n_expediente, adjudicatario, tipo_contrato, cif_adjudicatario, _esExterno, _idLocal, _identidad --
ninguna fecha de adjudicación real, solo el ejercicio. La ventana de 5 años se aplica a nivel de AÑO completo:
se excluye 2021 entero por ambiguo frente al corte de 2021-09-01, se incluyen 2022-2026 completos.

**Filas duplicadas con `_esExterno` distinto**: algunos expedientes aparecen dos veces, con `tipo_contrato`
distinto (p. ej. "Obras" vs "Servicios") y `_esExterno` True/False -- se colapsan por `n_expediente` (mismo
patrón de deduplicación por id que ya usa Las Palmas GC), quedándose con la última fila leída.

Uso (desde backend/):
    python actualizar_contratos_menores_arona.py

Genera contratos_menores_arona.json.gz, que app.py carga al arrancar (ver _cargar_contratos_menores_arona)."""
import csv
import gzip
import io
import json
import os
import re
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "contratos_menores_arona.json.gz")
from alcance import alcance_desde
MENORES_DESDE_FECHA = alcance_desde()   # ventana móvil de 5 años (alcance.py), la misma que usa app.py

_ANOS = [2022, 2023, 2024, 2025, 2026]   # 2021 excluido por ambiguo (ver docstring)
_URL_BASE = ("https://transparencia.arona.org/api/proxy/obligaciones/"
             "datos-multiples-registros-por-ano/124/1/{anio}/csv")
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
    if re.match(r"^\d+\.\d{2}$", t):
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
                "id":               f"arona::{expediente}",
                "municipio":         "Arona",
                "provincia":         "santa_cruz_tenerife",
                "fuente":            "arona",
                "organisme":         "Ayuntamiento de Arona",
                "adjudicatari":      adjudicatario,
                "nif":               _limpiar(f.get("cif_adjudicatario")),
                "import_num":        round(_importe(f.get("importe")), 2),
                "data_adjudicacio":  "",   # esta fuente no publica fecha por contrato, ver docstring
                "tipus_contracte":   _limpiar(f.get("tipo_contrato")),
                "descripcio":        "",   # esta fuente no publica objeto/descripción del contrato
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
            "descripcion": ("Contratos menores del Ayuntamiento de Arona. Portal de transparencia (Next.js, "
                             "misma plataforma que Las Palmas de Gran Canaria), API de descarga CSV "
                             "encontrada con un navegador real (Playwright) visitando la página de la "
                             "obligación. Sin fecha por contrato (ventana de 5 años aplicada por ejercicio "
                             "completo, 2021 excluido por ambiguo). Sin descripción del objeto del contrato "
                             "(la fuente no la publica en este listado). "
                             "Ver actualizar_contratos_menores_arona.py."),
            "registros": list(existentes.values()),
        }, f, ensure_ascii=False)
    os.replace(tmp, FICHERO)

    print(f"\nHecho: {len(existentes)} registros en {FICHERO}.")


if __name__ == "__main__":
    main()
