# encoding: utf-8
"""
Contratos MENORES del Ayuntamiento de Gijón/Xixón (~270.000 hab., Asturias) y su sector público municipal.

Fuente OFICIAL: dataset abierto "Contratos menores adjudicados" del portal de datos abiertos del Ayuntamiento
(opendata.gijon.es, id=725; el mismo que muestra https://www.gijon.es/es/datos/contrataciones_menores_adjudicadas
y el OpenDataSoft observa.gijon.es). Un único TSV con TODO el histórico desde 2018 (~64.000 filas, comprobado
2026-09-29), actualizado casi a diario. Localizado en la auditoría de las 29 ciudades >100.000 hab. sin fuente
(DATOS_PETICION_MENORES.md §5).

Campos que se usan (verificados en crudo):
- FECHA_ADJUDICACION "dd/mm/aa" -> fecha real de adjudicación por contrato (1 sola fila sin fecha en todo el
  dataset; se descarta).
- PRECIO_DE_ADJUDICACIÓN: importe CON IVA (comprobado fila a fila: precio = base + IMPORTE_DEL_IVA, p.ej.
  169,40 = 140,00 + 29,40).
- PODER_ADJUDICADOR: el Ayuntamiento y 8 entes de su sector público (Fundación Municipal de Cultura, EMTUSA,
  Divertia, Patronato Deportivo...) -- se guardan todos, con el ente real en `organisme`, igual que RPC/Euskadi.
- CODIGO_CONTRATO + LOTE: clave única real (0 repetidas en la ventana de 5 años).
- FASE_DEL_CONTRATO es siempre "ADJUDICADO" y PROCEDIMIENTO siempre "Contrato menor" (verificado): no hace
  falta filtrar anulados.

Uso (desde backend/):
    python actualizar_contratos_menores_gijon.py

Genera contratos_menores_gijon.json.gz, que app.py carga al arrancar (_cargar_contratos_menores_gijon)."""
import csv
import gzip
import io
import json
import os
import time
import urllib.request
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "contratos_menores_gijon.json.gz")
MENORES_DESDE_FECHA = "2021-09-01"   # mismo corte que MENORES_DESDE_FECHA en app.py -- mantener sincronizado a mano
TSV_URL = "https://opendata.gijon.es/descargar.php?id=725&tipo=TSV"
_UA = "Mozilla/5.0 (compatible; dinero-publico-bot/1.0)"
# Salvaguarda: el dataset tenía ~37.000 filas en ventana al conectarlo. Si una descarga trae muchas menos, es un
# fallo del origen (fichero truncado, página de error) y NO se sobrescribe lo que ya había.
MINIMO_FILAS_EN_VENTANA = 20000


def _num(txt):
    t = (txt or "").strip()
    if not t:
        return None
    try:
        return float(t.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _fecha(txt):
    try:
        return datetime.strptime((txt or "").strip(), "%d/%m/%y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _limpiar(txt):
    return " ".join(str(txt or "").split())


def main():
    req = urllib.request.Request(TSV_URL, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        crudo = r.read()
    texto = crudo.decode("utf-8", errors="replace")
    filas = list(csv.DictReader(io.StringIO(texto), delimiter="\t"))
    if not filas or "CODIGO_CONTRATO" not in filas[0]:
        raise SystemExit(f"!! La descarga no es el TSV esperado ({len(crudo)} bytes). No se toca {FICHERO}.")

    registros, sin_fecha, sin_importe = {}, 0, 0
    for f in filas:
        fecha = _fecha(f.get("FECHA_ADJUDICACION"))
        if not fecha:
            sin_fecha += 1
            continue
        if fecha < MENORES_DESDE_FECHA:
            continue
        importe = _num(f.get("PRECIO_DE_ADJUDICACIÓN"))
        if importe is None:
            sin_importe += 1
            continue
        codigo, lote = _limpiar(f.get("CODIGO_CONTRATO")), _limpiar(f.get("LOTE"))
        rid = f"gijon::{codigo}::{lote}" if lote else f"gijon::{codigo}"
        registros[rid] = {
            "id":               rid,
            "municipio":        "Gijón",
            "provincia":        "asturias",
            "fuente":           "gijon",
            "organisme":        _limpiar(f.get("PODER_ADJUDICADOR")) or "Ayuntamiento de Gijón",
            "adjudicatari":     _limpiar(f.get("IDENTIDAD_DEL_ADJUDICATARIO")) or "No localizada",
            "nif":              _limpiar(f.get("CIF_ADJUDICATARIO")),
            "import_num":       round(importe, 2),
            "data_adjudicacio": fecha,
            "tipus_contracte":  _limpiar(f.get("TIPO_DE_CONTRATO")),
            "descripcio":       _limpiar(f.get("OBJETO_DEL_CONTRATO")),
            "codi_cpv":         "",
            "exercici":         fecha[:4],
        }

    if len(registros) < MINIMO_FILAS_EN_VENTANA:
        raise SystemExit(f"!! Solo {len(registros)} filas en ventana (< {MINIMO_FILAS_EN_VENTANA}): posible fallo "
                         f"del origen. No se toca {FICHERO}.")
    tmp = f"{FICHERO}.tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump({
            "generado": time.strftime("%Y-%m-%d"),
            "descripcion": ("Contratos menores del Ayuntamiento de Gijón y su sector público municipal, dataset "
                            "abierto oficial opendata.gijon.es id=725 (TSV). Importe adjudicado CON IVA. Ver "
                            "actualizar_contratos_menores_gijon.py."),
            "registros": list(registros.values()),
        }, fh, ensure_ascii=False)
    os.replace(tmp, FICHERO)
    print(f"Hecho: {len(registros)} contratos en ventana (de {len(filas)} filas; {sin_fecha} sin fecha y "
          f"{sin_importe} sin importe descartadas) -> {FICHERO}")


if __name__ == "__main__":
    main()
