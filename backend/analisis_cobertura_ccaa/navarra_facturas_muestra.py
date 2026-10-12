"""Descarga el documento más reciente de cada entidad del inventario de Navarra (navarra_facturas_inventario.py) y
clasifica su formato: extensión y, en hojas de cálculo, si la fila de cabecera trae adjudicatario, importe y objeto.

Uso:  python navarra_facturas_muestra.py inventario.json carpeta_destino resumen.json"""
import io
import json
import os
import re
import subprocess
import sys
import time
import unicodedata

BASE = "https://hacienda.navarra.es/sicpportal/mtoGenerarDocumentoFacturaTrimestral.aspx?UID="
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36"

RX = {
    "adjudicatario": r"adjudicatari|proveedor|tercero|contratista|empresa|razon social|acreedor|nombre|hornitzaile|esleipendun",
    "nif": r"\bnif\b|\bcif\b|n\.i\.f|c\.i\.f|\bdni\b|\bifz\b|\bifk\b|identificacion fiscal",
    "importe": r"importe|precio|total|cuantia|euros|zenbateko|prezio",
    "objeto": r"objeto|concepto|descripcion|texto|asunto|denominacion|xede|kontzeptu|deskribapen",
}


def norm(s):
    s = "".join(c for c in unicodedata.normalize("NFD", str(s).lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def magia(b):
    if b[:4] == b"%PDF":
        return "pdf"
    if b[:2] == b"PK":
        return "ods" if b"opendocument.spreadsheet" in b[:400] else "docx" if b"word/" in b[:4000] else "xlsx"
    if b[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "xls_o_doc"
    return "otro"


def hojas(b, tipo):
    """Lista de (nombre de hoja, filas) con las primeras 40 filas de cada hoja."""
    if tipo == "xlsx":
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(b), read_only=True, data_only=True)
        return [(ws.title, [list(r) for r in ws.iter_rows(min_row=1, max_row=40, values_only=True)]) for ws in wb]
    import xlrd
    wb = xlrd.open_workbook(file_contents=b)
    return [(sh.name, [sh.row_values(i) for i in range(min(sh.nrows, 40))]) for sh in wb.sheets()]


def cabecera(filas):
    """La fila (de las primeras 40) que más campos reconoce; devuelve (campos reconocidos, textos de la fila)."""
    mejor = (set(), [])
    for f in filas:
        celdas = [norm(c) for c in f if c not in (None, "")]
        if len(celdas) < 3 or any(len(c) > 60 for c in celdas[:3]):
            continue
        campos = {k for k, rx in RX.items() if any(re.search(rx, c) for c in celdas)}
        if len(campos) > len(mejor[0]):
            mejor = (campos, celdas[:14])
    return mejor


def main():
    inventario, carpeta, salida = sys.argv[1:4]
    os.makedirs(carpeta, exist_ok=True)
    docs = json.load(open(inventario, encoding="utf-8"))
    ultimo = {}
    for d in docs:                                  # el listado viene del más reciente al más antiguo
        ultimo.setdefault(d["entidad"], d)
    res = []
    for i, d in enumerate(ultimo.values(), 1):
        ruta = os.path.join(carpeta, d["uid"])
        if not os.path.exists(ruta):
            subprocess.run(["curl", "-s", "-m", "120", "-A", UA, "-L", "-o", ruta, BASE + d["uid"]])
            time.sleep(0.5)
        b = open(ruta, "rb").read() if os.path.exists(ruta) else b""
        tipo = magia(b)
        r = dict(d, tipo=tipo, bytes=len(b), campos=[], cabecera=[], hojas=0)
        if tipo in ("xlsx", "xls_o_doc"):
            try:
                hs = hojas(b, "xlsx" if tipo == "xlsx" else "xls")
                r["hojas"] = len(hs)
                campos, textos = max((cabecera(f) for _n, f in hs), key=lambda x: len(x[0]))
                r["campos"], r["cabecera"] = sorted(campos), textos
                if tipo == "xls_o_doc":
                    r["tipo"] = "xls"
            except Exception as e:
                r["error"] = f"{type(e).__name__}: {e}"[:120]
        res.append(r)
        if i % 20 == 0:
            print(f"{i}/{len(ultimo)}", flush=True)
    json.dump(res, open(salida, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(res)} entidades -> {salida}")


if __name__ == "__main__":
    main()
