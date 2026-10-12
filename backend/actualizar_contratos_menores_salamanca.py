# encoding: utf-8
"""
Contratos MENORES del Ayuntamiento de Salamanca (~144.000 hab., Castilla y León).

Fuente OFICIAL: `aytosalamanca.es/web/guest/contratos-menores`, un PDF por año ("Relación de Contratos
menores") con tabla real de `pdfplumber.extract_tables()` (bordes visibles, se extrae limpio). Enlaces
Liferay sin extensión de fichero en la URL (`/documents/d/guest/contratosmenores2022`, servidos con
`Content-Type: application/pdf`) -- encontrados navegando la página con un navegador real (Playwright).

**Solo hay datos hasta el primer trimestre de 2024**: el fichero de 2024 se llama literalmente
"contratosmenores20241t" (1er trimestre) y no hay ningún fichero de 2024 completo ni de 2025/2026 enlazado en
la página -- se documenta la fuente como parcialmente desactualizada, no se inventa ni se busca en otro sitio.

**Dos formatos de tabla, según el año**:
- 2022, 2023, 2024: 7 columnas con cabecera repetida en cada página: ID | CIF | OBJETO DEL CONTRATO |
  DURACIÓN (en realidad trae una fecha, no una duración -- así la rotula la propia fuente) | IMPORTE ADJ. |
  PROVEEDOR / ADJUDICATARIO | FECHA A.D. (fecha de adjudicación definitiva, la que se usa).
- 2021: 6 columnas, SIN fila de cabecera en ninguna página: ID | CIF | OBJETO | FECHA | IMPORTE | PROVEEDOR
  (un único campo de fecha, que es el que se usa).
Se detecta el formato por el número de columnas de cada fila, no por el año (por si un año futuro cambia).

Fechas en formato español abreviado con variantes ("21-ene-21", "5-ene.-2022", "4-ene.-23": con o sin punto
tras el mes, año de 2 o 4 dígitos) -- se normalizan con una tabla de meses.

Uso (desde backend/):
    python actualizar_contratos_menores_salamanca.py

Genera contratos_menores_salamanca.json.gz, que app.py carga al arrancar (ver
_cargar_contratos_menores_salamanca)."""
import gzip
import io
import json
import os
import re
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "contratos_menores_salamanca.json.gz")
from alcance import alcance_desde
MENORES_DESDE_FECHA = alcance_desde()   # ventana móvil de 5 años (alcance.py), la misma que usa app.py

_BASE = "https://www.aytosalamanca.es/documents/d/guest/"
_UA = "Mozilla/5.0 (compatible; dinero-publico-bot/1.0)"
_FICHEROS = {
    2021: "contratosmenores2021",
    2022: "contratosmenores2022",
    2023: "contratosmenores20234t",
    2024: "contratosmenores20241t",
}
_MESES = {"ene": "01", "feb": "02", "mar": "03", "abr": "04", "may": "05", "jun": "06",
          "jul": "07", "ago": "08", "sep": "09", "oct": "10", "nov": "11", "dic": "12"}
_RE_FECHA = re.compile(r"^(\d{1,2})-([a-záéíóú]{3})\.?-(\d{2,4})$", re.IGNORECASE)


def _limpiar(txt):
    return re.sub(r"\s+", " ", str(txt or "")).strip()


def _fecha_iso(txt):
    m = _RE_FECHA.match(_limpiar(txt).lower())
    if not m:
        return ""
    dia, mes_txt, anio = m.groups()
    mes = _MESES.get(mes_txt[:3])
    if not mes:
        return ""
    if len(anio) == 2:
        anio = f"20{anio}"
    return f"{anio}-{mes}-{dia.zfill(2)}"


def _importe(txt):
    t = re.sub(r"[^\d.,]", "", str(txt or ""))
    if not t:
        return 0.0
    t = t.replace(".", "").replace(",", ".") if "," in t else t
    try:
        return float(t)
    except ValueError:
        return 0.0


def _descargar(url):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _filas_tablas(contenido):
    import pdfplumber
    filas = []
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        for pagina in pdf.pages:
            for tabla in pagina.extract_tables():
                for f in tabla:
                    filas.append([_limpiar(c) for c in f])
    return filas


def _parsear_anio(anio, contenido):
    registros = []
    for i, f in enumerate(_filas_tablas(contenido)):
        if not f or f[0] in ("ID.", "ID", ""):
            continue
        if len(f) >= 7:
            expediente, cif, objeto, _dur, importe_txt, proveedor, fecha_txt = f[:7]
        elif len(f) == 6:
            expediente, cif, objeto, fecha_txt, importe_txt, proveedor = f
        else:
            continue
        proveedor = _limpiar(proveedor)
        if not proveedor:
            continue
        fecha = _fecha_iso(fecha_txt)
        if not fecha or fecha < MENORES_DESDE_FECHA:
            continue
        registros.append({
            "id":               f"salamanca::{anio}-{expediente}-{i}",
            "municipio":         "Salamanca",
            "provincia":         "salamanca",
            "fuente":            "salamanca",
            "organisme":         "Ayuntamiento de Salamanca",
            "adjudicatari":      proveedor,
            "nif":               _limpiar(cif),
            "import_num":        round(_importe(importe_txt), 2),
            "data_adjudicacio":  fecha,
            "tipus_contracte":   "",
            "descripcio":        _limpiar(objeto),
            "codi_cpv":          "",
            "exercici":          fecha[:4],
        })
    return registros


def main():
    existentes = {}
    for anio, slug in sorted(_FICHEROS.items()):
        url = _BASE + slug
        print(f"Descargando {anio} ({slug})...", flush=True)
        try:
            crudo = _descargar(url)
        except Exception as e:
            print(f"  !! {anio}: error de descarga ({type(e).__name__}: {e})", flush=True)
            continue
        registros = _parsear_anio(anio, crudo)
        for r in registros:
            existentes[r["id"]] = r
        print(f"  {anio}: {len(registros)} contratos en ventana", flush=True)

    tmp = f"{FICHERO}.tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump({
            "generado": time.strftime("%Y-%m-%d"),
            "descripcion": ("Contratos menores del Ayuntamiento de Salamanca, informes anuales oficiales en "
                             "PDF (tabla real extraída con pdfplumber), enlaces encontrados navegando la "
                             "página con un navegador real. Solo hay datos hasta el 1er trimestre de 2024 (la "
                             "propia fuente no publica nada más reciente). "
                             "Ver actualizar_contratos_menores_salamanca.py."),
            "registros": list(existentes.values()),
        }, f, ensure_ascii=False)
    os.replace(tmp, FICHERO)
    print(f"\nHecho: {len(existentes)} registros en {FICHERO}.")


if __name__ == "__main__":
    main()
