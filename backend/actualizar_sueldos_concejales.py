# encoding: utf-8
"""
Sueldos de CONCEJALES publicados con nombre por fuentes OFICIALES de cada ayuntamiento (portal de transparencia,
sede electrónica, boletín oficial o la propia web municipal). NUNCA agregadores ni prensa.

Genera backend/sueldos_concejales.json, que app.py carga al arrancar (SUELDOS_CONCEJALES) y muestra en la ficha
del ayuntamiento (sueldos_concejales_html). El bitácora de cada lote está en SUELDOS_CONCEJALES_LOG.md.

Regla de cada registro (encargo de César, 2026-09-26): nombre, cargo/concejalía, importe y URL de la fuente
oficial (+ la base del importe: "bruto anual", "bruto mensual"... tal como la fuente la dice). Si falta cualquiera,
o la base/fuente es ambigua, NO se guarda: nada se adivina ni se completa con estimaciones ni se convierte
(mensual -> anual). Para que ni un error de parseo ni una fila descuadrada cuele un dato falso, cada registro se
VERIFICA contra el texto crudo de la fuente antes de aceptarlo (nuevo_registro): el importe debe aparecer en ese
texto y, dentro de una ventana cerca de él, todos los tokens del nombre.

Uso:  python actualizar_sueldos_concejales.py [fuente ...]      (sin argumentos: todas)
      python actualizar_sueldos_concejales.py --lista           (fuentes registradas)

Cada fuente es una función conector registrada en _FUENTES; devuelve la lista de registros de UN municipio.
Salvaguarda (como en el script de menores): si un conector falla o devuelve menos del 90 % de lo que ya había
para ese municipio, se CONSERVAN los anteriores y se avisa (--forzar para aceptar el resultado nuevo).
"""
import io
import json
import os
import re
import sys
import time
import unicodedata

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_FILE = os.path.join(BASE_DIR, "sueldos_concejales.json")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "es-ES,es;q=0.9",
}


# ── utilidades ──────────────────────────────────────────────────────────────────────────────────────────────
def _norm(s):
    s = unicodedata.normalize("NFD", s or "")
    return re.sub(r"\s+", " ", "".join(c for c in s if unicodedata.category(c) != "Mn").lower()).strip()


def descargar(url, intentos=3, timeout=60, **kw):
    """GET con reintentos; devuelve el Response (lanza si no hay 200 tras los intentos)."""
    ultimo = None
    for i in range(intentos):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout, **kw)
            r.raise_for_status()
            return r
        except Exception as e:
            ultimo = e
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"no se pudo descargar {url}: {ultimo}")


def texto_html(html):
    """Texto plano de un HTML (sin scripts/estilos), con saltos de línea por fila/bloque."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    return soup.get_text("\n")


def texto_pdf(contenido):
    """Texto de un PDF (pdfplumber), página a página."""
    import pdfplumber
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def _formas_importe(importe):
    """Formas en que un importe puede aparecer escrito en la fuente: 45.000,00 / 45.000 / 45000,00 / 45000 / 45,000.00..."""
    formas = set()
    ent, dec = divmod(round(importe * 100), 100)
    dec = int(dec)
    for miles in (".", "", " ", ","):
        e = f"{int(ent):,}".replace(",", miles)
        formas.add(f"{e},{dec:02d}")
        formas.add(f"{e}.{dec:02d}") if miles != "." else None
        if dec == 0:
            formas.add(e)
    return formas


def verificar_en_texto(nombre, importe, texto, ventana=450):
    """True si el importe aparece en `texto` y, en una ventana de ±`ventana` caracteres, aparecen TODOS los tokens
    del nombre (sin tildes ni mayúsculas). Protege contra filas descuadradas y errores de parseo."""
    t = _norm(texto)
    tokens = [x for x in _norm(nombre).replace(",", " ").split() if len(x) > 1]
    if not tokens:
        return False
    for forma in _formas_importe(importe):
        for m in re.finditer(r"(?<![\d.,])" + re.escape(forma) + r"(?![\d])", t):
            w = t[max(0, m.start() - ventana): m.end() + ventana]
            if all(tok in w for tok in tokens):
                return True
    return False


def nuevo_registro(municipio, provincia, nombre, cargo, importe, base, periodo, fuente_url, fuente_nombre, texto_fuente):
    """Registro validado. Lanza ValueError si falta algún campo obligatorio, la URL no es https o el dato no se
    puede comprobar en el texto crudo de la fuente."""
    nombre, cargo, base = (nombre or "").strip(), (cargo or "").strip(), (base or "").strip()
    if not (municipio and nombre and cargo and base and importe and importe > 0 and (fuente_url or "").startswith("https://")):
        raise ValueError(f"registro incompleto: {municipio!r} {nombre!r} {cargo!r} {importe!r} {base!r} {fuente_url!r}")
    if not verificar_en_texto(nombre, importe, texto_fuente):
        raise ValueError(f"no verificable en la fuente: {nombre!r} {importe!r}")
    return {"municipio": municipio, "provincia": provincia, "nombre": nombre, "cargo": cargo, "importe": round(float(importe), 2),
            "base": base, "periodo": (periodo or "").strip(), "fuente_url": fuente_url, "fuente_nombre": (fuente_nombre or "").strip()}


def num_es(txt):
    """'45.000,50' / '45000,5' / '45.000' -> float; None si no es un número claro."""
    x = re.sub(r"[€\s]|euros?", "", txt or "", flags=re.I).rstrip(".,")
    if not x or re.search(r"[A-Za-z]", x) or not re.search(r"\d", x):
        return None
    try:
        if "," in x:
            return float(x.replace(".", "").replace(",", "."))
        if re.match(r"^\d{1,3}(\.\d{3})+$", x):
            return float(x.replace(".", ""))
        return float(x)
    except ValueError:
        return None


# ── conectores (uno por municipio; se añaden por lotes, ver SUELDOS_CONCEJALES_LOG.md) ───────────────────────
_FUENTES = {}


# ── main ────────────────────────────────────────────────────────────────────────────────────────────────────
def _leer():
    if os.path.exists(OUT_FILE):
        with open(OUT_FILE, encoding="utf-8") as f:
            return json.load(f).get("registros", [])
    return []


def _escribir(registros):
    registros = sorted(registros, key=lambda r: (r["provincia"], r["municipio"], -r["importe"], r["nombre"]))
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump({"generado": time.strftime("%Y-%m-%d"),
                   "descripcion": "Sueldos de concejales publicados con nombre por fuentes oficiales de cada ayuntamiento "
                                  "(ver SUELDOS_CONCEJALES_LOG.md). Registro: municipio, provincia, nombre, cargo, importe, base, "
                                  "periodo, fuente_url, fuente_nombre.",
                   "registros": registros}, f, ensure_ascii=False, indent=1)


def main():
    args = sys.argv[1:]
    if "--lista" in args:
        print("\n".join(sorted(_FUENTES)))
        return
    forzar = "--forzar" in args
    pedidas = [a for a in args if not a.startswith("--")] or sorted(_FUENTES)
    desconocidas = [a for a in pedidas if a not in _FUENTES]
    if desconocidas:
        sys.exit(f"Fuente(s) desconocida(s): {desconocidas}. Válidas: {sorted(_FUENTES)}")
    previos = _leer()
    todos = [r for r in previos if _clave_fuente(r) not in pedidas]
    for nombre in pedidas:
        antes = [r for r in previos if _clave_fuente(r) == nombre]
        try:
            nuevos = _FUENTES[nombre]()
        except Exception as e:
            print(f"  !! {nombre}: FALLÓ ({type(e).__name__}: {e}); se conservan las {len(antes)} filas anteriores.")
            todos += antes
            continue
        if antes and not forzar and len(nuevos) < 0.9 * len(antes):
            print(f"  !! {nombre}: devolvió {len(nuevos)} filas frente a las {len(antes)} que ya había (< 90 %); se conservan las anteriores.")
            todos += antes
            continue
        print(f"  {nombre}: {len(nuevos)} concejales")
        todos += nuevos
    _escribir(todos)
    print(f"\nTotal: {len(todos)} registros en {OUT_FILE}")


def _clave_fuente(r):
    """Clave del conector que generó el registro: normalizar(municipio) con guiones bajos (= clave de _FUENTES)."""
    return _norm(r["municipio"]).replace(" ", "_")


if __name__ == "__main__":
    main()
