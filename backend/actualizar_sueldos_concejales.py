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


def nuevo_registro(municipio, provincia, nombre, cargo, importe, base, periodo, fuente_url, fuente_nombre, texto_fuente,
                   verificar_adyacencia=True):
    """Registro validado. Lanza ValueError si falta algún campo obligatorio, la URL no es https o el dato no se
    puede comprobar en el texto crudo de la fuente."""
    nombre, cargo, base = (nombre or "").strip(), (cargo or "").strip(), (base or "").strip()
    if not (municipio and nombre and cargo and base and importe and importe > 0 and (fuente_url or "").startswith("https://")):
        raise ValueError(f"registro incompleto: {municipio!r} {nombre!r} {cargo!r} {importe!r} {base!r} {fuente_url!r}")
    if len(nombre.split()) < 2:
        raise ValueError(f"nombre incompleto (una sola palabra): {nombre!r}")
    # verificar_adyacencia=False SOLO para fuentes que publican el importe por CARGO en una tabla y las personas en otra
    # (p. ej. Málaga): allí el conector valida la unión por su cuenta y aquí se comprueba solo que nombre e importe existen
    # por separado en el texto de la fuente.
    if verificar_adyacencia:
        ok = verificar_en_texto(nombre, importe, texto_fuente)
    else:
        t = _norm(texto_fuente)
        ok = (all(tok in t for tok in _norm(nombre).replace(',', ' ').split() if len(tok) > 1)
              and any(f in t for f in _formas_importe(importe)))
    if not ok:
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


_PARTICULAS = {"de", "del", "la", "las", "los", "y", "e", "el"}


def nombre_persona(apellidos, nombre):
    """'ARAGON JIMENEZ' + 'JUAN TOMAS DE' -> 'Juan Tomas de Aragon Jimenez' (formato "Nombre Apellidos", capitalizado,
    partículas en minúscula; una partícula final del nombre —'... DE'— pasa delante de los apellidos). No se añaden
    ni se quitan tildes: se respeta lo que escribe la fuente."""
    ap, no = (apellidos or "").split(), (nombre or "").split()
    while no and no[-1].lower() in _PARTICULAS:
        ap.insert(0, no.pop())
    palabras = no + ap
    def cap(w):
        return "-".join(x.capitalize() for x in w.split("-")) if (w.isupper() or w.islower()) else w
    return " ".join(w.lower() if (i and w.lower() in _PARTICULAS) else cap(w) for i, w in enumerate(palabras))


_SIGLAS = {"PSOE", "PP", "VOX", "RRHH", "MRH", "PSC", "ERC", "JXCAT", "BNG", "PNV", "CS", "IU", "TTE.", "UP", "EH", "BILDU", "CC", "PAR", "PRC"}


def cargo_frase(cargo):
    """'PORTAVOZ PSOE' -> 'Portavoz PSOE' (frase en minúsculas salvo la 1.ª letra y las siglas de partidos/abreviaturas)."""
    palabras = [w if w.strip(".,").upper() in _SIGLAS else w.lower() for w in (cargo or "").split()]
    frase = " ".join(palabras)
    return frase[:1].upper() + frase[1:]


def filas_tabla_pdf(contenido):
    """Todas las filas de todas las tablas de un PDF (pdfplumber.extract_tables), con las celdas ya limpias."""
    import pdfplumber
    filas = []
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        for pagina in pdf.pages:
            for tabla in pagina.extract_tables():
                for f in tabla:
                    filas.append([re.sub(r"\s+", " ", (c or "")).strip() for c in f])
    return filas


# ── conectores (uno por municipio; se añaden por lotes, ver SUELDOS_CONCEJALES_LOG.md) ───────────────────────
_FUENTES = {}


def _fuente(clave):
    def deco(fn):
        _FUENTES[clave] = fn
        return fn
    return deco


@_fuente("sevilla")
def actualizar_sevilla():
    """Portal de Transparencia del Ayuntamiento de Sevilla > Régimen de retribuciones > Retribuciones Concejales:
    'Retribuciones percibidas por los concejales en 2024' (PDF, actualizado a 23/05/2025). Tabla APELLIDOS | NOMBRE |
    RETRIBUCIONES | dietas | locomoción | asistencia a sesiones | trienio: solo se toma la columna RETRIBUCIONES
    (verificado por posición: incluso los importes pequeños de concejales sin dedicación están en esa columna).
    El documento no dice la concejalía de cada persona: cargo = 'Concejal/a' (el título del documento las identifica
    como concejales). Existe además una 'previsión 2025' (solo dedicaciones) que no se usa: es previsión, no lo percibido."""
    url = ("https://www.sevilla.org/transparencia/informacion-sobre-la-corporacion-municipal/regimen-de-retribuciones/"
           "retribuciones-concejales-2024.pdf")
    contenido = descargar(url).content
    texto = texto_pdf(contenido)
    pagina = ("https://www.sevilla.org/transparencia/informacion-sobre-la-corporacion-municipal/regimen-de-retribuciones")
    out = []
    for f in filas_tabla_pdf(contenido):
        if len(f) < 3 or f[0].upper().startswith("APELLIDOS") or not f[0] or not f[1]:
            continue
        importe = num_es(f[2])
        if not importe or importe <= 0:
            continue
        out.append(nuevo_registro("Sevilla", "sevilla", nombre_persona(f[0], f[1]), "Concejal/a", importe,
                                  "retribuciones percibidas en el año", "2024", url,
                                  "Portal de Transparencia del Ayuntamiento de Sevilla", texto))
    if len(out) < 20:
        raise RuntimeError(f"Sevilla: solo {len(out)} concejales (¿cambió el documento?)")
    return out


@_fuente("malaga")
def actualizar_malaga():
    """Portal de Transparencia del Ayuntamiento de Málaga > Altos cargos > 'Retribuciones del Alcalde y los Concejales, y
    regímenes de dedicación' (Excel oficial). Dos tablas en el mismo libro: (1) 'Régimen dedicación (mes año)': nombre,
    régimen de dedicación y cargo de cada miembro; (2) 'Retribuciones AAAA': retribución anual por CARGO y ámbito. Se une
    cargo -> importe solo en los casos SIN ambigüedad: cargos que existen únicamente en el equipo de gobierno (TENIENTE
    ALCALDE, CONCEJAL DELEGADO) con dedicación del 100 %. Se saltan: PORTAVOZ/PORTAVOZ ADJUNTO (el importe depende de si el
    grupo es de gobierno u oposición y el documento no lo dice por persona), dedicación parcial (la tabla no da importe),
    cargos combinados '/ SECRETARIO' (llevan complemento) y el alcalde (cubierto aparte)."""
    import openpyxl
    url = "https://www.malaga.eu/system/modules/eu.malaga.ayto.corporativas/templates/organigrama/vista-documento.jsp?id=1"
    wb = openpyxl.load_workbook(io.BytesIO(descargar(url).content), data_only=True)
    hojas_reg = [ws for ws in wb.worksheets if ws.title.startswith("Régimen dedicación")]
    hojas_ret = sorted((ws for ws in wb.worksheets if re.match(r"Retribuciones \d{4}$", ws.title)), key=lambda w: w.title)
    if not hojas_reg or not hojas_ret:
        raise RuntimeError("Málaga: cambió la estructura del libro")
    reg, ret = hojas_reg[-1], hojas_ret[-1]
    anio = ret.title.split()[-1]
    escala = {}
    for f in ret.iter_rows(values_only=True):
        if f[0] and str(f[0]).startswith("I. ") and f[1] == "Equipo de gobierno" and f[2] and isinstance(f[3], (int, float)):
            escala[str(f[2]).strip().upper()] = float(f[3])
    texto = "\n".join(" ".join("" if c is None else str(c) for c in f) for ws in (reg, ret) for f in ws.iter_rows(values_only=True))
    out = []
    for f in reg.iter_rows(values_only=True):
        if not f or len(f) < 6 or f[4] is None or str(f[3]).replace("%", "").strip() not in ("100", "1", "1.0"):
            continue
        cargo = str(f[4]).strip().upper()
        if cargo not in ("TENIENTE ALCALDE", "CONCEJAL DELEGADO") or cargo not in escala:
            continue
        nombre = " ".join(str(x).replace("*", "").strip() for x in f[:3] if x)
        out.append(nuevo_registro("Málaga", "malaga", nombre, cargo.capitalize(), escala[cargo],
                                  "retribución anual de su cargo según la tabla oficial (dedicación exclusiva 100 %)",
                                  f"{anio} ({reg.title.split('(')[-1].rstrip(')')})", url,
                                  "Portal de Transparencia del Ayuntamiento de Málaga", texto, verificar_adyacencia=False))
    if len(out) < 8:
        raise RuntimeError(f"Málaga: solo {len(out)} concejales (¿cambió el documento?)")
    return out


@_fuente("cadiz")
def actualizar_cadiz():
    """Portal de Transparencia del Ayuntamiento de Cádiz > ¿Quién es quién? > Concejales: una ficha por concejal con nombre,
    cargo/delegación y apartado RETRIBUCIONES ('Importe anual ( en 14 pagas ) : 45.000,00 €'). Se recorren las fichas del
    listado; solo se guardan las que declaran 'Importe anual' (el resto, sin retribución fija, se salta) y se excluye el
    alcalde (cubierto aparte)."""
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin
    listado = "https://transparencia.cadiz.es/quien-es-quien/concejales/"
    r = descargar(listado)
    enlaces = []
    for a in BeautifulSoup(r.text, "html.parser").find_all("a", href=True):
        h = urljoin(r.url, a["href"])
        if re.match(r"^https://transparencia\.cadiz\.es/quien-es-quien/concejales/[a-z0-9-]+/?$", h) and h not in enlaces:
            enlaces.append(h)
    if len(enlaces) < 20:
        raise RuntimeError(f"Cádiz: solo {len(enlaces)} fichas de concejales (¿cambió la web?)")
    out, sin_importe = [], 0
    for url in enlaces:
        pagina = descargar(url)
        soup = BeautifulSoup(pagina.text, "html.parser")
        cuerpo = soup.find("main") or soup
        for t in cuerpo(["script", "style", "nav", "header", "footer"]):
            t.decompose()
        lineas = [re.sub(r"\s+", " ", x).strip() for x in cuerpo.get_text("\n").split("\n") if x.strip()]
        if "Datos personales" not in lineas or len(lineas) < lineas.index("Datos personales") + 3:
            continue
        i = lineas.index("Datos personales")
        nombre = lineas[i + 1]
        # tras el nombre pueden venir enlaces a redes sociales ('Twitter de X') o el nombre repetido: se ignoran
        cand = [x for x in lineas[i + 2: i + 9]
                if not re.match(r"(?i)(facebook|twitter|instagram|linkedin|youtube|tiktok)\b", x) and _norm(x) != _norm(nombre)]
        cand = [x for x in cand if not (x.isupper() and len(x) > 12)]
        if not cand:
            continue
        tipo, deleg = cand[0], (cand[1] if len(cand) > 1 and not re.match(r"(?i)(fecha|lugar|grupo)", cand[1]) else "")
        if tipo.lower().startswith("alcald"):
            continue
        texto = "\n".join(lineas)
        m = re.search(r"Importe anual\s*\(([^)]*)\)\s*:\s*([\d.,]+)\s*€", texto)
        if not m or not num_es(m.group(2)):
            sin_importe += 1
            continue
        if "máximo" in m.group(1).lower():
            sin_importe += 1          # tope anual de asistencias de concejales sin dedicación, no una retribución: se salta
            continue
        cargo = tipo + (f". {deleg}" if deleg else "")
        out.append(nuevo_registro("Cádiz", "cadiz", nombre, cargo[:220], num_es(m.group(2)),
                                  "importe anual (" + re.sub(r"\s+", " ", m.group(1)).strip() + ")", "vigente (ficha actualizada)",
                                  url, "Portal de Transparencia del Ayuntamiento de Cádiz", texto))
        time.sleep(0.4)
    print(f"  Cádiz: {len(enlaces)} fichas, {len(out)} con importe anual, {sin_importe} sin importe anual")
    if len(out) < 8:
        raise RuntimeError(f"Cádiz: solo {len(out)} concejales con importe (¿cambió el formato?)")
    return out


@_fuente("huelva")
def actualizar_huelva():
    """Portal de Transparencia del Ayuntamiento de Huelva > Ea - Cargos representativos > 'Retribuciones cargos
    representativos AAAA' (PDF). Primera sección 'CORPORACIÓN.- AÑO AAAA' (PUESTO | NOMBRE | NETO): importe NETO anual de
    los cargos con dedicación. Columnas separadas por posición (el puesto ocupa varias líneas). Se saltan la alcaldesa
    (cubierta aparte), la sección de asistencia a plenos y la de atrasos del año anterior."""
    import pdfplumber
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin
    indice = "https://www.huelva.es/portal/es/transparencia/cargos-representativos"
    r = descargar(indice)
    docs = []
    for a in BeautifulSoup(r.text, "html.parser").find_all("a", href=True):
        m = re.search(r"Retribuciones cargos representativos\s+(\d{4})$", a.get_text(" ", strip=True))
        if m:
            docs.append((int(m.group(1)), urljoin(r.url, a["href"])))
    if not docs:
        raise RuntimeError("Huelva: no se encontró el listado de retribuciones")
    anio, pagina_doc = max(docs)
    pdf_url = None
    for a in BeautifulSoup(descargar(pagina_doc).text, "html.parser").find_all("a", href=True):
        if a["href"].lower().endswith(".pdf") and "retribuciones" in a["href"].lower():
            pdf_url = urljoin(pagina_doc, a["href"])
            break
    if not pdf_url:
        raise RuntimeError("Huelva: no se encontró el PDF")
    contenido = descargar(pdf_url).content
    texto = texto_pdf(contenido)
    # La sección principal es la PRIMERA tabla de la primera página (pdfplumber la separa bien por columnas: PUESTO | NOMBRE |
    # NETO); le siguen la de asistencia a plenos y la de atrasos del año anterior, que no se usan.
    out = []
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        pagina = pdf.pages[0]
        titulos = (pagina.extract_text() or "")
        if f"CORPORACIÓN.- AÑO {anio}" not in titulos:
            raise RuntimeError(f"Huelva: el PDF no empieza por 'CORPORACIÓN.- AÑO {anio}'")
        tablas = pagina.find_tables()
        filas = tablas[0].extract() if tablas else []
    for f in filas:
        if len(f) < 3 or (f[0] or "").strip().upper() == "PUESTO" or not f[1] or not f[2]:
            continue
        cargo, nombre, importe = re.sub(r"\s+", " ", f[0] or "").strip(), re.sub(r"\s+", " ", f[1]).strip(), num_es(f[2])
        if not importe or cargo.upper().startswith("ALCALD"):
            continue
        nombre_fmt = " ".join(p_.lower() if p_.lower() in _PARTICULAS else "-".join(x.capitalize() for x in p_.split("-"))
                              for p_ in nombre.split())
        out.append(nuevo_registro("Huelva", "huelva", nombre_fmt, cargo_frase(cargo), importe,
                                  f"importe neto anual percibido en {anio}", str(anio), pdf_url,
                                  "Portal de Transparencia del Ayuntamiento de Huelva", texto))
    if len(out) < 8:
        raise RuntimeError(f"Huelva: solo {len(out)} concejales (¿cambió el documento?)")
    return out


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
        nuevos, alcaldes = _sin_alcalde(nuevos)
        print(f"  {nombre}: {len(nuevos)} concejales" + (f" (excluido el alcalde, cubierto aparte: {alcaldes})" if alcaldes else ""))
        todos += nuevos
    _escribir(todos)
    print(f"\nTotal: {len(todos)} registros en {OUT_FILE}")


def _sin_alcalde(registros):
    """Quita los registros que son el alcalde/sa cuando el fichero del Ministerio (alcaldes_concejales.json, hoy solo
    Murcia y Cataluña) lo identifica: el alcalde ya está cubierto aparte (ISPA). Devuelve (resto, [nombres quitados])."""
    try:
        with open(os.path.join(BASE_DIR, "alcaldes_concejales.json"), encoding="utf-8") as f:
            ministerio = json.load(f).get("municipios", {})
    except Exception:
        return registros, []
    resto, quitados = [], []
    for r in registros:
        info = ministerio.get(_norm(r["municipio"]))
        alc = _norm(((info or {}).get("alcalde") or {}).get("nombre", "")).replace(",", " ").split()
        toks = _norm(r["nombre"]).replace(",", " ").split()
        if alc and set(alc) == set(toks):
            quitados.append(r["nombre"])
        else:
            resto.append(r)
    return resto, quitados


def _clave_fuente(r):
    """Clave del conector que generó el registro: normalizar(municipio) con guiones bajos (= clave de _FUENTES)."""
    return _norm(r["municipio"]).replace(" ", "_")


if __name__ == "__main__":
    main()
