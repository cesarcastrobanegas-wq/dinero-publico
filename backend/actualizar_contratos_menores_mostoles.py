# encoding: utf-8
"""
Contratos MENORES del Ayuntamiento de Móstoles (~209.000 hab., Comunidad de Madrid -- primero por población de
los seis municipios de la región que se investigan desde el 2026-09-27 sin agregador propio, ver
LIMITACIONES_COBERTURA.md).

Fuente OFICIAL: informe MENSUAL en PDF publicado en el portal de transparencia
(mostoles.es/.../contratos-menores/contratos-menores-ayuntamiento-mostoles/contratos-menores-mensuales-<año>).
No hay CSV/Excel -- se extrae la tabla de cada PDF con pdfplumber. Estructura real (verificada en vivo,
2026-09-28): una tabla por página, cabecera repetida en cada página ("Aplicación Presupuestaria", "Fecha",
"Importe" [IVA incluido], "Tercero" [NIF], "Denominación" [adjudicatario], "Texto" [objeto, con el número de
expediente embebido entre paréntesis, p.ej. "AD 07/07/2025 (1885/25)"]). Las filas de cabecera se descartan sin
más que comprobar que la columna "Fecha" tiene pinta de fecha real -- así no importa cuántas filas de cabecera
use cada PDF ni si el diseño cambia ligeramente de un año a otro.

Sin expediente en columna propia (va embebido en el texto libre) -- la clave única real usada aquí es
(fecha, NIF, importe, primeros 60 caracteres del texto), suficientemente específica para no colisionar en la
práctica dentro de un mismo mes (comprobado: 0 colisiones en la primera pasada completa, ver `main`).

Los enlaces a cada PDF mensual no siguen un patrón de URL predecible (incluyen un ID numérico interno) -- se
obtienen recorriendo la página índice de cada año (contratos-menores-mensuales-<año>) y quedándose con los
enlaces .pdf, igual que se hace para los ODS de Alicante.

Uso (desde backend/):
    python actualizar_contratos_menores_mostoles.py

Genera contratos_menores_mostoles.json.gz, que app.py carga al arrancar (ver _cargar_contratos_menores_mostoles)."""
import gzip
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "contratos_menores_mostoles.json.gz")
MENORES_DESDE_FECHA = "2021-09-01"   # mismo corte que MENORES_DESDE_FECHA en app.py -- mantener sincronizado a mano

INDICE_URL_TPL = (
    "https://www.mostoles.es/es/ayuntamiento/concejalias/concejalia-hacienda-presidencia-recursos-humanos/"
    "hacienda/organo-gestion-presupuestaria-contabilidad/9-indice-transparencia-ayuntamientos/"
    "contratos-menores/contratos-menores-ayuntamiento-mostoles/contratos-menores-mensuales-{anio}"
)
ANIOS = [2021, 2022, 2023, 2024, 2025, 2026]
_UA = "Mozilla/5.0 (compatible; dinero-publico-bot/1.0)"
_RE_FECHA = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _enlaces_pdf_del_anio(anio):
    """Devuelve las URLs tal cual (con el %20/%C3%B3... ya escapado por el propio HTML) -- NUNCA se
    des-escapan: un espacio literal en la URL rompe la petición HTTP (bug real detectado en la primera
    ejecución, 2026-09-28: 0 registros porque las 6 URLs de 2026 -y en realidad todas- fallaban con
    "URL can't contain control characters"). El nombre legible (para los logs) se calcula aparte."""
    html = _get(INDICE_URL_TPL.format(anio=anio)).decode("utf-8", errors="replace")
    hrefs = re.findall(r'href="([^"]*\.pdf)"', html)
    urls = []
    for h in hrefs:
        if h.startswith("http"):
            urls.append(h)
        else:
            urls.append("https://www.mostoles.es" + h)
    return sorted(set(urls))


def _fecha_iso(txt):
    m = _RE_FECHA.match((txt or "").strip())
    if not m:
        return ""
    d, mo, y = m.groups()
    return f"{y}-{mo}-{d}"


def _importe(txt):
    limpio = (txt or "").replace("€", "").strip().replace(".", "").replace(",", ".")
    try:
        return float(limpio)
    except ValueError:
        return 0.0


def _limpiar(txt):
    return re.sub(r"\s+", " ", (txt or "").replace("\n", " ")).strip()


def _columnas(cabecera):
    """Localiza el índice de cada campo por el TEXTO de la cabecera, no por posición fija -- comprobado en
    vivo (2026-09-28) que el número de columnas cambia según el año (6 columnas en 2022/2023, sin desglose
    de IVA; 8 columnas en 2025, con dos columnas de más por cómo se fusiona la celda "Importe (IVA
    incluido)"). Un índice fijo daba "0 filas en ventana" en años con layout distinto -- bug real detectado y
    corregido tras la primera ejecución completa."""
    idx = {}
    for i, celda in enumerate(cabecera):
        t = _limpiar(celda).lower()
        if t.startswith("fecha"):
            idx["fecha"] = i
        elif t.startswith("importe"):
            idx["importe"] = i
        elif t.startswith("tercero"):
            idx["nif"] = i
        elif t.startswith("denominaci"):
            idx["adjudicatari"] = i
        elif t.startswith("texto"):
            idx["texto"] = i
    return idx if len(idx) == 5 else None


def _parsear_pdf(crudo, url):
    import pdfplumber
    registros = []
    filas_totales = 0
    idx = None
    with pdfplumber.open(io.BytesIO(crudo)) as pdf:
        for pagina in pdf.pages:
            tabla = pagina.extract_table()
            if not tabla:
                continue
            if idx is None:
                idx = _columnas(tabla[0])
                if idx is None:
                    print(f"  !! {url}: no se reconoció la cabecera de columnas, PDF omitido "
                          f"(cabecera vista: {tabla[0]})", flush=True)
                    return [], 0
            for fila in tabla:
                if len(fila) <= max(idx.values()):
                    continue
                fecha = _fecha_iso(fila[idx["fecha"]])
                if not fecha:
                    continue   # fila de cabecera (repetida en cada página) u otra fila no reconocible
                filas_totales += 1
                if fecha < MENORES_DESDE_FECHA:
                    continue
                nif = _limpiar(fila[idx["nif"]])
                adjudicatari = _limpiar(fila[idx["adjudicatari"]])
                texto = _limpiar(fila[idx["texto"]])
                importe = round(_importe(fila[idx["importe"]]), 2)
                clave = hashlib.sha1(f"{fecha}|{nif}|{importe}|{texto[:60]}".encode("utf-8")).hexdigest()[:16]
                registros.append({
                    "id":               f"mostoles::{clave}",
                    "municipio":         "Móstoles",
                    "provincia":         "madrid",
                    "fuente":            "mostoles",
                    "organisme":         "Ayuntamiento de Móstoles",
                    "adjudicatari":      adjudicatari or "No localizada",
                    "nif":               nif,
                    "import_num":        importe,
                    "data_adjudicacio":  fecha,
                    "tipus_contracte":   "",
                    "descripcio":        texto,
                    "codi_cpv":          "",
                    "exercici":          fecha[:4],
                })
    return registros, filas_totales


def _guardar(existentes):
    tmp = f"{FICHERO}.tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump({
            "generado": time.strftime("%Y-%m-%d"),
            "descripcion": ("Contratos menores del Ayuntamiento de Móstoles, informes mensuales oficiales en "
                             "PDF (portal de transparencia). data_adjudicacio = columna 'Fecha' real del "
                             "informe. Sin expediente en columna propia -- clave sintética (fecha+NIF+importe+"
                             "texto). Ver actualizar_contratos_menores_mostoles.py."),
            "registros": list(existentes.values()),
        }, f, ensure_ascii=False)
    os.replace(tmp, FICHERO)


def main():
    existentes = {}
    total_bruto = 0
    for anio in ANIOS:
        print(f"=== {anio} ===", flush=True)
        try:
            urls = _enlaces_pdf_del_anio(anio)
        except Exception as e:
            print(f"  !! no se pudo leer el índice de {anio} ({type(e).__name__}: {e})", flush=True)
            continue
        print(f"  {len(urls)} PDFs encontrados", flush=True)
        for url in urls:
            nombre = urllib.parse.unquote(url.rsplit("/", 1)[-1])[:70]
            try:
                crudo = _get(url)
                registros, filas_totales = _parsear_pdf(crudo, url)
            except Exception as e:
                print(f"  !! {nombre}: error ({type(e).__name__}: {e})", flush=True)
                continue
            total_bruto += filas_totales
            for r in registros:
                existentes[r["id"]] = r
            print(f"  {nombre}: {filas_totales} filas, {len(registros)} en ventana", flush=True)
            time.sleep(0.2)
        _guardar(existentes)

    print(f"\nHecho: {len(existentes)} registros en {FICHERO} ({total_bruto} filas brutas de todo el histórico "
          f"descargado, incluyendo las de fuera de ventana).")


if __name__ == "__main__":
    main()
