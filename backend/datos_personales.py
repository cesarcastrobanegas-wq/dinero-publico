# encoding: utf-8
"""Ficheros de datos con NOMBRES DE PERSONAS FÍSICAS: primero del disco persistente, si no, del repositorio.

FASE 1 (18-11-2026, informe «INFORME datos personales en GitHub (18-11).md»). El repositorio es público y estos
ficheros llevan nombres de alcaldes y concejales y de autónomos adjudicatarios (con su NIF enmascarado). El plan es que
vivan solo en el disco de Render, como administradores_borme.json. En esta fase:
  - la web busca cada fichero primero en DATA_DIR/datos_personales/<ruta> y, si no está, en backend/<ruta> como hasta
    ahora (nada cambia mientras no se suba nada);
  - POST /admin/datos-personales?fichero=<ruta> (cabecera X-Admin-Token) valida el fichero y lo guarda en el disco;
  - no se quita nada del repositorio ni se tocan los flujos.
Lo subido se usa desde el SIGUIENTE ARRANQUE: las rutas se eligen al importar la web (casi todos se cargan en la base
al arrancar). Subir exactamente los mismos bytes que hay en el repositorio no cambia nada en la web: las cargas que
llevan huella (backfills, correcciones, feed de PLACE) ven la misma huella y no repiten trabajo.

Este módulo no imprime ni devuelve nombres: solo recuentos.
"""
import gzip
import hashlib
import json
import os
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", BASE_DIR)
DIR_DISCO = os.path.join(DATA_DIR, "datos_personales")
TAMANO_MAXIMO = 60 * 1024 * 1024          # el mayor hoy (Euskadi) son 10,4 MB en gzip; alcaldes, 9 MB sin comprimir

# Ciudades con fichero propio de contratos menores (los de la tabla del informe; Almería, Burgos, Cádiz, Getafe,
# Santa Cruz y Valladolid van también: son la misma familia y pueden traer autónomos en una descarga nueva).
_CIUDADES_MENORES = (
    "alcala_henares", "alicante", "almeria", "arona", "burgos", "cadiz", "ciudad_real", "euskadi", "fuenlabrada",
    "getafe", "gijon", "la_laguna", "laspalmasgc", "leganes", "madrid_capital", "malaga", "mostoles",
    "murcia_manual", "palma", "salamanca", "santa_cruz", "sevilla", "toledo", "torrejon", "torrent",
    "valencia_capital", "valladolid", "zaragoza")

# ruta relativa (exacta o por patrón) -> tipo de validación
_EXACTOS = {
    "alcaldes_concejales.json": "alcaldes",
    "sueldos_concejales.json": "sueldos",
    "correcciones_formales_5anios.json.gz": "correcciones",
    "facturas_trimestrales_navarra.json.gz": "facturas_navarra",
    "backfill_galicia_place.json.gz": "backfill_municipios",
    "backfill_ajuntament_place.json.gz": "backfill_municipios",
    "backfill_nombres_place.json.gz": "backfill_municipios",
}
_EXACTOS.update({f"contratos_menores_{c}.json.gz": "menores" for c in _CIUDADES_MENORES})
_PATRONES = (
    (re.compile(r"^contratos_menores_place_\d{4}-\d{2}\.json\.gz$"), "menores"),
    (re.compile(r"^backfill_formales_place_prov/[a-z_]+(__[a-z0-9_]+)?\.json\.gz$"), "backfill_provincia"),
)


def tipo_de(rel):
    """Tipo de validación de una ruta relativa permitida, o None si no es uno de estos ficheros."""
    rel = (rel or "").replace("\\", "/")
    if rel in _EXACTOS:
        return _EXACTOS[rel]
    for patron, tipo in _PATRONES:
        if patron.match(rel):
            return tipo
    return None


def ruta(rel):
    """Dónde leer `rel` (p. ej. "alcaldes_concejales.json"): el disco si está ahí, si no, backend/."""
    disco = os.path.join(DIR_DISCO, *rel.split("/"))
    return disco if os.path.isfile(disco) else os.path.join(BASE_DIR, *rel.split("/"))


def rutas_patron(carpeta, prefijo, sufijo):
    """Ficheros de `carpeta` ("" = backend/) cuyo nombre empieza por `prefijo` y acaba en `sufijo`, juntando disco y
    repositorio (si está en los dos, gana el disco). Ordenados por NOMBRE de fichero, no por ruta completa: así la
    huella del feed de PLACE (sha256 de los ficheros en orden) no cambia porque unos vengan del disco y otros no."""
    vistos = {}
    for base in (os.path.join(BASE_DIR, carpeta) if carpeta else BASE_DIR,
                 os.path.join(DIR_DISCO, carpeta) if carpeta else DIR_DISCO):
        try:
            nombres = os.listdir(base)
        except OSError:
            continue
        for n in nombres:
            if n.startswith(prefijo) and n.endswith(sufijo) and os.path.isfile(os.path.join(base, n)):
                vistos[n] = os.path.join(base, n)          # el disco va segundo: sobrescribe
    return [vistos[n] for n in sorted(vistos)]


def _json_de(crudo, rel):
    """Bytes recibidos -> (objeto JSON, bytes a guardar). Un .json.gz se guarda en gzip y un .json sin comprimir: si
    llega ya en esa forma se guarda TAL CUAL (mismos bytes = misma huella en las cargas que la usan)."""
    es_gzip = crudo[:2] == b"\x1f\x8b"
    plano = gzip.decompress(crudo) if es_gzip else crudo
    datos = json.loads(plano.decode("utf-8"))
    if rel.endswith(".gz"):
        guardar = crudo if es_gzip else gzip.compress(plano, 6)
    else:
        guardar = plano
    return datos, guardar


def _contar(tipo, d):
    """Valida la forma del fichero y devuelve cuántos registros trae. ValueError si no es válido."""
    if not isinstance(d, dict):
        raise ValueError("no es un objeto JSON")
    if tipo == "menores":
        regs = d.get("registros")
        if not isinstance(regs, list) or not regs:
            raise ValueError("falta 'registros' o está vacío")
        for r in regs[:50]:
            if not isinstance(r, dict) or not all(k in r for k in ("id", "municipio", "adjudicatari", "import_num")):
                raise ValueError("registros sin id/municipio/adjudicatari/import_num")
        return len(regs)
    if tipo == "alcaldes":
        m = d.get("municipios")
        if not isinstance(m, dict) or len(m) < 1000:
            raise ValueError("falta 'municipios' o trae menos de 1.000")
        for v in list(m.values())[:50]:
            if not isinstance(v, dict) or "municipio" not in v or "concejales" not in v:
                raise ValueError("municipios sin municipio/concejales")
        return len(m)
    if tipo == "sueldos":
        regs = d.get("registros")
        if not isinstance(regs, list) or not regs:
            raise ValueError("falta 'registros' o está vacío")
        for r in regs[:50]:
            if not isinstance(r, dict) or not all(k in r for k in ("municipio", "nombre", "cargo", "importe")):
                raise ValueError("registros sin municipio/nombre/cargo/importe")
        return len(regs)
    if tipo == "correcciones":
        c = d.get("correcciones")
        if not isinstance(c, dict) or not c:
            raise ValueError("falta 'correcciones' o está vacío")
        return len(c)
    if tipo == "facturas_navarra":
        m = d.get("municipios")
        if not isinstance(m, dict) or not m or not all(isinstance(v, dict) and "facturas" in v for v in m.values()):
            raise ValueError("falta 'municipios' con 'facturas'")
        return sum(len(v.get("facturas") or []) for v in m.values())
    if tipo == "backfill_municipios":
        m = d.get("municipios")
        if not isinstance(m, dict) or not m or not all(isinstance(v, dict) and isinstance(v.get("contratos"), list)
                                                       for v in m.values()):
            raise ValueError("falta 'municipios' con 'contratos'")
        return sum(len(v["contratos"]) for v in m.values())
    if tipo == "backfill_provincia":
        m = d.get("municipios")
        if not isinstance(m, dict) or not m or not all(isinstance(v, list) for v in m.values()):
            raise ValueError("falta 'municipios' con listas de contratos")
        return sum(len(v) for v in m.values())
    raise ValueError(f"tipo desconocido {tipo}")


def registros_de_fichero(ruta_fichero, rel):
    """Cuántos registros tiene un fichero ya guardado (para comparar con lo que llega); 0 si no se puede leer."""
    try:
        with open(ruta_fichero, "rb") as f:
            datos, _ = _json_de(f.read(), rel)
        return _contar(tipo_de(rel), datos)
    except (OSError, ValueError):
        return 0


def preparar(rel, crudo):
    """Valida lo recibido para `rel`. Devuelve (bytes a guardar, registros, sha256). ValueError si no vale."""
    tipo = tipo_de(rel)
    if not tipo:
        raise ValueError("fichero no permitido")
    if not crudo:
        raise ValueError("cuerpo vacío")
    try:
        datos, guardar = _json_de(crudo, rel)
    except (OSError, EOFError, ValueError, UnicodeDecodeError) as e:
        raise ValueError(f"no es JSON válido ({type(e).__name__})") from None
    n = _contar(tipo, datos)
    return guardar, n, hashlib.sha256(guardar).hexdigest()


def guardar(rel, contenido):
    """Escritura atómica en DATA_DIR/datos_personales/<rel>. El fichero anterior del disco, si lo había, queda como
    <rel>.anterior (una sola copia). Devuelve la ruta final."""
    destino = os.path.join(DIR_DISCO, *rel.split("/"))
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    tmp = destino + ".nuevo"
    with open(tmp, "wb") as f:
        f.write(contenido)
        f.flush()
        os.fsync(f.fileno())
    if os.path.isfile(destino):
        os.replace(destino, destino + ".anterior")
    os.replace(tmp, destino)
    return destino


def estado():
    """Para GET /admin/datos-personales: de cada fichero permitido que exista, de dónde se lee y su sha256 corto.
    Sin nombres."""
    rels = set(_EXACTOS)
    for base, carpeta in ((BASE_DIR, ""), (DIR_DISCO, ""), (os.path.join(BASE_DIR, "backfill_formales_place_prov"),
                                                            "backfill_formales_place_prov/"),
                          (os.path.join(DIR_DISCO, "backfill_formales_place_prov"), "backfill_formales_place_prov/")):
        try:
            rels |= {carpeta + n for n in os.listdir(base) if tipo_de(carpeta + n)}
        except OSError:
            pass
    out = []
    for rel in sorted(rels):
        r = ruta(rel)
        if not os.path.isfile(r):
            continue
        with open(r, "rb") as f:
            h = hashlib.sha256(f.read()).hexdigest()
        out.append({"fichero": rel, "origen": "disco" if r.startswith(DIR_DISCO + os.sep) else "repositorio",
                    "bytes": os.path.getsize(r), "sha256": h[:16]})
    return out
