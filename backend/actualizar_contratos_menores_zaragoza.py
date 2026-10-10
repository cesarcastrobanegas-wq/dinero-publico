# encoding: utf-8
"""
Contratos MENORES del Ayuntamiento de Zaragoza (~675.000 hab., Aragón).

Fuente OFICIAL: API REST propia del Ayuntamiento (no el estándar OCDS que documenta y que tiene la
paginación rota -- ver más abajo), documentada en su catálogo Swagger (zaragoza.es/sede/catalogo/api.json,
tag "Ayuntamiento: Contratacion publica"):

    https://www.zaragoza.es/sede/servicio/contratacion-publica/contrato.json?contratoMenor=true&start=<n>&rows=500

**Cómo se encontró (2026-09-30)**: la fuente que el propio Ayuntamiento documenta como "estándar" para
reutilizadores es su API OCDS (`.../ocds/award.json`, `.../ocds/contracting-process.json`), pero tiene la
paginación genuinamente rota -- el parámetro `start` se ignora (siempre devuelve los mismos registros) y
`rows` tiene un tope dese ~1300-1400 en `award`. El propio PDF de política de publicación de OCDS
(`Politica_Publicacion_OCDS.pdf`) menciona una "API no estándar... utilizada para los servicios de
visualización" -- esa es esta: `/servicio/contratacion-publica/contrato`, con paginación `start`/`rows` que
SÍ funciona (verificado: páginas de 500 sin solape real, `totalCount` estable) y un filtro explícito
`contratoMenor=true` (3.887 contratos menores en total en la fuente a fecha de la extracción, de searchable
Swagger vía zaragoza.es/sede/catalogo/api.json).

**Estructura de cada contrato**: cada `contrato` puede tener varias `ofertas` (una por licitador, cuando
aplica); la oferta ganadora tiene `ganador: true` y trae `fechaAdjudicacion`, `importeSinIVA`,
`importeConIVA` y el `empresa` (nombre + `nif`). Los contratos sin ninguna oferta ganadora (`Desierto`,
`Anulado`, todavía `En Licitación`) se descartan -- no hay adjudicatario que mostrar. La fecha de
adjudicación real vive en la oferta ganadora, NO en el campo `fechaAdjudicacion` de nivel superior del
contrato (ese casi siempre viene vacío en esta fuente). Importe: se usa `importeConIVA` (con IVA, la base
más común entre las fuentes ya conectadas del proyecto).

Uso (desde backend/):
    python actualizar_contratos_menores_zaragoza.py

Genera contratos_menores_zaragoza.json.gz, que app.py carga al arrancar (ver
_cargar_contratos_menores_zaragoza)."""
import gzip
import json
import os
import re
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "contratos_menores_zaragoza.json.gz")
from alcance import alcance_desde
MENORES_DESDE_FECHA = alcance_desde()   # ventana móvil de 5 años (alcance.py), la misma que usa app.py

_URL_BASE = "https://www.zaragoza.es/sede/servicio/contratacion-publica/contrato.json"
_ROWS_POR_PAGINA = 500   # tope real observado del servidor (rows=10000 igualmente devuelve 500)
_UA = "Mozilla/5.0 (compatible; dinero-publico-bot/1.0)"


def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def _limpiar(txt):
    return re.sub(r"\s+", " ", str(txt or "")).strip()


def _fecha_iso(valor):
    """'2023-08-21T00:00:00' -> '2023-08-21'."""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", str(valor or ""))
    return m.group(1) if m else ""


def _oferta_ganadora(contrato):
    for of in (contrato.get("ofertas") or []):
        if of.get("ganador"):
            return of
    return None


def _parsear_pagina(resultado):
    registros = []
    for c in resultado:
        ganadora = _oferta_ganadora(c)
        if not ganadora:
            continue   # Desierto / Anulado / En Licitación / sin adjudicatario -- nada que mostrar
        fecha = _fecha_iso(ganadora.get("fechaAdjudicacion") or c.get("fechaAdjudicacion")
                            or ganadora.get("fechaFormalizacion") or c.get("fechaFormalizacion"))
        if not fecha or fecha < MENORES_DESDE_FECHA:
            continue
        empresa = ganadora.get("empresa") or {}
        importe = ganadora.get("importeConIVA")
        if importe is None:
            importe = ganadora.get("importeSinIVA")
        registros.append({
            "id":               f"zaragoza::{c.get('id')}",
            "municipio":         "Zaragoza",
            "provincia":         "zaragoza",
            "fuente":            "zaragoza",
            "organisme":         "Ayuntamiento de Zaragoza",
            "adjudicatari":      _limpiar(empresa.get("nombre") or ganadora.get("adjudicatario")) or "No localizada",
            "nif":               _limpiar(empresa.get("nif") or ganadora.get("nif")),
            "import_num":        round(float(importe), 2) if importe is not None else 0.0,
            "data_adjudicacio":  fecha,
            "tipus_contracte":   _limpiar((c.get("type") or {}).get("title")),
            "descripcio":        _limpiar(c.get("objeto") or c.get("title")),
            "codi_cpv":          "|".join(str(x.get("id")) for x in (c.get("cpv") or []) if x.get("id")),
            "exercici":          fecha[:4],
        })
    return registros


def _guardar(existentes):
    tmp = f"{FICHERO}.tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump({
            "generado": time.strftime("%Y-%m-%d"),
            "descripcion": ("Contratos menores del Ayuntamiento de Zaragoza, API oficial propia "
                             "(contratacion-publica/contrato.json?contratoMenor=true; no la OCDS estándar, "
                             "que tiene la paginación rota -- ver actualizar_contratos_menores_zaragoza.py). "
                             "Fecha real de adjudicación (de la oferta ganadora), importe con IVA, NIF del "
                             "adjudicatario, CPV."),
            "registros": list(existentes.values()),
        }, f, ensure_ascii=False)
    os.replace(tmp, FICHERO)


def main():
    existentes = {}
    start = 0
    total_count = None
    while total_count is None or start < total_count:
        url = f"{_URL_BASE}?contratoMenor=true&start={start}&rows={_ROWS_POR_PAGINA}"
        print(f"Descargando start={start}...", flush=True)
        try:
            d = _get_json(url)
        except Exception as e:
            print(f"  !! start={start}: error de descarga ({type(e).__name__}: {e})", flush=True)
            break
        total_count = d.get("totalCount", 0)
        resultado = d.get("result", [])
        if not resultado:
            break
        registros = _parsear_pagina(resultado)
        for r in registros:
            existentes[r["id"]] = r
        print(f"  start={start}: {len(resultado)} contratos recibidos, {len(registros)} en ventana "
              f"(totalCount fuente: {total_count})", flush=True)
        _guardar(existentes)
        start += _ROWS_POR_PAGINA

    print(f"\nHecho: {len(existentes)} registros en {FICHERO}.")


if __name__ == "__main__":
    main()
