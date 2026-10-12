# encoding: utf-8
"""
Contratos MENORES del Ayuntamiento de Toledo (~85.000 hab., Castilla-La Mancha -- primer municipio por
población de la comunidad, sin agregador regional propio, ver LIMITACIONES_COBERTURA.md).

Fuente OFICIAL: informes SEMESTRALES en XLSX del portal de transparencia (toledo.es/toledo-abierto/
transparencia-economico-financiera-contratacion-publica-convenios-y-subvenciones/contratos-menores/).

**Limitación real e importante, a diferencia de TODAS las demás fuentes locales de menores conectadas hasta
ahora**: estos informes NO traen ninguna columna de fecha por contrato -- solo "UNIDAD GESTORA", "OBJETO DEL
CONTRATO", "DURACIÓN" (a veces un texto libre, no siempre un plazo), "IMPORTE ADJUDICACIÓN (IVA INCLUIDO)" y
"ADJUDICATARIO". Por eso aquí `data_adjudicacio` se deja VACÍO en cada fila (mismo patrón ya aceptado en el
proyecto para las 801 filas sin fecha de Fuente Álamo, ver `_guardar_contratos_menors_locales`/
`MENORES_DESDE_FECHA`: una fila sin fecha nunca se descarta por el filtro de 5 años, se conserva). El alcance de
5 años se aplica aquí a nivel de FICHERO (cada semestre entero cae dentro o fuera de la ventana), no fila a
fila -- por eso se omite el fichero "Contratos Menores 2021" (parece cubrir el año COMPLETO, no solo el 2º
semestre; incluir sus filas sin poder filtrar por fecha metería contratos de enero-agosto de 2021, fuera de la
ventana de 5 años, sin forma de separarlos).

El NIF viene embebido en "ADJUDICATARIO" solo en ALGUNOS ficheros (formato "B12345678 - NOMBRE EMPRESA"; en
otros, como el de 2022 1er semestre, el campo es solo el nombre, sin NIF) -- se extrae con una expresión
regular cuando está presente, se deja vacío si no.

Uso (desde backend/):
    python actualizar_contratos_menores_toledo.py

Genera contratos_menores_toledo.json.gz, que app.py carga al arrancar (ver _cargar_contratos_menores_toledo)."""
import gzip
import io
import json
import os
import re
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "contratos_menores_toledo.json.gz")

# (año, semestre) -> URL exacta del XLSX (recogidas a mano de la página de transparencia, 2026-09-29). El
# semestre 1 de 2021 NO se incluye a propósito -- ver docstring del módulo.
FICHEROS = {
    (2022, 1): "https://www.toledo.es/wp-content/uploads/2022/09/copia-de-contratos-menores-2022-portal-transparencia.xlsx",
    (2022, 2): "https://www.toledo.es/wp-content/uploads/2024/02/relacion-de-contratos-menores-segundo-semestre-2022-agregado.xlsx",
    (2023, 1): "https://www.toledo.es/wp-content/uploads/2024/02/relacion-de-contratos-menores-primer-semestre-2023-agregado.xlsx",
    (2023, 2): "https://www.toledo.es/wp-content/uploads/2024/06/relacion-de-contratos-y-otros-gastos.-segundo-semestre-2023..xlsx",
    (2024, 1): "https://www.toledo.es/wp-content/uploads/2025/01/relacion-de-contratos-menores-primer-semestre-2024.xlsx",
}

_UA = "Mozilla/5.0 (compatible; dinero-publico-bot/1.0)"
_RE_NIF_PREFIJO = re.compile(r"^\s*([A-Z0-9]{8,9})\s*-\s*(.+)$")


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _limpiar(txt):
    return re.sub(r"\s+", " ", str(txt or "")).strip()


def _importe(valor):
    """La columna de importe mezcla celdas numéricas reales (la inmensa mayoría) con, al menos una vez
    detectada (2023 2º semestre, fila 131: 'SUMINISTRO DE VENTANAS...'), una celda de TEXTO en formato
    inglés/plano ('6179.68 €', punto como separador decimal, no de miles) -- aplicarle sin más el reemplazo
    de punto/coma del formato español la convertía en 617.968,00 € (diez veces más), un error real detectado
    al revisar los importes más altos del resultado. Se distingue por forma: un texto con UN solo punto y
    exactamente 2 cifras decimales y SIN coma se trata como decimal directo; el resto, como formato español
    (punto de miles, coma decimal)."""
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor or "").replace("€", "").strip()
    if re.match(r"^\d+\.\d{2}$", texto):
        try:
            return float(texto)
        except ValueError:
            pass
    limpio = texto.replace(".", "").replace(",", ".")
    try:
        return float(limpio)
    except ValueError:
        return 0.0


def _nif_y_nombre(adjudicatario):
    m = _RE_NIF_PREFIJO.match(adjudicatario or "")
    if m:
        return m.group(1), _limpiar(m.group(2))
    return "", _limpiar(adjudicatario)


def _hoja_de_datos(wb):
    """La primera hoja de tipo Worksheet (no Chartsheet) que tenga más de una fila -- el nombre y el número
    de hojas varía de un fichero a otro (a veces solo 'Hoja1', a veces 'Hoja2'+'Gráfico1'+'Hoja1')."""
    for nombre in wb.sheetnames:
        ws = wb[nombre]
        if type(ws).__name__ != "Worksheet":
            continue
        if ws.max_row and ws.max_row > 1:
            return ws
    return None


def _parsear_xlsx(crudo, anio, semestre):
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(crudo), data_only=True)
    ws = _hoja_de_datos(wb)
    if ws is None:
        print(f"  !! {anio}S{semestre}: no se encontró ninguna hoja con datos", flush=True)
        return []
    filas = list(ws.iter_rows(values_only=True))
    idx_cabecera = next((i for i, f in enumerate(filas)
                          if f and _limpiar(f[0]).upper().startswith("UNIDAD GESTORA")), None)
    if idx_cabecera is None:
        print(f"  !! {anio}S{semestre}: no se encontró la fila de cabecera ('UNIDAD GESTORA'), omitido", flush=True)
        return []
    registros = []
    for i, fila in enumerate(filas[idx_cabecera + 1:]):
        if len(fila) < 5 or not _limpiar(fila[1]):   # sin objeto -> fila vacía/de relleno
            continue
        objeto = _limpiar(fila[1])
        importe = round(_importe(fila[3]), 2)
        nif, adjudicatari = _nif_y_nombre(_limpiar(fila[4]))
        clave = f"{anio}-{semestre}-{i}"   # sin expediente propio -- posición dentro del fichero + periodo
        registros.append({
            "id":               f"toledo::{clave}",
            "municipio":         "Toledo",
            "provincia":         "toledo",
            "fuente":            "toledo",
            "organisme":         _limpiar(fila[0]) or "Ayuntamiento de Toledo",
            "adjudicatari":      adjudicatari or "No localizada",
            "nif":               nif,
            "import_num":        importe,
            "data_adjudicacio":  "",   # esta fuente no publica fecha por contrato, ver docstring del módulo
            "tipus_contracte":   "",
            "descripcio":        objeto,
            "codi_cpv":          "",
            "exercici":          str(anio),
        })
    return registros


def _guardar(existentes):
    tmp = f"{FICHERO}.tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump({
            "generado": time.strftime("%Y-%m-%d"),
            "descripcion": ("Contratos menores del Ayuntamiento de Toledo, informes semestrales oficiales en "
                             "XLSX. SIN fecha por contrato (limitación real de la fuente, ver docstring de "
                             "actualizar_contratos_menores_toledo.py) -- el alcance de 5 años se aplicó "
                             "excluyendo ficheros enteros fuera de ventana, no fila a fila."),
            "registros": list(existentes.values()),
        }, f, ensure_ascii=False)
    os.replace(tmp, FICHERO)


def main():
    existentes = {}
    for (anio, semestre), url in sorted(FICHEROS.items()):
        print(f"Descargando {anio}S{semestre}...", flush=True)
        try:
            crudo = _get(url)
        except Exception as e:
            print(f"  !! {anio}S{semestre}: error de descarga ({type(e).__name__}: {e})", flush=True)
            continue
        registros = _parsear_xlsx(crudo, anio, semestre)
        for r in registros:
            existentes[r["id"]] = r
        print(f"  {anio}S{semestre}: {len(registros)} contratos", flush=True)
        _guardar(existentes)

    print(f"\nHecho: {len(existentes)} registros en {FICHERO}.")


if __name__ == "__main__":
    main()
