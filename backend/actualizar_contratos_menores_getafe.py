# encoding: utf-8
"""
Contratos MENORES del Ayuntamiento de Getafe (~185.000 hab., Comunidad de Madrid).

Fuente OFICIAL: portal de gobierno abierto de Getafe (gobiernoabierto.getafe.es), construido sobre la
plataforma Gobierto (gobierto.es, usada por varios ayuntamientos españoles) -- expone una API tipo "SQL sobre
CSV" descubierta inspeccionando el dashboard "Contratos y licitaciones"
(gobiernoabierto.getafe.es/visualizaciones/contratos, atributo `data-contracts-endpoint` del HTML):

    https://gobiernoabierto.getafe.es/api/v1/data/data.csv?sql=select * from contratos where minor_contract='t'

Devuelve TODOS los contratos (no solo menores) con un campo booleano `minor_contract` -- se filtra en la propia
consulta sin descargar de más. Es, con diferencia, la fuente más rica de las conectadas hasta ahora en esta
ronda: trae CPV (`cpvs`), tipo de contrato, categoría e importes con y sin impuestos. Limitación real: NO
publica NIF/CIF del adjudicatario (solo el nombre en `assignee`), igual que RPC Cataluña/Euskadi formales.

Campo de fecha usado: `award_date` (fecha de adjudicación formal). Se ha comprobado que varios contratos
comparten la misma fecha en lotes de decenas -- consistente con sesiones periódicas de Junta de Gobierno Local
que aprueban varios contratos menores de golpe, no un artefacto de carga por lotes (contrastado con
`gobierto_start_date`, que sí varía contrato a contrato y no coincide con `award_date`, luego son campos
distintos con significados distintos: inicio de ejecución vs. fecha de aprobación formal).

Uso (desde backend/):
    python actualizar_contratos_menores_getafe.py

Genera contratos_menores_getafe.json.gz, que app.py carga al arrancar (ver _cargar_contratos_menores_getafe)."""
import csv
import gzip
import io
import json
import os
import time
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "contratos_menores_getafe.json.gz")
MENORES_DESDE_FECHA = "2021-09-01"   # mismo corte que MENORES_DESDE_FECHA en app.py -- mantener sincronizado a mano

API_URL = "https://gobiernoabierto.getafe.es/api/v1/data/data.csv"
SQL = "select * from contratos where minor_contract='t'"
_UA = "Mozilla/5.0 (compatible; dinero-publico-bot/1.0)"


def _descargar():
    url = f"{API_URL}?sql={urllib.parse.quote(SQL)}"
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8-sig")


def _importe(fila):
    """final_amount (con impuestos) como importe principal -- si falta o es 0, cae a initial_amount."""
    for clave in ("final_amount", "initial_amount"):
        try:
            v = float(fila.get(clave) or 0)
            if v:
                return round(v, 2)
        except ValueError:
            continue
    return 0.0


def _fila_a_contrato(fila):
    fecha = (fila.get("award_date") or "").strip()
    return {
        "id":               f"getafe::{fila['id']}",
        "municipio":         "Getafe",
        "provincia":         "madrid",
        "fuente":            "getafe",
        "organisme":         fila.get("contractor") or "Ayuntamiento de Getafe",
        "adjudicatari":      (fila.get("assignee") or "").strip() or "No localizada",
        "nif":               "",   # no publicado por esta fuente (ver docstring)
        "import_num":        _importe(fila),
        "data_adjudicacio":  fecha,
        "tipus_contracte":   fila.get("contract_type") or "",
        "descripcio":        (fila.get("title") or "").strip(),
        "codi_cpv":          (fila.get("cpvs") or "").strip(),
        "exercici":          fecha[:4] if fecha else "",
    }


def _guardar(registros):
    tmp = f"{FICHERO}.tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump({
            "generado": time.strftime("%Y-%m-%d"),
            "descripcion": ("Contratos menores del Ayuntamiento de Getafe, API pública de la plataforma "
                             "Gobierto (gobiernoabierto.getafe.es). data_adjudicacio = 'award_date' (fecha de "
                             "adjudicación formal). Sin NIF del adjudicatario (no publicado por esta fuente). "
                             "Ver actualizar_contratos_menores_getafe.py."),
            "registros": registros,
        }, f, ensure_ascii=False)
    os.replace(tmp, FICHERO)


def main():
    print("Descargando contratos menores de Getafe...", flush=True)
    texto = _descargar()
    lector = csv.DictReader(io.StringIO(texto))
    filas = list(lector)
    print(f"  {len(filas)} filas brutas (minor_contract='t')", flush=True)

    registros = []
    descartados = 0
    for fila in filas:
        c = _fila_a_contrato(fila)
        if not c["data_adjudicacio"] or c["data_adjudicacio"] < MENORES_DESDE_FECHA:
            descartados += 1
            continue
        registros.append(c)

    _guardar(registros)
    print(f"\nHecho: {len(registros)} registros en {FICHERO} ({descartados} descartados por fecha < "
          f"{MENORES_DESDE_FECHA} o sin fecha).")


if __name__ == "__main__":
    main()
