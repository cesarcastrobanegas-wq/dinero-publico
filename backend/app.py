"""
Contratos Públicos - Murcia
Fuente: Plataforma de Contratación del Sector Público (datos oficiales CODICE/Atom)
"""

import gzip as _gzip
import json, os, re, html, io, zipfile, threading, uuid, time
from datetime import datetime
from urllib.parse import parse_qs, quote_plus, urlparse
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from concurrent.futures import ThreadPoolExecutor, as_completed

# BORM search endpoint (POST, JSON)
BORM_BUSCAR_URL = "https://www.borm.es/services/buscador"
BORM_TXT_URL    = "https://www.borm.es/services/anuncio/{id}/txt"
BORM_PDF_URL    = "https://www.borm.es/services/anuncio/{id}/pdf"

import requests
from bs4 import BeautifulSoup

# ─── CONFIGURACIÓN ───────────────────────────────────────────────────────────

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_FILE  = os.path.join(BASE_DIR, "datos.json")
CACHE_DIR  = os.path.join(BASE_DIR, "place_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "es-ES,es;q=0.9",
}

PLACE_ZIP_BASE = (
    "https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_643/"
    "licitacionesPerfilesContratanteCompleto3_{anomes}.zip"
)
PLACE_FEED_LIVE = (
    "https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_643/"
    "licitacionesPerfilesContratanteCompleto3.atom"
)

MUNICIPIOS_MURCIA = [
    "Abanilla","Abarán","Águilas","Albudeite","Alcantarilla","Los Alcázares",
    "Aledo","Alguazas","Alhama de Murcia","Archena","Beniel","Blanca",
    "Bullas","Calasparra","Campos del Río","Caravaca de la Cruz",
    "Cartagena","Cehegín","Ceutí","Cieza","Fortuna",
    "Fuente Álamo de Murcia","Jumilla","Librilla","Lorca","Lorquí",
    "Mazarrón","Molina de Segura","Moratalla","Mula","Murcia","Ojós",
    "Pliego","Puerto Lumbreras","Ricote","San Javier",
    "San Pedro del Pinatar","Santomera","Torre Pacheco",
    "Las Torres de Cotillas","Totana","Ulea","La Unión",
    "Villanueva del Río Segura","Yecla",
]

session = requests.Session()
session.headers.update(HEADERS)
adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=0)
session.mount("http://", adapter)
session.mount("https://", adapter)

_datos_lock = threading.Lock()
_datos_memoria: list = []    # datos.json cargado en RAM al arrancar
_jobs: dict = {}
_jobs_lock = threading.Lock()
_enriqueciendo_lock = threading.Lock()  # evita lanzar dos hilos de enriquecimiento a la vez

PAGE_SIZE = 50               # contratos máximos por página

# ─── CACHÉ DE RESULTADOS ──────────────────────────────────────────────────────
_result_cache: dict = {}   # normalizar(municipio) → {"ts": float, "resultado": dict}
_cache_lock   = threading.Lock()
RESULT_CACHE_TTL = 6 * 3600   # 6 horas

# ─── CACHÉ DE DIRECTIVOS (persistente) ───────────────────────────────────────
DIRECTOR_CACHE_FILE = os.path.join(BASE_DIR, "director_cache.json")
_dir_cache: dict = {}          # clave → {"nombre": str, "cargo": str, "ts": float}
_dir_cache_lock = threading.Lock()
DIR_CACHE_POS_TTL = 90 * 24 * 3600   # 90 días para resultados encontrados
DIR_CACHE_NEG_TTL =  7 * 24 * 3600   # 7 días para "no encontrado"

def _dir_cache_key(empresa, nif=""):
    return nif.upper().strip() if nif else normalizar(empresa)

def _dir_cache_load():
    global _dir_cache
    try:
        with open(DIRECTOR_CACHE_FILE, encoding="utf-8") as f:
            _dir_cache = json.load(f)
    except Exception:
        _dir_cache = {}

def _dir_cache_save():
    try:
        with open(DIRECTOR_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_dir_cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _dir_cache_get(empresa, nif=""):
    """Devuelve (nombre, cargo) si hay hit válido; (None, None) si hay que buscar."""
    key = _dir_cache_key(empresa, nif)
    with _dir_cache_lock:
        entry = _dir_cache.get(key)
    if not entry:
        return None, None
    ttl = DIR_CACHE_POS_TTL if entry.get("nombre") else DIR_CACHE_NEG_TTL
    if time.time() - entry.get("ts", 0) > ttl:
        return None, None
    return entry.get("nombre", ""), entry.get("cargo", "")

def _dir_cache_set(empresa, nif, nombre, cargo):
    key = _dir_cache_key(empresa, nif)
    with _dir_cache_lock:
        _dir_cache[key] = {"nombre": nombre, "cargo": cargo, "ts": time.time()}
        _dir_cache_save()

# ─── UTILIDADES ──────────────────────────────────────────────────────────────

# ─── PERFILES PLACE POR MUNICIPIO ────────────────────────────────────────────
# ID numérico en la Plataforma de Contratación del Sector Público (PLACE).
# URL: https://contrataciondelsectorpublico.gob.es/web/guest/perfil-del-contratante/-/entity/id/{ID}
MUNICIPIOS_PLACE_IDS = {
    "Murcia":                    "4127",
    "Cartagena":                 "3769",
    "Lorca":                     "3946",
    "Molina de Segura":          "4056",
    "Alcantarilla":              "3600",
    "Yecla":                     "4369",
    "Mazarrón":                  "4024",
    "Jumilla":                   "3908",
    "Águilas":                   "3583",
    "Torre Pacheco":             "4277",
    "San Javier":                "4195",
    "Totana":                    "4283",
    "Alhama de Murcia":          "3620",
    "Cieza":                     "3802",
    "Caravaca de la Cruz":       "3757",
    "Archena":                   "3660",
    "Cehegín":                   "3787",
    "Fuente Álamo de Murcia":    "3875",
    "San Pedro del Pinatar":     "4199",
    "Las Torres de Cotillas":    "4284",
    "Calasparra":                "3740",
    "Abarán":                    "3561",
    "Beniel":                    "3708",
    "Fortuna":                   "3868",
    "Blanca":                    "3718",
    "Mula":                      "4082",
    "Ceutí":                     "3799",
    "Lorquí":                    "3949",
    "Alguazas":                  "3617",
    "Puerto Lumbreras":          "4170",
    "Moratalla":                 "4069",
    "La Unión":                  "4299",
    "Santomera":                 "4220",
    "Bullas":                    "3731",
    "Abanilla":                  "3558",
    "Los Alcázares":             "3602",
    "Albudeite":                 "3597",
    "Aledo":                     "3607",
    "Campos del Río":            "3748",
    "Librilla":                  "3933",
    "Ojós":                      "4121",
    "Pliego":                    "4150",
    "Ricote":                    "4183",
    "Ulea":                      "4292",
    "Villanueva del Río Segura": "4336",
}

def place_profile_url(municipio):
    pid = MUNICIPIOS_PLACE_IDS.get(municipio)
    if pid:
        return f"https://contrataciondelsectorpublico.gob.es/web/guest/perfil-del-contratante/-/entity/id/{pid}"
    from urllib.parse import quote_plus as _qp
    return (f"https://contrataciondelsectorpublico.gob.es/web/guest/perfil-del-contratante"
            f"?buscador={_qp('Ayuntamiento de ' + municipio)}")


def normalizar(s):
    s = (s or "").lower().strip()
    for a, b in {"á":"a","é":"e","í":"i","ó":"o","ú":"u","ü":"u","ñ":"n"}.items():
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s)

def esc(s):
    return html.escape(str(s or ""), quote=True)

def municipio_valido(txt):
    buscado = normalizar(txt)
    for m in MUNICIPIOS_MURCIA:
        if normalizar(m) == buscado:
            return m
    return None

def fmt_eur(valor_str):
    try:
        n = float(str(valor_str).replace(",", "."))
        return f"{n:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(valor_str)


# ─── PARSEO REGEX SOBRE ATOM/CODICE RAW ──────────────────────────────────────

def _re_tag(tag, text, default=""):
    """Devuelve el texto del primer tag (con o sin namespace prefix)."""
    m = re.search(
        rf'<(?:[A-Za-z0-9_-]+:)?{re.escape(tag)}(?:\s[^>]*)?>([^<]*)</(?:[A-Za-z0-9_-]+:)?{re.escape(tag)}>',
        text, re.IGNORECASE
    )
    return html.unescape(m.group(1).strip()) if m else default

def _re_tag_block(tag, text):
    """Devuelve el contenido interior del primer tag encontrado (puede tener hijos)."""
    m = re.search(
        rf'<(?:[A-Za-z0-9_-]+:)?{re.escape(tag)}(?:\s[^>]*)?>(.+?)</(?:[A-Za-z0-9_-]+:)?{re.escape(tag)}>',
        text, re.DOTALL | re.IGNORECASE
    )
    return m.group(1) if m else ""

def _parse_summary(summary_raw):
    """Extrae campos del texto del <summary> CODICE."""
    s = summary_raw
    # quitar CDATA si existe
    s = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', s, flags=re.DOTALL)
    # quitar tags HTML
    s = re.sub(r'<[^>]+>', ' ', s)
    s = html.unescape(s).strip()

    organo, importe_raw, estado, lid = "", "", "", ""

    m = re.search(r'[OÓo]rgano de [Cc]ontrataci[oó]n\s*:\s*([^;]+)', s)
    if m: organo = m.group(1).strip()

    m = re.search(r'Importe\s*:\s*([0-9][0-9\s.,]*)\s*EUR', s, re.I)
    if m: importe_raw = m.group(1).replace(" ", "").strip()

    m = re.search(r'Estado\s*:\s*([A-Z]{2,4})', s, re.I)
    if m: estado = m.group(1).upper()

    m = re.search(r'Id\s+licitaci[oó]n\s*:\s*([^;]+)', s, re.I)
    if m: lid = m.group(1).strip()

    return organo, importe_raw, estado, lid


_SUFIJOS_EMPRESA = re.compile(
    r'\b(s\.?l\.?u?\.?|s\.?a\.?u?\.?|s\.?c\.?|s\.?l\.?p\.?|s\.?coop\.?|s\.?a\.?)\s*$', re.I
)

def _entry_to_contrato(entry_xml):
    """Convierte el XML crudo de un <entry> a dict de contrato. Retorna None si no relevante."""

    # ── estado primero (salida rápida) ────────────────────────────────────────
    estado = ""
    m = re.search(r'ContractFolderStatusCode[^>]*>\s*([A-Z]{2,4})\s*<', entry_xml, re.I)
    if m:
        estado = m.group(1).upper()

    organo, importe_raw, licitacion_id = "", "", ""

    # ── summary → organo, importe, estado (si no lo tenemos aún), licitacion_id
    m = re.search(
        r'<(?:[A-Za-z0-9_-]+:)?summary(?:\s[^>]*)?>(.+?)</(?:[A-Za-z0-9_-]+:)?summary>',
        entry_xml, re.DOTALL | re.I
    )
    if m:
        organo, importe_raw, estado_sum, licitacion_id = _parse_summary(m.group(1))
        if not estado:
            estado = estado_sum

    if estado not in ("ADJ", "RES", "FOR"):
        return None

    # ── título ───────────────────────────────────────────────────────────────
    m = re.search(r'<(?:[A-Za-z0-9_-]+:)?title(?:\s[^>]*)?>([^<]*)</(?:[A-Za-z0-9_-]+:)?title>',
                  entry_xml, re.I)
    titulo = html.unescape(m.group(1).strip()) if m else ""

    # ── URL ──────────────────────────────────────────────────────────────────
    m = re.search(r'<link\b[^>]+href=["\']([^"\']+)["\']', entry_xml, re.I)
    url = m.group(1) if m else ""

    # ── organo fallback ───────────────────────────────────────────────────────
    if not organo:
        lcp = _re_tag_block("LocatedContractingParty", entry_xml)
        if lcp:
            party = _re_tag_block("Party", lcp)
            if party:
                pn = _re_tag_block("PartyName", party)
                organo = _re_tag("Name", pn) if pn else _re_tag("Name", party)

    # ── importe fallback ──────────────────────────────────────────────────────
    if not importe_raw:
        for tag in ("TaxExclusiveAmount", "TotalAmount", "PayableAmount",
                    "EstimatedOverallContractAmount", "TaxInclusiveAmount"):
            m = re.search(rf'<(?:[A-Za-z0-9_-]+:)?{re.escape(tag)}[^>]*>([0-9][0-9.,]+)<',
                          entry_xml, re.I)
            if m:
                importe_raw = m.group(1)
                break

    importe = fmt_eur(importe_raw) if importe_raw else ""

    # ── empresa + NIF (dentro de WinningParty / WinnerParty) ─────────────────
    empresa, nif = "", ""
    for tr_m in re.finditer(
        r'<(?:[A-Za-z0-9_-]+:)?TenderResult(?:\s[^>]*)?>(.+?)</(?:[A-Za-z0-9_-]+:)?TenderResult>',
        entry_xml, re.DOTALL | re.I
    ):
        tr_block = tr_m.group(1)
        for wp_tag in ("WinningParty", "WinnerParty"):
            wp_m = re.search(
                rf'<(?:[A-Za-z0-9_-]+:)?{wp_tag}(?:\s[^>]*)?>(.+?)</(?:[A-Za-z0-9_-]+:)?{wp_tag}>',
                tr_block, re.DOTALL | re.I
            )
            if not wp_m:
                continue
            wp_block = wp_m.group(1)
            # NIF
            nif_m = re.search(
                r'schemeName=["\']NIF["\'][^>]*>([A-Za-z][0-9]{7}[A-Za-z0-9])<', wp_block, re.I
            )
            if not nif_m:
                nif_m = re.search(r'<[^>]*ID[^>]*>([A-Za-z][0-9]{7}[A-Za-z0-9])<', wp_block, re.I)
            if nif_m:
                nif = nif_m.group(1).upper()
            # Nombre
            pn_m = re.search(
                r'<(?:[A-Za-z0-9_-]+:)?PartyName(?:\s[^>]*)?>(.+?)</(?:[A-Za-z0-9_-]+:)?PartyName>',
                wp_block, re.DOTALL | re.I
            )
            block = pn_m.group(1) if pn_m else wp_block
            name_m = re.search(
                r'<(?:[A-Za-z0-9_-]+:)?Name(?:\s[^>]*)?>([^<]+)</(?:[A-Za-z0-9_-]+:)?Name>',
                block, re.I
            )
            if name_m:
                empresa = html.unescape(name_m.group(1).strip())
                break
        if empresa:
            break

    # Fallback: cualquier Name en TenderResult que parezca empresa
    if not empresa:
        for tr_m in re.finditer(
            r'<(?:[A-Za-z0-9_-]+:)?TenderResult(?:\s[^>]*)?>(.+?)</(?:[A-Za-z0-9_-]+:)?TenderResult>',
            entry_xml, re.DOTALL | re.I
        ):
            for name_m in re.finditer(
                r'<(?:[A-Za-z0-9_-]+:)?Name(?:\s[^>]*)?>([^<]{3,80})</(?:[A-Za-z0-9_-]+:)?Name>',
                tr_m.group(1), re.I
            ):
                candidate = html.unescape(name_m.group(1).strip())
                if _SUFIJOS_EMPRESA.search(candidate) or len(candidate.split()) >= 2:
                    empresa = candidate
                    break
            if empresa:
                break

    return {
        "titulo":        titulo[:200],
        "organo":        organo,
        "empresa":       empresa or "No localizada",
        "nif":           nif,
        "importe":       importe or "No localizado",
        "importe_num":   float(importe_raw.replace(",", ".")) if importe_raw else 0.0,
        "estado":        estado,
        "licitacion_id": licitacion_id,
        "url":           url,
        "fuente":        "PLACE",
        "directivo":     "",
        "cargo":         "",
    }


_OPEN_ENTRY_B  = b'<entry>'
_CLOSE_ENTRY_B = b'</entry>'
_OPEN_LEN_B    = len(_OPEN_ENTRY_B)

# Códigos de estado como bytes literales (bytes.find es 12× más rápido que regex en bytes)
_STATUS_CODES_B = (b'>ADJ<', b'>RES<', b'>FOR<',
                   b'Estado: ADJ', b'Estado: RES', b'Estado: FOR',
                   b'Estado:ADJ',  b'Estado:RES',  b'Estado:FOR')


def _entries_con_estado_bytes(raw_bytes, muni_b_variants):
    """
    Escanea el fichero atom en bytes usando bytes.find (sin regex, ~12× más rápido).
    Devuelve solo las entries con estado ADJ/RES/FOR que mencionan el municipio.
    """
    import bisect

    # Índice de inicios de <entry>
    starts, pos = [], 0
    while True:
        p = raw_bytes.find(_OPEN_ENTRY_B, pos)
        if p == -1: break
        starts.append(p + _OPEN_LEN_B)
        pos = p + 1
    if not starts:
        return []

    # Cierre de cada entry
    ends = []
    for s in starts:
        e = raw_bytes.find(_CLOSE_ENTRY_B, s)
        ends.append(e if e != -1 else len(raw_bytes))

    # Posiciones de códigos de estado (bytes.find × 9 patrones → O(n) total)
    status_positions = []
    for code in _STATUS_CODES_B:
        pos = 0
        while True:
            p = raw_bytes.find(code, pos)
            if p == -1: break
            status_positions.append(p)
            pos = p + 1
    if not status_positions:
        return []

    # Para cada posición de estado, localizar la entry que la contiene
    seen, results = set(), []
    for mpos in status_positions:
        idx = bisect.bisect_right(starts, mpos) - 1
        if idx < 0 or idx in seen: continue
        if ends[idx] < mpos: continue
        # Criba municipio sobre bytes (sin decodificar)
        entry_raw = raw_bytes[starts[idx]:ends[idx]]
        if not any(v in entry_raw for v in muni_b_variants):
            continue
        seen.add(idx)
        try:
            results.append(entry_raw.decode("utf-8"))
        except UnicodeDecodeError:
            results.append(entry_raw.decode("latin-1", errors="replace"))

    return results


def parsear_atom_bytes(raw_bytes, municipio, _muni_re=None):
    """Parsea un .atom en bytes buscando contratos del municipio."""

    # ── Criba rápida a nivel de fichero (bytes) ───────────────────────────────
    muni_b = (' ' + municipio).encode('utf-8')
    muni_b_lo = (' ' + municipio.lower()).encode('utf-8')
    if muni_b not in raw_bytes and muni_b_lo not in raw_bytes:
        return []

    # Variantes de bytes para filtrar entries
    muni_b_variants = (muni_b, muni_b_lo, (' ' + municipio.upper()).encode('utf-8'))

    # Regex organo (compilar una vez por municipio)
    if _muni_re is None:
        _muni_re = re.compile(rf'\b{re.escape(normalizar(municipio))}\b')

    contratos = []
    # _entries_con_estado_bytes ya filtra por estado Y municipio; parsear solo las candidatas
    for entry_xml in _entries_con_estado_bytes(raw_bytes, muni_b_variants):
        try:
            c = _entry_to_contrato(entry_xml)
            if c and _muni_re.search(normalizar(c.get("organo", ""))):
                contratos.append(c)
        except Exception:
            pass
    return contratos


# ─── DESCARGA Y CACHÉ DE ZIPS ────────────────────────────────────────────────

def _anomes_actual():
    return datetime.now().strftime("%Y%m")

def _anomes_anterior():
    now = datetime.now()
    return f"{now.year - 1}12" if now.month == 1 else f"{now.year}{now.month - 1:02d}"


def descargar_zip_place(anomes, job_id=None):
    """Descarga el ZIP mensual de PLACE con reintentos y reanudación parcial."""
    cache_path = os.path.join(CACHE_DIR, f"place_{anomes}.zip")
    if os.path.exists(cache_path):
        _log(job_id, f"ZIP {anomes} en caché local.")
        return cache_path

    url = PLACE_ZIP_BASE.format(anomes=anomes)
    temp_path = cache_path + ".tmp"
    _log(job_id, f"Descargando datos oficiales PLACE {anomes}…")

    for intento in range(5):
        try:
            descargado = os.path.getsize(temp_path) if os.path.exists(temp_path) else 0
            hdrs = {"Range": f"bytes={descargado}-"} if descargado > 0 else {}
            r = session.get(url, timeout=(20, 120), stream=True, headers=hdrs)

            if r.status_code == 416:
                os.rename(temp_path, cache_path)
                return cache_path
            if r.status_code not in (200, 206):
                _log(job_id, f"HTTP {r.status_code} — ZIP no disponible para {anomes}")
                return None

            content_len = int(r.headers.get("content-length", 0))
            total = descargado + content_len if r.status_code == 206 else content_len
            modo = "ab" if r.status_code == 206 else "wb"
            if r.status_code == 200:
                descargado = 0

            ultimo_pct = -1
            with open(temp_path, modo) as f:
                for chunk in r.iter_content(512 * 1024):
                    f.write(chunk)
                    descargado += len(chunk)
                    if total:
                        pct = int(100 * descargado / total)
                        if pct != ultimo_pct and pct % 10 == 0:
                            _log(job_id, f"  ↓ {anomes}: {pct}% "
                                 f"({descargado // 1024 // 1024} MB / {total // 1024 // 1024} MB)")
                            ultimo_pct = pct

            os.rename(temp_path, cache_path)
            _log(job_id, f"ZIP {anomes} descargado ({descargado // 1024 // 1024} MB).")
            return cache_path

        except Exception as e:
            _log(job_id, f"  Intento {intento+1}/5 interrumpido ({type(e).__name__}). Reanudando…")
            time.sleep(4 * (intento + 1))

    _log(job_id, f"No se pudo descargar el ZIP de {anomes} tras 5 intentos.")
    return None


def buscar_en_zip(zip_path, municipio, job_id=None):
    """Lee el ZIP completo en RAM y procesa los atom files en paralelo."""
    nombre = os.path.basename(zip_path)
    muni_re = re.compile(rf'\b{re.escape(normalizar(municipio))}\b')

    # 1. Leer todos los bytes en memoria (el ZIP ya está en disco, es I/O puro)
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            atom_names = [n for n in z.namelist() if n.endswith(".atom")]
            total = len(atom_names)
            _log(job_id, f"  Cargando {total} archivos de {nombre}…")
            raw_list = [(n, z.read(n)) for n in atom_names]
    except Exception as e:
        _log(job_id, f"Error abriendo {nombre}: {e}")
        return []

    # 2. Procesar en paralelo (4 workers)
    contratos_total = []
    lock = threading.Lock()
    procesados = [0]

    def _procesar(item):
        _, raw = item
        result = parsear_atom_bytes(raw, municipio, muni_re)
        with lock:
            procesados[0] += 1
            pct = int(100 * procesados[0] / total)
            if pct % 25 == 0 and pct > 0 and procesados[0] % (total // 4 or 1) == 0:
                n_enc = len(contratos_total)
                _log(job_id, f"  {nombre}: {pct}% — {n_enc} contratos encontrados")
        return result

    with ThreadPoolExecutor(max_workers=4) as ex:
        for parcial in ex.map(_procesar, raw_list):
            contratos_total.extend(parcial)

    return contratos_total


def buscar_en_feed_vivo(municipio):
    """Consulta el feed en vivo de PLACE (últimas ~200 entradas de toda España)."""
    try:
        r = session.get(PLACE_FEED_LIVE, timeout=(8, 30))
        if r.status_code == 200:
            return parsear_atom_bytes(r.content, municipio)
    except Exception:
        pass
    return []


# ─── BÚSQUEDA EN BORM (Boletín Oficial Región de Murcia) ─────────────────────

_BORM_CONTRATO_RE = re.compile(
    r'\b(adjudic|formaliz|licitaci|contrat[ao]\b|obras?\b|servicio\b|suministro\b|concesi[oó]n)',
    re.I,
)

# Empresa: captura nombre + NIF/CIF en diversas estructuras textuales del BORM
_BORM_EMPRESA_RE = re.compile(
    r'(?:adjudic[oó](?:\s+el\s+contrato)?(?:\s+a)?|'
    r'adjudicatari[ao][:\s]+|'
    r'empresa\s+adjudicataria[:\s]+|'
    r'contratista[:\s]+|'
    r'mercantil\s+|'
    r'empresa\s+)'
    r'([A-ZÁÉÍÓÚÑ\w][^,(]{3,80}?)'
    r'\s*[\(,]?\s*(?:CIF|NIF|C\.?I\.?F\.?|N\.?I\.?F\.?)[:\s]*([A-Za-z][0-9]{7}[A-Za-z0-9])',
    re.I,
)

# Importe: captura importes en texto con múltiples formulaciones habituales del BORM
_BORM_IMPORTE_RE = re.compile(
    r'(?:'
    r'importe\s+(?:de\s+)?(?:adjudicaci[oó]n|licitaci[oó]n|contrato)?|'
    r'precio\s+(?:de\s+)?(?:adjudicaci[oó]n|licitaci[oó]n)?|'
    r'presupuesto\s+(?:base\s+de\s+licitaci[oó]n\s+)?(?:de\s+contrata\s+)?|'
    r'adjudicaci[oó]n\s+por\s+(?:un\s+importe\s+(?:de\s+)?)?|'
    r'por\s+(?:un\s+total\s+de\s+)?(?:importe\s+(?:de\s+)?)?\s*'
    r')'
    r'[\:\-de]?\s*(?:IVA\s+(?:excluido|incluido|no\s+incluido)\s+)?'
    r'([0-9]{1,3}(?:[.,][0-9]{3})*(?:[.,][0-9]{1,2})?)\s*(?:euros?|€)',
    re.I,
)

# Fecha de adjudicación en texto BORM
_BORM_FECHA_RE = re.compile(
    r'(?:fecha\s+de\s+adjudicaci[oó]n|resoluci[oó]n\s+de\s+fecha)[:\s]+'
    r'(\d{1,2}\s+de\s+\w+\s+de\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})',
    re.I,
)


def _parse_borm_contrato(texto, id_anuncio, sumario, fecha_pub):
    """Extrae datos de contrato del texto plano de un anuncio BORM."""
    empresa, nif, importe_raw = "", "", ""

    m = _BORM_EMPRESA_RE.search(texto)
    if m:
        empresa = m.group(1).strip().rstrip(",. ")
        nif = m.group(2).upper()

    if not empresa:
        m2 = re.search(
            r'([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñÁÉÍÓÚÑ ,\.&]{4,70}?)\s*[\(,\s]'
            r'(?:CIF|NIF)[:\s]+([A-Za-z][0-9]{7}[A-Za-z0-9])',
            texto, re.I,
        )
        if m2:
            empresa = m2.group(1).strip().rstrip(",. (")
            nif = m2.group(2).upper()

    # Fallback: busca NIF suelto y retrocede al nombre
    if not empresa:
        for nif_m in re.finditer(r'\b([ABCDEFGHJKLMNPQRSUVW][0-9]{7}[A-Z0-9])\b', texto, re.I):
            start = max(0, nif_m.start() - 120)
            ctx = texto[start:nif_m.start()]
            candidate = re.split(r'[\.\n;]', ctx)[-1].strip().rstrip(",( ")
            if 4 < len(candidate) < 80 and not re.search(r'\d{5,}', candidate):
                empresa = candidate
                nif = nif_m.group(1).upper()
                break

    m_imp = _BORM_IMPORTE_RE.search(texto)
    if m_imp:
        raw = re.sub(r'\s+', '', m_imp.group(1))
        # Normalizar separadores: si tiene punto Y coma, el último separador es decimal
        if ',' in raw and '.' in raw:
            # Formato español: 1.234.567,89 → quitar puntos, coma→punto
            raw = raw.replace('.', '').replace(',', '.')
        elif ',' in raw:
            # Puede ser 1234,56 (decimal) o 1.234 (miles)
            parts = raw.split(',')
            if len(parts) == 2 and len(parts[1]) <= 2:
                raw = raw.replace(',', '.')
            else:
                raw = raw.replace(',', '')
        importe_raw = raw

    # Órgano contratante: busca en el texto cerca de "órgano" o "contratante"
    organo = ""
    m_org = re.search(
        r'(?:[oó]rgano\s+(?:de\s+)?contrataci[oó]n|poder\s+adjudicador)[:\s]+([^\n.]{5,80})',
        texto, re.I,
    )
    if m_org:
        organo = m_org.group(1).strip().rstrip(",. ")

    # Título: 1.ª línea no vacía que parezca descripción del objeto
    titulo = sumario
    lines = [l.strip() for l in texto.splitlines() if l.strip()]
    for line in lines[2:]:
        if (len(line) > 20
                and not re.match(r'^[IVX]+[\.\-]', line)
                and not re.match(r'^\d+[\.\-]', line)
                and not re.search(r'ayuntamiento|municipio|borm|boletín', line, re.I)):
            titulo = line
            break

    importe = fmt_eur(importe_raw) if importe_raw else ""
    borm_pdf  = BORM_PDF_URL.format(id=id_anuncio)
    borm_html = f"https://www.borm.es/services/anuncio/{id_anuncio}/html"

    return {
        "titulo":        titulo[:200],
        "organo":        organo,
        "empresa":       empresa or "No localizada",
        "nif":           nif,
        "importe":       importe or "No localizado",
        "importe_num":   float(importe_raw) if importe_raw else 0.0,
        "estado":        "ADJ",
        "licitacion_id": "",
        "url":           borm_pdf,
        "borm_html_url": borm_html,
        "fuente":        "BORM",
        "fuente_label":  f"BORM {fecha_pub}",
        "directivo":     "",
        "cargo":         "",
    }


def _enlazar_borm_place(contratos):
    """Añade borm_url a contratos PLACE si existe un contrato BORM con título similar."""
    borm_cs = [c for c in contratos if c.get("fuente") == "BORM"]
    place_cs = [c for c in contratos if c.get("fuente") == "PLACE"]
    if not borm_cs:
        return
    for b in borm_cs:
        btit = normalizar(b.get("titulo", ""))[:60]
        if not btit:
            continue
        for p in place_cs:
            ptit = normalizar(p.get("titulo", ""))[:60]
            if btit and ptit and btit[:40] == ptit[:40]:
                p["borm_url"] = b["url"]


def buscar_en_borm(municipio, job_id=None):
    """Busca contratos adjudicados publicados en el BORM para el municipio dado."""
    _log(job_id, "Consultando BORM (Boletín Oficial Región de Murcia)…")
    contratos = []

    # Solo anuncios de adjudicación/formalización de contratos (evitar padrones, presupuestos, etc.)
    keywords_sumario = ["adjudic", "formaliz", "licitaci"]

    # Buscar anuncios del municipio en BORM (sumario)
    payload = {
        "textoLibre": municipio,
        "fechaDesde": "01/01/2020",
        "fechaHasta": datetime.now().strftime("%d/%m/%Y"),
        "anunciante": municipio,   # el BORM registra el Ayto. solo con el nombre del municipio
        "rango": 0,
        "tipo": "libre",
        "nombre": "", "apellidos": "", "nif": "",
        "etiqueta": 0, "origen": 0,
        "idApartado": "", "anuncianteFaceta": "", "idCategoria": "",
        "tipoBusqueda": 0,
    }
    try:
        r = session.post(BORM_BUSCAR_URL, json=payload, timeout=(8, 20))
        if r.status_code != 200:
            _log(job_id, f"  BORM: HTTP {r.status_code}")
            return []

        # La API puede responder con JSON o con XML según la versión
        ct = r.headers.get("Content-Type", "")
        if "json" in ct:
            raw_anuncios = r.json().get("anuncios", [])
            anuncios = raw_anuncios if isinstance(raw_anuncios, list) else []
        else:
            # Parsear XML (formato vigente a partir de mayo 2026)
            import xml.etree.ElementTree as _ET
            root = _ET.fromstring(r.content)
            anuncios = []
            for a in root.findall("anuncios/anuncios"):
                def _txt(tag):
                    el = a.find(tag)
                    return el.text.strip() if el is not None and el.text else ""
                anuncios.append({
                    "idAnuncio":        _txt("idAnuncio"),
                    "sumario":          _txt("sumario"),
                    "anunciante":       _txt("anunciante"),
                    "fechaPublicacion": _txt("fechaPublicacion"),
                })
    except Exception as e:
        _log(job_id, f"  BORM no disponible ({type(e).__name__})")
        return []

    # Filtrar anuncios que sean adjudicaciones/formalizaciones reales
    candidatos = [
        a for a in anuncios
        if any(k in normalizar(a.get("sumario", "")) for k in keywords_sumario)
    ]

    if not candidatos:
        _log(job_id, f"  BORM: 0 contratos encontrados para {municipio}")
        return []

    _log(job_id, f"  BORM: {len(candidatos)} anuncios de contratos — leyendo texto…")

    muni_re = re.compile(rf'\b{re.escape(normalizar(municipio))}\b', re.I)

    def _fetch_y_parsear(anuncio):
        try:
            id_a = anuncio["idAnuncio"]
            txt_url = BORM_TXT_URL.format(id=id_a)
            r2 = session.get(txt_url, timeout=(4, 10))
            if r2.status_code != 200:
                return None
            # Force UTF-8; fall back to Latin-1 if decoding fails
            try:
                texto = r2.content.decode("utf-8")
            except UnicodeDecodeError:
                texto = r2.content.decode("latin-1", errors="replace")
            if not (muni_re.search(normalizar(texto)) and _BORM_CONTRATO_RE.search(texto)):
                return None
            return _parse_borm_contrato(
                texto,
                id_a,
                anuncio.get("sumario", ""),
                anuncio.get("fechaPublicacion", ""),
            )
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=4) as ex:
        for c in ex.map(_fetch_y_parsear, candidatos):
            if c:
                contratos.append(c)

    _log(job_id, f"  BORM: {len(contratos)} contratos con datos extraídos")
    return contratos


# ─── DIRECTIVOS (BORME / InfoEmpresa) ────────────────────────────────────────

def _obtener_html(url, timeout=(5, 12)):
    try:
        r = session.get(url, timeout=timeout, allow_redirects=True)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return ""

def _extraer_texto(html_text):
    soup = BeautifulSoup(html_text, "html.parser")
    for t in soup(["script", "style", "noscript"]):
        t.extract()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()

_CARGO_RE = re.compile(
    r"(administrador(?:\s+[úu]nico|\s+solidario|\s+mancomunado)?|"
    r"apoderado(?:\s+general)?|consejero\s+delegado|presidente|"
    r"gerente|director\s+general|socio(?:\s+director)?)"
    r"[\s:,\-]+([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ ]{5,80})",
    re.IGNORECASE,
)

def _extraer_directivo(texto):
    for m in _CARGO_RE.finditer(texto):
        a, b = m.group(1).strip(), m.group(2).strip()
        if len(b.split()) >= 2:
            return b.title(), a.title()
    return "", ""

def _infoempresa_slug(empresa):
    """Genera el slug de URL para infoempresa.com a partir del nombre de empresa."""
    s = normalizar(empresa)
    s = re.sub(r"[,/&|]", " ", s)
    s = re.sub(r"[^a-z0-9\s]", "", s)
    return re.sub(r"\s+", "-", s.strip())

_SUF_NORM_RE = re.compile(r"\b(sl|sa|slu|sau|slp|sc|cb|coop|slne|sal)\b\.?", re.I)

def _empresa_match(busqueda, borme):
    """True si dos nombres de empresa se refieren a la misma entidad (comparación aproximada)."""
    if not busqueda or not borme:
        return False
    a = normalizar(busqueda)
    b = normalizar(borme)
    if a == b:
        return True
    a2 = _SUF_NORM_RE.sub("", a).strip()
    b2 = _SUF_NORM_RE.sub("", b).strip()
    return bool(a2) and bool(b2) and (a2 == b2 or a2 in b2 or b2 in a2)

_BORME_NOM_RE = re.compile(
    r"nombramiento[s]?\s*[.:]\s*"
    r"(administrador(?:\s+(?:[úu]nico|solidario|mancomunado))?|"
    r"consejero\s+delegado|presidente|gerente|director\s+general|"
    r"apoderado(?:\s+general)?)\s*[.:]?\s+"
    r"([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñÁÉÍÓÚÑ]+(?:\s+[A-Za-záéíóúñÁÉÍÓÚÑ]+){1,5})",
    re.IGNORECASE,
)

def _extraer_directivo_nombramiento(texto):
    """Extrae el administrador de texto BORME priorizando la sección Nombramientos."""
    if not texto:
        return "", ""
    nom_idx = texto.lower().find("nombramiento")
    candidato = texto[nom_idx:] if nom_idx >= 0 else texto
    for m in _BORME_NOM_RE.finditer(candidato):
        cargo, nombre = m.group(1).strip(), m.group(2).strip()
        if len(nombre.split()) >= 2 and not _CARGOS_SKIP.search(cargo):
            return nombre.title(), cargo.title()
    for m in _CARGO_RE.finditer(candidato):
        cargo, nombre = m.group(1).strip(), m.group(2).strip()
        if len(nombre.split()) >= 2 and not _CARGOS_SKIP.search(cargo):
            return nombre.title(), cargo.title()
    return "", ""


_CARGOS_SKIP = re.compile(r"\b(auditor|liquidador|comisario|verificador)\b", re.I)
_NOMBRE_EMPRESA_RE = re.compile(r"\b(s\.?l\.?|s\.?a\.?|s\.?l\.?p\.?|s\.?c\.?|cb)\b", re.I)


# Maps BORME abbreviated titles to canonical Spanish names
_CARGO_BORME_MAP = (
    (re.compile(r"adm\.?\s+[úu]nico", re.I),        "Administrador Único"),
    (re.compile(r"adm\.?\s+solidario", re.I),        "Administrador Solidario"),
    (re.compile(r"adm\.?\s+mancomunado", re.I),      "Administrador Mancomunado"),
    (re.compile(r"c\.?\s+delegado", re.I),            "Consejero Delegado"),
    (re.compile(r"consejero\s+delegado", re.I),       "Consejero Delegado"),
    (re.compile(r"administrador", re.I),              "Administrador"),
    (re.compile(r"gerente", re.I),                    "Gerente"),
    (re.compile(r"presidente", re.I),                 "Presidente"),
)

_BORME_PARRAFO_RE = re.compile(
    r"\b(Adm\.?\s+(?:[Úú]nico|Unico|Solidario|Mancomunado)"
    r"|Administrador(?:\s+(?:[Úú]nico|Solidario|Mancomunado))?"
    r"|C\.?\s+Delegado|Consejero\s+Delegado"
    r"|Gerente|Presidente|Director\s+General"
    r"|Apoderado(?:\s+General)?)\s*[:.]\s*"
    r"([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñÁÉÍÓÚÑ]+(?:\s+[A-Za-záéíóúñÁÉÍÓÚÑ]+){1,5})",
    re.IGNORECASE,
)


def _extraer_directivo_parrafo(texto):
    """Extrae administrador de un párrafo BORME (usa abreviaturas: Adm. Unico, etc.)."""
    if not texto:
        return "", ""
    # Only look in the Nombramientos section; stop at 'Datos registrales'
    nom_idx = texto.lower().find("nombramiento")
    candidato = texto[nom_idx:] if nom_idx >= 0 else texto
    dr_idx = candidato.lower().find("datos registrales")
    if dr_idx > 0:
        candidato = candidato[:dr_idx]
    for m in _BORME_PARRAFO_RE.finditer(candidato):
        cargo_raw = m.group(1).strip()
        nombre = m.group(2).strip().rstrip(".")
        if len(nombre.split()) < 2 or _CARGOS_SKIP.search(cargo_raw):
            continue
        cargo = cargo_raw
        for pat, canonical in _CARGO_BORME_MAP:
            if pat.match(cargo_raw):
                cargo = canonical
                break
        return nombre.title(), cargo
    return "", ""


def _borme_entry_admin(entry_id, empresa):
    """Descarga el XML de una entrada provincial BORME-A y extrae el administrador."""
    import xml.etree.ElementTree as ET
    try:
        rx = session.get(
            f"https://www.boe.es/diario_borme/xml.php?id={entry_id}",
            timeout=(5, 15),
        )
        if rx.status_code != 200:
            return "", ""
        root = ET.fromstring(rx.content)
        texto_el = root.find(".//texto")
        if texto_el is None:
            return "", ""
        # Collect all <p> in order — alternating articulo / parrafo
        parrafos = [p for p in texto_el.iter("p")]
        for i, p in enumerate(parrafos):
            if p.get("class") != "articulo":
                continue
            articulo_txt = (p.text or "").strip()
            # Format: "NUMBER - COMPANY NAME."
            m = re.match(r"\d+\s*-\s*(.+)", articulo_txt)
            if not m:
                continue
            company_in_entry = m.group(1).strip().rstrip(".")
            if not _empresa_match(empresa, company_in_entry):
                continue
            # Found this company — parse the following parrafo
            if i + 1 < len(parrafos) and parrafos[i + 1].get("class") == "parrafo":
                n, c = _extraer_directivo_parrafo((parrafos[i + 1].text or "").strip())
                if n:
                    return n, c
    except Exception:
        pass
    return "", ""


def buscar_directivo_borme_api(empresa, nif=""):
    """Busca directivos en el BORME oficial vía sumario API + índice alfabético."""
    if not empresa or empresa == "No localizada":
        return "", ""
    from datetime import date, timedelta
    import xml.etree.ElementTree as ET

    d = date.today()
    issues_checked = 0
    attempts = 0
    seen_entries: set = set()

    while issues_checked < 10 and attempts < 30:
        date_str = d.strftime("%Y%m%d")
        d -= timedelta(days=1)
        attempts += 1

        # Get the daily sumario
        try:
            r_sum = session.get(
                f"https://www.boe.es/datosabiertos/api/borme/sumario/{date_str}",
                headers={"Accept": "application/xml"},
                timeout=(4, 10),
            )
        except Exception:
            continue
        if r_sum.status_code != 200 or "<seccion" not in r_sum.text:
            continue

        try:
            sum_root = ET.fromstring(r_sum.content)
        except Exception:
            continue

        # Find the alphabetical index entry (always ends in -99)
        idx_id = None
        all_section_a_ids = []
        for item in sum_root.iter("item"):
            eid = (item.findtext("identificador") or "").strip()
            if not eid.startswith("BORME-A-"):
                continue
            all_section_a_ids.append(eid)
            if eid.endswith("-99"):
                idx_id = eid

        if not idx_id:
            continue
        issues_checked += 1

        # Fetch the alphabetical index to find which provincial entry contains our company
        try:
            r_idx = session.get(
                f"https://www.boe.es/diario_borme/xml.php?id={idx_id}",
                timeout=(5, 15),
            )
            if r_idx.status_code != 200:
                continue
            idx_root = ET.fromstring(r_idx.content)
        except Exception:
            continue

        texto_el = idx_root.find(".//texto")
        if texto_el is None:
            continue

        for tr in texto_el.iter("tr"):
            tds = list(tr.findall("td"))
            if len(tds) < 2:
                continue
            company_cell = (tds[0].text or "").strip()
            if not company_cell:
                for p in tds[0].iter("p"):
                    company_cell = (p.text or "").strip()
                    break
            entry_id = ""
            for p in tds[1].iter("p"):
                entry_id = (p.text or "").strip()
                break
            if not company_cell or not entry_id or not entry_id.startswith("BORME-A-"):
                continue
            if not _empresa_match(empresa, company_cell):
                continue
            if entry_id in seen_entries:
                continue
            seen_entries.add(entry_id)
            n, c = _borme_entry_admin(entry_id, empresa)
            if n:
                return n, c

    return "", ""


_CONECTORES = {"y", "e", "de", "del", "los", "las", "el", "la", "y", "para", "en"}


def buscar_directivo_empresite(empresa):
    """Fallback: scraper de empresite.eleconomista.es (datos públicos del R.M.)."""
    slug = normalizar(empresa)
    slug = re.sub(r"[^a-z0-9\s]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    if not slug:
        return "", ""
    try:
        r = session.get(
            f"https://empresite.eleconomista.es/{slug}/",
            timeout=(4, 9),
            allow_redirects=True,
        )
        if r.status_code != 200:
            return "", ""
        soup = BeautifulSoup(r.text, "html.parser")
        # Sección de administradores / directivos
        for section in soup.find_all(["section", "div"], class_=re.compile(r"administ|directiv|cargo", re.I)):
            text = section.get_text(" ", strip=True)
            for m in _CARGO_RE.finditer(text):
                cargo_str, nombre = m.group(1).strip(), m.group(2).strip()
                if len(nombre.split()) >= 2 and not _CARGOS_SKIP.search(cargo_str):
                    return nombre.title(), cargo_str.title()
        # Fallback: buscar el patrón en el texto completo de la página
        page_text = soup.get_text(" ", strip=True)
        for m in _CARGO_RE.finditer(page_text):
            cargo_str, nombre = m.group(1).strip(), m.group(2).strip()
            if len(nombre.split()) >= 2 and not _CARGOS_SKIP.search(cargo_str):
                return nombre.title(), cargo_str.title()
    except Exception:
        pass
    return "", ""


def buscar_directivo_borme(empresa, nif=""):
    """Busca en el BORME (boe.es) nombramientos/ceses de la empresa."""
    if not empresa or empresa == "No localizada":
        return "", ""
    try:
        from urllib.parse import quote_plus as _qp
        query = nif if nif else empresa
        url = f"https://www.boe.es/borme/buscar.php?text={_qp(query)}&type=1"
        r = session.get(url, timeout=(5, 12))
        if r.status_code != 200:
            return "", ""
        soup = BeautifulSoup(r.text, "html.parser")
        # Extrae el primer resultado con datos de nombramiento
        for row in soup.select("div.resultado, li.resultado, tr"):
            text = row.get_text(" ", strip=True)
            for m in _CARGO_RE.finditer(text):
                cargo_str, nombre = m.group(1).strip(), m.group(2).strip()
                if len(nombre.split()) >= 2 and not _CARGOS_SKIP.search(cargo_str):
                    return nombre.title(), cargo_str.title()
    except Exception:
        pass
    return "", ""


def _scrape_admin_from_page(soup):
    """Extrae administrador de una página BS4 probando varios selectores y CARGO_RE."""
    # Intentar bloques específicos primero
    for sel in ("div.administradores", "section.administradores", "#administradores",
                "div.cargos", "section.cargos", "#cargos", "table.cargos",
                "div.organ", ".organ-section", ".empresa-directivos__list"):
        bloque = soup.select_one(sel)
        if bloque:
            for m in _CARGO_RE.finditer(bloque.get_text(" ", strip=True)):
                c, n = m.group(1).strip(), m.group(2).strip()
                if len(n.split()) >= 2 and not _CARGOS_SKIP.search(c):
                    return n.title(), c.title()
    # Fallback: página completa
    for m in _CARGO_RE.finditer(soup.get_text(" ", strip=True)):
        c, n = m.group(1).strip(), m.group(2).strip()
        if len(n.split()) >= 2 and not _CARGOS_SKIP.search(c):
            return n.title(), c.title()
    return "", ""


def buscar_directivo_einforma(empresa, nif=""):
    """Busca administrador en einforma.com (búsqueda por NIF o nombre)."""
    if not empresa or empresa == "No localizada":
        return "", ""
    try:
        q = nif if nif else empresa
        r = session.get(
            "https://www.einforma.com/buscar-empresa",
            params={"q": q},
            timeout=(5, 12),
        )
        if r.status_code != 200:
            return "", ""
        soup = BeautifulSoup(r.text, "html.parser")
        primer = (soup.select_one("a[href*='/info-empresa'], a[href*='/empresa/']") or
                  soup.find("a", href=re.compile(r"einforma\.com/\S*empresa\S*", re.I)))
        if not primer:
            return "", ""
        href = primer.get("href", "")
        if not href.startswith("http"):
            href = "https://www.einforma.com" + href
        r2 = session.get(href, timeout=(5, 12))
        if r2.status_code != 200:
            return "", ""
        return _scrape_admin_from_page(BeautifulSoup(r2.text, "html.parser"))
    except Exception:
        pass
    return "", ""


def buscar_directivo_axesor(empresa, nif=""):
    """Busca administrador en axesor.es."""
    if not empresa or empresa == "No localizada":
        return "", ""
    try:
        # Axesor permite buscar directamente por NIF en la URL
        if nif:
            r = session.get(
                f"https://www.axesor.es/informes-empresas/{quote_plus(nif)}",
                timeout=(5, 12),
                allow_redirects=True,
            )
        else:
            r = session.get(
                "https://www.axesor.es/buscar",
                params={"q": empresa},
                timeout=(5, 12),
            )
        if r.status_code != 200:
            return "", ""
        soup = BeautifulSoup(r.text, "html.parser")
        # Si es página de búsqueda, seguir primer resultado
        if "/buscar" in r.url or "/search" in r.url:
            primer = (soup.select_one("a[href*='/informes-empresas/']") or
                      soup.find("a", href=re.compile(r"axesor\.es/informes", re.I)))
            if not primer:
                return "", ""
            href = primer.get("href", "")
            if not href.startswith("http"):
                href = "https://www.axesor.es" + href
            r = session.get(href, timeout=(5, 12))
            if r.status_code != 200:
                return "", ""
            soup = BeautifulSoup(r.text, "html.parser")
        return _scrape_admin_from_page(soup)
    except Exception:
        pass
    return "", ""


def buscar_directivo_infocif(empresa, nif=""):
    """Busca administrador en infocif.es."""
    if not empresa or empresa == "No localizada":
        return "", ""
    try:
        q = nif if nif else empresa
        r = session.get(
            "https://www.infocif.es/buscar",
            params={"q": q, "tipo": "empresas"},
            timeout=(5, 12),
        )
        if r.status_code != 200:
            return "", ""
        soup = BeautifulSoup(r.text, "html.parser")
        primer = (soup.select_one("a[href*='/ficha-empresa/']") or
                  soup.find("a", href=re.compile(r"infocif\.es/ficha", re.I)))
        if not primer:
            return "", ""
        href = primer.get("href", "")
        if not href.startswith("http"):
            href = "https://www.infocif.es" + href
        r2 = session.get(href, timeout=(5, 12))
        if r2.status_code != 200:
            return "", ""
        return _scrape_admin_from_page(BeautifulSoup(r2.text, "html.parser"))
    except Exception:
        pass
    return "", ""


def buscar_directivo(empresa, nif=""):
    """Busca directivo: persona física → BORME API → empresite. Usa caché persistente."""
    if not empresa or empresa == "No localizada":
        return "", ""
    palabras = empresa.strip().split()
    palabras_limpias = [p for p in palabras if re.match(r"^[A-ZÁÉÍÓÚÑÜa-záéíóúñü]+$", p)]
    tiene_conectores = any(p.lower() in _CONECTORES for p in palabras)
    if (2 <= len(palabras) <= 4
            and not tiene_conectores
            and not _SUFIJOS_EMPRESA.search(empresa)
            and len(palabras_limpias) == len(palabras)):
        return empresa.title(), "Autónomo / Persona física"
    cached_n, cached_c = _dir_cache_get(empresa, nif)
    if cached_n is not None:
        return cached_n, cached_c
    nombre, cargo = buscar_directivo_borme_api(empresa, nif)
    if not nombre:
        nombre, cargo = buscar_directivo_empresite(empresa)
    _dir_cache_set(empresa, nif, nombre, cargo)
    return nombre, cargo


# ─── ANÁLISIS ANTICORRUPCIÓN ─────────────────────────────────────────────────

def analizar_riesgo(contratos):
    """Genera indicadores de riesgo sobre la lista de contratos."""
    if not contratos:
        return []

    alertas = []
    total = len(contratos)
    empresas_count = {}
    empresas_importe = {}

    for c in contratos:
        emp = c.get("empresa", "No localizada")
        if emp == "No localizada":
            continue
        empresas_count[emp] = empresas_count.get(emp, 0) + 1
        empresas_importe[emp] = empresas_importe.get(emp, 0.0) + c.get("importe_num", 0.0)

    if not empresas_count:
        return alertas

    # Empresa con > 50% de adjudicaciones
    for emp, count in empresas_count.items():
        pct = round(100 * count / total)
        if pct > 50:
            alertas.append({
                "nivel": "alto",
                "icono": "⚠️",
                "texto": (
                    f"<strong>{esc(emp)}</strong> acumula el {pct}% de las adjudicaciones "
                    f"({count} de {total} contratos) — posible concentración de contratación."
                ),
            })

    # Empresa con > 50% del importe total
    total_importe = sum(empresas_importe.values())
    if total_importe > 0:
        for emp, imp in empresas_importe.items():
            pct = round(100 * imp / total_importe)
            if pct > 50 and empresas_count.get(emp, 0) >= 2:
                alertas.append({
                    "nivel": "medio",
                    "icono": "🔍",
                    "texto": (
                        f"<strong>{esc(emp)}</strong> concentra el {pct}% del importe total adjudicado "
                        f"({fmt_eur(str(imp))})."
                    ),
                })

    # Empresa sin nombre (posible opacidad)
    sin_empresa = sum(1 for c in contratos if c.get("empresa") == "No localizada")
    if sin_empresa > 0:
        pct = round(100 * sin_empresa / total)
        alertas.append({
            "nivel": "info",
            "icono": "ℹ️",
            "texto": (
                f"{sin_empresa} contrato{'s' if sin_empresa != 1 else ''} "
                f"({pct}%) sin empresa adjudicataria identificada."
            ),
        })

    return alertas


# ─── ORQUESTACIÓN DEL JOB ────────────────────────────────────────────────────

# ─── CACHÉ DE RESULTADOS — helpers ───────────────────────────────────────────

def _cache_get(municipio):
    key = normalizar(municipio)
    with _cache_lock:
        entry = _result_cache.get(key)
    if entry and (time.time() - entry["ts"]) < RESULT_CACHE_TTL:
        return entry["resultado"]
    return None

def _cache_set(municipio, resultado):
    key = normalizar(municipio)
    with _cache_lock:
        _result_cache[key] = {"ts": time.time(), "resultado": resultado}

def _cache_age_str(municipio):
    key = normalizar(municipio)
    with _cache_lock:
        entry = _result_cache.get(key)
    if not entry:
        return ""
    mins = int((time.time() - entry["ts"]) / 60)
    if mins < 2:   return "hace menos de 2 min"
    if mins < 60:  return f"hace {mins} min"
    return f"hace {mins // 60}h {mins % 60}min"

def _cache_invalidate(municipio):
    key = normalizar(municipio)
    with _cache_lock:
        _result_cache.pop(key, None)


def _log(job_id, msg):
    if job_id:
        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id].setdefault("log", []).append(msg)


def _job_run(job_id, municipio):
    try:
        _log(job_id, f"Iniciando búsqueda de contratos para {municipio}…")
        contratos = []

        # 1. Feed en vivo
        _log(job_id, "Consultando feed en vivo de PLACE…")
        vivos = buscar_en_feed_vivo(municipio)
        contratos += vivos
        _log(job_id, f"  Feed en vivo: {len(vivos)} contratos")

        # 2. Construir lista de ZIPs: los 2 más recientes + todos los ya cacheados
        _zips_vistos = set()
        zips = []   # lista de (anomes, zip_path)

        def _add_zip(am):
            if am in _zips_vistos:
                return
            _zips_vistos.add(am)
            p = descargar_zip_place(am, job_id)
            if p:
                try:        # descartar archivos vacíos / inválidos
                    import zipfile as _zf
                    with _zf.ZipFile(p) as _z:
                        pass
                    zips.append((am, p))
                except Exception:
                    _log(job_id, f"  ZIP {am}: archivo inválido, ignorado")

        # Descargar los 2 más recientes si faltan
        _add_zip(_anomes_actual())
        _add_zip(_anomes_anterior())

        # Sumar los que ya estén en caché (en orden descendente = más recientes primero)
        for _fname in sorted(os.listdir(CACHE_DIR), reverse=True):
            if _fname.startswith("place_") and _fname.endswith(".zip"):
                _am = _fname[len("place_"):][:6]   # "place_202503.zip" → "202503"
                _add_zip(_am)

        _log(job_id, f"Procesando {len(zips)} ZIPs en paralelo (BORM simultáneo)…")

        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = {ex.submit(buscar_en_zip, zp, municipio, job_id): ("ZIP", am)
                    for am, zp in zips}
            borm_fut = ex.submit(buscar_en_borm, municipio, job_id)
            futs[borm_fut] = ("BORM", "")
            for fut in as_completed(futs):
                tipo, etiqueta = futs[fut]
                nuevos = fut.result()
                contratos += nuevos
                if tipo == "ZIP":
                    _log(job_id, f"  ZIP {etiqueta}: {len(nuevos)} contratos")
                else:
                    _log(job_id, f"  BORM: {len(nuevos)} contratos adicionales")

        # Deduplicar por URL (dentro de la misma fuente) — PLACE y BORM pueden tener URLs distintas para el mismo contrato
        vistos = set()
        unicos = []
        for c in contratos:
            key = c.get("url") or c.get("titulo", "")[:80]
            if key and key not in vistos:
                vistos.add(key)
                unicos.append(c)
        contratos = unicos

        # Enriquecer contratos PLACE con el link al BORM cuando existe uno equivalente
        _enlazar_borm_place(contratos)
        _log(job_id, f"Total contratos únicos: {len(contratos)}")

        # Directivos — todas las empresas únicas identificadas
        emp_nif = {}  # empresa → nif
        for c in contratos:
            emp = c.get("empresa", "")
            if emp and emp != "No localizada" and emp not in emp_nif:
                emp_nif[emp] = c.get("nif", "")
        empresas_lista = list(emp_nif.items())

        if empresas_lista:
            _log(job_id, f"Buscando directivos de {len(empresas_lista)} empresas "
                 f"(BORME oficial · empresite)…")
        directivos = {}
        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = {ex.submit(buscar_directivo, emp, nif): emp
                    for emp, nif in empresas_lista}
            for fut in as_completed(futs):
                emp = futs[fut]
                try:
                    d, cargo = fut.result()
                    directivos[emp] = (d, cargo)
                except Exception:
                    directivos[emp] = ("", "")

        for c in contratos:
            emp = c.get("empresa", "")
            if emp in directivos:
                c["directivo"], c["cargo"] = directivos[emp]

        # Análisis de riesgo
        alertas = analizar_riesgo(contratos)

        resultado = {
            "municipio":       municipio,
            "organismo":       f"Ayuntamiento de {municipio}",
            "total_contratos": len(contratos),
            "contratos":       contratos,
            "alertas":         alertas,
            "place_profile":   place_profile_url(municipio),
            "timestamp":       time.time(),
        }

        _cache_set(municipio, resultado)

        with _datos_lock:
            _datos_memoria[:] = [d for d in _datos_memoria if normalizar(d.get("municipio", "")) != normalizar(municipio)]
            _datos_memoria.append(resultado)
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(_datos_memoria, f, ensure_ascii=False, indent=2)

        with _jobs_lock:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["total"] = len(contratos)

        # Enriquecer en fondo las sociedades que aún no tienen directivo
        _lanzar_enriquecimiento()

    except Exception as e:
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(e)


def _cargar_datos():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, list):
                    return d
        except Exception:
            pass
    return []


def _inicializar_datos():
    """Carga datos.json y director_cache.json en RAM al arrancar."""
    _dir_cache_load()
    cargados = _cargar_datos()
    with _datos_lock:
        _datos_memoria[:] = cargados
    for d in cargados:
        muni = d.get("municipio", "")
        ts = d.get("timestamp", 0)
        if muni and (time.time() - ts) < RESULT_CACHE_TTL:
            _cache_set(muni, d)


# ─── ENRIQUECIMIENTO EN BACKGROUND (einforma / axesor / infocif) ─────────────

def _contrato_key(c):
    """Clave estable para identificar un contrato independientemente de su posición en memoria."""
    return (c.get("empresa", ""), c.get("url", ""), c.get("titulo", "")[:60])


def _guardar_datos_sin_lock():
    """Escribe _datos_memoria en datos.json. Llamar solo desde dentro de _datos_lock."""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(_datos_memoria, f, ensure_ascii=False, indent=2)


def _enriquecer_directivos_bg():
    """
    Hilo de fondo: para cada contrato de sociedad (SL, SA…) sin directivo localizado
    y sin intento previo, prueba einforma → axesor → infocif y guarda el resultado.
    """
    if not _enriqueciendo_lock.acquire(blocking=False):
        return  # ya hay otro hilo de enriquecimiento en marcha

    try:
        time.sleep(6)  # dejar que el servidor arranque del todo

        # Recopilar contratos pendientes: (municipio, key, empresa, nif)
        pendientes = []
        with _datos_lock:
            for d in _datos_memoria:
                for c in d.get("contratos", []):
                    if (not c.get("directivo")
                            and not c.get("intentado")
                            and _SUFIJOS_EMPRESA.search(c.get("empresa", ""))):
                        pendientes.append((
                            d.get("municipio", ""),
                            _contrato_key(c),
                            c.get("empresa", ""),
                            c.get("nif", ""),
                        ))

        if not pendientes:
            return

        cambios = 0
        for municipio, key, empresa, nif in pendientes:
            # Comprobar caché antes de lanzar peticiones de red
            cached_n, cached_c = _dir_cache_get(empresa, nif)
            if cached_n is not None:
                nombre, cargo = cached_n, cached_c
            else:
                nombre, cargo = buscar_directivo_einforma(empresa, nif)
                if not nombre:
                    nombre, cargo = buscar_directivo_axesor(empresa, nif)
                if not nombre:
                    nombre, cargo = buscar_directivo_infocif(empresa, nif)
                _dir_cache_set(empresa, nif, nombre, cargo)

            with _datos_lock:
                for d in _datos_memoria:
                    if d.get("municipio") != municipio:
                        continue
                    for c in d.get("contratos", []):
                        if _contrato_key(c) == key:
                            if nombre:
                                c["directivo"] = nombre
                                c["cargo"] = cargo
                            c["intentado"] = True
                            cambios += 1
                            break
                # Guardar cada 10 cambios para no perder trabajo si el servidor para
                if cambios % 10 == 0:
                    _guardar_datos_sin_lock()

            if cached_n is None:
                time.sleep(1.5)  # delay entre peticiones para no saturar los sitios

        if cambios > 0:
            with _datos_lock:
                _guardar_datos_sin_lock()

    finally:
        _enriqueciendo_lock.release()


def _lanzar_enriquecimiento():
    """Arranca el hilo de enriquecimiento si no está ya en marcha."""
    threading.Thread(target=_enriquecer_directivos_bg, daemon=True).start()


# ─── HTML / UI ───────────────────────────────────────────────────────────────

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
:root{
  --bg:#0d1117;--surface:#161b22;--border:#30363d;
  --accent:#f0883e;--blue:#58a6ff;--text:#c9d1d9;--dim:#8b949e;
  --red:#f85149;--green:#3fb950;--yellow:#d29922;
}
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:'IBM Plex Sans',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;padding-bottom:60px;}
header{background:var(--surface);border-bottom:1px solid var(--border);padding:16px 28px;display:flex;align-items:center;gap:14px;position:sticky;top:0;z-index:10;}
.logo{font-family:'IBM Plex Mono',monospace;font-size:11px;font-weight:600;color:var(--accent);letter-spacing:3px;border:1px solid var(--accent);padding:4px 8px;border-radius:3px;}
header h1{font-size:15px;font-weight:600;}
header p{font-size:12px;color:var(--dim);margin-top:2px;}
.main{max-width:1340px;margin:28px auto;padding:0 20px;}
.search-bar{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:18px 22px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:24px;}
.search-bar label{font-size:11px;font-family:'IBM Plex Mono',monospace;color:var(--dim);text-transform:uppercase;letter-spacing:1px;white-space:nowrap;}
.search-bar input{background:var(--bg);border:1px solid var(--border);color:var(--text);font-family:'IBM Plex Mono',monospace;font-size:14px;padding:8px 12px;border-radius:6px;flex:1;min-width:180px;outline:none;}
.search-bar input:focus{border-color:var(--blue);}
.btn{padding:8px 18px;border:none;border-radius:6px;cursor:pointer;font-size:13px;font-weight:600;font-family:'IBM Plex Sans',sans-serif;}
.btn-primary{background:var(--accent);color:#000;}
.btn-danger{background:var(--red);color:#fff;}
.stats-bar{display:flex;gap:14px;margin-bottom:18px;flex-wrap:wrap;}
.stat{background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:10px 16px;font-family:'IBM Plex Mono',monospace;font-size:12px;}
.stat span{color:var(--accent);font-size:20px;display:block;font-weight:600;}
/* alertas anticorrupcion */
.alertas{margin-bottom:18px;display:flex;flex-direction:column;gap:8px;}
.alerta{border-radius:6px;padding:10px 16px;font-size:13px;line-height:1.6;display:flex;gap:10px;align-items:flex-start;}
.alerta.alto{background:rgba(248,81,73,.1);border:1px solid rgba(248,81,73,.4);color:#f8c4c2;}
.alerta.medio{background:rgba(210,153,34,.1);border:1px solid rgba(210,153,34,.4);color:#e6c87a;}
.alerta.info{background:rgba(88,166,255,.08);border:1px solid rgba(88,166,255,.3);color:var(--text);}
.alerta-ico{font-size:16px;line-height:1;}
.alerta-titulo{font-family:'IBM Plex Mono',monospace;font-size:10px;text-transform:uppercase;letter-spacing:1px;margin-bottom:3px;opacity:.7;}
/* cards municipio */
.muni-card{background:var(--surface);border:1px solid var(--border);border-radius:8px;margin-bottom:18px;overflow:hidden;}
.muni-header{padding:12px 18px;background:rgba(240,136,62,.08);border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;}
.muni-header h2{font-size:14px;font-weight:600;color:var(--accent);}
.badge{font-family:'IBM Plex Mono',monospace;font-size:11px;padding:3px 8px;border-radius:4px;background:rgba(88,166,255,.15);color:var(--blue);border:1px solid rgba(88,166,255,.3);}
.source-bar{padding:5px 18px;font-size:11px;color:var(--dim);font-family:'IBM Plex Mono',monospace;border-bottom:1px solid var(--border);background:rgba(0,0,0,.2);}
table{width:100%;border-collapse:collapse;font-size:13px;}
th{font-family:'IBM Plex Mono',monospace;font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--dim);padding:9px 14px;text-align:left;background:rgba(0,0,0,.2);border-bottom:1px solid var(--border);}
td{padding:9px 14px;border-bottom:1px solid rgba(48,54,61,.5);vertical-align:top;line-height:1.5;}
tr:last-child td{border-bottom:none;}
.empresa{font-weight:600;}
.contrato-title{font-size:11px;color:var(--dim);margin-top:3px;}
.importe{font-family:'IBM Plex Mono',monospace;font-size:13px;color:var(--green);white-space:nowrap;font-weight:600;}
.importe.noloc{color:var(--dim);font-style:italic;font-weight:normal;}
.directivo{color:var(--blue);}
.cargo{color:var(--dim);font-size:11px;}
a.link{color:var(--blue);font-size:11px;}
a.borm-link{color:#e0a0ff;font-size:11px;}
.empty{text-align:center;padding:50px;color:var(--dim);font-family:'IBM Plex Mono',monospace;font-size:13px;}
.estado-badge{font-family:'IBM Plex Mono',monospace;font-size:10px;padding:2px 7px;border-radius:3px;}
.est-ADJ,.est-RES{background:rgba(63,185,80,.15);color:var(--green);}
.est-FOR{background:rgba(88,166,255,.15);color:var(--blue);}
.lid{font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--dim);}
.fuente-badge{font-family:'IBM Plex Mono',monospace;font-size:9px;padding:1px 5px;border-radius:3px;vertical-align:middle;margin-left:4px;}
.fuente-place{background:rgba(88,166,255,.15);color:var(--blue);border:1px solid rgba(88,166,255,.3);}
.fuente-borm{background:rgba(224,160,255,.15);color:#e0a0ff;border:1px solid rgba(224,160,255,.3);}
</style>
"""

SPINNER_CSS = """
<style>
.sp-wrap{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:70vh;gap:24px;}
.sp-ring{width:56px;height:56px;border:3px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .8s linear infinite;}
@keyframes spin{to{transform:rotate(360deg)}}
.sp-label{font-family:'IBM Plex Mono',monospace;font-size:13px;color:var(--dim);text-align:center;line-height:2;}
.sp-label strong{color:var(--accent);}
.sp-log{font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--dim);max-width:600px;width:100%;background:rgba(0,0,0,.3);border:1px solid var(--border);border-radius:6px;padding:12px 16px;max-height:220px;overflow-y:auto;line-height:1.8;}
.err-box{background:rgba(248,81,73,.1);border:1px solid var(--red);border-radius:8px;padding:20px 28px;text-align:center;font-family:'IBM Plex Mono',monospace;font-size:13px;color:var(--red);display:none;max-width:500px;}
.err-box a{color:var(--blue);display:block;margin-top:12px;}
</style>
"""

# Contenido CSS puro (sin tags <style>) para servir como archivo estático con caché
_ALL_CSS_CONTENT = re.sub(r'</?style[^>]*>', '', CSS + SPINNER_CSS).strip() + """
.pagination{padding:12px 18px;border-top:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;font-size:12px;flex-wrap:wrap;gap:8px;}
.pag-info{font-family:'IBM Plex Mono',monospace;color:var(--dim);}
.pag-links{display:flex;gap:6px;}
.pag-btn{padding:5px 12px;background:rgba(88,166,255,.1);border:1px solid rgba(88,166,255,.3);border-radius:4px;color:var(--blue);text-decoration:none;font-size:12px;}
.pag-btn:hover{background:rgba(88,166,255,.2);}
.pag-more{padding:10px 18px;border-top:1px solid var(--border);font-size:12px;}
.pag-more a{color:var(--blue);}
.back-link{font-size:12px;color:var(--dim);margin-bottom:12px;display:block;}
.back-link a{color:var(--blue);}
"""


def spinner_page(job_id, municipio):
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Buscando — {esc(municipio)}</title>
<link rel="stylesheet" href="/static/style.css"></head>
<body>
<header>
  <div class="logo">DINERO&nbsp;PÚBLICO</div>
  <div><h1>Contratos Públicos · Región de Murcia</h1>
  <p>Datos oficiales: PLACE (Ministerio de Hacienda) + BORM (Boletín Oficial Región de Murcia)</p></div>
</header>
<div class="main">
  <div class="sp-wrap">
    <div class="sp-ring" id="ring"></div>
    <div class="sp-label">Analizando contratos de <strong>{esc(municipio)}</strong><br>
    Descargando datos de PLACE (Ministerio de Hacienda) y BORM…</div>
    <div class="sp-log" id="log">Iniciando…</div>
    <div class="err-box" id="err"><span id="errmsg"></span><a href="/">← Volver</a></div>
  </div>
</div>
<script>
const JOB="{job_id}";
const logEl=document.getElementById("log");
async function poll(){{
  try{{
    const r=await fetch("/api/job/"+JOB);
    const d=await r.json();
    if(d.log&&d.log.length)logEl.innerHTML=d.log.map(l=>`<div>${{l}}</div>`).join("");
    logEl.scrollTop=logEl.scrollHeight;
    if(d.status==="done"){{window.location.href="/";return;}}
    if(d.status==="error"){{
      document.getElementById("ring").style.display="none";
      document.getElementById("errmsg").textContent="Error: "+(d.error||"desconocido");
      document.getElementById("err").style.display="block";
      return;
    }}
    setTimeout(poll,1200);
  }}catch(e){{setTimeout(poll,2500);}}
}}
poll();
</script></body></html>"""


def _render_alertas(alertas):
    if not alertas:
        return ""
    html_parts = ['<div class="alertas">']
    for a in alertas:
        nivel = esc(a.get("nivel", "info"))
        icono = a.get("icono", "ℹ️")
        texto = a.get("texto", "")
        html_parts.append(
            f'<div class="alerta {nivel}">'
            f'<span class="alerta-ico">{icono}</span>'
            f'<div><div class="alerta-titulo">Indicador de riesgo</div>{texto}</div>'
            f'</div>'
        )
    html_parts.append('</div>')
    return "\n".join(html_parts)


def render_html(datos, muni_filter="", page=1):
    if muni_filter:
        datos = [d for d in datos if normalizar(d.get("municipio", "")) == normalizar(muni_filter)]

    total_m = len(datos)
    total_c = sum(d.get("total_contratos", 0) for d in datos)
    total_e = len(set(
        normalizar(c.get("empresa", ""))
        for d in datos for c in d.get("contratos", [])
        if c.get("empresa") not in ("No localizada", "")
    ))
    total_imp = sum(
        c.get("importe_num", 0.0)
        for d in datos for c in d.get("contratos", [])
    )

    stats = ""
    if datos:
        stats = f"""<div class="stats-bar">
          <div class="stat"><span>{total_m}</span>Municipios</div>
          <div class="stat"><span>{total_c}</span>Contratos</div>
          <div class="stat"><span>{total_e}</span>Empresas únicas</div>
          <div class="stat"><span>{fmt_eur(str(total_imp))}</span>Importe total</div>
        </div>"""

    back_html = (f'<span class="back-link"><a href="/">← Ver todos los municipios</a></span>'
                 if muni_filter else "")

    cards = ""
    for d in datos:
        alertas_html = _render_alertas(d.get("alertas", []))

        muni_name_d = d.get("municipio", "")
        contratos_all = d.get("contratos", [])
        total_muni = len(contratos_all)
        is_paged = bool(muni_filter) and normalizar(muni_name_d) == normalizar(muni_filter)
        if is_paged:
            start = (page - 1) * PAGE_SIZE
            contratos_shown = contratos_all[start:start + PAGE_SIZE]
        else:
            contratos_shown = contratos_all[:PAGE_SIZE]
        total_pages = max(1, (total_muni + PAGE_SIZE - 1) // PAGE_SIZE)

        filas = ""
        for c in contratos_shown:
            imp = c.get("importe", "") or "No localizado"
            imp_cls = "importe" if imp != "No localizado" else "importe noloc"
            dir_html = (
                f'<div class="directivo">{esc(c.get("directivo",""))}</div>'
                f'<div class="cargo">{esc(c.get("cargo",""))}</div>'
                if c.get("directivo") else
                '<span style="color:var(--dim);font-size:11px;font-style:italic">No localizado</span>'
            )
            est = c.get("estado", "")
            est_label = {"ADJ": "Adjudicado", "RES": "Resuelto", "FOR": "Formalizado"}.get(est, est)
            url = c.get("url", "")
            fuente = c.get("fuente", "PLACE")
            fuente_label = c.get("fuente_label", fuente)

            # Enlace directo al anuncio original (PLACE o BORM)
            if fuente == "BORM":
                borm_html_url = c.get("borm_html_url", "")
                html_link = (f' <a class="link borm-link" href="{esc(borm_html_url)}" target="_blank" '
                             f'title="Ver HTML en BORM">HTML ↗</a>') if borm_html_url else ""
                link_html = (f'<a class="link borm-link" href="{esc(url)}" target="_blank" '
                             f'title="Ver PDF en BORM">BORM PDF ↗</a>{html_link}')
            elif url:
                link_html = f'<a class="link" href="{esc(url)}" target="_blank" title="Ficha en PLACE">PLACE ↗</a>'
            else:
                link_html = ""

            # Si es contrato PLACE que además tiene enlace en BORM
            borm_url = c.get("borm_url", "")
            borm_extra = f' <a class="link borm-link" href="{esc(borm_url)}" target="_blank" title="Ver publicación BORM">BORM ↗</a>' if borm_url else ""

            lid = c.get("licitacion_id", "")
            lid_html = f'<div class="lid">Licit. {esc(lid)}</div>' if lid else ""

            fuente_badge = (
                f'<span class="fuente-badge fuente-borm">BORM</span>'
                if fuente == "BORM" else
                f'<span class="fuente-badge fuente-place">PLACE</span>'
            )

            filas += f"""<tr>
              <td>
                <div class="empresa">{esc(c.get('empresa', '—'))} {fuente_badge}</div>
                <div class="contrato-title">{esc(c.get('titulo', '')[:110])}</div>
                {lid_html}
              </td>
              <td class="{imp_cls}">{esc(imp)}</td>
              <td>{dir_html}</td>
              <td>
                <span class="estado-badge est-{esc(est)}">{esc(est_label)}</span>
                <div style="margin-top:4px">{link_html}{borm_extra}</div>
              </td>
            </tr>"""

        if not filas:
            filas = '<tr><td colspan="4" class="empty">Sin contratos adjudicados encontrados en PLACE ni BORM para este municipio</td></tr>'

        n_place = sum(1 for c in contratos_all if c.get("fuente", "PLACE") == "PLACE")
        n_borm  = sum(1 for c in contratos_all if c.get("fuente") == "BORM")
        fuentes_desc = []
        if n_place: fuentes_desc.append(f"PLACE: {n_place}")
        if n_borm:  fuentes_desc.append(f"BORM: {n_borm}")
        fuentes_str = " · ".join(fuentes_desc) if fuentes_desc else "—"

        muni_name     = muni_name_d
        muni_enc      = quote_plus(muni_name)
        profile_url   = d.get("place_profile", place_profile_url(muni_name))
        age_str       = _cache_age_str(muni_name)
        ts            = d.get("timestamp", 0)
        if not age_str and ts:
            mins = int((time.time() - ts) / 60)
            age_str = (f"hace {mins} min" if mins < 60
                       else f"hace {mins//60}h {mins%60}min")
        age_html = f'<span style="font-size:11px;color:var(--dim);font-family:\'IBM Plex Mono\',monospace"> · datos {esc(age_str)}</span>' if age_str else ""

        # Paginación
        pag_html = ""
        if total_muni > PAGE_SIZE:
            if is_paged:
                prev_link = (f'<a href="/?muni={muni_enc}&pag={page-1}" class="pag-btn">← Anterior</a>'
                             if page > 1 else '')
                next_link = (f'<a href="/?muni={muni_enc}&pag={page+1}" class="pag-btn">Siguiente →</a>'
                             if page < total_pages else '')
                pag_html = (f'<div class="pagination">'
                            f'<span class="pag-info">Página {page} de {total_pages} · {total_muni} contratos</span>'
                            f'<div class="pag-links">{prev_link}{next_link}</div>'
                            f'</div>')
            else:
                pag_html = (f'<div class="pag-more">Mostrando los primeros {PAGE_SIZE} de {total_muni} contratos. '
                            f'<a href="/?muni={muni_enc}&pag=1">Ver todos →</a></div>')

        cards += f"""<div class="muni-card">
          <div class="muni-header">
            <h2>🏛 {esc(muni_name)}</h2>
            <div style="display:flex;gap:8px;align-items:center;">
              <a href="{esc(profile_url)}" target="_blank" class="link" title="Perfil contratante en PLACE" style="font-size:11px">Perfil PLACE ↗</a>
              <form method="POST" action="/actualizar" style="display:inline">
                <input type="hidden" name="municipio" value="{esc(muni_name)}">
                <button type="submit" class="btn" style="padding:3px 10px;font-size:11px;background:rgba(88,166,255,.15);color:var(--blue);border:1px solid rgba(88,166,255,.3);">↻ Actualizar</button>
              </form>
              <span class="badge">{d.get('total_contratos', 0)} contratos</span>
            </div>
          </div>
          <div class="source-bar">Fuentes: PLACE (Ministerio de Hacienda) + BORM (Región de Murcia) · {fuentes_str}{age_html}</div>
          {alertas_html}
          <table>
            <tr>
              <th>Empresa adjudicataria / Contrato</th>
              <th>Importe</th>
              <th>Directivo / Cargo</th>
              <th>Estado / Fuente</th>
            </tr>
            {filas}
          </table>
          {pag_html}
        </div>"""

    if not cards:
        cards = '<div class="empty">Busca un municipio de la Región de Murcia para empezar.<br><small>Fuentes: PLACE (Ministerio de Hacienda) y BORM (Boletín Oficial de la Región de Murcia).</small></div>'

    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Contratos Públicos — Murcia</title>
<link rel="stylesheet" href="/static/style.css"></head>
<body>
<header>
  <div class="logo">DINERO&nbsp;PÚBLICO</div>
  <div>
    <h1>Contratos Públicos · Región de Murcia</h1>
    <p>Datos oficiales: PLACE (Ministerio de Hacienda) + BORM (Boletín Oficial Región de Murcia)</p>
  </div>
</header>
<div class="main">
  {back_html}
  <div class="search-bar">
    <label>Municipio</label>
    <form method="POST" action="/buscar" style="display:flex;gap:10px;flex:1;flex-wrap:wrap;align-items:center;">
      <input name="municipio" placeholder="Ej: Lorca, Murcia, Cartagena, Archena…" required>
      <button type="submit" class="btn btn-primary">Buscar contratos</button>
    </form>
    <form method="POST" action="/vaciar"><button type="submit" class="btn btn-danger">Vaciar</button></form>
  </div>
  {stats}
  {cards}
</div></body></html>"""


# ─── SERVIDOR HTTP ───────────────────────────────────────────────────────────

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        if parsed.path == "/":
            with _datos_lock:
                datos_snap = list(_datos_memoria)
            muni_filter = qs.get("muni", [""])[0].strip()
            try:
                page = max(1, int(qs.get("pag", ["1"])[0]))
            except ValueError:
                page = 1
            self._html(render_html(datos_snap, muni_filter=muni_filter, page=page))
        elif parsed.path == "/static/style.css":
            self._static_css()
        elif parsed.path.startswith("/api/job/"):
            job_id = parsed.path[len("/api/job/"):]
            with _jobs_lock:
                job = dict(_jobs.get(job_id, {}))
            self._json(job if job else {"status": "not_found"}, 200 if job else 404)
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            params = parse_qs(body, keep_blank_values=True)

            if self.path == "/buscar":
                municipio = params.get("municipio", [""])[0].strip()
                force     = params.get("force", [""])[0] == "1"
                mun_ok = municipio_valido(municipio)
                if not mun_ok:
                    self._error("Municipio no válido o no pertenece a la Región de Murcia.", 400)
                    return
                # Servir desde caché si los datos son recientes (salvo si fuerza actualización)
                if not force:
                    cached = _cache_get(mun_ok)
                    if cached is None:
                        # Intentar restaurar desde memoria (TTL igual)
                        with _datos_lock:
                            datos_disco = list(_datos_memoria)
                        for d in datos_disco:
                            if normalizar(d.get("municipio","")) == normalizar(mun_ok):
                                ts = d.get("timestamp", 0)
                                if (time.time() - ts) < RESULT_CACHE_TTL:
                                    _cache_set(mun_ok, d)
                                    cached = d
                                break
                    if cached:
                        self._redirect("/")
                        return
                else:
                    _cache_invalidate(mun_ok)
                job_id = str(uuid.uuid4())
                with _jobs_lock:
                    _jobs[job_id] = {"status": "running", "log": [], "error": None}
                threading.Thread(target=_job_run, args=(job_id, mun_ok), daemon=True).start()
                self._html(spinner_page(job_id, mun_ok))
                return

            if self.path == "/vaciar":
                with _datos_lock:
                    _datos_memoria.clear()
                    with open(DATA_FILE, "w", encoding="utf-8") as f:
                        json.dump([], f)
                with _cache_lock:
                    _result_cache.clear()
                self._redirect("/")
                return

            if self.path == "/actualizar":
                municipio = params.get("municipio", [""])[0].strip()
                mun_ok = municipio_valido(municipio)
                if not mun_ok:
                    self._redirect("/")
                    return
                _cache_invalidate(mun_ok)
                job_id = str(uuid.uuid4())
                with _jobs_lock:
                    _jobs[job_id] = {"status": "running", "log": [], "error": None}
                threading.Thread(target=_job_run, args=(job_id, mun_ok), daemon=True).start()
                self._html(spinner_page(job_id, mun_ok))
                return

            self.send_response(404); self.end_headers()
        except Exception as e:
            self._error(f"Error: {e}", 500)

    def _html(self, content, code=200):
        b = content.encode("utf-8")
        accept = self.headers.get("Accept-Encoding", "")
        use_gzip = "gzip" in accept
        if use_gzip:
            b = _gzip.compress(b, compresslevel=6)
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        if use_gzip:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        self.wfile.write(b)

    def _json(self, data, code=200):
        b = json.dumps(data, ensure_ascii=False).encode("utf-8")
        accept = self.headers.get("Accept-Encoding", "")
        use_gzip = "gzip" in accept
        if use_gzip:
            b = _gzip.compress(b, compresslevel=6)
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        if use_gzip:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        self.wfile.write(b)

    def _static_css(self):
        b = _ALL_CSS_CONTENT.encode("utf-8")
        accept = self.headers.get("Accept-Encoding", "")
        use_gzip = "gzip" in accept
        if use_gzip:
            b = _gzip.compress(b, compresslevel=9)
        self.send_response(200)
        self.send_header("Content-Type", "text/css; charset=utf-8")
        self.send_header("Cache-Control", "public, max-age=86400")
        self.send_header("Content-Length", str(len(b)))
        if use_gzip:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        self.wfile.write(b)

    def _redirect(self, path):
        self.send_response(303)
        self.send_header("Location", path)
        self.end_headers()

    def _error(self, msg, code=500):
        self._html(
            f"<html><body style='font-family:sans-serif;padding:40px;background:#0d1117;color:#c9d1d9'>"
            f"<h2>{esc(msg)}</h2><a href='/' style='color:#58a6ff'>← Volver</a></body></html>",
            code,
        )


if __name__ == "__main__":
    print("=" * 55)
    print("  DINERO PÚBLICO — CONTRATOS REGIÓN DE MURCIA")
    print("  Fuente: PLACE (Ministerio de Hacienda)")
    print("=" * 55)
    print(f"  Caché ZIPs: {CACHE_DIR}")
    print(f"  Servidor:   http://127.0.0.1:8000")
    print("=" * 55)
    _inicializar_datos()
    _lanzar_enriquecimiento()   # enriquecer sociedades ya guardadas sin directivo
    srv = ThreadedHTTPServer(("127.0.0.1", 8000), Handler)
    srv.serve_forever()
