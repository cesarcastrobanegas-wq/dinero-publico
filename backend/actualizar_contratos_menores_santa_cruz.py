# encoding: utf-8
"""
Contratos MENORES del Ayuntamiento de Santa Cruz de Tenerife (~212.000 hab., Canarias).

Fuente OFICIAL: https://www.santacruzdetenerife.es/gobiernoabierto/transparencia/contratos -- un PDF ANUAL
"Contratos menores <AÑO>" agrupado por concejalía/organismo. Localizado en la auditoría de
DATOS_PETICION_MENORES.md §5. Se usa el PDF y no el CSV: el CSV de 2023-2024 NO trae adjudicatario y el de 2025
es solo un resumen.

Verificado en crudo (2026-09-29):
- 2022-2025: tabla de 7 columnas (Nº CONTRATO / Nº EXPTE. / OBJETO / ADJUDICATARIO / FECHA ADJUD. / IMPORTE
  (Impuestos incl.) / DURACIÓN) SIN líneas de rejilla en las filas de datos: pdfplumber solo reconoce la cabecera
  como tabla. Se reconstruye por POSICIÓN: las x de inicio de columna salen de las celdas de la cabecera de cada
  página, cada palabra va a su columna y cada fila empieza donde aparece un código "MEN<año><nº>" en la 1.ª
  columna. Comprobado: 1.163 filas en 2025 = 1.163 códigos MEN distintos en el texto del PDF.
- Las líneas con texto en la 1.ª columna pero SIN código MEN son el encabezado de bloque (concejalía u
  organismo): se guardan como `organisme` de los contratos que siguen, no se pegan al contrato anterior.
- La duración se cuela a veces en la columna de importe ("4.895,25 €2 MESES"): el importe se saca con una
  expresión regular del texto de ambas columnas. Importe CON impuestos (IGIC; cabecera "Impuestos incl.").
- 2021 NO tiene fecha por contrato (solo totales por trimestre y otro formato): no se carga.

Uso (desde backend/):
    python actualizar_contratos_menores_santa_cruz.py

Genera contratos_menores_santa_cruz.json.gz, que app.py carga al arrancar (_cargar_contratos_menores_santa_cruz)."""
import gzip
import html
import io
import json
import os
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "contratos_menores_santa_cruz.json.gz")
MENORES_DESDE_FECHA = "2021-09-01"   # mismo corte que MENORES_DESDE_FECHA en app.py -- mantener sincronizado a mano
INDICE = "https://www.santacruzdetenerife.es/gobiernoabierto/transparencia/contratos"
BASE = "https://www.santacruzdetenerife.es"
PRIMER_ANIO = 2022
_UA = "Mozilla/5.0 (compatible; dinero-publico-bot/1.0)"
_RE_CODIGO = re.compile(r"^MEN\d{10}$")
_RE_IMPORTE = re.compile(r"(\d{1,3}(?:\.\d{3})*,\d{2})\s*€")


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()


def _norm(txt):
    t = unicodedata.normalize("NFD", str(txt or "").lower())
    return " ".join("".join(c for c in t if unicodedata.category(c) != "Mn").split())


def _limpiar(txt):
    return " ".join(str(txt or "").split())


def _enlaces():
    """{año: url del PDF anual} desde la página de contratos (el nombre del fichero cambia cada año)."""
    pagina = _get(INDICE).decode("utf-8", errors="replace")
    res = {}
    for h in re.findall(r'href="([^"]+\.pdf)"', pagina, re.I):
        h = html.unescape(h)
        nombre = _norm(urllib.parse.unquote(h.rsplit("/", 1)[-1]))
        m = re.search(r"contratos_menores_(?:ano_|ejercicio_)?(20\d\d)", nombre.replace(" ", "_"))
        if m and int(m.group(1)) >= PRIMER_ANIO:
            res.setdefault(int(m.group(1)), h if h.startswith("http") else BASE + h)
    return res


def _cortes(p):
    for t in p.find_tables():
        celdas = [c for c in t.rows[0].cells if c]
        if len(celdas) >= 7:
            primero = _norm(p.crop(celdas[0]).extract_text() or "")
            if "contrato" in primero:
                return [c[0] for c in celdas[:7]], t.bbox[3]
    return None, None


def _filas(crudo):
    import pdfplumber
    out, organismo, xs = [], "", None
    with pdfplumber.open(io.BytesIO(crudo)) as pdf:
        for p in pdf.pages:
            nx, techo = _cortes(p)
            if nx:
                xs = nx
            if not xs:
                continue
            lineas = {}
            for w in p.extract_words():
                lineas.setdefault(round(w["top"]), []).append(w)
            cabecera_bloque = []
            for top in sorted(lineas):
                celdas = [""] * 7
                for w in sorted(lineas[top], key=lambda w: w["x0"]):
                    col = max([i for i, x in enumerate(xs) if w["x0"] >= x - 2] or [0])
                    celdas[col] = (celdas[col] + " " + w["text"]).strip()
                todo = _norm(" ".join(celdas))
                # líneas que no son datos: cabecera de columnas (se repite en cada bloque), título del documento y
                # la línea "viernes, 20 de marzo de 2026   Página 2 de 82" (va arriba en unas páginas y abajo en otras)
                if (("contrato" in todo and "expte" in todo) or todo.startswith("contratos menores")
                        or re.search(r"pagina \d+ de \d+", todo)
                        or re.match(r"^(lunes|martes|miercoles|jueves|viernes|sabado|domingo),", todo)
                        or todo in ("adjud.", "(impuestos incl.)", "plazo ejec.", "adjud. (impuestos incl.) plazo ejec.")):
                    continue
                if _RE_CODIGO.match(celdas[0]):
                    if cabecera_bloque:
                        organismo = _limpiar(" ".join(cabecera_bloque))
                        cabecera_bloque = []
                    out.append({"org": organismo, "c": celdas})
                elif celdas[0]:                          # texto en la 1.ª columna sin código: encabezado de bloque
                    cabecera_bloque.append(" ".join(c for c in celdas if c))
                elif out and not cabecera_bloque:        # continuación de una celda de varias líneas
                    out[-1]["c"] = [(a + " " + b).strip() if b else a for a, b in zip(out[-1]["c"], celdas)]
    return out


def _fecha(txt):
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", txt or "")
    if not m:
        return ""
    try:
        return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def main():
    enlaces = _enlaces()
    print(f"PDF anuales: {sorted(enlaces)}", flush=True)
    registros, descartadas = {}, 0
    for anio in sorted(enlaces):
        crudo = _get(enlaces[anio])
        texto_codigos = None
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(crudo)) as pdf:
                texto_codigos = len(set(re.findall(r"MEN\d{10}", " ".join(p.extract_text() or "" for p in pdf.pages))))
        except Exception:
            pass
        filas = _filas(crudo)
        n = 0
        for f in filas:
            codigo, expte, obj, adj, fec, imp, dur = f["c"]
            fecha = _fecha(fec)
            m = _RE_IMPORTE.search(imp + " " + dur)
            if not fecha or not m or not adj:
                descartadas += 1
                continue
            if fecha < MENORES_DESDE_FECHA:
                continue
            importe = float(m.group(1).replace(".", "").replace(",", "."))
            rid = f"santa_cruz::{codigo}"
            if rid in registros:
                continue
            registros[rid] = {
                "id":               rid,
                "municipio":        "Santa Cruz de Tenerife",
                "provincia":        "santa_cruz_tenerife",
                "fuente":           "santa_cruz",
                "organisme":        f["org"] or "Ayuntamiento de Santa Cruz de Tenerife",
                "adjudicatari":     _limpiar(adj),
                "nif":              "",
                "import_num":       round(importe, 2),
                "data_adjudicacio": fecha,
                "tipus_contracte":  "",
                "descripcio":       _limpiar(obj),
                "codi_cpv":         "",
                "exercici":         fecha[:4],
            }
            n += 1
        print(f"  {anio}: {len(filas)} filas leídas (códigos MEN en el texto: {texto_codigos}), {n} contratos",
              flush=True)
        if texto_codigos and abs(len(filas) - texto_codigos) > 0.02 * texto_codigos:
            raise SystemExit(f"!! {anio}: {len(filas)} filas frente a {texto_codigos} códigos en el texto. No se "
                             f"toca {FICHERO}.")
        time.sleep(0.3)
    if len(registros) < 2500:
        raise SystemExit(f"!! Solo {len(registros)} contratos: posible fallo del origen. No se toca {FICHERO}.")
    tmp = f"{FICHERO}.tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump({
            "generado": time.strftime("%Y-%m-%d"),
            "descripcion": ("Contratos menores del Ayuntamiento de Santa Cruz de Tenerife, PDF anuales oficiales "
                            "2022-2025 reconstruidos por posición. Fecha real, importe con impuestos (IGIC), sin NIF. "
                            "Ver actualizar_contratos_menores_santa_cruz.py."),
            "registros": list(registros.values()),
        }, fh, ensure_ascii=False)
    os.replace(tmp, FICHERO)
    por_anio = {}
    for r in registros.values():
        por_anio[r["exercici"]] = por_anio.get(r["exercici"], 0) + 1
    print(f"Hecho: {len(registros)} contratos {dict(sorted(por_anio.items()))}, {descartadas} filas descartadas "
          f"(sin fecha, importe o adjudicatario) -> {FICHERO}")


if __name__ == "__main__":
    main()
