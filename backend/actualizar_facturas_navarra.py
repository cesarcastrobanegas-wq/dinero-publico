"""Genera backend/facturas_trimestrales_navarra.json.gz a partir de las "Relaciones trimestrales de facturas" que
los ayuntamientos navarros suben al Portal de Contratación de Navarra (art. 88 de la ley foral de contratos).

Decisión de César (2026-10-02): NO son contratos menores estándar y no se mezclan con ellos (ni tabla
contratos_menors_locales, ni Índice, ni rankings). Solo entran los documentos en hoja de cálculo cuya cabecera trae
adjudicatario + importe + objeto, y se muestran aparte, etiquetados "Facturas trimestrales Navarra". Los PDF (104 de
140 entidades) quedan fuera por ahora.

Cada ayuntamiento usa su propio formato, así que por cada hoja se localiza la fila de cabecera y se eligen las
columnas por prioridad (ver COLUMNAS). Una fila solo entra si tiene los tres datos; el importe se guarda con la
etiqueta de su columna tal como la escribe la fuente ("Importe líquido", "Total", "Importe sin IVA"...), sin
convertir. El DNI/NIE de personas físicas se guarda ya enmascarado.

Va por curl: `requests` con Python 3.14 recibe un corte en el saludo TLS de hacienda.navarra.es.

Uso (desde backend/):
    python actualizar_facturas_navarra.py                 # inventario + descarga + extracción
    python actualizar_facturas_navarra.py --inventario analisis_cobertura_ccaa/nav_inventario.json
"""
import datetime
import gzip
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "facturas_trimestrales_navarra.json.gz")
CACHE = os.path.join(tempfile.gettempdir(), "facturas_navarra_docs")
URL_DOC = "https://hacienda.navarra.es/sicpportal/mtoGenerarDocumentoFacturaTrimestral.aspx?UID="
URL_LISTADO = "https://hacienda.navarra.es/sicpportal/mtoBuscadorFacturasTrimestrales.aspx"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36"
DESDE_ANIO = 2021          # alcance del proyecto: últimos 5 años

# Entidades con documentos en hoja de cálculo con los tres campos (muestra del 2026-10-02, ver
# analisis_cobertura_ccaa/navarra_facturas_muestra.py) -> municipio tal como está en MUNICIPIOS_NAVARRA de app.py.
# Solo ayuntamientos: el Patronato de Cultura de Noáin es un organismo dependiente y se deja fuera.
# Milagro también queda fuera aunque su hoja trae los tres campos: es una "relación de gastos" por partida
# presupuestaria (subvenciones nominativas, ayudas a personas, transferencias), no una relación de facturas --
# mismo criterio que con los apuntes contables de Pamplona.
ENTIDADES = {
    "ayuntamiento de salinas de oro": "Salinas de Oro/Jaitz",
    "ayuntamiento del valle de yerri": "Valle de Yerri/Deierri",
    "ayuntamiento de guesalaz": "Guesálaz/Gesalatz",
    "ayuntamiento de azagra": "Azagra",
    "ayuntamiento de carcar": "Cárcar",
    "ayuntamiento de allo": "Allo",
    "ayuntamiento de garaioa": "Garaioa",
    "ayuntamiento de zubieta": "Zubieta",
    "ayuntamiento de biurrun-olcoz": "Biurrun-Olcoz",
    "ayuntamiento de artajona": "Artajona",
    "ayuntamiento de villava": "Villava/Atarrabia",
    "ayuntamiento de amescoa baja": "Améscoa Baja",
    "ayuntamiento de sunbilla /sunbilla udala": "Sunbilla",
    "ayuntamiento de huarte": "Huarte/Uharte",
}

# Por campo, patrones en orden de preferencia (sobre la cabecera normalizada). El NIF se mira antes que el
# adjudicatario para que "dni/cif tercero" no se tome por el nombre.
COLUMNAS = {
    "nif": [r"\bcif\b|\bnif\b|\bdni\b|c\.i\.f|n\.i\.f"],
    "adjudicatario": [r"^nombre proveedor$", r"^proveedor$", r"adjudicatari", r"contratista", r"razon social",
                      r"^tercero$", r"^empresa$"],
    "objeto": [r"^objeto", r"^concepto", r"^descripcion$", r"denominacion del contrato"],
    "importe": [r"^total$|^imp\.? ?total", r"^importe liquido$", r"^importe$", r"^importe factura$",
                r"^importe partida$", r"^importe"],
    "fecha": [r"^fecha reg\.?$|^f\.registro$|^fecha registro$", r"^fecha fra|^fecha factura", r"^fecha$",
              r"fecha adjudicacion"],
}
OBLIGATORIOS = ("adjudicatario", "objeto", "importe")


def norm(s):
    s = "".join(c for c in unicodedata.normalize("NFD", str(s).lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def curl(url, data=None, salida=None, jar=None):
    cmd = ["curl", "-s", "-m", "120", "-A", UA, "-L"]
    if jar:
        cmd += ["-b", jar, "-c", jar]
    if salida:
        cmd += ["-o", salida]
    if data is not None:
        cmd += ["-H", "Content-Type: application/x-www-form-urlencoded; charset=iso-8859-15", "--data-binary", data]
    return subprocess.run(cmd + [url], capture_output=True).stdout


def inventario():
    """[{entidad, anio, titulo, uid}] de todas las entidades con "Ayuntamiento" en el nombre (68 páginas)."""
    import urllib.parse
    from bs4 import BeautifulSoup
    jar = os.path.join(tempfile.gettempdir(), "facturas_navarra_cookies.txt")
    if os.path.exists(jar):
        os.remove(jar)

    def ocultos(s):
        return {i.get("name"): i.get("value", "") for i in s.find_all("input", type="hidden") if i.get("name")}

    def cod(d):
        return "&".join(f"{k}={urllib.parse.quote(str(v).encode('iso-8859-15', errors='replace'))}"
                        for k, v in d.items())

    s = BeautifulSoup(curl(URL_LISTADO, jar=jar).decode("iso-8859-15", "replace"), "html.parser")
    p = dict(ocultos(s), txtEntidad="Ayuntamiento", btnEnviar="Buscar")
    docs, vistos = [], set()
    while True:
        s = BeautifulSoup(curl(URL_LISTADO, cod(p), jar=jar).decode("iso-8859-15", "replace"), "html.parser")
        t = s.find("table", id="tblFacturasTrimestrales")
        nuevas = 0
        for tr in (t.find_all("tr") if t else []):
            a = tr.find("a", href=re.compile("mtoGenerarDocumentoFacturaTrimestral"))
            if not a or a["href"].split("UID=")[1] in vistos:
                continue
            tds = tr.find_all("td")
            vistos.add(a["href"].split("UID=")[1])
            docs.append({"entidad": tds[2].get_text(" ", strip=True), "anio": tds[3].get_text(strip=True),
                         "titulo": a.get_text(" ", strip=True), "uid": a["href"].split("UID=")[1]})
            nuevas += 1
        if not nuevas or not s.find("input", attrs={"name": "btnSiguiente"}):
            return docs
        p = dict(ocultos(s), txtEntidad="Ayuntamiento")
        p.update({"btnSiguiente.x": "5", "btnSiguiente.y": "5"})
        time.sleep(0.8)


def hojas(b):
    """[(nombre, filas)] de un xlsx/xls; [] si no es una hoja de cálculo legible."""
    try:
        if b[:2] == b"PK":
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(b), read_only=True, data_only=True)
            return [(ws.title, [list(r) for r in ws.iter_rows(values_only=True)]) for ws in wb]
        if b[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            import xlrd
            wb = xlrd.open_workbook(file_contents=b)
            out = []
            for sh in wb.sheets():
                filas = []
                for i in range(sh.nrows):
                    fila = []
                    for c in sh.row(i):
                        if c.ctype == xlrd.XL_CELL_DATE:
                            try:
                                fila.append(xlrd.xldate_as_datetime(c.value, wb.datemode))
                            except Exception:
                                fila.append(c.value)
                        else:
                            fila.append(c.value)
                    filas.append(fila)
                out.append((sh.name, filas))
            return out
    except Exception:
        return []
    return []


def localizar_cabecera(filas):
    """(índice de fila, {campo: (columna, etiqueta original)}) de la primera fila (de las 40 primeras) que trae los
    tres campos obligatorios, o (None, {})."""
    for i, fila in enumerate(filas[:40]):
        etiquetas = [(j, str(c).strip(), norm(c)) for j, c in enumerate(fila) if c not in (None, "")]
        if len(etiquetas) < 3 or any(len(n) > 60 for _j, _o, n in etiquetas):
            continue
        usadas, cols = set(), {}
        for campo in ("nif", "adjudicatario", "objeto", "importe", "fecha"):
            for rx in COLUMNAS[campo]:
                hit = next(((j, o) for j, o, n in etiquetas if j not in usadas and re.search(rx, n)
                            and not (campo != "nif" and re.search(COLUMNAS["nif"][0], n))), None)
                if hit:
                    cols[campo] = hit
                    usadas.add(hit[0])
                    break
        if all(c in cols for c in OBLIGATORIOS):
            return i, cols
    return None, {}


def a_importe(v):
    if isinstance(v, bool) or v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    t = re.sub(r"[^\d,.\-]", "", str(v))
    if not re.search(r"\d", t):
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return round(float(t), 2)
    except ValueError:
        return None


def a_fecha(v):
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.strftime("%Y-%m-%d")
    m = re.match(r"\s*(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})", str(v or ""))
    if m:
        d, me, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
        a += 2000 if a < 100 else 0
        if 1 <= d <= 31 and 1 <= me <= 12 and 2000 <= a <= 2100:
            return f"{a:04d}-{me:02d}-{d:02d}"
    return ""


def enmascarar_nif(v):
    """DNI/NIE de persona física enmascarado (***4567** / ****4567*); el NIF de una sociedad, tal cual."""
    n = re.sub(r"[^0-9A-Za-z]", "", str(v or "")).upper()
    if re.fullmatch(r"\d{8}[A-Z]?", n):
        return "***" + n[3:7] + "**"
    if re.fullmatch(r"[XYZ]\d{7}[A-Z]", n):
        return "****" + n[4:8] + "*"
    return n if re.fullmatch(r"[A-Z]\d{7}[0-9A-Z]", n) else ""


_NIF = r"(?:[A-HJNP-SUVW]\d{7}[0-9A-J]|\d{8}[A-Z]?|[XYZ]\d{7}[A-Z])"
_RE_NIF_DELANTE = re.compile(rf"^(?:(?:CIF|NIF|DNI)[:.]?\s*)?({_NIF})\s+(?=\S)", re.I)
_RE_NIF_DETRAS = re.compile(rf"\s+(?:(?:CIF|NIF|DNI)[:.]?\s*)?({_NIF}\S*)\s*$", re.I)
_RE_DNI_SUELTO = re.compile(r"\b(\d{8}[A-Za-z]|[XYZxyz]\d{7}[A-Za-z])\b")
_RE_OBJETO_VACIO = re.compile(r"^(fac(t(ura)?)?|fra|fa|n[oº.]*)$")
# Pagos que no son una compra: ayudas y subvenciones a personas o entidades. No se publican aquí.
_RE_NO_FACTURA = re.compile(r"concesi[oó]n de (subvenci|ayuda)|subvenci[oó]n nominativa|ayuda (familiar|al estudio|social|"
                            r"de emergencia)|emergencia social|\bbecas?\b", re.I)


def separar_nif(adjudicatario):
    """("B06290241 PREVING SLU" | "Sasoi S.L. B31544075") -> (nombre, NIF). Algunos ayuntamientos pegan el NIF al
    nombre; se separa para poder enmascarar el de las personas físicas."""
    m = _RE_NIF_DELANTE.match(adjudicatario)
    if m:
        return adjudicatario[m.end():].strip(), m.group(1)
    m = _RE_NIF_DETRAS.search(adjudicatario)
    if m:
        return re.sub(r"\s*(CIF|NIF|DNI)[:.]?\s*$", "", adjudicatario[:m.start()], flags=re.I).strip(" ,.-"), m.group(1)
    # cualquier otro identificador pegado delante (pasaporte, NIF extranjero): se quita y no se guarda
    m = re.match(r"^[A-Z]{0,2}\d{6,}[A-Z0-9]*\s+(?=\S)", adjudicatario, re.I)
    if m:
        return adjudicatario[m.end():].strip(), ""
    return adjudicatario, ""


def sin_dni(texto):
    return _RE_DNI_SUELTO.sub(lambda m: enmascarar_nif(m.group(1)), texto)


def objeto_con_detalle(objeto):
    """False si el objeto es solo "FAC", "FAC. 1234" o similar: sin una palabra que diga qué se compró no cuenta."""
    palabras = [w for w in re.findall(r"[a-zñ]{3,}", norm(objeto)) if not _RE_OBJETO_VACIO.match(w)]
    return bool(palabras)


def extraer(b):
    """Filas válidas de un documento: lista de dicts, y la lista de etiquetas de importe usadas."""
    out = []
    for _nombre, filas in hojas(b):
        i, cols = localizar_cabecera(filas)
        if i is None:
            continue

        def celda(fila, campo):
            j = cols.get(campo, (None,))[0]
            return fila[j] if j is not None and j < len(fila) else None
        for fila in filas[i + 1:]:
            adj = re.sub(r"\s+", " ", str(celda(fila, "adjudicatario") or "")).strip()
            obj = re.sub(r"\s+", " ", str(celda(fila, "objeto") or "")).strip()
            imp = a_importe(celda(fila, "importe"))
            if not adj or not obj or imp is None or norm(adj) in ("total", "totales", "suma"):
                continue
            adj, nif_pegado = separar_nif(adj)
            if not re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{2}", adj):
                continue                                  # una cifra o un código en la columna del adjudicatario
            if not objeto_con_detalle(obj) or _RE_NO_FACTURA.search(obj) or norm(adj) == "acreedores varios":
                continue
            out.append({"adjudicatario": sin_dni(adj), "nif": enmascarar_nif(celda(fila, "nif") or nif_pegado),
                        "objeto": sin_dni(obj)[:400],
                        "importe": imp, "importe_base": cols["importe"][1], "fecha": a_fecha(celda(fila, "fecha"))})
    return out


def main():
    if "--inventario" in sys.argv:
        docs = json.load(open(sys.argv[sys.argv.index("--inventario") + 1], encoding="utf-8"))
    else:
        docs = inventario()
    print(f"{len(docs)} documentos en el listado")
    os.makedirs(CACHE, exist_ok=True)
    municipios, resumen = {}, []
    for d in docs:
        muni = ENTIDADES.get(norm(d["entidad"]))
        if not muni or not d["anio"].isdigit() or int(d["anio"]) < DESDE_ANIO:
            continue
        ruta = os.path.join(CACHE, d["uid"])
        if not os.path.exists(ruta) or os.path.getsize(ruta) == 0:
            curl(URL_DOC + d["uid"], salida=ruta)
            time.sleep(0.5)
        b = open(ruta, "rb").read() if os.path.exists(ruta) else b""
        filas = extraer(b)
        resumen.append((muni, d["anio"], d["titulo"][:50], "pdf" if b[:4] == b"%PDF" else "hoja" if hojas(b) else "otro",
                        len(filas)))
        if not filas:
            continue
        doc = {"anio": int(d["anio"]), "titulo": d["titulo"], "url": URL_DOC + d["uid"], "entidad": d["entidad"]}
        m = municipios.setdefault(muni, {"provincia": "navarra", "documentos": [], "facturas": []})
        m["documentos"].append(doc)
        vistas = m.setdefault("_vistas", {})
        n_doc = len(m["documentos"]) - 1
        for f in filas:
            # la misma factura en dos documentos (relaciones acumuladas, "parcial" y "total" del mismo trimestre)
            k = (norm(f["adjudicatario"]), norm(f["objeto"]), f["importe"], f["fecha"])
            if vistas.get(k, n_doc) != n_doc:
                continue
            vistas[k] = n_doc
            m["facturas"].append(dict(f, anio=doc["anio"], doc=n_doc))
    for m in municipios.values():
        m.pop("_vistas", None)
    print(f"{len(resumen)} documentos mirados; con filas: {sum(1 for r in resumen if r[4])}; "
          f"PDF: {sum(1 for r in resumen if r[3] == 'pdf')}")
    datos = {"generado": time.strftime("%Y-%m-%d"), "fuente": URL_LISTADO, "municipios": municipios}
    contenido = json.dumps(datos, ensure_ascii=False, sort_keys=True).encode("utf-8")
    with open(FICHERO, "wb") as crudo:
        with gzip.GzipFile(filename="", mode="wb", fileobj=crudo, compresslevel=9, mtime=0) as z:
            z.write(contenido)
    for muni, m in sorted(municipios.items()):
        print(f"{muni}: {len(m['facturas'])} facturas en {len(m['documentos'])} documentos, "
              f"{sum(f['importe'] for f in m['facturas']):,.2f} EUR, bases {sorted({f['importe_base'] for f in m['facturas']})}")
    print(f"TOTAL: {sum(len(m['facturas']) for m in municipios.values())} facturas, {len(municipios)} municipios -> "
          f"{FICHERO} ({os.path.getsize(FICHERO) >> 10} KB)")


if __name__ == "__main__":
    main()
