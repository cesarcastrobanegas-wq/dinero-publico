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
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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
    formas.add(f"{int(ent):,}".replace(",", ".") + f".{dec:02d}")   # notación '63.407.63' (Eivissa)
    plano = f"{importe:.2f}".rstrip("0").rstrip(".")      # celdas de Excel: 49777.7 (sin ceros finales)
    formas.update({plano, plano.replace(".", ",")})
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
                   verificar_adyacencia=True, omitir_verificacion=False):
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
    if omitir_verificacion:
        # SOLO para importes que el conector obtiene SUMANDO cifras publicadas (Madrid: mensualidades) y que por tanto no
        # aparecen tal cual en el texto; el nombre sí debe aparecer en la fuente.
        t = _norm(texto_fuente)
        ok = all(tok in t for tok in _norm(nombre).replace(',', ' ').split() if len(tok) > 1)
    elif verificar_adyacencia:
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


_SIGLAS = {"PSOE", "PP", "VOX", "RRHH", "MRH", "PSC", "ERC", "JXCAT", "BNG", "PNV", "CS", "IU", "TTE.", "TTE", "UP", "EH", "BILDU", "CC", "PAR", "PRC", "IU-PODEMOS", "MC", "UPN", "PSN", "EAJ-PNV"}


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


def filas_tablas_html(html, cabecera_regex):
    """Filas (listas de celdas de texto) de las <table> cuya primera fila casa con `cabecera_regex`."""
    from bs4 import BeautifulSoup
    out = []
    for t in BeautifulSoup(html, "html.parser").find_all("table"):
        filas = [[re.sub(r"\s+", " ", c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th"])] for tr in t.find_all("tr")]
        filas = [f for f in filas if any(f)]
        if filas and re.search(cabecera_regex, " ".join(filas[0]), re.I):
            out.append(filas)
    return out


@_fuente("l'hospitalet de llobregat")
def actualizar_hospitalet():
    """Seu electrònica de l'Ajuntament de L'Hospitalet > Organització municipal > 'Retribucions de càrrecs electes': tablas
    'Cognoms i nom | Càrrec | Govern/Oposició | Dedicació | Retribució bruta anual (EUR) | Formació política' de los
    miembros con dedicación exclusiva (y parcial). Acuerdo del Pleno de 26/06/2023; 'Retribucions 2025'. Se excluye el
    alcalde (cubierto aparte)."""
    url = "https://seuelectronica.l-h.cat/238622_1.aspx?id=1"
    r = descargar(url)
    texto = texto_html(r.text)
    m = re.search(r"Retribucions\s+(\d{4})", texto)
    anio = m.group(1) if m else ""
    out = []
    for filas in filas_tablas_html(r.text, r"Cognoms i nom"):
        cab = [c.lower() for c in filas[0]]
        # La 3.ª tabla (concejales sin dedicación) no tiene columna de dedicación: da un tope anual por asistencias
        # ('19.890 (1.657,5 per assistència)'), no una retribución: se salta.
        pos = [next((i for i, c in enumerate(cab) if k in c), None) for k in ("càrrec", "dedic", "bruta anual")]
        if None in pos:
            continue
        ic, ig, ir = pos
        for f in filas[1:]:
            if len(f) <= max(ic, ir) or "," not in f[0]:
                continue
            apellidos, nombre = [x.strip() for x in f[0].split(",", 1)]
            importe = num_es(f[ir])
            if not importe or f[ic].lower().startswith("alcalde"):
                continue
            out.append(nuevo_registro("L'Hospitalet de Llobregat", "barcelona", nombre_persona(apellidos, nombre), f[ic], importe,
                                      "retribució bruta anual (" + (f[ig] or "dedicació").lower() + ")", anio, url,
                                      "Seu electrònica de l'Ajuntament de L'Hospitalet", texto))
    if len(out) < 8:
        raise RuntimeError(f"L'Hospitalet: solo {len(out)} regidores (¿cambió la página?)")
    return out


@_fuente("terrassa")
def actualizar_terrassa():
    """Govern Obert de l'Ajuntament de Terrassa > Retribucions dels càrrecs electes: tabla 'NOM | RETRIBUCIONS 2026 (a: mensual
    bruta, 14 pagues; aa: indemnització d'assistència)'. Solo se guardan los que tienen mensual bruta > 0 (el importe se
    muestra tal cual, mensual, SIN convertir a anual). La tabla no da el cargo de cada persona: cargo = 'Regidor/a'
    (es la tabla de drets econòmics dels regidors). Se excluye el alcalde (cubierto aparte)."""
    url = "https://governobert.terrassa.cat/transparencia/retribucions-carrecs-electes/"
    r = descargar(url)
    texto = texto_html(r.text)
    tablas = filas_tablas_html(r.text, r"^NOM")
    if not tablas:
        raise RuntimeError("Terrassa: no se encontró la tabla")
    out = []
    for f in tablas[0]:
        if len(f) < 2 or not num_es(f[1]) or "€" not in f[1]:
            continue
        nombre = f[0].strip()
        if nombre.lower().startswith("jordi ballart"):
            continue                       # alcalde
        out.append(nuevo_registro("Terrassa", "barcelona", nombre, "Regidor/a", num_es(f[1]), "mensual bruta (14 pagues)", "2026",
                                  url, "Govern Obert de l'Ajuntament de Terrassa", texto))
    if len(out) < 8:
        raise RuntimeError(f"Terrassa: solo {len(out)} regidores (¿cambió la página?)")
    return out


def _titulo_nombre(txt):
    """'FÈLIX LARROSA PIQUÉ' -> 'Fèlix Larrosa Piqué' (partículas en minúscula, guiones respetados)."""
    return " ".join(w.lower() if (i and w.lower() in _PARTICULAS | {"i"}) else "-".join(x.capitalize() for x in w.split("-"))
                    for i, w in enumerate(txt.split()))


@_fuente("sabadell")
def actualizar_sabadell():
    """Ajuntament de Sabadell > Retribucions de l'alcaldessa i els/les regidors/es (PDF; 'Aprovació Ple de 11/10/2024'): tabla
    Regidor | Càrrec | Dedicació | Règim | Retribució bruta mensual | Retribució bruta anual | Indemnitzacions per assistència.
    Solo filas con retribución bruta ANUAL (exclusiva/parcial); las de solo indemnización por asistencia se saltan
    (no son sueldo) y también la alcaldesa (renuncia al sueldo; cubierta aparte)."""
    url = "https://web.sabadell.cat/images/Retribucions_electes.pdf"
    contenido = descargar(url).content
    texto = texto_pdf(contenido)
    m = re.search(r"Aprovaci[oó] Ple de (\d{2}/\d{2}/\d{4})", texto)
    periodo = f"acuerdo del Pleno de {m.group(1)}" if m else ""
    out = []
    for f in filas_tabla_pdf(contenido):
        if len(f) < 6 or f[0].lower().startswith("regidor") or not f[0]:
            continue
        anual = num_es(f[5]) if "----" not in f[5] else None
        if not anual or f[1].lower().startswith("alcald"):
            continue
        out.append(nuevo_registro("Sabadell", "barcelona", f[0], f[1][:220], anual,
                                  "retribució bruta anual (" + (f[2] or "dedicació").lower() + ")", periodo, url,
                                  "Ajuntament de Sabadell (retribucions dels electes)", texto))
    if len(out) < 8:
        raise RuntimeError(f"Sabadell: solo {len(out)} regidores (¿cambió el documento?)")
    return out


@_fuente("lleida")
def actualizar_lleida():
    """La Paeria (Ajuntament de Lleida) > Cartipàs > Retribucions > Retribucions càrrecs electes (PDF vigente, 'Data
    actualització'): NOM I COGNOMS | CÀRREC | GRUP | DEDICACIÓ | RETRIBUCIÓ MENSUAL | RETRIBUCIÓ ANUAL (= mensual x 14).
    Solo dedicación EXCLUSIVA/PARCIAL con importe anual; comprobación de integridad: anual == mensual x 14 (±0,5): una fila
    con un importe mal escrito en origen (p. ej. '60,300,10 €') se SALTA y se anota. Se excluye el Paer en cap (alcalde)."""
    url = "https://www.paeria.cat/ca/ajuntament/el-govern/cartipas/retribucions/retribucions-carrecs-electes/carrecs-electes-febrer-2026.pdf"
    r = descargar(url)
    texto = texto_pdf(r.content)
    m = re.search(r"Data actualitzaci[oó]:\s*(\d{2}/\d{2}/\d{4})", texto)
    periodo = "2026" + (f" (actualizado el {m.group(1)})" if m else "")
    out, saltadas = [], []
    for f in filas_tabla_pdf(r.content):
        if len(f) < 8 or f[0].upper().startswith("NOM I") or f[5].upper() not in ("EXCLUSIVA", "PARCIAL"):
            continue
        nombre = re.sub(r"\s+\d+$", "", f[0]).strip()               # llamada a nota al pie pegada al nombre ("... CÉSPEDES 4")
        mensual, anual = num_es(f[6]), num_es(f[7])
        if not (mensual and anual and abs(mensual * 14 - anual) <= 0.5):
            saltadas.append(nombre)
            continue
        if f[3].upper().startswith("PAER EN CAP"):
            continue
        out.append(nuevo_registro("Lleida", "lleida", _titulo_nombre(nombre), cargo_frase(f[3])[:220], anual,
                                  f"retribució anual, 14 pagues ({f[5].lower()})", periodo, r.url,
                                  "La Paeria (Ajuntament de Lleida), Retribucions càrrecs electes", texto))
    if saltadas:
        print(f"  Lleida: saltadas por importe ilegible/incoherente en origen: {saltadas}")
    if len(out) < 8:
        raise RuntimeError(f"Lleida: solo {len(out)} regidors (¿cambió el documento?)")
    return out


# ── Plataforma seu-e.cat (sede electrónica oficial de muchos ayuntamientos catalanes) ────────────────────────
_SEUE_BASE = "https://seu-e.cat/ca/web/{slug}/govern-obert-i-transparencia/informacio-institucional-i-organitzativa/organitzacio-politica-i-retribucions/carrecs-electes"


def _seue_enlaces(slug):
    """URLs de las fichas 'veureCarrec/ID' del listado de cargos electes de un ayuntamiento en seu-e.cat ([] si no existe)."""
    try:
        r = requests.get(_SEUE_BASE.format(slug=slug), headers=HEADERS, timeout=40)
    except requests.RequestException:
        return []
    if r.status_code != 200 or "veureCarrec" not in r.text:
        return []
    ids = []
    for m in re.finditer(r"veureCarrec/(\d+)", r.text):
        if m.group(1) not in ids:
            ids.append(m.group(1))
    return [_SEUE_BASE.format(slug=slug) + f"/-/grupPolitic/veureCarrec/{i}" for i in ids]


def seue_concejales(slug, municipio, provincia):
    """Fichas de cargos electes de un ayuntamiento en seu-e.cat: 'Retribució anual bruta: Any 2026: 63.983,06 € (dedicació
    exclusiva ...)'. Solo se guardan las fichas que declaran esa retribución (importe del año tal como figura); se excluye el
    alcalde. Cargo = el de la ficha (p. ej. 'Tinent/a d'alcalde', 'Regidor/a')."""
    from bs4 import BeautifulSoup
    enlaces = _seue_enlaces(slug)
    if len(enlaces) < 8:
        raise RuntimeError(f"{municipio}: la plataforma seu-e.cat no devuelve fichas de cargos electes")
    out, sin_retribucion = [], 0
    for url in enlaces:
        pagina = descargar(url)
        soup = BeautifulSoup(pagina.text, "html.parser")
        for t in soup(["script", "style", "noscript", "nav", "header", "footer"]):
            t.decompose()
        lineas = [re.sub(r"\s+", " ", x).strip() for x in soup.get_text("\n").split("\n") if x.strip()]
        texto = "\n".join(lineas)
        try:
            i = lineas.index("Càrrec electe")
        except ValueError:
            continue
        nombre, cargo = lineas[i - 3], lineas[i - 2]
        m = re.search(r"Retribuci[oó] anual bruta:\s*Any\s+(\d{4}):\s*([\d.,]+)\s*€\s*(\([^)]*\))?", texto)
        if not m or not num_es(m.group(2)):
            sin_retribucion += 1
            continue
        if cargo.lower().startswith("alcald"):
            continue
        detalle = (m.group(3) or "").strip("() ")
        try:
            # nombre (cabecera de la ficha) e importe (bloque 'Retribució anual bruta') están en la MISMA ficha pero lejos
            # entre sí (lista de comisiones en medio): se comprueba que ambos existen en la ficha, no su adyacencia.
            out.append(nuevo_registro(municipio, provincia, nombre, cargo, num_es(m.group(2)),
                                      "retribució anual bruta" + (f" ({detalle})" if detalle else ""), m.group(1), url,
                                      f"Seu electrònica de l'Ajuntament de {municipio} (seu-e.cat)", texto,
                                      verificar_adyacencia=False))
        except ValueError as e:
            print(f"  {municipio}: ficha saltada ({e})")
        time.sleep(0.3)
    print(f"  {municipio}: {len(enlaces)} fichas, {len(out)} con retribución anual bruta, {sin_retribucion} sin retribución publicada")
    return out


# municipios de seu-e.cat: clave del conector -> (slug de la sede, nombre, provincia)
_SEUE = {
    "badalona": ("badalona", "Badalona", "barcelona"),
    "tarragona": ("tarragona", "Tarragona", "tarragona"),
    "girona": ("girona", "Girona", "girona"),
    "rubí": ("rubi", "Rubí", "barcelona"),
    "castelldefels": ("castelldefels", "Castelldefels", "barcelona"),
    "viladecans": ("viladecans", "Viladecans", "barcelona"),
    "granollers": ("granollers", "Granollers", "barcelona"),
    "vic": ("vic", "Vic", "barcelona"),
    "gavà": ("gava", "Gavà", "barcelona"),
    "blanes": ("blanes", "Blanes", "girona"),
    "ripollet": ("ripollet", "Ripollet", "barcelona"),
    "olot": ("olot", "Olot", "girona"),
    "salt": ("salt", "Salt", "girona"),
    "calafell": ("calafell", "Calafell", "tarragona"),
    "sitges": ("sitges", "Sitges", "barcelona"),
    "martorell": ("martorell", "Martorell", "barcelona"),
    "palafrugell": ("palafrugell", "Palafrugell", "girona"),
    "manlleu": ("manlleu", "Manlleu", "barcelona"),
    "banyoles": ("banyoles", "Banyoles", "girona"),
    "roses": ("roses", "Roses", "girona"),
    "tàrrega": ("tarrega", "Tàrrega", "lleida"),
    "cardedeu": ("cardedeu", "Cardedeu", "barcelona"),
    "tordera": ("tordera", "Tordera", "barcelona"),
    "palamós": ("palamos", "Palamós", "girona"),
    "torredembarra": ("torredembarra", "Torredembarra", "tarragona"),
    "cubelles": ("cubelles", "Cubelles", "barcelona"),
    "canovelles": ("canovelles", "Canovelles", "barcelona"),
    "castellbisbal": ("castellbisbal", "Castellbisbal", "barcelona"),
    "argentona": ("argentona", "Argentona", "barcelona"),
    "montgat": ("montgat", "Montgat", "barcelona"),
    "alella": ("alella", "Alella", "barcelona"),
    "alcarràs": ("alcarras", "Alcarràs", "lleida"),
    "masquefa": ("masquefa", "Masquefa", "barcelona"),
    "palafolls": ("palafolls", "Palafolls", "barcelona"),
    "matadepera": ("matadepera", "Matadepera", "barcelona"),
    "cervelló": ("cervello", "Cervelló", "barcelona"),
    "llagostera": ("llagostera", "Llagostera", "girona"),
    "tiana": ("tiana", "Tiana", "barcelona"),
    "vidreres": ("vidreres", "Vidreres", "girona"),
    "roquetes": ("roquetes", "Roquetes", "tarragona"),
    "polinyà": ("polinya", "Polinyà", "barcelona"),
    "tona": ("tona", "Tona", "barcelona"),
    "guissona": ("guissona", "Guissona", "lleida"),
}
for _clave, (_slug, _muni, _prov) in _SEUE.items():
    _FUENTES[_norm(_muni)] = (lambda s=_slug, m=_muni, p=_prov: seue_concejales(s, m, p))


@_fuente("madrid")
def actualizar_madrid():
    """Portal de Transparencia del Ayuntamiento de Madrid > Recursos humanos > Retribuciones > 'Retribuciones brutas percibidas
    en nómina por cargos electos, periodo 2025' (PDF; una fila por persona y mes: unidad, cargo, nombre, año, mes, régimen,
    % dedicación, retribuciones). El importe guardado es la SUMA de las mensualidades brutas publicadas de cada persona en el
    año (aritmética sobre cifras oficiales, no una estimación) y la base dice cuántas mensualidades son. Se saltan el
    alcalde (cubierto aparte) y las personas con un mes repetido (dato ambiguo)."""
    url = ("https://transparencia.madrid.es/UnidadAyre/Estructura/CargosPoliticosDirectivosYEventuales/ficheros/"
           "RetribucionesCargosElectos_2025.pdf")
    contenido = descargar(url, timeout=120).content
    texto = texto_pdf(contenido)
    por_persona = {}
    for f in filas_tabla_pdf(contenido):
        if len(f) < 11 or not f[6].isdigit() or f[7] not in {str(i) for i in range(1, 13)}:
            continue
        importe = num_es(f[10])
        if importe is None:
            continue
        por_persona.setdefault(f[2], []).append((int(f[7]), importe, f[1], f[0]))
    if len(por_persona) < 30:
        raise RuntimeError(f"Madrid: solo {len(por_persona)} personas (¿cambió el documento?)")
    out, saltadas = [], []
    for nombre, filas in por_persona.items():
        meses = [m for m, _, _, _ in filas]
        if len(set(meses)) != len(meses):
            saltadas.append(nombre)
            continue
        cargos = list(dict.fromkeys(c for _, _, c, _ in filas))
        if any(c.upper().startswith("ALCALDE") for c in cargos):
            continue
        total = round(sum(i for _, i, _, _ in filas), 2)
        if total <= 0:
            continue
        unidad = filas[-1][3].replace("P.P.", "PP").replace("p.p.", "PP")
        # la fuente escribe a veces el mismo cargo de dos formas ("Delegado/a area de gobierno" / "Delegado/a de area de
        # gobierno"): se dejan una sola vez (comparando sin artículos ni tildes)
        vistos, unicos = set(), []
        for c in cargos:
            k = re.sub(r"\s+", " ", re.sub(r"\b(de|del|la)\b", "", _norm(c))).strip()
            if k not in vistos:
                vistos.add(k)
                unicos.append(c)
        cargo = " / ".join(cargo_frase(c) for c in unicos) + f" ({unidad.capitalize().replace(' pp', ' PP')})"
        n = len(filas)
        out.append(nuevo_registro("Madrid", "madrid", _titulo_nombre(nombre), cargo[:240], total,
                                  f"suma de las retribuciones brutas percibidas en nómina en el año ({n} mensualidad{'es' if n != 1 else ''})",
                                  "2025", url, "Portal de Transparencia del Ayuntamiento de Madrid", texto,
                                  omitir_verificacion=True))
    if saltadas:
        print(f"  Madrid: saltadas por mes repetido: {saltadas}")
    return out


@_fuente("elche")
def actualizar_elche():
    """Portal de Transparencia del Ayuntamiento de Elche > Cargos, personal y retribuciones > Sueldos públicos: un bloque por
    concejal (nombre, concejalía, tenencia de alcaldía y 'Dedicación exclusiva/75 % (Anual 2026): importe €'; o, sin dedicación,
    'Retribución anual 2026 por tenencia de alcaldía: importe €'). Cada bloque repite la línea en valenciano: se ignora.
    Solo se guardan los bloques con importe anual; se excluye el alcalde (cubierto aparte)."""
    url = "https://www.elche.es/transparencia-gobierno-abierto/informacion-institucional-y-organizativa/cargos-personal-y-retribuciones/sueldos-publicos/"
    r = descargar(url)
    texto = texto_html(r.text)
    lineas = [re.sub(r"\s+", " ", x).strip() for x in texto.split("\n")]
    lineas = [x for x in lineas if x]
    try:
        inicio = max(i for i, x in enumerate(lineas) if x.startswith("Régimen de dedicación de los concejales")) + 2
    except ValueError:
        raise RuntimeError("Elche: no se encontró el inicio del listado")
    re_ded = re.compile(r"^Dedicación (exclusiva|\d+ ?%)\s*\(Anual (\d{4})\):\s*([\d.,]+)\s*€")
    re_ten = re.compile(r"^Sin dedicación\. Retribución anual (\d{4}) por tenencia de alcadía ([\d.,]+)\s*€")
    re_cargo = re.compile(r"^(Vicealcald|Alcald|Concejal|(Primer|Segund|Tercer|Cuart|Quint|Sext|Séptim|Octav|Noven|Décim)[oa]? Teniente)", re.I)
    out, buf = [], []
    for x in lineas[inicio:]:
        m1, m2 = re_ded.match(x), re_ten.match(x)
        if x.startswith(("Dedicació ", "Sense dedicació")):
            buf = []                                   # línea en valenciano: cierra el bloque
            continue
        if re.fullmatch(r"[\d.,]+|€", x):
            continue                                   # importe partido en varias líneas en la versión valenciana
        if m1 or m2:
            # Un concejal sin línea de importe (sin dedicación) deja sus líneas en el buffer: el bloque de ESTE importe empieza
            # en la última línea que no parece un cargo (nombre); lo anterior es de otra persona y se descarta.
            k = max((i for i, y in enumerate(buf) if not re_cargo.match(y)), default=None)
            if k is not None and len(buf) - k >= 2:
                nombre, cargo = buf[k], ". ".join(buf[k + 1:])
                if m1:
                    importe, base, anio = num_es(m1.group(3)), f"importe anual (dedicación {m1.group(1).replace(' ', '')})", m1.group(2)
                else:
                    importe, base, anio = num_es(m2.group(2)), "retribución anual por tenencia de alcaldía (sin dedicación)", m2.group(1)
                if importe and not cargo.lower().startswith("alcalde") and cargo.split(".")[0].strip().lower() != "alcalde":
                    out.append(nuevo_registro("Elche", "alicante", nombre, cargo[:240], importe, base, anio, url,
                                              "Portal de Transparencia del Ayuntamiento de Elche", texto))
            buf = []
            continue
        buf.append(x)
        if len(buf) > 6:
            buf = buf[-6:]                              # ruido antes/después del listado
    if len(out) < 8:
        raise RuntimeError(f"Elche: solo {len(out)} concejales (¿cambió la página?)")
    return out


@_fuente("mataro")
def actualizar_mataro():
    """Portal de Transparència de l'Ajuntament de Mataró > Retribucions dels càrrecs electes > 'Retribució i dedicació de l'alcalde
    i els regidors AAAA' (Excel; el del último año publicado): 'Cognoms, nom | Càrrec | Grup | Tipo personal | DEDICACIÓ |
    RETRIBUCIÓ ANUAL AAAA'. Solo filas con dedicación numérica (1 = 100 %, 0,75 = 75 %) y retribución; las de 'Assistència a
    Plens' (dietas) no son sueldo y se saltan; se excluye el alcalde (cubierto aparte)."""
    import openpyxl
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin
    pagina = "https://www.mataro.cat/transparencia/organitzacio-politica-i-retribucions/retribucions-de-lalcalde-i-els-regidors/retribucions-dels-carrecs-electes"
    r = descargar(pagina)
    docs = []
    for a in BeautifulSoup(r.text, "html.parser").find_all("a", href=True):
        m = re.search(r"Retribuci[oó] i dedicaci[oó] de l'alcalde i els regidors (\d{4})$", a.get_text(" ", strip=True))
        if m and a["href"].lower().endswith(".xlsx"):
            docs.append((int(m.group(1)), urljoin(r.url, a["href"])))
    if not docs:
        raise RuntimeError("Mataró: no se encontró ningún Excel de retribuciones")
    anio, url = max(docs)
    wb = openpyxl.load_workbook(io.BytesIO(descargar(url).content), data_only=True)
    ws = wb.worksheets[0]
    filas = [list(f) for f in ws.iter_rows(values_only=True)]
    texto = "\n".join(" ".join("" if c is None else str(c) for c in f) for f in filas)
    out = []
    for f in filas:
        if not f or not f[0] or "," not in str(f[0]) or str(f[0]).lower().startswith("cognoms"):
            continue
        cargo, dedic, importe = str(f[1] or "").strip(), f[4], f[5]
        if not isinstance(dedic, (int, float)) or not isinstance(importe, (int, float)) or importe <= 0:
            continue                                   # 'Assistència a Plens' u otros sin dedicación numérica
        if cargo.lower().startswith("alcalde"):
            continue
        # 'Assistència a Plens' en el cargo = dietas (aunque la columna de dedicación diga 1); e importes < 20.000 € con
        # dedicación numérica son un periodo parcial (p. ej. 75 % y 8.791 €), no una retribución anual comparable: se saltan.
        if "assist" in cargo.lower() or importe < 20000:
            continue
        apellidos, nombre = [x.strip() for x in str(f[0]).split(",", 1)]
        out.append(nuevo_registro("Mataró", "barcelona", nombre_persona(apellidos, nombre), cargo, float(importe),
                                  f"retribució anual {anio} (dedicació {round(dedic * 100)}%)", f"{anio} (a 31/12/{anio})", url,
                                  "Portal de Transparència de l'Ajuntament de Mataró", texto))
    if len(out) < 8:
        raise RuntimeError(f"Mataró: solo {len(out)} regidors (¿cambió el Excel?)")
    return out


@_fuente("vigo")
def actualizar_vigo():
    """Portal de Transparencia del Concello de Vigo > 10. Retribuciones de los cargos electos > 'Retribuciones del alcalde, de las
    concejalas y los concejales' (Resolución de la Alcaldía, expediente 3891/1101, julio de 2023): lista de concelleiros en
    dedicación EXCLUSIVA y en dedicación PARCIAL (26 horas) con su importe anual. Es una resolución fechada: el periodo lo dice.
    Se excluye el alcalde (cubierto aparte)."""
    url = "https://transparencia.vigo.org/?id_file=870&lang=es&file="
    contenido = descargar(url, timeout=90).content
    if contenido[:4] != b"%PDF":
        raise RuntimeError("Vigo: el fichero ya no es un PDF")
    texto = texto_pdf(contenido)
    re_linea = re.compile(r"^(Alcalde|Concelleir[oa](?: do g\.m\. [^ ]+(?: [^ ]+)?)?)\.?\s+(?:D\.|Dª)\s+(.+?)\s+([\d.]+,\d{2}) €$")
    out, seccion = [], None
    for x in [re.sub(r"\s+", " ", l).strip() for l in texto.split("\n")]:
        if x.startswith("Primeiro.") and "dedicación exclusiva" in x:
            seccion = "exclusiva"
        elif x.startswith("Segundo.") and "dedicación parcial" in x:
            seccion = "parcial (26 horas)"
        m = re_linea.match(x)
        if not m or not seccion or m.group(1) == "Alcalde":
            continue
        out.append(nuevo_registro("Vigo", "pontevedra", m.group(2), m.group(1).rstrip("."), num_es(m.group(3)),
                                  f"retribución anual (dedicación {seccion})", "resolución de la Alcaldía de julio de 2023", url,
                                  "Portal de Transparencia del Concello de Vigo", texto))
    if len(out) < 8:
        raise RuntimeError(f"Vigo: solo {len(out)} concelleiros (¿cambió el documento?)")
    return out


@_fuente("logrono")
def actualizar_logrono():
    """Ayuntamiento de Logroño > Corporación local > 'Retribuciones e indemnizaciones de los miembros de la Corporación Municipal
    (actualización ...)' (PDF vigente, p. ej. junio 2026): tabla APELLIDOS Y NOMBRE | CARGO | GRUPO MUNICIPAL | TIPO DEDICACIÓN |
    RETRIBUCIÓN ANUAL. Solo 'Dedicación exclusiva/parcial' (las 'Indemnización asistencias' son dietas: se saltan); se excluye el
    alcalde (cubierto aparte)."""
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin
    pagina = "https://logrono.es/corporacion-local"
    r = descargar(pagina)
    url = None
    for a in BeautifulSoup(r.text, "html.parser").find_all("a", href=True):
        if a.get_text(" ", strip=True).startswith("Retribuciones e indemnizaciones de los miembros de la Corporación Municipal (actualiza"):
            url = urljoin(r.url, a["href"])
            break
    if not url:
        raise RuntimeError("Logroño: no se encontró el PDF de retribuciones vigente")
    contenido = descargar(url, timeout=120).content
    texto = texto_pdf(contenido)
    m = re.search(r"Retribuciones (\d{4})", texto)
    anio = m.group(1) if m else ""
    out = []
    for f in filas_tabla_pdf(contenido):
        f = [c for c in f if c]                      # la 1.ª tabla trae celdas vacías de relleno entre columnas
        if len(f) < 5 or f[0].upper().startswith("APELLIDOS"):
            continue
        tipo = f[3].lower()
        importe = num_es(f[4])
        if not importe or "dedicación" not in tipo or f[1].upper().startswith("ALCALDE"):
            continue
        out.append(nuevo_registro("Logroño", "la_rioja", f[0], cargo_frase(f[1]) + f" ({f[2].title()})", importe,
                                  f"retribución anual ({tipo})", anio, url, "Ayuntamiento de Logroño (transparencia)", texto))
    if len(out) < 8:
        raise RuntimeError(f"Logroño: solo {len(out)} concejales (¿cambió el documento?)")
    return out


@_fuente("murcia")
def actualizar_murcia():
    """Ayuntamiento de Murcia > Institucional > 'Dedicación y Retribuciones de los miembros de la Corporación Municipal': el PDF más
    reciente de la lista ('Régimen de dedicación y retribuciones de los miembros de la Corporación (2023-2027)', p. ej. febrero 2024):
    tabla Nombre | Grupo | Dedicación | Competencias | Puesto | Retribuciones AÑO. El documento es el último que publica el
    ayuntamiento y está fechado (el periodo lo dice). Se excluye el alcalde (cubierto aparte)."""
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin
    pagina = "https://web.murcia.es/institucional/dedicacion-retribuciones-corporacion"
    r = descargar(pagina)
    pdfs = [urljoin(r.url, a["href"]) for a in BeautifulSoup(r.text, "html.parser").find_all("a", href=True)
            if re.search(r"dedicacion", a["href"], re.I) and a["href"].lower().endswith(".pdf")]
    if not pdfs:
        raise RuntimeError("Murcia: no se encontró el PDF de retribuciones")
    url = pdfs[0]
    contenido = descargar(url, timeout=90).content
    texto = texto_pdf(contenido)
    m = re.search(r"CORPORACI[ÓO]N.{0,30}?\)\s*([A-ZÁÉÍÓÚ]+ \d{4})", texto)
    periodo = f"documento de {m.group(1).lower()}" if m else "documento vigente"
    out = []
    for f in filas_tabla_pdf(contenido):
        f = [c for c in f if c]
        if len(f) < 6 or f[0].lower().startswith("nombre"):
            continue
        importe = num_es(f[-1])
        if not importe or f[4].lower().startswith("alcalde"):
            continue
        out.append(nuevo_registro("Murcia", "murcia", f[0], f[4], importe,
                                  f"retribución anual (dedicación {f[2].lower()}, {f[3].lower()})", periodo, url,
                                  "Ayuntamiento de Murcia (dedicación y retribuciones de la Corporación)", texto))
    if len(out) < 15:
        raise RuntimeError(f"Murcia: solo {len(out)} concejales (¿cambió el documento?)")
    return out


@_fuente("santa cruz de tenerife")
def actualizar_santa_cruz_tenerife():
    """Portal de Transparencia del Ayuntamiento de Santa Cruz de Tenerife > Retribuciones > Altos cargos > 'Retribución percibida
    anualmente y dedicación de los miembros electos': la PRIMERA tabla (el año más reciente publicado: EMPLEADO/A | DENOMINACIÓN
    PUESTO | Dedicación | Periodo | RETRIBUCIÓN €). Solo filas con el año COMPLETO (01/01 a 31/12): las de periodos parciales se
    saltan (importe no comparable). Las tablas de años anteriores traen celdas combinadas y no se usan. Se excluye el alcalde."""
    url = "https://www.santacruzdetenerife.es/gobiernoabierto/transparencia/retribuciones/altos-cargos"
    r = descargar(url)
    texto = texto_html(r.text)
    tablas = filas_tablas_html(r.text, r"EMPLEADO")
    if not tablas:
        raise RuntimeError("Santa Cruz de Tenerife: no se encontró la tabla")
    out, parciales = [], 0
    for f in tablas[0][1:]:
        if len(f) != 5 or "," not in f[0]:
            continue
        m = re.match(r"^01/01/(\d{4}) a 31/12/(\d{4})$", f[3])
        if not m or m.group(1) != m.group(2):
            parciales += 1
            continue
        importe = num_es(f[4])
        if not importe or f[1].upper().startswith("ALCALDE"):
            continue
        apellidos, nombre = [x.strip() for x in f[0].split(",", 1)]
        out.append(nuevo_registro("Santa Cruz de Tenerife", "santa_cruz_tenerife", nombre_persona(apellidos, nombre), cargo_frase(f[1]),
                                  importe, f"retribución percibida en el año (dedicación {f[2].lower()})", m.group(1), url,
                                  "Portal de Transparencia del Ayuntamiento de Santa Cruz de Tenerife", texto))
    if parciales:
        print(f"  Santa Cruz de Tenerife: {parciales} filas con periodo parcial saltadas")
    if len(out) < 8:
        raise RuntimeError(f"Santa Cruz de Tenerife: solo {len(out)} concejales (¿cambió la página?)")
    return out


def _sin_tratamiento(nombre):
    """'Dña. María Dolores Moreno Molino' / 'D.  Pablo Pérez' -> sin el tratamiento (D., Dª, Dña., Doña)."""
    return re.sub(r"^(?:D\.|Dª|Dña\.|Doña|Don)\s+", "", re.sub(r"\s+", " ", (nombre or "").replace("\xa0", " ")).strip())


@_fuente("majadahonda")
def actualizar_majadahonda():
    """Portal de Transparencia de Majadahonda > Retribuciones percibidas > 'Retribuciones de la Alcaldesa y Concejales 2025' (Excel):
    Nombre | Cargo | Grupo | CORPORACIÓN 2025 (importe). Se guardan las personas con UNA sola fila e importe > 0; las de dos
    filas por cambio de cargo a mitad de año (hasta/desde una fecha) se saltan por ambiguas, y las 'En régimen de asistencia' (0 €).
    Se excluye la alcaldesa (cubierta aparte)."""
    import openpyxl
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin
    pagina = "https://transparencia.majadahonda.org/retribuciones-de-la-alcaldesa-y-concejales-2025"
    r = descargar(pagina)
    url = None
    for a in BeautifulSoup(r.text, "html.parser").find_all("a", href=True):
        if "formato Excel" in a.get_text(" ", strip=True) and "Retribuciones brutas" in a.get_text(" ", strip=True):
            url = urljoin(r.url, a["href"])
            break
    if not url:
        raise RuntimeError("Majadahonda: no se encontró el Excel de retribuciones")
    wb = openpyxl.load_workbook(io.BytesIO(descargar(url).content), data_only=True)
    filas = [list(f) for f in wb.worksheets[0].iter_rows(values_only=True)]
    texto = "\n".join(" ".join("" if c is None else str(c) for c in f) for f in filas)
    contadas = {}
    for f in filas:
        if f and f[0] and f[1] and isinstance(f[3], (int, float)):
            contadas[_sin_tratamiento(str(f[0]))] = contadas.get(_sin_tratamiento(str(f[0])), 0) + 1
    out, dobles = [], []
    for f in filas:
        if not (f and f[0] and f[1] and isinstance(f[3], (int, float))) or str(f[0]).startswith("Nombre"):
            continue
        nombre, cargo, importe = _sin_tratamiento(str(f[0])), re.sub(r"\s+", " ", str(f[1])).strip(), float(f[3])
        if contadas[nombre] > 1:
            dobles.append(nombre)
            continue
        if importe <= 0 or cargo.lower().startswith("alcalde"):
            continue
        out.append(nuevo_registro("Majadahonda", "madrid", nombre, cargo, importe, "retribución bruta anual 2025", "2025", url,
                                  "Portal de Transparencia del Ayuntamiento de Majadahonda", texto))
    if dobles:
        print(f"  Majadahonda: saltadas por dos filas (cambio de cargo en el año): {sorted(set(dobles))}")
    if len(out) < 8:
        raise RuntimeError(f"Majadahonda: solo {len(out)} concejales (¿cambió el Excel?)")
    return out


@_fuente("molina de segura")
def actualizar_molina_de_segura():
    """Portal de Transparencia de Molina de Segura > Información sobre cargos públicos > 'Las retribuciones percibidas anualmente':
    tabla Cargo | Nombre | Retribución bruta | Dedicación | Partido de la Corporación 2023-2027 (la propia página se titula
    'retribuciones percibidas anualmente'). Se excluye el alcalde (cubierto aparte)."""
    url = "https://transparencia.molinadesegura.es/publicidad-activa/informacion-sobre-cargos-publicos/las-retribuciones-percibidas-anualmente/"
    r = descargar(url)
    texto = texto_html(r.text)
    m = re.search(r"Fecha de última revisión/actualización:\s*(\d{2}/\d{2}/\d{4})", texto)
    periodo = f"Corporación 2023-2027 (revisado el {m.group(1)})" if m else "Corporación 2023-2027"
    tablas = filas_tablas_html(r.text, r"^Cargo")
    if not tablas:
        raise RuntimeError("Molina de Segura: no se encontró la tabla")
    out = []
    for f in tablas[0][1:]:
        if len(f) < 4 or not num_es(f[2]) or f[0].lower().startswith("alcalde"):
            continue
        out.append(nuevo_registro("Molina de Segura", "murcia", f[1], f[0], num_es(f[2]),
                                  f"retribución bruta anual (dedicación {f[3].lower()})", periodo, url,
                                  "Portal de Transparencia del Ayuntamiento de Molina de Segura", texto))
    if len(out) < 8:
        raise RuntimeError(f"Molina de Segura: solo {len(out)} concejales (¿cambió la tabla?)")
    return out


@_fuente("palencia")
def actualizar_palencia():
    """Ayuntamiento de Palencia > Corporación municipal > Retribuciones corporación > 'Retribuciones íntegras de los Miembros de la
    Corporación con dedicación exclusiva o parcial año AAAA' (PDF del último año publicado): 'Apellidos, Nombre | Cargo | Retribuciones'
    (retribuciones íntegras percibidas en el año; algunas son de un año parcial por altas/bajas y se muestran tal cual). El nombre
    de pila y el cargo van seguidos en mayúsculas: se separan en la primera palabra ALCALD*/CONCEJAL*. Se excluye la alcaldesa."""
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin
    pagina = "https://www.aytopalencia.es/ayuntamiento/corporacion-municipal/retribuciones-corporacion"
    r = descargar(pagina)
    docs = []
    for a in BeautifulSoup(r.text, "html.parser").find_all("a", href=True):
        m = re.match(r"Retribuciones íntegras de los Miembros de la Corporación con dedicación exclusiva o parcial año (\d{4})$", a.get_text(" ", strip=True))
        if m:
            docs.append((int(m.group(1)), urljoin(r.url, a["href"])))
    if not docs:
        raise RuntimeError("Palencia: no se encontró el PDF de retribuciones")
    anio, url = max(docs)
    texto = texto_pdf(descargar(url, timeout=90).content)
    out = []
    for linea in [re.sub(r"\s+", " ", x).strip() for x in texto.split("\n")]:
        m = re.match(r"^([A-ZÁÉÍÓÚÑÜ' -]+), (.+?) ([\d.]+,\d{2})$", linea)
        if not m:
            continue
        resto = m.group(2)
        k = re.search(r"\b(ALCALD\w*|CONCEJAL\w*)\b", resto)
        if not k or k.start() == 0:
            continue
        nombre, cargo = resto[:k.start()].strip(), resto[k.start():].strip()
        if cargo.upper().startswith("ALCALD"):
            continue
        out.append(nuevo_registro("Palencia", "palencia", nombre_persona(m.group(1), nombre), cargo_frase(cargo), num_es(m.group(3)),
                                  "retribuciones íntegras percibidas en el año (dedicación exclusiva o parcial)", str(anio), url,
                                  "Ayuntamiento de Palencia (retribuciones de la Corporación)", texto))
    if len(out) < 8:
        raise RuntimeError(f"Palencia: solo {len(out)} concejales (¿cambió el PDF?)")
    return out


@_fuente("eivissa")
def actualizar_eivissa():
    """Ayuntamiento de Eivissa > Corporación > Retribuciones regidores: tabla Nombre | Cargo | Dedicación | Régimen | Retribución anual
    2025 | Indemnizaciones anuales 2025. Filas cuyo importe no es un número claro (p. ej. '63.407.63 €', con punto en vez de coma
    decimal) se SALTAN y se anotan: no se corrige un dato de la fuente adivinando. Se excluye el alcalde."""
    url = "https://www.eivissa.es/es/retribucions-regidors"
    r = descargar(url)
    texto = texto_html(r.text)
    tablas = filas_tablas_html(r.text, r"^Nombre")
    if not tablas:
        raise RuntimeError("Eivissa: no se encontró la tabla")
    cab = tablas[0][0]
    m = re.search(r"(\d{4})", cab[4] if len(cab) > 4 else "")
    anio = m.group(1) if m else ""
    out, ilegibles = [], []
    for f in tablas[0][1:]:
        if len(f) < 5 or not f[0] or f[1].lower().startswith("alcalde"):
            continue
        importe = num_es(f[4])
        if importe is None:
            # notación de la fuente '63.407.63 €' (punto de millar Y punto decimal): patrón exacto de 3 grupos con 2 cifras finales,
            # inequívoco (no puede ser otra cifra) y coherente con las demás filas; cualquier otra rareza se salta.
            m = re.match(r"^(\d{1,3})\.(\d{3})\.(\d{2})\s*€?$", f[4].strip())
            if m:
                importe = float(f"{m.group(1)}{m.group(2)}.{m.group(3)}")
            elif f[4].strip() in ("-", ""):
                continue                              # sin retribución (concejal sin dedicación)
            else:
                ilegibles.append(f"{f[0]} ({f[4]})")
                continue
        out.append(nuevo_registro("Eivissa", "baleares", f[0], f[1][:230], importe,
                                  f"retribución anual (dedicación {f[2].lower()})", anio, url,
                                  "Ayuntamiento de Eivissa (retribuciones de los regidores)", texto))
    if ilegibles:
        print(f"  Eivissa: saltadas por importe ilegible en origen: {ilegibles}")
    if len(out) < 8:
        raise RuntimeError(f"Eivissa: solo {len(out)} regidores (¿cambió la tabla?)")
    return out


@_fuente("cartagena")
def actualizar_cartagena():
    """Ayuntamiento de Cartagena > Portal de Transparencia > Personal directivo y eventual: PDF 'Retribuciones de la corporación municipal y
    del personal eventual' (actualizado, p. ej., a 29/05/2026), sección 'Alcaldesa y concejales. Legislatura 2023-2027': PUESTO | GRUPO |
    NOMBRE Y APELLIDOS | JORNADA | RETRIB. BRUTAS (anuales). Se guardan las filas con jornada completa o porcentaje; las 'ASIST. PLENOS'
    (asistencias) no son sueldo y se saltan. Algunos nombres se parten en dos líneas en el PDF: se recomponen. Se excluye la alcaldesa."""
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin
    pagina = "https://www.cartagena.es/personal_directivo_eventual.asp"
    r = descargar(pagina)
    url = None
    for a in BeautifulSoup(r.text, "html.parser").find_all("a", href=True):
        t = a.get_text(" ", strip=True)
        if t.startswith("Retribuciones de la corporación municipal y del personal eventual") and "PDF" in t.upper():
            url = urljoin(r.url, a["href"])
            break
    if not url:
        raise RuntimeError("Cartagena: no se encontró el PDF de retribuciones de la corporación")
    texto = texto_pdf(descargar(url, timeout=120).content)
    m = re.search(r"actualizado a (\d{2}/\d{2}/\d{4})", texto, re.I)
    periodo = "legislatura 2023-2027" + (f" (actualizado a {m.group(1)})" if m else "")
    lineas = [re.sub(r"\s+", " ", x).strip() for x in texto.split("\n")]
    try:
        ini = next(i for i, x in enumerate(lineas) if x.lower().startswith("alcaldesa y concejales"))
    except StopIteration:
        raise RuntimeError("Cartagena: no se encontró la sección de alcaldesa y concejales")
    re_fila = re.compile(r"^(?P<puesto>CONCEJAL (?:PP|MC|PSOE|VOX|GRUPO MIXTO|CONCEJAL NO ADSCRITO)|ALCALDESA PP)\s+(?P<resto>.+?)\s+"
                         r"(?P<jornada>C[O0]MPLETA|\d{2}%|MEDIA)\s+(?P<imp>[\d.]+,\d{2}) €$")
    out, pendiente, asist = [], "", 0
    for x in lineas[ini + 1:]:
        if x.startswith(("Coordinador General", "Documento actualizado", "RETRIB.", "PUESTO", "LEGISLATURA")) or x.isdigit():
            if x.startswith("Coordinador General"):
                break
            continue
        if x.startswith("ASIST."):
            asist += 1
            pendiente = ""
            continue
        m = re_fila.match(x)
        if not m:
            if re.match(r"^(D\.|Dª)\s", x) and "€" not in x:
                pendiente = x                       # 1.ª línea de un nombre partido en dos
            continue
        nombre = re.sub(r"^(D\.|Dª)\s+", "", ((pendiente + " ") if pendiente and not re.match(r"^(D\.|Dª)\s", m.group("resto")) else "") + m.group("resto"))
        nombre = re.sub(r"^(D\.|Dª)\s+", "", nombre)
        pendiente = ""
        if m.group("puesto").startswith("ALCALDESA"):
            continue
        jornada = "completa" if m.group("jornada").startswith("C") else m.group("jornada").lower()
        out.append(nuevo_registro("Cartagena", "murcia", _titulo_nombre(nombre), cargo_frase(m.group("puesto")), num_es(m.group("imp")),
                                  f"retribuciones brutas anuales (jornada {jornada})", periodo, url,
                                  "Portal de Transparencia del Ayuntamiento de Cartagena", texto))
    if asist:
        print(f"  Cartagena: {asist} concejales con 'ASIST. PLENOS' (asistencias) saltados")
    if len(out) < 12:
        raise RuntimeError(f"Cartagena: solo {len(out)} concejales (¿cambió el PDF?)")
    return out


@_fuente("alcoy")
def actualizar_alcoy():
    """Ajuntament d'Alcoi > Corporación > Retribuciones > 'Cuadro de retribuciones de dedicaciones exclusivas y parciales': un PDF por año (el más reciente enlazado;
    hoy 'Retribuciones Concejales 2023', mandato 2023-2027). Línea por persona: APELLIDOS, NOMBRE | CARGO | GRUPO | % dedicación | SALARIO ANUAL | SALARIO MENSUAL (14 pagas).
    Se saltan las filas 'Asistencias' y 'Renuncia' (sin salario) y el alcalde (cubierto aparte)."""
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin
    pagina = "https://www.alcoi.org/es/ayuntamiento/Corporacion/retribuciones/retribu_dedic_exclusivas_parciales.html"
    r = descargar(pagina, verify=False)
    cand = []
    for a in BeautifulSoup(r.text, "html.parser").find_all("a", href=True):
        m = re.match(r"^A[ñn]o (\d{4})", a.get_text(" ", strip=True))
        if m and a["href"].lower().endswith(".pdf"):
            cand.append((m.group(1), urljoin(r.url, a["href"])))
    if not cand:
        raise RuntimeError("Alcoy: no se encontró el PDF de retribuciones de dedicaciones")
    anio, url = max(cand)
    texto = texto_pdf(descargar(url, timeout=120, verify=False).content)
    re_fila = re.compile(r"^(?P<ap>[^,]+), (?P<no>.+?) (?P<cargo>ALCALDE|TENIENTE DE ALCALDE(?:/PORTAVOZ)?|PORTAVOZ|CONCEJAL SIN DELEGACI[OÓ]N|CONCEJAL CON DELEGACI[OÓ]N) "
                         r"(?P<grupo>[A-ZÁÉÍÓÚÑ]+) (?P<pct>\d+,\d+) % (?P<anual>[\d.]+,\d{2}) (?P<men>[\d.]+,\d{2})$")
    out, sin_salario = [], 0
    for x in (re.sub(r"\s+", " ", l).strip() for l in texto.split("\n")):
        if " % Asistencias" in x or " % Renuncia" in x:
            sin_salario += 1
            continue
        m = re_fila.match(x)
        if not m or m.group("cargo") == "ALCALDE":
            continue
        out.append(nuevo_registro("Alcoy", "alicante", nombre_persona(m.group("ap"), m.group("no")), f'{cargo_frase(m.group("cargo"))} ({m.group("grupo")})',
                                  num_es(m.group("anual")), f"salario anual (14 pagas; dedicación {m.group('pct').replace(',00', '')} %)", f"año {anio}", url,
                                  "Web del Ayuntamiento de Alcoy: retribuciones de dedicaciones exclusivas y parciales", texto))
    if sin_salario:
        print(f"  Alcoy: {sin_salario} filas de asistencias/renuncia (sin salario) saltadas")
    if len(out) < 15:
        raise RuntimeError(f"Alcoy: solo {len(out)} concejales (¿cambió el PDF?)")
    return out


@_fuente("sagunto")
def actualizar_sagunto():
    """Ajuntament de Sagunt > Transparencia: PDF 'Retribuciones y dedicación del alcalde y los concejales/concejalas de la Corporación 2023/2027' (1.er trimestre
    de 2026). Columnas: grupo político | nombre y apellidos | dedicación (Exclusiva/Parcial/Asistencias) | % | salario bruto/mes (14 pagas) | SALARIO BRUTO ANUAL |
    retribuciones efectivamente percibidas en el trimestre. Se guarda el SALARIO BRUTO ANUAL de exclusiva/parcial; las filas de 'Asistencias' (sin salario) se saltan.
    El documento no rotula el cargo ni separa al alcalde (figura como una persona más con dedicación exclusiva): cargo = 'Alcalde o concejal (grupo)'.
    La URL del PDF es un enlace con hash de la web (la página no lo expone de forma legible): si el Ayuntamiento publica otro trimestre hay que actualizarla."""
    url = "https://aytosagunto.es/media/0cnm1k0u/copia-de-retribuciones-altos-cargos1-trimestre-2026.pdf"
    texto = texto_pdf(descargar(url, timeout=120, verify=False).content)
    m = re.search(r"PERCIBIDAS (\d)\S* trim\. (\d{4})", re.sub(r"\s+", " ", texto))
    periodo = f"{m.group(1)}.er trimestre de {m.group(2)} (salario bruto anual de la tabla)" if m else "salario bruto anual de la tabla"
    re_fila = re.compile(r"^(?:(?P<g>[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ-]+(?: [A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ-]+)*) )?(?P<nombre>[A-ZÁÉÍÓÚÑ][^\d€]*?) (?P<ded>Exclusiva|Parcial) (?P<pct>\d+) "
                         r"(?P<men>[\d.]+,\d{2}) € (?P<anual>[\d.]+,\d{2}) € (?P<perc>[\d.]+,\d{2}) €(?: .*)?$")
    out, grupo, asist = [], "", 0
    for x in (re.sub(r"\s+", " ", l).strip() for l in texto.split("\n")):
        if re.search(r" Asi?stencias ", x + " "):
            asist += 1
            g = re.match(r"^([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ-]+(?: [A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ-]+)*) [A-ZÁÉÍÓÚÑ][a-záéíóúñ]", x)
            if g:
                grupo = g.group(1)
            continue
        m = re_fila.match(x)
        if not m:
            continue
        if m.group("g"):
            grupo = m.group("g")
        out.append(nuevo_registro("Sagunto", "valencia", m.group("nombre"), f"Alcalde o concejal ({grupo})", num_es(m.group("anual")),
                                  f"salario bruto anual (14 pagas; dedicación {m.group('ded').lower()} {m.group('pct')} %)", periodo, url,
                                  "Web del Ayuntamiento de Sagunto: retribuciones y dedicación de la Corporación", texto))
    if asist:
        print(f"  Sagunto: {asist} filas de 'Asistencias' (sin salario) saltadas")
    if len(out) < 8:
        raise RuntimeError(f"Sagunto: solo {len(out)} personas (¿cambió el PDF?)")
    return out


@_fuente("torrevieja")
def actualizar_torrevieja():
    """Ayuntamiento de Torrevieja > Gobierno Abierto > una ficha web por representante (nombre, cargo, retribución
    bruta anual del año vigente y dedicación), en vez de una tabla. El menú desplegable de cualquier ficha lista a
    TODOS los representantes agrupados por legislatura ('Legislatura: 2019-2023' / 'Legislatura: 2023-2027'); solo
    se recorren los de la legislatura vigente (la última que aparece). Se incluyen también los de dedicación
    'Sin dedicación' (el importe que muestra la fuente ya es el total anual por asistencias, no hay que estimar
    nada) y 'Parcial'. Se excluye el alcalde (cubierto aparte)."""
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin
    seed = descargar("https://gobiernoabierto.torrevieja.es/t/representantes/694", timeout=60)
    dd = BeautifulSoup(seed.text, "html.parser").find("div", class_="dropdown-menu")
    if dd is None:
        raise RuntimeError("Torrevieja: no se encontró el desplegable de representantes")
    legislatura, ids_por_legislatura = None, {}
    for el in dd.find_all(["span", "a"], recursive=False):
        if el.name == "span" and el.get_text(strip=True).startswith("Legislatura:"):
            legislatura = el.get_text(strip=True)
            ids_por_legislatura.setdefault(legislatura, [])
        elif el.name == "a" and legislatura:
            m = re.search(r"/representantes/(\d+)", el.get("href", ""))
            if m:
                ids_por_legislatura[legislatura].append(m.group(1))
    legislatura_vigente = list(ids_por_legislatura)[-1]
    ids = ids_por_legislatura[legislatura_vigente]

    out = []
    for rid in ids:
        url = f"https://gobiernoabierto.torrevieja.es/t/representantes/{rid}"
        r = descargar(url, timeout=60)
        soup = BeautifulSoup(r.text, "html.parser")
        cargo_el = soup.find("strong", class_="cargo1")
        nombre_el = soup.find("strong", style=re.compile("font-size: ?20px"))
        if not cargo_el or not nombre_el or cargo_el.get_text(strip=True).lower().startswith("alcalde"):
            continue
        tabla = next((t for t in soup.find_all("table") if "Retribuci" in t.get_text()), None)
        fila = tabla.find_all("tr")[1] if tabla else None
        if fila is None:
            continue
        celdas = [re.sub(r"\s+", " ", c.get_text(" ", strip=True)) for c in fila.find_all(["td", "th"])]
        m = re.match(r"^(\d{4}): ([\d.]+,\d{2})$", celdas[0])
        if not m:
            continue
        dedicacion = celdas[4] if len(celdas) > 4 else ""
        texto = texto_html(r.text)
        nombre = re.sub(r"^(D\.|Dña\.?|D)\s+", "", nombre_el.get_text(strip=True))
        out.append(nuevo_registro("Torrevieja", "alicante", nombre, cargo_frase(cargo_el.get_text(strip=True)),
                                  num_es(m.group(2)), f"retribución bruta anual percibida en {m.group(1)} según su ficha (dedicación: {dedicacion.lower()}; "
                                  "si es 'sin dedicación' es el total por asistencias, ya sumado por la fuente)",
                                  legislatura_vigente, url, "Portal de Gobierno Abierto del Ayuntamiento de Torrevieja: ficha del representante", texto,
                                  # La ficha de cada representante lista, en un menú de navegación, los NOMBRES de TODOS los demás
                                  # representantes (otras legislaturas incluidas) muy lejos en el texto de la tabla de retribución de
                                  # ESTA persona -- sin riesgo de cruce (una ficha = una persona = un importe), así que no hace
                                  # falta exigir cercanía; basta con que el nombre y el importe existan en la página.
                                  verificar_adyacencia=False))
    if len(out) < 15:
        raise RuntimeError(f"Torrevieja: solo {len(out)} concejales (¿cambió la página?)")
    return out


@_fuente("pozuelo de alarcon")
def actualizar_pozuelo_de_alarcon():
    """Ayuntamiento de Pozuelo de Alarcón > Corporación Municipal > 'Composición del Pleno': una ficha por
    concejal/a (nombre en negrita + cargo + enlace 'Retribuciones y régimen de dedicación' con el importe anual
    entre paréntesis a continuación, p. ej. '(84.044,94 €)'). Los concejales sin dedicación llevan
    '(Asistencias, concejal sin dedicación)' o directamente no llevan paréntesis: se saltan (sin importe). Se
    excluye la alcaldesa (cubierta aparte)."""
    from bs4 import BeautifulSoup
    url = "https://www.pozuelodealarcon.org/tu-ayuntamiento/organizacion-municipal/corporacion-municipal"
    r = descargar(url)
    texto = texto_html(r.text)
    out, sin_importe = [], 0
    for bloque in BeautifulSoup(r.text, "html.parser").find_all("div", class_="col-sm-8"):
        strong = bloque.find("p") and bloque.find("p").find("strong")
        ul = bloque.find("ul")
        if not strong or not ul:
            continue
        nombre = re.sub(r"\s+", " ", strong.get_text(" ", strip=True)).strip()
        cargo_li = ul.find("li", recursive=False)
        cargo = ""
        if cargo_li:
            for br in cargo_li.find_all("br"):
                br.replace_with(" \x00 ")
            cargo = re.sub(r"\s*\x00\s*", "; ", re.sub(r"\s+", " ", cargo_li.get_text(" ", strip=True))).strip()
        if not nombre or cargo.lower().startswith(("alcalde", "alcaldesa")):
            continue
        retrib_li = next((li for li in ul.find_all("li", recursive=False)
                          if "Retribuciones y régimen de dedicación" in li.get_text()), None)
        if retrib_li is None:
            continue
        m = re.search(r"\(([\d.]+,\d{2})\s*€\)", retrib_li.get_text(" ", strip=True))
        if not m:
            sin_importe += 1
            continue
        out.append(nuevo_registro("Pozuelo de Alarcón", "madrid", nombre, cargo_frase(cargo), num_es(m.group(1)),
                                  "retribución anual según su ficha en la web del Ayuntamiento (régimen de dedicación)",
                                  "vigente", url, "Web del Ayuntamiento de Pozuelo de Alarcón: composición del Pleno", texto))
    if sin_importe:
        print(f"  Pozuelo de Alarcón: {sin_importe} concejales sin importe (asistencias o sin dedicación) saltados")
    if len(out) < 10:
        raise RuntimeError(f"Pozuelo de Alarcón: solo {len(out)} concejales (¿cambió la página?)")
    return out


@_fuente("alcala de henares")
def actualizar_alcala_de_henares():
    """Ayuntamiento de Alcalá de Henares > 'Retribuciones de los Concejales' (actualizada a 14/08/2025). NO es una
    tabla: es un párrafo por tramo de cargo/dedicación, con la lista de personas de ese tramo entre paréntesis y el
    importe (compartido por todo el tramo) a continuación: 'Tenientes de Alcalde (Dª. X, D. Y y Dª Z): 85.754,18 €'.
    Algunos nombres llevan una nota entre llaves: '{hasta el DD/MM/AAAA}' (ya no está en ese tramo -> se excluye) o
    '{desde el DD/MM/AAAA}' (entró después del acuerdo -> se incluye, con la fecha en el periodo); un tramo puede
    llevar el 'desde DD/MM/AAAA' delante de todo el listado en vez de en cada nombre. Los tramos sin nadie
    ('actualmente no hay ningún concejal en dicha situación') se saltan. Se excluye la alcaldesa (cubierta aparte)."""
    from urllib.parse import urljoin
    from bs4 import BeautifulSoup
    url = "https://www.ayto-alcaladehenares.es/retribuciones-de-los-concejales/"
    r = descargar(url, verify=False)
    texto = texto_html(r.text)
    m = re.search(r"(\d{1,2} \w+ \d{4}) \| Retribuciones de los Concejales", texto)
    periodo_base = f"acuerdo del Pleno, tal como se publica (actualizado a {m.group(1)})" if m else "acuerdo del Pleno vigente"
    re_tramo = re.compile(r"^(?P<cargo>.+?)\s*\((?P<names>.*?)\)\s*:?\s*(?P<imp>[\d.]+,\d{2})\s*€")
    re_desde_tramo = re.compile(r"^desde el (\d{2}/\d{2}/\d{4})\s+(.+)$")
    re_nota_persona = re.compile(r"\s*\{([^}]*)\}")
    out = []
    for p in BeautifulSoup(r.text, "html.parser").find_all(["p", "li"]):
        t = re.sub(r"\s+", " ", p.get_text(" ", strip=True)).strip()
        m = re_tramo.match(t)
        if not m or m.group("cargo").lower().startswith("alcaldesa") or "actualmente no hay ningún concejal" in m.group("names"):
            continue
        cargo, names, imp = m.group("cargo").strip(), m.group("names"), num_es(m.group("imp"))
        desde_tramo = ""
        md = re_desde_tramo.match(names.strip())
        if md:
            desde_tramo, names = md.group(1), md.group(2)
        # Protege las comas DENTRO de una nota entre llaves (p.ej. '{esta última, hasta el 31/12/2023}') para que
        # el split de abajo no las trate como separador de persona; y separa también un cierre de llave pegado
        # directamente al siguiente nombre sin coma ('...García {desde el 18/03/2025} Dª Alba...', visto en la
        # fuente real) igual que si fuera ' y '.
        names_prot = re.sub(r"\{[^}]*\}", lambda m: m.group(0).replace(",", "\x00"), names)
        names_prot = re.sub(r"\}\s+(?=D[ª.]?\s)", "}, ", names_prot)
        for nombre in re.split(r",\s*| y (?=D[ª.]?\s)", names_prot):
            nombre = nombre.replace("\x00", ",").strip().rstrip(",")
            if not nombre or not re.match(r"^D[ª.]?\s", nombre):
                continue   # ruido suelto tras una coma (p.ej. 'a partir del 01/01/2024'), no un nombre
            notas = re_nota_persona.findall(nombre)
            nombre_limpio = re_nota_persona.sub("", nombre).strip()
            nombre_limpio = re.sub(r"^(D\.|Dª\.?|D)\s+", "", nombre_limpio)
            if any("hasta el" in n.lower() for n in notas):
                continue   # ya no está en este tramo: se salta
            desde_persona = next((re.search(r"desde el (\d{2}/\d{2}/\d{4})", n) for n in notas if "desde el" in n.lower()), None)
            desde = (desde_persona.group(1) if desde_persona else None) or desde_tramo
            periodo = periodo_base + (f"; en este tramo desde el {desde}" if desde else "")
            out.append(nuevo_registro("Alcalá de Henares", "madrid", nombre_limpio, cargo_frase(cargo), imp,
                                      "importe fijado por tramo de cargo/dedicación (lo comparten todas las personas del tramo)",
                                      periodo, url, "Web del Ayuntamiento de Alcalá de Henares: retribuciones de los concejales", texto))
    if len(out) < 10:
        raise RuntimeError(f"Alcalá de Henares: solo {len(out)} concejales (¿cambió la página?)")
    return out


@_fuente("calvia")
def actualizar_calvia():
    """Ajuntament de Calvià > Transparencia > Corporación 2023-2027 > 'Retribuciones e indemnizaciones de los miembros de la Corporación' (enlace 'AQUÍ' =
    acuerdo plenario de 23/06/2023 publicado en el BOIB nº 93 de 8/07/2023). El punto 'Primero' lista, por cargo, las personas con dedicación exclusiva y la
    retribución bruta anual de cada cargo ('58.550'00 euros'). Se guardan tenientes de alcalde y concejales; se excluye el alcalde (cubierto aparte) y NO se
    guardan las 'indemnizaciones por asistencia' de los puntos Segundo y Tercero (no son sueldo). Importes de 2023: pueden haberse actualizado."""
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin
    pagina = "https://www.calvia.com/es/ayuntamiento/transparencia/corporacion-2023-2027/copy_of_estructura-organizativa-del-ajuntament-de-calvia"
    r = descargar(pagina, verify=False)
    url = None
    for a in BeautifulSoup(r.text, "html.parser").find_all("a", href=True):
        if a.get_text(strip=True).upper().startswith("AQU") and a["href"].lower().endswith(".pdf"):
            url = urljoin(r.url, a["href"])
            break
    if not url:
        raise RuntimeError("Calvià: no se encontró el enlace al acuerdo plenario")
    texto = texto_pdf(descargar(url, timeout=120, verify=False).content)
    plano = re.sub(r"\s+", " ", texto)
    i, j = plano.find("Primero.-"), plano.find("Los anteriores miembros")
    if i < 0 or j < i:
        raise RuntimeError("Calvià: no se reconoce el punto 'Primero' del acuerdo")
    m_bo = re.search(r"N[uú]m\. (\d+) (\d{1,2} de \w+ de \d{4})", plano)
    m_ac = re.search(r"Acuerdo plenario de (\d{2}\.\d{2}\.\d{2})", plano)
    periodo = (f"acuerdo plenario de {m_ac.group(1).replace('.', '/')}" if m_ac else "acuerdo plenario") + (f" (BOIB nº {m_bo.group(1)}, {m_bo.group(2)})" if m_bo else "")
    verif = texto.replace("'", ",")                      # 58.550'00 -> 58.550,00 (solo para la comprobación contra el texto crudo)
    cargos = {"Tenientes de Alcalde": "Teniente de Alcalde", "Concejales": "Concejal"}
    out = []
    for item in re.split(r"\s(?=\d\. [A-Z])", plano[i:j]):
        m = re.match(r"^\d\. (?P<cargo>Alcalde-Presidente|Tenientes de Alcalde|Concejales) (?P<nombres>.+?): (?P<imp>[\d.]+'\d{2}) euros distribuidos en (?P<pagas>.+?)\.?$", item)
        if not m or m.group("cargo") not in cargos:
            continue
        importe = num_es(m.group("imp").replace("'", ","))
        for nom in re.split(r", | y (?=Sr[a]?\. )", m.group("nombres")):
            nom = re.sub(r"^(Sra?\.|D\.|D[ñn]a\.)\s+", "", nom.strip())
            out.append(nuevo_registro("Calvià", "baleares", nom, cargos[m.group("cargo")], importe,
                                      f"retribución bruta anual del cargo en dedicación exclusiva ({m.group('pagas')})", periodo, url,
                                      "Ajuntament de Calvià: acuerdo plenario de retribuciones (BOIB)", verif))
    if len(out) < 8:
        raise RuntimeError(f"Calvià: solo {len(out)} concejales (¿cambió el acuerdo?)")
    return out


@_fuente("telde")
def actualizar_telde():
    """Ayuntamiento de Telde > Hacienda > Intervención > Retribuciones Cargos Electos, altos cargos y personal directivo (información del año indicado en la
    página). Tabla HTML: nombre (los tenientes de alcalde con su ordinal) | concejalía / grupo | retribución mensual bruta | retribución anual bruta (x14).
    Se guarda la ANUAL. La nota de la propia página dice quién tiene dedicación parcial (el resto, exclusiva). Se excluye el alcalde (fila sin importe mensual)."""
    from bs4 import BeautifulSoup
    url = "https://www.telde.es/areas/hacienda/intervencion/retribuciones-cargos-electos/"
    r = descargar(url)
    texto = texto_html(r.text)
    m = re.search(r"Informaci[oó]n correspondiente al a[nñ]o (\d{4})", texto)
    periodo = f"año {m.group(1)}" if m else "vigente"
    parcial = {_norm(x) for x in re.findall(r"excepto (?:Don|Do[ñn]a) ([^,.]+?) que tiene dedicaci[oó]n parcial", texto)}
    out, grupo_opo = [], False
    tabla = BeautifulSoup(r.text, "html.parser").find("table")
    for tr in (tabla.find_all("tr") if tabla else []):
        c = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]
        if len(c) == 4 and c[0].upper().startswith("CONCEJALES/AS DE LA OPOSICI"):
            grupo_opo = True
            continue
        if len(c) != 4 or "euros" not in c[3] or "euros" not in c[2]:
            continue
        anual = num_es(c[3].replace("euros", ""))
        m_t = re.match(r"^(?P<ord>\d+º Teniente de [Aa]lcalde): (?P<nom>.+)$", c[0])
        nombre = m_t.group("nom") if m_t else c[0]
        cargo = (f"{m_t.group('ord')}; {c[1]}" if m_t else (f"Concejal de la oposición con dedicación exclusiva ({c[1]})" if grupo_opo else c[1]))
        dedic = "parcial" if _norm(nombre) in parcial else "exclusiva"
        out.append(nuevo_registro("Telde", "las_palmas", nombre, cargo, anual, f"retribución anual bruta (14 pagas; dedicación {dedic})", periodo, url,
                                  "Web del Ayuntamiento de Telde: retribuciones de cargos electos", texto))
    if len(out) < 12:
        raise RuntimeError(f"Telde: solo {len(out)} concejales (¿cambió la tabla?)")
    return out


@_fuente("salamanca")
def actualizar_salamanca():
    """Ayuntamiento de Salamanca > Transparencia > Transparencia activa y organización: PDF 'Retribuciones percibidas por los miembros de la Corporación
    municipal en el ejercicio <año>' (enlace 'Retribuciones percibidas'). Una línea por persona: APELLIDOS, NOMBRE[*] importe €; '*' = dedicaciones exclusivas /
    parciales. El PDF no da concejalía ni identifica al alcalde (figura como miembro de la Corporación): cargo = 'Miembro de la Corporación' (+ dedicación si lleva
    '*'). Se guarda el importe percibido tal cual, sin asumir qué conceptos incluye."""
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin
    pagina = "https://www.aytosalamanca.es/en/transparencia/transparencia-activa-y-organizacion"
    r = descargar(pagina, verify=False)
    cand = []
    for a in BeautifulSoup(r.text, "html.parser").find_all("a", href=True):
        m = re.search(r"retribuciones-percibidas-miembros-corporacion-(\d{4})", a["href"])
        if m:
            cand.append((m.group(1), urljoin(r.url, a["href"])))
    if not cand:
        raise RuntimeError("Salamanca: no se encontró el PDF de retribuciones percibidas por los miembros de la corporación")
    anio, url = max(cand)
    texto = texto_pdf(descargar(url, timeout=120, verify=False).content)
    out = []
    for x in (re.sub(r"\s+", " ", l).strip() for l in texto.split("\n")):
        m = re.match(r"^(?P<ap>[A-ZÁÉÍÓÚÑÜ' -]+), (?P<no>[A-ZÁÉÍÓÚÑÜ' -]+?)(?P<ast>\*)? (?P<imp>[\d.]+,\d{2}) €$", x)
        if not m:
            continue
        cargo = "Miembro de la Corporación" + (" (dedicación exclusiva o parcial)" if m.group("ast") else "")
        out.append(nuevo_registro("Salamanca", "salamanca", nombre_persona(m.group("ap"), m.group("no")), cargo, num_es(m.group("imp")),
                                  "importe percibido en el ejercicio, tal como lo publica el Ayuntamiento (el PDF no detalla conceptos)", f"año {anio}", url,
                                  "Portal de transparencia del Ayuntamiento de Salamanca", texto))
    if len(out) < 20:
        raise RuntimeError(f"Salamanca: solo {len(out)} miembros (¿cambió el PDF?)")
    return out


@_fuente("ciudad real")
def actualizar_ciudad_real():
    """Ayuntamiento de Ciudad Real > Transparencia > Retribuciones anuales de los miembros de la Corporación (PDF 'RETRIBUCIONES ANUALES MIEMBROS DE
    LA CORPORACIÓN 2.024', actualizado a 30/12/2024). Una línea por persona: unidad | grupo | nivel | nº empleado + NOMBRE (APELLIDOS NOMBRE, sin coma) |
    código + puesto | situación | S.BASE | prog. | P.EXTRA | C.EMP.SS (cotización de la empresa) | TOTAL RETRIB. Se guarda TOTAL RETRIB., y se comprueba
    que es S.BASE + P.EXTRA. El nombre se deja en el orden de la fuente ('Apellidos Nombre'): sin coma no se puede separar sin adivinar. Se excluye el alcalde."""
    url = "https://www.ciudadreal.es/documentos/transparencia/activa/7.-Retribuciones_Concejales_024.3.pdf"
    texto = texto_pdf(descargar(url, timeout=120).content)
    m = re.search(r"actualizado (\d{2}/\d{2}/\d{4})", texto)
    m_anio = re.search(r"CORPORACI[OÓ]N (\d)\.(\d{3})", texto)
    if not m_anio:
        raise RuntimeError("Ciudad Real: no se reconoce el año del PDF")
    anio = m_anio.group(1) + m_anio.group(2)
    periodo = f"año {anio}" + (f" (actualizado a {m.group(1)})" if m else "")
    re_fila = re.compile(r"^CONCEJALES A\d 0 (?:\d+)?(?P<nombre>[A-ZÁÉÍÓÚÑÜ' ]+?) \d{3}(?P<puesto>[A-ZÁÉÍÓÚ ]+?) Ocu (?P<base>[\d.]+,\d{2}) \d{4} "
                         r"(?P<extra>[\d.]+,\d{2}) (?P<ss>[\d.]+,\d{2}) (?P<total>[\d.]+,\d{2})$")
    out, incoherentes = [], 0
    for x in (re.sub(r"\s+", " ", l).strip() for l in texto.split("\n")):
        m = re_fila.match(x)
        if not m or m.group("puesto").strip().startswith("ALCALDE"):
            continue
        base, extra, total = num_es(m.group("base")), num_es(m.group("extra")), num_es(m.group("total"))
        if abs(base + extra - total) > 0.05:
            incoherentes += 1
            continue
        out.append(nuevo_registro("Ciudad Real", "ciudad_real", _titulo_nombre(m.group("nombre")), cargo_frase(m.group("puesto").strip()), total,
                                  "total de retribuciones anuales (sueldo base + pagas extra; sin la cotización de la empresa); nombre en el orden de la fuente (apellidos primero)",
                                  periodo, url, "Portal de transparencia del Ayuntamiento de Ciudad Real", texto))
    if incoherentes:
        print(f"  Ciudad Real: {incoherentes} filas con total != base + extra saltadas")
    if len(out) < 10:
        raise RuntimeError(f"Ciudad Real: solo {len(out)} concejales (¿cambió el PDF?)")
    return out


@_fuente("huesca")
def actualizar_huesca():
    """Ayuntamiento de Huesca > Recursos humanos > Retribuciones (2026, actual) > '2. Retribuciones alcalde y concejales/as con dedicación
    exclusiva y parcial': tabla NOMBRE | GRUPO | DEDICACIÓN | IMPORTE BRUTO ANUAL | RESOLUCIÓN ALCALDÍA (acuerdo BOP de 27/06/2023). La tabla no
    da concejalía: cargo = 'Concejal/a' + grupo. Se excluye la alcaldesa (cubierta aparte); el personal eventual de la 3.ª tabla no es concejal."""
    from bs4 import BeautifulSoup
    url = "https://www.huesca.es/ayuntamiento/organizacion-administrativa/empleado-publico/retribuciones"
    r = descargar(url)
    texto = texto_html(r.text)
    out = []
    for tabla in BeautifulSoup(r.text, "html.parser").find_all("table"):
        trs = tabla.find_all("tr")
        cab = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)).upper() for td in (trs[0].find_all(["td", "th"]) if trs else [])]
        if not (len(cab) >= 4 and "GRUPO" in cab[1] and "DEDICACI" in _norm(cab[2]).upper()):
            continue
        for tr in trs[1:]:
            c = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]
            if len(c) < 4 or not num_es(c[3]):
                continue
            nombre, grupo, dedic = c[0], c[1], c[2]
            if any("alcalde" in (a["href"] or "").lower() for a in tr.find_all("a", href=True)):
                continue                         # la resolución de la alcaldesa es 'BOP dedicacion exclusiva Alcaldesa.pdf' (cubierta aparte)
            out.append(nuevo_registro("Huesca", "huesca", nombre, f"Concejal/a ({grupo})", num_es(c[3]),
                                      f"importe bruto anual (dedicación {dedic.lower()})", "acuerdo BOP de 27 de junio de 2023 y resoluciones de Alcaldía",
                                      url, "Web del Ayuntamiento de Huesca: retribuciones", texto))
    if len(out) < 4:
        raise RuntimeError(f"Huesca: solo {len(out)} concejales (¿cambió la tabla?)")
    return out


@_fuente("las rozas de madrid")
def actualizar_las_rozas():
    """Ayuntamiento de Las Rozas de Madrid > Portal de Transparencia > 'Dedicación, retribución, indemnizaciones, compatibilidades y delegaciones
    de altos cargos'. El acuerdo fija la 'Retribución bruta anual' por cargo y persona (efectos 1/08/2023; la propia fuente añade que se
    incrementan según las Leyes de Presupuestos sin nuevo acuerdo). Cada fila de la página son 3 encabezados: cargo | nombre | importe. Los
    concejales con 'VARIABLE POR ASISTENCIAS' (sin importe fijo) se saltan. Se excluye el alcalde (cubierto aparte)."""
    from bs4 import BeautifulSoup
    url = "https://transparencia.lasrozas.es/institucional-organizativa-y-personal/dedicacion-retribucion-e-indemnizaciones-de-altos-cargos/"
    r = descargar(url)
    texto = texto_html(r.text)
    m = re.search(r"entrar[aá]n en vigor desde el d[ií]a (\d{1,2} de \w+ de \d{4})", texto)
    periodo = f"acuerdo con efectos desde el {m.group(1)}" if m else "acuerdo vigente"
    out, variable = [], 0
    for sec in BeautifulSoup(r.text, "html.parser").find_all("section"):
        hs = [re.sub(r"\s+", " ", h.get_text(" ", strip=True)) for h in sec.find_all("h6", class_="elementor-heading-title")]
        if len(hs) != 3 or not re.search(r"\d", hs[2] + "x") and "VARIABLE" not in hs[2].upper():
            continue
        cargo, nombre, imp = hs
        if "VARIABLE" in imp.upper():
            variable += 1
            continue
        if cargo.lower().startswith("alcalde"):
            continue
        importe = num_es(imp)
        if not importe:
            continue
        nombre = re.sub(r"^(D\.|Dª|D\.ª|Doña|Don)\s+", "", nombre)
        out.append(nuevo_registro("Las Rozas de Madrid", "madrid", nombre, cargo, importe, "retribución bruta anual fijada en el acuerdo (12 mensualidades)",
                                  periodo, url, "Portal de Transparencia del Ayuntamiento de Las Rozas de Madrid", texto))
    if variable:
        print(f"  Las Rozas: {variable} concejales 'variable por asistencias' saltados")
    if len(out) < 10:
        raise RuntimeError(f"Las Rozas: solo {len(out)} concejales (¿cambió la página?)")
    return out


@_fuente("almeria")
def actualizar_almeria():
    """Ayuntamiento de Almería > Transparencia > Retribuciones de los cargos electos: PDF 'Retribuciones y régimen de dedicación miembros
    Corporación <año>' (el más reciente enlazado). Una línea por persona: GRUPO | CARGO | APELLIDOS, NOMBRE | RÉGIMEN DE DEDICACIÓN |
    retribuciones íntegras mensuales | íntegras anuales. Se guarda la ANUAL. Se excluye la alcaldesa (cubierta aparte). El servidor de
    almeriaciudad.es sirve un certificado con la cadena incompleta: la descarga (solo lectura de un documento público) va sin verificar el certificado."""
    import urllib3
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin
    urllib3.disable_warnings()
    pagina = "https://almeriaciudad.es/transparencia-municipal/retribuciones-de-los-cargos-electos"
    r = descargar(pagina, verify=False)
    cand = []
    for a in BeautifulSoup(r.text, "html.parser").find_all("a", href=True):
        m = re.match(r"Retribuciones y r[eé]gimen de dedicaci[oó]n miembros Corporaci[oó]n (\d{4})$", a.get_text(" ", strip=True))
        if m:
            cand.append((m.group(1), urljoin(r.url, a["href"])))
    if not cand:
        raise RuntimeError("Almería: no se encontró el PDF de retribuciones y régimen de dedicación")
    anio, url = max(cand)
    texto = texto_pdf(descargar(url, timeout=120, verify=False).content)
    re_fila = re.compile(r"^(?P<g>PP|PSOE|VOX|PODEMOS|CS|[A-ZÁÉÍÓÚ-]{2,12}) (?P<cargo>ALCALDESA|ALCALDE|CONCEJAL|(?:\d.*?|DELEGAD[OA]|DLEGAD[OA]) ?(?:DE )?(?:ÁREA|AREA|ÁEA)|PORTAVOZ GRUPO POL+ÍTICO) "
                         r"(?P<nombre>[^,]+, .+?) (?P<reg>EXCLUSIVA|PARCIAL \d+ ?%)(?P<nota> \(Desde [\d/]+\))? (?P<men>[\d.]+,\d\d) (?P<anual>[\d.]+,\d\d)$")
    out = []
    for x in (re.sub(r"\s+", " ", l).strip() for l in texto.split("\n")):
        m = re_fila.match(x)
        if not m or m.group("cargo").startswith("ALCALD"):
            continue
        partes = [p.strip() for p in m.group("nombre").split(",")]
        ap, no = (" ".join(partes[:-1]), partes[-1]) if len(partes) >= 2 else ("", partes[0])
        reg = m.group("reg").lower().replace(" %", "%") + (m.group("nota") or "")
        out.append(nuevo_registro("Almería", "almeria", nombre_persona(ap, no), f'{cargo_frase(m.group("cargo"))} ({m.group("g")})',
                                  num_es(m.group("anual")), f"retribuciones íntegras anuales (dedicación {reg})", f"año {anio}", url,
                                  "Portal de transparencia del Ayuntamiento de Almería", texto))
    if len(out) < 15:
        raise RuntimeError(f"Almería: solo {len(out)} concejales (¿cambió el PDF?)")
    return out


@_fuente("mostoles")
def actualizar_mostoles():
    """Ayuntamiento de Móstoles > Corporación municipal > Remuneraciones > 'Remuneraciones de los miembros de la Corporación Municipal
    2023-2027' (acuerdo plenario 2/242 de 8/01/2026). Dos tablas HTML: GRUPO | CARGO | NOMBRE Y APELLIDOS | RETRIBUCIONES (importe en €).
    La página no indica el periodo del importe: se guarda tal cual, sin llamarlo anual. Se excluye el alcalde (cubierto aparte)."""
    from bs4 import BeautifulSoup
    url = "https://www.mostoles.es/es/ayuntamiento/organizacion-municipal-organos-gobierno-personal/corporacion-municipal/remuneraciones/remuneraciones-miembros-corporacion-municipal-2023-2027"
    try:
        r = descargar(url, intentos=1)
    except RuntimeError:
        url = url.replace("/es/", "/en/", 1)
        r = descargar(url)
    texto = texto_html(r.text)
    m = re.search(r"acuerdo ([\d/]+) de (\d{1,2} de \w+ de \d{4})", texto)
    periodo = f"acuerdo plenario {m.group(1)} de {m.group(2)}" if m else "vigente"
    out = []
    for tabla in BeautifulSoup(r.text, "html.parser").find_all("table"):
        for tr in tabla.find_all("tr"):
            c = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]
            if len(c) != 4 or c[0] == "GRUPO" or c[1].lower().startswith("alcalde"):
                continue
            out.append(nuevo_registro("Móstoles", "madrid", c[2], f"{c[1]} ({c[0]})", num_es(c[3]),
                                      "retribución publicada por el Ayuntamiento (la tabla no indica el periodo)", periodo, r.url,
                                      "Web del Ayuntamiento de Móstoles: remuneraciones de la Corporación 2023-2027", texto))
    if len(out) < 20:
        raise RuntimeError(f"Móstoles: solo {len(out)} concejales (¿cambió la tabla?)")
    return out


@_fuente("vitoria-gasteiz")
def actualizar_vitoria():
    """Ayuntamiento de Vitoria-Gasteiz > Portal de transparencia > 'Retribuciones de los altos cargos del Ayuntamiento': XLS 'Salario mensual
    según puesto y dedicación' (personal eventual, cargos electos y órganos directivos; p. ej. 'Documento actualizado a 19/03/2025'). Columnas:
    nombre | código de puesto | denominación | ID | SALARIO MENSUAL | % dedicación. Se toman solo los puestos de cargo electo (tenientes de alcalde
    2102, concejales delegados de área 2104, con delegación especial 2106 y portavoces 2108); alcaldesa, eventuales y directivos se excluyen.
    El importe es MENSUAL tal como lo publica la fuente (no se anualiza)."""
    import xlrd
    from urllib.parse import urljoin
    from bs4 import BeautifulSoup
    pagina = "https://www.vitoria-gasteiz.org/wb021/was/contenidoAction.do?idioma=en&uid=u7c6618d7_148a69ca5e2__7f0e"
    r = descargar(pagina)
    url = None
    for a in BeautifulSoup(r.text, "html.parser").find_all("a", href=True):
        if _norm(a.get_text(" ", strip=True)).startswith("salario mensual segun puesto"):
            url = urljoin(r.url, a["href"])
            break
    if not url:
        raise RuntimeError("Vitoria: no se encontró el XLS de salario mensual según puesto y dedicación")
    hoja = xlrd.open_workbook(file_contents=descargar(url, timeout=120).content).sheet_by_index(0)
    m = re.search(r"actualizado a (\d{2}/\d{2}/\d{4})", " ".join(str(c) for c in hoja.row_values(0)), re.I)
    periodo = f"salario mensual vigente (documento actualizado a {m.group(1)})" if m else "salario mensual vigente"
    filas = [hoja.row_values(i) for i in range(2, hoja.nrows)]
    texto = "\n".join(f"{f[0]} {f[2]} {f[4]} {f[5]}" for f in filas)
    out = []
    for f in filas:
        if int(f[1] or 0) not in (2102, 2104, 2106, 2108):
            continue
        cargo = re.search(r"(TENIENTE.*|CONCEJAL/A.*)$", str(f[2]).strip())
        if not cargo or not isinstance(f[4], float):
            continue
        out.append(nuevo_registro("Vitoria-Gasteiz", "pais_vasco", _titulo_nombre(str(f[0])), cargo_frase(cargo.group(1)), f[4],
                                  f"salario mensual (dedicación {round(f[5] * 100)} %), no anualizado", periodo, url,
                                  "Portal de transparencia del Ayuntamiento de Vitoria-Gasteiz", texto))
    if len(out) < 15:
        raise RuntimeError(f"Vitoria: solo {len(out)} concejales (¿cambió el XLS?)")
    return out


@_fuente("castellon de la plana")
def actualizar_castellon():
    """Ayuntamiento de Castelló de la Plana > Transparencia > 'Las retribuciones percibidas anualmente por altos cargos...': PDF
    'Retribuciones_Cargos_Electos_<año>' (el del año más reciente enlazado). Una tabla por grupo municipal: Apellidos y Nombre | Cargo |
    % dedicación | Salario/Retención/Líquido por mes | Total anual acumulado. Solo se toma la fila 'Salario' (bruto) y su total anual.
    Las personas con algún mes a 0,00 (año parcial) se saltan: su total no es comparable. La alcaldesa se excluye (cubierta aparte)."""
    from urllib.parse import urljoin
    pagina = "https://www.castello.es/es/w/retribuciones"
    r = descargar(pagina)
    enlaces = re.findall(r'href="([^"]*Retribuciones_Cargos_Electos_(\d{4})\.pdf[^"]*)"', r.text)
    if not enlaces:
        raise RuntimeError("Castellón: no se encontró el PDF de retribuciones de cargos electos")
    href, anio = max(enlaces, key=lambda x: x[1])
    url = urljoin(r.url, href.replace("&amp;", "&"))
    texto = texto_pdf(descargar(url, timeout=120).content)
    re_fila = re.compile(r"^(?P<ap>[^,]+), (?P<no>.+?) (?P<cargo>Alcaldesa|Alcalde|Concejal|Concejala) (?P<pct>\d{1,3}) % Salario (?P<resto>[\d., ]+)$")
    out, grupo, parciales = [], "", 0
    for x in (re.sub(r"\s+", " ", l).strip() for l in texto.split("\n")):
        g = re.match(r"^Retribuciones Grupo (.+)$", x)
        if g:
            grupo = g.group(1).strip().title()
            continue
        m = re_fila.match(x)
        if not m:
            continue
        cifras = m.group("resto").split()
        if len(cifras) != 13 or m.group("cargo").startswith("Alcalde"):
            continue
        if any(c == "0,00" for c in cifras[:12]):
            parciales += 1
            continue
        nombre = f'{m.group("no")} {m.group("ap")}'
        cargo = f'{m.group("cargo")} (grupo {grupo}), dedicación {m.group("pct")} %'
        out.append(nuevo_registro("Castellón de la Plana", "castellon", nombre, cargo, num_es(cifras[12]),
                                  "total anual acumulado bruto (fila «Salario»), suma de los 12 meses", f"año {anio}", url,
                                  "Portal de Transparencia del Ayuntamiento de Castelló de la Plana", texto))
    if parciales:
        print(f"  Castellón: {parciales} concejales con meses a 0,00 (año parcial) saltados")
    if len(out) < 15:
        raise RuntimeError(f"Castellón: solo {len(out)} concejales (¿cambió el PDF?)")
    return out


@_fuente("badajoz")
def actualizar_badajoz():
    """Portal de Transparencia del Ayuntamiento de Badajoz > Excel 'Retribuciones alcalde, concejales y personal de
    confianza <año>': hoja 'Alcalde y Concejales' con APELLIDOS Y NOMBRE (con coma) | PUESTO | Salario bruto mensual
    (14 pagas) | Salario Anual Bruto. Se guarda el Salario Anual Bruto; se excluye el alcalde."""
    import openpyxl
    pagina = "https://www.aytobadajoz.es/es/ayto/participacion-ciudadana/58345/transparencia"
    r = descargar(pagina)
    m = re.search(r'href="([^"]*retribuciones_alcalde_concejales_y_personal_de_confianza_(\d{4})\.xlsx)"', r.text)
    if not m:
        raise RuntimeError("Badajoz: no se encontró el Excel de retribuciones")
    from urllib.parse import urljoin
    url, anio = urljoin(r.url, m.group(1)), m.group(2)
    wb = openpyxl.load_workbook(io.BytesIO(descargar(url).content), data_only=True)
    filas = [list(f) for f in wb["Alcalde y Concejales"].iter_rows(values_only=True)]
    # las celdas de Excel a veces guardan un float con ruido de coma flotante (65928.09999999999 en vez de
    # 65928.10): si el texto de verificación se construye con str(c) tal cual, ese ruido nunca coincide con
    # ninguna de las formas "65928,10" que genera _formas_importe -- se redondea a 2 decimales para el texto.
    texto = "\n".join(" ".join("" if c is None else (f"{c:.2f}" if isinstance(c, float) else str(c)) for c in f)
                      for f in filas)
    out = []
    for f in filas:
        if not (f and f[0] and f[1] and isinstance(f[3], (int, float))) or str(f[0]).upper().startswith("APELLIDOS"):
            continue
        if "," not in str(f[0]):
            continue
        apellidos, nombre_pila = str(f[0]).split(",", 1)
        nombre = nombre_persona(apellidos, nombre_pila)
        cargo = cargo_frase(str(f[1]))
        if cargo.lower().startswith("alcalde"):
            continue
        out.append(nuevo_registro("Badajoz", "badajoz", nombre, cargo, round(float(f[3]), 2),
                                  "salario anual bruto (14 pagas)", f"año {anio}", url,
                                  "Portal de Transparencia del Ayuntamiento de Badajoz", texto))
    if len(out) < 10:
        raise RuntimeError(f"Badajoz: solo {len(out)} concejales (¿cambió el Excel?)")
    return out


@_fuente("lorca")
def actualizar_lorca():
    """Ayuntamiento de Lorca (Murcia) > transparencia.lorca.es > Corporación municipal > PDF "Retribuciones
    percibidas por los miembros de la Corporación Local de Lorca <año>": un bloque por persona, SIN tabla real
    -- la 1.ª línea del bloque es el final del cargo + DEDICACIÓN (EXCLUSIVA/PARCIAL, a veces con asteriscos de
    nota al pie) + RÉGIMEN DE ASISTENCIAS (SI/NO) + el importe; las líneas siguientes son más cargo (a veces
    ninguna); la ÚLTIMA línea del bloque, justo antes del siguiente bloque, es el nombre. Los concejales que
    solo cobran por asistencia (sin dedicación fija, "... SI" sin importe al final) se saltan -- no tienen un
    importe anual que publicar. Alcalde excluido."""
    pagina = "http://www.transparencia.lorca.es/corporacion-municipal"
    r = descargar(pagina)
    m = re.search(r'href="([^"]*RETRIBUCIONES_CORPORACION_LOCAL[^"]*\.pdf)"', r.text, re.I)
    if not m:
        raise RuntimeError("Lorca: no se encontró el PDF de retribuciones")
    from urllib.parse import urljoin
    url = urljoin(r.url, m.group(1).replace(" ", "%20").replace("&amp;", "&"))
    contenido = descargar(url, timeout=90).content
    texto = texto_pdf(contenido)
    m_anio = re.search(r"CORPORACI[ÓO]N LOCAL DE LORCA (\d{4})", texto, re.I)
    anio = m_anio.group(1) if m_anio else "?"

    def es_ruido(l):
        """Cabeceras/pies de página de la tabla: aparecen partidas en trozos distintos según cómo caiga el
        salto de página (a veces "GRUPO MUNICIPAL X" en una línea y el resto de la cabecera de columnas en
        otra bien distinta, p. ej. "VERDE ÓRGANOS ANUALES" o "ORGANOS ANUALES" sueltos, sin acento ni el resto
        de la frase) -- bug real encontrado: un filtro que solo miraba el PREFIJO de la línea dejaba pasar esas
        variantes como si fueran el nombre de la persona, y arrastraba mal el bloque siguiente. Por eso se
        busca cualquiera de estas palabras COMO SUBCADENA, en cualquier posición de la línea."""
        if not l or re.match(r"^\d+$", l):
            return True
        lu = l.upper()
        for palabra in ("GRUPO MUNICIPAL", "RELACIÓN DE", "RETRIBUCIONES PERCIBIDAS", "COLEGIADOS",
                        "ÓRGANOS", "ORGANOS", "ANUALES", "DE LA CORPORACIÓN", "DEDICACIÓN", "RÉGIMEN DE",
                        "COMISIÓN INFORMATIVA O PLENO", "ACTUALIZADO A"):
            if palabra in lu:
                return True
        if re.match(r"^\d+\.-", l):
            return True
        return False

    RE_DATA = re.compile(r"^(?P<cargo>.*?)\**\s*(?P<dedicacion>EXCLUSIVA|PARCIAL)\s+(?P<asist>SI|NO)\s+(?P<importe>[\d.,]+)\s*$")
    RE_SIN_IMPORTE = re.compile(r"^.+\s(?:SI|NO)\s*$")   # "... SI" sin dedicación/importe: solo asistencias
    out, pendiente, continuacion, solo_asistencia = [], None, [], 0

    def cerrar():
        nonlocal pendiente, continuacion
        if pendiente and continuacion:
            nombre = continuacion[-1]
            cargo = re.sub(r"\s+", " ", (pendiente["cargo"] + " " + " ".join(continuacion[:-1])).strip(" ,"))
            if not cargo.lower().startswith("alcalde"):
                out.append(nuevo_registro("Lorca", "murcia", nombre, cargo_frase(cargo), num_es(pendiente["importe"]),
                                          f"retribución bruta anual (dedicación {pendiente['dedicacion'].lower()})",
                                          f"año {anio}", url,
                                          "Portal de Transparencia del Ayuntamiento de Lorca", texto))
        pendiente, continuacion = None, []

    for l in (x.strip() for x in texto.split("\n")):
        if es_ruido(l):
            continue
        m = RE_DATA.match(l)
        if m:
            cerrar()
            pendiente = m.groupdict()
            continue
        if RE_SIN_IMPORTE.match(l) and not any(c.isdigit() for c in l):
            cerrar()
            solo_asistencia += 1
            continue
        if pendiente is not None:
            continuacion.append(l)
    cerrar()
    if solo_asistencia:
        print(f"  Lorca: {solo_asistencia} concejales solo con régimen de asistencias (sin importe fijo) saltados")
    if len(out) < 10:
        raise RuntimeError(f"Lorca: solo {len(out)} concejales (¿cambió el PDF?)")
    return out


@_fuente("burgos")
def actualizar_burgos():
    """Ayuntamiento de Burgos > Corporación municipal > PDF "Retribuciones corporativos <año>": una tabla real
    (con líneas) por MES (12 páginas), columnas Nombre | Dedicación (DEDICACIÓN/ASISTENCIAS) | Bruto/Neto de
    cada una de 3 entidades (Ayuntamiento, Aguas de Burgos, Promueve Burgos) | Bruto/Neto TOTALES. El importe
    guardado es la SUMA de los "TOTALES BRUTO" mensuales de cada persona en el año (aritmética sobre cifras
    oficiales, no una estimación), igual que Madrid. La fuente NO etiqueta quién es el alcalde (a diferencia
    de Madrid): se excluye por nombre, a partir de quién ocupa la alcaldía (dato público, no deducido de esta
    tabla) -- si cambia de alcalde, esta exclusión habría que actualizarla a mano."""
    import pdfplumber
    from collections import defaultdict
    from difflib import SequenceMatcher
    from urllib.parse import urljoin
    ALCALDE_CONOCIDO = "DANIEL DE LA ROSA VILLAHOZ"   # alcalde de Burgos (PSOE) -- dato público, no viene marcado en la fuente
    pagina = "https://www.aytoburgos.es/corporacionmunicipal"
    r = descargar(pagina)
    m = re.search(r'href="(/documents/[^"]*[Rr]etribuciones[^"]*[Cc]orporativos[^"]*(\d{4})[^"]*\.pdf[^"]*)"', r.text)
    if not m:
        raise RuntimeError("Burgos: no se encontró el PDF de retribuciones de corporativos")
    url, anio = urljoin(r.url, m.group(1).replace("&amp;", "&")), m.group(2)
    contenido = descargar(url, timeout=120).content
    sumas, tipos, meses = defaultdict(float), {}, defaultdict(int)
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        texto = "\n".join((p.extract_text() or "") for p in pdf.pages)
        for pagina_pdf in pdf.pages:
            t = pagina_pdf.extract_table()
            if not t:
                continue
            for fila in t:
                if not fila or not fila[0] or fila[0].upper().startswith("NOMBRE"):
                    continue
                nombre = re.sub(r"\s+", " ", fila[0]).strip()
                if len(fila) <= 8:
                    continue
                total_bruto = num_es(fila[8])
                if total_bruto:
                    sumas[nombre] += total_bruto
                    meses[nombre] += 1
                if (fila[1] or "").strip():
                    tipos[nombre] = fila[1].strip()
    # bug real de origen encontrado (2026-09-30): algún mes concreto tiene una errata de tecleo en el nombre
    # ("BORJ A SUAREZ PEDROSA" en vez de "BORJA...", "C�SAR BARRIADA HEBOSA" en vez de "...HERBOSA") -- eso
    # abre una clave nueva en el diccionario y esa persona queda partida en dos entradas, una de ellas con un
    # importe mensual sospechosamente bajo (1-2 meses en vez de 12). Se fusionan pares de nombres muy
    # parecidos (SequenceMatcher > 0.82) quedándose con la ortografía que aparece en más meses; nunca se
    # inventa una ortografía nueva, solo se suman los importes de la que menos meses tiene a la que más.
    nombres = sorted(sumas, key=lambda n: -meses[n])
    fusionados = set()
    for i, a in enumerate(nombres):
        if a in fusionados:
            continue
        for b in nombres[i + 1:]:
            if b in fusionados:
                continue
            if SequenceMatcher(None, _norm(a), _norm(b)).ratio() > 0.82:
                sumas[a] += sumas.pop(b)
                meses[a] += meses.pop(b)
                fusionados.add(b)
                print(f"  Burgos: '{b}' fusionado con '{a}' (misma persona, errata de un mes)")
    if len(sumas) < 20:
        raise RuntimeError(f"Burgos: solo {len(sumas)} personas (¿cambió el documento?)")
    out = []
    for nombre, importe in sumas.items():
        if nombre.upper() == ALCALDE_CONOCIDO or importe <= 0:
            continue
        cargo = ("Concejal con dedicación" if _norm(tipos.get(nombre, "")).startswith("dedicaci")
                 else "Concejal (régimen de asistencias)")
        out.append(nuevo_registro("Burgos", "burgos", _titulo_nombre(nombre), cargo, round(importe, 2),
                                  "suma de los importes brutos mensuales (Ayuntamiento + Aguas de Burgos + "
                                  f"Promueve Burgos) de {anio}", f"año {anio}", url,
                                  "Ayuntamiento de Burgos (Retribuciones corporativos)", texto,
                                  omitir_verificacion=True))
    return out


@_fuente("teruel")
def actualizar_teruel():
    """Ayuntamiento de Teruel > Portal de Transparencia > "Retribuciones de los miembros de la Corporación":
    tabla HTML real (TablePress) con NOMBRE Y APELLIDOS | GRUPO POLÍTICO | TIPO DE DEDICACIÓN | IMPORTE BRUTO
    ANUAL | Decreto de Alcaldía. La alcaldesa no aparece en esta tabla (su retribución se publica aparte, no
    en esta página) -- no hace falta excluirla a mano."""
    from bs4 import BeautifulSoup
    url = "https://www.teruel.es/portal-de-transparencia/retribuciones-de-los-miembros-de-la-corporacion/"
    r = descargar(url)
    texto = texto_html(r.text)
    soup = BeautifulSoup(r.text, "html.parser")
    tabla = soup.find("table", id="tablepress-24")
    if not tabla:
        raise RuntimeError("Teruel: no se encontró la tabla de retribuciones (¿cambió el id de TablePress?)")
    out = []
    for fila in tabla.find("tbody").find_all("tr"):
        celdas = [c.get_text(" ", strip=True) for c in fila.find_all("td")]
        if len(celdas) < 4:
            continue
        nombre, grupo, dedicacion, importe_txt = celdas[0], celdas[1], celdas[2], celdas[3]
        importe = num_es(importe_txt)
        if not importe:
            continue
        cargo = f"Concejal ({dedicacion}, grupo {grupo})" if grupo else f"Concejal ({dedicacion})"
        out.append(nuevo_registro("Teruel", "teruel", nombre, cargo, importe,
                                  "importe bruto anual según la propia tabla de la fuente", "vigente", url,
                                  "Portal de Transparencia del Ayuntamiento de Teruel", texto))
    if len(out) < 5:
        raise RuntimeError(f"Teruel: solo {len(out)} concejales (¿cambió la tabla?)")
    return out


# ── main ────────────────────────────────────────────────────────────────────────────────────────────────────
def _leer():
    if not os.path.exists(OUT_FILE):
        return []
    for intento in range(5):                       # otra ejecución puede estar reemplazando el fichero en este instante
        try:
            with open(OUT_FILE, encoding="utf-8") as f:
                return json.load(f).get("registros", [])
        except (json.JSONDecodeError, PermissionError):
            time.sleep(0.5 * (intento + 1))
    raise RuntimeError("no se pudo leer sueldos_concejales.json")


def _escribir(registros):
    """Escritura atómica (fichero temporal + os.replace): nadie lee nunca un JSON a medias."""
    registros = sorted(registros, key=lambda r: (r["provincia"], r["municipio"], -r["importe"], r["nombre"]))
    tmp = f"{OUT_FILE}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"generado": time.strftime("%Y-%m-%d"),
                   "descripcion": "Sueldos de concejales publicados con nombre por fuentes oficiales de cada ayuntamiento "
                                  "(ver SUELDOS_CONCEJALES_LOG.md). Registro: municipio, provincia, nombre, cargo, importe, base, "
                                  "periodo, fuente_url, fuente_nombre.",
                   "registros": registros}, f, ensure_ascii=False, indent=1)
    for intento in range(10):
        try:
            os.replace(tmp, OUT_FILE)
            return
        except PermissionError:
            time.sleep(0.3)
    raise RuntimeError("no se pudo reemplazar sueldos_concejales.json")


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
    for nombre in pedidas:
        antes = [r for r in previos if _clave_fuente(r) == nombre]
        try:
            nuevos = _FUENTES[nombre]()
        except Exception as e:
            print(f"  !! {nombre}: FALLÓ ({type(e).__name__}: {e}); se conservan las {len(antes)} filas anteriores.", flush=True)
            continue
        if antes and not forzar and len(nuevos) < 0.9 * len(antes):
            print(f"  !! {nombre}: devolvió {len(nuevos)} filas frente a las {len(antes)} que ya había (< 90 %); se conservan las anteriores.", flush=True)
            continue
        nuevos, alcaldes = _sin_alcalde(nuevos)
        # Se guarda YA, tras cada municipio, RELEYENDO antes el fichero: si el proceso se corta no se pierde lo hecho, y varias
        # ejecuciones simultáneas (municipios distintos) no se pisan entre sí.
        _escribir([r for r in _leer() if _clave_fuente(r) != nombre] + nuevos)
        print(f"  {nombre}: {len(nuevos)} concejales" + (f" (excluido el alcalde, cubierto aparte: {alcaldes})" if alcaldes else ""), flush=True)
    print(f"\nHecho: {len(_leer())} registros en {OUT_FILE}", flush=True)


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
        ruido = _PARTICULAS | {"i"}
        alc = [x for x in _norm(((info or {}).get("alcalde") or {}).get("nombre", "")).replace(",", " ").split() if x not in ruido]
        toks = [x for x in _norm(r["nombre"]).replace(",", " ").split() if x not in ruido]
        if alc and set(alc) == set(toks):
            quitados.append(r["nombre"])
        else:
            resto.append(r)
    return resto, quitados


def _clave_fuente(r):
    """Clave del conector que generó el registro: el municipio normalizado (sin tildes, minúsculas) = clave de _FUENTES."""
    return _norm(r["municipio"])


if __name__ == "__main__":
    main()
