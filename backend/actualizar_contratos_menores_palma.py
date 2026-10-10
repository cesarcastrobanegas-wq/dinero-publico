# encoding: utf-8
"""
Contratos MENORES del Ayuntamiento de Palma (~416.000 hab., Illes Balears -- único municipio de la comunidad,
sin agregador regional propio, ver LIMITACIONES_COBERTURA.md).

Fuente OFICIAL: informes TRIMESTRALES en Excel del portal municipal (palma.es/es/contratos-menores), formato
simple y consistente de 2017 a hoy: 4 columnas -- Data (fecha real, a veces como texto a veces como
`datetime` nativo de Excel según el fichero), Import, EMPRESA ADJUDICATÀRIA (sin NIF/CIF -- esta fuente no lo
publica en ningún trimestre comprobado) y OBJECTE CONTRACTE (con el número de expediente embebido en el texto
libre, sin columna propia y sin patrón fijo -- no se puede extraer con garantías, se deja fuera).

Los enlaces de descarga son documentos de Liferay con nombre legible + UUID en la propia URL (a diferencia de
Leganés, donde el nombre legible NO estaba en el href real) -- confirmado que SÍ funcionan con una petición
HTTP directa. Aun así se guardan como diccionario fijo (mismo patrón que Alicante) porque no siguen un patrón
de URL predecible entre trimestres (carpetas `/documents/<id>/<id>/` distintas según cuándo se subió cada
fichero).

Huecos conocidos en la ventana de 5 años (no localizados en la página al recogerla, 2026-09-29): falta el 3er
trimestre de 2021 y el 2º de 2022 -- ningún enlace con ese nombre aparece en el listado (puede que el
Ayuntamiento no lo llegara a publicar, o use un nombre distinto no encontrado). El resto de trimestres desde
2021 T4 en adelante están completos.

Uso (desde backend/):
    python actualizar_contratos_menores_palma.py

Genera contratos_menores_palma.json.gz, que app.py carga al arrancar (ver _cargar_contratos_menores_palma)."""
import gzip
import hashlib
import io
import json
import os
import re
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "contratos_menores_palma.json.gz")
from alcance import alcance_desde
MENORES_DESDE_FECHA = alcance_desde()   # ventana móvil de 5 años (alcance.py), la misma que usa app.py

_BASE = "https://www.palma.es"
# (año, trimestre) -> URL exacta (recogidas a mano de palma.es/es/contratos-menores, 2026-09-29). Sin 2021T3
# ni 2022T2 -- ver docstring del módulo (huecos reales de la propia página, no un error de recogida).
FICHEROS = {
    (2021, 4): _BASE + "/documents/39048/11934097/Contratos+menores+4rt+trim+2021+%28excel%29.xls/78094c46-4697-4bdc-53d3-badd6d0b44dd",
    (2022, 1): _BASE + "/documents/39048/11934097/Contratos+menores+1er+trim.+2022+%28excel%29.xls/a10fedd6-faba-f5e3-958f-ad114d894cb1",
    (2022, 3): _BASE + "/documents/39048/11934097/Contratos+menores+3er+trim.+2022+%28excel%29.xls/873796ab-85b0-31ba-22ae-3877e62b85c4",
    (2022, 4): _BASE + "/documents/39048/11934097/Contratos+menores+4%C2%BA+trim+2022+%28excel%29.xls/7ec20357-ec25-5985-84f2-e34066659225",
    (2023, 1): _BASE + "/documents/39048/11779545/Contractes+menors+1er+Trim+2023+%28excel%29.xlsx/bc6027d0-d7ba-e8c6-abd2-67b5778b3b9e",
    (2023, 2): _BASE + "/documents/39028/13897382/Contratos+menores++2+TRIM+2023.xlsx/e0f17177-a4f1-0e5e-8d9b-3d2705eddfde",
    (2023, 3): _BASE + "/documents/39048/11933805/Contractes+menors++3+TRIM+2023.xlsx/e74b7ad8-db0e-be0d-408f-2819407a56f6",
    (2023, 4): _BASE + "/documents/39048/14957744/Contractes+menors++4+TRIM+2023.xlsx/f62ed9ce-65d5-ee51-12f4-e8fb77af74ee",
    (2024, 1): _BASE + "/documents/39048/14957744/Contractes+menors++1+TRIM+2024.xlsx/47c80d30-675c-dd0f-c7a2-85f89b9a70e3",
    (2024, 2): _BASE + "/documents/39048/14957744/Contractes+menors++2+TRIM+2024.xlsx/94a49d66-36f9-da59-d021-2e1ed32ddc2c",
    (2024, 3): _BASE + "/documents/39048/18116062/Contractes+menors++3er+TRIM+2024.xlsx/d90bb609-6678-f2b8-51ad-c1e6152ad9c1",
    (2024, 4): _BASE + "/documents/39048/18116062/Contractes+menors++4rt+TRIM+2024.xlsx/0bb2a744-1e08-c8fb-f7d1-454e19945f69",
    (2025, 1): _BASE + "/documents/39048/18116062/Contractes+menors+1er+TRIM+2025.xlsx/730c1512-c08c-c5a5-938b-058f389b169b",
    (2025, 2): _BASE + "/documents/39048/18116062/Contractes+menors+2on+TRIM+2025.xlsx/7311187d-6450-78e9-9737-c3d8ca7d9c74",
    (2025, 3): _BASE + "/documents/39048/18116062/Contractes+menors+3er+TRIM+2025.xlsx+%28115+KB%29.xlsx/9c003fd2-1c0e-8955-e949-2efbf84415ea",
    (2025, 4): _BASE + "/documents/39028/19784129/Contractes+menors++4rt+TRIM+2025.xlsx+%28121+KB%29.xlsx/eefb1dfe-d3c9-68f2-658e-c37e12b3a93c",
    (2026, 1): _BASE + "/documents/39028/19784129/Contractes+menors+1er+trim+2026.xlsx+%28112+KB%29.xlsx/e7ffcd2d-5589-20e0-9b5b-70ccd049e869",
}

_UA = "Mozilla/5.0 (compatible; dinero-publico-bot/1.0)"


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _limpiar(txt):
    return re.sub(r"\s+", " ", str(txt or "")).strip()


def _fecha_iso(valor):
    if hasattr(valor, "strftime"):
        return valor.strftime("%Y-%m-%d")
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$", str(valor or "").strip())
    if m:
        d, mo, y = m.groups()
        return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"
    return ""


def _importe(valor):
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor or "").replace("€", "").strip()
    if re.match(r"^\d+\.\d{2}$", texto):   # mismo caso raro ya detectado en Toledo -- por si acaso
        try:
            return float(texto)
        except ValueError:
            pass
    limpio = texto.replace(".", "").replace(",", ".")
    try:
        return float(limpio)
    except ValueError:
        return 0.0


def _hoja_de_datos(wb):
    for nombre in wb.sheetnames:
        ws = wb[nombre]
        if type(ws).__name__ == "Worksheet" and ws.max_row and ws.max_row > 1:
            return ws
    return None


def _parsear_xlsx(crudo, etiqueta):
    import openpyxl
    if crudo[:2] not in (b"PK", b"\xd0\xcf"):   # PK = xlsx (zip), D0CF = xls (OLE2) -- ninguno = no es Excel real
        print(f"  !! {etiqueta}: la descarga no parece un Excel real, fichero omitido", flush=True)
        return []
    if crudo[:2] == b"PK":
        wb = openpyxl.load_workbook(io.BytesIO(crudo), data_only=True)
    else:
        import xlrd
        libro_xls = xlrd.open_workbook(file_contents=crudo)
        return _filas_desde_xlrd(libro_xls, etiqueta)
    ws = _hoja_de_datos(wb)
    if ws is None:
        print(f"  !! {etiqueta}: no se encontró ninguna hoja con datos", flush=True)
        return []
    return _filas_a_registros(ws.iter_rows(values_only=True), etiqueta)


def _filas_desde_xlrd(libro, etiqueta):
    import xlrd
    hoja = libro.sheet_by_index(0)
    filas = []
    for i in range(hoja.nrows):
        fila = hoja.row_values(i)
        # xlrd da las fechas como número de serie de Excel, no como datetime -- convertir si la celda 0
        # tiene pinta de fecha (tipo XL_CELL_DATE = 3)
        if hoja.cell_type(i, 0) == 3 and fila[0]:
            from datetime import datetime
            y, mo, d, hh, mm, ss = xlrd.xldate_as_tuple(fila[0], libro.datemode)
            fila = [datetime(y, mo, d)] + list(fila[1:])
        filas.append(tuple(fila))
    return _filas_a_registros(filas, etiqueta)


def _columnas(cabecera):
    """Localiza cada campo por el TEXTO de la cabecera, no por posición fija -- comprobado en vivo
    (2026-09-29) que el número y significado de columnas cambia según el trimestre: la mayoría de ficheros
    traen solo 4 columnas (Data/Import/Empresa/Objecte, sin NIF), pero al menos 2024T1 trae 6 (con "C. gestor"
    y "CIF EMPRESA ADJUDICATÀRIA" de más). Un índice fijo leía el departamento como si fuera la empresa y el
    NIF como si fuera el objeto del contrato en ese fichero -- bug real detectado revisando los importes más
    altos del resultado (aparecían códigos de departamento tipo "06-GOVERN INTERIOR" como si fueran nombres
    de empresa)."""
    idx = {}
    for i, celda in enumerate(cabecera):
        t = _limpiar(celda).lower()
        if t.startswith("data") or t.startswith("fecha"):
            idx["fecha"] = i
        elif t.startswith("import"):
            idx["importe"] = i
        elif t.startswith("cif"):
            idx["nif"] = i
        elif t.startswith("empresa adjudicat"):
            idx["empresa"] = i
        elif t.startswith("objecte") or t.startswith("objeto"):
            idx["objecte"] = i
    return idx if {"fecha", "importe", "empresa", "objecte"} <= idx.keys() else None


def _filas_a_registros(filas, etiqueta):
    idx = None
    registros = []
    for fila in filas:
        if idx is None:
            idx = _columnas(fila)
            if idx is not None:
                continue   # esta fila YA es la cabecera, no un dato
            if _limpiar(fila[0] if fila else "").lower().startswith(("data", "fecha")):
                continue   # cabecera con columnas no reconocidas -- se seguirá intentando en la siguiente fila
            else:
                continue   # todavía no hemos visto la cabecera
        if len(fila) <= max(idx.values()):
            continue
        fecha = _fecha_iso(fila[idx["fecha"]])
        if not fecha or fecha < MENORES_DESDE_FECHA:
            continue
        empresa = _limpiar(fila[idx["empresa"]])
        objecte = _limpiar(fila[idx["objecte"]])
        if not empresa and not objecte:
            continue
        nif = _limpiar(fila[idx["nif"]]) if "nif" in idx else ""
        importe = round(_importe(fila[idx["importe"]]), 2)
        clave = hashlib.sha1(f"{fecha}|{empresa}|{importe}|{objecte[:60]}".encode("utf-8")).hexdigest()[:16]
        registros.append({
            "id":               f"palma::{clave}",
            "municipio":         "Palma",
            "provincia":         "illes_balears",
            "fuente":            "palma",
            "organisme":         "Ajuntament de Palma",
            "adjudicatari":      empresa or "No localizada",
            "nif":               nif,
            "import_num":        importe,
            "data_adjudicacio":  fecha,
            "tipus_contracte":   "",
            "descripcio":        objecte,
            "codi_cpv":          "",
            "exercici":          fecha[:4],
        })
    if idx is None:
        print(f"  !! {etiqueta}: no se reconoció la fila de cabecera, fichero omitido", flush=True)
    return registros


def _guardar(existentes):
    tmp = f"{FICHERO}.tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump({
            "generado": time.strftime("%Y-%m-%d"),
            "descripcion": ("Contratos menores del Ayuntamiento de Palma, informes trimestrales oficiales en "
                             "Excel. data_adjudicacio = columna 'Data' real. Sin NIF del adjudicatario (no "
                             "publicado por esta fuente). Faltan 2021T3 y 2022T2 (no localizados en la página "
                             "al recogerla). Ver actualizar_contratos_menores_palma.py."),
            "registros": list(existentes.values()),
        }, f, ensure_ascii=False)
    os.replace(tmp, FICHERO)


def main():
    existentes = {}
    for (anio, trimestre), url in sorted(FICHEROS.items()):
        etiqueta = f"{anio}T{trimestre}"
        print(f"Descargando {etiqueta}...", flush=True)
        try:
            crudo = _get(url)
        except Exception as e:
            print(f"  !! {etiqueta}: error de descarga ({type(e).__name__}: {e})", flush=True)
            continue
        registros = _parsear_xlsx(crudo, etiqueta)
        for r in registros:
            existentes[r["id"]] = r
        print(f"  {etiqueta}: {len(registros)} contratos en ventana", flush=True)
        _guardar(existentes)

    print(f"\nHecho: {len(existentes)} registros en {FICHERO}.")


if __name__ == "__main__":
    main()
