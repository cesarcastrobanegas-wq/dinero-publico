"""
Contratos Públicos - Murcia
Fuente: Plataforma de Contratación del Sector Público (datos oficiales CODICE/Atom)
"""

import gzip as _gzip
import json, os, re, html, io, sqlite3, zipfile, threading, uuid, time
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

# ─── EJECUCIÓN HTTP ──────────────────────────────────────────────────────────
HTTP_TIMEOUT = 5            # timeout para feeds PLACE/BORM (peticiones rápidas)
DIRECTIVOS_TIMEOUT = 15    # timeout para búsquedas de directivos (páginas empresia/BOE más lentas)
HTTP_POOL = ThreadPoolExecutor(max_workers=10)   # pool compartido para todas las peticiones HTTP

_datos_lock = threading.Lock()
_datos_memoria: list = []    # datos.json cargado en RAM al arrancar
_jobs: dict = {}
_jobs_lock = threading.Lock()
_enriqueciendo_lock = threading.Lock()  # evita lanzar dos hilos de enriquecimiento a la vez
_actualizando_todos_lock = threading.Lock()  # evita lanzar dos refrescos completos a la vez

PAGE_SIZE = 50               # contratos máximos por página

# ─── CACHÉ DE RESULTADOS ──────────────────────────────────────────────────────
_result_cache: dict = {}   # normalizar(municipio) → {"ts": float, "resultado": dict}
_cache_lock   = threading.Lock()
RESULT_CACHE_TTL = 6 * 3600   # 6 horas

# ─── CACHÉ SQLITE (directivos + contratos por municipio) ─────────────────────
DB_FILE = os.path.join(BASE_DIR, "cache.db")
DIRECTOR_CACHE_FILE = os.path.join(BASE_DIR, "director_cache.json")   # solo para migración inicial

_db = sqlite3.connect(DB_FILE, check_same_thread=False, timeout=30)
_db.execute("PRAGMA journal_mode=WAL")
_db_lock = threading.Lock()

DIR_CACHE_POS_TTL = 90 * 24 * 3600   # 90 días para resultados encontrados
DIR_CACHE_NEG_TTL =  7 * 24 * 3600   # 7 días para "no encontrado"

DIR_INTENTOS_MAX = 3  # tras estos intentos fallidos, se marca "sin datos registrales públicos" y se deja de reintentar

def _db_init():
    with _db_lock:
        _db.execute("""CREATE TABLE IF NOT EXISTS directores (
            clave  TEXT PRIMARY KEY,
            nombre TEXT,
            cargo  TEXT,
            ts     REAL NOT NULL
        )""")
        _db.execute("""CREATE TABLE IF NOT EXISTS municipios (
            municipio TEXT PRIMARY KEY,
            data      TEXT NOT NULL,
            ts        REAL NOT NULL
        )""")
        try:
            _db.execute("ALTER TABLE directores ADD COLUMN intentos INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # ya existe (migración ya aplicada en un arranque anterior)
        _db.commit()
    _migrar_json_a_sqlite()


def _migrar_json_a_sqlite():
    """Importa datos.json / director_cache.json (versiones antiguas) si la BD está vacía."""
    with _db_lock:
        n_muni = _db.execute("SELECT COUNT(*) FROM municipios").fetchone()[0]
        n_dir  = _db.execute("SELECT COUNT(*) FROM directores").fetchone()[0]

    if n_muni == 0 and os.path.exists(DATA_FILE):
        for d in _cargar_datos_json():
            muni = d.get("municipio", "")
            if muni:
                _db_set_municipio(muni, d)

    if n_dir == 0 and os.path.exists(DIRECTOR_CACHE_FILE):
        try:
            with open(DIRECTOR_CACHE_FILE, encoding="utf-8") as f:
                old = json.load(f)
            with _db_lock:
                for k, v in old.items():
                    if not v.get("nombre"):
                        continue  # no migrar negativos: las nuevas fuentes pueden encontrarlos
                    _db.execute(
                        "INSERT OR IGNORE INTO directores (clave, nombre, cargo, ts) VALUES (?,?,?,?)",
                        (k, v.get("nombre", ""), v.get("cargo", ""), v.get("ts", time.time())),
                    )
                _db.commit()
        except Exception:
            pass


def _cargar_datos_json():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, list):
                    return d
        except Exception:
            pass
    return []


def _db_set_municipio(municipio, resultado):
    key = normalizar(municipio)
    with _db_lock:
        _db.execute(
            "INSERT INTO municipios (municipio, data, ts) VALUES (?,?,?) "
            "ON CONFLICT(municipio) DO UPDATE SET data=excluded.data, ts=excluded.ts",
            (key, json.dumps(resultado, ensure_ascii=False), resultado.get("timestamp", time.time())),
        )
        _db.commit()


def _db_all_municipios():
    with _db_lock:
        rows = _db.execute("SELECT data FROM municipios").fetchall()
    out = []
    for (data,) in rows:
        try:
            out.append(json.loads(data))
        except Exception:
            pass
    return out


def _db_clear_municipios():
    with _db_lock:
        _db.execute("DELETE FROM municipios")
        _db.commit()


# ─── CACHÉ DE DIRECTIVOS (persistente, SQLite) ────────────────────────────────

def _dir_cache_key(empresa, nif=""):
    return nif.upper().strip() if nif else normalizar(empresa)

def _dir_cache_get(empresa, nif=""):
    """Devuelve (nombre, cargo) si hay hit válido; (None, None) si hay que buscar."""
    key = _dir_cache_key(empresa, nif)
    with _db_lock:
        row = _db.execute("SELECT nombre, cargo, ts FROM directores WHERE clave=?", (key,)).fetchone()
    if not row:
        return None, None
    nombre, cargo, ts = row
    ttl = DIR_CACHE_POS_TTL if nombre else DIR_CACHE_NEG_TTL
    if time.time() - ts > ttl:
        return None, None
    return nombre or "", cargo or ""

def _dir_cache_agotado(empresa, nif=""):
    """True si ya se agotaron los reintentos automáticos para esta empresa
    (DIR_INTENTOS_MAX intentos fallidos): se considera sin datos registrales públicos."""
    key = _dir_cache_key(empresa, nif)
    with _db_lock:
        row = _db.execute(
            "SELECT intentos FROM directores WHERE clave=? AND (nombre IS NULL OR nombre='')", (key,)
        ).fetchone()
    return bool(row) and (row[0] or 0) >= DIR_INTENTOS_MAX


def _dir_cache_set(empresa, nif, nombre, cargo):
    key = _dir_cache_key(empresa, nif)
    with _db_lock:
        if nombre:
            _db.execute(
                "INSERT INTO directores (clave, nombre, cargo, ts, intentos) VALUES (?,?,?,?,0) "
                "ON CONFLICT(clave) DO UPDATE SET nombre=excluded.nombre, cargo=excluded.cargo, "
                "ts=excluded.ts, intentos=0",
                (key, nombre, cargo, time.time()),
            )
        else:
            _db.execute(
                "INSERT INTO directores (clave, nombre, cargo, ts, intentos) VALUES (?,?,?,?,1) "
                "ON CONFLICT(clave) DO UPDATE SET nombre=excluded.nombre, cargo=excluded.cargo, "
                "ts=excluded.ts, intentos=directores.intentos+1",
                (key, nombre, cargo, time.time()),
            )
        _db.commit()

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
        r = session.get(PLACE_FEED_LIVE, timeout=HTTP_TIMEOUT)
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
        r = session.post(BORM_BUSCAR_URL, json=payload, timeout=HTTP_TIMEOUT)
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
            r2 = session.get(txt_url, timeout=HTTP_TIMEOUT)
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

    for c in HTTP_POOL.map(_fetch_y_parsear, candidatos):
        if c:
            contratos.append(c)

    _log(job_id, f"  BORM: {len(contratos)} contratos con datos extraídos")
    return contratos


# ─── DIRECTIVOS (empresia/BORME via BOE) ────────────────────────────────────

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

_CARGOS_SKIP = re.compile(r"\b(auditor|liquidador|comisario|verificador)\b", re.I)

# Prioridad de cargos: índice menor = más relevante
_CARGO_PRIORITY = [
    "administrador único", "administrador unico",
    "administrador solidario", "administrador mancomunado", "administrador",
    "consejero delegado", "director general", "presidente", "gerente",
    "socio director", "apoderado general", "apoderado",
]

_STOPWORDS_NOMBRE = {
    "fuente", "informe", "boletin", "boletín", "oficial", "registro", "mercantil",
    "sociedad", "consejero", "consejeros", "presidente", "secretario",
    "administrador", "administradores", "gerente", "apoderado", "datos",
    "seguir", "dejar", "avanzado", "axesor", "completa", "básica", "basica",
    "de", "del", "la", "el", "los", "las", "y",
}

_SUFIJOS_SOCIEDAD_NOM = re.compile(
    r'\b(s\.?l\.?u?\.?|s\.?a\.?u?\.?|s\.?c\.?|s\.?coop\.?|s\.?r\.?l\.?)\s*$', re.I
)

def _limpiar_nombre(raw):
    """Recorta una captura a las 2-4 primeras palabras válidas. Acepta mayúsculas BORME."""
    # Rechazar si el raw completo parece ser una empresa (termina en SL, SA, etc.)
    if _SUFIJOS_SOCIEDAD_NOM.search(raw.strip()):
        return ""
    out = []
    for w in raw.split():
        clean = re.sub(r"[^A-Za-záéíóúñÁÉÍÓÚÑ]", "", w)
        if not clean or len(clean) < 2:
            break
        if not (clean[0].isupper() or clean.isupper()):
            break
        if clean.lower() in _STOPWORDS_NOMBRE:
            break
        # Si la palabra acumulada hasta aquí es un sufijo de sociedad, parar
        if _SUFIJOS_SOCIEDAD_NOM.search(clean):
            break
        out.append(clean)
        if len(out) >= 4:
            break
    return " ".join(out)

def _extraer_directivo(texto):
    best_n, best_c, best_prio = "", "", 999
    for m in _CARGO_RE.finditer(texto):
        cargo_raw, raw = m.group(1).strip(), m.group(2).strip()
        if _CARGOS_SKIP.search(cargo_raw):
            continue
        nombre = _limpiar_nombre(raw)
        if len(nombre.split()) < 2:
            continue
        cargo_norm = normalizar(cargo_raw)
        prio = next((i for i, p in enumerate(_CARGO_PRIORITY) if p in cargo_norm), 500)
        if prio < best_prio:
            best_n, best_c, best_prio = nombre.title(), cargo_raw.title(), prio
    return best_n, best_c

_BORME_NOM_RE = re.compile(
    r"nombramiento[s]?\s*[.:]\s*"
    r"(administrador(?:\s+(?:[úu]nico|solidario|mancomunado))?|"
    r"adm\.?\s*(?:[úu]nico|unico|solid(?:\.|ario)?|mancom(?:\.|unado)?)?\.?|"
    r"consejero\s+delegado|cons\.?\s*del\.?|"
    r"presidente|pres\.?|"
    r"gerente|ger\.?|"
    r"director\s+general|"
    r"apoderado(?:\s+(?:solidario|mancomunado|general))?|"
    r"apo\.?\s*(?:sol(?:\.|idario)?|mancom(?:\.|unado)?|gen(?:\.|eral)?)?\.?)\s*[.:]?\s+"
    r"([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñÁÉÍÓÚÑ]+(?:\s+[A-Za-záéíóúñÁÉÍÓÚÑ]+){1,5})",
    re.IGNORECASE,
)

_CARGO_ABREV = [
    (re.compile(r"^adm\.?\s*[úu]nico\.?$", re.I), "Administrador Único"),
    (re.compile(r"^adm\.?\s*solid(?:\.|ario)?\.?$", re.I), "Administrador Solidario"),
    (re.compile(r"^adm\.?\s*mancom(?:\.|unado)?\.?$", re.I), "Administrador Mancomunado"),
    (re.compile(r"^adm\.?$", re.I), "Administrador"),
    (re.compile(r"^apo\.?\s*sol(?:\.|idario)?\.?$", re.I), "Apoderado Solidario"),
    (re.compile(r"^apo\.?\s*mancom(?:\.|unado)?\.?$", re.I), "Apoderado Mancomunado"),
    (re.compile(r"^apo\.?\s*gen(?:\.|eral)?\.?$", re.I), "Apoderado General"),
    (re.compile(r"^apo\.?$", re.I), "Apoderado"),
    (re.compile(r"^pres\.?$", re.I), "Presidente"),
    (re.compile(r"^ger\.?$", re.I), "Gerente"),
    (re.compile(r"^cons\.?\s*del\.?$", re.I), "Consejero Delegado"),
]

def _normalizar_cargo_borme(cargo_raw):
    """Expande abreviaturas de BORME (Adm. Unico, Apo.Sol., …) a su forma completa."""
    c = cargo_raw.strip()
    for rx, full in _CARGO_ABREV:
        if rx.match(c):
            return full
    return cargo_raw

def _extraer_directivo_nombramiento(texto):
    """Extrae el administrador de texto BORME priorizando sección Nombramientos."""
    if not texto:
        return "", ""
    nom_idx = texto.lower().find("nombramiento")
    candidato = texto[nom_idx:] if nom_idx >= 0 else texto
    best_n, best_c, best_prio = "", "", 999
    for m in _BORME_NOM_RE.finditer(candidato):
        cargo, nombre = m.group(1).strip(), m.group(2).strip()
        cargo = _normalizar_cargo_borme(cargo)
        if _CARGOS_SKIP.search(cargo):
            continue
        nombre_clean = _limpiar_nombre(nombre)
        if len(nombre_clean.split()) < 2:
            continue
        cargo_norm = normalizar(cargo)
        prio = next((i for i, p in enumerate(_CARGO_PRIORITY) if p in cargo_norm), 500)
        if prio < best_prio:
            best_n, best_c, best_prio = nombre_clean.title(), cargo.title(), prio
    if best_n:
        return best_n, best_c
    return _extraer_directivo(candidato)


_BORME_REF_RE = re.compile(r'BORME-[A-Z]-\d{4}-\d+-\d+', re.I)

def _fetch_borme_texto(borme_id):
    """Descarga el texto plano de un anuncio BORME directamente desde BOE."""
    try:
        r = session.get(
            f"https://www.boe.es/diario_borme/txt.php?id={borme_id}",
            timeout=DIRECTIVOS_TIMEOUT,
        )
        if r.status_code == 200:
            try:
                return r.content.decode("utf-8")
            except UnicodeDecodeError:
                return r.content.decode("latin-1", errors="replace")
    except Exception:
        pass
    return ""


def _extraer_de_borme_empresa(boe_texto, empresa, sufijos_empresa_re):
    """
    Extrae el director del boletín BORME localizando primero la sección
    de la empresa concreta (los boletines pueden incluir MUCHAS empresas).
    """
    boe_clean = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", boe_texto))
    # Palabras clave del nombre de empresa (sin sufijos legales, min 4 chars)
    palabras = [
        w for w in re.split(r"[\s,\.&\-]+", empresa)
        if len(w) > 3 and not sufijos_empresa_re.match(w)
    ]
    if not palabras:
        return "", ""

    # Buscar la sección de la empresa en el BORME (case-insensitive)
    best_n, best_c, best_prio = "", "", 999
    for p in palabras[:3]:
        idx = boe_clean.lower().find(p.lower())
        if idx < 0:
            continue
        # Contexto: desde 100 chars antes hasta 800 chars después
        context = boe_clean[max(0, idx - 100):idx + 900]
        n, c = _extraer_directivo_nombramiento(context)
        if n:
            cargo_norm = normalizar(c)
            prio = next((i for i, cp in enumerate(_CARGO_PRIORITY) if cp in cargo_norm), 500)
            if prio < best_prio:
                best_n, best_c, best_prio = n, c, prio
        if best_n:
            break  # primera palabra que funciona es suficiente

    return best_n, best_c


_CONECTORES = {"y", "e", "de", "del", "los", "las", "el", "la", "para", "en"}


def buscar_directivo_einforma(empresa, nif=""):
    """Fuente 1: einforma.com (actualmente retorna 404 para la mayoría — solo intento rápido)."""
    if not empresa or empresa == "No localizada":
        return "", ""
    try:
        url = f"https://www.einforma.com/servlet/app/prod/EMPRESA_BUSCADOR_NOMBRE/nombre/{quote_plus(empresa)}"
        r = session.get(url, timeout=DIRECTIVOS_TIMEOUT, allow_redirects=True)
        if r.status_code != 200:
            return "", ""
        soup = BeautifulSoup(r.text, "html.parser")
        primer = (soup.select_one("a[href*='/informe-empresa'], a[href*='/cif/'], a[href*='/empresa/']") or
                  soup.find("a", href=re.compile(r"einforma\.com/\S*empresa\S*", re.I)))
        if not primer:
            return "", ""
        href = primer.get("href", "")
        if not href.startswith("http"):
            href = "https://www.einforma.com" + href
        r2 = session.get(href, timeout=DIRECTIVOS_TIMEOUT)
        if r2.status_code != 200:
            return "", ""
        soup2 = BeautifulSoup(r2.text, "html.parser")
        for sel in ("div.administradores", "section.administradores", "#administradores",
                    "div.cargos", ".empresa-directivos__list"):
            bloque = soup2.select_one(sel)
            if bloque:
                n, c = _extraer_directivo(bloque.get_text(" ", strip=True))
                if n:
                    return n, c
        return _extraer_directivo(soup2.get_text(" ", strip=True))
    except Exception:
        pass
    return "", ""


def buscar_directivo_empresia(empresa, nif=""):
    """
    Fuente 2 (principal): empresia.es → eventos BORME → texto BOE → administrador.

    Estrategia:
      1. Busca la empresa en empresia.es
      2. Recoge links de eventos BORME del resultado de búsqueda y del perfil
      3. Por cada evento extrae la ref BORME-A-YYYY-NNN-PP
      4. Descarga el texto plano del anuncio desde BOE (/diario_borme/txt.php)
      5. Parsea buscando nombramientos de administradores (prioriza Administrador > Apoderado)
    """
    if not empresa or empresa == "No localizada":
        return "", ""
    try:
        r = session.get(
            "https://empresia.es/busqueda/",
            params={"q": empresa},
            timeout=DIRECTIVOS_TIMEOUT,
        )
        if r.status_code != 200:
            return "", ""
        soup = BeautifulSoup(r.text, "html.parser")

        evento_links = []
        perfil_href = None
        seen_ev = set()
        for a in soup.find_all("a", href=re.compile(r"^/empresa/")):
            href = a.get("href", "")
            if "/evento/" in href and href not in seen_ev:
                evento_links.append(href)
                seen_ev.add(href)
            elif perfil_href is None:
                parts = [p for p in href.split("/") if p]
                if len(parts) == 2:
                    perfil_href = href

        # Si pocos eventos en la búsqueda, ir al perfil a buscar más
        if len(evento_links) < 3 and perfil_href:
            try:
                time.sleep(0.4)
                r2 = session.get("https://empresia.es" + perfil_href, timeout=DIRECTIVOS_TIMEOUT)
                if r2.status_code == 200:
                    soup2 = BeautifulSoup(r2.text, "html.parser")
                    for a in soup2.find_all("a", href=re.compile(r"^/empresa/")):
                        href = a.get("href", "")
                        if "/evento/" in href and href not in seen_ev:
                            evento_links.append(href)
                            seen_ev.add(href)
            except Exception:
                pass

        print(f"  [empresia] {empresa[:40]}: {len(evento_links)} eventos", flush=True)

        # Palabras significativas del nombre de empresa para validar el BORME
        _palabras_emp = [
            w for w in re.split(r"[\s,\.&]+", empresa)
            if len(w) > 3 and not _SUFIJOS_EMPRESA.match(w)
        ]

        def _borme_menciona_empresa(boe_text):
            """Verifica que el texto BORME es de la empresa buscada."""
            txt_low = boe_text.lower()
            return any(p.lower() in txt_low for p in _palabras_emp[:2])

        for ev_href in evento_links[:12]:
            try:
                time.sleep(0.3)
                r_ev = session.get("https://empresia.es" + ev_href, timeout=DIRECTIVOS_TIMEOUT)
                if r_ev.status_code != 200:
                    continue
                borme_m = _BORME_REF_RE.search(r_ev.text)
                if not borme_m:
                    continue
                borme_id = borme_m.group(0).upper()
                boe_texto = _fetch_borme_texto(borme_id)
                if boe_texto and _borme_menciona_empresa(boe_texto):
                    # Extraer desde la sección de esta empresa específica en el boletín
                    n, c = _extraer_de_borme_empresa(boe_texto, empresa, _SUFIJOS_EMPRESA)
                    if n:
                        print(f"    OK {borme_id} => {n} [{c}]", flush=True)
                        return n, c
                # Fallback: texto del evento en empresia
                ev_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r_ev.text))
                if _borme_menciona_empresa(ev_text):
                    n, c = _extraer_de_borme_empresa(ev_text, empresa, _SUFIJOS_EMPRESA)
                    if n:
                        print(f"    OK evento empresia => {n} [{c}]", flush=True)
                        return n, c
            except Exception:
                continue

        # Fallback cuando no hay eventos: buscar refs BORME en el HTML del perfil directamente
        if not evento_links and perfil_href:
            try:
                time.sleep(0.4)
                r_perfil = session.get("https://empresia.es" + perfil_href, timeout=DIRECTIVOS_TIMEOUT)
                if r_perfil.status_code == 200:
                    seen_borme = set()
                    for borme_m in _BORME_REF_RE.finditer(r_perfil.text):
                        borme_id = borme_m.group(0).upper()
                        if borme_id in seen_borme:
                            continue
                        seen_borme.add(borme_id)
                        boe_texto = _fetch_borme_texto(borme_id)
                        if not boe_texto or not _borme_menciona_empresa(boe_texto):
                            continue
                        n, c = _extraer_de_borme_empresa(boe_texto, empresa, _SUFIJOS_EMPRESA)
                        if n:
                            print(f"    OK perfil {borme_id} => {n} [{c}]", flush=True)
                            return n, c
            except Exception:
                pass

    except Exception:
        pass
    return "", ""


def buscar_directivo_borme_anuncios(empresa, nif=""):
    """
    Fuente 3 (fallback): busca refs BORME en la página de resultados del BOE
    usando el nombre de empresa sin sufijos legales (SL, SA, SLU…).
    """
    if not empresa or empresa == "No localizada":
        return "", ""
    nombre_sin_sufijo = re.sub(
        r"\s*,?\s*(s\.?l\.?u?\.?|s\.?a\.?u?\.?|s\.?c\.?|s\.?coop\.?)\s*$",
        "", empresa, flags=re.I,
    ).strip().rstrip(".,")
    variantes = [nombre_sin_sufijo]
    if "," in nombre_sin_sufijo:
        variantes.append(nombre_sin_sufijo.split(",")[0].strip())

    for variante in variantes:
        if not variante:
            continue
        try:
            r = session.get(
                "https://www.boe.es/buscar/anborme.php",
                params={"campo[0]": "TITULO", "dato[0]": variante,
                        "operador[0]": "and", "accion": "Buscar"},
                timeout=DIRECTIVOS_TIMEOUT,
            )
            if r.status_code != 200:
                continue
            for borme_m in _BORME_REF_RE.finditer(r.text):
                borme_id = borme_m.group(0).upper()
                boe_texto = _fetch_borme_texto(borme_id)
                if not boe_texto:
                    continue
                n, c = _extraer_de_borme_empresa(boe_texto, empresa, _SUFIJOS_EMPRESA)
                if n:
                    print(f"    OK BORME {borme_id} => {n} [{c}]", flush=True)
                    return n, c
        except Exception:
            pass
    return "", ""


_ddg_bloqueado = False  # circuit-breaker: DuckDuckGo puede exigir captcha si detecta tráfico de bot

def buscar_directivo_web(empresa, nif=""):
    """
    Fuente 4 (último recurso): búsqueda de texto en DuckDuckGo (Google bloquea el
    scraping directo) restringida a portales mercantiles conocidos, extrayendo el
    cargo/nombre del snippet o, si no aparece, de la primera ficha enlazada.
    Se desactiva sola para el resto de la sesión si DDG responde con un captcha.
    """
    global _ddg_bloqueado
    if not empresa or empresa == "No localizada" or _ddg_bloqueado:
        return "", ""
    query = (
        f'"{empresa}" administrador OR gerente OR apoderado OR autónomo '
        f'site:einforma.com OR site:empresia.es OR site:axesor.es OR '
        f'site:empresite.eleconomista.es OR site:infoempresa.com'
    )
    try:
        r = session.get(
            "https://lite.duckduckgo.com/lite/",
            params={"q": query},
            timeout=DIRECTIVOS_TIMEOUT,
        )
        if r.status_code == 202 or "Select all squares" in r.text:
            _ddg_bloqueado = True
            print("  [web] DuckDuckGo pide captcha — fuente desactivada para esta sesión.", flush=True)
            return "", ""
        if r.status_code != 200:
            return "", ""
        n, c = _extraer_directivo(_extraer_texto(r.text))
        if n:
            return n, c

        soup = BeautifulSoup(r.text, "html.parser")
        vistos = set()
        for a in soup.find_all("a", href=re.compile(
                r"(einforma|empresia|axesor|empresite\.eleconomista|infoempresa)\.[a-z]+", re.I)):
            href = a.get("href", "")
            if not href.startswith("http") or href in vistos:
                continue
            vistos.add(href)
            try:
                time.sleep(0.3)
                r2 = session.get(href, timeout=DIRECTIVOS_TIMEOUT)
                if r2.status_code == 200:
                    n, c = _extraer_directivo(_extraer_texto(r2.text))
                    if n:
                        return n, c
            except Exception:
                continue
            if len(vistos) >= 3:
                break
    except Exception:
        pass
    return "", ""


def buscar_directivo(empresa, nif=""):
    """Busca directivo: persona física → einforma → empresia → BORME anuncios → búsqueda web. Usa caché persistente."""
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

    nombre, cargo = "", ""
    for fuente in (buscar_directivo_einforma, buscar_directivo_empresia,
                   buscar_directivo_borme_anuncios, buscar_directivo_web):
        try:
            nombre, cargo = fuente(empresa, nif)
        except Exception:
            nombre, cargo = "", ""
        if nombre:
            break

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

    # Empresa sin nombre (posible opacidad) — indicador de riesgo prominente
    sin_empresa = sum(1 for c in contratos if c.get("empresa") == "No localizada")
    if sin_empresa > 0:
        pct = round(100 * sin_empresa / total)
        alertas.append({
            "nivel": "opacidad",
            "icono": "🚩",
            "texto": (
                f"<b>{sin_empresa} contrato{'s' if sin_empresa != 1 else ''}</b> "
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
            borm_fut = HTTP_POOL.submit(buscar_en_borm, municipio, job_id)
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
                 f"(einforma · empresia · BORME)…")
        directivos = {}
        futs = {HTTP_POOL.submit(buscar_directivo, emp, nif): emp
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
                if not c["directivo"] and _dir_cache_agotado(emp, c.get("nif", "")):
                    c["rm_agotado"] = True
                    c["intentado"] = True

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
        _db_set_municipio(municipio, resultado)

        with _jobs_lock:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["total"] = len(contratos)

        # Enriquecer en fondo las sociedades que aún no tienen directivo
        _lanzar_enriquecimiento()

    except Exception as e:
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(e)


def _actualizar_todos_bg(job_id):
    """
    Hilo de fondo: refresca secuencialmente los 45 municipios de la Región de
    Murcia (invalida caché + relanza _job_run para cada uno, con una pausa
    entre municipios para no saturar PLACE/BORM). Pensado para dispararse
    desde un disparador externo (cron) vía POST /actualizar-todos.

    Mientras corre, la web sigue sirviendo los datos anteriores con
    normalidad: _job_run solo sustituye la entrada de _datos_memoria del
    municipio que esté procesando en ese momento, bajo _datos_lock, así que
    nunca hay un estado a medias visible para quien esté navegando.
    """
    if not _actualizando_todos_lock.acquire(blocking=False):
        with _jobs_lock:
            _jobs[job_id] = {"status": "error", "log": [],
                              "error": "Ya hay un refresco completo en curso."}
        return

    try:
        with _jobs_lock:
            _jobs[job_id] = {"status": "running", "log": [], "error": None,
                              "total_municipios": len(MUNICIPIOS_MURCIA), "procesados": 0}
        print(f"  [actualizar-todos] Iniciando refresco de {len(MUNICIPIOS_MURCIA)} municipios…", flush=True)

        for idx, municipio in enumerate(MUNICIPIOS_MURCIA, 1):
            print(f"  [actualizar-todos] [{idx}/{len(MUNICIPIOS_MURCIA)}] {municipio}", flush=True)
            sub_job_id = f"{job_id}-{idx}"
            with _jobs_lock:
                _jobs[sub_job_id] = {"status": "running", "log": [], "error": None}
            try:
                _cache_invalidate(municipio)
                _job_run(sub_job_id, municipio)
            except Exception as e:
                print(f"  [actualizar-todos] Error en {municipio}: {e}", flush=True)
            finally:
                with _jobs_lock:
                    _jobs.pop(sub_job_id, None)
                    if job_id in _jobs:
                        _jobs[job_id]["procesados"] = idx
            time.sleep(4)  # pausa entre municipios

        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id]["status"] = "done"
        print("  [actualizar-todos] Refresco completo terminado.", flush=True)

    finally:
        _actualizando_todos_lock.release()


def _inicializar_datos():
    """Carga municipios y directivos cacheados desde SQLite en RAM al arrancar."""
    _db_init()
    cargados = _db_all_municipios()
    with _datos_lock:
        _datos_memoria[:] = cargados
    for d in cargados:
        muni = d.get("municipio", "")
        ts = d.get("timestamp", 0)
        if muni and (time.time() - ts) < RESULT_CACHE_TTL:
            _cache_set(muni, d)


# ─── ENRIQUECIMIENTO EN BACKGROUND (empresia / BORME) ────────────────────────

def _contrato_key(c):
    """Clave estable para identificar un contrato independientemente de su posición en memoria."""
    return (c.get("empresa", ""), c.get("url", ""), c.get("titulo", "")[:60])


def _guardar_datos_sin_lock():
    """Persiste _datos_memoria en SQLite. Llamar solo desde dentro de _datos_lock."""
    for d in _datos_memoria:
        muni = d.get("municipio", "")
        if muni:
            _db_set_municipio(muni, d)


def _limpiar_cache_negativos():
    """Elimina del caché SQLite las entradas negativas que aún no agotaron sus
    reintentos, para forzar re-búsqueda. Las que ya llegaron a DIR_INTENTOS_MAX
    se dejan (se consideran "sin datos registrales públicos" y no se reintentan)."""
    with _db_lock:
        deleted = _db.execute(
            "DELETE FROM directores WHERE (nombre = '' OR nombre IS NULL) AND intentos < ?",
            (DIR_INTENTOS_MAX,),
        ).rowcount
        _db.commit()
    if deleted:
        print(f"  [enriquecimiento] {deleted} entradas negativas eliminadas del caché.", flush=True)


def _enriquecer_directivos_bg():
    """
    Hilo de fondo: para cada empresa o autónomo sin directivo,
    busca via einforma → empresia.es → BORME → BOE → búsqueda web y guarda el resultado.
    """
    if not _enriqueciendo_lock.acquire(blocking=False):
        return  # ya hay otro hilo de enriquecimiento en marcha

    try:
        time.sleep(6)  # dejar que el servidor arranque del todo

        # Limpiar caché negativo y flags "intentado" para re-buscar con la nueva estrategia
        # (las empresas que ya agotaron DIR_INTENTOS_MAX no se tocan: se consideran
        # "sin datos registrales públicos" y no se vuelven a intentar automáticamente)
        _limpiar_cache_negativos()
        with _datos_lock:
            for d in _datos_memoria:
                for c in d.get("contratos", []):
                    if not c.get("directivo") and c.get("intentado"):
                        if _dir_cache_agotado(c.get("empresa", ""), c.get("nif", "")):
                            c["rm_agotado"] = True
                        else:
                            c.pop("intentado", None)

        # Recopilar contratos pendientes: (municipio, key, empresa, nif)
        pendientes = []
        with _datos_lock:
            for d in _datos_memoria:
                for c in d.get("contratos", []):
                    empresa_c = c.get("empresa", "")
                    if not empresa_c or empresa_c == "No localizada" or c.get("directivo") or c.get("intentado"):
                        continue
                    if _dir_cache_agotado(empresa_c, c.get("nif", "")):
                        c["rm_agotado"] = True
                        c["intentado"] = True
                        continue
                    pendientes.append((
                        d.get("municipio", ""),
                        _contrato_key(c),
                        empresa_c,
                        c.get("nif", ""),
                    ))

        if not pendientes:
            print("  [enriquecimiento] Sin empresas pendientes.", flush=True)
            return

        print(f"  [enriquecimiento] {len(pendientes)} empresas pendientes.", flush=True)
        encontrados = 0
        cambios = 0
        for idx, (municipio, key, empresa, nif) in enumerate(pendientes, 1):
            print(f"  [{idx}/{len(pendientes)}] {empresa} (NIF:{nif})", flush=True)
            cached_n, cached_c = _dir_cache_get(empresa, nif)
            if cached_n is not None:
                nombre, cargo = cached_n, cached_c
                print(f"    caché: {nombre!r}", flush=True)
            else:
                nombre, cargo = buscar_directivo(empresa, nif)

            if nombre:
                encontrados += 1
            else:
                print(f"    No localizado.", flush=True)

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
                if cambios % 10 == 0:
                    _guardar_datos_sin_lock()

            time.sleep(1.2)  # delay entre peticiones

        print(f"  [enriquecimiento] Fin: {encontrados}/{len(pendientes)} directivos encontrados.", flush=True)
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
html{overflow-x:hidden;}
body{font-family:'IBM Plex Sans',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;padding-bottom:60px;overflow-x:hidden;}
header{background:var(--surface);border-bottom:1px solid var(--border);padding:16px 28px;display:flex;align-items:center;gap:14px;position:sticky;top:0;z-index:10;}
header a{display:flex;align-items:center;gap:14px;min-width:0;flex:1;}
header a>div{min-width:0;}
header h1{overflow-wrap:break-word;}
.logo-svg{flex-shrink:0;line-height:0;}
.logo-svg svg{width:160px;height:auto;display:block;}
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

/* ── banner publicitario ─────────────────────────────────────────────── */
.ad-banner{max-width:728px;min-height:90px;margin:0 auto 22px;background:var(--surface);border:1px dashed var(--border);border-radius:6px;display:flex;align-items:center;justify-content:center;font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--dim);letter-spacing:.5px;text-align:center;padding:8px;}

/* ── landing ──────────────────────────────────────────────────────────── */
.hero{text-align:center;padding:38px 20px 8px;}
.hero-tagline{font-size:20px;color:var(--text);font-weight:600;}
.hero-sub{color:var(--dim);margin-top:10px;font-size:13px;max-width:640px;margin-left:auto;margin-right:auto;}
.global-search{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:20px 22px;margin:22px 0;}
.global-search .gs-row{display:flex;gap:10px;flex-wrap:wrap;align-items:center;}
.global-search input{background:var(--bg);border:1px solid var(--border);color:var(--text);font-family:'IBM Plex Mono',monospace;font-size:14px;padding:10px 14px;border-radius:6px;flex:1;min-width:220px;outline:none;}
.global-search input:focus{border-color:var(--blue);}
.global-search .gs-hint{font-size:11px;color:var(--dim);margin-top:8px;}

/* ── buscador avanzado (3 modos, AJAX) ───────────────────────────────── */
.adv-search{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:20px 22px;margin:22px 0;width:100%;}
.as-tabs{display:flex;gap:6px;margin-bottom:14px;flex-wrap:wrap;}
.as-tab{font-family:'IBM Plex Mono',monospace;font-size:12px;padding:7px 16px;border-radius:6px;border:1px solid var(--border);background:var(--bg);color:var(--dim);cursor:pointer;font-weight:600;}
.as-tab.active{background:rgba(240,136,62,.15);color:var(--accent);border-color:rgba(240,136,62,.4);}
.as-row{display:flex;gap:10px;flex-wrap:wrap;align-items:center;width:100%;}
.as-row input{background:var(--bg);border:1px solid var(--border);color:var(--text);font-family:'IBM Plex Mono',monospace;font-size:14px;padding:12px 16px;border-radius:6px;flex:1;min-width:220px;outline:none;}
.as-row input:focus{border-color:var(--blue);}
.as-row .btn{padding:12px 22px;}
.gs-hint{font-size:11px;color:var(--dim);margin-top:8px;}
#as-results{margin-top:16px;display:flex;flex-direction:column;gap:10px;}
.as-loading{font-family:'IBM Plex Mono',monospace;font-size:12px;color:var(--dim);padding:10px 0;}
.as-total{font-family:'IBM Plex Mono',monospace;font-size:12px;color:var(--accent);padding:4px 0 8px;border-bottom:1px solid var(--border);}
.as-row-result{background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:12px 16px;}
.as-rr-top{display:flex;justify-content:space-between;gap:10px;align-items:baseline;flex-wrap:wrap;}
.as-rr-empresa{font-weight:600;font-size:13px;}
.as-rr-importe{font-family:'IBM Plex Mono',monospace;font-size:13px;color:var(--green);white-space:nowrap;}
.as-rr-importe.big{font-size:15px;color:#5fe37a;font-weight:600;}
.as-rr-sub{font-size:11px;color:var(--dim);margin-top:3px;font-family:'IBM Plex Mono',monospace;}
.as-rr-titulo{font-size:12px;color:var(--text);margin-top:5px;}
.as-rr-directivo{font-size:12px;color:var(--blue);margin-top:4px;}
.as-group{background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:14px 16px;}
.as-group .as-row-result{margin-top:8px;background:var(--surface);}
.section-title{font-size:13px;font-family:'IBM Plex Mono',monospace;text-transform:uppercase;letter-spacing:1.5px;color:var(--dim);margin:26px 0 12px;}
.muni-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px;}
.muni-tile{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:16px 18px;display:flex;flex-direction:column;gap:8px;transition:border-color .15s;}
.muni-tile:hover{border-color:var(--accent);}
.muni-tile h3{font-size:14px;color:var(--accent);}
.muni-tile .mt-row{display:flex;justify-content:space-between;font-size:12px;color:var(--dim);font-family:'IBM Plex Mono',monospace;}
.muni-tile .mt-row b{color:var(--text);font-weight:600;}
.muni-tile .mt-imp{font-family:'IBM Plex Mono',monospace;font-size:15px;color:var(--green);font-weight:600;}
.muni-tile a.btn-ver{margin-top:4px;text-align:center;padding:7px 10px;background:rgba(240,136,62,.12);color:var(--accent);border:1px solid rgba(240,136,62,.35);border-radius:6px;font-size:12px;font-weight:600;text-decoration:none;}
.muni-tile a.btn-ver:hover{background:rgba(240,136,62,.22);}

/* ── footer ───────────────────────────────────────────────────────────── */
.site-footer{max-width:1340px;margin:48px auto 0;padding:22px 20px;border-top:1px solid var(--border);display:flex;flex-wrap:wrap;justify-content:space-between;gap:16px;align-items:center;}
.site-footer .ft-links{display:flex;flex-wrap:wrap;gap:16px;align-items:center;}
.site-footer a{color:var(--dim);font-size:12px;text-decoration:none;}
.site-footer a:hover{color:var(--blue);}
.site-footer .ft-brand{font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--dim);}
.site-footer .ft-sep{color:var(--border);font-size:12px;}
.site-footer .ft-label{color:var(--dim);font-size:12px;}

/* ── páginas estáticas (quiénes somos / aviso legal) ─────────────────── */
.static-page{max-width:820px;margin:0 auto;background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:34px 38px;line-height:1.8;font-size:14px;}
.static-page h1{font-size:22px;color:var(--accent);margin-bottom:18px;}
.static-page h2{font-size:15px;color:var(--text);margin:26px 0 10px;font-family:'IBM Plex Mono',monospace;text-transform:uppercase;letter-spacing:1px;}
.static-page p{margin-bottom:14px;color:var(--text);}
.static-page ul{margin:0 0 14px 22px;}
.static-page li{margin-bottom:6px;}
.static-page a{color:var(--blue);}
.static-page .contact-btn{display:inline-block;margin-top:8px;padding:9px 18px;background:var(--accent);color:#000;border-radius:6px;text-decoration:none;font-weight:600;font-size:13px;}

/* ── mejoras visuales: importes / iconos / avisos ────────────────────── */
.importe.big{font-size:16px;color:#5fe37a;}
.icon-tipo{margin-right:5px;}
.noloc-warn{display:inline-flex;align-items:center;gap:5px;color:var(--yellow);font-size:11px;font-style:italic;}
.noloc-warn a{color:var(--yellow);text-decoration:underline;}
.noloc-nota{display:block;font-size:10px;color:var(--dim);font-style:italic;margin-top:2px;}
.risk-prominent{border-radius:8px;padding:14px 18px;margin-bottom:18px;display:flex;gap:12px;align-items:center;background:rgba(248,81,73,.12);border:2px solid rgba(248,81,73,.5);}
.risk-prominent .rp-ico{font-size:26px;line-height:1;}
.risk-prominent .rp-text{font-size:13px;color:#f8c4c2;line-height:1.5;}
.risk-prominent .rp-text b{color:#fff;}

/* ── responsive ───────────────────────────────────────────────────────── */
@media (max-width:700px){
  header{padding:10px 14px;}
  header h1{font-size:13px;}
  header p{font-size:10px;}
  .logo-svg svg{width:96px;}
  .main{padding:0 12px;margin:18px auto;max-width:100%;}
  .hero{padding:22px 6px 4px;}
  .hero-tagline{font-size:16px;}
  .hero-sub{font-size:12px;}
  .stats-bar{gap:8px;}
  .stat{padding:8px 12px;flex:1 1 40%;}
  .stat span{font-size:16px;}
  .muni-grid{grid-template-columns:1fr 1fr;gap:10px;}
  .muni-tile{padding:12px 14px;}
  .search-bar,.global-search,.adv-search{padding:14px 16px;}
  .search-bar .btn,.search-bar form,.global-search .gs-row,.as-row{width:100%;}
  .global-search input,.search-bar input,.as-row input{min-width:0;width:100%;}
  .as-row .btn{width:100%;}
  .as-tab{flex:1 1 auto;text-align:center;padding:8px 6px;}
  table{font-size:12px;display:block;overflow-x:auto;white-space:nowrap;}
  th,td{padding:7px 8px;}
  .contrato-title{display:none;}
  .site-footer{flex-direction:column;align-items:flex-start;max-width:100%;}
  .site-footer .ft-links{gap:10px 14px;}
  .static-page{padding:22px 18px;}
  .ad-banner{max-width:100%;}
}
@media (max-width:420px){
  .muni-grid{grid-template-columns:1fr;}
}
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
    normales = [a for a in alertas if a.get("nivel") != "opacidad"]
    prominentes = [a for a in alertas if a.get("nivel") == "opacidad"]

    html_parts = []
    for a in prominentes:
        html_parts.append(
            f'<div class="risk-prominent">'
            f'<span class="rp-ico">{a.get("icono","🚩")}</span>'
            f'<div class="rp-text">{a.get("texto","")}</div>'
            f'</div>'
        )
    if normales:
        html_parts.append('<div class="alertas">')
        for a in normales:
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


# ─── PLANTILLA COMÚN (header / footer / banner / SEO) ────────────────────────

SITE_URL = os.environ.get("SITE_URL", "https://dinero-publico.com")
SITE_TAGLINE = "El dinero de todos, en manos de quién"

REGISTRO_MERCANTIL_URL = "https://www.registradores.org/actualidad/portal-notarial/registro-mercantil-en-linea"

LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 500 200" width="220" height="88">
  <defs>
    <filter id="glow">
      <feGaussianBlur stdDeviation="2.5" result="coloredBlur"/>
      <feMerge><feMergeNode in="coloredBlur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="glowStrong">
      <feGaussianBlur stdDeviation="4" result="coloredBlur"/>
      <feMerge><feMergeNode in="coloredBlur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <radialGradient id="eyeGlow" cx="50%" cy="50%" r="50%">
      <stop offset="0%" style="stop-color:#f0883e;stop-opacity:0.3"/>
      <stop offset="100%" style="stop-color:#0d1117;stop-opacity:0"/>
    </radialGradient>
  </defs>
  <rect width="500" height="200" fill="#0d1117"/>
  <text x="8"   y="22" font-family="Arial" font-size="11" fill="#f0883e" opacity="0.25">€</text>
  <text x="24"  y="18" font-family="Arial" font-size="9"  fill="#f0883e" opacity="0.15">€</text>
  <text x="38"  y="25" font-family="Arial" font-size="13" fill="#f0883e" opacity="0.3">€</text>
  <text x="54"  y="16" font-family="Arial" font-size="8"  fill="#f0883e" opacity="0.2">€</text>
  <text x="66"  y="24" font-family="Arial" font-size="11" fill="#f0883e" opacity="0.18">€</text>
  <text x="82"  y="19" font-family="Arial" font-size="10" fill="#f0883e" opacity="0.12">€</text>
  <text x="96"  y="26" font-family="Arial" font-size="9"  fill="#f0883e" opacity="0.08">€</text>
  <text x="6"   y="42" font-family="Arial" font-size="10" fill="#f0883e" opacity="0.3">€</text>
  <text x="20"  y="48" font-family="Arial" font-size="14" fill="#f0883e" opacity="0.2">€</text>
  <text x="36"  y="40" font-family="Arial" font-size="9"  fill="#f0883e" opacity="0.25">€</text>
  <text x="50"  y="46" font-family="Arial" font-size="11" fill="#f0883e" opacity="0.15">€</text>
  <text x="64"  y="38" font-family="Arial" font-size="8"  fill="#f0883e" opacity="0.1">€</text>
  <text x="4"   y="66" font-family="Arial" font-size="12" fill="#f0883e" opacity="0.35">€</text>
  <text x="18"  y="70" font-family="Arial" font-size="9"  fill="#f0883e" opacity="0.22">€</text>
  <text x="32"  y="63" font-family="Arial" font-size="11" fill="#f0883e" opacity="0.28">€</text>
  <text x="5"   y="90" font-family="Arial" font-size="11" fill="#f0883e" opacity="0.4">€</text>
  <text x="19"  y="94" font-family="Arial" font-size="14" fill="#f0883e" opacity="0.25">€</text>
  <text x="4"   y="115" font-family="Arial" font-size="10" fill="#f0883e" opacity="0.4">€</text>
  <text x="18"  y="119" font-family="Arial" font-size="13" fill="#f0883e" opacity="0.22">€</text>
  <text x="5"   y="140" font-family="Arial" font-size="11" fill="#f0883e" opacity="0.35">€</text>
  <text x="6"   y="164" font-family="Arial" font-size="12" fill="#f0883e" opacity="0.3">€</text>
  <text x="7"   y="186" font-family="Arial" font-size="11" fill="#f0883e" opacity="0.25">€</text>
  <circle cx="100" cy="100" r="55" fill="url(#eyeGlow)"/>
  <path d="M 45 100 Q 100 55 155 100" fill="#0d1117" stroke="#f0883e" stroke-width="2.5"/>
  <path d="M 45 100 Q 100 140 155 100" fill="#0d1117" stroke="#f0883e" stroke-width="2.5"/>
  <line x1="70"  y1="72"  x2="73"  y2="80"  stroke="#f0883e" stroke-width="1.5" opacity="0.6"/>
  <line x1="85"  y1="62"  x2="86"  y2="71"  stroke="#f0883e" stroke-width="1.5" opacity="0.6"/>
  <line x1="100" y1="58"  x2="100" y2="67"  stroke="#f0883e" stroke-width="2"   opacity="0.7"/>
  <line x1="115" y1="62"  x2="114" y2="71"  stroke="#f0883e" stroke-width="1.5" opacity="0.6"/>
  <line x1="130" y1="72"  x2="127" y2="80"  stroke="#f0883e" stroke-width="1.5" opacity="0.6"/>
  <circle cx="100" cy="100" r="28" fill="#1a0a00" stroke="#f0883e" stroke-width="2" filter="url(#glow)"/>
  <circle cx="100" cy="100" r="22" fill="none" stroke="#f0883e" stroke-width="0.8" opacity="0.4"/>
  <circle cx="100" cy="100" r="11" fill="#f0883e" filter="url(#glowStrong)"/>
  <circle cx="100" cy="100" r="7" fill="#0d1117"/>
  <circle cx="106" cy="94" r="3.5" fill="#ffffff" opacity="0.55"/>
  <line x1="168" y1="15" x2="168" y2="185" stroke="#f0883e" stroke-width="1" opacity="0.35"/>
  <text x="188" y="88" font-family="'IBM Plex Mono','Courier New',monospace" font-size="50" font-weight="700" letter-spacing="2" fill="#f0883e" filter="url(#glow)">DINERO</text>
  <text x="188" y="138" font-family="'IBM Plex Mono','Courier New',monospace" font-size="50" font-weight="700" letter-spacing="2" fill="#ffffff">PÚBLICO</text>
  <text x="190" y="164" font-family="'IBM Plex Mono','Courier New',monospace" font-size="10" letter-spacing="3" fill="#8b949e">¿EN QUÉ SE GASTA TU DINERO?</text>
</svg>"""

_ADV_SEARCH_JS = r"""
(function(){
  var PLACEHOLDERS = {
    empresa: 'Nombre de la empresa…',
    directivo: 'Nombre del directivo o empresario…',
    licitacion: 'Número de licitación (ej: 321/2026)…'
  };
  var tabs = document.querySelectorAll('#adv-search .as-tab');
  var input = document.getElementById('as-input');
  var btn = document.getElementById('as-btn');
  var results = document.getElementById('as-results');
  if (!input || !results) return;
  var tipo = 'empresa';
  var timer = null;
  var seq = 0;

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }

  function setTipo(t) {
    tipo = t;
    tabs.forEach(function(tb){ tb.classList.toggle('active', tb.dataset.tipo === t); });
    input.placeholder = PLACEHOLDERS[t] || '';
    results.innerHTML = '';
    input.focus();
  }
  tabs.forEach(function(tb){ tb.addEventListener('click', function(){ setTipo(tb.dataset.tipo); }); });

  function filaContrato(c) {
    var row = el('div', 'as-row-result');
    var top = el('div', 'as-rr-top');
    var emp = el('span', 'as-rr-empresa', c.empresa || '—');
    top.appendChild(emp);
    var imp = el('span', 'as-rr-importe', c.importe);
    if ((c.importe_num || 0) > 100000) imp.classList.add('big');
    top.appendChild(imp);
    row.appendChild(top);
    var sub = el('div', 'as-rr-sub');
    sub.appendChild(el('span', null, '📍 ' + c.municipio + ' · ' + c.estado));
    row.appendChild(sub);
    var titulo = el('div', 'as-rr-titulo', c.titulo);
    row.appendChild(titulo);
    if (c.directivo) {
      row.appendChild(el('div', 'as-rr-directivo', c.directivo + (c.cargo ? ' — ' + c.cargo : '')));
    }
    if (c.url) {
      var a = document.createElement('a');
      a.href = c.url; a.target = '_blank'; a.rel = 'noopener'; a.className = 'link';
      a.textContent = 'PLACE ↗';
      row.appendChild(a);
    }
    return row;
  }

  function renderEmpresa(data) {
    results.innerHTML = '';
    if (!data.resultados || !data.resultados.length) {
      results.appendChild(el('div', 'empty', 'Sin resultados.'));
      return;
    }
    var head = el('div', 'as-total', data.total_contratos + ' contratos · total acumulado ' + data.total_importe);
    results.appendChild(head);
    data.resultados.forEach(function(c){ results.appendChild(filaContrato(c)); });
  }

  function renderDirectivo(data) {
    results.innerHTML = '';
    if (!data.grupos || !data.grupos.length) {
      results.appendChild(el('div', 'empty', 'Sin resultados.'));
      return;
    }
    var head = el('div', 'as-total', data.n_empresas + ' empresa(s) vinculada(s) · total global ' + data.total_importe);
    results.appendChild(head);
    data.grupos.forEach(function(g){
      var card = el('div', 'as-group');
      var top = el('div', 'as-rr-top');
      top.appendChild(el('span', 'as-rr-empresa', g.empresa));
      top.appendChild(el('span', 'as-rr-importe big', g.total_importe));
      card.appendChild(top);
      card.appendChild(el('div', 'as-rr-sub', (g.cargo || 'Directivo') + ' · ' + g.n_contratos + ' contrato(s)'));
      g.contratos.forEach(function(c){ card.appendChild(filaContrato(c)); });
      results.appendChild(card);
    });
  }

  function renderLicitacion(data) {
    results.innerHTML = '';
    if (!data.encontrado) {
      results.appendChild(el('div', 'empty', 'No se ha encontrado ninguna licitación con ese número.'));
      return;
    }
    results.appendChild(filaContrato(data.contrato));
  }

  function buscar() {
    var q = input.value.trim();
    if (q.length < 2) { results.innerHTML = ''; return; }
    var mySeq = ++seq;
    results.innerHTML = '';
    results.appendChild(el('div', 'as-loading', 'Buscando…'));
    fetch('/api/buscar?tipo=' + encodeURIComponent(tipo) + '&q=' + encodeURIComponent(q))
      .then(function(r){ return r.json(); })
      .then(function(data){
        if (mySeq !== seq) return; // respuesta obsoleta, ya se lanzó otra búsqueda
        if (data.error) { results.innerHTML = ''; results.appendChild(el('div', 'empty', data.error)); return; }
        if (tipo === 'empresa') renderEmpresa(data);
        else if (tipo === 'directivo') renderDirectivo(data);
        else renderLicitacion(data);
      })
      .catch(function(){
        if (mySeq !== seq) return;
        results.innerHTML = '';
        results.appendChild(el('div', 'empty', 'Error al buscar. Inténtalo de nuevo.'));
      });
  }

  input.addEventListener('input', function(){
    clearTimeout(timer);
    timer = setTimeout(buscar, 300);
  });
  input.addEventListener('keydown', function(e){
    if (e.key === 'Enter') { e.preventDefault(); clearTimeout(timer); buscar(); }
  });
  btn.addEventListener('click', function(){ clearTimeout(timer); buscar(); });
})();
"""

_ICONOS_TIPO = [
    (re.compile(r"\bobra|construcci[oó]n|rehabilitaci[oó]n|edificaci[oó]n", re.I), "🏗️"),
    (re.compile(r"\blimpieza|residuos|jardiner[ií]a|mantenimiento", re.I), "🧹"),
    (re.compile(r"\bsuministro|material|equipamiento|veh[ií]culo", re.I), "📦"),
    (re.compile(r"\bconsultor[ií]a|asisten|asesor|direcci[oó]n facultativa", re.I), "📋"),
    (re.compile(r"\bseguridad|vigilancia|polic[ií]a", re.I), "🛡️"),
    (re.compile(r"\benerg[ií]a|el[eé]ctric", re.I), "⚡"),
    (re.compile(r"\binform[aá]tic|software|digital|web|tecnolog", re.I), "💻"),
    (re.compile(r"\bcultura|festival|espect[aá]culo|deporte|fiestas", re.I), "🎭"),
    (re.compile(r"\bsanidad|salud|social|dependenc", re.I), "🏥"),
    (re.compile(r"\beducaci[oó]n|escuela|centro docente", re.I), "🎓"),
]

def _icono_contrato(titulo):
    for rx, ico in _ICONOS_TIPO:
        if rx.search(titulo or ""):
            return ico
    return "📄"


def _ad_banner_html():
    return ('<div class="ad-banner" id="ad-banner">'
            'Espacio publicitario — contacto@dinero-publico.com'
            '</div>')


def _header_html():
    return f"""<header>
  <a href="/" style="text-decoration:none;display:flex;align-items:center;gap:14px;">
    <div class="logo-svg">{LOGO_SVG}</div>
    <div>
      <h1 style="color:var(--text)">Contratos Públicos · Región de Murcia</h1>
      <p>{esc(SITE_TAGLINE)}</p>
    </div>
  </a>
</header>"""


def _footer_html():
    return f"""<footer class="site-footer">
  <div class="ft-brand">© Dinero Público — datos oficiales públicos, Región de Murcia</div>
  <div class="ft-links">
    <a href="https://contrataciondelsectorpublico.gob.es/" target="_blank" rel="noopener">PLACE</a>
    <a href="https://www.borm.es/" target="_blank" rel="noopener">BORM</a>
    <a href="https://www.boe.es/" target="_blank" rel="noopener">BOE</a>
    <a href="{esc(REGISTRO_MERCANTIL_URL)}" target="_blank" rel="noopener">Registro Mercantil</a>
    <a href="/aviso-legal">Aviso Legal</a>
    <a href="/quienes-somos">Quiénes Somos</a>
    <span class="ft-sep">|</span>
    <span class="ft-label">Enlaces de interés:</span>
    <a href="https://civio.es" target="_blank" rel="noopener">CIVIO</a>
    <a href="https://transparencia.org.es" target="_blank" rel="noopener">Transparency International España</a>
    <a href="https://www.hayderecho.com" target="_blank" rel="noopener">Fundación Hay Derecho</a>
    <a href="https://www.datadista.com" target="_blank" rel="noopener">Datadista</a>
  </div>
</footer>"""


def _page_shell(title, body_html, description="", extra_head=""):
    full_title = title if "|" in title else f"{title} | Dinero Público"
    desc = esc(description or "Consulta los contratos públicos de los 45 municipios de la "
                               "Región de Murcia con los directivos de las empresas adjudicatarias. "
                               "Datos oficiales PLACE + Registro Mercantil.")
    return f"""<!DOCTYPE html>
<html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(full_title)}</title>
<meta name="description" content="{desc}">
<meta name="robots" content="index, follow">
<link rel="canonical" href="{esc(SITE_URL)}/">
<link rel="icon" type="image/svg+xml" href="/static/logo.svg">
<meta property="og:type" content="website">
<meta property="og:title" content="{esc(full_title)}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{esc(SITE_URL)}/">
<meta property="og:site_name" content="Dinero Público">
<meta property="og:locale" content="es_ES">
<meta property="og:image" content="{esc(SITE_URL)}/static/logo.svg">
<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{esc(full_title)}">
<meta name="twitter:description" content="{desc}">
<meta name="twitter:image" content="{esc(SITE_URL)}/static/logo.svg">
<link rel="stylesheet" href="/static/style.css">
{extra_head}</head>
<body>
{_header_html()}
<div class="main">
{_ad_banner_html()}
{body_html}
</div>
{_footer_html()}
</body></html>"""


def _render_fila_contrato(c, municipio_label=None):
    """Genera la fila <tr> de un contrato. Reutilizada por la vista de
    municipio y por los resultados de búsqueda global."""
    imp = c.get("importe", "") or "No localizado"
    imp_cls = "importe" if imp != "No localizado" else "importe noloc"
    try:
        if c.get("importe_num", 0) and float(c.get("importe_num", 0)) > 100000:
            imp_cls += " big"
    except (TypeError, ValueError):
        pass

    directivo = c.get("directivo", "")
    if directivo:
        dir_html = (f'<div class="directivo">{esc(directivo)}</div>'
                     f'<div class="cargo">{esc(c.get("cargo",""))}</div>')
    else:
        empresa_q = quote_plus(c.get("empresa", ""))
        rm_link = (f'<a href="{esc(REGISTRO_MERCANTIL_URL)}" target="_blank" rel="noopener" '
                   f'title="Buscar {esc(c.get("empresa",""))} en el Registro Mercantil">'
                   f'Registro Mercantil ↗</a>') if empresa_q else ""
        nota = ('<span class="noloc-nota">Empresa sin datos registrales públicos</span>'
                if c.get("rm_agotado") else "")
        dir_html = (f'<span class="noloc-warn">⚠️ No localizado {rm_link}</span>{nota}')

    est = c.get("estado", "")
    est_label = {"ADJ": "Adjudicado", "RES": "Resuelto", "FOR": "Formalizado"}.get(est, est)
    url = c.get("url", "")
    fuente = c.get("fuente", "PLACE")

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

    borm_url = c.get("borm_url", "")
    borm_extra = (f' <a class="link borm-link" href="{esc(borm_url)}" target="_blank" '
                  f'title="Ver publicación BORM">BORM ↗</a>') if borm_url else ""

    lid = c.get("licitacion_id", "")
    lid_html = f'<div class="lid">Licit. {esc(lid)}</div>' if lid else ""

    fuente_badge = (
        f'<span class="fuente-badge fuente-borm">BORM</span>' if fuente == "BORM" else
        f'<span class="fuente-badge fuente-place">PLACE</span>'
    )

    muni_html = (f'<div class="lid" style="margin-top:2px">📍 {esc(municipio_label)}</div>'
                 if municipio_label else "")

    titulo = c.get("titulo", "")
    icono = _icono_contrato(titulo)

    return f"""<tr>
      <td>
        <div class="empresa">{esc(c.get('empresa', '—'))} {fuente_badge}</div>
        <div class="contrato-title"><span class="icon-tipo">{icono}</span>{esc(titulo[:110])}</div>
        {lid_html}{muni_html}
      </td>
      <td class="{imp_cls}">{esc(imp)}</td>
      <td>{dir_html}</td>
      <td>
        <span class="estado-badge est-{esc(est)}">{esc(est_label)}</span>
        <div style="margin-top:4px">{link_html}{borm_extra}</div>
      </td>
    </tr>"""


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

    back_html = '<span class="back-link"><a href="/">← Ver todos los municipios</a></span>'

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

        filas = "".join(_render_fila_contrato(c) for c in contratos_shown)

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
        cards = '<div class="empty">Municipio no encontrado.</div>'

    body = f"""{back_html}
  <div class="search-bar">
    <label>Municipio</label>
    <form method="POST" action="/buscar" style="display:flex;gap:10px;flex:1;flex-wrap:wrap;align-items:center;">
      <input name="municipio" placeholder="Ej: Lorca, Murcia, Cartagena, Archena…" required>
      <button type="submit" class="btn btn-primary">Buscar contratos</button>
    </form>
  </div>
  {stats}
  {cards}"""

    muni_display = datos[0].get("municipio", "") if datos else muni_filter
    titulo = f"Contratos públicos de {muni_display}" if muni_display else "Contratos Públicos"
    descripcion = (f"Contratos públicos adjudicados en {muni_display} (Región de Murcia): "
                   f"empresa adjudicataria, importe y directivo/administrador. "
                   f"Datos oficiales PLACE + Registro Mercantil.") if muni_display else ""
    return _page_shell(titulo, body, description=descripcion)


def render_landing_html(datos):
    """Página de inicio: no carga ningún municipio, muestra stats globales,
    buscador global y el grid de los 45 municipios."""
    por_muni = {normalizar(d.get("municipio", "")): d for d in datos}

    total_m = len(datos)
    total_c = sum(d.get("total_contratos", 0) for d in datos)
    total_e = len(set(
        normalizar(c.get("empresa", ""))
        for d in datos for c in d.get("contratos", [])
        if c.get("empresa") not in ("No localizada", "")
    ))
    total_imp = sum(c.get("importe_num", 0.0) for d in datos for c in d.get("contratos", []))

    stats = f"""<div class="stats-bar">
      <div class="stat"><span>{total_m}</span>Municipios</div>
      <div class="stat"><span>{total_c}</span>Contratos</div>
      <div class="stat"><span>{total_e}</span>Empresas únicas</div>
      <div class="stat"><span>{fmt_eur(str(total_imp))}</span>Importe total</div>
    </div>"""

    tiles = ""
    for muni in sorted(MUNICIPIOS_MURCIA, key=lambda m: normalizar(m)):
        d = por_muni.get(normalizar(muni))
        n = d.get("total_contratos", 0) if d else 0
        imp = sum(c.get("importe_num", 0.0) for c in d.get("contratos", [])) if d else 0.0
        muni_enc = quote_plus(muni)
        tiles += f"""<div class="muni-tile">
          <h3>🏛 {esc(muni)}</h3>
          <div class="mt-row"><span>Contratos</span><b>{n}</b></div>
          <div class="mt-imp">{fmt_eur(str(imp))}</div>
          <a class="btn-ver" href="/?muni={muni_enc}">Ver contratos →</a>
        </div>"""

    body = f"""<div class="hero">
    <div class="hero-tagline">{esc(SITE_TAGLINE)}</div>
    <p class="hero-sub">
      Contratos públicos de los 45 municipios de la Región de Murcia, cruzados con el
      Registro Mercantil para saber qué empresa — y qué persona — hay detrás de cada adjudicación.
    </p>
  </div>
  <div class="adv-search" id="adv-search">
    <div class="as-tabs">
      <button type="button" class="as-tab active" data-tipo="empresa">Empresa</button>
      <button type="button" class="as-tab" data-tipo="directivo">Directivo</button>
      <button type="button" class="as-tab" data-tipo="licitacion">Licitación</button>
    </div>
    <div class="as-row">
      <input type="text" id="as-input" placeholder="Nombre de la empresa…" autocomplete="off" autofocus>
      <button type="button" id="as-btn" class="btn btn-primary">Buscar</button>
    </div>
    <div class="gs-hint">Busca en los {total_c} contratos ya cargados de toda la región · mínimo 2 caracteres.</div>
    <div id="as-results"></div>
  </div>
  {stats}
  <div class="section-title">Municipios · Región de Murcia</div>
  <div class="muni-grid">{tiles}</div>
  <div class="search-bar" style="margin-top:24px">
    <label>¿No aparece o quieres forzar una actualización?</label>
    <form method="POST" action="/buscar" style="display:flex;gap:10px;flex:1;flex-wrap:wrap;align-items:center;">
      <input name="municipio" placeholder="Nombre exacto del municipio…" required>
      <button type="submit" class="btn btn-primary">Actualizar</button>
    </form>
  </div>
  <script>{_ADV_SEARCH_JS}</script>"""

    return _page_shell("Dinero Público | Contratos públicos Región de Murcia", body,
                        description="Consulta los contratos públicos de los 45 municipios de la "
                                     "Región de Murcia con los directivos de las empresas "
                                     "adjudicatarias. Datos oficiales PLACE + Registro Mercantil.")


def _contrato_json(c, municipio):
    """Representación JSON de un contrato para el buscador avanzado (/api/buscar)."""
    return {
        "municipio": municipio,
        "empresa": c.get("empresa", ""),
        "titulo": c.get("titulo", ""),
        "importe": c.get("importe", "") or "No localizado",
        "importe_num": c.get("importe_num", 0.0) or 0.0,
        "estado": {"ADJ": "Adjudicado", "RES": "Resuelto", "FOR": "Formalizado"}.get(c.get("estado", ""), c.get("estado", "")),
        "directivo": c.get("directivo", ""),
        "cargo": c.get("cargo", ""),
        "url": c.get("url", ""),
        "licitacion_id": c.get("licitacion_id", ""),
    }


def api_buscar(tipo, q, datos):
    """Backend del buscador avanzado (GET /api/buscar?tipo=...&q=...). Devuelve
    un dict JSON-serializable; ninguna búsqueda distingue mayúsculas ni acentos."""
    q = (q or "").strip()
    if len(q) < 2:
        return {"tipo": tipo, "query": q, "error": "Escribe al menos 2 caracteres."}

    q_norm = normalizar(q)

    if tipo == "empresa":
        resultados = []
        for d in datos:
            muni = d.get("municipio", "")
            for c in d.get("contratos", []):
                if q_norm in normalizar(c.get("empresa", "")):
                    resultados.append(_contrato_json(c, muni))
        resultados.sort(key=lambda r: r["importe_num"], reverse=True)
        total = sum(r["importe_num"] for r in resultados)
        return {
            "tipo": "empresa", "query": q,
            "resultados": resultados[:500],
            "total_contratos": len(resultados),
            "total_importe": fmt_eur(str(total)),
        }

    if tipo == "directivo":
        grupos = {}  # empresa -> {cargo, contratos:[], total}
        for d in datos:
            muni = d.get("municipio", "")
            for c in d.get("contratos", []):
                directivo = c.get("directivo", "")
                if directivo and q_norm in normalizar(directivo):
                    emp = c.get("empresa", "")
                    g = grupos.setdefault(emp, {"empresa": emp, "directivo": directivo,
                                                 "cargo": c.get("cargo", ""), "contratos": [], "total": 0.0})
                    g["contratos"].append(_contrato_json(c, muni))
                    g["total"] += c.get("importe_num", 0.0) or 0.0
        lista = sorted(grupos.values(), key=lambda g: g["total"], reverse=True)
        for g in lista:
            g["contratos"].sort(key=lambda r: r["importe_num"], reverse=True)
            g["total_importe"] = fmt_eur(str(g["total"]))
            g["n_contratos"] = len(g["contratos"])
        total_global = sum(g["total"] for g in lista)
        return {
            "tipo": "directivo", "query": q,
            "grupos": lista[:200],
            "n_empresas": len(lista),
            "total_importe": fmt_eur(str(total_global)),
        }

    if tipo == "licitacion":
        q_low = q.strip().lower()
        for d in datos:
            muni = d.get("municipio", "")
            for c in d.get("contratos", []):
                lid = (c.get("licitacion_id") or "").lower()
                if lid and q_low in lid:
                    return {"tipo": "licitacion", "query": q, "encontrado": True,
                            "contrato": _contrato_json(c, muni)}
        return {"tipo": "licitacion", "query": q, "encontrado": False}

    return {"tipo": tipo, "query": q, "error": "Tipo de búsqueda no reconocido."}


def render_busqueda_global_html(datos, q):
    """Resultados de la búsqueda global por empresa, directivo o municipio."""
    q_norm = normalizar(q)
    resultados = []
    for d in datos:
        muni = d.get("municipio", "")
        for c in d.get("contratos", []):
            if (q_norm in normalizar(c.get("empresa", ""))
                    or q_norm in normalizar(c.get("directivo", ""))
                    or q_norm in normalizar(muni)):
                resultados.append((muni, c))

    if resultados:
        filas = "".join(_render_fila_contrato(c, municipio_label=m) for m, c in resultados[:300])
        aviso = (f'<div class="gs-hint" style="margin-bottom:10px">Mostrando los primeros 300 de '
                 f'{len(resultados)} resultados.</div>') if len(resultados) > 300 else ""
        tabla = f"""{aviso}<table>
          <tr>
            <th>Empresa adjudicataria / Contrato</th>
            <th>Importe</th>
            <th>Directivo / Cargo</th>
            <th>Estado / Fuente</th>
          </tr>
          {filas}
        </table>"""
    else:
        tabla = '<div class="empty">Sin resultados para tu búsqueda.</div>'

    body = f"""<span class="back-link"><a href="/">← Volver al inicio</a></span>
  <div class="global-search">
    <form method="GET" action="/" class="gs-row">
      <input name="q" value="{esc(q)}" placeholder="Buscar por empresa, directivo o municipio…" autofocus>
      <button type="submit" class="btn btn-primary">Buscar</button>
    </form>
    <div class="gs-hint">{len(resultados)} resultado{'s' if len(resultados) != 1 else ''} para "{esc(q)}"</div>
  </div>
  <div class="muni-card">{tabla}</div>"""

    return _page_shell(f'Búsqueda: {q}', body, description=f'Resultados de "{q}" en contratos públicos de la Región de Murcia.')


def render_quienes_somos_html():
    body = """<div class="static-page">
  <h1>Transparencia al servicio de la ciudadanía</h1>

  <p>Dinero Público nació con un objetivo claro: hacer accesible a cualquier ciudadano
  la información sobre cómo se gasta el dinero público en la Región de Murcia.</p>

  <p>Cruzamos datos oficiales de la Plataforma de Contratación del Sector Público (PLACE)
  del Ministerio de Hacienda con información registral pública para identificar quién
  está detrás de cada empresa que recibe contratos públicos.</p>

  <p>No somos un partido político. No tenemos agenda ideológica. Creemos que la
  transparencia es la mejor herramienta contra la corrupción, y que los ciudadanos
  tienen derecho a saber quién se beneficia del dinero de todos.</p>

  <p>Todos los datos que mostramos son públicos y oficiales.</p>

  <h2>Para quién</h2>
  <ul>
    <li>📰 Periodistas de investigación</li>
    <li>🏛️ Grupos municipales de oposición</li>
    <li>🤝 ONGs y asociaciones ciudadanas</li>
    <li>👤 Cualquier ciudadano</li>
  </ul>

  <h2>Fuentes de datos</h2>
  <ul>
    <li>PLACE (Ministerio de Hacienda) — contratos públicos</li>
    <li>BORM (Boletín Oficial Región de Murcia) — publicaciones oficiales</li>
    <li>Registro Mercantil — directivos y administradores</li>
    <li>einforma.com, axesor.es, infocif.es — datos empresariales públicos</li>
  </ul>

  <h2>Contacto</h2>
  <a class="contact-btn" href="mailto:cesarcastrobanegas@hotmail.com">✉ cesarcastrobanegas@hotmail.com</a>
</div>"""
    return _page_shell("Quiénes Somos", body,
                        description="Quiénes somos y por qué existe Dinero Público: transparencia sobre "
                                     "la contratación pública en la Región de Murcia.")


def render_aviso_legal_html():
    body = f"""<div class="static-page">
  <h1>Aviso Legal y Privacidad</h1>

  <h2>Titular</h2>
  <p>César Castro Banegas.</p>

  <h2>Dominio</h2>
  <p>{esc(SITE_URL)}</p>

  <h2>Actividad</h2>
  <p>Plataforma de transparencia y datos públicos sobre contratación del sector público
  en la Región de Murcia.</p>

  <h2>Origen de los datos</h2>
  <p>Los datos de contratos mostrados provienen de fuentes oficiales públicas: la
  Plataforma de Contratación del Sector Público (PLACE) del Ministerio de Hacienda y
  el Boletín Oficial de la Región de Murcia (BORM).</p>
  <p>Los nombres de directivos y administradores provienen de registros públicos
  (Registro Mercantil y fuentes empresariales públicas equivalentes).</p>

  <h2>Base legal para el tratamiento de datos</h2>
  <p>El tratamiento de los nombres de personas físicas que aparecen como
  administradores o apoderados de empresas adjudicatarias se ampara en el interés
  público de la información y en que proceden de fuentes accesibles al público
  (art. 9.2.e del Reglamento General de Protección de Datos y Ley Orgánica 3/2018,
  de Protección de Datos Personales y garantía de los derechos digitales — LOPDGDD).</p>

  <h2>Ejercicio de derechos RGPD</h2>
  <p>Para ejercer tus derechos de acceso, rectificación, supresión, oposición o
  limitación del tratamiento, escribe a
  <a href="mailto:cesarcastrobanegas@hotmail.com">cesarcastrobanegas@hotmail.com</a>.</p>

  <h2>Cookies y publicidad</h2>
  <p>Este sitio no utiliza cookies de seguimiento ni publicidad personalizada.</p>

  <h2>Contacto</h2>
  <a class="contact-btn" href="mailto:cesarcastrobanegas@hotmail.com">✉ cesarcastrobanegas@hotmail.com</a>
</div>"""
    return _page_shell("Aviso Legal", body,
                        description="Aviso legal, privacidad y base legal para el tratamiento de datos "
                                     "públicos en Dinero Público.")


# ─── ENRUTADO HTTP (compartido: servidor de desarrollo + WSGI/gunicorn) ──────
#
# Toda la lógica de rutas vive aquí como funciones puras que devuelven
# (código, cabeceras, cuerpo-en-bytes). Tanto el Handler de http.server
# (uso local: `python app.py`) como el callable WSGI `app` (uso en
# producción: `gunicorn backend.app:app`) llaman a estas mismas funciones,
# así que el comportamiento es idéntico en ambos casos.

_HTTP_STATUS_TEXT = {
    200: "OK", 303: "See Other", 400: "Bad Request",
    404: "Not Found", 405: "Method Not Allowed", 500: "Internal Server Error",
}


def _resp(body, content_type="text/html; charset=utf-8", code=200, headers=None, gzip_ok=False):
    b = body.encode("utf-8") if isinstance(body, str) else body
    hdrs = dict(headers or {})
    hdrs["Content-Type"] = content_type
    if gzip_ok:
        b = _gzip.compress(b, compresslevel=6)
        hdrs["Content-Encoding"] = "gzip"
    hdrs["Content-Length"] = str(len(b))
    return code, hdrs, b


def _redirect_resp(path):
    return 303, {"Location": path, "Content-Length": "0"}, b""


def _error_resp(msg, code=500):
    body = (f"<html><body style='font-family:sans-serif;padding:40px;background:#0d1117;color:#c9d1d9'>"
            f"<h2>{esc(msg)}</h2><a href='/' style='color:#58a6ff'>← Volver</a></body></html>")
    return _resp(body, code=code)


def _route_get(path, qs, gzip_ok=False):
    if path == "/":
        with _datos_lock:
            datos_snap = list(_datos_memoria)
        muni_filter = qs.get("muni", [""])[0].strip()
        q = qs.get("q", [""])[0].strip()
        if muni_filter:
            try:
                page = max(1, int(qs.get("pag", ["1"])[0]))
            except ValueError:
                page = 1
            return _resp(render_html(datos_snap, muni_filter=muni_filter, page=page), gzip_ok=gzip_ok)
        if q:
            return _resp(render_busqueda_global_html(datos_snap, q), gzip_ok=gzip_ok)
        return _resp(render_landing_html(datos_snap), gzip_ok=gzip_ok)

    if path == "/quienes-somos":
        return _resp(render_quienes_somos_html(), gzip_ok=gzip_ok)

    if path == "/aviso-legal":
        return _resp(render_aviso_legal_html(), gzip_ok=gzip_ok)

    if path == "/robots.txt":
        body = f"User-agent: *\nAllow: /\n\nSitemap: {SITE_URL}/sitemap.xml\n"
        return _resp(body, content_type="text/plain; charset=utf-8", gzip_ok=gzip_ok)

    if path == "/sitemap.xml":
        with _datos_lock:
            munis = [d.get("municipio", "") for d in _datos_memoria]
        urls = [f"  <url><loc>{esc(SITE_URL)}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>",
                f"  <url><loc>{esc(SITE_URL)}/quienes-somos</loc><changefreq>monthly</changefreq></url>",
                f"  <url><loc>{esc(SITE_URL)}/aviso-legal</loc><changefreq>monthly</changefreq></url>"]
        for m in munis:
            urls.append(f"  <url><loc>{esc(SITE_URL)}/?muni={quote_plus(m)}</loc><changefreq>daily</changefreq></url>")
        body = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                + "\n".join(urls) + "\n</urlset>\n")
        return _resp(body, content_type="application/xml; charset=utf-8", gzip_ok=gzip_ok)

    if path == "/static/style.css":
        return _resp(
            _ALL_CSS_CONTENT, content_type="text/css; charset=utf-8",
            headers={"Cache-Control": "public, max-age=86400"}, gzip_ok=gzip_ok,
        )

    if path == "/static/logo.svg":
        return _resp(
            LOGO_SVG, content_type="image/svg+xml; charset=utf-8",
            headers={"Cache-Control": "public, max-age=86400"}, gzip_ok=gzip_ok,
        )

    if path.startswith("/api/job/"):
        job_id = path[len("/api/job/"):]
        with _jobs_lock:
            job = dict(_jobs.get(job_id, {}))
        code = 200 if job else 404
        body = json.dumps(job if job else {"status": "not_found"}, ensure_ascii=False)
        return _resp(body, content_type="application/json; charset=utf-8", code=code, gzip_ok=gzip_ok)

    if path == "/api/buscar":
        tipo = qs.get("tipo", ["empresa"])[0]
        q = qs.get("q", [""])[0]
        with _datos_lock:
            datos_snap = list(_datos_memoria)
        resultado = api_buscar(tipo, q, datos_snap)
        return _resp(json.dumps(resultado, ensure_ascii=False),
                     content_type="application/json; charset=utf-8", gzip_ok=gzip_ok)

    return 404, {"Content-Length": "0"}, b""


def _route_post(path, params):
    try:
        if path == "/buscar":
            municipio = params.get("municipio", [""])[0].strip()
            force     = params.get("force", [""])[0] == "1"
            mun_ok = municipio_valido(municipio)
            if not mun_ok:
                return _error_resp("Municipio no válido o no pertenece a la Región de Murcia.", 400)
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
                    return _redirect_resp("/")
            else:
                _cache_invalidate(mun_ok)
            job_id = str(uuid.uuid4())
            with _jobs_lock:
                _jobs[job_id] = {"status": "running", "log": [], "error": None}
            threading.Thread(target=_job_run, args=(job_id, mun_ok), daemon=True).start()
            return _resp(spinner_page(job_id, mun_ok))

        if path == "/vaciar":
            # Borra TODOS los contratos ya scrapeados/enriquecidos. Ya no hay botón en
            # la interfaz que apunte aquí, pero el endpoint sigue existiendo y el código
            # es público — se exige ADMIN_TOKEN para evitar que cualquiera lo dispare
            # directamente contra el sitio en producción.
            admin_token = os.environ.get("ADMIN_TOKEN", "")
            if not admin_token or params.get("token", [""])[0] != admin_token:
                return _error_resp("No autorizado.", 403)
            with _datos_lock:
                _datos_memoria.clear()
                _db_clear_municipios()
            with _cache_lock:
                _result_cache.clear()
            return _redirect_resp("/")

        if path == "/actualizar":
            municipio = params.get("municipio", [""])[0].strip()
            mun_ok = municipio_valido(municipio)
            if not mun_ok:
                return _redirect_resp("/")
            _cache_invalidate(mun_ok)
            job_id = str(uuid.uuid4())
            with _jobs_lock:
                _jobs[job_id] = {"status": "running", "log": [], "error": None}
            threading.Thread(target=_job_run, args=(job_id, mun_ok), daemon=True).start()
            return _resp(spinner_page(job_id, mun_ok))

        if path == "/actualizar-todos":
            # Refresca los 45 municipios de la región, uno a uno. Pensado para
            # un disparador externo (GitHub Actions programado), no para la
            # interfaz — de ahí el ADMIN_TOKEN (mismo patrón que /vaciar).
            admin_token = os.environ.get("ADMIN_TOKEN", "")
            if not admin_token or params.get("token", [""])[0] != admin_token:
                return _error_resp("No autorizado.", 403)
            job_id = str(uuid.uuid4())
            threading.Thread(target=_actualizar_todos_bg, args=(job_id,), daemon=True).start()
            body = json.dumps({"status": "started", "job_id": job_id,
                                "total_municipios": len(MUNICIPIOS_MURCIA)})
            return _resp(body, content_type="application/json; charset=utf-8")

        return 404, {"Content-Length": "0"}, b""
    except Exception as e:
        return _error_resp(f"Error: {e}", 500)


# ─── WSGI (producción: gunicorn backend.app:app) ─────────────────────────────

def app(environ, start_response):
    """Callable WSGI estándar — es lo que gunicorn/render.yaml invocan."""
    method = environ.get("REQUEST_METHOD", "GET")
    path = environ.get("PATH_INFO", "/")
    qs = parse_qs(environ.get("QUERY_STRING", ""))
    gzip_ok = "gzip" in environ.get("HTTP_ACCEPT_ENCODING", "")

    if method == "GET":
        code, headers, body = _route_get(path, qs, gzip_ok=gzip_ok)
    elif method == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        raw = environ["wsgi.input"].read(length).decode("utf-8") if length else ""
        params = parse_qs(raw, keep_blank_values=True)
        code, headers, body = _route_post(path, params)
    else:
        code, headers, body = 405, {"Content-Length": "0"}, b""

    status_line = f"{code} {_HTTP_STATUS_TEXT.get(code, 'OK')}"
    start_response(status_line, list(headers.items()))
    return [body]


# ─── SERVIDOR HTTP DE DESARROLLO (uso local: python app.py) ──────────────────

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _write(self, code, headers, body):
        self.send_response(code)
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        gzip_ok = "gzip" in self.headers.get("Accept-Encoding", "")
        self._write(*_route_get(parsed.path, qs, gzip_ok=gzip_ok))

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length).decode("utf-8") if length else ""
            params = parse_qs(raw, keep_blank_values=True)
            self._write(*_route_post(self.path, params))
        except Exception as e:
            self._write(*_error_resp(f"Error: {e}", 500))


# Se ejecuta al importar el módulo (tanto `python app.py` como
# `gunicorn backend.app:app`, que solo importa `app` sin pasar por
# `if __name__ == "__main__"`), así los datos están cargados en memoria
# antes de servir la primera petición.
_inicializar_datos()
_lanzar_enriquecimiento()   # enriquecer sociedades ya guardadas sin directivo

if __name__ == "__main__":
    _host = "0.0.0.0"
    _port = int(os.environ.get("PORT", 8000))
    print("=" * 55)
    print("  DINERO PÚBLICO — CONTRATOS REGIÓN DE MURCIA")
    print("  Fuente: PLACE (Ministerio de Hacienda)")
    print("=" * 55)
    print(f"  Caché ZIPs: {CACHE_DIR}")
    print(f"  Servidor:   http://{_host}:{_port}")
    print("=" * 55)
    srv = ThreadedHTTPServer((_host, _port), Handler)
    srv.serve_forever()
