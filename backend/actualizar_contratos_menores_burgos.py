# encoding: utf-8
"""
Contratos MENORES del Ayuntamiento de Burgos (~175.000 hab., Castilla y León).

Fuente OFICIAL: la página `aytoburgos.es/contratos-menores` es una biblioteca de documentos (Liferay) con
~49 PDF enlazados, subidos a mano trimestre a trimestre desde 2020 -- **sin ningún orden ni criterio de
nombrado fiable**: el mismo tipo de informe aparece con nombres tan dispares como "Contratos+Menores+1ºT.pdf",
"AYTOBURGOSTOTALDEFINITIVO.pdf", "Documento+Final.pdf" o, más engañoso todavía, "CONTRATOS_TRABAJO...pdf" /
"Trabajo.pdf" / "trabajo+definitivo.pdf" (nombres que sugieren contratos de personal/trabajo, pero que al
abrirlos son en realidad "RELACIÓN CONTRATOS MENORES" -- contratación pública normal). **Por eso este
conector clasifica cada PDF por su CONTENIDO real (el título de su primera página), nunca por el nombre del
fichero**: se acepta si el título contiene "CONTRATOS MENORES" y NO empieza por "DATOS AGREGADOS" ni
"AGRUPADOS" (esas dos variantes son solo totales por departamento, sin adjudicatario ni fecha por contrato,
usadas para excluir sin ambigüedad las ~22 de las 49 que no son un listado por contrato).

**Tres plantillas de columnas distintas conviven** (la cabecera cambia de formato con los años, a veces
incluso el orden de las columnas), así que las posiciones de columna se detectan por el TEXTO de la cabecera
de cada PDF en concreto (buscando las palabras "ADJUDICATARIO"/"OBJETO"/"IMPORTE"/"FECHA"/"PLAZO" y usando su
posición X real), nunca una posición fija -- igual que Palma/Fuenlabrada. Los nombres de adjudicatario y el
objeto del contrato pueden partirse en varias líneas dentro del PDF (sin bordes de tabla reales); se maneja
igual que Alcalá de Henares: una línea "huérfana" (sin fecha ni importe reconocibles) se guarda en un buffer y
se antepone al siguiente registro real, porque en este documento el trozo de nombre/objeto que se envuelve
aparece SIEMPRE ANTES de la línea con el resto de los datos, no después.

**Sin NIF** en ningún formato de los tres. Fecha real de adjudicación por contrato (a diferencia de Ciudad
Real/Toledo, aquí SÍ hay fecha por fila en las tres eras), así que el filtro de ventana de 5 años se aplica
fila a fila, nunca a nivel de fichero.

Uso (desde backend/):
    python actualizar_contratos_menores_burgos.py

Genera contratos_menores_burgos.json.gz, que app.py carga al arrancar (ver _cargar_contratos_menores_burgos).
"""
import gzip
import hashlib
import io
import json
import os
import re
import time
import unicodedata
import ssl
import urllib.error
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "contratos_menores_burgos.json.gz")
MENORES_DESDE_FECHA = "2021-09-01"   # mismo corte que MENORES_DESDE_FECHA en app.py -- mantener sincronizado a mano

_URL_PAGINA = "https://www.aytoburgos.es/contratos-menores"
_URL_BASE = "https://www.aytoburgos.es"
_UA = "Mozilla/5.0 (compatible; dinero-publico-bot/1.0)"


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.read()
    except urllib.error.URLError as e:
        # El servidor del ayuntamiento no envía la cadena completa de certificados: Windows la completa
        # solo, pero Linux (GitHub Actions) la rechaza. Solo en ese caso se repite sin verificar (mismo
        # criterio que Alcalá de Henares): son listados públicos y no se envía ningún dato.
        if not isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError):
            raise
        with urllib.request.urlopen(req, timeout=90, context=ssl._create_unverified_context()) as r:
            return r.read()


def _sin_acentos(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _limpiar(txt):
    return re.sub(r"\s+", " ", str(txt or "")).strip()


def _importe(valor):
    t = re.sub(r"[^\d.,]", "", str(valor or ""))
    t = re.sub(r"[.,]+$", "", t)   # separador residual de cierre de frase (ver bug real de Ciudad Real)
    if not t:
        return 0.0
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


def _fecha_iso(txt):
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", str(txt or ""))
    if not m:
        return ""
    d, mo, y = m.groups()
    return f"{y}-{mo}-{d}"


def _detectar_anchors(pagina):
    """Busca en la cabecera (top < 220, cubre cabeceras de hasta 3 líneas) la posición X real de cada
    columna, por su palabra de cabecera -- nunca una posición fija, porque cambia entre plantillas."""
    anchors = {}
    for w in pagina.extract_words():
        if w["top"] > 220:
            break
        t = _sin_acentos(w["text"].upper().rstrip(":").rstrip(","))
        if t == "ADJUDICATARIO" and "nombre" not in anchors:
            anchors["nombre"] = w["x0"]
        elif t in ("ORGANO", "UNIDAD") and "organo" not in anchors:
            anchors["organo"] = w["x0"]
        elif t in ("EXPEDIENTE", "EXPTE", "NRO") and "expediente" not in anchors:
            anchors["expediente"] = w["x0"]
        elif t.startswith("OBJETO") and "objeto" not in anchors:
            anchors["objeto"] = w["x0"]
        elif t == "IMPORTE" and "importe" not in anchors:
            anchors["importe"] = w["x0"]
        elif t == "FECHA" and "fecha" not in anchors:
            anchors["fecha"] = w["x0"]
        elif t.startswith("PLAZO") and "plazo" not in anchors:
            anchors["plazo"] = w["x0"]
    return anchors


def _es_listado_menores(titulo0):
    t = _sin_acentos(titulo0.upper())
    return "CONTRATOS MENORES" in t and not t.startswith("DATOS AGREGADOS") and not t.startswith("AGRUPADOS")


_EPSILON_COLUMNA = 1.5   # margen de tolerancia en puntos: sin él, un ancla y una palabra de la MISMA columna
# visual pueden diferir en centésimas de punto entre página y página (kerning/renderizado), y la palabra cae
# en la columna vecina -- bug real encontrado (2026-09-30): "Gerencia" (ancla "organo") con x0=158.99094 caía
# en "nombre" porque el ancla real (tomada de la cabecera) era x0=158.99110, un margen de 0,0002pt.
_RE_FECHA = re.compile(r"^\d{2}/\d{2}/\d{4}")   # prefijo, no fin de cadena -- ver bug real más abajo
_RE_IMPORTE = re.compile(r"^\d{1,3}(\.\d{3})*,\d{2}$")


def _col_de(x0, umbrales):
    """umbrales: lista [(nombre_columna, x0_inicio)] ordenada de menor a mayor x0."""
    col = umbrales[0][0]
    for nombre_col, inicio in umbrales:
        if x0 >= inicio - _EPSILON_COLUMNA:
            col = nombre_col
        else:
            break
    return col


def _parsear_pdf(crudo, nombre_fichero):
    import pdfplumber
    registros = []
    with pdfplumber.open(io.BytesIO(crudo)) as pdf:
        primera = pdf.pages[0].extract_text() or ""
        titulo0 = primera.split("\n")[0] if primera else ""
        if not _es_listado_menores(titulo0):
            return []   # DATOS AGREGADOS / AGRUPADOS / cualquier otra cosa -- no es un listado por contrato
        anchors = _detectar_anchors(pdf.pages[0])
        necesarias = ("nombre", "objeto", "importe", "fecha")
        if not all(k in anchors for k in necesarias):
            print(f"  !! {nombre_fichero}: cabecera reconocida como 'CONTRATOS MENORES' pero columnas "
                  f"incompletas ({sorted(anchors.keys())}), fichero omitido", flush=True)
            return []
        # IMPORTE y FECHA se extraen por PATRÓN, no por posición: bug real encontrado (2026-09-30) en la
        # plantilla de 2025 -- el valor de FECHA se renderiza más a la izquierda que la propia palabra de
        # cabecera "FECHA", así que caía dentro de la columna IMPORTE y se concatenaba con el importe real,
        # multiplicándolo por billones (393,25 + 18/02/2025 -> "3932518022025"). Solo nombre/objeto (texto
        # libre, sin patrón fiable) siguen bucketizándose por posición X.
        umbrales = sorted(((k, v) for k, v in anchors.items() if k not in ("importe", "fecha", "plazo")),
                          key=lambda kv: kv[1])
        tope_objeto = anchors.get("plazo")

        buf_nombre, buf_objeto = "", ""
        for pagina in pdf.pages:
            filas = {}
            for w in pagina.extract_words():
                if w["top"] < 155:
                    continue   # cabecera repetida en cada página
                top_r = round(w["top"] / 3) * 3
                filas.setdefault(top_r, []).append(w)
            for top_r in sorted(filas.keys()):
                palabras = sorted(filas[top_r], key=lambda w: w["x0"])
                fecha_w, importe_w, resto = None, None, []
                for w in palabras:
                    t = w["text"]
                    # bug real de origen encontrado (2026-09-30, un solo fichero de 27): en la plantilla del
                    # primer trimestre de 2026, la fecha se renderiza SIN espacio respecto al texto que le
                    # sigue en la misma celda de PLAZO/DURACIÓN ("26/02/20263 meses", "26/02/2026Desde") --
                    # pdfplumber lo lee como una única palabra. Por eso se busca la fecha como PREFIJO del
                    # token, nunca exigiendo que ocupe el token entero.
                    if fecha_w is None and _RE_FECHA.match(t):
                        fecha_w = w
                        continue
                    if _RE_IMPORTE.match(t):
                        importe_w = w   # si hay varios candidatos en la fila, se queda con el último visto
                        continue
                    resto.append(w)
                cols = {k: [] for k, _ in umbrales}
                for w in resto:
                    if tope_objeto is not None and w["x0"] >= tope_objeto - _EPSILON_COLUMNA:
                        continue   # plazo/duración -- no forma parte del esquema compartido, se descarta
                    cols[_col_de(w["x0"], umbrales)].append(w["text"])
                fila = {k: _limpiar(" ".join(v)) for k, v in cols.items()}
                fila["objeto"] = re.sub(r"P.gina \d+ de \d+", "", fila.get("objeto", "")).strip()
                es_dato = bool(fecha_w and importe_w)
                if not es_dato:
                    if fila.get("nombre"):
                        buf_nombre = (buf_nombre + " " + fila["nombre"]).strip()
                    if fila.get("objeto"):
                        buf_objeto = (buf_objeto + " " + fila["objeto"]).strip()
                    continue
                if buf_nombre:
                    fila["nombre"] = (buf_nombre + " " + fila["nombre"]).strip()
                    buf_nombre = ""
                if buf_objeto:
                    fila["objeto"] = (buf_objeto + " " + fila["objeto"]).strip()
                    buf_objeto = ""
                fecha = _fecha_iso(fecha_w["text"])
                if not fecha or fecha < MENORES_DESDE_FECHA:
                    continue
                nombre = fila.get("nombre") or "No localizada"
                clave = hashlib.sha1(f"{fecha}|{importe_w['text']}|{nombre}|{fila.get('objeto','')}"
                                      .encode("utf-8")).hexdigest()[:16]
                registros.append({
                    "id":               f"burgos::{clave}",
                    "municipio":         "Burgos",
                    "provincia":         "burgos",
                    "fuente":            "burgos",
                    "organisme":         "Ayuntamiento de Burgos",
                    "adjudicatari":      nombre,
                    "nif":               "",   # no publicado en ninguna de las 3 plantillas (ver docstring)
                    "import_num":        round(_importe(importe_w["text"]), 2),
                    "data_adjudicacio":  fecha,
                    "tipus_contracte":   "",
                    "descripcio":        fila.get("objeto", ""),
                    "codi_cpv":          "",
                    "exercici":          fecha[:4],
                })
    return registros


def main():
    print("Descargando página de contratos menores...", flush=True)
    pagina = _get(_URL_PAGINA).decode("utf-8", errors="replace")
    urls = sorted(set(re.findall(r'href="(/documents/[^"]+)"', pagina)))
    print(f"  {len(urls)} documentos enlazados en la página.", flush=True)

    existentes = {}
    for u in urls:
        url = _URL_BASE + u.replace("&amp;", "&")
        nombre_fichero = u.rsplit("/", 2)[-2] if "/" in u else u
        try:
            crudo = _get(url)
        except Exception as e:
            print(f"  !! {url}: error de descarga ({type(e).__name__}: {e})", flush=True)
            continue
        try:
            registros = _parsear_pdf(crudo, nombre_fichero)
        except Exception as e:
            print(f"  !! {url}: error de parseo ({type(e).__name__}: {e})", flush=True)
            continue
        if not registros:
            continue
        nuevos = 0
        for r in registros:
            if r["id"] not in existentes:
                nuevos += 1
            existentes[r["id"]] = r
        print(f"  {nombre_fichero}: {len(registros)} contratos en ventana ({nuevos} nuevos, "
              f"{len(registros) - nuevos} ya vistos en otro fichero)", flush=True)

    tmp = f"{FICHERO}.tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump({
            "generado": time.strftime("%Y-%m-%d"),
            "descripcion": ("Contratos menores del Ayuntamiento de Burgos. Biblioteca de documentos PDF "
                             "clasificados por el título real de cada uno (nunca por el nombre del fichero, "
                             "que es poco fiable en esta fuente). Fecha real de adjudicación e importe con "
                             "IVA por contrato. Sin NIF del adjudicatario. Ver "
                             "actualizar_contratos_menores_burgos.py."),
            "registros": list(existentes.values()),
        }, f, ensure_ascii=False)
    os.replace(tmp, FICHERO)

    print(f"\nHecho: {len(existentes)} registros en {FICHERO}.")


if __name__ == "__main__":
    main()
