"""
Contratos Públicos - Murcia
Fuente: Plataforma de Contratación del Sector Público (datos oficiales CODICE/Atom)
"""

import gzip as _gzip
import json, os, re, html, io, shutil, sqlite3, zipfile, threading, uuid, time
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, quote_plus, urlencode, urlparse
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

# DATA_DIR apunta al disco persistente de Render (/var/data) cuando existe la
# env var; en local (sin la env var) sigue siendo BASE_DIR, como siempre --
# tanto cache.db como place_cache/ se guardan junto al código igual que
# antes de este cambio. Sin disco persistente, cualquier dato escrito en
# caliente (cache.db, o los ZIPs de place_cache/) se perdía en cuanto
# Render reiniciaba el servicio por inactividad, porque arrancaba de nuevo
# desde cero (ver INFORME_NOCHE.md, 2026-07-20/21).
DATA_DIR = os.environ.get("DATA_DIR", BASE_DIR)
os.makedirs(DATA_DIR, exist_ok=True)

DATA_FILE  = os.path.join(BASE_DIR, "datos.json")
ALCALDES_FILE = os.path.join(BASE_DIR, "alcaldes_concejales.json")
RETRIBUCIONES_FILE = os.path.join(BASE_DIR, "retribuciones_ispa.json")
CONTRATOS_MENORES_MURCIA_MANUAL_FILE = os.path.join(BASE_DIR, "contratos_menores_murcia_manual.json")
CUENTAS_ANUALES_FILE = os.path.join(BASE_DIR, "cuentas_anuales.json")
HACIENDA_EELL_FILE = os.path.join(BASE_DIR, "hacienda_eell.json")
POBLACION_FILE = os.path.join(BASE_DIR, "poblacion.json")
# place_cache/ (ZIPs mensuales de PLACE, ~127 MB cada uno) NO se siembra
# desde el repo -- está en .gitignore a propósito (nunca se ha commiteado,
# a diferencia de cache.db) y no tiene sentido empezar a versionar binarios
# de ese tamaño solo para esto. En un disco nuevo/vacío simplemente se
# vuelve a descargar el ZIP del mes en curso la primera vez que haga falta
# (descargar_zip_place ya cachea en CACHE_DIR y reutiliza si ya existe) --
# un único coste de unos minutos, una vez, y ya queda para siempre en el
# disco persistente en vez de repetirse en cada reinicio.
CACHE_DIR  = os.path.join(DATA_DIR, "place_cache")
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
_actualizando_fondos_ue_lock = threading.Lock()  # evita lanzar dos refrescos de fondos_ue a la vez
_actualizando_rpc_menors_lock = threading.Lock()  # evita lanzar dos refrescos de contratos menors Girona a la vez
_actualizando_menores_fuentealamo_lock = threading.Lock()  # evita lanzar dos refrescos de Fuente Álamo a la vez

PAGE_SIZE = 50               # contratos máximos por página

# ─── CACHÉ DE RESULTADOS ──────────────────────────────────────────────────────
_result_cache: dict = {}   # normalizar(municipio) → {"ts": float, "resultado": dict}
_cache_lock   = threading.Lock()
RESULT_CACHE_TTL = 6 * 3600   # 6 horas

# ─── CACHÉ SQLITE (directivos + contratos por municipio) ─────────────────────
# DATA_DIR ya se resuelve arriba, junto a BASE_DIR (la usan tanto cache.db
# como place_cache/).
DB_FILE = os.path.join(DATA_DIR, "cache.db")
DIRECTOR_CACHE_FILE = os.path.join(BASE_DIR, "director_cache.json")   # solo para migración inicial

# Primer arranque con disco nuevo/vacío (DATA_DIR distinto de BASE_DIR y sin
# cache.db todavía): sembrarlo con el cache.db commiteado en el repo para no
# empezar de cero. En arranques siguientes DB_FILE ya existe en el disco
# persistente y este bloque no hace nada.
_DB_SEED_FILE = os.path.join(BASE_DIR, "cache.db")
if (not os.path.exists(DB_FILE) and os.path.exists(_DB_SEED_FILE)
        and os.path.abspath(_DB_SEED_FILE) != os.path.abspath(DB_FILE)):
    shutil.copy2(_DB_SEED_FILE, DB_FILE)
    print(f"[startup] Disco persistente vacío: cache.db sembrado desde el repo "
          f"({_DB_SEED_FILE} -> {DB_FILE})", flush=True)

# Backup de seguridad de una sola vez, ANTES de aplicar el fix de refresco
# aditivo (ver INFORME_NOCHE.md 2026-07-22): copia el cache.db tal cual está
# en este primer arranque con el código nuevo -- incompleto para algún
# municipio ya afectado por el bug de refresco sustitutivo, pero es lo único
# que hay en este disco, y es mejor tener esta foto que ninguna. Vive en el
# mismo DATA_DIR (mismo disco persistente), no requiere credenciales
# adicionales. El nombre fijo (sin timestamp) hace que el `if` de abajo sea
# idempotente: solo copia la primera vez que arranca este código.
_DB_BACKUP_PRE_REFRESCO_ADITIVO = os.path.join(DATA_DIR, "cache_db_backup_pre_refresco_aditivo_20260722.db")
if os.path.exists(DB_FILE) and not os.path.exists(_DB_BACKUP_PRE_REFRESCO_ADITIVO):
    shutil.copy2(DB_FILE, _DB_BACKUP_PRE_REFRESCO_ADITIVO)
    # Copiar también los sidecars de WAL si el proceso anterior no hizo un
    # checkpoint limpio al parar -- si no, el backup podría no reflejar los
    # últimos commits todavía no volcados al fichero principal.
    for _ext in ("-wal", "-shm"):
        if os.path.exists(DB_FILE + _ext):
            shutil.copy2(DB_FILE + _ext, _DB_BACKUP_PRE_REFRESCO_ADITIVO + _ext)
    print(f"[startup] Backup de seguridad de cache.db antes del fix de refresco aditivo: "
          f"{_DB_BACKUP_PRE_REFRESCO_ADITIVO}", flush=True)

_db = sqlite3.connect(DB_FILE, check_same_thread=False, timeout=30)
_db.execute("PRAGMA journal_mode=WAL")
_db_lock = threading.Lock()

DIR_CACHE_POS_TTL = 90 * 24 * 3600   # 90 días para resultados encontrados
DIR_CACHE_NEG_TTL =  7 * 24 * 3600   # 7 días para "no encontrado"

DIR_INTENTOS_MAX = 3  # tras estos intentos fallidos, se marca "sin datos registrales públicos" y se deja de reintentar

# _limpiar_cache_negativos() se relanza cada vez que un municipio termina de
# refrescarse (vía _lanzar_enriquecimiento() en _job_run) -- en un lote de
# /actualizar-todos eso puede ser un ciclo completo de re-consultas externas
# cada pocos segundos/minutos, si no se limita. Este intervalo mínimo evita
# que se repita más de una vez al día por proceso (ver INFORME_NOCHE.md,
# propuesta de consumo #4: identificado como causa principal de que el lote
# de Girona tardase ~4x más en Render que en local).
_ULTIMA_LIMPIEZA_NEGATIVOS = 0.0   # fast-path en memoria; la fuente fiable es la tabla settings
LIMPIEZA_NEGATIVOS_INTERVALO = 24 * 3600
_CLAVE_ULTIMA_LIMPIEZA_NEG = "ultima_limpieza_negativos"


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
        _db.execute("""CREATE TABLE IF NOT EXISTS fondos_ue (
            id           TEXT PRIMARY KEY,
            fuente       TEXT NOT NULL,
            provincia    TEXT NOT NULL,
            municipio    TEXT,
            nuts_code    TEXT,
            titulo       TEXT,
            beneficiario TEXT,
            nif          TEXT,
            rol          TEXT,
            importe_num  REAL,
            fecha_inicio TEXT,
            fecha_fin    TEXT,
            programa     TEXT,
            fondo        TEXT,
            url          TEXT,
            ts           REAL NOT NULL
        )""")
        # Clave-valor de settings persistentes en disco (sobrevive a reinicios
        # del contenedor de Render, a diferencia de un global en memoria). Hoy
        # guarda el timestamp de la última limpieza de caché negativo -- ver
        # _limpiar_cache_negativos e INFORME_NOCHE.md 2026-07-25.
        _db.execute("""CREATE TABLE IF NOT EXISTS settings (
            clave TEXT PRIMARY KEY,
            valor TEXT
        )""")
        # Noticias del RSS de comunicados de prensa de la Comisión Europea
        # (ver actualizar_noticias_ue) filtradas a presupuesto/fondos/
        # subvenciones -- id = URL del comunicado (estable, ya es única).
        _db.execute("""CREATE TABLE IF NOT EXISTS noticias_ue (
            id           TEXT PRIMARY KEY,
            titulo       TEXT,
            resumen      TEXT,
            url          TEXT,
            fecha_ts     REAL,
            policy_areas TEXT,
            ts           REAL NOT NULL
        )""")
        # Contratos menores de fuentes LOCALES (no PLACE/PSCP): registros que
        # los ayuntamientos publican en su propio portal/sede porque la ley no
        # exige llevarlos a la plataforma de contratación formal. Empezó siendo
        # solo Girona (RPC, dataset hb6v-jcbf de la Generalitat -- ver
        # actualizar_contratos_menors_girona) y se generalizó 2026-08-03 para
        # cubrir también fuentes municipales de Murcia (Fuente Álamo, Mula,
        # Molina de Segura) -- de ahí el nombre genérico "_locales" y las
        # columnas "provincia"/"fuente" para distinguir origen. Los nombres de
        # columna en catalán (organisme/adjudicatari/tipus_contracte/...) son
        # herencia de cuando la tabla era solo de Girona; no se han renombrado
        # para no arriesgar una migración de columnas sobre datos ya en
        # producción -- son solo nombres de columna SQL, no texto visible.
        # id: namespacea por municipio ("{municipio}::{identificador}") porque
        # el identificador de origen (codi_expedient/expediente) puede
        # repetirse entre municipios o fuentes distintas (ver
        # _fila_rpc_menor_a_registro para el caso medido en Girona).
        try:
            _db.execute("ALTER TABLE contratos_menors_girona RENAME TO contratos_menors_locales")
            print("  [db-init] Tabla contratos_menors_girona renombrada a contratos_menors_locales.", flush=True)
        except sqlite3.OperationalError:
            pass  # ya renombrada en un arranque anterior, o base de datos nueva sin la tabla vieja
        _db.execute("""CREATE TABLE IF NOT EXISTS contratos_menors_locales (
            id                TEXT PRIMARY KEY,
            municipio         TEXT NOT NULL,
            provincia         TEXT NOT NULL DEFAULT 'girona',
            fuente            TEXT NOT NULL DEFAULT 'rpc-girona',
            organisme         TEXT,
            adjudicatari      TEXT,
            nif               TEXT,
            import_num        REAL,
            data_adjudicacio  TEXT,
            tipus_contracte   TEXT,
            descripcio        TEXT,
            codi_cpv          TEXT,
            exercici          TEXT,
            ts                REAL NOT NULL
        )""")
        # Añade las columnas nuevas si la tabla viene del rename de arriba (la
        # tabla vieja no las tenía) -- no-op si ya existen (base de datos
        # nueva creada directamente con el CREATE TABLE de arriba).
        for _col, _default in (("provincia", "'girona'"), ("fuente", "'rpc-girona'"), ("nif", "''")):
            try:
                _db.execute(f"ALTER TABLE contratos_menors_locales ADD COLUMN {_col} TEXT DEFAULT {_default}")
            except sqlite3.OperationalError:
                pass  # ya existe
        # Migración de un solo uso (2026-08-03): el primer backfill en
        # producción guardaba id=codi_expedient a secas, sin namespacear por
        # municipio -- como codi_expedient se repite entre municipios
        # distintos (ver nota más arriba), esas filas antiguas están
        # incompletas (contratos de un municipio sobrescritos por los de
        # otro). Se detectan por no contener "::" y se borran todas de golpe;
        # el siguiente /actualizar-contratos-menors-girona las repuebla ya con
        # el id correcto. No-op en cualquier arranque posterior.
        try:
            n_borradas = _db.execute(
                "DELETE FROM contratos_menors_locales WHERE id NOT LIKE '%::%'"
            ).rowcount
            if n_borradas:
                print(f"  [db-init] Migración contratos_menors_locales: "
                      f"{n_borradas} filas con id antiguo (sin namespacear) borradas.", flush=True)
        except sqlite3.OperationalError:
            pass
        try:
            _db.execute("ALTER TABLE directores ADD COLUMN intentos INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # ya existe (migración ya aplicada en un arranque anterior)
        try:
            # SQLite aplica el DEFAULT a las filas ya existentes al añadir la
            # columna, así que todo lo cargado antes de Girona queda como
            # 'murcia' sin necesidad de migrar datos a mano.
            _db.execute("ALTER TABLE municipios ADD COLUMN provincia TEXT DEFAULT 'murcia'")
        except sqlite3.OperationalError:
            pass  # ya existe
        try:
            # Municipio canónico (mismo listado que MUNICIPIOS_MURCIA/GIRONA,
            # o el pseudo-municipio de la provincia -- ver MUNICIPIOS_PSEUDO)
            # al que se ha podido cruzar este registro de fondos_ue, o '' si
            # la fuente solo trae ubicación a nivel regional/provincial no
            # cruzable -- ver _cruzar_municipio_fondo_ue().
            _db.execute("ALTER TABLE fondos_ue ADD COLUMN municipio_match TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # ya existe
        # Comentarios de usuarios en la ficha de municipio o de empresa
        # (búsqueda global) -- formulario simple, sin gestión activa ni
        # aviso por email: se guardan y se muestran públicos al instante,
        # sin cola de moderación. clave = normalizar(nombre del municipio)
        # o normalizar(texto de búsqueda de la empresa) -- mismo criterio
        # que el resto de tablas indexadas por municipio (ver DEUDA_VIVA/
        # POBLACION), así "Molina de Segura" y "molina  de   segura"
        # comparten hilo de comentarios.
        _db.execute("""CREATE TABLE IF NOT EXISTS comentarios (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo    TEXT NOT NULL,
            clave   TEXT NOT NULL,
            etiqueta TEXT NOT NULL,
            nombre  TEXT,
            texto   TEXT NOT NULL,
            ts      REAL NOT NULL
        )""")
        _db.commit()

        # Recalcula municipio_match para TODAS las filas en cada arranque (no
        # solo cuando la columna es nueva): es una tabla pequeña (unos pocos
        # miles de filas, coste insignificante una vez al arrancar) y así
        # cualquier cambio futuro en _cruzar_municipio_fondo_ue (como el del
        # 2026-07-23 que añadió el cruce contra los pseudo-municipios) se
        # aplica de inmediato a los datos ya cargados, sin esperar al próximo
        # /actualizar-fondos-ue.
        filas_existentes = _db.execute(
            "SELECT id, provincia, municipio, municipio_match FROM fondos_ue").fetchall()
        cambios = 0
        for fid, prov, muni, match_actual in filas_existentes:
            match = _cruzar_municipio_fondo_ue(prov, muni)
            if match != (match_actual or ""):
                _db.execute("UPDATE fondos_ue SET municipio_match=? WHERE id=?", (match, fid))
                cambios += 1
        _db.commit()
        if filas_existentes:
            print(f"  [db-init] municipio_match recalculado para {len(filas_existentes)} "
                  f"filas de fondos_ue ({cambios} cambiaron).", flush=True)
    _migrar_json_a_sqlite()


def _settings_get(clave, default=None):
    """Lee un valor de la tabla settings (persistente en disco)."""
    with _db_lock:
        row = _db.execute("SELECT valor FROM settings WHERE clave=?", (clave,)).fetchone()
    return row[0] if row else default


def _settings_get_float(clave, default=0.0):
    try:
        return float(_settings_get(clave, default))
    except (TypeError, ValueError):
        return default


def _settings_set(clave, valor):
    """Escribe (upsert) un valor en la tabla settings."""
    with _db_lock:
        _db.execute(
            "INSERT INTO settings (clave, valor) VALUES (?, ?) "
            "ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
            (clave, str(valor)),
        )
        _db.commit()


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


def _cargar_alcaldes_concejales():
    """Carga alcaldes_concejales.json (generado por actualizar_alcaldes.py a
    partir del Ministerio de Política Territorial y Memoria Democrática).
    Dato estático: no se recalcula en caliente, solo se refresca re-lanzando
    ese script periódicamente."""
    if os.path.exists(ALCALDES_FILE):
        try:
            with open(ALCALDES_FILE, encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, dict):
                    return d.get("municipios", {})
        except Exception:
            pass
    return {}


ALCALDES_CONCEJALES = _cargar_alcaldes_concejales()


def _cargar_retribuciones_ispa():
    """Carga retribuciones_ispa.json (generado por actualizar_retribuciones.py
    a partir del fichero 'retribuciones_alcaldes.xlsx' del Portal MTDFP -
    Espacio ISPA, Ministerio para la Transformación Digital y de la Función
    Pública). Dato anual y estático, mismo patrón que ALCALDES_CONCEJALES:
    no se recalcula en caliente, solo se refresca re-lanzando ese script."""
    if os.path.exists(RETRIBUCIONES_FILE):
        try:
            with open(RETRIBUCIONES_FILE, encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, dict):
                    return d.get("municipios", {})
        except Exception:
            pass
    return {}


RETRIBUCIONES_ISPA = _cargar_retribuciones_ispa()


def _cargar_cuentas_anuales():
    """Carga cuentas_anuales.json (generado por actualizar_cuentas_anuales.py):
    idEntidad + último ejercicio rendido en la Plataforma de Rendición de
    Cuentas, por municipio -- permite enlazar directo a la ficha de esa
    Cuenta General concreta en vez de al buscador genérico. Mismo patrón
    estático/periódico que ALCALDES_CONCEJALES y RETRIBUCIONES_ISPA."""
    if os.path.exists(CUENTAS_ANUALES_FILE):
        try:
            with open(CUENTAS_ANUALES_FILE, encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, dict):
                    return d.get("municipios", {})
        except Exception:
            pass
    return {}


CUENTAS_ANUALES = _cargar_cuentas_anuales()


def _cargar_hacienda_eell():
    """Carga hacienda_eell.json (generado por actualizar_deuda_y_liquidaciones.py):
    deuda viva municipal y saldo presupuestario no financiero (superávit/
    déficit), ambos del Ministerio de Hacienda -- ver docstring de ese
    script sobre por qué esta fuente sí trae el importe que rendiciondecuentas.es
    no puede dar. Mismo patrón estático/periódico que CUENTAS_ANUALES."""
    if os.path.exists(HACIENDA_EELL_FILE):
        try:
            with open(HACIENDA_EELL_FILE, encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, dict):
                    return (d.get("deuda_viva", {}).get("municipios", {}),
                            d.get("deuda_viva", {}).get("fuente_url", ""),
                            d.get("saldo_no_financiero", {}).get("municipios", {}))
        except Exception:
            pass
    return {}, "", {}


DEUDA_VIVA, DEUDA_VIVA_FUENTE_URL, SALDO_NO_FINANCIERO = _cargar_hacienda_eell()


def _cargar_poblacion():
    """Carga poblacion.json (generado por actualizar_poblacion.py): cifra
    oficial de población de cada municipio (INE, Padrón Municipal) y la URL
    pública de la tabla del INE de la que sale, una por provincia (no una
    por municipio, ver docstring de ese script)."""
    if os.path.exists(POBLACION_FILE):
        try:
            with open(POBLACION_FILE, encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, dict):
                    return d.get("municipios", {}), d.get("fuente_url", {})
        except Exception:
            pass
    return {}, {}


POBLACION, POBLACION_FUENTE_URL = _cargar_poblacion()


def _construir_indice_cargos_publicos():
    """Índice nombre_completo_normalizado -> [{cargo, municipio, provincia}, ...]
    a partir de ALCALDES_CONCEJALES, para el detector de coincidencias de
    nombre (adjudicatarios/directivos vs. alcaldes/concejales). Exige nombre
    + al menos un apellido (2+ palabras) -- un apellido suelto no es señal
    de nada y generaría demasiados falsos positivos."""
    idx = {}
    for info in ALCALDES_CONCEJALES.values():
        municipio = info.get("municipio", "")
        provincia = info.get("provincia", "murcia")
        for conc in info.get("concejales", []):
            nombre = conc.get("nombre", "")
            key = normalizar(nombre)
            if not key or len(key.split()) < 2:
                continue
            idx.setdefault(key, []).append({
                "cargo": conc.get("cargo", ""),
                "municipio": municipio,
                "provincia": provincia,
            })
    return idx


def _detectar_coincidencia_cargo(nombre_persona, municipio_contrato, provincia_contrato):
    """Compara el nombre completo de un adjudicatario/directivo contra el
    índice de alcaldes/concejales. Coincidencia EXACTA de nombre+apellidos
    únicamente (nunca apellido suelto). Devuelve None o un dict con tipo
    'local' (mismo municipio) o 'regional' (misma provincia, municipio
    distinto) -- nunca implica relación, es solo una señal para verificar."""
    key = normalizar(nombre_persona or "")
    if not key or len(key.split()) < 2:
        return None
    candidatos = INDICE_CARGOS_PUBLICOS.get(key)
    if not candidatos:
        return None
    muni_norm = normalizar(municipio_contrato or "")
    for cand in candidatos:
        if normalizar(cand["municipio"]) == muni_norm:
            return {"tipo": "local", **cand}
    for cand in candidatos:
        if cand["provincia"] == provincia_contrato:
            return {"tipo": "regional", **cand}
    return None


def _db_set_municipio(municipio, resultado, provincia="murcia"):
    key = normalizar(municipio)
    # Mutar el dict del caller in-place (NO una copia): resultado suele ser el
    # mismo objeto que ya vive en _datos_memoria, así que si copiáramos aquí
    # la provincia nunca llegaría a esa copia en memoria -- y el hilo de
    # enriquecimiento (_guardar_datos_sin_lock, que sí lee d.get("provincia"))
    # la volvería a pisar a "murcia" en su siguiente checkpoint. Confirmado
    # con un test dirigido durante la Fase 4.
    resultado["provincia"] = provincia
    with _db_lock:
        _db.execute(
            "INSERT INTO municipios (municipio, data, ts, provincia) VALUES (?,?,?,?) "
            "ON CONFLICT(municipio) DO UPDATE SET data=excluded.data, ts=excluded.ts, provincia=excluded.provincia",
            (key, json.dumps(resultado, ensure_ascii=False), resultado.get("timestamp", time.time()), provincia),
        )
        _db.commit()


def _db_all_municipios(provincia=None):
    with _db_lock:
        if provincia:
            rows = _db.execute("SELECT data, provincia FROM municipios WHERE provincia=?", (provincia,)).fetchall()
        else:
            rows = _db.execute("SELECT data, provincia FROM municipios").fetchall()
    out = []
    for data, prov in rows:
        try:
            d = json.loads(data)
            d.setdefault("provincia", prov or "murcia")  # filas antiguas sin el campo en el JSON
            out.append(d)
        except Exception:
            pass
    return out


def _db_obtener_contratos_municipio(municipio):
    """Contratos ya guardados para este municipio ANTES de un nuevo refresco
    -- se usa para fusionar en vez de sustituir (ver _fusionar_historico_
    contratos e INFORME_NOCHE.md 2026-07-22: el refresco sustitutivo anterior
    borró histórico real de al menos Archena)."""
    key = normalizar(municipio)
    with _db_lock:
        row = _db.execute("SELECT data FROM municipios WHERE municipio=?", (key,)).fetchone()
    if not row:
        return []
    try:
        return json.loads(row[0]).get("contratos", [])
    except Exception:
        return []


def _db_clear_municipios(provincia=None):
    with _db_lock:
        if provincia:
            _db.execute("DELETE FROM municipios WHERE provincia=?", (provincia,))
        else:
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

# ─── PROVINCIA DE GIRONA (Fase 1 — módulo PSCP, no usado aún por las rutas) ──
# Los 221 municipios oficiales (Idescat) y su codi_ine10 (10 dígitos) en el
# dataset de contractació pública de Catalunya, para poder filtrar la
# consulta a PSCP por municipio exacto (en vez de buscar por texto libre
# como se hace en PLACE/BORM).
MUNICIPIOS_GIRONA = [
    "Agullana", "Aiguaviva", "Albanyà", "Albons", "Alp", "Amer", "Anglès",
    "Arbúcies", "Argelaguer", "Armentera, l'", "Avinyonet de Puigventós",
    "Banyoles", "Begur", "Bellcaire d'Empordà", "Besalú", "Bescanó", "Beuda",
    "Bisbal d'Empordà, la", "Biure", "Blanes", "Boadella i les Escaules",
    "Bolvir", "Bordils", "Borrassà", "Breda", "Brunyola i Sant Martí Sapresa",
    "Bàscara", "Cabanelles", "Cabanes", "Cadaqués", "Caldes de Malavella",
    "Calonge i Sant Antoni", "Campdevànol", "Campelles", "Campllong",
    "Camprodon", "Camós", "Canet d'Adri", "Cantallops", "Capmany",
    "Cassà de la Selva", "Castell d'Aro, Platja d'Aro i s'Agaró",
    "Castellfollit de la Roca", "Castelló d'Empúries", "Cellera de Ter, la",
    "Celrà", "Cervià de Ter", "Cistella", "Colera", "Colomers",
    "Cornellà del Terri", "Corçà", "Crespià",
    "Cruïlles, Monells i Sant Sadurní de l'Heura", "Darnius", "Das",
    "Escala, l'", "Espinelves", "Espolla", "Esponellà", "Far d'Empordà, el",
    "Figueres", "Flaçà", "Foixà", "Fontanals de Cerdanya", "Fontanilles",
    "Fontcoberta", "Forallac", "Fornells de la Selva", "Fortià",
    "Garrigoles", "Garriguella", "Garrigàs", "Ger", "Girona", "Gombrèn",
    "Gualta", "Guils de Cerdanya", "Hostalric", "Isòvol", "Jafre",
    "Jonquera, la", "Juià", "Lladó", "Llagostera", "Llambilles", "Llanars",
    "Llançà", "Llers", "Lloret de Mar", "Llosses, les", "Llívia",
    "Madremanya", "Maià de Montcal", "Masarac i Vilarnadal", "Massanes",
    "Maçanet de Cabrenys", "Maçanet de la Selva", "Meranges", "Mieres",
    "Mollet de Peralada", "Molló", "Mont-ras", "Montagut i Oix", "Navata",
    "Ogassa", "Olot", "Ordis", "Osor", "Palafrugell", "Palamós",
    "Palau de Santa Eulàlia", "Palau-sator", "Palau-saverdera",
    "Palol de Revardit", "Pals", "Pardines", "Parlavà", "Pau",
    "Pedret i Marzà", "Pera, la", "Peralada", "Planes d'Hostoles, les",
    "Planoles", "Pont de Molins", "Pontós", "Porqueres",
    "Port de la Selva, el", "Portbou", "Preses, les", "Puigcerdà", "Quart",
    "Queralbs", "Rabós", "Regencós", "Ribes de Freser", "Riells i Viabrea",
    "Ripoll", "Riudarenes", "Riudaura", "Riudellots de la Selva", "Riumors",
    "Roses", "Rupià", "Sales de Llierca", "Salt", "Sant Andreu Salou",
    "Sant Aniol de Finestres", "Sant Climent Sescebes",
    "Sant Feliu de Buixalleu", "Sant Feliu de Guíxols",
    "Sant Feliu de Pallerols", "Sant Ferriol", "Sant Gregori",
    "Sant Hilari Sacalm", "Sant Jaume de Llierca", "Sant Joan de Mollet",
    "Sant Joan de les Abadesses", "Sant Joan les Fonts",
    "Sant Jordi Desvalls", "Sant Julià de Ramis",
    "Sant Julià del Llor i Bonmatí", "Sant Llorenç de la Muga",
    "Sant Martí Vell", "Sant Martí de Llémena", "Sant Miquel de Campmajor",
    "Sant Miquel de Fluvià", "Sant Mori", "Sant Pau de Segúries",
    "Sant Pere Pescador", "Santa Coloma de Farners", "Santa Cristina d'Aro",
    "Santa Llogaia d'Àlguema", "Santa Pau", "Sarrià de Ter",
    "Saus, Camallera i Llampaies", "Selva de Mar, la", "Serinyà",
    "Serra de Daró", "Setcases", "Sils", "Siurana", "Susqueda",
    "Tallada d'Empordà, la", "Terrades", "Torrent", "Torroella de Fluvià",
    "Torroella de Montgrí", "Tortellà", "Toses", "Tossa de Mar", "Ullastret",
    "Ullà", "Ultramort", "Urús", "Vajol, la", "Vall d'en Bas, la",
    "Vall de Bianya, la", "Vall-llobrega", "Vallfogona de Ripollès",
    "Ventalló", "Verges", "Vidreres", "Vidrà", "Vila-sacra", "Vilabertran",
    "Vilablareix", "Viladamat", "Viladasens", "Vilademuls", "Viladrau",
    "Vilafant", "Vilajuïga", "Vilallonga de Ter", "Vilamacolum", "Vilamalla",
    "Vilamaniscle", "Vilanant", "Vilaür", "Vilobí d'Onyar", "Vilopriu",
]

# nombre de municipio -> codi_ine10 (10 dígitos) del Ajuntament en el dataset
# PSCP. Construido cruzando el listado oficial de Idescat con el dataset
# ybgg-dgi6 (ver backend/diag_pscp_build_municipios.py); validado 221/221
# sin ambigüedad.
MUNICIPIOS_GIRONA_INE = {
    "Agullana": "1700100000", "Aiguaviva": "1700250006", "Albanyà": "1700310007",
    "Albons": "1700460009", "Alp": "1700620002", "Amer": "1700780001",
    "Anglès": "1700840003", "Arbúcies": "1700970005", "Argelaguer": "1701010007",
    "Armentera, l'": "1701180001", "Avinyonet de Puigventós": "1701230008",
    "Banyoles": "1701570005", "Begur": "1701390004", "Bellcaire d'Empordà": "1701820002",
    "Besalú": "1701950006", "Bescanó": "1702090004", "Beuda": "1702160009",
    "Bisbal d'Empordà, la": "1702210007", "Biure": "1723480001", "Blanes": "1702370005",
    "Boadella i les Escaules": "1702930008", "Bolvir": "1702420002", "Bordils": "1702550006",
    "Borrassà": "1702680001", "Breda": "1702740003",
    "Brunyola i Sant Martí Sapresa": "1702800000", "Bàscara": "1701600000",
    "Cabanelles": "1703140003", "Cabanes": "1703070005", "Cadaqués": "1703290004",
    "Caldes de Malavella": "1703350006", "Calonge i Sant Antoni": "1703400000",
    "Campdevànol": "1703660009", "Campelles": "1703720002", "Campllong": "1703880001",
    "Camprodon": "1703910007", "Camós": "1703530008", "Canet d'Adri": "1704050006",
    "Cantallops": "1704120002", "Capmany": "1704270005", "Cassà de la Selva": "1704480001",
    "Castell d'Aro, Platja d'Aro i s'Agaró": "1704860009",
    "Castellfollit de la Roca": "1704640003", "Castelló d'Empúries": "1704700000",
    "Cellera de Ter, la": "1718990004", "Celrà": "1704990004", "Cervià de Ter": "1705020002",
    "Cistella": "1705190004", "Colera": "1705450006", "Colomers": "1705580001",
    "Cornellà del Terri": "1705610007", "Corçà": "1705770005", "Crespià": "1705830008",
    "Cruïlles, Monells i Sant Sadurní de l'Heura": "1790110007", "Darnius": "1706000000",
    "Das": "1706170005", "Escala, l'": "1706220002", "Espinelves": "1706380001",
    "Espolla": "1706430008", "Esponellà": "1706560009", "Far d'Empordà, el": "1700590004",
    "Figueres": "1706690004", "Flaçà": "1706750006", "Foixà": "1706810007",
    "Fontanals de Cerdanya": "1706940003", "Fontanilles": "1707080001",
    "Fontcoberta": "1707150006", "Forallac": "1790260009",
    "Fornells de la Selva": "1707360009", "Fortià": "1707410007", "Garrigoles": "1707670005",
    "Garriguella": "1707730008", "Garrigàs": "1707540003", "Ger": "1707890004",
    "Girona": "1707920002", "Gombrèn": "1708060009", "Gualta": "1708130008",
    "Guils de Cerdanya": "1708280001", "Hostalric": "1708340003", "Isòvol": "1708490004",
    "Jafre": "1708520002", "Jonquera, la": "1708650006", "Juià": "1708710007",
    "Lladó": "1708870005", "Llagostera": "1708900000", "Llambilles": "1709040003",
    "Llanars": "1709110007", "Llançà": "1709260009", "Llers": "1709320002",
    "Lloret de Mar": "1709500000", "Llosses, les": "1709630008", "Llívia": "1709470005",
    "Madremanya": "1709790004", "Maià de Montcal": "1709850006",
    "Masarac i Vilarnadal": "1710020002", "Massanes": "1710190004",
    "Maçanet de Cabrenys": "1710240003", "Maçanet de la Selva": "1710300000",
    "Meranges": "1709980001", "Mieres": "1710580001", "Mollet de Peralada": "1710610007",
    "Molló": "1710770005", "Mont-ras": "1711000000", "Montagut i Oix": "1710960009",
    "Navata": "1711170005", "Ogassa": "1711220002", "Olot": "1711430008",
    "Ordis": "1711560009", "Osor": "1711690004", "Palafrugell": "1711750006",
    "Palamós": "1711810007", "Palau de Santa Eulàlia": "1711940003",
    "Palau-sator": "1712150006", "Palau-saverdera": "1712080001",
    "Palol de Revardit": "1712360009", "Pals": "1712410007", "Pardines": "1712540003",
    "Parlavà": "1712670005", "Pau": "1712890004", "Pedret i Marzà": "1712920002",
    "Pera, la": "1713060009", "Peralada": "1713280001",
    "Planes d'Hostoles, les": "1713340003", "Planoles": "1713490004",
    "Pont de Molins": "1713520002", "Pontós": "1713650006", "Porqueres": "1713710007",
    "Port de la Selva, el": "1714040003", "Portbou": "1713870005", "Preses, les": "1713900000",
    "Puigcerdà": "1714110007", "Quart": "1714260009", "Queralbs": "1704330008",
    "Rabós": "1714320002", "Regencós": "1714470005", "Ribes de Freser": "1714500000",
    "Riells i Viabrea": "1714630008", "Ripoll": "1714790004", "Riudarenes": "1714850006",
    "Riudaura": "1714980001", "Riudellots de la Selva": "1715010007",
    "Riumors": "1715180001", "Roses": "1715230008", "Rupià": "1715390004",
    "Sales de Llierca": "1715440003", "Salt": "1715570005",
    "Sant Andreu Salou": "1715760009", "Sant Aniol de Finestres": "1718330008",
    "Sant Climent Sescebes": "1715820002", "Sant Feliu de Buixalleu": "1715950006",
    "Sant Feliu de Guíxols": "1716090004", "Sant Feliu de Pallerols": "1716160009",
    "Sant Ferriol": "1716210007", "Sant Gregori": "1716370005",
    "Sant Hilari Sacalm": "1716420002", "Sant Jaume de Llierca": "1716550006",
    "Sant Joan de Mollet": "1716800000", "Sant Joan de les Abadesses": "1716740003",
    "Sant Joan les Fonts": "1718510007", "Sant Jordi Desvalls": "1716680001",
    "Sant Julià de Ramis": "1716930008", "Sant Julià del Llor i Bonmatí": "1790320002",
    "Sant Llorenç de la Muga": "1717140003", "Sant Martí Vell": "1717350006",
    "Sant Martí de Llémena": "1717290004", "Sant Miquel de Campmajor": "1717400000",
    "Sant Miquel de Fluvià": "1717530008", "Sant Mori": "1717660009",
    "Sant Pau de Segúries": "1717720002", "Sant Pere Pescador": "1717880001",
    "Santa Coloma de Farners": "1718050006", "Santa Cristina d'Aro": "1718120002",
    "Santa Llogaia d'Àlguema": "1718270005", "Santa Pau": "1718480001",
    "Sarrià de Ter": "1718640003", "Saus, Camallera i Llampaies": "1718700000",
    "Selva de Mar, la": "1718860009", "Serinyà": "1719030008", "Serra de Daró": "1719100000",
    "Setcases": "1719250006", "Sils": "1719310007", "Siurana": "1705240003",
    "Susqueda": "1719460009", "Tallada d'Empordà, la": "1719590004",
    "Terrades": "1719620002", "Torrent": "1719780001", "Torroella de Fluvià": "1719840003",
    "Torroella de Montgrí": "1719970005", "Tortellà": "1720010007", "Toses": "1720180001",
    "Tossa de Mar": "1720230008", "Ullastret": "1720570005", "Ullà": "1720440003",
    "Ultramort": "1720390004", "Urús": "1720600000", "Vajol, la": "1701440003",
    "Vall d'en Bas, la": "1720760009", "Vall de Bianya, la": "1720820002",
    "Vall-llobrega": "1720950006", "Vallfogona de Ripollès": "1717070005",
    "Ventalló": "1721090004", "Verges": "1721160009", "Vidreres": "1721370005",
    "Vidrà": "1721210007", "Vila-sacra": "1723050006", "Vilabertran": "1721420002",
    "Vilablareix": "1721550006", "Viladamat": "1721740003", "Viladasens": "1721680001",
    "Vilademuls": "1721800000", "Viladrau": "1722070005", "Vilafant": "1722140003",
    "Vilajuïga": "1722350006", "Vilallonga de Ter": "1722400000",
    "Vilamacolum": "1722530008", "Vilamalla": "1722660009", "Vilamaniscle": "1722720002",
    "Vilanant": "1722880001", "Vilaür": "1722290004", "Vilobí d'Onyar": "1723330008",
    "Vilopriu": "1723270005",
}

PSCP_URL = "https://analisi.transparenciacatalunya.cat/resource/ybgg-dgi6.json"
PSCP_FASES = "'Adjudicació','Formalització'"


def place_profile_url(municipio):
    pid = MUNICIPIOS_PLACE_IDS.get(municipio)
    if pid:
        return f"https://contrataciondelsectorpublico.gob.es/web/guest/perfil-del-contratante/-/entity/id/{pid}"
    from urllib.parse import quote_plus as _qp
    return (f"https://contrataciondelsectorpublico.gob.es/web/guest/perfil-del-contratante"
            f"?buscador={_qp('Ayuntamiento de ' + municipio)}")


# Comunidad Autónoma / Provincia tal como los identifica el desplegable de
# la Plataforma de Rendición de Cuentas (rendiciondecuentas.es) -- ids
# verificados a mano el 2026-08-02 inspeccionando el HTML del propio
# formulario de busqueda (idComunidadAutonoma=9 "Cataluña", idProvincia=17
# "Gerona"; idComunidadAutonoma=13 "Región de Murcia", idProvincia=30
# "Murcia"). idTipoEntidad="A" = Ayuntamiento.
RENDICION_CUENTAS_IDS = {
    "murcia": {"idComunidadAutonoma": "13", "idProvincia": "30"},
    "girona": {"idComunidadAutonoma": "9", "idProvincia": "17"},
}


def rendicion_cuentas_url(municipio, provincia):
    """Enlace a la Plataforma de Rendición de Cuentas de las Corporaciones
    Locales (Tribunal de Cuentas) para este ayuntamiento.

    Si CUENTAS_ANUALES tiene el idEntidad de este municipio (ver
    actualizar_cuentas_anuales.py), enlaza DIRECTO a la ficha de la Cuenta
    General del último ejercicio rendido -- verificado a mano el
    2026-08-02 que esa URL (buscarCuentas/consultarCuenta.html) funciona
    "en frío", sin sesión ni Referer previos, GET plano. Si no hay dato
    cacheado para el municipio (script sin ejecutar todavía, o municipio
    sin match), cae al buscador genérico por nombre -- también un GET
    plano verificado en frío, un paso menos directo pero sigue llevando al
    municipio correcto en la inmensa mayoría de los casos.

    No incluimos el resultado (superávit/déficit) en ningún caso: esa
    cifra vive detrás de un visualizador Java con sesión de varios pasos
    (ver docstring de actualizar_cuentas_anuales.py) que no es replicable
    como enlace estable para el usuario final."""
    info = CUENTAS_ANUALES.get(normalizar(municipio))
    if info and info.get("id_entidad") and info.get("ultimo_ejercicio_rendido"):
        params = {"idEntidad": info["id_entidad"], "ejercicio": info["ultimo_ejercicio_rendido"]}
        return ("https://www.rendiciondecuentas.es/es/consultadeentidadesycuentas/"
                f"buscarCuentas/consultarCuenta.html?{urlencode(params)}")

    ids = RENDICION_CUENTAS_IDS.get(provincia)
    if not ids:
        return ""
    params = {
        "idComunidadAutonoma": ids["idComunidadAutonoma"],
        "idProvincia": ids["idProvincia"],
        "idTipoEntidad": "A",
        "denominacion": municipio,
        "submitFormBusquedaEntidades": "Buscar",
    }
    return ("https://www.rendiciondecuentas.es/es/consultadeentidadesycuentas/"
            f"buscarEntidades/index.html?{urlencode(params)}")


def normalizar(s):
    s = (s or "").lower().strip()
    for a, b in {"á":"a","é":"e","í":"i","ó":"o","ú":"u","ü":"u","ñ":"n",
                 "à":"a","è":"e","ò":"o","ï":"i","ç":"c"}.items():  # también vocales/ç catalanas (Girona)
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s)

def esc(s):
    return html.escape(str(s or ""), quote=True)


INDICE_CARGOS_PUBLICOS = _construir_indice_cargos_publicos()


def _capitalizar_nombre(s):
    """Los nombres del Ministerio vienen en mayúsculas (NOMBRE APELLIDO1
    APELLIDO2); formato legible tipo 'Nombre Apellido'."""
    return " ".join(p.capitalize() for p in (s or "").split())


def alcalde_concejales_html(municipio):
    """Bloque HTML de alcalde/alcaldesa + desplegable de concejales para la
    ficha de un ayuntamiento, a partir de ALCALDES_CONCEJALES (Ministerio de
    Política Territorial y Memoria Democrática, ver actualizar_alcaldes.py).
    Cada concejal enlaza a una búsqueda de la transparencia de su
    ayuntamiento (no hay una fuente pública con la URL directa de cada uno
    de los 266 municipios). Devuelve "" si no hay datos para el municipio.

    El sueldo del alcalde/sa (si existe en RETRIBUCIONES_ISPA, ver
    actualizar_retribuciones.py) se muestra junto a su nombre -- es la única
    fila del fichero ISPA con una atribución nombre↔importe inequívoca (una
    fila = un ayuntamiento). Los concejales NO llevan importe: el fichero
    ISPA de concejales trae una fila por asiento sin nombre ni cargo
    distintivo (siempre "Concejal"), así que no hay forma fiable de saber
    qué importe corresponde a qué persona cuando hay varios -- instrucción
    del 2026-08-02, mejor no mostrar dato que atribuirlo mal."""
    info = ALCALDES_CONCEJALES.get(normalizar(municipio))
    if not info:
        return ""

    alcalde = info.get("alcalde") or {}
    nombre_alcalde = _capitalizar_nombre(alcalde.get("nombre", ""))
    alcalde_html = ""
    if nombre_alcalde:
        partido_alcalde = alcalde.get("partido", "")
        sufijo = f" ({esc(partido_alcalde)})" if partido_alcalde else ""
        retrib = RETRIBUCIONES_ISPA.get(normalizar(municipio))
        retrib_html = ""
        if retrib and retrib.get("importe") is not None:
            anio = retrib.get("anio", "")
            retrib_html = (f' <span class="pol-retrib">💰 {fmt_eur(retrib["importe"])}/año'
                            f'{f" (ISPA {esc(anio)})" if anio else ""}</span>')
        alcalde_html = (f'<span class="alcalde-info">👤 Alcalde/sa: '
                         f'<b class="pol-nombre">{esc(nombre_alcalde)}</b>{sufijo}{retrib_html}</span>')

    concejales = info.get("concejales") or []
    organismo = f"Ajuntament de {municipio}" if info.get("provincia") == "girona" else f"Ayuntamiento de {municipio}"
    transp_url = f"https://www.google.com/search?q={quote_plus(organismo + ' transparencia')}"

    items = []
    for c in concejales:
        nombre_c = esc(_capitalizar_nombre(c.get("nombre", "")))
        cargo_c = esc(c.get("cargo", ""))
        partido_c = c.get("partido", "")
        sufijo_c = f" ({esc(partido_c)})" if partido_c else ""
        items.append(
            f'<li><a href="{esc(transp_url)}" target="_blank" rel="noopener">{nombre_c}</a> '
            f'<span class="conc-cargo">— {cargo_c}{sufijo_c}</span></li>'
        )

    dd_html = ""
    if concejales:
        dd_html = (f'<details class="concejales-dd"><summary>Concejales ({len(concejales)})</summary>'
                   f'<ul>{"".join(items)}</ul></details>')

    if not alcalde_html and not dd_html:
        return ""
    return f'<div class="alcalde-block">{alcalde_html}{dd_html}</div>'


def municipio_valido(txt):
    buscado = normalizar(txt)
    for m in MUNICIPIOS_MURCIA:
        if normalizar(m) == buscado:
            return m
    return None

def municipio_valido_girona(txt):
    buscado = normalizar(txt)
    for m in MUNICIPIOS_GIRONA:
        if normalizar(m) == buscado:
            return m
    return None

# ─── PROVINCIA (Fase 4 — rutas/UI transversales) ─────────────────────────────
MUNICIPIOS_POR_PROVINCIA = {"murcia": MUNICIPIOS_MURCIA, "girona": MUNICIPIOS_GIRONA}
PROVINCIA_LABEL = {"murcia": "Región de Murcia", "girona": "Provincia de Girona", "todas": "España"}

def _provincia_valida(txt):
    """Normaliza el parámetro ?provincia= de la querystring: cualquier valor
    desconocido (o ausente) cae a 'murcia'. Para rutas que operan siempre
    sobre una provincia concreta (rankings provincial, /buscar, /actualizar,
    /actualizar-todos) — un municipio pertenece a una única provincia, no
    tiene sentido "todas" ahí."""
    return txt if txt in MUNICIPIOS_POR_PROVINCIA else "murcia"

def _provincia_o_todas(txt):
    """Como _provincia_valida, pero para las rutas que sí soportan una vista
    agregada: cualquier valor que no sea una provincia real (ausente, vacío,
    'todas' o inválido) se trata como "sin filtro"."""
    return txt if txt in MUNICIPIOS_POR_PROVINCIA else "todas"

def municipio_valido_provincia(municipio, provincia):
    if provincia == "girona":
        return municipio_valido_girona(municipio)
    return municipio_valido(municipio)


# ─── PSEUDO-MUNICIPIOS (ámbito autonómico/provincial, no un ayuntamiento) ────
# Contratos y fondos UE cuyo ámbito es toda la Región de Murcia o toda la
# provincia de Girona -- no pertenecen a ningún ayuntamiento concreto, así
# que hoy se quedaban fuera del listado de municipios (los fondos, solo
# visibles en /fondos-ue) o mal atribuidos (los contratos de la CCAA de
# Murcia, ver _es_organo_ccaa_murcia). Estas entradas se guardan en las
# mismas tablas/estructuras que un ayuntamiento más (misma tabla SQLite
# `municipios`, mismo `_datos_memoria`, mismas páginas de listado/ficha) para
# que aparezcan con sus propias estadísticas igual que cualquier otro
# municipio -- pero NO están en MUNICIPIOS_MURCIA/MUNICIPIOS_GIRONA a
# propósito, para no arrastrar el pipeline de scraping por-municipio
# (buscador PLACE "Ayuntamiento de X", INE10 de Girona, alcalde/concejales...)
# que no tiene sentido para ellas. Ver INFORME_NOCHE.md 2026-07-23 para el
# porqué de no incluir también "Generalitat de Catalunya": el PSCP no
# permite acotar sus contratos a solo Girona (son de toda Catalunya), así
# que de momento solo se resuelve el lado de fondos UE para Girona
# (etiquetado "Provincia de Girona", que sí es un recorte fiable por NUTS3).
MUNICIPIOS_PSEUDO = {"murcia": "Región de Murcia", "girona": "Provincia de Girona"}

# Pseudo-municipios ADICIONALES por provincia (puede haber más de uno).
# La Administración General del Estado (organismos estatales periféricos con
# sede en Murcia: Guardia Civil, AEAT, TGSS, INSS, Delegación del Gobierno,
# centros penitenciarios, SEPE...) contamina hoy el municipio "Murcia" capital
# por el mismo bug de subcadena que la CCAA -- el nombre del municipio aparece
# dentro del texto del órgano ("...en Murcia", "(Murcia)"), así que se
# atribuye a la ciudad sin ser ni municipal ni autonómico. Se separan a su
# propia entrada, igual que "Región de Murcia". Ver _es_organo_age e
# INFORME_NOCHE.md 2026-07-25.
NOMBRE_PSEUDO_AGE = "Administración General del Estado"
# La Universidad de Murcia se agrupó inicialmente dentro de la AGE (mismo bug
# de subcadena), pero es una universidad pública AUTÓNOMA, no AGE en sentido
# estricto -- pesaba el 64% de esa entrada. Se separa a su propia entrada
# pseudo-municipio, con el mismo patrón de detección/reclasificación que la
# AGE (ver _es_organo_umu / _guardar_pseudo_municipio_umu).
NOMBRE_PSEUDO_UMU = "Universidad de Murcia"
MUNICIPIOS_PSEUDO_EXTRA = {"murcia": [NOMBRE_PSEUDO_AGE, NOMBRE_PSEUDO_UMU]}


def _pseudos_de_provincia(provincia):
    """Nombres de todas las entradas pseudo-municipio de una provincia (la
    de ámbito autonómico/provincial de MUNICIPIOS_PSEUDO más las adicionales
    de MUNICIPIOS_PSEUDO_EXTRA, p.ej. la AGE en Murcia)."""
    out = []
    n = MUNICIPIOS_PSEUDO.get(provincia)
    if n:
        out.append(n)
    out.extend(MUNICIPIOS_PSEUDO_EXTRA.get(provincia, []))
    return out


def _todos_los_pseudo_nombres():
    nombres = list(MUNICIPIOS_PSEUDO.values())
    for extra in MUNICIPIOS_PSEUDO_EXTRA.values():
        nombres.extend(extra)
    return nombres


def es_pseudo_municipio(municipio):
    buscado = normalizar(municipio)
    return any(normalizar(m) == buscado for m in _todos_los_pseudo_nombres())


_RE_ORGANO_CCAA_MURCIA = re.compile(r"region(al)? de murcia")
_EXCLUIR_ORGANO_CCAA_MURCIA = ("consorcio", "mancomunidad", "federacion de municipios")


def _es_organo_ccaa_murcia(organo):
    """True si el órgano contratante es la propia Comunidad Autónoma de la
    Región de Murcia (Consejerías, institutos, agencias, Asamblea Regional,
    Boletín Oficial...) y no un ayuntamiento ni un ente conjunto con varios
    municipios (consorcio/mancomunidad/federación de municipios -- estos sí
    incluyen "Región de Murcia" en su nombre pero no son la CCAA en sí, se
    dejan sin tocar). Verificado contra los 1.886 contratos ya atribuidos al
    municipio "Murcia" en local: 736 clasificados como CCAA, sin falsos
    positivos evidentes entre ayuntamientos/consorcios/mancomunidades (ver
    INFORME_NOCHE.md 2026-07-23). Los organismos ESTATALES que también se
    cuelan hoy en "Murcia" por el mismo bug de texto libre (Guardia Civil,
    AEAT, TGSS, INSS, Universidad de Murcia...) no encajan aquí ni en
    ningún otro bucket -- quedan documentados como pendiente, no se tocan."""
    n = normalizar(organo)
    if not _RE_ORGANO_CCAA_MURCIA.search(n):
        return False
    return not any(kw in n for kw in _EXCLUIR_ORGANO_CCAA_MURCIA)


def _separar_contratos_ccaa_murcia(contratos):
    """Separa una lista de contratos ya atribuidos al municipio "Murcia" en
    (municipales, ccaa) según _es_organo_ccaa_murcia."""
    municipales, ccaa = [], []
    for c in contratos:
        (ccaa if _es_organo_ccaa_murcia(c.get("organo", "")) else municipales).append(c)
    return municipales, ccaa


def _guardar_pseudo_municipio_ccaa(provincia, contratos_ccaa, job_id=None):
    """Guarda los contratos de la CCAA (separados de un municipio real, ver
    _separar_contratos_ccaa_murcia) bajo la entrada pseudo-municipio de esa
    provincia, tratada en el resto de la app igual que un ayuntamiento más
    (mismas tablas/listados), pero sin alcalde ni perfil PLACE propio. Se
    recalcula entera en cada refresco del municipio real del que procede
    (hoy solo "Murcia" capital) -- no necesita fusión propia con histórico
    porque siempre deriva del histórico ya fusionado de ese municipio."""
    nombre = MUNICIPIOS_PSEUDO.get(provincia)
    if not nombre:
        return
    resultado = {
        "municipio":       nombre,
        "organismo":       "Comunidad Autónoma de la Región de Murcia" if provincia == "murcia" else nombre,
        "total_contratos": len(contratos_ccaa),
        "contratos":       contratos_ccaa,
        "alertas":         analizar_riesgo(contratos_ccaa),
        "place_profile":   "",
        "timestamp":       time.time(),
    }
    if job_id:
        _log(job_id, f"  {len(contratos_ccaa)} contratos reclasificados a "
                      f"'{nombre}' (órgano = CCAA, no ayuntamiento)")
    with _datos_lock:
        _datos_memoria[:] = [d for d in _datos_memoria if normalizar(d.get("municipio", "")) != normalizar(nombre)]
        _datos_memoria.append(resultado)
    _db_set_municipio(nombre, resultado, provincia=provincia)


# ─── AGE (Administración General del Estado) ─────────────────────────────────
# Detección por patrones de texto del ÓRGANO contratante (no del objeto), medida
# contra los contratos reales ya atribuidos a municipios de Murcia en cache.db
# (ver INFORME_NOCHE.md 2026-07-25): 226 en "Murcia" capital + 4 duplicados del
# Centro Penitenciario Murcia II en "Campos del Río". Cada patrón corresponde a
# un órgano estatal periférico realmente presente en los datos; se añaden unos
# pocos patrones extra igual de inequívocos (Policía Nacional, DGT/Tráfico,
# Confederación Hidrográfica del Segura, Ministerios, Defensa) por robustez ante
# futuros refrescos, todos elegidos para no chocar con órganos municipales.
_AGE_KEYWORDS = (
    "guardia civil",
    "agencia estatal de administracion tributaria",
    "instituto social de la marina",
    "delegacion del gobierno",
    "subdelegacion del gobierno",
    "tesoreria general de la seguridad social",
    "instituto nacional de la seguridad social",
    "centro penitenciario",
    "centro de insercion social",
    "servicio publico de empleo estatal",
    "confederacion hidrografica del segura",
    "jefatura provincial de trafico",
    "jefatura de trafico",
    "direccion general de trafico",
    "policia nacional",
    "cuerpo nacional de policia",
    "direccion general de la policia",
    "ministerio de ",
    "ministerio del ",
    "subdelegacion de defensa",
    "delegacion de defensa",
)
# Siglas como token aislado (\b) + las Delegaciones (Especiales) de Economía y
# Hacienda del Estado (periféricas del Ministerio de Hacienda; distintas de una
# "Consejería de Economía y Hacienda" autonómica, que queda excluida abajo).
_AGE_REGEX = re.compile(
    r"\btgss\b|\binss\b|\baeat\b|\bsepe\b|"
    r"delegacion (especial )?de economia y hacienda"
)
# Excluye explícitamente lo que NO es AGE aunque comparta alguna palabra: el
# propio Ayuntamiento y sus empresas municipales, la CCAA (Consejerías / "Región
# de Murcia"), y los entes conjuntos de varios municipios (mancomunidad /
# consorcio / diputación / junta vecinal). Ver encargo, punto 3.
_AGE_EXCLUIR = (
    "ayuntamiento", "alcaldia", "consejeria", "region de murcia",
    "regional de murcia", "mancomunidad", "consorcio", "empresa municipal",
    "junta vecinal", "diputacion",
)


def _es_organo_age(organo):
    """True si el órgano contratante es un organismo de la Administración
    General del Estado que se ha colado en un municipio murciano por el bug
    de subcadena. Excluye ayuntamientos, empresas municipales, la CCAA y
    entes conjuntos aunque compartan alguna palabra clave. La Universidad de
    Murcia tiene su propio detector (_es_organo_umu, no AGE en sentido
    estricto -- ver INFORME_NOCHE.md)."""
    n = normalizar(organo)
    if any(kw in n for kw in _AGE_EXCLUIR):
        return False
    if any(kw in n for kw in _AGE_KEYWORDS):
        return True
    return bool(_AGE_REGEX.search(n))


def _separar_contratos_age(contratos):
    """Separa una lista de contratos de un municipio murciano en (resto, age)
    según _es_organo_age."""
    resto, age = [], []
    for c in contratos:
        (age if _es_organo_age(c.get("organo", "")) else resto).append(c)
    return resto, age


def _guardar_pseudo_municipio_acumulado(nombre_pseudo, municipio_origen, contratos_extra, job_id=None):
    """Acumula contratos separados de un municipio murciano bajo una entrada
    pseudo-municipio (AGE, Universidad de Murcia...), tratada en el resto de
    la app igual que un ayuntamiento más.

    A diferencia de "Región de Murcia" (que solo procede de un municipio,
    Murcia capital), estas entradas pueden recibir contratos de VARIOS
    municipios en un mismo refresco completo (p.ej. la AGE: Murcia capital +
    Campos del Río, este último con duplicados del mismo centro
    penitenciario). Por eso acumula en vez de sustituir: cada contrato se
    etiqueta con `_origen_muni`; al refrescar un municipio se reemplaza SOLO
    su aportación anterior (para que no queden restos si un contrato deja de
    encajar) y se deduplica por URL/título, así los duplicados que llegan por
    dos municipios distintos colapsan en uno.

    Se llama para TODOS los municipios de origen (incluso con lista vacía,
    para poder limpiar la aportación previa de ese municipio); si tras la
    fusión no queda ningún contrato y no había entrada previa, no crea una
    vacía."""
    origen = normalizar(municipio_origen)
    for c in contratos_extra:
        c["_origen_muni"] = origen

    with _datos_lock:
        prev = next((d for d in _datos_memoria
                     if normalizar(d.get("municipio", "")) == normalizar(nombre_pseudo)), None)
        conservados = [c for c in (prev.get("contratos", []) if prev else [])
                       if c.get("_origen_muni") != origen]

    fusionados = _dedup_contratos_por_url(conservados + list(contratos_extra))

    if not fusionados and prev is None:
        return

    resultado = {
        "municipio":       nombre_pseudo,
        "organismo":       nombre_pseudo,
        "total_contratos": len(fusionados),
        "contratos":       fusionados,
        "alertas":         analizar_riesgo(fusionados),
        "place_profile":   "",
        "timestamp":       time.time(),
    }
    if job_id and contratos_extra:
        _log(job_id, f"  {len(contratos_extra)} contratos de '{municipio_origen}' "
                      f"reclasificados a '{nombre_pseudo}' -- total ahora: {len(fusionados)}")
    with _datos_lock:
        _datos_memoria[:] = [d for d in _datos_memoria
                             if normalizar(d.get("municipio", "")) != normalizar(nombre_pseudo)]
        _datos_memoria.append(resultado)
    _db_set_municipio(nombre_pseudo, resultado, provincia="murcia")


def _guardar_pseudo_municipio_age(municipio_origen, contratos_age, job_id=None):
    """Acumula los contratos de la AGE separados de un municipio murciano bajo
    la entrada pseudo-municipio "Administración General del Estado". Ver
    _guardar_pseudo_municipio_acumulado."""
    _guardar_pseudo_municipio_acumulado(NOMBRE_PSEUDO_AGE, municipio_origen, contratos_age, job_id)


def _es_organo_umu(organo):
    """True si el órgano contratante es la Universidad de Murcia, colada en
    el municipio "Murcia" por el mismo bug de subcadena que la AGE (ver
    _es_organo_age). Se separa en su propia entrada porque es una
    universidad pública AUTÓNOMA, no AGE en sentido estricto -- pesaba el
    64% de esa entrada antes de separarla (ver INFORME_NOCHE.md)."""
    return "universidad de murcia" in normalizar(organo)


def _separar_contratos_umu(contratos):
    """Separa una lista de contratos de un municipio murciano en (resto, umu)
    según _es_organo_umu."""
    resto, umu = [], []
    for c in contratos:
        (umu if _es_organo_umu(c.get("organo", "")) else resto).append(c)
    return resto, umu


def _guardar_pseudo_municipio_umu(municipio_origen, contratos_umu, job_id=None):
    """Acumula los contratos de la Universidad de Murcia separados de un
    municipio murciano bajo su propia entrada pseudo-municipio. Ver
    _guardar_pseudo_municipio_acumulado."""
    _guardar_pseudo_municipio_acumulado(NOMBRE_PSEUDO_UMU, municipio_origen, contratos_umu, job_id)


def _asegurar_pseudo_municipio_fondos(provincia):
    """Crea (si no existe ya) la entrada pseudo-municipio de una provincia
    con 0 contratos propios, solo para que aparezca en el listado general y
    su ficha de detalle no dé "municipio no encontrado" cuando lo único que
    tiene son fondos UE cruzados (hoy, "Provincia de Girona" -- "Región de
    Murcia" ya se crea con contratos reales en _guardar_pseudo_municipio_ccaa
    y esta función no la sobrescribe). Se llama al arrancar y tras cada
    refresco de fondos UE."""
    nombre = MUNICIPIOS_PSEUDO.get(provincia)
    if not nombre:
        return
    with _datos_lock:
        ya_existe = any(normalizar(d.get("municipio", "")) == normalizar(nombre) for d in _datos_memoria)
    if ya_existe:
        return
    resultado = {
        "municipio":       nombre,
        "organismo":       nombre,
        "total_contratos": 0,
        "contratos":       [],
        "alertas":         [],
        "place_profile":   "",
        "timestamp":       time.time(),
    }
    with _datos_lock:
        _datos_memoria.append(resultado)
    _db_set_municipio(nombre, resultado, provincia=provincia)


def fmt_eur(valor_str):
    try:
        n = float(str(valor_str).replace(",", "."))
        return f"{n:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(valor_str)


def fmt_num(valor):
    try:
        return f"{int(round(float(valor))):,}".replace(",", ".")
    except Exception:
        return str(valor)


_MESES_ES = ["ene", "feb", "mar", "abr", "may", "jun",
             "jul", "ago", "sep", "oct", "nov", "dic"]


def fmt_fecha_corta(ts):
    """'29 jul 2026' a partir de un epoch -- evita depender del locale del
    sistema (Render/gunicorn no garantiza es_ES instalado)."""
    if not ts:
        return ""
    d = datetime.fromtimestamp(ts)
    return f"{d.day} {_MESES_ES[d.month - 1]} {d.year}"


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

# Códigos de TenderResultCode-2.09 (PLACE) que significan que NO hubo
# adjudicatario por decisión de la fuente (no es un fallo de nuestro cruce):
# 3 Desierto · 4 Desistimiento · 5 Renuncia · 6 Desierto provisional ·
# 7 Desierto definitivo. Los códigos 1/2/8/9/10 sí tienen adjudicatario.
_RESULTADO_SIN_ADJUDICATARIO = {"3", "4", "5", "6", "7"}

def _entry_to_contrato(entry_xml):
    """Convierte el XML crudo de un <entry> a dict de contrato. Retorna None si no relevante."""

    # ── estado primero (salida rápida) ────────────────────────────────────────
    estado = ""
    m = re.search(r'ContractFolderStatusCode[^>]*>\s*([A-Z]{2,4})\s*<', entry_xml, re.I)
    if m:
        estado = m.group(1).upper()

    # ── resultado de la licitación (TenderResultCode-2.09) ────────────────────
    # Distingue los concursos SIN adjudicatario por decisión de la fuente
    # (desierto/desistimiento/renuncia, ver _RESULTADO_SIN_ADJUDICATARIO) de
    # aquellos donde sí hubo adjudicatario pero no lo hemos podido extraer.
    # Solo lo publica PLACE; BORM/PSCP no traen este código. Ver analizar_riesgo
    # e INFORME_NOCHE.md 2026-07-25.
    resultado_code = ""
    m_rc = re.search(r'ResultCode[^>]*>\s*(\d+)\s*<', entry_xml, re.I)
    if m_rc:
        resultado_code = m_rc.group(1)

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
        "resultado_code": resultado_code,
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
    """Procesa los atom files de un ZIP en paralelo, leyendo cada uno bajo
    demanda dentro de cada worker -- NO carga el ZIP completo descomprimido
    en RAM de golpe antes de empezar. Un ZIP mensual de PLACE puede rondar
    el GB descomprimido en varios cientos de archivos; cargarlos todos a
    la vez (multiplicado por los varios ZIPs que _job_run procesa en
    paralelo) agotaba la RAM del plan free de Render y mataba el proceso a
    media faena -- confirmado en producción reprocesando Murcia (ver
    INFORME_NOCHE.md, 2026-07-21). Verificado en local con ZIPs reales:
    mismos contratos encontrados que antes, con un pico de memoria por ZIP
    ~39x menor (2.131 MB -> 55 MB en un ZIP de 142 archivos / 2,1 GB
    descomprimidos)."""
    nombre = os.path.basename(zip_path)
    muni_re = re.compile(rf'\b{re.escape(normalizar(municipio))}\b')

    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            atom_names = [n for n in z.namelist() if n.endswith(".atom")]
    except Exception as e:
        _log(job_id, f"Error abriendo {nombre}: {e}")
        return []

    total = len(atom_names)
    _log(job_id, f"  Procesando {total} archivos de {nombre}…")

    contratos_total = []
    lock = threading.Lock()
    procesados = [0]

    def _procesar(name):
        # Cada hilo abre su propia instancia de ZipFile -- zipfile.ZipFile
        # no es seguro para lecturas concurrentes desde una única instancia
        # compartida entre hilos.
        with zipfile.ZipFile(zip_path, "r") as z:
            raw = z.read(name)
        result = parsear_atom_bytes(raw, municipio, muni_re)
        with lock:
            procesados[0] += 1
            pct = int(100 * procesados[0] / total)
            if pct % 25 == 0 and pct > 0 and procesados[0] % (total // 4 or 1) == 0:
                n_enc = len(contratos_total)
                _log(job_id, f"  {nombre}: {pct}% — {n_enc} contratos encontrados")
        return result

    with ThreadPoolExecutor(max_workers=4) as ex:
        for parcial in ex.map(_procesar, atom_names):
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

    # Pool LOCAL, no el HTTP_POOL compartido: buscar_en_borm ya se envía a
    # HTTP_POOL.submit(...) desde _job_run, así que reentrar en el mismo
    # pool aquí (como hacía antes) puede dejar todos sus workers ocupados
    # esperándose entre sí -- con suficiente concurrencia real, un
    # interbloqueo total del pool compartido (afectaría a todas las
    # peticiones que dependen de él, no solo a esta búsqueda). Mismo patrón
    # que ya usa buscar_en_zip.
    with ThreadPoolExecutor(max_workers=4) as ex:
        for c in ex.map(_fetch_y_parsear, candidatos):
            if c:
                contratos.append(c)

    _log(job_id, f"  BORM: {len(contratos)} contratos con datos extraídos")
    return contratos


# ─── PSCP — Plataforma de Serveis de Contractació Pública de Catalunya ──────
# (provincia de Girona). Fuente: dades obertes de la Generalitat, dataset
# "ybgg-dgi6" (Socrata/SODA API, sin autenticación). A diferencia de PLACE
# (ATOM) o BORM (HTML), la fila ya trae empresa/NIF/importe como columnas
# planas — no hace falta resolver ningún JSON de detalle. Ver diagnóstico en
# backend/diag_pscp_*.py.

_PSCP_FASE_A_ESTADO = {"Formalització": "FOR", "Adjudicació": "ADJ"}
_PSCP_FASE_PRIORIDAD = {"Formalització": 2, "Adjudicació": 1}


def _fila_pscp_a_contrato(fila):
    """Convierte una fila del dataset PSCP al mismo formato de contrato que
    usan PLACE y BORM."""
    nif = (fila.get("identificacio_adjudicatari") or "").strip()
    empresa = (fila.get("denominacio_adjudicatari") or "").strip()

    # UTEs (uniones temporales de empresas): PSCP publica todas las
    # empresas del consorcio en un único campo separadas por "||" (p.ej.
    # "TELEFÓNICA DE ESPAÑA SAU||ORANGE ESPAGNE SA"). Sin partir esto, el
    # texto conjunto (razones sociales y NIF pegados) no casa con ninguna
    # fuente de directivos. Usamos la primera empresa del consorcio como
    # entidad principal para el matching y guardamos el resto solo para
    # mostrarlo (ute_socios no participa en la búsqueda de directivo).
    ute_socios = []
    if "||" in empresa:
        empresas_ute = [e.strip() for e in empresa.split("||") if e.strip()]
        nifs_ute = [n.strip() for n in nif.split("||") if n.strip()]
        if empresas_ute:
            empresa = empresas_ute[0]
            nif = nifs_ute[0] if nifs_ute else ""
            ute_socios = empresas_ute[1:]

    # NIF enmascarado (p.ej. "*** 0336 **"): PSCP lo hace tanto con personas
    # físicas como, a veces, con empresas -- pero el nombre del adjudicatario
    # sí es legible y se mantiene (igual que un autónomo en Murcia: se
    # muestra el nombre aunque no haya NIF utilizable para cruzar registro).
    # Solo se marca "No localizada" cuando PSCP no publica ni el nombre.
    if not empresa:
        empresa, nif = "No localizada", ""
    elif "*" in nif:
        nif = ""

    importe_num = 0.0
    for campo in ("import_adjudicacio_amb_iva", "import_adjudicacio_sense"):
        try:
            v = fila.get(campo)
            if v not in (None, ""):
                importe_num = float(v)
                break
        except (TypeError, ValueError):
            pass

    enllac = fila.get("enllac_publicacio")
    url = enllac.get("url", "") if isinstance(enllac, dict) else (enllac or "")

    titulo = fila.get("denominacio", "") or fila.get("objecte_contracte", "") or ""

    return {
        "titulo":        titulo[:200],
        "organo":        fila.get("nom_organ", ""),
        "empresa":       empresa,
        "nif":           nif,
        "ute_socios":    ute_socios,
        "importe":       fmt_eur(str(importe_num)) if importe_num else "No localizado",
        "importe_num":   importe_num,
        "estado":        _PSCP_FASE_A_ESTADO.get(fila.get("fase_publicacio", ""), "ADJ"),
        "licitacion_id": fila.get("codi_expedient", ""),
        "url":           url,
        "fuente":        "PSCP",
        "directivo":     "",
        "cargo":         "",
    }


def _dedup_contratos_por_url(contratos):
    """Deduplica contratos por URL (o título si no hay URL). PLACE/BORM
    publican una URL por contrato -- ahí esto es un no-op salvo colisión
    real. PSCP a veces publica varias filas (multi-lote) bajo la MISMA
    enllac_publicacio, con solo alguna de ellas trayendo el adjudicatario
    resuelto (las demás pueden tener el NIF enmascarado en esa fila
    concreta); si la fila que ya tenemos para una URL no tiene empresa
    identificada y aparece otra que sí, la sustituye en vez de descartarla."""
    vistos = {}
    orden = []
    for c in contratos:
        key = c.get("url") or c.get("titulo", "")[:80]
        if not key:
            continue
        if key not in vistos:
            vistos[key] = c
            orden.append(key)
        elif (vistos[key].get("empresa") in ("No localizada", "")
              and c.get("empresa") not in ("No localizada", "")):
            vistos[key] = c
    return [vistos[k] for k in orden]


def _fusionar_historico_contratos(existentes, nuevos):
    """Fusiona el histórico ya guardado de un municipio con lo recién
    encontrado en un refresco -- NUNCA se pierde un contrato que ya estuviera
    guardado y que este refresco en concreto no haya vuelto a encontrar (ver
    INFORME_NOCHE.md 2026-07-22: el refresco sustitutivo anterior borró
    histórico real de al menos Archena cuando faltaba algún ZIP mensual
    antiguo de PLACE en caché en el momento del refresco). Aplica por igual a
    las tres fuentes (PLACE, BORM, PSCP) aunque el riesgo real detectado es
    solo de PLACE -- BORM y PSCP consultan en vivo su histórico completo en
    cada refresco, no dependen de caché local, así que para ellas esto es
    solo una red de seguridad adicional, no un fix necesario.

    Misma clave que _dedup_contratos_por_url (URL, o título truncado si no
    hay URL). Si la misma clave aparece en ambos lados, gana la versión
    NUEVA (dato más fresco: estado, enlace BORM, etc.) -- lo antiguo solo se
    conserva cuando el refresco actual no lo trae en absoluto."""
    combinados = {}
    orden = []
    for c in existentes:
        key = c.get("url") or c.get("titulo", "")[:80]
        if not key:
            continue
        if key not in combinados:
            orden.append(key)
        combinados[key] = c
    for c in nuevos:
        key = c.get("url") or c.get("titulo", "")[:80]
        if not key:
            continue
        if key not in combinados:
            orden.append(key)
        combinados[key] = c   # el nuevo siempre gana si la clave ya existía
    return [combinados[k] for k in orden]


_RECUPERACION_HISTORICO_MARCADOR = os.path.join(DATA_DIR, "recuperacion_historico_20260722.marker")


def _recuperar_historico_perdido():
    """Recuperación puntual (ver INFORME_NOCHE.md 2026-07-22): el cache.db
    commiteado en el repo (`_DB_SEED_FILE`) no se ha vuelto a tocar desde el
    commit c05918d (2026-07-19) -- es decir, conserva el histórico de
    contratos tal como estaba justo antes de que el bug de refresco
    sustitutivo empezara a truncar municipios al perderse ZIPs antiguos de
    PLACE en caché. Se fusiona (nunca sustituye, misma función ya verificada
    del fix) ese histórico "conocido bueno" con lo que haya AHORA MISMO en
    el disco de producción, municipio a municipio. Solo puede añadir o
    refrescar contratos, nunca puede quitar ninguno de los que ya hubiera en
    producción -- si un municipio no perdió nada, esto es un no-op. Se
    ejecuta una única vez (marcador en disco)."""
    if os.path.exists(_RECUPERACION_HISTORICO_MARCADOR):
        return
    if not os.path.exists(_DB_SEED_FILE) or os.path.abspath(_DB_SEED_FILE) == os.path.abspath(DB_FILE):
        return

    seed_db = sqlite3.connect(_DB_SEED_FILE)
    filas_seed = seed_db.execute("SELECT municipio, data, provincia FROM municipios").fetchall()
    seed_db.close()

    recuperados = []
    for muni_key, data_json, prov in filas_seed:
        try:
            seed_d = json.loads(data_json)
        except Exception:
            continue
        seed_contratos = seed_d.get("contratos", [])
        if not seed_contratos:
            continue

        with _db_lock:
            row = _db.execute("SELECT data FROM municipios WHERE municipio=?", (muni_key,)).fetchone()
        actual = json.loads(row[0]) if row else {}
        actual_contratos = actual.get("contratos", [])

        fusion = _fusionar_historico_contratos(actual_contratos, seed_contratos)
        if len(fusion) <= len(actual_contratos):
            continue  # nada que recuperar para este municipio

        nuevo = dict(actual) if actual else dict(seed_d)
        nuevo["contratos"] = fusion
        nuevo["total_contratos"] = len(fusion)
        nuevo["alertas"] = analizar_riesgo(fusion)
        with _db_lock:
            _db.execute(
                "INSERT INTO municipios (municipio, data, ts, provincia) VALUES (?,?,?,?) "
                "ON CONFLICT(municipio) DO UPDATE SET data=excluded.data, ts=excluded.ts, provincia=excluded.provincia",
                (muni_key, json.dumps(nuevo, ensure_ascii=False),
                 nuevo.get("timestamp", time.time()), prov or "murcia"),
            )
            _db.commit()
        recuperados.append((muni_key, len(actual_contratos), len(fusion)))

    with open(_RECUPERACION_HISTORICO_MARCADOR, "w") as f:
        f.write(f"{time.time()}\n")
    if recuperados:
        print(f"[startup] Recuperación de histórico perdido: {len(recuperados)} municipios "
              f"recibieron contratos recuperados del seed del repo (municipio, antes, después): "
              f"{recuperados}", flush=True)
    else:
        print("[startup] Recuperación de histórico: comprobado, ningún municipio necesitaba "
              "recuperación (todos igual o más completos que el seed del repo).", flush=True)


def _dedup_pscp_fases(filas):
    """El mismo lote pasa por fase Adjudicació y luego Formalització, así que
    el dataset publica una fila por cada una. Nos quedamos con la más
    avanzada (Formalització) para no contar el mismo contrato dos veces."""
    mejores = {}
    for f in filas:
        clave = (f.get("codi_expedient", ""), f.get("numero_lot", ""),
                 f.get("identificacio_adjudicatari", ""))
        actual = mejores.get(clave)
        if actual is None or (_PSCP_FASE_PRIORIDAD.get(f.get("fase_publicacio"), 0)
                               > _PSCP_FASE_PRIORIDAD.get(actual.get("fase_publicacio"), 0)):
            mejores[clave] = f
    return list(mejores.values())


def buscar_en_pscp(municipio, job_id=None):
    """Busca contratos adjudicados/formalizados del Ajuntament del municipio
    dado en la Plataforma de Serveis de Contractació Pública de Catalunya
    (vía el espejo de dades obertes, dataset ybgg-dgi6)."""
    ine10 = MUNICIPIOS_GIRONA_INE.get(municipio, "")
    if not ine10:
        _log(job_id, f"  PSCP: municipio sin codi_ine10 mapeado ({municipio})")
        return []

    _log(job_id, "Consultando PSCP (Plataforma de contractació pública de Catalunya)…")
    filas = []
    limit, offset = 1000, 0
    while True:
        try:
            r = session.get(PSCP_URL, params={
                "$where": f"codi_ine10='{ine10}' AND fase_publicacio in ({PSCP_FASES})",
                "$order": "codi_expedient",
                "$limit": limit,
                "$offset": offset,
            }, timeout=HTTP_TIMEOUT * 4)  # SODA puede tardar más que PLACE/BORM
            if r.status_code != 200:
                _log(job_id, f"  PSCP: HTTP {r.status_code}")
                break
            pagina = r.json()
        except Exception as e:
            _log(job_id, f"  PSCP no disponible ({type(e).__name__})")
            break

        if not pagina:
            break
        filas += pagina
        if len(pagina) < limit:
            break
        offset += limit

    filas = _dedup_pscp_fases(filas)
    contratos = [_fila_pscp_a_contrato(f) for f in filas]
    _log(job_id, f"  PSCP: {len(contratos)} contratos encontrados")
    return contratos


# ─── RPC — Registre Públic de Contractes (contractes menors, Girona) ────────
# Fuente: dades obertes de la Generalitat, dataset "hb6v-jcbf" (Socrata/SODA,
# mismo dominio analisi.transparenciacatalunya.cat que PSCP). A diferencia de
# PSCP (ybgg-dgi6, solo procediments formals Adjudicació/Formalització), este
# dataset es el registro general de contratos y aquí se filtra específicamente
# a procediment_adjudicacio='Menor' -- disjunto por definición legal de lo que
# ya trae PSCP, así que no se solapa con los contratos ya indexados.
#
# id_organisme_contractant usa el MISMO código de 10 dígitos que
# MUNICIPIOS_GIRONA_INE (verificado en vivo: Girona capital = 1707920002,
# Setcases = 1719250006) -- se reutiliza ese mapeo, no hace falta ninguno nuevo.
#
# Volumen medido en vivo (2026-08-03): ~194.000 filas "Menor" históricas para
# toda la provincia de Girona -- viable en SQLite, pero demasiado para el flujo
# de scraping por clic (buscar_en_pscp) que corre en vivo en cada visita/
# actualización de un municipio. Por eso esta fuente vive en su propia tabla
# (contratos_menors_locales, compartida con otras fuentes de contratos
# menores locales -- ver _db_init) y se refresca con un job periódico (mismo
# patrón que fondos_ue), no dentro de _job_run.
#
# Decisión 2026-08-03 (César): histórico desde 2021 en adelante, sin umbral de
# importe (se guarda todo), sección propia colapsable en la ficha de municipio.
RPC_MENORS_URL = "https://analisi.transparenciacatalunya.cat/resource/hb6v-jcbf.json"
RPC_MENORS_DESDE_ANY = 2021


def _variantes_nombre_para_detector(nombre):
    """Genera variantes de orden de un nombre para PROBARLAS contra el índice
    de cargos públicos (nunca para decidir qué se muestra en pantalla --
    adjudicatari/proveedor se muestra siempre tal cual viene de la fuente).

    Dos patrones de inversión medidos en producción (2026-08-03), cada uno en
    una fuente de contratos menores distinta:
    - Girona (RPC): 'Apellidos, Nombre' CON coma (p.ej. 'VIAL TAULERA, MIREIA').
    - Molina de Segura (Murcia): 'Apellidos Nombre' SIN coma (p.ej.
      'GALERA FERNANDEZ NOE', confirmado cruzando contra el objeto del
      contrato que sí menciona 'D. Noé Galera Fernández' en orden correcto).

    El índice de cargos públicos (ALCALDES_CONCEJALES) espera 'Nombre
    Apellido1 Apellido2', con coincidencia EXACTA de cadena -- ver
    _detectar_coincidencia_cargo. Sin estas variantes, el detector nunca
    dispararía sobre las fuentes con nombre invertido.

    OJO: el patrón 'X, Y' aparece también en nombres de empresa (p.ej.
    'PLANTERS ROVIRA, SCP', donde SCP es forma jurídica, no nombre de pila), y
    la heurística "último token al principio" (sin coma) puede fallar con
    nombres compuestos (p.ej. 'María José'). Es un riesgo aceptado: como el
    detector exige coincidencia exacta de nombre completo, una variante de
    más nunca genera un falso positivo nuevo, solo puede añadir cobertura."""
    nombre = (nombre or "").strip()
    variantes = [nombre]
    if "," in nombre:
        izq, _, der = nombre.partition(",")
        invertido = f"{der.strip()} {izq.strip()}".strip()
        if invertido:
            variantes.append(invertido)
    else:
        tokens = nombre.split()
        if len(tokens) >= 3:
            invertido = f"{tokens[-1]} {' '.join(tokens[:-1])}".strip()
            if invertido:
                variantes.append(invertido)
    return variantes


def _dedup_rpc_menors(filas):
    """codi_expedient ya viene casi único de la fuente (verificado: solo 5
    colisiones de ~28.000 expedientes 'Menor' de Girona capital) -- a
    diferencia de PSCP no hace falta lógica de prioridad de fases, basta con
    quedarse con la fila 'liquidació' si hay colisión (estado más completo/final)."""
    mejores = {}
    for f in filas:
        clave = f.get("codi_expedient", "")
        if not clave:
            continue
        actual = mejores.get(clave)
        if actual is None or (f.get("situaci_contractual") == "liquidació"
                               and actual.get("situaci_contractual") != "liquidació"):
            mejores[clave] = f
    return list(mejores.values())


def _fila_rpc_menor_a_registro(fila, municipio):
    """Convierte una fila del dataset RPC al formato que guarda
    contratos_menors_locales. Sin NIF (la fuente no lo publica) y sin URL por
    expediente (la fuente no publica un enlace público por registro).

    OJO -- codi_expedient NO es único a nivel global: muchos municipios
    pequeños comparten el mismo software/numeración de expedientes (medido en
    producción 2026-08-03: 'X2022000056' aparece en más de 10 ayuntamientos
    distintos -- Canet d'Adri, Palau-sator, Maçanet de la Selva, Osor,
    Susqueda...). Usar solo codi_expedient como id causaba que, al procesar
    los 221 municipios uno detrás de otro, un municipio posterior en
    MUNICIPIOS_GIRONA sobrescribiera silenciosamente los contratos de un
    municipio anterior con el mismo código (147 de 221 municipios afectados,
    ~15% de filas perdidas en el primer backfill). El id se namespacea con el
    municipio para que la clave primaria sea única de verdad."""
    try:
        importe_num = float(fila.get("import_adjudicacio") or 0)
    except (TypeError, ValueError):
        importe_num = 0.0
    return {
        "id":               f"{municipio}::{fila.get('codi_expedient', '')}",
        "municipio":        municipio,
        "provincia":        "girona",
        "fuente":           "rpc-girona",
        "organisme":        fila.get("organisme_contractant", ""),
        "adjudicatari":     (fila.get("adjudicatari") or "").strip(),
        "nif":              "",
        "import_num":       importe_num,
        "data_adjudicacio": (fila.get("data_adjudicacio") or "")[:10],
        "tipus_contracte":  fila.get("tipus_contracte", ""),
        "descripcio":       (fila.get("descripcio_expedient") or "").strip(),
        "codi_cpv":         fila.get("codi_cpv", ""),
        "exercici":         fila.get("exercici", ""),
    }


def buscar_en_rpc_menors(municipio, job_id=None):
    """Busca contractes menors del Ajuntament del municipio dado en el
    Registre Públic de Contractes (dataset hb6v-jcbf), desde
    RPC_MENORS_DESDE_ANY en adelante."""
    ine10 = MUNICIPIOS_GIRONA_INE.get(municipio, "")
    if not ine10:
        _log(job_id, f"  RPC: municipio sin codi_ine10 mapeado ({municipio})")
        return []

    _log(job_id, "Consultando RPC (Registre Públic de Contractes, contractes menors)…")
    filas = []
    limit, offset = 1000, 0
    while True:
        try:
            r = session.get(RPC_MENORS_URL, params={
                "$where": (f"id_organisme_contractant='{ine10}' AND "
                           f"procediment_adjudicacio='Menor' AND "
                           f"exercici >= '{RPC_MENORS_DESDE_ANY}'"),
                "$order": "codi_expedient",
                "$limit": limit,
                "$offset": offset,
            }, timeout=HTTP_TIMEOUT * 4)  # SODA puede tardar más que PLACE/BORM
            if r.status_code != 200:
                _log(job_id, f"  RPC: HTTP {r.status_code}")
                break
            pagina = r.json()
        except Exception as e:
            _log(job_id, f"  RPC no disponible ({type(e).__name__})")
            break

        if not pagina:
            break
        filas += pagina
        if len(pagina) < limit:
            break
        offset += limit

    filas = _dedup_rpc_menors(filas)
    registros = [_fila_rpc_menor_a_registro(f, municipio) for f in filas]
    _log(job_id, f"  RPC: {len(registros)} contractes menors encontrados")
    return registros


def _guardar_contratos_menors_locales(registros):
    """Inserta/actualiza filas en contratos_menors_locales (mismo patrón que
    _guardar_fondos_ue: misma clave = mismo registro, se sobrescribe con el
    dato más reciente). Compartida por todas las fuentes de contratos menores
    locales (Girona RPC, Fuente Álamo, Mula, Molina de Segura...) -- cada
    registro trae su propio 'provincia'/'fuente' para distinguir origen."""
    if not registros:
        return
    ahora = time.time()
    with _db_lock:
        for r in registros:
            _db.execute(
                """INSERT INTO contratos_menors_locales
                   (id, municipio, provincia, fuente, organisme, adjudicatari, nif,
                    import_num, data_adjudicacio, tipus_contracte, descripcio, codi_cpv,
                    exercici, ts)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     municipio=excluded.municipio, provincia=excluded.provincia,
                     fuente=excluded.fuente, organisme=excluded.organisme,
                     adjudicatari=excluded.adjudicatari, nif=excluded.nif,
                     import_num=excluded.import_num,
                     data_adjudicacio=excluded.data_adjudicacio,
                     tipus_contracte=excluded.tipus_contracte, descripcio=excluded.descripcio,
                     codi_cpv=excluded.codi_cpv, exercici=excluded.exercici, ts=excluded.ts""",
                (r["id"], r["municipio"], r.get("provincia", ""), r.get("fuente", ""),
                 r["organisme"], r["adjudicatari"], r.get("nif", ""), r["import_num"],
                 r["data_adjudicacio"], r["tipus_contracte"], r["descripcio"], r["codi_cpv"],
                 r["exercici"], ahora),
            )
        _db.commit()


def _db_contratos_menors_por_municipio(municipio):
    """Lee contratos_menors_locales para un municipio exacto -- se usa para
    mostrar la sección colapsable de contratos menores en la ficha del
    ayuntamiento (cualquier fuente: Girona RPC, Fuente Álamo, Mula, Molina de
    Segura...)."""
    with _db_lock:
        rows = _db.execute(
            "SELECT id, municipio, provincia, fuente, organisme, adjudicatari, nif, "
            "import_num, data_adjudicacio, tipus_contracte, descripcio, codi_cpv, exercici, ts "
            "FROM contratos_menors_locales WHERE municipio=? ORDER BY data_adjudicacio DESC",
            (municipio,),
        ).fetchall()
    cols = ("id", "municipio", "provincia", "fuente", "organisme", "adjudicatari", "nif",
            "import_num", "data_adjudicacio", "tipus_contracte", "descripcio", "codi_cpv",
            "exercici", "ts")
    return [dict(zip(cols, r)) for r in rows]


def actualizar_contratos_menors_girona(job_id=None):
    """Refresca contratos_menors_locales (filas de Girona/RPC) para los 221
    municipios de Girona, uno detrás de otro (mismo dataset, un municipio por
    consulta filtrada por id_organisme_contractant -- no tiene sentido
    paralelizar de más contra la misma API pública)."""
    total = 0
    for municipio in MUNICIPIOS_GIRONA:
        registros = buscar_en_rpc_menors(municipio, job_id)
        _guardar_contratos_menors_locales(registros)
        total += len(registros)
    _log(job_id, f"RPC: {total} contractes menors guardados en total ({len(MUNICIPIOS_GIRONA)} municipios).")
    return total


def _actualizar_contratos_menors_girona_bg(job_id):
    """Hilo de fondo para POST /actualizar-contratos-menors-girona. Mismo
    patrón que _actualizar_fondos_ue_bg: un lock para no lanzar dos refrescos
    a la vez, y log de progreso vía _jobs."""
    if not _actualizando_rpc_menors_lock.acquire(blocking=False):
        with _jobs_lock:
            _jobs[job_id] = {"status": "error", "log": [],
                              "error": "Ya hay un refresco de contratos menors Girona en curso."}
        return

    try:
        with _jobs_lock:
            _jobs[job_id] = {"status": "running", "log": [], "error": None}
        total = actualizar_contratos_menors_girona(job_id)
        with _jobs_lock:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["total"] = total
        print(f"  [actualizar-contratos-menors-girona] Terminado: {total} contractes menors.", flush=True)
    except Exception as e:
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(e)
    finally:
        _actualizando_rpc_menors_lock.release()


# ─── CONTRATOS MENORES -- FUENTE ÁLAMO DE MURCIA (portal propio, CSV) ────────
# A diferencia de Girona (API pública), esta es la web propia del ayuntamiento
# publicando un CSV/XLSX/PDF por trimestre -- sin API, hay que scrapear la
# página de listado en cada refresco porque las URLs de los ficheros NO son
# predecibles (nombre y carpeta de subida varían de forma inconsistente entre
# trimestres, verificado 2026-08-03: mismo contenido aparece subido en
# carpetas de un año distinto al que describe). El CSV es la variante elegida
# (frente a PDF/XLSX que la página también ofrece) porque no necesita ninguna
# dependencia nueva -- solo el módulo `csv` de la librería estándar -- así que
# esta fuente SÍ puede vivir en el cron diario automático (a diferencia de
# Mula/Molina de Segura, que necesitan odfpy/openpyxl y de momento se quedan
# en el patrón manual/periódico, ver actualizar_contratos_menores_murcia_manual.py).
#
# Formato real verificado descargando un CSV: delimitador ';', codificación
# ISO-8859-1 (no UTF-8), columnas "Expediente; Tipos de contrato;
# Adjudicatario; Objeto; Duración; Importe...sin IVA; IVA; Precio
# adjudicación...; Importe total; Fecha de aprobación/adjudicación; Petición
# de ofertas; Publicidad; DECRETO GASTOS/JGL". Sin NIF/CIF. Nombres de
# personas físicas en orden correcto ("Nombre Apellido1 Apellido2") -- a
# diferencia de Molina de Segura, no hace falta ninguna variante invertida.
FUENTEALAMO_LISTADO_URL = "https://ayto-fuentealamo.es/transparencia/transparencia-contratos-convenios-y-subvenciones/contratos-menores/"
FUENTEALAMO_DESDE_ANY = 2021


def _listar_csv_fuentealamo(job_id=None):
    """Scrapea la página de listado y devuelve las URLs de todos los CSV de
    contratos menores encontrados (no se puede adivinar la URL por
    año/trimestre, ver nota del módulo)."""
    try:
        r = session.get(FUENTEALAMO_LISTADO_URL, timeout=HTTP_TIMEOUT * 4)
        if r.status_code != 200:
            _log(job_id, f"  Fuente Álamo: HTTP {r.status_code} en la página de listado")
            return []
    except Exception as e:
        _log(job_id, f"  Fuente Álamo: página de listado no disponible ({type(e).__name__})")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    urls = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith(".csv") and "menor" in href.lower():
            urls.append(href)
    return sorted(set(urls))


def _parsear_csv_fuentealamo(contenido, url_origen):
    """Parsea un CSV de contratos menores de Fuente Álamo (';' delimitado,
    ISO-8859-1) y devuelve registros ya normalizados al formato de
    contratos_menors_locales, filtrados a FUENTEALAMO_DESDE_ANY en adelante."""
    import csv as _csv
    texto = contenido.decode("iso-8859-1", errors="replace")
    registros = []
    for fila in _csv.DictReader(texto.splitlines(), delimiter=";"):
        expediente = (fila.get("Expediente") or "").strip()
        adjudicatario = (fila.get("Adjudicatario") or "").strip()
        fecha_raw = (fila.get("Fecha de aprobación del gasto/fecha de adjudicación") or "").strip()
        if not expediente or not adjudicatario:
            continue
        # Fecha viene "DD/MM/AAAA" -- reconvertir a "AAAA-MM-DD" (mismo
        # formato que el resto de la app) solo para mostrar; el año para el
        # FILTRO se saca preferentemente del expediente ("NNNN/AAAA" o
        # "NNNN-AAAA"), más fiable que la fecha libre -- verificado en
        # producción: alguna fila trae la fecha con año claramente erróneo
        # (p.ej. "26/12/2027" en un expediente de 2024) o el propio expediente
        # en orden invertido ("AAAA/NNNN"). Cualquier año fuera de un rango
        # razonable se descarta como no fiable (se excluye la fila, más
        # seguro que arriesgarse a colar algo anterior a 2021 sin saberlo).
        fecha_iso = ""
        m_fecha = re.match(r"(\d{2})/(\d{2})/(\d{4})", fecha_raw)
        if m_fecha:
            dia, mes, anio_fecha = m_fecha.groups()
            fecha_iso = f"{anio_fecha}-{mes}-{dia}"
        else:
            anio_fecha = ""

        anio = ""
        m_exp = re.search(r"[/-](\d{4})$", expediente)
        if m_exp and 2000 <= int(m_exp.group(1)) <= 2035:
            anio = m_exp.group(1)
        elif anio_fecha and 2000 <= int(anio_fecha) <= 2035:
            anio = anio_fecha

        if not anio or int(anio) < FUENTEALAMO_DESDE_ANY:
            continue

        def _num(campo):
            try:
                return float((fila.get(campo) or "0").replace(".", "").replace(",", "."))
            except (TypeError, ValueError):
                return 0.0

        registros.append({
            "id":               f"Fuente Alamo de Murcia::{expediente}",
            "municipio":        "Fuente Álamo de Murcia",
            "provincia":        "murcia",
            "fuente":           "fuente-alamo",
            "organisme":        "Ayuntamiento de Fuente Álamo de Murcia",
            "adjudicatari":     adjudicatario,
            "nif":              "",
            "import_num":       _num("Importe total") or _num(" Precio de adjudicación  sin I.V.A. y otros impuestos indirectos  "),
            "data_adjudicacio": fecha_iso,
            "tipus_contracte":  (fila.get("Tipos de contrato") or "").strip(),
            "descripcio":       (fila.get("Objeto") or "").strip(),
            "codi_cpv":         "",
            "exercici":         anio,
        })
    return registros


def buscar_en_fuentealamo_menores(job_id=None):
    """Descubre y descarga todos los CSV de contratos menores de Fuente Álamo
    de Murcia, y devuelve los registros ya normalizados desde
    FUENTEALAMO_DESDE_ANY en adelante."""
    _log(job_id, "Consultando portal de transparencia de Fuente Álamo de Murcia…")
    urls = _listar_csv_fuentealamo(job_id)
    _log(job_id, f"  Fuente Álamo: {len(urls)} ficheros CSV encontrados en el listado")
    registros = []
    for url in urls:
        try:
            r = session.get(url, timeout=HTTP_TIMEOUT * 4)
            if r.status_code != 200:
                _log(job_id, f"  Fuente Álamo: HTTP {r.status_code} en {url}")
                continue
        except Exception as e:
            _log(job_id, f"  Fuente Álamo: {url} no disponible ({type(e).__name__})")
            continue
        registros += _parsear_csv_fuentealamo(r.content, url)
    _log(job_id, f"  Fuente Álamo: {len(registros)} contratos menores encontrados")
    return registros


def actualizar_contratos_menores_fuentealamo(job_id=None):
    registros = buscar_en_fuentealamo_menores(job_id)
    _guardar_contratos_menors_locales(registros)
    return len(registros)


def _actualizar_contratos_menores_fuentealamo_bg(job_id):
    """Hilo de fondo para POST /actualizar-contratos-menores-fuentealamo.
    Mismo patrón que _actualizar_contratos_menors_girona_bg."""
    if not _actualizando_menores_fuentealamo_lock.acquire(blocking=False):
        with _jobs_lock:
            _jobs[job_id] = {"status": "error", "log": [],
                              "error": "Ya hay un refresco de Fuente Álamo en curso."}
        return
    try:
        with _jobs_lock:
            _jobs[job_id] = {"status": "running", "log": [], "error": None}
        total = actualizar_contratos_menores_fuentealamo(job_id)
        with _jobs_lock:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["total"] = total
        print(f"  [actualizar-contratos-menores-fuentealamo] Terminado: {total} contratos menores.", flush=True)
    except Exception as e:
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(e)
    finally:
        _actualizando_menores_fuentealamo_lock.release()


# ─── FONDOS Y PROYECTOS FINANCIADOS POR LA UE ────────────────────────────────
# Dos fuentes oficiales, ambas de acceso libre sin autenticación (ver
# INFORME_NOCHE.md 2026-07-21/22 para el diagnóstico completo):
#
# - CORDIS (proyectos de investigación Horizon Europe 2021-2027): volcado
#   masivo CSV/JSON/XML en cordis.europa.eu/data/. Trae beneficiario, NIF
#   (con prefijo de país, ej. "ESB12345678"), NUTS, importe -- la fuente
#   más completa, compatible con el detector de coincidencias de nombre.
# - Cohesion Data / Kohesio (fondos estructurales FEDER/FSE 2014-2020): API
#   Socrata en cohesiondata.ec.europa.eu (mismo tipo de plataforma que
#   PSCP). Trae proyecto, importe, región y programa, pero NO el nombre
#   del beneficiario para España (confirmado: 0 de 139.395 registros
#   españoles tienen beneficiary_name relleno, aunque el campo sí existe
#   y se rellena para otros países) -- así que no se cruza con el detector.

# Cruce de cada registro de fondos_ue contra la lista canónica de municipios
# ya usada para contratos públicos (MUNICIPIOS_MURCIA/MUNICIPIOS_GIRONA), a
# partir del texto libre de ubicación que trae cada fuente -- ver
# INFORME_NOCHE.md 2026-07-22 para el porqué de las limitaciones por fuente:
# - CORDIS: el campo "city" de organization.csv ya es un nombre de ciudad
#   real (ej. "MURCIA", "Girona"), cruzable directamente.
# - Cohesion Data: el campo "region" es SIEMPRE a nivel provincial/regional
#   (ej. "Province of Girona", a veces varias regiones separadas por "|" en
#   programas de cooperación transfronteriza) -- verificado con datos reales,
#   nunca trae una ciudad concreta, así que el cruce por texto no encuentra
#   nada para esta fuente (comportamiento esperado, no un bug: son
#   operaciones a nivel región que deben quedarse solo en /fondos-ue, tal
#   como pide el encargo). Sí trae coordenadas (location_indicator_latitude_
#   longitude) que en teoría permitirían geolocalizar al municipio exacto,
#   pero construir esa correspondencia por coordenadas (centroides/límites de
#   los 264 municipios) es un desarrollo nuevo de más envergadura -- se deja
#   documentado como posible ampliación futura, no se implementa ahora.
_ARTICULOS_MUNICIPIO = ("l'", "la ", "el ", "els ", "les ")


def _clave_municipio_match(nombre):
    """Clave de comparación para cruzar el texto libre de ubicación de una
    fuente externa contra la lista canónica de municipios: normaliza y quita
    el artículo catalán, tanto en formato normal ("la Bisbal d'Empordà")
    como en el formato invertido tipo callejero que usa MUNICIPIOS_GIRONA
    ("Bisbal d'Empordà, la"), para que ambos casen con la misma clave."""
    n = normalizar(nombre)
    m = re.match(r"^(.*), (l'|la|el|els|les)$", n)
    if m:
        return m.group(1).strip()
    for art in _ARTICULOS_MUNICIPIO:
        if n.startswith(art):
            return n[len(art):].strip()
    return n.strip()


def _construir_indice_municipios_fondos_ue():
    idx = {"murcia": {}, "girona": {}}
    for m in MUNICIPIOS_MURCIA:
        idx["murcia"][_clave_municipio_match(m)] = m
    for m in MUNICIPIOS_GIRONA:
        idx["girona"][_clave_municipio_match(m)] = m
    return idx


_INDICE_MUNICIPIOS_FONDOS_UE = _construir_indice_municipios_fondos_ue()


_TEXTO_REGIONAL_GIRONA = "province of girona"


def _cruzar_municipio_fondo_ue(provincia, texto_ubicacion):
    """Intenta identificar el municipio canónico al que corresponde un
    proyecto/operación de fondos UE a partir del texto libre de ubicación de
    su fuente. Devuelve '' si no hay cruce fiable -- el proyecto se queda
    solo en /fondos-ue, no se fuerza a ningún municipio.

    Dos casos adicionales cruzan contra el pseudo-municipio de la provincia
    (ver MUNICIPIOS_PSEUDO) en vez de contra una ciudad concreta, para fondos
    de ámbito regional/provincial sin desglose municipal (ver INFORME_NOCHE.md
    2026-07-23 para el análisis de los datos reales que justifica cada regla):

    - Murcia: Cohesion Data (FEDER/FSE) sin "region" relleno -- confirmado en
      datos reales que toda fila con provincia="murcia" y texto_ubicacion=""
      es del programa "Murcia - ERDF/ESF" (la consulta ya filtra por ese
      programa) sin desglose de ciudad, 5.175 filas / ~741M€. Los casos donde
      sí trae otra región (p.ej. "Cantabria", "A Coruña Province" -- 59 filas,
      posible dato cruzado o programa interregional) se dejan sin tocar, no
      se fuerzan.
    - Girona: Cohesion Data con "region" EXACTAMENTE "Province of Girona" (sin
      combinar con otras regiones) -- 895 filas / ~237M€, ya acotado a NUTS3
      ES512 por la propia consulta. Las combinaciones multi-región (p.ej.
      "Province of Girona|Pyrénées-Orientales", programas de cooperación
      transfronteriza que no son solo de Girona) se dejan sin tocar."""
    if provincia == "murcia" and not texto_ubicacion:
        return MUNICIPIOS_PSEUDO["murcia"]

    idx = _INDICE_MUNICIPIOS_FONDOS_UE.get(provincia)
    if not idx or not texto_ubicacion:
        return ""

    match_ciudad = idx.get(_clave_municipio_match(texto_ubicacion), "")
    if match_ciudad:
        return match_ciudad

    if provincia == "girona" and normalizar(texto_ubicacion) == _TEXTO_REGIONAL_GIRONA:
        return MUNICIPIOS_PSEUDO["girona"]

    return ""


CORDIS_HORIZON_CSV_URL = "https://cordis.europa.eu/data/cordis-HORIZONprojects-csv.zip"
COHESION_DATA_URL = "https://cohesiondata.ec.europa.eu/resource/557j-pmg8.json"

# NUTS3 (Girona) / prefijo de programa (Murcia, que no trae NUTS3 relleno
# en Cohesion Data) por provincia -- ver diagnóstico para el porqué de la
# diferencia de criterio entre una y otra.
FONDOS_UE_NUTS3_GIRONA = "ES512"
FONDOS_UE_PROGRAMA_MURCIA = "Murcia"


def _guardar_fondos_ue(filas):
    """Inserta/actualiza filas en la tabla fondos_ue (misma clave = mismo
    registro, se sobrescribe con el dato más reciente).

    Excepción: 'beneficiario' NO se sobrescribe con un valor vacío si la fila
    ya tenía uno guardado. Necesario porque Cohesion Data siempre llega con
    beneficiary_name vacío para España (ver actualizar_fondos_cohesion) y el
    backfill de enriquecer_beneficiarios_cohesion() lo rellena aparte, en un
    paso posterior -- sin esta excepción, el refresco diario de Cohesion Data
    borraría cada noche el trabajo del enriquecimiento del día anterior."""
    if not filas:
        return
    ahora = time.time()
    with _db_lock:
        for f in filas:
            municipio_match = f.get("municipio_match") or _cruzar_municipio_fondo_ue(
                f["provincia"], f.get("municipio", ""))
            _db.execute(
                """INSERT INTO fondos_ue
                   (id, fuente, provincia, municipio, nuts_code, titulo, beneficiario,
                    nif, rol, importe_num, fecha_inicio, fecha_fin, programa, fondo, url, ts,
                    municipio_match)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     fuente=excluded.fuente, provincia=excluded.provincia,
                     municipio=excluded.municipio, nuts_code=excluded.nuts_code,
                     titulo=excluded.titulo,
                     beneficiario=CASE WHEN excluded.beneficiario<>'' THEN excluded.beneficiario
                                       ELSE fondos_ue.beneficiario END,
                     nif=excluded.nif, rol=excluded.rol, importe_num=excluded.importe_num,
                     fecha_inicio=excluded.fecha_inicio, fecha_fin=excluded.fecha_fin,
                     programa=excluded.programa, fondo=excluded.fondo, url=excluded.url,
                     ts=excluded.ts, municipio_match=excluded.municipio_match""",
                (f["id"], f["fuente"], f["provincia"], f.get("municipio", ""),
                 f.get("nuts_code", ""), f.get("titulo", ""), f.get("beneficiario", ""),
                 f.get("nif", ""), f.get("rol", ""), f.get("importe_num", 0.0),
                 f.get("fecha_inicio", ""), f.get("fecha_fin", ""), f.get("programa", ""),
                 f.get("fondo", ""), f.get("url", ""), ahora, municipio_match),
            )
        _db.commit()


def _db_fondos_ue(provincia=None):
    """Lee de vuelta la tabla fondos_ue, opcionalmente filtrada por provincia."""
    with _db_lock:
        if provincia:
            rows = _db.execute(
                "SELECT id, fuente, provincia, municipio, nuts_code, titulo, beneficiario, "
                "nif, rol, importe_num, fecha_inicio, fecha_fin, programa, fondo, url, ts "
                "FROM fondos_ue WHERE provincia=? ORDER BY importe_num DESC", (provincia,),
            ).fetchall()
        else:
            rows = _db.execute(
                "SELECT id, fuente, provincia, municipio, nuts_code, titulo, beneficiario, "
                "nif, rol, importe_num, fecha_inicio, fecha_fin, programa, fondo, url, ts "
                "FROM fondos_ue ORDER BY importe_num DESC",
            ).fetchall()
    cols = ("id", "fuente", "provincia", "municipio", "nuts_code", "titulo", "beneficiario",
            "nif", "rol", "importe_num", "fecha_inicio", "fecha_fin", "programa", "fondo", "url", "ts")
    return [dict(zip(cols, r)) for r in rows]


def _db_fondos_ue_por_municipio(municipio):
    """Fondos UE ya cruzados con este municipio exacto (columna municipio_match,
    calculada en la ingesta -- ver _cruzar_municipio_fondo_ue). Se usa para
    mostrar el bloque amarillo/azul de fondos UE en la ficha de cada ayuntamiento."""
    with _db_lock:
        rows = _db.execute(
            "SELECT id, fuente, provincia, municipio, nuts_code, titulo, beneficiario, "
            "nif, rol, importe_num, fecha_inicio, fecha_fin, programa, fondo, url, ts "
            "FROM fondos_ue WHERE municipio_match=? ORDER BY importe_num DESC", (municipio,),
        ).fetchall()
    cols = ("id", "fuente", "provincia", "municipio", "nuts_code", "titulo", "beneficiario",
            "nif", "rol", "importe_num", "fecha_inicio", "fecha_fin", "programa", "fondo", "url", "ts")
    return [dict(zip(cols, r)) for r in rows]


def _db_comentarios_insertar(tipo, clave_raw, texto, nombre=""):
    """Guarda un comentario de usuario en la ficha de municipio o de empresa.
    Sin gestión activa ni email: se guarda directamente y se muestra público
    de inmediato (ver render_comentarios_html), no hay cola de moderación."""
    with _db_lock:
        _db.execute(
            "INSERT INTO comentarios (tipo, clave, etiqueta, nombre, texto, ts) VALUES (?,?,?,?,?,?)",
            (tipo, normalizar(clave_raw), clave_raw.strip(), nombre.strip(), texto.strip(), time.time()),
        )
        _db.commit()


def _db_comentarios_por(tipo, clave_raw):
    """Comentarios guardados para este municipio/empresa, más reciente primero."""
    with _db_lock:
        rows = _db.execute(
            "SELECT nombre, texto, ts FROM comentarios WHERE tipo=? AND clave=? ORDER BY ts DESC",
            (tipo, normalizar(clave_raw)),
        ).fetchall()
    return [{"nombre": r[0], "texto": r[1], "ts": r[2]} for r in rows]


def actualizar_fondos_cordis(job_id=None):
    """Descarga el volcado masivo de CORDIS (Horizon Europe 2021-2027) y
    guarda las organizaciones de Murcia/Girona en la tabla fondos_ue.
    ~36 MB comprimidos -- se procesa en memoria fila a fila con csv.DictReader,
    no se acumulan los CSV completos como texto (mismo cuidado que con los
    ZIPs de PLACE, aunque aquí el volumen es dos órdenes de magnitud menor).

    project.csv trae TODOS los proyectos Horizon Europe del mundo (decenas de
    miles, con columnas largas como el abstract) aunque solo usemos 4 campos
    de cada uno -- guardar el `row` completo de csv.DictReader en `proyectos`
    multiplicaba la memoria varias veces sin necesidad. Ver INFORME_NOCHE.md
    2026-07-27: sospecha fundada de que esto (no Kohesio ni el refresco de
    contratos en paralelo) es la causa real del reinicio del contenedor del
    free tier de Render -- el contenedor murió a los ~4 min lanzando SOLO
    /actualizar-fondos-ue, justo la ventana en la que corre este bloque."""
    import csv, io, zipfile as _zf

    _log(job_id, "Descargando volcado CORDIS (Horizon Europe 2021-2027)…")
    try:
        r = session.get(CORDIS_HORIZON_CSV_URL, timeout=120)
        r.raise_for_status()
    except Exception as e:
        _log(job_id, f"  CORDIS no disponible ({type(e).__name__})")
        return 0

    proyectos = {}
    filas = []
    with _zf.ZipFile(io.BytesIO(r.content)) as z:
        with z.open("project.csv") as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"), delimiter=";")
            for row in reader:
                proyectos[row["id"]] = {
                    "title": row.get("title", ""),
                    "startDate": row.get("startDate", ""),
                    "endDate": row.get("endDate", ""),
                    "frameworkProgramme": row.get("frameworkProgramme", ""),
                }

        with z.open("organization.csv") as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"), delimiter=";")
            for row in reader:
                nuts = (row.get("nutsCode") or "").strip()
                if nuts.startswith(FONDOS_UE_NUTS3_GIRONA):
                    provincia = "girona"
                elif nuts.startswith("ES62"):
                    provincia = "murcia"
                else:
                    continue

                proy = proyectos.get(row.get("projectID", ""), {})
                nif = (row.get("vatNumber") or "").strip()
                if nif.upper().startswith("ES"):
                    nif = nif[2:]
                try:
                    importe = float((row.get("ecContribution") or "0").replace(",", "."))
                except ValueError:
                    importe = 0.0

                filas.append({
                    "id": f"cordis-{row.get('projectID','')}-{row.get('organisationID','')}",
                    "fuente": "cordis",
                    "provincia": provincia,
                    "municipio": row.get("city", ""),
                    "nuts_code": nuts,
                    "titulo": proy.get("title", ""),
                    "beneficiario": row.get("name", ""),
                    "nif": nif,
                    "rol": row.get("role", ""),
                    "importe_num": importe,
                    "fecha_inicio": proy.get("startDate", ""),
                    "fecha_fin": proy.get("endDate", ""),
                    "programa": proy.get("frameworkProgramme", ""),
                    "fondo": "Horizon Europe",
                    "url": f"https://cordis.europa.eu/project/id/{row.get('projectID','')}",
                })

    _guardar_fondos_ue(filas)
    _log(job_id, f"  CORDIS: {len(filas)} organizaciones de Murcia/Girona guardadas")
    return len(filas)


def actualizar_fondos_cohesion(job_id=None):
    """Consulta la API de Cohesion Data (fondos estructurales 2014-2020,
    FEDER/FSE) filtrada a Murcia y Girona, y guarda en fondos_ue. Sin
    beneficiario para España (ver nota de cabecera) -- se guarda igualmente
    para mostrar en qué proyecto/importe/región se invirtió el fondo."""
    _log(job_id, "Consultando Cohesion Data (fondos FEDER/FSE 2014-2020)…")
    filas = []

    consultas = [
        ("girona", {"$where": f"nuts3_code like '%{FONDOS_UE_NUTS3_GIRONA}%'", "$limit": 10000}),
        ("murcia", {"$where": f"programme_name like '{FONDOS_UE_PROGRAMA_MURCIA}%'", "$limit": 10000}),
    ]
    for provincia, params in consultas:
        try:
            r = session.get(COHESION_DATA_URL, params=params, timeout=60)
            if r.status_code != 200:
                _log(job_id, f"  Cohesion Data ({provincia}): HTTP {r.status_code}")
                continue
            filas_prov = r.json()
        except Exception as e:
            _log(job_id, f"  Cohesion Data ({provincia}) no disponible ({type(e).__name__})")
            continue

        for row in filas_prov:
            op_id = (row.get("operation_unique_identifier") or {}).get("url", "")
            if not op_id:
                continue
            try:
                importe = float(row.get("total_eligible_expenditure_amount") or 0)
            except ValueError:
                importe = 0.0
            filas.append({
                "id": f"cohesion-{op_id}",
                "fuente": "cohesion",
                "provincia": provincia,
                "municipio": row.get("region", ""),
                "nuts_code": row.get("nuts3_code", ""),
                "titulo": row.get("operation_name_english") or row.get("operation_name_programme_language", ""),
                "beneficiario": row.get("beneficiary_name", ""),
                "nif": "",
                "rol": "",
                "importe_num": importe,
                "fecha_inicio": row.get("operation_start_date", ""),
                "fecha_fin": row.get("operation_end_date", ""),
                "programa": row.get("programme_name", ""),
                "fondo": row.get("fund_name", ""),
                "url": "",
            })

    _guardar_fondos_ue(filas)
    _log(job_id, f"  Cohesion Data: {len(filas)} operaciones de Murcia/Girona guardadas")
    return len(filas)


# ─── Beneficiario de Cohesion Data vía Kohesio/linkedopendata.eu ────────────
# cohesiondata.ec.europa.eu (Socrata) no trae beneficiary_name para España
# (ver cabecera de actualizar_fondos_cohesion), pero cada operación sí trae un
# identificador único propio -- operation_unique_identifier.url, guardado
# como sufijo del id de esta fila (ej. "cohesion-https://linkedopendata.eu/
# entity/Q3168603") -- que apunta a un ítem Wikibase en linkedopendata.eu, un
# espejo comunitario en abierto del propio Kohesio (el portal oficial de la
# Comisión, kohesio.ec.europa.eu, es una SPA Angular sin API pública propia
# de la que tirar). Ese ítem sí trae el nombre real del beneficiario en la
# propiedad P841 ("beneficiary name (string)"), con P889 ("beneficiario",
# enlace a otro ítem) como respaldo si P841 faltara. Verificado a mano contra
# 5 operaciones de programas distintos (Girona): 5/5 con P841 relleno.
#
# Nota deliberada sobre robots.txt: linkedopendata.eu publica "Disallow: /"
# para todo user-agent. Se consulta de todos modos, por ser: (a) datos
# abiertos de fondos públicos de la UE sin autenticación ni captcha, en la
# misma línea de transparencia que el resto de la app; (b) peticiones
# puntuales por identificador exacto (una URL por operación ya conocida, no
# un rastreo/descubrimiento del sitio); (c) espaciadas con pausa y con
# presupuesto de tiempo acotado (ver más abajo) para no cargar el servicio.
# Mismo criterio que ya se aplica a einforma/axesor/infocif/BORME para
# administradores de empresas adjudicatarias.
KOHESIO_ENTITY_URL = "https://linkedopendata.eu/wiki/Special:EntityData/{qid}.json"
_KOHESIO_QID_RE = re.compile(r"/entity/(Q\d+)$")


def _kohesio_beneficiario(qid):
    """Nombre del beneficiario de una operación Cohesion Data a partir del
    ítem Wikibase de linkedopendata.eu.

    Devuelve (nombre, motivo). 'motivo' es 'ok' si se encontró, o un código
    corto de por qué no (http_XXX, timeout, sin_p841_p889, error:<Tipo>) --
    se usa solo para diagnóstico/logging del proceso en producción, no se
    guarda en la base de datos."""
    try:
        r = session.get(KOHESIO_ENTITY_URL.format(qid=qid), timeout=8)
        if r.status_code != 200:
            return "", f"http_{r.status_code}"
        ent = r.json().get("entities", {}).get(qid, {})
        claims = ent.get("claims", {})

        p841 = claims.get("P841")
        if p841:
            valor = p841[0].get("mainsnak", {}).get("datavalue", {}).get("value")
            if isinstance(valor, str) and valor.strip():
                return valor.strip(), "ok"

        # Respaldo: P889 (beneficiario) enlaza a otro ítem; su etiqueta es el nombre.
        p889 = claims.get("P889")
        if p889:
            item_id = (p889[0].get("mainsnak", {}).get("datavalue", {})
                       .get("value", {}).get("id", ""))
            if item_id:
                r2 = session.get(KOHESIO_ENTITY_URL.format(qid=item_id), timeout=8)
                if r2.status_code != 200:
                    return "", f"http_item_{r2.status_code}"
                labels = r2.json().get("entities", {}).get(item_id, {}).get("labels", {})
                for lang in ("es", "en"):
                    valor = labels.get(lang, {}).get("value", "").strip()
                    if valor:
                        return valor, "ok"
        return "", "sin_p841_p889"
    except requests.exceptions.Timeout:
        return "", "timeout"
    except Exception as e:
        return "", f"error:{type(e).__name__}"


def enriquecer_beneficiarios_cohesion(job_id=None, presupuesto_minutos=60):
    """Backfill del nombre de beneficiario de las operaciones Cohesion Data
    que llegan sin él (ver nota de cabecera arriba). Solo toca filas con
    beneficiario todavía vacío -- _guardar_fondos_ue ya preserva un
    beneficiario ya enriquecido en refrescos posteriores, así que esto es
    incremental: cada día solo se procesan las operaciones nuevas o las que
    quedaron pendientes por el presupuesto de tiempo del día anterior."""
    deadline = time.time() + presupuesto_minutos * 60
    with _db_lock:
        filas = _db.execute(
            "SELECT id FROM fondos_ue WHERE fuente='cohesion' "
            "AND (beneficiario IS NULL OR beneficiario='')"
        ).fetchall()
    total = len(filas)
    _log(job_id, f"Enriqueciendo beneficiarios de Cohesion Data (Kohesio): "
                 f"{total} operaciones pendientes…")
    encontrados = procesados = 0
    motivos = {}   # diagnóstico: cuenta de fallos por motivo (http_403, timeout, ...)
    for (fid,) in filas:
        if time.time() >= deadline:
            _log(job_id, f"  Presupuesto de {presupuesto_minutos} min agotado: "
                         f"{procesados}/{total} procesadas, se retoma en el próximo refresco.")
            break
        procesados += 1
        m = _KOHESIO_QID_RE.search(fid)
        if not m:
            continue
        nombre, motivo = _kohesio_beneficiario(m.group(1))
        if nombre:
            with _db_lock:
                _db.execute("UPDATE fondos_ue SET beneficiario=? WHERE id=?", (nombre, fid))
                _db.commit()
            encontrados += 1
        else:
            motivos[motivo] = motivos.get(motivo, 0) + 1
        time.sleep(0.3)
        if procesados % 200 == 0:
            _log(job_id, f"  … {procesados}/{total} procesadas ({encontrados} encontrados, "
                         f"fallos: {motivos})")
    _log(job_id, f"  Motivos de fallo: {motivos}")
    _log(job_id, f"  Beneficiarios Cohesion Data: {encontrados}/{procesados} "
                 f"encontrados (de {total} pendientes).")
    return encontrados


def enriquecer_directivos_fondos_ue(job_id=None, presupuesto_minutos=30):
    """Busca gerente/administrador de los beneficiarios de fondos UE con el
    MISMO detector y caché que ya se usa para los adjudicatarios de contratos
    públicos (buscar_directivo: einforma → empresia → BORME anuncios →
    búsqueda web, caché persistente en la tabla `directores`).

    No añade columnas nuevas a `fondos_ue`: el resultado se guarda en la
    misma tabla `directores` (clave = NIF si lo hay, si no nombre
    normalizado -- ver _dir_cache_key) y se lee de ahí al renderizar (ver
    _render_fila_fondo_ue), exactamente igual que para los adjudicatarios de
    contratos. Respeta el mismo caché negativo con reintentos limitados
    (_dir_cache_agotado/DIR_INTENTOS_MAX) para no repetir búsquedas contra
    beneficiarios sin datos registrales públicos.

    Solo procesa beneficiarios ya identificados (con nombre no vacío) -- los
    de Cohesion Data que aún no tienen beneficiario dependen primero de
    enriquecer_beneficiarios_cohesion(), que se llama antes en el mismo job."""
    deadline = time.time() + presupuesto_minutos * 60
    with _db_lock:
        filas = _db.execute(
            "SELECT DISTINCT beneficiario, nif FROM fondos_ue "
            "WHERE beneficiario IS NOT NULL AND beneficiario <> ''"
        ).fetchall()
    pendientes = [(b, nif or "") for b, nif in filas
                  if _dir_cache_get(b, nif or "")[0] is None
                  and not _dir_cache_agotado(b, nif or "")]
    total = len(pendientes)
    _log(job_id, f"Buscando gerente/administrador de {total} beneficiarios de "
                 f"fondos UE pendientes (einforma · empresia · BORME)…")
    encontrados = procesados = 0
    for beneficiario, nif in pendientes:
        if time.time() >= deadline:
            _log(job_id, f"  Presupuesto de {presupuesto_minutos} min agotado: "
                         f"{procesados}/{total} procesados, se retoma en el próximo refresco.")
            break
        procesados += 1
        nombre, cargo = buscar_directivo(beneficiario, nif)
        if nombre:
            encontrados += 1
        time.sleep(1.2)  # mismo delay entre peticiones que el enriquecimiento de contratos
        if procesados % 50 == 0:
            _log(job_id, f"  … {procesados}/{total} procesados ({encontrados} encontrados)")
    _log(job_id, f"  Gerentes/administradores de fondos UE: {encontrados}/{procesados} "
                 f"encontrados (de {total} pendientes).")
    return encontrados


def _actualizar_fondos_ue_bg(job_id):
    """Hilo de fondo para POST /actualizar-fondos-ue: refresca CORDIS y
    Cohesion Data uno detrás de otro. A diferencia de los contratos
    (municipio por municipio), aquí son dos descargas masivas ya filtradas
    a Murcia/Girona en la propia consulta, así que no hace falta trocearlo
    por municipio ni haría sentido reutilizar _actualizar_todos_bg."""
    if not _actualizando_fondos_ue_lock.acquire(blocking=False):
        with _jobs_lock:
            _jobs[job_id] = {"status": "error", "log": [],
                              "error": "Ya hay un refresco de fondos UE en curso."}
        return

    try:
        with _jobs_lock:
            _jobs[job_id] = {"status": "running", "log": [], "error": None}
        n_cordis = actualizar_fondos_cordis(job_id)
        n_cohesion = actualizar_fondos_cohesion(job_id)
        n_enriquecidos = enriquecer_beneficiarios_cohesion(job_id)
        n_directivos = enriquecer_directivos_fondos_ue(job_id)
        for _prov in MUNICIPIOS_PSEUDO:
            _asegurar_pseudo_municipio_fondos(_prov)
        with _jobs_lock:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["total"] = n_cordis + n_cohesion
        print(f"  [actualizar-fondos-ue] Terminado: {n_cordis} CORDIS + {n_cohesion} Cohesion Data "
              f"({n_enriquecidos} beneficiarios enriquecidos vía Kohesio, "
              f"{n_directivos} gerentes/administradores encontrados).", flush=True)
    except Exception as e:
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(e)
    finally:
        _actualizando_fondos_ue_lock.release()


# ─── NOTICIAS UE (RSS oficial Press Corner, presupuesto y subvenciones) ──────
# Feed general de la Comisión Europea (Press Corner) -- trae los últimos ~10
# comunicados de TODAS las áreas mezcladas (exterior, competencia, migración,
# presupuesto...), sin filtro de tema soportado por el propio servidor
# (?policyArea=BUDG devuelve 400). El filtrado a presupuesto/fondos/
# subvenciones se hace aquí, al guardar, por código POLICY_AREA + palabras
# clave de refuerzo. ?language=es da títulos/resúmenes en español cuando ya
# existe traducción (la mayoría) y cae a inglés si no -- confirmado el
# 2026-07-29, ver INFORME_NOCHE.md.
NOTICIAS_UE_RSS_URL = "https://ec.europa.eu/commission/presscorner/api/rss?language=es"

NOTICIAS_UE_POLICY_AREAS = {"BUDG", "REGIO", "RECOVERY", "ESF", "COHESION", "AGRI", "EMPL"}
NOTICIAS_UE_KEYWORDS = [
    "fondo", "fondos", "subvencion", "ayudas", "presupuesto", "millones de euros",
    "financiacion", "nextgenerationeu", "cohesion", "fondos estructurales",
]

# La <description> del RSS trae de cabecera "European Commission <tipo>
# Brussels, <fecha> " antes del resumen real -- se recorta para no
# duplicarlo (ya mostramos título y fecha aparte).
_NOTICIA_UE_CABECERA_RE = re.compile(
    r"^European Commission\s+\S.*?Brussels,\s*\d{1,2}\s+\w+\s+\d{4}\s*", re.I)


def _guardar_noticias_ue(filas):
    """Inserta/actualiza noticias UE (id = URL del comunicado, estable).
    Igual patrón de upsert que _guardar_fondos_ue."""
    if not filas:
        return
    ahora = time.time()
    with _db_lock:
        for f in filas:
            _db.execute(
                """INSERT INTO noticias_ue (id, titulo, resumen, url, fecha_ts, policy_areas, ts)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     titulo=excluded.titulo, resumen=excluded.resumen, url=excluded.url,
                     fecha_ts=excluded.fecha_ts, policy_areas=excluded.policy_areas, ts=excluded.ts""",
                (f["id"], f["titulo"], f["resumen"], f["url"], f["fecha_ts"], f["policy_areas"], ahora),
            )
        _db.commit()


def _db_noticias_ue(limit=6):
    """Últimas noticias guardadas, más recientes primero (por fecha de
    publicación del propio comunicado, no por cuándo se cacheó)."""
    with _db_lock:
        rows = _db.execute(
            "SELECT titulo, resumen, url, fecha_ts FROM noticias_ue "
            "ORDER BY fecha_ts DESC LIMIT ?", (limit,)
        ).fetchall()
    return [{"titulo": t, "resumen": r, "url": u, "fecha_ts": f} for t, r, u, f in rows]


def actualizar_noticias_ue(job_id=None):
    """Descarga el RSS de comunicados de prensa de la Comisión Europea y
    guarda solo los relacionados con presupuesto/fondos/subvenciones
    (ver NOTICIAS_UE_POLICY_AREAS/_KEYWORDS). Llamada desde el cron diario
    (POST /actualizar-noticias-ue), mismo patrón que actualizar_fondos_ue."""
    _log(job_id, "Consultando RSS de comunicados de prensa de la Comisión Europea…")
    try:
        r = session.get(NOTICIAS_UE_RSS_URL, timeout=30)
        r.raise_for_status()
    except Exception as e:
        _log(job_id, f"  RSS Comisión Europea no disponible ({type(e).__name__})")
        return 0

    try:
        root = ET.fromstring(r.content)
    except ET.ParseError as e:
        _log(job_id, f"  RSS Comisión Europea: XML inválido ({e})")
        return 0

    items = root.findall(".//item")
    filas = []
    for item in items:
        titulo = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        descripcion = (item.findtext("description") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        if not titulo or not link:
            continue

        policy_areas = set()
        for cat in item.findall("category"):
            texto_cat = (cat.text or "")
            if texto_cat.startswith("POLICY_AREA="):
                policy_areas.update(texto_cat.split("=", 1)[1].split(","))

        texto_norm = normalizar(titulo + " " + descripcion)
        relevante = bool(policy_areas & NOTICIAS_UE_POLICY_AREAS) or any(
            kw in texto_norm for kw in NOTICIAS_UE_KEYWORDS)
        if not relevante:
            continue

        try:
            fecha_ts = parsedate_to_datetime(pub_date).timestamp() if pub_date else 0.0
        except (TypeError, ValueError):
            fecha_ts = 0.0

        resumen = _NOTICIA_UE_CABECERA_RE.sub("", descripcion).strip()
        if len(resumen) > 280:
            resumen = resumen[:277].rsplit(" ", 1)[0] + "…"

        filas.append({
            "id": link, "titulo": titulo, "resumen": resumen, "url": link,
            "fecha_ts": fecha_ts, "policy_areas": ",".join(sorted(policy_areas)),
        })

    _guardar_noticias_ue(filas)
    _log(job_id, f"  RSS Comisión Europea: {len(filas)} noticias de presupuesto/fondos guardadas "
                 f"(de {len(items)} comunicados recibidos)")
    return len(filas)


_actualizando_noticias_ue_lock = threading.Lock()  # evita lanzar dos refrescos de noticias_ue a la vez


def _actualizar_noticias_ue_bg(job_id):
    if not _actualizando_noticias_ue_lock.acquire(blocking=False):
        with _jobs_lock:
            _jobs[job_id] = {"status": "error", "log": [],
                              "error": "Ya hay un refresco de noticias UE en curso."}
        return
    try:
        with _jobs_lock:
            _jobs[job_id] = {"status": "running", "log": [], "error": None}
        n = actualizar_noticias_ue(job_id)
        with _jobs_lock:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["total"] = n
        print(f"  [actualizar-noticias-ue] Terminado: {n} noticias guardadas.", flush=True)
    except Exception as e:
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(e)
    finally:
        _actualizando_noticias_ue_lock.release()


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


_ddg_bloqueado_hasta = 0.0  # circuit-breaker temporal (epoch): DuckDuckGo puede
# exigir captcha si detecta tráfico de bot. Antes era un booleano permanente
# para toda la sesión -- en la tirada de Girona (175 min, 221 municipios) un
# captcha en el municipio 2 desactivó esta fuente para el resto de la tirada
# completa. Ahora se reactiva sola pasado el cooldown, para no perder la
# fuente 4 durante horas por un único bloqueo puntual.
DDG_COOLDOWN = 15 * 60  # 15 minutos

def buscar_directivo_web(empresa, nif=""):
    """
    Fuente 4 (último recurso): búsqueda de texto en DuckDuckGo (Google bloquea el
    scraping directo) restringida a portales mercantiles conocidos, extrayendo el
    cargo/nombre del snippet o, si no aparece, de la primera ficha enlazada.
    Si DDG responde con un captcha, se desactiva temporalmente (DDG_COOLDOWN)
    en vez de para el resto de la sesión.
    """
    global _ddg_bloqueado_hasta
    if not empresa or empresa == "No localizada" or time.time() < _ddg_bloqueado_hasta:
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
            _ddg_bloqueado_hasta = time.time() + DDG_COOLDOWN
            print(f"  [web] DuckDuckGo pide captcha — fuente desactivada {DDG_COOLDOWN // 60} min.", flush=True)
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

    # Contratos sin empresa: distingue los declarados SIN adjudicatario por la
    # propia fuente (desierto/desistimiento/renuncia, código de resultado de
    # PLACE) de aquellos donde sí hubo adjudicatario pero no hemos podido
    # cruzarlo (limitación nuestra). PLACE trae el código; BORM/PSCP no, así
    # que sus "sin empresa" se cuentan como "no identificada" (ver
    # INFORME_NOCHE.md 2026-07-25).
    sin_empresa_lista = [c for c in contratos if c.get("empresa") == "No localizada"]
    sin_empresa = len(sin_empresa_lista)
    if sin_empresa > 0:
        pct = round(100 * sin_empresa / total)
        desiertos = sum(1 for c in sin_empresa_lista
                        if c.get("resultado_code") in _RESULTADO_SIN_ADJUDICATARIO)
        no_identificados = sin_empresa - desiertos
        plural = "s" if sin_empresa != 1 else ""
        if desiertos and no_identificados:
            texto = (
                f"<b>{sin_empresa} contrato{plural}</b> ({pct}%) sin empresa adjudicataria: "
                f"<b>{desiertos}</b> declarado{'s' if desiertos != 1 else ''} desierto{'s' if desiertos != 1 else ''} "
                f"o sin adjudicatario por la fuente (renuncia/desistimiento), y "
                f"<b>{no_identificados}</b> no identificado{'s' if no_identificados != 1 else ''} "
                f"(hubo adjudicatario pero no se ha podido cruzar)."
            )
        elif desiertos:
            texto = (
                f"<b>{sin_empresa} contrato{plural}</b> ({pct}%) declarado{plural} desierto{plural} "
                f"o sin adjudicatario por la fuente (renuncia/desistimiento) — no es una limitación del cruce."
            )
        else:
            texto = (
                f"<b>{sin_empresa} contrato{plural}</b> ({pct}%) sin empresa adjudicataria identificada "
                f"(hubo adjudicatario pero no se ha podido cruzar con la empresa)."
            )
        alertas.append({"nivel": "opacidad", "icono": "🚩", "texto": texto})

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


def _job_run(job_id, municipio, provincia="murcia"):
    try:
        _log(job_id, f"Iniciando búsqueda de contratos para {municipio}…")

        if provincia == "girona":
            contratos = buscar_en_pscp(municipio, job_id)
        else:
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
        contratos = _dedup_contratos_por_url(contratos)

        if provincia != "girona":
            # Enriquecer contratos PLACE con el link al BORM cuando existe uno equivalente
            _enlazar_borm_place(contratos)
        _log(job_id, f"Total contratos únicos (este refresco): {len(contratos)}")

        # Fusión con el histórico ya guardado -- el refresco de este ciclo
        # NUNCA sustituye lo ya persistido, se fusiona con ello (ver
        # _fusionar_historico_contratos). Corrige el bug documentado en
        # INFORME_NOCHE.md 2026-07-22 que borró histórico real de Archena.
        existentes = _db_obtener_contratos_municipio(municipio)
        if existentes:
            antes = len(contratos)
            contratos = _fusionar_historico_contratos(existentes, contratos)
            _log(job_id, f"Fusionado con histórico ya guardado: {antes} de este refresco + "
                 f"{len(existentes)} ya guardados -> {len(contratos)} tras fusión")

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

        # Separa los contratos cuyo órgano contratante es la propia CCAA de
        # Murcia (Consejerías, institutos...) de los del Ayuntamiento de
        # Murcia capital -- ver _es_organo_ccaa_murcia e INFORME_NOCHE.md
        # 2026-07-23. Solo aplica al refresco de "Murcia" capital porque el
        # bug de atribución (buscar el nombre del municipio como subcadena
        # del órgano) solo mete contratos de la CCAA ahí -- el resto de
        # municipios de Murcia no tienen ese problema.
        contratos_ccaa_murcia = []
        if provincia == "murcia" and normalizar(municipio) == normalizar("Murcia"):
            contratos, contratos_ccaa_murcia = _separar_contratos_ccaa_murcia(contratos)

        # Separa los contratos cuyo órgano es un organismo de la Administración
        # General del Estado (Guardia Civil, AEAT, TGSS, INSS, Delegación del
        # Gobierno, centros penitenciarios, SEPE...) o la Universidad de Murcia
        # que se cuelan por el mismo bug de subcadena. A diferencia de la CCAA,
        # esto aplica a CUALQUIER municipio de Murcia (medido: Murcia capital
        # 226 + Campos del Río 4 duplicados) -- ver _es_organo_age/_es_organo_umu
        # e INFORME_NOCHE.md 2026-07-25 y 2026-07-29 (separación de la UMU).
        # No se ejecuta sobre las propias entradas pseudo. La UMU se separa
        # ANTES que la AGE para que quede en su propia entrada (si se hiciera
        # al revés, _es_organo_age ya no la reconoce, pero el orden se deja
        # explícito por claridad).
        es_age_target = provincia == "murcia" and not es_pseudo_municipio(municipio)
        contratos_umu = []
        contratos_age = []
        if es_age_target:
            contratos, contratos_umu = _separar_contratos_umu(contratos)
            contratos, contratos_age = _separar_contratos_age(contratos)

        # Análisis de riesgo
        alertas = analizar_riesgo(contratos)

        organismo = f"Ajuntament de {municipio}" if provincia == "girona" else f"Ayuntamiento de {municipio}"
        resultado = {
            "municipio":       municipio,
            "organismo":       organismo,
            "total_contratos": len(contratos),
            "contratos":       contratos,
            "alertas":         alertas,
            # PSCP no tiene perfil de contratante equivalente al de PLACE (ver Fase 3)
            "place_profile":   "" if provincia == "girona" else place_profile_url(municipio),
            "timestamp":       time.time(),
        }

        _cache_set(municipio, resultado)

        with _datos_lock:
            _datos_memoria[:] = [d for d in _datos_memoria if normalizar(d.get("municipio", "")) != normalizar(municipio)]
            _datos_memoria.append(resultado)
        _db_set_municipio(municipio, resultado, provincia=provincia)

        if contratos_ccaa_murcia:
            _guardar_pseudo_municipio_ccaa("murcia", contratos_ccaa_murcia, job_id)

        # Siempre para municipios de Murcia (incluso con lista vacía): así se
        # limpia la aportación previa de este municipio si un contrato dejó de
        # encajar, y se acumulan los de varios municipios sin duplicar.
        if es_age_target:
            _guardar_pseudo_municipio_age(municipio, contratos_age, job_id)
            _guardar_pseudo_municipio_umu(municipio, contratos_umu, job_id)

        with _jobs_lock:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["total"] = len(contratos)

        # Enriquecer en fondo las sociedades que aún no tienen directivo
        _lanzar_enriquecimiento()

    except Exception as e:
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(e)


def _refrescar_provincia_secuencial(job_id, provincia, offset=0):
    """Refresca secuencialmente todos los municipios de UNA provincia,
    actualizando `_jobs[job_id]["procesados"]` con el progreso acumulado
    (offset = municipios ya procesados de provincias anteriores en la misma
    llamada, para que el contador avance sin reiniciarse al pasar de Murcia
    a Girona cuando se pide provincia="todas")."""
    municipios = MUNICIPIOS_POR_PROVINCIA.get(provincia, MUNICIPIOS_MURCIA)
    print(f"  [actualizar-todos:{provincia}] Iniciando refresco de {len(municipios)} municipios…", flush=True)

    for idx, municipio in enumerate(municipios, 1):
        print(f"  [actualizar-todos:{provincia}] [{idx}/{len(municipios)}] {municipio}", flush=True)
        sub_job_id = f"{job_id}-{provincia}-{idx}"
        with _jobs_lock:
            _jobs[sub_job_id] = {"status": "running", "log": [], "error": None}
        try:
            _cache_invalidate(municipio)
            _job_run(sub_job_id, municipio, provincia=provincia)
        except Exception as e:
            print(f"  [actualizar-todos:{provincia}] Error en {municipio}: {e}", flush=True)
        finally:
            with _jobs_lock:
                _jobs.pop(sub_job_id, None)
                if job_id in _jobs:
                    _jobs[job_id]["procesados"] = offset + idx
        time.sleep(4)  # pausa entre municipios

    print(f"  [actualizar-todos:{provincia}] Refresco completo terminado.", flush=True)


def _actualizar_todos_bg(job_id, provincia="murcia"):
    """
    Hilo de fondo: refresca secuencialmente todos los municipios de la
    provincia dada, o de TODAS (Murcia y luego Girona, una detrás de otra)
    si provincia="todas". Pensado para dispararse desde un disparador
    externo (cron) vía POST /actualizar-todos -- el cron diario pasa
    provincia=todas para cubrir ambas fuentes en una sola ejecución.

    Mientras corre, la web sigue sirviendo los datos anteriores con
    normalidad: _job_run solo sustituye la entrada de _datos_memoria del
    municipio que esté procesando en ese momento, bajo _datos_lock, así que
    nunca hay un estado a medias visible para quien esté navegando.
    """
    provincias = (list(MUNICIPIOS_POR_PROVINCIA.keys()) if provincia == "todas"
                  else [provincia if provincia in MUNICIPIOS_POR_PROVINCIA else "murcia"])
    total = sum(len(MUNICIPIOS_POR_PROVINCIA[p]) for p in provincias)

    if not _actualizando_todos_lock.acquire(blocking=False):
        with _jobs_lock:
            _jobs[job_id] = {"status": "error", "log": [],
                              "error": "Ya hay un refresco completo en curso."}
        return

    try:
        with _jobs_lock:
            _jobs[job_id] = {"status": "running", "log": [], "error": None,
                              "total_municipios": total, "procesados": 0}

        offset = 0
        for prov in provincias:
            _refrescar_provincia_secuencial(job_id, prov, offset=offset)
            offset += len(MUNICIPIOS_POR_PROVINCIA[prov])

        with _jobs_lock:
            if job_id in _jobs:
                _jobs[job_id]["status"] = "done"
        print(f"  [actualizar-todos] Refresco completo terminado ({'+'.join(provincias)}).", flush=True)

    finally:
        _actualizando_todos_lock.release()


def _cargar_contratos_menores_murcia_manual():
    """Carga contratos_menores_murcia_manual.json (generado por
    actualizar_contratos_menores_murcia_manual.py -- Mula y Molina de Segura,
    fuentes que necesitan odfpy/openpyxl y por eso se ingieren a mano en vez
    de en el cron diario, ver ese script) y lo vuelca a la tabla compartida
    contratos_menors_locales. A diferencia de ALCALDES_CONCEJALES/
    RETRIBUCIONES_ISPA (que se quedan en memoria), esto SÍ escribe en SQLite
    porque la tabla es la fuente única de verdad para renderizar la sección
    de contratos menores de cualquier origen -- ver
    _db_contratos_menors_por_municipio. Se ejecuta en cada arranque (barato,
    es un upsert idempotente sobre unos pocos miles de filas como mucho); el
    fichero solo cambia cuando alguien vuelve a lanzar el script a mano."""
    if not os.path.exists(CONTRATOS_MENORES_MURCIA_MANUAL_FILE):
        return
    try:
        with open(CONTRATOS_MENORES_MURCIA_MANUAL_FILE, encoding="utf-8") as f:
            d = json.load(f)
        registros = d.get("registros", []) if isinstance(d, dict) else []
    except Exception:
        registros = []
    if registros:
        _guardar_contratos_menors_locales(registros)
        print(f"  [startup] contratos_menores_murcia_manual.json: {len(registros)} "
              f"contratos menores (Mula/Molina de Segura) cargados en contratos_menors_locales.", flush=True)


def _inicializar_datos():
    """Carga municipios y directivos cacheados desde SQLite en RAM al arrancar."""
    _db_init()
    _cargar_contratos_menores_murcia_manual()
    _recuperar_historico_perdido()
    cargados = _db_all_municipios()
    with _datos_lock:
        _datos_memoria[:] = cargados
    for d in cargados:
        muni = d.get("municipio", "")
        ts = d.get("timestamp", 0)
        if muni and (time.time() - ts) < RESULT_CACHE_TTL:
            _cache_set(muni, d)
    for _prov in MUNICIPIOS_PSEUDO:
        _asegurar_pseudo_municipio_fondos(_prov)


# ─── ENRIQUECIMIENTO EN BACKGROUND (empresia / BORME) ────────────────────────

def _contrato_key(c):
    """Clave estable para identificar un contrato independientemente de su posición en memoria."""
    return (c.get("empresa", ""), c.get("url", ""), c.get("titulo", "")[:60])


def _guardar_datos_sin_lock():
    """Persiste _datos_memoria en SQLite. Llamar solo desde dentro de _datos_lock."""
    for d in _datos_memoria:
        muni = d.get("municipio", "")
        if muni:
            # Propagar la provincia del propio dict -- si no, el hilo de
            # enriquecimiento (que recorre TODOS los municipios en memoria,
            # de cualquier provincia) pisaría silenciosamente a "murcia" el
            # valor de cualquier municipio de Girona que reguarde de paso.
            _db_set_municipio(muni, d, provincia=d.get("provincia", "murcia"))


def _limpiar_cache_negativos():
    """Elimina del caché SQLite las entradas negativas que aún no agotaron sus
    reintentos, para forzar re-búsqueda. Las que ya llegaron a DIR_INTENTOS_MAX
    se dejan (se consideran "sin datos registrales públicos" y no se reintentan).

    No hace nada si ya se ejecutó hace menos de LIMPIEZA_NEGATIVOS_INTERVALO
    -- sin este límite, cada refresco de municipio relanza el hilo de
    enriquecimiento (_lanzar_enriquecimiento en _job_run), que llama aquí
    incondicionalmente y anulaba en la práctica el TTL negativo de 7 días
    (DIR_CACHE_NEG_TTL) durante cualquier lote de refrescos consecutivos.

    El timestamp de la última limpieza se persiste en la tabla `settings`
    (disco), NO solo en un global en memoria: el contenedor de Render se
    reinicia con frecuencia (sleep del plan free), y un global se reiniciaría
    a 0.0 en cada arranque, dejando que la primera limpieza del nuevo proceso
    volviera a disparar la tormenta de re-consultas externas a mitad de un
    lote de /actualizar-todos. Con el timestamp en disco, el límite de 24h se
    respeta aunque el proceso muera y vuelva a arrancar durante el lote (ver
    INFORME_NOCHE.md 2026-07-25)."""
    global _ULTIMA_LIMPIEZA_NEGATIVOS
    ahora = time.time()
    ultima = max(_ULTIMA_LIMPIEZA_NEGATIVOS,
                 _settings_get_float(_CLAVE_ULTIMA_LIMPIEZA_NEG, 0.0))
    if ahora - ultima < LIMPIEZA_NEGATIVOS_INTERVALO:
        return
    with _db_lock:
        deleted = _db.execute(
            "DELETE FROM directores WHERE (nombre = '' OR nombre IS NULL) AND intentos < ?",
            (DIR_INTENTOS_MAX,),
        ).rowcount
        _db.commit()
    _ULTIMA_LIMPIEZA_NEGATIVOS = ahora
    _settings_set(_CLAVE_ULTIMA_LIMPIEZA_NEG, ahora)
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
  --red:#f85149;--green:#3fb950;--yellow:#d29922;--purple:#d2a8ff;
}
*{box-sizing:border-box;margin:0;padding:0;}
/* overflow-x:hidden SOLO en html, no en body -- ver INFORME_NOCHE.md (header
   roto en movil): con overflow-x:hidden en AMBOS, body pasa a computar
   overflow-y:auto (regla de la spec cuando un eje no es 'visible') y se
   convierte en su propio contenedor de scroll, desacoplado del scroll real
   del documento (document.scrollingElement, que sigue siendo <html>). El
   header (position:sticky) queda anclado a ese scroll-container de body en
   vez de al del documento, así que cuando el foco automático del buscador
   (autofocus en #as-input) desplaza la pagina en pantallas bajas (~568px de
   alto, tipo iPhone SE), el header se desplaza fuera de la vista en vez de
   quedarse fijo arriba. Reproducido con Playwright a 320x568: scrollY=341,
   header en y=-341 pese a position:sticky. Con overflow-x:hidden solo en
   html, body ya no crea ese segundo contenedor y el sticky vuelve a anclarse
   al scroll real del documento.*/
html{overflow-x:hidden;}
body{font-family:'IBM Plex Sans',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;padding-bottom:60px;}
header{background:var(--surface);border-bottom:1px solid var(--border);padding:16px 28px;display:flex;align-items:center;gap:14px;position:sticky;top:0;z-index:10;}
.header-brand{display:flex;align-items:center;gap:14px;min-width:0;flex:1;}
.header-brand>div{min-width:0;}
header h1{overflow-wrap:break-word;}
.logo-svg{flex-shrink:0;line-height:0;}
.logo-svg svg{width:160px;height:auto;display:block;}
header h1{font-size:15px;font-weight:600;}
header p{font-size:12px;color:var(--dim);margin-top:2px;}
.header-nav{flex-shrink:0;display:flex;align-items:center;gap:10px;}
.header-nav>a{display:inline-flex;text-decoration:none;padding:8px 16px;border-radius:6px;background:rgba(240,136,62,.12);color:var(--accent);border:1px solid rgba(240,136,62,.35);font-size:13px;font-weight:600;white-space:nowrap;}
.header-nav>a:hover{background:rgba(240,136,62,.22);}
.pwa-install-btn{display:inline-flex;font-family:'IBM Plex Sans',sans-serif;text-decoration:none;padding:8px 16px;border-radius:6px;background:var(--accent);color:#000;border:1px solid var(--accent);font-size:13px;font-weight:600;white-space:nowrap;cursor:pointer;}
.pwa-install-btn[hidden]{display:none;}
.pwa-install-btn:hover{background:#ffa657;}
.prov-switch{display:flex;border:1px solid var(--border);border-radius:6px;overflow:hidden;}
.prov-tab{text-decoration:none;padding:8px 14px;font-size:13px;font-weight:600;color:var(--dim);background:var(--bg);white-space:nowrap;}
.prov-tab:hover{color:var(--text);}
.prov-tab.active{background:var(--accent);color:#000;}
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
.muni-header{padding:12px 18px;background:rgba(240,136,62,.08);border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap;}
.muni-header h2{font-size:14px;font-weight:600;color:var(--accent);}
.cuentas-link{font-size:10px;font-weight:600;color:var(--dim);text-decoration:none;border:1px solid var(--border);border-radius:4px;padding:2px 6px;vertical-align:middle;white-space:nowrap;}
.cuentas-link:hover{color:var(--text);border-color:var(--dim);}
.alcalde-info{display:block;font-size:11px;color:var(--dim);margin-top:4px;}
.pol-nombre{color:var(--purple);}
.pol-retrib{color:var(--green);font-family:'IBM Plex Mono',monospace;}
.concejales-dd{margin-top:4px;font-size:11px;}
.concejales-dd summary{cursor:pointer;color:var(--dim);}
.concejales-dd summary:hover{color:var(--accent);}
.concejales-dd ul{list-style:none;margin:6px 0 0;padding:0;display:flex;flex-direction:column;gap:3px;}
.concejales-dd a{color:var(--purple);text-decoration:none;}
.concejales-dd a:hover{text-decoration:underline;}
.conc-cargo{color:var(--dim);}
.badge{font-family:'IBM Plex Mono',monospace;font-size:11px;padding:3px 8px;border-radius:4px;background:rgba(88,166,255,.15);color:var(--blue);border:1px solid rgba(88,166,255,.3);}
.source-bar{padding:5px 18px;font-size:11px;color:var(--dim);font-family:'IBM Plex Mono',monospace;border-bottom:1px solid var(--border);background:rgba(0,0,0,.2);}
table{width:100%;border-collapse:collapse;font-size:13px;}
th{font-family:'IBM Plex Mono',monospace;font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--dim);padding:9px 14px;text-align:left;background:rgba(0,0,0,.2);border-bottom:1px solid var(--border);}
td{padding:9px 14px;border-bottom:1px solid rgba(48,54,61,.5);vertical-align:top;line-height:1.5;}
tr:last-child td{border-bottom:none;}
.empresa{font-weight:600;}
.contrato-title{font-size:11px;color:var(--dim);margin-top:3px;}
.ute-nota{font-size:10px;color:var(--dim);font-weight:normal;}
.importe{font-family:'IBM Plex Mono',monospace;font-size:13px;color:var(--green);white-space:nowrap;font-weight:600;}
.importe.noloc{color:var(--dim);font-style:italic;font-weight:normal;}
.directivo{color:var(--blue);}
.cargo{color:var(--dim);font-size:11px;}
.cargo-match{font-size:10.5px;line-height:1.5;margin-top:5px;padding:5px 8px;border-radius:4px;max-width:260px;}
.cargo-match-local{background:rgba(210,153,34,.1);border:1px solid rgba(210,153,34,.4);color:#e6c87a;}
.cargo-match-regional{background:rgba(88,166,255,.06);border:3px double rgba(88,166,255,.5);color:var(--text);}
.cargo-match-detalle{opacity:.85;font-weight:normal;}
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
.fuente-pscp{background:rgba(63,185,80,.15);color:var(--green);border:1px solid rgba(63,185,80,.3);}
a.pscp-link{color:var(--green);}
/* Fondos UE -- letra amarilla sobre fondo azul a propósito, para
   diferenciarlos a simple vista de los contratos públicos normales
   (naranja/azul). Antes del 2026-07-23 era violeta -- ver INFORME_NOCHE.md. */
.fuente-cordis{background:rgba(88,166,255,.15);color:var(--yellow);border:1px solid rgba(88,166,255,.3);}
.fuente-cohesion{background:rgba(88,166,255,.15);color:var(--yellow);border:1px solid rgba(88,166,255,.35);}
.fue-card{background:var(--surface);border:1px solid rgba(88,166,255,.35);border-radius:8px;margin-bottom:18px;overflow:hidden;}
.fue-header{padding:12px 18px;background:rgba(88,166,255,.15);border-bottom:1px solid var(--border);}
.fue-header h2{font-size:14px;font-weight:600;color:var(--yellow);}
.fue-importe{font-family:'IBM Plex Mono',monospace;font-size:13px;color:var(--yellow);white-space:nowrap;font-weight:600;}
a.fue-link{color:var(--yellow);font-size:11px;}
.fue-nif{font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--dim);}
/* Contractes menors (Girona, RPC) -- acento naranja (--accent), distinto del
   azul/amarillo de Fondos UE y del verde de PSCP, para que se reconozca como
   una tercera fuente de naturaleza distinta (registre de menors, no
   licitació formal). Colapsable con <details> -- son muchos contratos de
   importe bajo, no tiene sentido mostrarlos todos abiertos por defecto. */
.cm-card{background:var(--surface);border:1px solid rgba(240,136,62,.35);border-radius:8px;margin-top:14px;overflow:hidden;}
.cm-card summary{padding:12px 18px;background:rgba(240,136,62,.12);cursor:pointer;font-size:14px;font-weight:600;color:var(--accent);list-style:none;}
.cm-card summary::-webkit-details-marker{display:none;}
.cm-importe{font-family:'IBM Plex Mono',monospace;font-size:13px;color:var(--accent);white-space:nowrap;font-weight:600;}
.cm-nif{font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--dim);}
.fuente-rpc{background:rgba(240,136,62,.15);color:var(--accent);border:1px solid rgba(240,136,62,.3);}
/* Comentarios de usuarios (ficha de municipio/empresa) -- mismo patrón
   <details> colapsable que cm-card, acento azul para diferenciarlo de las
   fuentes de datos oficiales (naranja/amarillo/verde). */
.comentarios-card{background:var(--surface);border:1px solid rgba(88,166,255,.35);border-radius:8px;margin-top:14px;overflow:hidden;}
.comentarios-card summary{padding:12px 18px;background:rgba(88,166,255,.1);cursor:pointer;font-size:14px;font-weight:600;color:var(--blue);list-style:none;}
.comentarios-card summary::-webkit-details-marker{display:none;}
.comentarios-list{padding:4px 18px;}
.comentario-item{padding:10px 0;border-bottom:1px solid rgba(48,54,61,.5);}
.comentario-item:last-child{border-bottom:none;}
.comentario-meta{font-size:12px;margin-bottom:4px;}
.comentario-meta b{color:var(--text);}
.comentario-fecha{color:var(--dim);font-family:'IBM Plex Mono',monospace;font-size:11px;margin-left:8px;}
.comentario-texto{font-size:13px;color:var(--text);line-height:1.6;white-space:pre-wrap;word-break:break-word;}
.comentario-form{display:flex;flex-direction:column;gap:8px;padding:14px 18px 18px;border-top:1px solid var(--border);}
.comentario-form input,.comentario-form textarea{background:var(--bg);border:1px solid var(--border);color:var(--text);font-family:'IBM Plex Sans',sans-serif;font-size:13px;padding:9px 12px;border-radius:6px;outline:none;resize:vertical;}
.comentario-form textarea{min-height:70px;}
.comentario-form input:focus,.comentario-form textarea:focus{border-color:var(--blue);}
.comentario-form .btn{align-self:flex-start;}
.rk-pos{font-size:16px;text-align:center;width:44px;}
.rk-empresa{color:var(--text);font-weight:600;text-decoration:none;}
.rk-empresa:hover{color:var(--accent);text-decoration:underline;}
.rk-valor{font-family:'IBM Plex Mono',monospace;font-size:13px;color:var(--green);white-space:nowrap;font-weight:600;}
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
a.btn-ver{display:inline-block;padding:8px 16px;background:rgba(240,136,62,.12);color:var(--accent);border:1px solid rgba(240,136,62,.35);border-radius:6px;font-size:13px;font-weight:600;text-decoration:none;}
a.btn-ver:hover{background:rgba(240,136,62,.22);}
.region-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:14px;margin-bottom:24px;}
.region-card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:18px 20px;display:flex;flex-direction:column;gap:8px;text-decoration:none;transition:border-color .15s;}
.region-card:hover{border-color:var(--accent);}
.region-card h3{font-size:15px;color:var(--accent);}
.region-stats{font-size:12px;color:var(--dim);font-family:'IBM Plex Mono',monospace;}
.region-stats b{color:var(--text);font-weight:600;}
.region-imp{font-family:'IBM Plex Mono',monospace;font-size:16px;color:var(--green);font-weight:600;}
.top1-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px;margin-bottom:8px;}
.top1-card{background:var(--surface);border:1px solid rgba(240,136,62,.35);border-radius:8px;padding:16px 20px;}
.top1-label{font-family:'IBM Plex Mono',monospace;font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--dim);margin-bottom:8px;}
.top1-empresa{display:block;font-size:16px;font-weight:600;color:var(--text);text-decoration:none;margin-bottom:4px;}
.top1-empresa:hover{color:var(--accent);text-decoration:underline;}
.top1-valor{font-family:'IBM Plex Mono',monospace;font-size:14px;color:var(--green);font-weight:600;margin-bottom:4px;}
.top1-directivo{font-size:12px;color:var(--blue);}
.rk-section-header{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin:32px 0 4px;padding-bottom:10px;border-bottom:2px solid var(--accent);scroll-margin-top:96px;}
.rk-section-header h2{font-size:18px;color:var(--text);}
.rk-badge{font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--dim);background:var(--surface);border:1px solid var(--border);border-radius:4px;padding:4px 10px;}
.muni-tile a.btn-ver:hover{background:rgba(240,136,62,.22);}

/* ── cabecera home: panel degradado azul (hero + buscador + stats) ──────
   Solo se aplica en la home nacional envolviendo .hero/.adv-search/.stats-bar
   en .hero-panel -- el resto de usos de esas clases (rankings, fondos-ue,
   landing por provincia) no llevan ese envoltorio y siguen en fondo oscuro. */
.hero-panel{background:linear-gradient(135deg,#0b2145 0%,#12336b 55%,#1c4fa0 100%);border-radius:14px;padding:6px 20px 24px;margin-bottom:24px;color:#fff;}
.hero-panel .hero-tagline{color:#fff;}
.hero-panel .hero-sub{color:rgba(255,255,255,.82);}
.hero-panel .adv-search{background:rgba(255,255,255,.07);border-color:rgba(255,255,255,.2);}
.hero-panel .as-tab{background:rgba(255,255,255,.08);color:rgba(255,255,255,.72);border-color:rgba(255,255,255,.2);}
.hero-panel .as-tab.active{background:rgba(245,183,0,.18);color:#f5b700;border-color:rgba(245,183,0,.55);}
.hero-panel .as-row input{background:rgba(255,255,255,.09);border-color:rgba(255,255,255,.28);color:#fff;}
.hero-panel .as-row input::placeholder{color:rgba(255,255,255,.55);}
.hero-panel .as-row input:focus{border-color:#f5b700;}
.hero-panel #as-btn{background:#f5b700;color:#1a1200;}
.hero-panel #as-btn:hover{background:#ffc93d;}
.hero-panel .gs-hint{color:rgba(255,255,255,.62);}
.hero-panel .stats-bar .stat{background:rgba(255,255,255,.08);border-color:rgba(255,255,255,.22);color:rgba(255,255,255,.9);}
.hero-panel .stats-bar .stat span{color:#f5b700;}

/* ── sección Cobertura (home, debajo de la cabecera) ─────────────────────
   Verde-teal deliberadamente distinto del verde de importes (var(--green),
   #3fb950) para que no se confundan a simple vista -- ver instrucción del
   2026-07-29. */
.cobertura-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;margin-bottom:28px;}
.cobertura-btn{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:5px;text-align:center;padding:24px 20px;border-radius:10px;text-decoration:none;border:1.5px solid #1fae7a;color:#1fae7a;background:rgba(31,174,122,.10);transition:background .15s,border-color .15s;}
.cobertura-btn:hover{background:rgba(31,174,122,.2);border-color:#26cf92;}
.cobertura-btn .cb-title{font-size:17px;font-weight:700;}
.cobertura-btn .cb-count{font-family:'IBM Plex Mono',monospace;font-size:12px;color:#1fae7a;opacity:.9;}

/* ── indicador de scroll horizontal en tarjetas de contrato (móvil) ─────── */
.tbl-scroll{position:relative;}
.scroll-hint{display:none;}

/* ── home: columna de noticias UE (margen izquierdo) + columna principal ─
   Mismo amarillo que fondos UE (.fue-header h2, badges CORDIS/Cohesion)
   para mantener "UE = amarillo" consistente en todo el sitio. */
.home-grid{display:grid;grid-template-columns:280px 1fr;gap:20px;align-items:start;}
.noticias-ue-panel{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:16px 18px;display:flex;flex-direction:column;gap:2px;position:sticky;top:80px;}
.nu-panel-title{font-size:13px;font-weight:600;color:var(--yellow);margin-bottom:10px;}
.noticia-ue-item{padding:10px 0;border-bottom:1px solid var(--border);}
.noticia-ue-item:last-of-type{border-bottom:none;}
.noticia-ue-item .nu-titulo{display:block;font-size:12.5px;font-weight:600;line-height:1.4;color:var(--text);text-decoration:none;margin-bottom:4px;}
.noticia-ue-item .nu-titulo:hover{color:var(--yellow);text-decoration:underline;}
.noticia-ue-item .nu-resumen{font-size:11.5px;color:var(--dim);line-height:1.5;margin-bottom:5px;}
.noticia-ue-item .nu-meta{display:flex;justify-content:space-between;font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--dim);}
.noticia-ue-item .nu-meta .nu-fuente{color:var(--yellow);}
.nu-ver-mas{display:block;margin-top:10px;font-size:11px;color:var(--yellow);text-decoration:none;}
.nu-ver-mas:hover{text-decoration:underline;}
.home-main-col{min-width:0;}

/* ── footer ───────────────────────────────────────────────────────────── */
.colabora-bar{max-width:1340px;margin:48px auto 0;padding:16px 20px;border-radius:8px;background:rgba(240,136,62,.08);border:1px solid rgba(240,136,62,.3);display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:14px;}
.colabora-text{font-size:12.5px;color:var(--text);line-height:1.6;max-width:760px;}
.colabora-text b{color:var(--accent);}
.colabora-bizum{font-family:'IBM Plex Mono',monospace;font-size:13px;font-weight:600;color:var(--accent);background:var(--surface);border:1px solid rgba(240,136,62,.4);border-radius:6px;padding:8px 16px;white-space:nowrap;}
.site-footer{max-width:1340px;margin:0 auto;padding:22px 20px;border-top:1px solid var(--border);display:flex;flex-wrap:wrap;justify-content:space-between;gap:16px;align-items:center;}
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
  header{padding:10px 14px;flex-wrap:wrap;row-gap:10px;}
  .header-brand{flex:1 1 100%;}
  header h1{font-size:15px;}
  header p{font-size:11px;}
  .logo-svg svg{width:96px;}
  .header-nav{flex:1 1 100%;flex-wrap:wrap;justify-content:flex-start;}
  .header-nav>a{padding:7px 10px;font-size:11px;}
  .pwa-install-btn{padding:7px 10px;font-size:11px;}
  /* El header sticky es más alto en móvil que en escritorio (el nav pasa
     a su propia fila bajo el logo) -- verificado con Playwright a 390px
     de ancho (2026-08-04): header real ~116px, el scroll-margin-top:96px
     pensado para escritorio dejaba el título de #alcaldes tapado ~20px
     bajo el header al saltar desde el enlace del menú. */
  .rk-section-header{scroll-margin-top:130px;}
  .prov-tab{padding:7px 10px;font-size:11px;}
  .main{padding:0 12px;margin:18px auto;max-width:100%;}
  .hero{padding:22px 6px 4px;}
  .hero-tagline{font-size:16px;}
  .hero-sub{font-size:12px;}
  .stats-bar{gap:8px;}
  .stat{padding:8px 12px;flex:1 1 40%;}
  .stat span{font-size:16px;}
  .muni-grid{grid-template-columns:1fr 1fr;gap:10px;}
  .muni-tile{padding:12px 14px;}
  .region-grid,.top1-grid{grid-template-columns:1fr;gap:10px;}
  .search-bar,.global-search,.adv-search{padding:14px 16px;}
  .search-bar label{white-space:normal;flex:1 1 100%;}
  .search-bar .btn,.search-bar form,.global-search .gs-row,.as-row{width:100%;}
  .global-search input,.search-bar input,.as-row input{min-width:0;width:100%;}
  .as-row .btn{width:100%;}
  .as-tab{flex:1 1 auto;text-align:center;padding:8px 6px;}
  table{font-size:12px;display:block;overflow-x:auto;white-space:nowrap;}
  th,td{padding:7px 8px;}
  .contrato-title{white-space:normal;}
  .site-footer{flex-direction:column;align-items:flex-start;max-width:100%;}
  .site-footer .ft-links{gap:10px 14px;}
  .colabora-bar{flex-direction:column;align-items:flex-start;max-width:100%;margin:32px auto 0;}
  .colabora-bizum{align-self:stretch;text-align:center;}
  .comentario-form .btn{align-self:stretch;}
  .static-page{padding:22px 18px;}
  .ad-banner{max-width:100%;}
  .cobertura-grid{grid-template-columns:1fr;}
  .scroll-hint{
    display:flex;align-items:center;gap:2px;
    position:absolute;top:16px;right:6px;z-index:2;pointer-events:none;
    background:rgba(22,27,34,.92);border:1px solid rgba(88,166,255,.45);color:var(--blue);
    font-family:'IBM Plex Mono',monospace;font-size:10px;font-weight:600;letter-spacing:.3px;
    padding:4px 8px;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,.4);
    animation:scroll-hint-nudge 1.6s ease-in-out infinite;
  }
}
@media (max-width:420px){
  .muni-grid{grid-template-columns:1fr;}
}
@media (max-width:860px){
  .home-grid{grid-template-columns:1fr;}
  .noticias-ue-panel{position:static;}
}
@keyframes scroll-hint-nudge{
  0%,100%{transform:translateX(0);}
  50%{transform:translateX(4px);}
}
"""


def spinner_page(job_id, municipio, provincia="murcia"):
    es_girona = provincia == "girona"
    label = PROVINCIA_LABEL.get(provincia, PROVINCIA_LABEL["murcia"])
    fuente_txt = ("Datos oficiales: PSCP (Generalitat de Catalunya)" if es_girona else
                  "Datos oficiales: PLACE (Ministerio de Hacienda) + BORM (Boletín Oficial Región de Murcia)")
    fuente_corta = "PSCP" if es_girona else "PLACE (Ministerio de Hacienda) y BORM"
    redirect_url = f"/?muni={quote_plus(municipio)}" + ("&provincia=girona" if es_girona else "")
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<script async src="https://www.googletagmanager.com/gtag/js?id=G-86Q210M1DC"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', 'G-86Q210M1DC');
</script>
<title>Buscando — {esc(municipio)}</title>
<link rel="stylesheet" href="/static/style.css"></head>
<body>
<header>
  <div class="logo">DINERO&nbsp;PÚBLICO</div>
  <div><h1>Contratos Públicos · {esc(label)}</h1>
  <p>{esc(fuente_txt)}</p></div>
</header>
<div class="main">
  <div class="sp-wrap">
    <div class="sp-ring" id="ring"></div>
    <div class="sp-label">Analizando contratos de <strong>{esc(municipio)}</strong><br>
    Descargando datos de {esc(fuente_corta)}…</div>
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
    if(d.status==="done"){{window.location.href="{redirect_url}";return;}}
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
BIZUM_TELEFONO = "661657013"

# ─── PWA: manifest + service worker (2026-08-05) ─────────────────────────────
# Instalable como app en Android/Chrome (banner automático) e iOS/Safari
# (Compartir > Añadir a pantalla de inicio, manual, sin banner -- iOS no
# soporta beforeinstallprompt). Colores tomados de las variables CSS ya
# existentes (--bg y --surface, ver _ALL_CSS_CONTENT) para que la barra de
# estado/task switcher combine con el sitio real, no un color inventado.
PWA_THEME_COLOR = "#161b22"       # --surface, mismo fondo que <header>
PWA_BACKGROUND_COLOR = "#0d1117"  # --bg, fondo de la pantalla de carga

PWA_MANIFEST = {
    "id": "/",
    "name": "Dinero Público — Contratación pública en España",
    "short_name": "Dinero Público",
    "description": "Consulta los contratos públicos, sueldos de alcaldes y deuda "
                    "municipal en España. Datos oficiales PLACE, BORM, PSCP e INE.",
    "lang": "es",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "background_color": PWA_BACKGROUND_COLOR,
    "theme_color": PWA_THEME_COLOR,
    "icons": [
        {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "maskable"},
        {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
        {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ],
}

# Service worker deliberadamente mínimo: su único trabajo es cumplir el
# requisito de Chrome de un SW con manejador `fetch` para que aparezca el
# banner automático de instalación (ver informe de viabilidad 2026-08-05).
# Cachea SOLO los estáticos que no cambian (CSS, logo, iconos, el propio
# manifest) -- todo lo demás (HTML de municipios/rankings, /api/*, cualquier
# POST) va SIEMPRE a red sin tocar caché, porque son datos de contratos que
# se actualizan a diario vía cron y nunca deben servirse desactualizados.
# CACHE_NAME lleva fecha para poder invalidar cachés viejas cambiándola --
# ver el evento 'activate', que borra cualquier caché con otro nombre.
_PWA_SW_JS = """
const CACHE_NAME = "dinero-publico-static-v1";
const STATIC_PATHS = [
  "/static/style.css",
  "/static/logo.svg",
  "/static/icon-192.png",
  "/static/icon-512.png",
  "/static/apple-touch-icon.png",
  "/manifest.json",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_PATHS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(names.filter((n) => n !== CACHE_NAME).map((n) => caches.delete(n)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  const isStatic = event.request.method === "GET" && STATIC_PATHS.includes(url.pathname);

  if (!isStatic) {
    // Todo lo que no sea un estatico conocido va directo a red, sin
    // interceptar ni cachear -- contratos, rankings, busquedas, comentarios
    // y cualquier POST deben ser siempre datos frescos.
    return;
  }

  // Estaticos: stale-while-revalidate (sirve de cache al instante si existe,
  // y de paso actualiza la cache en segundo plano para la proxima visita).
  event.respondWith(
    caches.open(CACHE_NAME).then((cache) =>
      cache.match(event.request).then((cached) => {
        const fetchPromise = fetch(event.request).then((response) => {
          cache.put(event.request, response.clone());
          return response;
        }).catch(() => cached);
        return cached || fetchPromise;
      })
    )
  );
});
"""

REGISTRO_MERCANTIL_URL = "https://www.registradores.org/actualidad/portal-notarial/registro-mercantil-en-linea"
REGISTRO_ASOCIACIONES_URL = "https://www.interior.gob.es/opencms/es/servicios-al-ciudadano/tramites-y-gestiones/asociaciones/consulta-del-fichero-de-denominaciones/"
REGISTRO_COOPERATIVAS_URL = "https://www.mites.gob.es/es/sec_trabajo/autonomos/economia-social/Regsociedades/index.htm"


def _registro_correcto(nif):
    """El Registro Mercantil no es el registro correcto para todos los NIF:
    las asociaciones (letra G) se inscriben en el Registro Nacional de
    Asociaciones y las cooperativas (letra F) en el Registro de
    Cooperativas -- nunca van a aparecer en el Registro Mercantil, así que
    enlazar ahí es directamente engañoso para el lector. Es la causa
    dominante del peor % de directivos localizados en Girona (más
    asociaciones/cooperativas entre sus adjudicatarios que Murcia)."""
    letra = (nif or "").strip()[:1].upper()
    if letra == "G":
        return "Registro Nacional de Asociaciones", REGISTRO_ASOCIACIONES_URL
    if letra == "F":
        return "Registro de Cooperativas", REGISTRO_COOPERATIVAS_URL
    return "Registro Mercantil", REGISTRO_MERCANTIL_URL

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
    ayuntamiento: 'Nombre del municipio…',
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

  function filaMunicipio(m) {
    var row = el('div', 'as-row-result');
    var top = el('div', 'as-rr-top');
    top.appendChild(el('span', 'as-rr-empresa', '🏛 ' + m.municipio));
    if (m.cached) top.appendChild(el('span', 'as-rr-importe', m.total_importe));
    row.appendChild(top);
    row.appendChild(el('div', 'as-rr-sub', '📍 ' + m.provincia_label +
      (m.cached ? ' · ' + m.total_contratos + ' contratos' : ' · aún sin datos cargados')));
    var form = document.createElement('form');
    form.method = 'POST'; form.action = '/buscar'; form.style.marginTop = '8px';
    var iMuni = document.createElement('input');
    iMuni.type = 'hidden'; iMuni.name = 'municipio'; iMuni.value = m.municipio;
    var iProv = document.createElement('input');
    iProv.type = 'hidden'; iProv.name = 'provincia'; iProv.value = m.provincia;
    var btnVer = document.createElement('button');
    btnVer.type = 'submit'; btnVer.className = 'btn btn-primary';
    btnVer.style.padding = '6px 14px'; btnVer.style.fontSize = '12px';
    btnVer.textContent = m.cached ? 'Ver contratos →' : 'Buscar contratos →';
    form.appendChild(iMuni); form.appendChild(iProv); form.appendChild(btnVer);
    row.appendChild(form);
    return row;
  }

  function renderAyuntamiento(data) {
    results.innerHTML = '';
    if (!data.resultados || !data.resultados.length) {
      results.appendChild(el('div', 'empty', 'Sin municipios que coincidan.'));
      return;
    }
    var head = el('div', 'as-total', data.resultados.length + ' municipio(s) encontrado(s).');
    results.appendChild(head);
    data.resultados.forEach(function(m){ results.appendChild(filaMunicipio(m)); });
  }

  function buscar() {
    var q = input.value.trim();
    if (q.length < 2) { results.innerHTML = ''; return; }
    var mySeq = ++seq;
    results.innerHTML = '';
    results.appendChild(el('div', 'as-loading', 'Buscando…'));
    fetch('/api/buscar?tipo=' + encodeURIComponent(tipo) + '&q=' + encodeURIComponent(q) +
          '&provincia=' + encodeURIComponent(window.__PROVINCIA__ || 'todas'))
      .then(function(r){ return r.json(); })
      .then(function(data){
        if (mySeq !== seq) return; // respuesta obsoleta, ya se lanzó otra búsqueda
        if (data.error) { results.innerHTML = ''; results.appendChild(el('div', 'empty', data.error)); return; }
        if (tipo === 'ayuntamiento') renderAyuntamiento(data);
        else if (tipo === 'empresa') renderEmpresa(data);
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


def _header_html(provincia="todas"):
    es_girona = provincia == "girona"
    rankings_href = "/rankings?provincia=girona" if es_girona else "/rankings"
    return f"""<header>
  <a href="/" class="header-brand" style="text-decoration:none;display:flex;align-items:center;gap:14px;">
    <div class="logo-svg">{LOGO_SVG}</div>
    <div>
      <h1 style="color:var(--text)">Dinero Público · Contratación pública en España</h1>
      <p>{esc(SITE_TAGLINE)}</p>
    </div>
  </a>
  <nav class="header-nav">
    <a href="{rankings_href}">🏆 Rankings</a>
    <a href="{rankings_href}#alcaldes">💰 Sueldos Alcaldes</a>
    <a href="/fondos-ue" style="color:var(--yellow)">🇪🇺 Fondos UE</a>
    <button id="pwa-install-btn" class="pwa-install-btn" type="button" hidden>📲 Instalar app</button>
  </nav>
</header>"""


def _footer_html(provincia="todas"):
    es_girona = provincia == "girona"
    es_murcia = provincia == "murcia"
    if es_girona:
        fuente_links = '<a href="https://contractaciopublica.cat/" target="_blank" rel="noopener">PSCP</a>'
    elif es_murcia:
        fuente_links = ('<a href="https://contrataciondelsectorpublico.gob.es/" target="_blank" rel="noopener">PLACE</a>\n'
                         '    <a href="https://www.borm.es/" target="_blank" rel="noopener">BORM</a>')
    else:
        fuente_links = ('<a href="https://contrataciondelsectorpublico.gob.es/" target="_blank" rel="noopener">PLACE</a>\n'
                         '    <a href="https://www.borm.es/" target="_blank" rel="noopener">BORM</a>\n'
                         '    <a href="https://contractaciopublica.cat/" target="_blank" rel="noopener">PSCP</a>')
    brand_label = PROVINCIA_LABEL.get(provincia, PROVINCIA_LABEL["todas"])
    return f"""<div class="colabora-bar">
  <div class="colabora-text">
    <b>🤝 Colabora</b> — La transparencia no se regala, se construye.
    Si este proyecto te ha servido para saber en qué se gasta el dinero de todos,
    ayúdanos a que siga en pie.
  </div>
  <span class="colabora-bizum" title="Envía un Bizum a este número desde tu app del banco">
    💙 Bizum: {BIZUM_TELEFONO}
  </span>
</div>
<footer class="site-footer">
  <div class="ft-brand">© Dinero Público — datos oficiales públicos, {esc(brand_label)}</div>
  <div class="ft-links">
    {fuente_links}
    <a href="https://www.boe.es/" target="_blank" rel="noopener">BOE</a>
    <a href="{esc(REGISTRO_MERCANTIL_URL)}" target="_blank" rel="noopener">Registro Mercantil</a>
    <a href="{'/rankings?provincia=girona' if es_girona else '/rankings'}">Rankings</a>
    <a href="{'/rankings?provincia=girona' if es_girona else '/rankings'}#alcaldes">Sueldos Alcaldes</a>
    <a href="/fondos-ue">Fondos UE</a>
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


def _page_shell(title, body_html, description="", extra_head="", provincia="todas"):
    full_title = title if "|" in title else f"{title} | Dinero Público"
    desc = esc(description or "Consulta los contratos públicos adjudicados en España "
                               "con los directivos de las empresas adjudicatarias. "
                               "Datos oficiales PLACE + BORM + PSCP + Registro Mercantil.")
    return f"""<!DOCTYPE html>
<html lang="es"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<script async src="https://www.googletagmanager.com/gtag/js?id=G-86Q210M1DC"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', 'G-86Q210M1DC');
</script>
<title>{esc(full_title)}</title>
<meta name="description" content="{desc}">
<meta name="robots" content="index, follow">
<link rel="canonical" href="{esc(SITE_URL)}/">
<link rel="icon" type="image/svg+xml" href="/static/logo.svg">
<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="{PWA_THEME_COLOR}">
<link rel="apple-touch-icon" href="/static/apple-touch-icon.png">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Dinero Público">
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
{_header_html(provincia)}
<div class="main">
{_ad_banner_html()}
{body_html}
</div>
{_footer_html(provincia)}
<script>
  if ('serviceWorker' in navigator) {{
    window.addEventListener('load', function() {{
      navigator.serviceWorker.register('/sw.js');
    }});
  }}
  (function() {{
    // Botón "Instalar app" custom (header) en vez de fiarse solo del
    // mini-infobar automático de Chrome, que es fácil de perder de vista.
    // Solo aparece en navegadores que disparan beforeinstallprompt
    // (Chrome/Edge/Android) -- en el resto (Firefox, iOS Safari) el botón
    // se queda oculto para siempre, que es el comportamiento correcto: ahí
    // no existe ese evento y la instalación es manual (Compartir > Añadir a
    // pantalla de inicio).
    var installBtn = document.getElementById('pwa-install-btn');
    var deferredPrompt = null;
    if (window.matchMedia('(display-mode: standalone)').matches) {{
      return;  // ya instalada, no hace falta ofrecer el botón
    }}
    window.addEventListener('beforeinstallprompt', function(e) {{
      e.preventDefault();
      deferredPrompt = e;
      if (installBtn) installBtn.hidden = false;
    }});
    if (installBtn) {{
      installBtn.addEventListener('click', function() {{
        if (!deferredPrompt) return;
        installBtn.hidden = true;
        deferredPrompt.prompt();
        deferredPrompt.userChoice.then(function() {{ deferredPrompt = null; }});
      }});
    }}
    window.addEventListener('appinstalled', function() {{
      if (installBtn) installBtn.hidden = true;
      deferredPrompt = null;
    }});
  }})();
</script>
</body></html>"""


def _render_fila_contrato(c, municipio_label=None, municipio=None, provincia=None):
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
        match = _detectar_coincidencia_cargo(directivo, municipio or municipio_label, provincia)
        if match:
            if match["tipo"] == "local":
                match_html = (
                    f'<div class="cargo-match cargo-match-local">'
                    f'⚠️ Coincidencia de nombre — verificar<br>'
                    f'<span class="cargo-match-detalle">Mismo nombre y apellidos que {esc(match["cargo"].lower())} '
                    f'de {esc(match["municipio"])}. No implica necesariamente relación — dato para verificar.</span>'
                    f'</div>'
                )
            else:
                match_html = (
                    f'<div class="cargo-match cargo-match-regional">'
                    f'🔎 Coincidencia de nombre (otro municipio) — verificar<br>'
                    f'<span class="cargo-match-detalle">Mismo nombre y apellidos que {esc(match["cargo"].lower())} '
                    f'de {esc(match["municipio"])}. No implica necesariamente relación — dato para verificar.</span>'
                    f'</div>'
                )
        else:
            match_html = ""
        dir_html = (f'<div class="directivo">{esc(directivo)}</div>'
                     f'<div class="cargo">{esc(c.get("cargo",""))}</div>{match_html}')
    else:
        empresa_q = quote_plus(c.get("empresa", ""))
        registro_label, registro_url = _registro_correcto(c.get("nif", ""))
        rm_link = (f'<a href="{esc(registro_url)}" target="_blank" rel="noopener" '
                   f'title="Buscar {esc(c.get("empresa",""))} en el {esc(registro_label)}">'
                   f'{esc(registro_label)} ↗</a>') if empresa_q else ""
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
    elif fuente == "PSCP" and url:
        link_html = (f'<a class="link pscp-link" href="{esc(url)}" target="_blank" '
                     f'title="Fitxa a contractaciopublica.cat">PSCP ↗</a>')
    elif url:
        link_html = f'<a class="link" href="{esc(url)}" target="_blank" title="Ficha en PLACE">PLACE ↗</a>'
    else:
        link_html = ""

    borm_url = c.get("borm_url", "")
    borm_extra = (f' <a class="link borm-link" href="{esc(borm_url)}" target="_blank" '
                  f'title="Ver publicación BORM">BORM ↗</a>') if borm_url else ""

    lid = c.get("licitacion_id", "")
    titulo = c.get("titulo", "")
    icono = _icono_contrato(titulo)

    if lid and titulo:
        contrato_line = f'Licit. {esc(lid)} — {esc(titulo[:110])}'
    elif lid:
        contrato_line = f'Licit. {esc(lid)}'
    else:
        contrato_line = esc(titulo[:110])
    contrato_html = (f'<div class="contrato-title"><span class="icon-tipo">{icono}</span>{contrato_line}</div>'
                      if contrato_line else "")

    fuente_badge = {
        "BORM": '<span class="fuente-badge fuente-borm">BORM</span>',
        "PSCP": '<span class="fuente-badge fuente-pscp">PSCP</span>',
    }.get(fuente, '<span class="fuente-badge fuente-place">PLACE</span>')

    muni_html = (f'<div class="lid" style="margin-top:2px">📍 {esc(municipio_label)}</div>'
                 if municipio_label else "")

    ute_socios = c.get("ute_socios") or []
    ute_html = (f' <span class="ute-nota">(UTE con {esc(", ".join(ute_socios))})</span>'
                if ute_socios else "")

    return f"""<tr>
      <td>
        <div class="empresa">{esc(c.get('empresa', '—'))}{ute_html} {fuente_badge}</div>
        {contrato_html}{muni_html}
      </td>
      <td class="{imp_cls}">{esc(imp)}</td>
      <td>{dir_html}</td>
      <td>
        <span class="estado-badge est-{esc(est)}">{esc(est_label)}</span>
        <div style="margin-top:4px">{link_html}{borm_extra}</div>
      </td>
    </tr>"""


def _calcular_ranking_alcaldes():
    """Ranking de sueldos de alcaldes/alcaldesas (ISPA), de mayor a menor
    importe anual. El nombre/partido viene de ALCALDES_CONCEJALES
    (concejales.redsara.es) y el importe de RETRIBUCIONES_ISPA (Portal
    MTDFP) -- dos fuentes distintas, igual que en alcalde_concejales_html(),
    así que solo entran al ranking los municipios que tienen AMBOS datos.
    Verificado el 2026-08-04: 239/266 (los otros 27 tienen alcalde/sa
    identificado pero ISPA no ha publicado o no ha podido atribuir su
    retribución todavía).
    Habitantes y deuda por habitante se añaden reutilizando POBLACION y
    DEUDA_VIVA (mismos datos ya cargados para la ficha de municipio, ver
    _cargar_poblacion/_cargar_hacienda_eell) -- ninguna fuente nueva.
    Ninguno de los dos es obligatorio para entrar en el ranking (sigue
    ordenado por sueldo), simplemente pueden venir vacíos ("") si el
    municipio no tiene ese dato."""
    filas = []
    for clave, retrib in RETRIBUCIONES_ISPA.items():
        importe = retrib.get("importe")
        if importe is None:
            continue
        info = ALCALDES_CONCEJALES.get(clave)
        if not info:
            continue
        nombre = (info.get("alcalde") or {}).get("nombre", "")
        if not nombre:
            continue
        municipio = retrib.get("municipio") or info.get("municipio", "")
        pob_info = POBLACION.get(normalizar(municipio))
        habitantes = pob_info["poblacion"] if pob_info else None
        deuda_info = DEUDA_VIVA.get(normalizar(municipio))
        deuda_por_habitante = None
        if deuda_info and habitantes:
            deuda_por_habitante = deuda_info["deuda_eur"] / habitantes
        filas.append({
            "nombre": _capitalizar_nombre(nombre),
            "partido": (info.get("alcalde") or {}).get("partido", ""),
            "municipio": municipio,
            "provincia": retrib.get("provincia") or info.get("provincia", ""),
            "importe": importe,
            "anio": retrib.get("anio", ""),
            "habitantes": habitantes,
            "deuda_por_habitante": deuda_por_habitante,
        })
    filas.sort(key=lambda f: f["importe"], reverse=True)
    return filas


def _calcular_ranking_deuda_por_habitante():
    """Ranking de deuda viva municipal por habitante, de mayor a menor,
    reutilizando DEUDA_VIVA y POBLACION (Ministerio de Hacienda + INE, ya
    cargados para la ficha de municipio -- ver _cargar_hacienda_eell/
    _cargar_poblacion) -- ninguna fuente nueva. Solo entran los municipios
    con ambos datos (deuda y población); se excluyen los pseudo-municipios
    ("Región de Murcia", AGE...) porque no tienen población propia."""
    filas = []
    for clave, deuda_info in DEUDA_VIVA.items():
        pob_info = POBLACION.get(clave)
        if not pob_info or not pob_info.get("poblacion"):
            continue
        municipio = deuda_info.get("municipio") or pob_info.get("municipio", "")
        if es_pseudo_municipio(municipio):
            continue
        habitantes = pob_info["poblacion"]
        deuda_eur = deuda_info["deuda_eur"]
        filas.append({
            "municipio": municipio,
            "provincia": deuda_info.get("provincia") or pob_info.get("provincia", ""),
            "deuda_eur": deuda_eur,
            "habitantes": habitantes,
            "deuda_por_habitante": deuda_eur / habitantes,
        })
    filas.sort(key=lambda f: f["deuda_por_habitante"], reverse=True)
    return filas


def _calcular_rankings(datos):
    """Agrupa todos los contratos cargados por empresa y devuelve dos listas
    Top 10: por número de contratos y por importe total adjudicado. Cada
    entrada incluye el directivo/cargo identificado (el primero que se
    encuentre para esa empresa), si lo tenemos."""
    por_empresa = {}
    for d in datos:
        for c in d.get("contratos", []):
            emp = c.get("empresa", "")
            if not emp or emp == "No localizada":
                continue
            key = normalizar(emp)
            g = por_empresa.setdefault(key, {
                "empresa": emp, "n": 0, "importe": 0.0,
                "directivo": "", "cargo": "",
            })
            g["n"] += 1
            g["importe"] += c.get("importe_num", 0.0) or 0.0
            if not g["directivo"] and c.get("directivo"):
                g["directivo"] = c.get("directivo")
                g["cargo"] = c.get("cargo", "")

    lista = list(por_empresa.values())
    top_n = sorted(lista, key=lambda g: g["n"], reverse=True)[:10]
    top_imp = sorted(lista, key=lambda g: g["importe"], reverse=True)[:10]
    return top_n, top_imp


def render_rankings_html(datos_nacional, datos_provincia, provincia_prov="murcia"):
    """Dos rankings claramente separados:
    - Nacional: agrega TODAS las provincias cargadas (Murcia + Girona + las que vengan).
    - Provincial: el mismo top 10 x2, filtrable por una provincia concreta.
    """
    top_n_nac, top_imp_nac = _calcular_rankings(datos_nacional)
    top_n_prov, top_imp_prov = _calcular_rankings(datos_provincia)
    label_prov = PROVINCIA_LABEL.get(provincia_prov, PROVINCIA_LABEL["murcia"])

    def _filas(lista, valor_html, q_prov=""):
        filas = ""
        for i, g in enumerate(lista, 1):
            pos = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}º")
            if g["directivo"]:
                dir_html = (f'<div class="directivo">{esc(g["directivo"])}</div>'
                            f'<div class="cargo">{esc(g["cargo"])}</div>')
            else:
                dir_html = '<span class="noloc-warn">⚠️ No localizado</span>'
            emp_q = quote_plus(g["empresa"])
            filas += f"""<tr>
              <td class="rk-pos">{pos}</td>
              <td><a class="rk-empresa" href="/?q={emp_q}{q_prov}">{esc(g['empresa'])}</a></td>
              <td class="rk-valor">{valor_html(g)}</td>
              <td>{dir_html}</td>
            </tr>"""
        if not filas:
            filas = '<tr><td colspan="4" class="empty">Aún no hay datos suficientes.</td></tr>'
        return filas

    # Los enlaces de empresa del ranking nacional no se filtran por provincia
    # (la empresa puede tener contratos en más de una); los del provincial sí.
    tabla_n_nac = _filas(top_n_nac, lambda g: f'<b>{g["n"]}</b> contratos')
    tabla_imp_nac = _filas(top_imp_nac, lambda g: fmt_eur(str(g["importe"])))
    q_prov_link = f"&provincia={provincia_prov}"
    tabla_n_prov = _filas(top_n_prov, lambda g: f'<b>{g["n"]}</b> contratos', q_prov=q_prov_link)
    tabla_imp_prov = _filas(top_imp_prov, lambda g: fmt_eur(str(g["importe"])), q_prov=q_prov_link)

    ranking_alcaldes = _calcular_ranking_alcaldes()
    anio_ispa = next((f["anio"] for f in ranking_alcaldes if f.get("anio")), "")
    filas_alcaldes_html = ""
    for i, f in enumerate(ranking_alcaldes, 1):
        pos = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}º")
        muni_q = quote_plus(f["municipio"])
        q_prov_muni = "&provincia=girona" if f["provincia"] == "girona" else ""
        partido_html = (esc(f["partido"]) if f["partido"]
                         else '<span class="noloc-warn">Sin partido registrado</span>')
        habitantes_html = fmt_num(f["habitantes"]) if f["habitantes"] else "—"
        deuda_hab_html = (fmt_eur(f["deuda_por_habitante"]) + "/hab."
                           if f["deuda_por_habitante"] is not None else "—")
        filas_alcaldes_html += f"""<tr>
          <td class="rk-pos">{pos}</td>
          <td><b class="pol-nombre">{esc(f['nombre'])}</b></td>
          <td><a class="rk-empresa" href="/?muni={muni_q}{q_prov_muni}">{esc(f['municipio'])}</a></td>
          <td>{partido_html}</td>
          <td class="rk-valor">{fmt_eur(f['importe'])}/año</td>
          <td>{habitantes_html}</td>
          <td class="rk-valor">{deuda_hab_html}</td>
        </tr>"""
    if not filas_alcaldes_html:
        filas_alcaldes_html = '<tr><td colspan="7" class="empty">Aún no hay datos suficientes.</td></tr>'

    ranking_deuda_hab = _calcular_ranking_deuda_por_habitante()
    filas_deuda_hab_html = ""
    for i, f in enumerate(ranking_deuda_hab, 1):
        pos = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}º")
        muni_q = quote_plus(f["municipio"])
        q_prov_muni = "&provincia=girona" if f["provincia"] == "girona" else ""
        filas_deuda_hab_html += f"""<tr>
          <td class="rk-pos">{pos}</td>
          <td><a class="rk-empresa" href="/?muni={muni_q}{q_prov_muni}">{esc(f['municipio'])}</a></td>
          <td>{fmt_eur(f['deuda_eur'])}</td>
          <td>{fmt_num(f['habitantes'])}</td>
          <td class="rk-valor">{fmt_eur(f['deuda_por_habitante'])}/hab.</td>
        </tr>"""
    if not filas_deuda_hab_html:
        filas_deuda_hab_html = '<tr><td colspan="5" class="empty">Aún no hay datos suficientes.</td></tr>'

    selector_prov = "".join(
        f'<a href="/rankings?provincia={prov}" class="prov-tab{" active" if prov == provincia_prov else ""}">'
        f'{esc(PROVINCIA_LABEL.get(prov, prov))}</a>'
        for prov in MUNICIPIOS_POR_PROVINCIA
    )

    body = f"""<span class="back-link"><a href="/">← Volver al inicio</a></span>
  <div class="hero" style="padding-bottom:4px">
    <div class="hero-tagline">🏆 Rankings</div>
    <p class="hero-sub">
      Clasificación de las empresas adjudicatarias con más contratos y mayor importe acumulado,
      con su directivo identificado cuando lo tenemos.
    </p>
  </div>

  <div class="rk-section-header">
    <h2>🌍 Ranking Nacional</h2>
    <span class="rk-badge">Región de Murcia + Provincia de Girona</span>
  </div>
  <div class="section-title">Top 10 por número de contratos adjudicados</div>
  <div class="muni-card"><table>
    <tr><th>#</th><th>Empresa</th><th>Contratos</th><th>Directivo / Cargo</th></tr>
    {tabla_n_nac}
  </table></div>
  <div class="section-title">Top 10 por importe total adjudicado</div>
  <div class="muni-card"><table>
    <tr><th>#</th><th>Empresa</th><th>Importe total</th><th>Directivo / Cargo</th></tr>
    {tabla_imp_nac}
  </table></div>

  <div class="rk-section-header">
    <h2>📍 Ranking por Provincia</h2>
    <div class="prov-switch">{selector_prov}</div>
  </div>
  <div class="section-title">Top 10 por número de contratos — {esc(label_prov)}</div>
  <div class="muni-card"><table>
    <tr><th>#</th><th>Empresa</th><th>Contratos</th><th>Directivo / Cargo</th></tr>
    {tabla_n_prov}
  </table></div>
  <div class="section-title">Top 10 por importe total — {esc(label_prov)}</div>
  <div class="muni-card"><table>
    <tr><th>#</th><th>Empresa</th><th>Importe total</th><th>Directivo / Cargo</th></tr>
    {tabla_imp_prov}
  </table></div>

  <div class="rk-section-header" id="alcaldes">
    <h2>💰 Ranking de Sueldos: Alcaldes y Alcaldesas</h2>
    <span class="rk-badge">ISPA {esc(anio_ispa)} · {len(ranking_alcaldes)} municipios con dato</span>
  </div>
  <div class="section-title">De mayor a menor retribución anual (Murcia + Girona)</div>
  <div class="muni-card"><div class="tbl-scroll"><table>
    <tr><th>#</th><th>Alcalde/sa</th><th>Municipio</th><th>Partido</th><th>Sueldo anual</th><th>Habitantes</th><th>Deuda/hab.</th></tr>
    {filas_alcaldes_html}
  </table></div></div>

  <div class="rk-section-header" id="deuda-habitante">
    <h2>🏦 Ranking de Deuda por Habitante</h2>
    <span class="rk-badge">Ministerio de Hacienda + INE · {len(ranking_deuda_hab)} municipios con dato</span>
  </div>
  <div class="section-title">De mayor a menor deuda viva por habitante (Murcia + Girona)</div>
  <div class="muni-card"><div class="tbl-scroll"><table>
    <tr><th>#</th><th>Municipio</th><th>Deuda viva</th><th>Habitantes</th><th>Deuda/hab.</th></tr>
    {filas_deuda_hab_html}
  </table></div></div>"""

    return _page_shell("Rankings — Top 10 empresas", body,
                        description="Ranking nacional y por provincia de las empresas con más contratos "
                                     "públicos y mayor importe adjudicado, con sus directivos identificados.",
                        provincia="todas")


_FUENTE_UE_LABEL = {
    "cordis": ("CORDIS", "fuente-cordis", "Horizon Europe -- proyectos de investigación e innovación"),
    "cohesion": ("Cohesion Data", "fuente-cohesion", "Fondos estructurales FEDER/FSE 2014-2020"),
}


def _render_fila_fondo_ue(f):
    fuente_label, fuente_cls, _ = _FUENTE_UE_LABEL.get(f["fuente"], (f["fuente"], "fuente-cordis", ""))
    fuente_badge = f'<span class="fuente-badge {fuente_cls}">{esc(fuente_label)}</span>'

    if f["beneficiario"]:
        nif_html = f'<div class="fue-nif">{esc(f["nif"])}</div>' if f.get("nif") else ""
        rol_html = f' <span class="ute-nota">({esc(f["rol"])})</span>' if f.get("rol") else ""

        # Gerente/administrador del beneficiario, con el MISMO detector y
        # caché que los adjudicatarios de contratos públicos (buscar_directivo,
        # ver enriquecer_directivos_fondos_ue) -- lectura de caché aquí,
        # nunca se lanza la búsqueda en el hilo de render.
        dir_nombre, dir_cargo = _dir_cache_get(f["beneficiario"], f.get("nif", "") or "")
        gerente_html = (f'<div class="lid" style="margin-top:2px">👤 {esc(dir_nombre)} — {esc(dir_cargo)}</div>'
                         if dir_nombre else "")

        # Mismo detector que ya usan los contratos públicos (cargo público vs
        # adjudicatario/directivo) -- aquí aplicado al beneficiario del fondo
        # UE. Solo tiene sentido para CORDIS: Cohesion Data no trae nombre de
        # beneficiario para España (ver diagnóstico), así que ahí "empresa"
        # suele ser una entidad (universidad, pyme...) y esto no da falsos
        # positivos porque el índice de cargos públicos solo casa con
        # nombre+apellidos completos, nunca con razones sociales.
        match = _detectar_coincidencia_cargo(f["beneficiario"], f.get("municipio"), f.get("provincia"))
        if match:
            if match["tipo"] == "local":
                match_html = (
                    f'<div class="cargo-match cargo-match-local">'
                    f'⚠️ Coincidencia de nombre — verificar<br>'
                    f'<span class="cargo-match-detalle">Mismo nombre y apellidos que {esc(match["cargo"].lower())} '
                    f'de {esc(match["municipio"])}. No implica necesariamente relación — dato para verificar.</span>'
                    f'</div>'
                )
            else:
                match_html = (
                    f'<div class="cargo-match cargo-match-regional">'
                    f'🔎 Coincidencia de nombre (otro municipio) — verificar<br>'
                    f'<span class="cargo-match-detalle">Mismo nombre y apellidos que {esc(match["cargo"].lower())} '
                    f'de {esc(match["municipio"])}. No implica necesariamente relación — dato para verificar.</span>'
                    f'</div>'
                )
        else:
            match_html = ""

        benef_html = f'<div class="empresa">{esc(f["beneficiario"])}{rol_html}</div>{nif_html}{gerente_html}{match_html}'
    else:
        benef_html = '<span class="noloc-warn">Beneficiario no publicado por la fuente</span>'

    municipio_html = (f'<div class="lid" style="margin-top:2px">📍 {esc(f["municipio"])}</div>'
                       if f.get("municipio") else "")

    fechas = ""
    if f.get("fecha_inicio"):
        fi = f["fecha_inicio"][:10]
        ff = f.get("fecha_fin", "")[:10]
        fechas = f'{esc(fi)}{" → " + esc(ff) if ff else ""}'

    link_html = (f'<a class="fue-link" href="{esc(f["url"])}" target="_blank" rel="noopener">Ver proyecto ↗</a>'
                 if f.get("url") else "")

    return f"""<tr>
      <td>
        <div class="empresa">{esc(f["titulo"][:110])}</div>
        {benef_html}
        {municipio_html}
      </td>
      <td class="fue-importe">{fmt_eur(str(f["importe_num"])) if f["importe_num"] else "—"}</td>
      <td>{fuente_badge}<div class="cargo">{esc(f.get("programa","") or f.get("fondo",""))}</div></td>
      <td><div class="lid">{fechas}</div>{link_html}</td>
    </tr>"""


_FUENTE_CM_LABEL = {
    "rpc-girona":      "RPC",
    "fuente-alamo":    "F. Álamo",
    "mula":            "Mula",
    "molina-segura":   "Molina",
    "lorqui":          "Lorquí",
    "lorca":           "Lorca",
}


def _render_fila_contrato_menor(r):
    """Fila de la tabla de contratos menores locales -- compartida por todas
    las fuentes (Girona/RPC, Fuente Álamo, Mula, Molina de Segura...). No
    todas traen NIF ni URL por registro (ninguna de las cuatro fuentes de
    momento las publica de forma completa), así que ambos se muestran solo
    si vienen informados."""
    adjudicatari = r.get("adjudicatari", "")
    fuente = r.get("fuente", "")
    fuente_badge = f'<span class="fuente-badge fuente-rpc">{esc(_FUENTE_CM_LABEL.get(fuente, fuente or "?"))}</span>'
    nif_html = f'<div class="cm-nif">{esc(r["nif"])}</div>' if r.get("nif") else ""

    # Mismo detector que ya usan contratos públicos y fondos UE, pero probando
    # también variantes de orden de nombre (ver _variantes_nombre_para_detector)
    # -- necesario para Girona (formato "Apellidos, Nombre") y Molina de Segura
    # (formato "Apellidos Nombre" sin coma); Fuente Álamo y Mula ya traen el
    # nombre en el orden correcto, pero probar variantes de más nunca genera
    # falsos positivos (el detector exige coincidencia EXACTA de nombre completo).
    match = None
    provincia_r = r.get("provincia") or "murcia"
    for variante in _variantes_nombre_para_detector(adjudicatari):
        match = _detectar_coincidencia_cargo(variante, r.get("municipio"), provincia_r)
        if match:
            break
    if match:
        cls = "cargo-match-local" if match["tipo"] == "local" else "cargo-match-regional"
        icono = "⚠️" if match["tipo"] == "local" else "🔎"
        otro_muni = "" if match["tipo"] == "local" else " (otro municipio)"
        match_html = (
            f'<div class="cargo-match {cls}">'
            f'{icono} Coincidencia de nombre{otro_muni} — verificar<br>'
            f'<span class="cargo-match-detalle">Mismo nombre y apellidos que {esc(match["cargo"].lower())} '
            f'de {esc(match["municipio"])}. No implica necesariamente relación — dato para verificar.</span>'
            f'</div>'
        )
    else:
        match_html = ""

    return f"""<tr>
      <td>
        <div class="empresa">{esc(adjudicatari)}{fuente_badge}</div>
        {nif_html}
        <div class="cargo">{esc(r.get("descripcio","")[:110])}</div>
        {match_html}
      </td>
      <td class="cm-importe">{fmt_eur(str(r["import_num"])) if r["import_num"] else "—"}</td>
      <td><div class="lid">{esc(r.get("tipus_contracte",""))}</div></td>
      <td><div class="lid">{esc(r.get("data_adjudicacio",""))}</div></td>
    </tr>"""


def render_fondos_ue_html(fondos, provincia="todas"):
    """Página de fondos y proyectos financiados por la UE (CORDIS + Cohesion
    Data), con estilo amarillo sobre azul distintivo respecto a los contratos públicos
    normales. Ver INFORME_NOCHE.md 2026-07-21/22 para el diagnóstico de
    fuentes."""
    total_importe = sum(f["importe_num"] for f in fondos)
    n_cordis = sum(1 for f in fondos if f["fuente"] == "cordis")
    n_cohesion = sum(1 for f in fondos if f["fuente"] == "cohesion")

    stats = f"""<div class="stats-bar">
      <div class="stat" style="border-color:rgba(88,166,255,.35)"><span style="color:var(--yellow)">{len(fondos)}</span>Proyectos/operaciones</div>
      <div class="stat" style="border-color:rgba(88,166,255,.35)"><span style="color:var(--yellow)">{fmt_eur(str(total_importe))}</span>Importe total</div>
      <div class="stat" style="border-color:rgba(88,166,255,.35)"><span style="color:var(--yellow)">{n_cordis}</span>CORDIS (Horizon Europe)</div>
      <div class="stat" style="border-color:rgba(88,166,255,.35)"><span style="color:var(--yellow)">{n_cohesion}</span>Cohesion Data (FEDER/FSE)</div>
    </div>"""

    selector_prov = "".join(
        f'<a href="/fondos-ue?provincia={prov}" class="prov-tab{" active" if prov == provincia else ""}">'
        f'{esc(PROVINCIA_LABEL.get(prov, prov))}</a>'
        for prov in MUNICIPIOS_POR_PROVINCIA
    )

    filas = "".join(_render_fila_fondo_ue(f) for f in fondos[:300])
    if not filas:
        filas = '<tr><td colspan="4" class="empty">Sin datos de fondos UE todavía para esta provincia.</td></tr>'
    aviso_limite = (f'<div class="gs-hint" style="margin-bottom:10px">Mostrando los primeros 300 de '
                     f'{len(fondos)}, ordenados por importe.</div>') if len(fondos) > 300 else ""

    body = f"""<span class="back-link"><a href="/">← Volver al inicio</a></span>
  <div class="hero" style="padding-bottom:4px">
    <div class="hero-tagline" style="color:var(--yellow)">🇪🇺 Fondos y proyectos financiados por la UE</div>
    <p class="hero-sub">
      Proyectos de investigación (CORDIS / Horizon Europe) y fondos estructurales
      (Cohesion Data, FEDER/FSE 2014-2020) que han recibido financiación europea en
      la Región de Murcia y la provincia de Girona. Fuentes oficiales de la Comisión
      Europea, sin scraping -- descarga/consulta directa de sus datasets abiertos.
    </p>
  </div>
  <div class="prov-switch" style="margin-bottom:14px">{selector_prov}</div>
  {stats}
  <div class="fue-card">
    {aviso_limite}
    <table>
      <tr>
        <th>Proyecto / Beneficiario</th>
        <th>Importe</th>
        <th>Fuente / Programa</th>
        <th>Fechas</th>
      </tr>
      {filas}
    </table>
  </div>"""

    return _page_shell("Fondos UE — Proyectos financiados por la Unión Europea", body,
                        description="Proyectos y fondos financiados por la Unión Europea (CORDIS, Horizon "
                                     "Europe, Cohesion Data FEDER/FSE) en la Región de Murcia y la provincia "
                                     "de Girona.",
                        provincia="todas")


def render_comentarios_html(tipo, clave_raw, redirect_url, titulo="esta ficha"):
    """Bloque 'Deja tu comentario' -- formulario simple sin gestión activa ni
    email: se guarda directamente en la tabla comentarios y se muestra
    público de inmediato, sin cola de moderación (decisión de César
    2026-08-05). Se usa tanto en la ficha de municipio (tipo='municipio',
    clave=nombre del municipio) como en los resultados de búsqueda por
    empresa (tipo='busqueda', clave=texto buscado), que es la única 'ficha
    de empresa' que existe hoy en el sitio -- no hay una página de perfil
    de empresa aparte, ver render_busqueda_global_html."""
    comentarios = _db_comentarios_por(tipo, clave_raw)
    if comentarios:
        filas = "".join(
            f"""<div class="comentario-item">
              <div class="comentario-meta"><b>{esc(c['nombre'] or 'Anónimo')}</b>
                <span class="comentario-fecha">{esc(datetime.fromtimestamp(c['ts']).strftime('%d/%m/%Y %H:%M'))}</span></div>
              <div class="comentario-texto">{esc(c['texto'])}</div>
            </div>"""
            for c in comentarios
        )
    else:
        filas = '<div class="empty" style="padding:14px 0">Todavía no hay comentarios. Sé el primero.</div>'

    return f"""<details class="comentarios-card" id="comentarios" open>
      <summary>💬 Comentarios <span class="badge">{len(comentarios)}</span></summary>
      <div class="comentarios-list">{filas}</div>
      <form method="POST" action="/comentario" class="comentario-form">
        <input type="hidden" name="tipo" value="{esc(tipo)}">
        <input type="hidden" name="clave" value="{esc(clave_raw)}">
        <input type="hidden" name="redirect" value="{esc(redirect_url)}">
        <input name="nombre" maxlength="60" placeholder="Tu nombre (opcional)">
        <textarea name="texto" maxlength="1000" required placeholder="Deja tu comentario sobre {esc(titulo)}…"></textarea>
        <button type="submit" class="btn btn-primary">Enviar comentario</button>
      </form>
    </details>"""


def render_html(datos, muni_filter="", page=1, page_cm=1, provincia="murcia"):
    q_prov = "&provincia=girona" if provincia == "girona" else ""
    q_prov_first = "?provincia=girona" if provincia == "girona" else ""
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

    back_html = f'<span class="back-link"><a href="/{q_prov_first}">← Ver todos los municipios</a></span>'

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

        filas = "".join(_render_fila_contrato(c, municipio=muni_name_d, provincia=d.get("provincia", provincia))
                         for c in contratos_shown)

        if not filas:
            filas = '<tr><td colspan="4" class="empty">Sin contratos adjudicados encontrados para este municipio</td></tr>'

        n_place = sum(1 for c in contratos_all if c.get("fuente", "PLACE") == "PLACE")
        n_borm  = sum(1 for c in contratos_all if c.get("fuente") == "BORM")
        n_pscp  = sum(1 for c in contratos_all if c.get("fuente") == "PSCP")
        fuentes_desc = []
        if n_place: fuentes_desc.append(f"PLACE: {n_place}")
        if n_borm:  fuentes_desc.append(f"BORM: {n_borm}")
        if n_pscp:  fuentes_desc.append(f"PSCP: {n_pscp}")
        fuentes_str = " · ".join(fuentes_desc) if fuentes_desc else "—"
        fuentes_label = ("Fuente: PSCP (Generalitat de Catalunya)" if provincia == "girona" else
                          "Fuentes: PLACE (Ministerio de Hacienda) + BORM (Región de Murcia)")

        muni_name     = muni_name_d
        muni_enc      = quote_plus(muni_name)
        profile_url   = d.get("place_profile", "" if provincia == "girona" else place_profile_url(muni_name))
        profile_html  = (f'<a href="{esc(profile_url)}" target="_blank" class="link" '
                          f'title="Perfil contratante en PLACE" style="font-size:11px">Perfil PLACE ↗</a>'
                          if profile_url else "")
        # Cuentas anuales (Plataforma de Rendición de Cuentas) -- no se
        # muestra en pseudo-municipios ("Región de Murcia", AGE, UMU...): no
        # son ayuntamientos y no tienen ficha propia ahí.
        # Población oficial (INE, Padrón Municipal) -- ver actualizar_poblacion.py.
        habitantes_html = ""
        if not es_pseudo_municipio(muni_name):
            pob_info = POBLACION.get(normalizar(muni_name))
            if pob_info:
                fuente_pob = POBLACION_FUENTE_URL.get(pob_info.get("provincia", ""), "")
                if fuente_pob:
                    habitantes_html = (f'<a href="{esc(fuente_pob)}" target="_blank" rel="noopener" '
                                        f'class="cuentas-link" title="Población oficial a 1 de enero de '
                                        f'{esc(pob_info.get("anio", ""))} (INE, Padrón Municipal)">'
                                        f'👥 {fmt_num(pob_info["poblacion"])} hab. ↗</a>')

        cuentas_html = ""
        if not es_pseudo_municipio(muni_name):
            cuentas_url = rendicion_cuentas_url(muni_name, d.get("provincia", provincia))
            if cuentas_url:
                cuentas_html = (f'<a href="{esc(cuentas_url)}" target="_blank" rel="noopener" '
                                 f'class="cuentas-link" title="Cuenta General y resultado de las '
                                 f'cuentas anuales en la Plataforma de Rendición de Cuentas">'
                                 f'📊 Cuentas anuales ↗</a>')
        # Importe (saldo no financiero, superávit/déficit real del último
        # ejercicio remitido) y deuda viva municipal -- Ministerio de
        # Hacienda, ver actualizar_deuda_y_liquidaciones.py. No todos los
        # municipios tienen saldo (algunos no han remitido ningún ejercicio
        # de los probados todavía), por eso se comprueba aparte de deuda.
        saldo_html = ""
        deuda_html = ""
        if not es_pseudo_municipio(muni_name):
            saldo_info = SALDO_NO_FINANCIERO.get(normalizar(muni_name))
            if saldo_info and saldo_info.get("importe_eur") is not None:
                ejercicio_saldo = saldo_info.get("ejercicio", "")
                importe_saldo = saldo_info["importe_eur"]
                fuente_saldo = saldo_info.get("fuente_url", "")
                etiqueta = "Superávit" if importe_saldo >= 0 else "Déficit"
                saldo_html = (f'<a href="{esc(fuente_saldo)}" target="_blank" rel="noopener" '
                               f'class="cuentas-link" title="Saldo presupuestario no financiero '
                               f'({etiqueta.lower()}) del ejercicio {esc(ejercicio_saldo)}, '
                               f'Ministerio de Hacienda">'
                               f'💶 {etiqueta} {esc(ejercicio_saldo)}: {fmt_eur(abs(importe_saldo))} ↗</a>')
            deuda_info = DEUDA_VIVA.get(normalizar(muni_name))
            if deuda_info and DEUDA_VIVA_FUENTE_URL:
                pob_info = POBLACION.get(normalizar(muni_name))
                por_habitante = ""
                if pob_info and pob_info.get("poblacion"):
                    por_habitante = f' ({fmt_eur(deuda_info["deuda_eur"] / pob_info["poblacion"])}/hab.)'
                deuda_html = (f'<a href="{esc(DEUDA_VIVA_FUENTE_URL)}" target="_blank" rel="noopener" '
                               f'class="cuentas-link" title="Deuda viva municipal a 31/12, '
                               f'Ministerio de Hacienda">'
                               f'🏦 Deuda viva: {fmt_eur(deuda_info["deuda_eur"])}{por_habitante} ↗</a>')
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
                prev_link = (f'<a href="/?muni={muni_enc}&pag={page-1}{q_prov}" class="pag-btn">← Anterior</a>'
                             if page > 1 else '')
                next_link = (f'<a href="/?muni={muni_enc}&pag={page+1}{q_prov}" class="pag-btn">Siguiente →</a>'
                             if page < total_pages else '')
                pag_html = (f'<div class="pagination">'
                            f'<span class="pag-info">Página {page} de {total_pages} · {total_muni} contratos</span>'
                            f'<div class="pag-links">{prev_link}{next_link}</div>'
                            f'</div>')
            else:
                pag_html = (f'<div class="pag-more">Mostrando los primeros {PAGE_SIZE} de {total_muni} contratos. '
                            f'<a href="/?muni={muni_enc}&pag=1{q_prov}">Ver todos →</a></div>')

        # Fondos y proyectos UE cruzados con este municipio (ver
        # _cruzar_municipio_fondo_ue) -- solo se muestra si hay al menos uno,
        # mismo estilo amarillo/azul que /fondos-ue para diferenciarlos de los
        # contratos públicos normales.
        fondos_ue_muni = _db_fondos_ue_por_municipio(muni_name_d)
        fondos_ue_html = ""
        if fondos_ue_muni:
            total_fue = sum(f["importe_num"] for f in fondos_ue_muni)
            filas_fue = "".join(_render_fila_fondo_ue(f) for f in fondos_ue_muni)
            fondos_ue_html = f"""<div class="fue-card" style="margin-top:14px">
            <div class="section-title" style="color:var(--yellow);margin:0 0 8px">
              🇪🇺 Fondos y proyectos financiados por la UE
              <span class="badge" style="background:rgba(88,166,255,.15);color:var(--yellow);border-color:rgba(88,166,255,.3)">
                {len(fondos_ue_muni)} · {fmt_eur(str(total_fue))}
              </span>
            </div>
            <table>
              <tr>
                <th>Proyecto / Beneficiario</th>
                <th>Importe</th>
                <th>Fuente / Programa</th>
                <th>Fechas</th>
              </tr>
              {filas_fue}
            </table>
          </div>"""

        # Contratos menores de fuentes LOCALES (Girona/RPC, Fuente Álamo, Mula,
        # Molina de Segura...) -- independientes de PLACE/PSCP, ver
        # contratos_menors_locales en _db_init. Colapsable por defecto: son
        # muchos contratos de importe bajo (compras rutinarias), no
        # formalizaciones grandes.
        contratos_menors_html = ""
        menors_muni = _db_contratos_menors_por_municipio(muni_name_d)
        if menors_muni:
            total_cm = sum(r["import_num"] for r in menors_muni)
            total_cm_n = len(menors_muni)
            total_pages_cm = max(1, (total_cm_n + PAGE_SIZE - 1) // PAGE_SIZE)
            # Paginación propia de esta sección (query param 'pag_cm',
            # independiente de la paginación de la tabla principal de
            # contratos) -- necesaria desde que Lorca (10.451 filas en una
            # sola ficha) hizo que renderizar todo de golpe generase una
            # página de ~5 MB. Solo se activan los controles Anterior/
            # Siguiente cuando se está viendo este municipio en detalle
            # (is_paged); en el listado de "todos los municipios" se
            # muestran los primeros PAGE_SIZE con un aviso, igual que ya
            # hace la tabla principal.
            if is_paged:
                start_cm = (page_cm - 1) * PAGE_SIZE
                menors_shown = menors_muni[start_cm:start_cm + PAGE_SIZE]
            else:
                menors_shown = menors_muni[:PAGE_SIZE]
            filas_cm = "".join(_render_fila_contrato_menor(r) for r in menors_shown)

            pag_cm_html = ""
            if total_cm_n > PAGE_SIZE:
                if is_paged:
                    prev_cm = (f'<a href="/?muni={muni_enc}&pag={page}&pag_cm={page_cm-1}{q_prov}" class="pag-btn">← Anterior</a>'
                               if page_cm > 1 else '')
                    next_cm = (f'<a href="/?muni={muni_enc}&pag={page}&pag_cm={page_cm+1}{q_prov}" class="pag-btn">Siguiente →</a>'
                               if page_cm < total_pages_cm else '')
                    pag_cm_html = (f'<div class="pagination">'
                                   f'<span class="pag-info">Página {page_cm} de {total_pages_cm} · {total_cm_n} contratos</span>'
                                   f'<div class="pag-links">{prev_cm}{next_cm}</div>'
                                   f'</div>')
                else:
                    pag_cm_html = (f'<div class="pag-more">Mostrando los primeros {PAGE_SIZE} de {total_cm_n}. '
                                   f'<a href="/?muni={muni_enc}&pag_cm=1{q_prov}">Ver todos →</a></div>')

            abierto = " open" if page_cm > 1 else ""
            contratos_menors_html = f"""<details class="cm-card"{abierto}>
                <summary>
                  📋 Contratos menores (fuentes locales del ayuntamiento)
                  <span class="badge" style="background:rgba(240,136,62,.15);color:var(--accent);border-color:rgba(240,136,62,.3)">
                    {total_cm_n} · {fmt_eur(str(total_cm))}
                  </span>
                </summary>
                <div class="tbl-scroll">
                  <table>
                    <tr>
                      <th>Adjudicatario / Objeto</th>
                      <th>Importe</th>
                      <th>Tipo</th>
                      <th>Fecha</th>
                    </tr>
                    {filas_cm}
                  </table>
                </div>
                {pag_cm_html}
              </details>"""

        cards += f"""<div class="muni-card">
          <div class="muni-header">
            <div>
              <h2>🏛 {esc(muni_name)} {habitantes_html} {cuentas_html} {saldo_html} {deuda_html}</h2>
              {alcalde_concejales_html(muni_name)}
            </div>
            <div style="display:flex;gap:8px;align-items:center;">
              {profile_html}
              <form method="POST" action="/actualizar" style="display:inline">
                <input type="hidden" name="municipio" value="{esc(muni_name)}">
                <input type="hidden" name="provincia" value="{esc(provincia)}">
                <button type="submit" class="btn" style="padding:3px 10px;font-size:11px;background:rgba(88,166,255,.15);color:var(--blue);border:1px solid rgba(88,166,255,.3);">↻ Actualizar</button>
              </form>
              <span class="badge">{d.get('total_contratos', 0)} contratos</span>
            </div>
          </div>
          <div class="source-bar">{esc(fuentes_label)} · {fuentes_str}{age_html}</div>
          {alertas_html}
          <div class="tbl-scroll">
            <table>
              <tr>
                <th>Empresa adjudicataria / Contrato</th>
                <th>Importe</th>
                <th>Directivo / Cargo</th>
                <th>Estado / Fuente</th>
              </tr>
              {filas}
            </table>
            <span class="scroll-hint" aria-hidden="true">sigue <span class="scroll-hint-arrow">›</span></span>
          </div>
          {pag_html}
          {fondos_ue_html}
          {contratos_menors_html}
          {render_comentarios_html("municipio", muni_name, f"/?muni={muni_enc}{q_prov}", titulo=muni_name)}
        </div>"""

    if not cards:
        cards = '<div class="empty">Municipio no encontrado.</div>'

    ejemplo_muni = "Olot, Figueres, Girona, Blanes…" if provincia == "girona" else "Lorca, Murcia, Cartagena, Archena…"
    body = f"""{back_html}
  <div class="search-bar">
    <label>Municipio</label>
    <form method="POST" action="/buscar" style="display:flex;gap:10px;flex:1;flex-wrap:wrap;align-items:center;">
      <input name="municipio" placeholder="Ej: {ejemplo_muni}" required>
      <input type="hidden" name="provincia" value="{esc(provincia)}">
      <button type="submit" class="btn btn-primary">Buscar contratos</button>
    </form>
  </div>
  {stats}
  {cards}"""

    muni_display = datos[0].get("municipio", "") if datos else muni_filter
    label = PROVINCIA_LABEL.get(provincia, PROVINCIA_LABEL["murcia"])
    fuente_desc = "PSCP" if provincia == "girona" else "PLACE"
    titulo = f"Contratos públicos de {muni_display}" if muni_display else "Contratos Públicos"
    descripcion = (f"Contratos públicos adjudicados en {muni_display} ({label}): "
                   f"empresa adjudicataria, importe y directivo/administrador. "
                   f"Datos oficiales {fuente_desc} + Registro Mercantil.") if muni_display else ""
    return _page_shell(titulo, body, description=descripcion, provincia=provincia)


def render_landing_nacional_html(datos):
    """Home agregada: cifras combinadas de todas las provincias cargadas,
    desglose secundario por región, y el top 1 del ranking nacional. Es la
    vista por defecto de '/' (sin ?provincia=); el acceso al listado de
    municipios por región es vía los botones de "Cobertura" y las tarjetas
    de "Cobertura por región" de más abajo (el toggle Murcia/Girona del
    header se quitó por redundante -- ver instrucción del 2026-08-02)."""
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

    # Desglose secundario por región (el "selector" ya no es la puerta de
    # entrada principal, sino estas tarjetas + las pestañas del header).
    region_cards = ""
    for prov, municipios_lista in MUNICIPIOS_POR_PROVINCIA.items():
        datos_prov = [d for d in datos if d.get("provincia", "murcia") == prov]
        # El pseudo-municipio (Región de Murcia / Provincia de Girona) suma
        # en contratos/importe pero no en el "N/total municipios" -- no es
        # uno de los ayuntamientos de esa lista, mostrarlo ahí daría un
        # "43/42 municipios" sin sentido.
        pseudos_prov = {normalizar(p) for p in _pseudos_de_provincia(prov)}
        n_con_datos = sum(1 for d in datos_prov
                           if normalizar(d.get("municipio", "")) not in pseudos_prov)
        c_prov = sum(d.get("total_contratos", 0) for d in datos_prov)
        imp_prov = sum(c.get("importe_num", 0.0) for d in datos_prov for c in d.get("contratos", []))
        label = PROVINCIA_LABEL.get(prov, prov)
        region_cards += f"""<a href="/?provincia={prov}" class="region-card">
          <h3>📍 {esc(label)}</h3>
          <div class="region-stats"><b>{n_con_datos}</b>/{len(municipios_lista)} municipios · <b>{c_prov}</b> contratos</div>
          <div class="region-imp">{fmt_eur(str(imp_prov))}</div>
        </a>"""

    # Botones grandes de Cobertura, justo debajo de la cabecera -- acceso
    # directo y prominente al listado de cada provincia (distinto de las
    # tarjetas "Cobertura por región" de más abajo, que van con el ranking
    # nacional y llevan el naranja de acento habitual).
    cobertura_html = ""
    for prov, municipios_lista in MUNICIPIOS_POR_PROVINCIA.items():
        label = PROVINCIA_LABEL.get(prov, prov)
        cobertura_html += f"""<a href="/?provincia={prov}" class="cobertura-btn">
          <span class="cb-title">📍 {esc(label)}</span>
          <span class="cb-count">{len(municipios_lista)} municipios</span>
        </a>"""

    # Top 1 del ranking nacional (agregando todas las provincias)
    top_n_nac, top_imp_nac = _calcular_rankings(datos)

    def _top1_card(lista, etiqueta, valor_html):
        if not lista:
            return f"""<div class="top1-card">
              <div class="top1-label">{etiqueta}</div>
              <div class="empty" style="padding:14px 0">Aún no hay datos suficientes.</div>
            </div>"""
        g = lista[0]
        if g["directivo"]:
            dir_html = f'{esc(g["directivo"])} — {esc(g["cargo"])}'
        else:
            dir_html = '<span class="noloc-warn">⚠️ No localizado</span>'
        emp_q = quote_plus(g["empresa"])
        return f"""<div class="top1-card">
          <div class="top1-label">{etiqueta}</div>
          <a class="top1-empresa" href="/?q={emp_q}">{esc(g['empresa'])}</a>
          <div class="top1-valor">{valor_html(g)}</div>
          <div class="top1-directivo">{dir_html}</div>
        </div>"""

    top1_html = (
        _top1_card(top_n_nac, "🥇 Más contratos", lambda g: f'{g["n"]} contratos') +
        _top1_card(top_imp_nac, "🥇 Mayor importe", lambda g: fmt_eur(str(g["importe"])))
    )

    # Columna de noticias UE (presupuesto/fondos/subvenciones) -- ver
    # actualizar_noticias_ue(). Solo titular + resumen corto + enlace
    # directo a ec.europa.eu, nunca el texto completo del comunicado.
    noticias_ue = _db_noticias_ue(limit=6)
    if noticias_ue:
        noticias_html = "".join(f"""<div class="noticia-ue-item">
          <a class="nu-titulo" href="{esc(n['url'])}" target="_blank" rel="noopener">{esc(n['titulo'])}</a>
          <div class="nu-resumen">{esc(n['resumen'])}</div>
          <div class="nu-meta"><span>{esc(fmt_fecha_corta(n['fecha_ts']))}</span><span class="nu-fuente">ec.europa.eu ↗</span></div>
        </div>""" for n in noticias_ue)
    else:
        noticias_html = ('<div class="empty" style="padding:20px 8px;font-size:12px">'
                          'Aún no hay noticias cargadas.</div>')

    body = f"""<div class="hero-panel">
    <div class="hero">
      <div class="hero-tagline">{esc(SITE_TAGLINE)}</div>
      <p class="hero-sub">
        Contratos públicos de España cruzados con el Registro Mercantil para saber qué empresa
        — y qué persona — hay detrás de cada adjudicación. Cubrimos actualmente la
        Región de Murcia y la provincia de Girona, con más territorios en camino.
      </p>
    </div>
    <div class="adv-search" id="adv-search">
      <div class="as-tabs">
        <button type="button" class="as-tab" data-tipo="ayuntamiento">Ayuntamiento</button>
        <button type="button" class="as-tab active" data-tipo="empresa">Empresa</button>
        <button type="button" class="as-tab" data-tipo="directivo">Directivo</button>
        <button type="button" class="as-tab" data-tipo="licitacion">Licitación</button>
      </div>
      <div class="as-row">
        <input type="text" id="as-input" placeholder="Nombre de la empresa…" autocomplete="off" autofocus>
        <button type="button" id="as-btn" class="btn btn-primary">Buscar</button>
      </div>
      <div class="gs-hint">Busca en los {total_c} contratos ya cargados de toda España · mínimo 2 caracteres.</div>
      <div id="as-results"></div>
    </div>
    {stats}
  </div>
  <div class="section-title">Cobertura</div>
  <div class="cobertura-grid">{cobertura_html}</div>
  <div class="home-grid">
    <aside class="noticias-ue-panel">
      <div class="nu-panel-title">🇪🇺 Noticias UE · Presupuesto y fondos</div>
      {noticias_html}
      <a class="nu-ver-mas" href="https://ec.europa.eu/commission/presscorner/home/es" target="_blank" rel="noopener">Ver más en la Comisión Europea →</a>
    </aside>
    <div class="home-main-col">
      <div class="section-title" style="margin-top:0">🏆 Liderando ahora mismo · Ranking Nacional</div>
      <div class="top1-grid">{top1_html}</div>
      <div style="margin:-6px 0 24px"><a href="/rankings" class="btn-ver">Ver ranking completo →</a></div>
      <div class="section-title">Cobertura por región</div>
      <div class="region-grid">{region_cards}</div>
    </div>
  </div>
  <script>window.__PROVINCIA__ = "";</script>
  <script>{_ADV_SEARCH_JS}</script>"""

    return _page_shell("Dinero Público | Contratación pública en España", body,
                        description="Consulta los contratos públicos adjudicados en España con los "
                                     "directivos de las empresas adjudicatarias. Cubrimos actualmente "
                                     "la Región de Murcia y la provincia de Girona.",
                        provincia="todas")


def render_landing_html(datos, provincia="murcia"):
    """Página de inicio: no carga ningún municipio, muestra stats globales,
    buscador global y el grid de municipios de la provincia seleccionada."""
    es_girona = provincia == "girona"
    municipios_lista = MUNICIPIOS_POR_PROVINCIA.get(provincia, MUNICIPIOS_MURCIA)
    label = PROVINCIA_LABEL.get(provincia, PROVINCIA_LABEL["murcia"])
    q_prov = "&provincia=girona" if es_girona else ""
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

    def _muni_tile(muni, d):
        """Tile de un municipio o pseudo-municipio (ver MUNICIPIOS_PSEUDO):
        mismas estadísticas de contratos con el mismo estilo de siempre, más
        una línea de fondos UE (amarillo sobre azul) si tiene alguno cruzado
        -- solo se muestra esa línea cuando hay datos, igual que en la ficha
        de detalle (_db_fondos_ue_por_municipio)."""
        n = d.get("total_contratos", 0) if d else 0
        imp = sum(c.get("importe_num", 0.0) for c in d.get("contratos", [])) if d else 0.0
        muni_enc = quote_plus(muni)
        fondos_ue_muni = _db_fondos_ue_por_municipio(muni)
        fue_html = ""
        if fondos_ue_muni:
            total_fue = sum(f["importe_num"] for f in fondos_ue_muni)
            fue_html = (f'<div class="mt-row" style="color:var(--yellow)">'
                        f'<span>🇪🇺 Fondos UE</span><b>{len(fondos_ue_muni)}</b></div>'
                        f'<div class="mt-imp" style="color:var(--yellow)">{fmt_eur(str(total_fue))}</div>')
        return f"""<div class="muni-tile">
          <h3>🏛 {esc(muni)}</h3>
          <div class="mt-row"><span>Contratos</span><b>{n}</b></div>
          <div class="mt-imp">{fmt_eur(str(imp))}</div>
          {fue_html}
          <a class="btn-ver" href="/?muni={muni_enc}{q_prov}">Ver contratos →</a>
        </div>"""

    tiles = ""
    # Pseudo-municipio de la provincia (Región de Murcia / Provincia de
    # Girona) primero, antes del listado alfabético de ayuntamientos: no es
    # un municipio más, así que fijarlo arriba lo hace más fácil de
    # encontrar, aunque el tile en sí es idéntico a los demás (mismas
    # estadísticas, mismo estilo -- ver INFORME_NOCHE.md 2026-07-23).
    for pseudo_nombre in _pseudos_de_provincia(provincia):
        tiles += _muni_tile(pseudo_nombre, por_muni.get(normalizar(pseudo_nombre)))
    for muni in sorted(municipios_lista, key=lambda m: normalizar(m)):
        tiles += _muni_tile(muni, por_muni.get(normalizar(muni)))

    hero_sub = (
        f"Contratos públicos de los {len(municipios_lista)} municipios de la provincia de Girona, "
        f"cruzados con el Registro Mercantil para saber qué empresa — y qué persona — hay detrás "
        f"de cada adjudicación."
        if es_girona else
        f"Contratos públicos de los {len(municipios_lista)} municipios de la Región de Murcia, "
        f"cruzados con el Registro Mercantil para saber qué empresa — y qué persona — hay detrás "
        f"de cada adjudicación."
    )

    body = f"""<div class="hero">
    <div class="hero-tagline">{esc(SITE_TAGLINE)}</div>
    <p class="hero-sub">{esc(hero_sub)}</p>
  </div>
  <div class="adv-search" id="adv-search">
    <div class="as-tabs">
      <button type="button" class="as-tab" data-tipo="ayuntamiento">Ayuntamiento</button>
      <button type="button" class="as-tab active" data-tipo="empresa">Empresa</button>
      <button type="button" class="as-tab" data-tipo="directivo">Directivo</button>
      <button type="button" class="as-tab" data-tipo="licitacion">Licitación</button>
    </div>
    <div class="as-row">
      <input type="text" id="as-input" placeholder="Nombre de la empresa…" autocomplete="off" autofocus>
      <button type="button" id="as-btn" class="btn btn-primary">Buscar</button>
    </div>
    <div class="gs-hint">Busca en los {total_c} contratos ya cargados de {esc(label)} · mínimo 2 caracteres.</div>
    <div id="as-results"></div>
  </div>
  {stats}
  <div class="section-title">Municipios · {esc(label)}</div>
  <div class="muni-grid">{tiles}</div>
  <script>window.__PROVINCIA__ = "{provincia}";</script>
  <script>{_ADV_SEARCH_JS}</script>"""

    return _page_shell(f"Dinero Público | Contratos públicos {label}", body,
                        description=f"Consulta los contratos públicos de los {len(municipios_lista)} "
                                     f"municipios de {label} con los directivos de las empresas "
                                     f"adjudicatarias.",
                        provincia=provincia)


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

    if tipo == "ayuntamiento":
        # Búsqueda de municipio siempre nacional (Murcia + Girona), sin
        # filtrar por la provincia de la página desde la que se lanza --
        # reutiliza el mismo POST /buscar que el buscador clásico de la
        # cabecera (ver formulario municipio/provincia en filaMunicipio()).
        with _datos_lock:
            datos_todas = list(_datos_memoria)
        por_muni = {normalizar(d.get("municipio", "")): d for d in datos_todas}
        resultados = []
        for prov, lista_muni in MUNICIPIOS_POR_PROVINCIA.items():
            nombres = list(_pseudos_de_provincia(prov)) + list(lista_muni)
            for muni in nombres:
                if q_norm not in normalizar(muni):
                    continue
                d = por_muni.get(normalizar(muni))
                cached = d is not None
                total_imp = sum(c.get("importe_num", 0.0) for c in d.get("contratos", [])) if cached else 0.0
                resultados.append({
                    "municipio": muni,
                    "provincia": prov,
                    "provincia_label": PROVINCIA_LABEL.get(prov, prov),
                    "cached": cached,
                    "total_contratos": d.get("total_contratos", 0) if cached else 0,
                    "total_importe": fmt_eur(str(total_imp)) if cached else "",
                })
        resultados.sort(key=lambda r: (not r["cached"], normalizar(r["municipio"])))
        return {"tipo": "ayuntamiento", "query": q, "resultados": resultados[:60]}

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


def render_busqueda_global_html(datos, q, provincia="murcia"):
    """Resultados de la búsqueda global por empresa, directivo o municipio."""
    label = PROVINCIA_LABEL.get(provincia, PROVINCIA_LABEL["murcia"])
    q_norm = normalizar(q)
    resultados = []
    for d in datos:
        muni = d.get("municipio", "")
        prov_d = d.get("provincia", "murcia")
        for c in d.get("contratos", []):
            if (q_norm in normalizar(c.get("empresa", ""))
                    or q_norm in normalizar(c.get("directivo", ""))
                    or q_norm in normalizar(muni)):
                resultados.append((muni, prov_d, c))

    if resultados:
        filas = "".join(_render_fila_contrato(c, municipio_label=m, municipio=m, provincia=p)
                         for m, p, c in resultados[:300])
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

    q_prov = "&provincia=girona" if provincia == "girona" else ""
    comentarios_html = (render_comentarios_html("busqueda", q, f"/?q={quote_plus(q)}{q_prov}", titulo=q)
                         if resultados else "")

    body = f"""<span class="back-link"><a href="/{'?provincia=girona' if provincia == 'girona' else ''}">← Volver al inicio</a></span>
  <div class="global-search">
    <form method="GET" action="/" class="gs-row">
      <input name="q" value="{esc(q)}" placeholder="Buscar por empresa, directivo o municipio…" autofocus>
      <input type="hidden" name="provincia" value="{esc(provincia)}">
      <button type="submit" class="btn btn-primary">Buscar</button>
    </form>
    <div class="gs-hint">{len(resultados)} resultado{'s' if len(resultados) != 1 else ''} para "{esc(q)}"</div>
  </div>
  <div class="muni-card">{tabla}</div>
  {comentarios_html}"""

    return _page_shell(f'Búsqueda: {q}', body,
                        description=f'Resultados de "{q}" en contratos públicos de {label}.',
                        provincia=provincia)


def render_quienes_somos_html():
    body = """<div class="static-page">
  <h1>Transparencia al servicio de la ciudadanía</h1>

  <p>Dinero Público nació con un objetivo claro: hacer accesible a cualquier ciudadano
  la información sobre cómo se gasta el dinero público. Actualmente cubrimos la
  Región de Murcia y la provincia de Girona, con expansión progresiva a toda
  España.</p>

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
    <li>PSCP (Generalitat de Catalunya) — contratos públicos de Girona</li>
    <li>BORM (Boletín Oficial Región de Murcia) — publicaciones oficiales</li>
    <li>Registro Mercantil — directivos y administradores</li>
    <li>einforma.com, axesor.es, infocif.es — datos empresariales públicos</li>
    <li>(próximamente) EU Funding &amp; Tenders / CORDIS — subvenciones y fondos europeos</li>
  </ul>

  <h2>Contacto</h2>
  <a class="contact-btn" href="mailto:contacto@dinero-publico.com">✉ contacto@dinero-publico.com</a>
</div>"""
    return _page_shell("Quiénes Somos", body,
                        description="Quiénes somos y por qué existe Dinero Público: transparencia sobre "
                                     "la contratación pública en la Región de Murcia y la provincia de "
                                     "Girona.")


def render_aviso_legal_html():
    body = f"""<div class="static-page">
  <h1>Aviso Legal y Privacidad</h1>

  <h2>Titular</h2>
  <p>César Castro Banegas.</p>

  <h2>Dominio</h2>
  <p>{esc(SITE_URL)}</p>

  <h2>Actividad</h2>
  <p>Plataforma de transparencia y datos públicos sobre contratación del sector
  público en España. Cubre actualmente la Región de Murcia y la provincia de
  Girona, con expansión progresiva a todo el territorio nacional.</p>

  <h2>Propiedad intelectual</h2>
  <p>El código fuente de esta plataforma está registrado como obra en Safe
  Creative con todos los derechos reservados, número de registro
  <a href="https://www.safecreative.org/work/2607236515551" target="_blank"
  rel="noopener">2607236515551</a> (23 de julio de 2026).</p>

  <h2>Origen de los datos</h2>
  <p>Los datos de contratos mostrados provienen de fuentes oficiales públicas: la
  Plataforma de Contratación del Sector Público (PLACE) del Ministerio de
  Hacienda, el Boletín Oficial de la Región de Murcia (BORM) y la Plataforma de
  Serveis de Contractació Pública de Catalunya (PSCP). Se irán incorporando otras
  plataformas de contratación pública autonómicas y estatales a medida que se
  amplíe la cobertura territorial.</p>
  <p>Los nombres de directivos y administradores provienen de registros públicos
  (Registro Mercantil y fuentes empresariales públicas equivalentes).</p>
  <p>Próximamente se incorporarán también datos de subvenciones y fondos
  europeos.</p>

  <h2>Base legal para el tratamiento de datos</h2>
  <p>El tratamiento de los nombres de personas físicas que aparecen como
  administradores o apoderados de empresas adjudicatarias se ampara en el interés
  público de la información y en que proceden de fuentes accesibles al público
  (art. 9.2.e del Reglamento General de Protección de Datos y Ley Orgánica 3/2018,
  de Protección de Datos Personales y garantía de los derechos digitales — LOPDGDD).</p>

  <h2>Ejercicio de derechos RGPD</h2>
  <p>Para ejercer tus derechos de acceso, rectificación, supresión, oposición o
  limitación del tratamiento, escribe a
  <a href="mailto:contacto@dinero-publico.com">contacto@dinero-publico.com</a>.</p>

  <h2>Cookies y publicidad</h2>
  <p>Este sitio no utiliza cookies de seguimiento ni publicidad personalizada.</p>

  <h2>Contacto</h2>
  <a class="contact-btn" href="mailto:contacto@dinero-publico.com">✉ contacto@dinero-publico.com</a>
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
        # Cualquier ?provincia= que no sea una provincia real (ausente,
        # vacio, "todas" o un valor invalido) se trata como "sin filtro":
        # esa es la nueva home nacional agregada, por defecto. Solo
        # provincia=murcia|girona explicito activa el filtro clasico de la
        # Fase 4 (bookmarks/enlaces existentes siguen funcionando igual).
        provincia_qs_raw = qs.get("provincia", [""])[0]
        provincia_filtro = _provincia_o_todas(provincia_qs_raw)
        muni_filter = qs.get("muni", [""])[0].strip()
        q = qs.get("q", [""])[0].strip()

        if muni_filter:
            provincia = provincia_filtro
            if provincia == "todas":
                # averiguar a que provincia pertenece el municipio para que
                # /?muni=Olot funcione sin necesidad de &provincia=girona
                with _datos_lock:
                    match = next((d for d in _datos_memoria
                                  if normalizar(d.get("municipio", "")) == normalizar(muni_filter)), None)
                provincia = match.get("provincia", "murcia") if match else "murcia"
            with _datos_lock:
                datos_snap = [d for d in _datos_memoria if d.get("provincia", "murcia") == provincia]
            try:
                page = max(1, int(qs.get("pag", ["1"])[0]))
            except ValueError:
                page = 1
            try:
                page_cm = max(1, int(qs.get("pag_cm", ["1"])[0]))
            except ValueError:
                page_cm = 1
            return _resp(render_html(datos_snap, muni_filter=muni_filter, page=page, page_cm=page_cm, provincia=provincia), gzip_ok=gzip_ok)

        if q:
            with _datos_lock:
                if provincia_filtro == "todas":
                    datos_snap = list(_datos_memoria)
                else:
                    datos_snap = [d for d in _datos_memoria if d.get("provincia", "murcia") == provincia_filtro]
            return _resp(render_busqueda_global_html(datos_snap, q, provincia=provincia_filtro), gzip_ok=gzip_ok)

        if provincia_filtro == "todas":
            with _datos_lock:
                datos_todas = list(_datos_memoria)
            return _resp(render_landing_nacional_html(datos_todas), gzip_ok=gzip_ok)

        with _datos_lock:
            datos_snap = [d for d in _datos_memoria if d.get("provincia", "murcia") == provincia_filtro]
        return _resp(render_landing_html(datos_snap, provincia=provincia_filtro), gzip_ok=gzip_ok)

    if path == "/rankings":
        provincia_prov = _provincia_valida(qs.get("provincia", ["murcia"])[0])
        with _datos_lock:
            datos_nacional = list(_datos_memoria)
            datos_provincia = [d for d in datos_nacional if d.get("provincia", "murcia") == provincia_prov]
        return _resp(render_rankings_html(datos_nacional, datos_provincia, provincia_prov), gzip_ok=gzip_ok)

    if path == "/fondos-ue":
        provincia_qs = qs.get("provincia", ["todas"])[0]
        provincia_fue = provincia_qs if provincia_qs in MUNICIPIOS_POR_PROVINCIA else "todas"
        fondos = _db_fondos_ue(provincia_fue if provincia_fue != "todas" else None)
        return _resp(render_fondos_ue_html(fondos, provincia_fue), gzip_ok=gzip_ok)

    if path == "/quienes-somos":
        return _resp(render_quienes_somos_html(), gzip_ok=gzip_ok)

    if path == "/aviso-legal":
        return _resp(render_aviso_legal_html(), gzip_ok=gzip_ok)

    if path == "/robots.txt":
        body = f"User-agent: *\nAllow: /\n\nSitemap: {SITE_URL}/sitemap.xml\n"
        return _resp(body, content_type="text/plain; charset=utf-8", gzip_ok=gzip_ok)

    if path == "/sitemap.xml":
        with _datos_lock:
            entradas = [(d.get("municipio", ""), d.get("provincia", "murcia")) for d in _datos_memoria]
        urls = [f"  <url><loc>{esc(SITE_URL)}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>",
                f"  <url><loc>{esc(SITE_URL)}/?provincia=girona</loc><changefreq>daily</changefreq></url>",
                f"  <url><loc>{esc(SITE_URL)}/rankings</loc><changefreq>daily</changefreq></url>",
                f"  <url><loc>{esc(SITE_URL)}/rankings?provincia=girona</loc><changefreq>daily</changefreq></url>",
                f"  <url><loc>{esc(SITE_URL)}/fondos-ue</loc><changefreq>weekly</changefreq></url>",
                f"  <url><loc>{esc(SITE_URL)}/quienes-somos</loc><changefreq>monthly</changefreq></url>",
                f"  <url><loc>{esc(SITE_URL)}/aviso-legal</loc><changefreq>monthly</changefreq></url>"]
        for m, prov in entradas:
            sufijo = "&provincia=girona" if prov == "girona" else ""
            urls.append(f"  <url><loc>{esc(SITE_URL)}/?muni={quote_plus(m)}{sufijo}</loc><changefreq>daily</changefreq></url>")
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

    if path in ("/static/icon-192.png", "/static/icon-512.png", "/static/apple-touch-icon.png"):
        # Iconos PWA -- ficheros PNG reales en backend/static/ (generados una
        # sola vez recortando LOGO_SVG a la zona del icono, ver informe de
        # viabilidad 2026-08-05), no contenido generado en caliente como el
        # resto del sitio. Se sirven desde BASE_DIR (código desplegado), no
        # desde DATA_DIR (disco persistente de datos), porque son un asset
        # del código, no un dato que cambie.
        icon_path = os.path.join(BASE_DIR, path.lstrip("/"))
        try:
            with open(icon_path, "rb") as f:
                data = f.read()
        except OSError:
            return 404, {"Content-Length": "0"}, b""
        return _resp(
            data, content_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"}, gzip_ok=False,
        )

    if path == "/manifest.json":
        return _resp(
            json.dumps(PWA_MANIFEST, ensure_ascii=False),
            content_type="application/manifest+json; charset=utf-8",
            headers={"Cache-Control": "public, max-age=86400"}, gzip_ok=gzip_ok,
        )

    if path == "/sw.js":
        # Sin caché -- si no, un navegador podría tardar en enterarse de que
        # hay una versión nueva del propio service worker (ver CACHE_NAME).
        return _resp(
            _PWA_SW_JS, content_type="application/javascript; charset=utf-8",
            headers={"Cache-Control": "no-cache"}, gzip_ok=gzip_ok,
        )

    if path == "/admin/cache-db":
        # Sirve el SQLite en bruto para que el cron de GitHub Actions haga una
        # copia versionada (Git LFS) tras un refresco completo con éxito. Mismo
        # patrón de protección que /actualizar-todos: ADMIN_TOKEN obligatorio
        # (403 si falta o no coincide). El fichero se sirve desde un snapshot
        # consistente (sqlite3.backup bajo _db_lock), NUNCA leyendo cache.db
        # directamente del disco, para no entregar un fichero a medio escribir
        # con WAL activo. Ver INFORME_NOCHE.md 2026-07-25.
        admin_token = os.environ.get("ADMIN_TOKEN", "")
        if not admin_token or qs.get("token", [""])[0] != admin_token:
            return _error_resp("No autorizado.", 403)
        tmp_path = os.path.join(DATA_DIR, f".cache_db_export_{uuid.uuid4().hex}.tmp")
        try:
            with _db_lock:
                dst = sqlite3.connect(tmp_path)
                try:
                    _db.backup(dst)
                finally:
                    dst.close()
            with open(tmp_path, "rb") as f:
                data = f.read()
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return _resp(
            data, content_type="application/octet-stream",
            headers={"Content-Disposition": 'attachment; filename="cache.db"'},
            gzip_ok=False,
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
        provincia_param = qs.get("provincia", [""])[0]
        with _datos_lock:
            if provincia_param in MUNICIPIOS_POR_PROVINCIA:
                datos_snap = [d for d in _datos_memoria if d.get("provincia", "murcia") == provincia_param]
            else:
                datos_snap = list(_datos_memoria)   # "" o "todas" -> sin filtro, busca en toda España
        resultado = api_buscar(tipo, q, datos_snap)
        return _resp(json.dumps(resultado, ensure_ascii=False),
                     content_type="application/json; charset=utf-8", gzip_ok=gzip_ok)

    return 404, {"Content-Length": "0"}, b""


def _route_post(path, params):
    try:
        if path == "/buscar":
            municipio = params.get("municipio", [""])[0].strip()
            force     = params.get("force", [""])[0] == "1"
            provincia = _provincia_valida(params.get("provincia", ["murcia"])[0])
            mun_ok = municipio_valido_provincia(municipio, provincia)
            if not mun_ok:
                label = PROVINCIA_LABEL.get(provincia, PROVINCIA_LABEL["murcia"])
                return _error_resp(f"Municipio no válido o no pertenece a {label}.", 400)
            redirect_url = f"/?muni={quote_plus(mun_ok)}" + ("&provincia=girona" if provincia == "girona" else "")
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
                    return _redirect_resp(redirect_url)
            else:
                _cache_invalidate(mun_ok)
            job_id = str(uuid.uuid4())
            with _jobs_lock:
                _jobs[job_id] = {"status": "running", "log": [], "error": None}
            threading.Thread(target=_job_run, args=(job_id, mun_ok, provincia), daemon=True).start()
            return _resp(spinner_page(job_id, mun_ok, provincia=provincia))

        if path == "/comentario":
            # Formulario "Deja tu comentario" (ficha de municipio o de
            # empresa) -- sin gestión activa ni email, se guarda y se
            # muestra público de inmediato (ver render_comentarios_html,
            # decisión de César 2026-08-05).
            tipo = params.get("tipo", [""])[0]
            clave_raw = params.get("clave", [""])[0].strip()[:200]
            nombre = params.get("nombre", [""])[0].strip()[:60]
            texto = params.get("texto", [""])[0].strip()[:1000]
            redirect_url = params.get("redirect", [""])[0]
            if not redirect_url.startswith("/"):
                redirect_url = "/"
            if tipo in ("municipio", "busqueda") and clave_raw and texto:
                _db_comentarios_insertar(tipo, clave_raw, texto, nombre)
            return _redirect_resp(redirect_url + "#comentarios" if "#" not in redirect_url else redirect_url)

        if path == "/vaciar":
            # Borra contratos ya scrapeados/enriquecidos. Ya no hay botón en la
            # interfaz que apunte aquí, pero el endpoint sigue existiendo y el
            # código es público — se exige ADMIN_TOKEN para evitar que cualquiera
            # lo dispare directamente contra el sitio en producción. Con
            # provincia=girona|murcia borra solo esa provincia; sin el parámetro,
            # borra todo (comportamiento de siempre).
            admin_token = os.environ.get("ADMIN_TOKEN", "")
            if not admin_token or params.get("token", [""])[0] != admin_token:
                return _error_resp("No autorizado.", 403)
            provincia_param = params.get("provincia", [""])[0]
            provincia_filtro = provincia_param if provincia_param in MUNICIPIOS_POR_PROVINCIA else None
            with _datos_lock:
                if provincia_filtro:
                    _datos_memoria[:] = [d for d in _datos_memoria if d.get("provincia", "murcia") != provincia_filtro]
                else:
                    _datos_memoria.clear()
                _db_clear_municipios(provincia=provincia_filtro)
            with _cache_lock:
                _result_cache.clear()
            return _redirect_resp("/")

        if path == "/actualizar":
            municipio = params.get("municipio", [""])[0].strip()
            provincia = _provincia_valida(params.get("provincia", ["murcia"])[0])
            mun_ok = municipio_valido_provincia(municipio, provincia)
            if not mun_ok:
                return _redirect_resp("/" + ("?provincia=girona" if provincia == "girona" else ""))
            _cache_invalidate(mun_ok)
            job_id = str(uuid.uuid4())
            with _jobs_lock:
                _jobs[job_id] = {"status": "running", "log": [], "error": None}
            threading.Thread(target=_job_run, args=(job_id, mun_ok, provincia), daemon=True).start()
            return _resp(spinner_page(job_id, mun_ok, provincia=provincia))

        if path == "/actualizar-todos":
            # Refresca todos los municipios de la provincia dada, uno a uno
            # -- o de TODAS (Murcia y Girona, secuencial) si provincia=todas.
            # Pensado para un disparador externo (GitHub Actions programado,
            # que pasa provincia=todas para cubrir ambas fuentes en un solo
            # disparo diario), no para la interfaz — de ahí el ADMIN_TOKEN
            # (mismo patrón que /vaciar). Sin el parámetro, sigue asumiendo
            # "murcia" por compatibilidad con disparos antiguos.
            admin_token = os.environ.get("ADMIN_TOKEN", "")
            if not admin_token or params.get("token", [""])[0] != admin_token:
                return _error_resp("No autorizado.", 403)
            provincia_raw = params.get("provincia", ["murcia"])[0]
            provincia = provincia_raw if provincia_raw in ("todas", *MUNICIPIOS_POR_PROVINCIA) else "murcia"
            job_id = str(uuid.uuid4())
            threading.Thread(target=_actualizar_todos_bg, args=(job_id, provincia), daemon=True).start()
            total_municipios = (sum(len(v) for v in MUNICIPIOS_POR_PROVINCIA.values()) if provincia == "todas"
                                 else len(MUNICIPIOS_POR_PROVINCIA.get(provincia, MUNICIPIOS_MURCIA)))
            body = json.dumps({"status": "started", "job_id": job_id, "provincia": provincia,
                                "total_municipios": total_municipios})
            return _resp(body, content_type="application/json; charset=utf-8")

        if path == "/actualizar-fondos-ue":
            # Refresca la tabla fondos_ue (CORDIS + Cohesion Data). Mismo
            # patrón de disparo externo + ADMIN_TOKEN que /actualizar-todos;
            # el cron diario llama a los dos endpoints uno detrás de otro.
            admin_token = os.environ.get("ADMIN_TOKEN", "")
            if not admin_token or params.get("token", [""])[0] != admin_token:
                return _error_resp("No autorizado.", 403)
            job_id = str(uuid.uuid4())
            threading.Thread(target=_actualizar_fondos_ue_bg, args=(job_id,), daemon=True).start()
            body = json.dumps({"status": "started", "job_id": job_id})
            return _resp(body, content_type="application/json; charset=utf-8")

        if path == "/actualizar-noticias-ue":
            # Refresca la tabla noticias_ue (RSS Press Corner de la Comisión
            # Europea). Mismo patrón de disparo externo + ADMIN_TOKEN que
            # /actualizar-fondos-ue; el cron diario lo llama justo después.
            admin_token = os.environ.get("ADMIN_TOKEN", "")
            if not admin_token or params.get("token", [""])[0] != admin_token:
                return _error_resp("No autorizado.", 403)
            job_id = str(uuid.uuid4())
            threading.Thread(target=_actualizar_noticias_ue_bg, args=(job_id,), daemon=True).start()
            body = json.dumps({"status": "started", "job_id": job_id})
            return _resp(body, content_type="application/json; charset=utf-8")

        if path == "/actualizar-contratos-menors-girona":
            # Refresca contratos_menors_girona (Registre Públic de Contractes,
            # dataset hb6v-jcbf). Mismo patrón de disparo externo + ADMIN_TOKEN
            # que /actualizar-fondos-ue; el cron diario lo llama al final,
            # igual que noticias UE.
            admin_token = os.environ.get("ADMIN_TOKEN", "")
            if not admin_token or params.get("token", [""])[0] != admin_token:
                return _error_resp("No autorizado.", 403)
            job_id = str(uuid.uuid4())
            threading.Thread(target=_actualizar_contratos_menors_girona_bg, args=(job_id,), daemon=True).start()
            body = json.dumps({"status": "started", "job_id": job_id})
            return _resp(body, content_type="application/json; charset=utf-8")

        if path == "/actualizar-contratos-menores-fuentealamo":
            # Refresca contratos_menors_locales (filas de Fuente Álamo de
            # Murcia, portal propio vía CSV -- ver buscar_en_fuentealamo_menores).
            # Mismo patrón de disparo externo + ADMIN_TOKEN que las demás
            # fuentes de contratos menores; el cron diario lo llama al final.
            admin_token = os.environ.get("ADMIN_TOKEN", "")
            if not admin_token or params.get("token", [""])[0] != admin_token:
                return _error_resp("No autorizado.", 403)
            job_id = str(uuid.uuid4())
            threading.Thread(target=_actualizar_contratos_menores_fuentealamo_bg, args=(job_id,), daemon=True).start()
            body = json.dumps({"status": "started", "job_id": job_id})
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
