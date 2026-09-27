# encoding: utf-8
"""
Contratos MENORES del Ayuntamiento de Alicante (~337.000 hab., Comunitat Valenciana -- segundo municipio por
población de los seis sin agregador regional que se investigan desde el 2026-09-27, ver LIMITACIONES_COBERTURA.md).

Fuente OFICIAL: "Informe trimestral de contratos menores" (Junta de Gobierno Local), publicado en formato ODS
(OpenDocument Spreadsheet) en el portal de transparencia (www.alicante.es/es/gobierno-abierto/transparencia/
contratacion-publica/contratos). Un fichero por trimestre desde 2015; aquí solo se descargan los necesarios para
el alcance de 5 años (desde el 3er trimestre de 2021).

Estructura real del ODS (verificada en vivo, 2026-09-28): unas filas de cabecera libre (título, entidad, año,
trimestre, fecha de generación) antes de la fila de columnas real -- se localiza buscando la fila cuya primera
celda sea exactamente "NIF" (mismo tipo de robustez que la fila de título del CSV de Madrid 2023, ver
actualizar_contratos_menores_madrid_capital.py). Columnas: NIF, Adjudicatario, Expediente, Objeto del contrato,
Fecha contrato (DD-MES_ES-AAAA, p.ej. "10-ABR-2026"), Precio sin impuestos, Precio con impuestos, Duración
contrato. El Expediente SÍ es una clave única real por contrato aquí (a diferencia de Valencia capital, donde el
número de expediente agrupa varios contratos distintos -- verificado con un chequeo de colisiones antes de
guardar, ver `main`).

Los enlaces a cada ODS trimestral NO siguen un patrón de URL predecible (la carpeta de subida cambia según
cuándo se publicó cada informe, no según el año/trimestre que describe) -- se han recogido a mano navegando las
páginas "contratos-menores-del-ayuntamiento-<año>-trimestres"; si un trimestre nuevo no aparece en `FICHEROS`
hay que localizar su URL a mano en esa página y añadirlo aquí.

Uso (desde backend/):
    python actualizar_contratos_menores_alicante.py

Genera contratos_menores_alicante.json.gz, que app.py carga al arrancar (ver
_cargar_contratos_menores_alicante)."""
import gzip
import io
import json
import os
import re
import sys
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "contratos_menores_alicante.json.gz")
MENORES_DESDE_FECHA = "2021-09-01"   # mismo corte que MENORES_DESDE_FECHA en app.py -- mantener sincronizado a mano

# (año, trimestre) -> URL exacta del ODS (recogidas a mano, ver docstring del módulo)
FICHEROS = {
    (2021, 3): "https://www.alicante.es/sites/default/files/documentos/202110/menores-3trim.ods",
    (2021, 4): "https://www.alicante.es/sites/default/files/documentos/202201/informe-menores.ods",
    (2022, 1): "https://www.alicante.es/sites/default/files/documentos/202210/informe-menores-2022-1trim.ods",
    (2022, 2): "https://www.alicante.es/sites/default/files/documentos/202210/informe-menores-2022-2trim.ods",
    (2022, 3): "https://www.alicante.es/sites/default/files/documentos/202210/informe-menores-2022-3trim.ods",
    (2022, 4): "https://www.alicante.es/sites/default/files/documentos/202302/informe-menores-2022-4trim.ods",
    (2023, 1): "https://www.alicante.es/sites/default/files/documentos/202306/informe-menores-2023-1trim.ods",
    (2023, 2): "https://www.alicante.es/sites/default/files/documentos/202308/informe-menores-2023-2trim.ods",
    (2023, 3): "https://www.alicante.es/sites/default/files/documentos/202310/informe-menores-2023-3trim.ods",
    (2023, 4): "https://www.alicante.es/sites/default/files/documentos/202402/informe-menores-2023-4trim-definitivo.ods",
    (2024, 1): "https://www.alicante.es/sites/default/files/documentos/202405/informe-menores-2024-1trim.ods",
    (2024, 2): "https://www.alicante.es/sites/default/files/documentos/202407/informe-menores-2trim.ods",
    (2024, 3): "https://www.alicante.es/sites/default/files/documentos/202410/informe-menores-3trim.ods",
    (2024, 4): "https://www.alicante.es/sites/default/files/documentos/202502/informe-menores-2024-4trim.ods",
    (2025, 1): "https://www.alicante.es/sites/default/files/documentos/202505/informe-menores-1trim.ods",
    (2025, 2): "https://www.alicante.es/sites/default/files/documentos/202507/informe-menores-2trim.ods",
    (2025, 3): "https://www.alicante.es/sites/default/files/documentos/202510/informe-menores-3trim.ods",
    (2025, 4): "https://www.alicante.es/sites/default/files/documentos/202603/informe-menores-4trim.ods",
    (2026, 1): "https://www.alicante.es/sites/default/files/documentos/202605/informemenores1trim.ods",
    (2026, 2): "https://www.alicante.es/sites/default/files/documento/documentos/informe-menores-2trim_1.ods",
}

_MESES = {"ENE": "01", "FEB": "02", "MAR": "03", "ABR": "04", "MAY": "05", "JUN": "06",
          "JUL": "07", "AGO": "08", "SEP": "09", "OCT": "10", "NOV": "11", "DIC": "12"}
_UA = "Mozilla/5.0 (compatible; dinero-publico-bot/1.0)"


def _fecha_iso(txt):
    """'10-ABR-2026' -> '2026-04-10'"""
    m = re.match(r"^(\d{1,2})-([A-Z]{3})-(\d{4})$", (txt or "").strip().upper())
    if not m:
        return ""
    d, mes_es, y = m.groups()
    mes = _MESES.get(mes_es)
    if not mes:
        return ""
    return f"{y}-{mes}-{d.zfill(2)}"


def _importe(txt):
    """'2.772' -> 2772.0, '1.202,91 €' -> 1202.91 (formato español: punto=miles, coma=decimales)."""
    limpio = (txt or "").replace("€", "").strip().replace(".", "").replace(",", ".")
    try:
        return float(limpio)
    except ValueError:
        return 0.0


def _descargar(url):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _filas_ods(crudo):
    """Extrae todas las filas (lista de listas de texto) de la primera hoja de un ODS, en memoria (sin
    escribir a disco)."""
    from odf.opendocument import load
    from odf.table import Table, TableRow, TableCell
    from odf.text import P
    doc = load(io.BytesIO(crudo))
    tabla = doc.spreadsheet.getElementsByType(Table)[0]
    filas = []
    for row in tabla.getElementsByType(TableRow):
        celdas = row.getElementsByType(TableCell)
        vals = []
        for c in celdas:
            texto = "".join(str(p) for p in c.getElementsByType(P))
            # repetición de celda (ODS comprime celdas vacías repetidas) -- ignorar, no aporta filas de datos
            vals.append(texto)
        filas.append(vals)
    return filas


def _parsear_trimestre(anio, trimestre, crudo):
    filas = _filas_ods(crudo)
    idx_cabecera = next((i for i, f in enumerate(filas) if f and f[0].strip() == "NIF"), None)
    if idx_cabecera is None:
        print(f"  !! {anio}T{trimestre}: no se encontró la fila de cabecera ('NIF'), fichero omitido", flush=True)
        return []
    registros = []
    for fila in filas[idx_cabecera + 1:]:
        if len(fila) < 7 or not (fila[0] or "").strip():
            continue
        nif, adjudicatari, expediente, objeto, fecha_txt, precio_sin, precio_con = fila[:7]
        fecha = _fecha_iso(fecha_txt)
        if not fecha or fecha < MENORES_DESDE_FECHA:
            continue
        registros.append({
            "id":               f"alicante::{expediente.strip()}",
            "municipio":         "Alicante",
            "provincia":         "alicante",
            "fuente":            "alicante",
            "organisme":         "Junta de Gobierno Local del Ayuntamiento de Alicante",
            "adjudicatari":      adjudicatari.strip() or "No localizada",
            "nif":               nif.strip(),
            "import_num":        round(_importe(precio_sin), 2),
            "data_adjudicacio":  fecha,
            "tipus_contracte":   "",
            "descripcio":        objeto.strip(),
            "codi_cpv":          "",
            "exercici":          fecha[:4],
        })
    return registros


def _guardar(existentes):
    tmp = f"{FICHERO}.tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump({
            "generado": time.strftime("%Y-%m-%d"),
            "descripcion": ("Contratos menores del Ayuntamiento de Alicante, informes trimestrales oficiales "
                             "en ODS (Junta de Gobierno Local). data_adjudicacio = 'Fecha contrato' real del "
                             "informe. Ver actualizar_contratos_menores_alicante.py."),
            "registros": list(existentes.values()),
        }, f, ensure_ascii=False)
    os.replace(tmp, FICHERO)


def main():
    existentes = {}
    total_bruto = 0
    for (anio, trimestre), url in sorted(FICHEROS.items()):
        print(f"Descargando {anio}T{trimestre}...", flush=True)
        try:
            crudo = _descargar(url)
        except Exception as e:
            print(f"  !! {anio}T{trimestre}: error de descarga ({type(e).__name__}: {e})", flush=True)
            continue
        registros = _parsear_trimestre(anio, trimestre, crudo)
        total_bruto += len(registros)
        colisiones = sum(1 for r in registros if r["id"] in existentes
                          and existentes[r["id"]]["descripcio"] != r["descripcio"])
        if colisiones:
            print(f"  !! {anio}T{trimestre}: {colisiones} claves de expediente repetidas con objeto DISTINTO "
                  "-- posible colisión real, revisar a mano (mismo problema que Valencia capital)", flush=True)
        for r in registros:
            existentes[r["id"]] = r
        print(f"  {anio}T{trimestre}: {len(registros)} contratos en ventana", flush=True)
        _guardar(existentes)

    print(f"\nHecho: {len(existentes)} registros en {FICHERO} ({total_bruto} filas brutas procesadas, "
          f"{total_bruto - len(existentes)} colapsadas por clave repetida -- si es alto, revisar unicidad "
          "del Expediente).")


if __name__ == "__main__":
    main()
