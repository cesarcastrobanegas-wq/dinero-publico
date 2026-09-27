# encoding: utf-8
"""
Contratos MENORES del Ayuntamiento de Leganés (~187.000 hab., Comunidad de Madrid).

Fuente OFICIAL: informes mensuales/trimestrales en XLSX del portal de transparencia
(www.leganes.org/web/transparencia/contratos-menores). Mismo formato EXACTO que los ODS de Alicante --
probablemente una plantilla común (Comunidad de Madrid o estatal): NIF, Adjudicatario, Expediente, Objeto del
contrato, Fecha contrato (DD-MES_ES-AAAA), Precio sin impuestos, Precio con impuestos, Duración contrato. Aquí
el Expediente SÍ es clave única real (mismo patrón que Alicante, distinto de Valencia capital).

Los enlaces de descarga de la página índice usan IDs opacos sin relación con el periodo que describen
(`/documents/113177/250360/0_54949_1.xls/<uuid>`) -- el periodo solo se conoce por el TEXTO del enlace ("Menores
julio 2026", "Menores 2Trimestre 2023"...). Por eso este script, a diferencia de los de Madrid/Alicante,
**recorre la página índice en cada ejecución** en vez de guardar un diccionario fijo de URLs: localiza cada
enlace por su texto, sin asumir un patrón de URL. El filtro de 5 años real se aplica sobre la fecha de cada
FILA (columna "Fecha contrato"), no sobre el periodo del fichero -- así un error al identificar qué mes es cada
fichero no puede colar contratos fuera de ventana ni perder los que sí están dentro.

Uso (desde backend/):
    python actualizar_contratos_menores_leganes.py

Genera contratos_menores_leganes.json.gz, que app.py carga al arrancar (ver
_cargar_contratos_menores_leganes)."""
import gzip
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "contratos_menores_leganes.json.gz")
MENORES_DESDE_FECHA = "2021-09-01"   # mismo corte que MENORES_DESDE_FECHA en app.py -- mantener sincronizado a mano

INDICE_URL = "https://www.leganes.org/web/transparencia/contratos-menores"
_MESES = {"ENE": "01", "FEB": "02", "MAR": "03", "ABR": "04", "MAY": "05", "JUN": "06",
          "JUL": "07", "AGO": "08", "SEP": "09", "OCT": "10", "NOV": "11", "DIC": "12"}
_UA = "Mozilla/5.0 (compatible; dinero-publico-bot/1.0)"

# Palabras que identifican el AÑO de cada enlace, para no descargar los ~70 ficheros desde 2016 cuando solo
# hacen falta desde 2021 -- basta con un filtro laxo por año en el propio TEXTO del enlace (la fecha real de
# cada fila se re-filtra de todas formas al parsear, ver docstring).
ANIOS_DE_INTERES = {"2021", "2022", "2023", "2024", "2025", "2026"}


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _enlaces_ficheros():
    html = _get(INDICE_URL).decode("utf-8", errors="replace")
    pares = []
    for m in re.finditer(
        r'<a[^>]*href="([^"]*\.(?:xlsx|xls)[^"]*)"[^>]*>\s*(?:<i[^>]*></i>)?\s*([^<]*)</a>', html
    ):
        href, texto = m.groups()
        texto = texto.strip()
        if not texto or not any(a in texto for a in ANIOS_DE_INTERES):
            continue
        if not href.startswith("http"):
            href = "https://www.leganes.org" + href
        pares.append((texto, href))
    return pares


def _fecha_iso(txt):
    """'10-ABR-2026' -> '2026-04-10' (mismo formato que Alicante) -- salvo que la celda ya venga como
    datetime real (algunos ficheros la dan con formato de fecha de Excel en vez de texto plano; openpyxl
    entonces devuelve un `datetime.datetime`, no un string)."""
    if hasattr(txt, "strftime"):
        return txt.strftime("%Y-%m-%d")
    m = re.match(r"^(\d{1,2})-([A-Z]{3})-(\d{4})$", (txt or "").strip().upper())
    if not m:
        return ""
    d, mes_es, y = m.groups()
    mes = _MESES.get(mes_es)
    if not mes:
        return ""
    return f"{y}-{mes}-{d.zfill(2)}"


def _importe(valor):
    """Igual que en Alicante, pero aquí una celda de importe puede venir ya como número real de Excel (no
    texto) según el fichero -- un número no lleva el punto de miles del formato español, así que NO hay que
    tratarlo como texto (bug real: aplicar el reemplazo de '.'/',' a un float como 2772.0 lo convertía en
    27720, diez veces más)."""
    if isinstance(valor, (int, float)):
        return float(valor)
    limpio = str(valor or "").replace("€", "").strip().replace(".", "").replace(",", ".")
    try:
        return float(limpio)
    except ValueError:
        return 0.0


def _limpiar(txt):
    return re.sub(r"\s+", " ", str(txt or "")).strip()


def _parsear_xlsx(crudo, etiqueta):
    import openpyxl
    if crudo[:2] != b"PK":   # firma ZIP real de un .xlsx -- si no, es HTML (ver docstring del módulo:
        print(f"  !! {etiqueta}: la descarga no es un XLSX real (posible fallo de la URL/sesión), "
              "fichero omitido", flush=True)
        return []
    wb = openpyxl.load_workbook(io.BytesIO(crudo), data_only=True)
    ws = wb[wb.sheetnames[0]]
    filas = list(ws.iter_rows(values_only=True))
    idx_cabecera = next((i for i, f in enumerate(filas)
                          if f and _limpiar(f[0]).upper().startswith("NIF")), None)
    if idx_cabecera is None:
        print(f"  !! {etiqueta}: no se encontró la fila de cabecera ('NIF'), fichero omitido", flush=True)
        return []
    registros = []
    for fila in filas[idx_cabecera + 1:]:
        if len(fila) < 7 or not _limpiar(fila[0]):
            continue
        nif, adjudicatari, expediente, objeto, fecha_txt, precio_sin, precio_con = fila[:7]
        fecha = _fecha_iso(fecha_txt)
        if not fecha or fecha < MENORES_DESDE_FECHA:
            continue
        registros.append({
            "id":               f"leganes::{_limpiar(expediente)}",
            "municipio":         "Leganés",
            "provincia":         "madrid",
            "fuente":            "leganes",
            "organisme":         "Junta de Gobierno del Ayuntamiento de Leganés",
            "adjudicatari":      _limpiar(adjudicatari) or "No localizada",
            "nif":               _limpiar(nif),
            "import_num":        round(_importe(precio_sin), 2),
            "data_adjudicacio":  fecha,
            "tipus_contracte":   "",
            "descripcio":        _limpiar(objeto),
            "codi_cpv":          "",
            "exercici":          fecha[:4],
        })
    return registros


def _guardar(existentes):
    tmp = f"{FICHERO}.tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump({
            "generado": time.strftime("%Y-%m-%d"),
            "descripcion": ("Contratos menores del Ayuntamiento de Leganés, informes mensuales/trimestrales "
                             "oficiales en XLSX (portal de transparencia). data_adjudicacio = 'Fecha contrato' "
                             "real del informe. Ver actualizar_contratos_menores_leganes.py."),
            "registros": list(existentes.values()),
        }, f, ensure_ascii=False)
    os.replace(tmp, FICHERO)


def main():
    pares = _enlaces_ficheros()
    print(f"{len(pares)} ficheros candidatos (años {sorted(ANIOS_DE_INTERES)})", flush=True)

    existentes = {}
    total_bruto = 0
    for etiqueta, url in pares:
        try:
            crudo = _get(url)
        except Exception as e:
            print(f"  !! {etiqueta}: error de descarga ({type(e).__name__}: {e})", flush=True)
            continue
        registros = _parsear_xlsx(crudo, etiqueta)
        total_bruto += len(registros)
        for r in registros:
            existentes[r["id"]] = r
        print(f"  {etiqueta}: {len(registros)} contratos en ventana", flush=True)
        _guardar(existentes)
        time.sleep(0.2)

    print(f"\nHecho: {len(existentes)} registros en {FICHERO} ({total_bruto} filas brutas procesadas, "
          f"{total_bruto - len(existentes)} colapsadas por clave repetida -- si es alto, revisar unicidad "
          "del Expediente).")


if __name__ == "__main__":
    main()
