"""Sistema de Transparencia Financiera de la Comisión Europea (FTS), beneficiarios de España (2026-10-18, encargo de
César; para después del viernes 23-10: de momento solo se genera y se prueba en local, la web no lo lee todavía).

El FTS publica cada año los compromisos que la Comisión gestiona directamente (Erasmus+ centralizado, LIFE, Mecanismo
Conectar Europa, Europa Creativa, CERV, Europa Digital, EU4Health, Fondo de Defensa, agencias y empresas comunes…). No
cubre la gestión compartida (FEDER, FSE+, PAC…), que ya entra por Cohesion Data y Kohesio.

Fuente: un CSV por ejercicio, https://ec.europa.eu/budget/financial-transparency-system/download/AAAA_FTS_dataset_en.csv
(comas, importes con coma de millares; 2014-2024 en UTF-8 con BOM y 2025 en Windows-1252: se detecta sola). Se baja a disco con flujo (sin cargarlo en memoria), se lee fila
a fila y solo se guardan las de "Beneficiary country" = Spain. Ver "INFORME viabilidad fondos europeos 2" §1.

Qué se descarta por defecto (configurable):
  - Horizon Europe y Horizon 2020 (--incluir-horizon para meterlos): la web ya tiene Horizon Europe por CORDIS, y las
    filas del FTS de ese programa coinciden en un 98 % con proyectos de CORDIS. Horizon 2020 no está en la web hoy (el
    CORDIS que se carga es solo Horizon Europe), pero se excluye igual para que, si se añade el CORDIS de H2020, no salga
    dos veces; si César prefiere tenerlo ya desde el FTS, basta --incluir-horizon (o cargar el CORDIS de H2020).
  - Con --cordis-zip RUTA (el ZIP de CORDIS que usa fondos_ue_espana.py) se quitan además las filas de otros programas
    (sobre todo empresas comunes, "DA/JU") cuyo Project ID ya está en CORDIS.
  - El Mecanismo de Recuperación (MRR) pagado al "Reino de España" (--incluir-mrr para meterlo): es una transferencia
    al Estado de decenas de miles de millones que inflaría todo; el MRR por perceptor ya tiene su bloque (mrr100).

Personas físicas (MISMA regla que Kohesio, fondos_ue_espana.es_entidad): el nombre solo se publica si es claramente una
entidad (forma jurídica o tipo de organismo en el nombre); lo dudoso se trata como persona física. Además, si el FTS
marca la fila como persona física ("NATURAL PERSON" o tipo "Private Persons") o el NIF tiene forma de DNI/NIE, va sin
nombre, sin NIF, sin municipio y sin asunto. El NIF/IVA solo se guarda si es de persona jurídica (letra + 7 cifras +
control); nunca un DNI/NIE. Las filas sin nombre tampoco llevan municipio (solo provincia o comunidad).

Ámbito, como en Kohesio/CORDIS: provincia por el código postal (si cuadra con la comunidad NUTS2 que trae la fila); si
no, la comunidad (las uniprovinciales cuentan como provincia); si no, estatal.

Uso:
  python fts_comision.py --salida fts.ndjson.gz [--anios 2014-2025 | --anios 2024 2025] [--descargas DIR]
                         [--reusar] [--cordis-zip horizon.zip] [--incluir-horizon] [--incluir-mrr]
Para engancharlo a la carga completa: python fondos_ue_espana.py generar ... --con-fts (desactivado por defecto).
El fichero lleva nombres y NIF de personas jurídicas: nunca va al repositorio (.gitignore: *fts*.ndjson*).
"""
import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import re
import sys
import time
import unicodedata
import zipfile

import requests

try:
    from . import fondos_ue_espana as FUE
except ImportError:
    import fondos_ue_espana as FUE

FTS_CSV_URL = "https://ec.europa.eu/budget/financial-transparency-system/download/{anio}_FTS_dataset_en.csv"
FTS_WEB = "https://ec.europa.eu/budget/financial-transparency-system/"
ANIOS_POR_DEFECTO = tuple(range(2014, 2026))

# Filas de España medidas el 17-10-2026 (informe de viabilidad 2, §1e). Si un año sale por debajo del 80 %, se para.
FILAS_ESPANA_ESPERADAS = {2014: 3304, 2015: 5068, 2016: 5121, 2017: 5408, 2018: 5001, 2019: 6673, 2020: 7909,
                          2021: 6572, 2022: 10413, 2023: 8777, 2024: 6887, 2025: 5989}
MINIMO_RELATIVO = 0.8
MINIMO_AÑO_DESCONOCIDO = 2000

_RE_HORIZON = re.compile(r"horizon\s*(europe|2020)|\bh2020\b", re.I)
_RE_MRR = re.compile(r"recovery and resilience", re.I)
_RE_NIF_JURIDICA = re.compile(r"^[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]$")
_RE_DNI_NIE = re.compile(r"^(\d{8}[A-Z]|[XYZKLM]\d{7}[A-Z])$")
# Tipos de beneficiario del FTS que nunca son personas físicas (solo cuentan con --entidad-por-cif-o-tipo)
_TIPOS_ENTIDAD = {"other public bodies", "member states", "regions-provinces member states",
                  "ministries - member states", "international organisations", "eu decentralised agencies",
                  "ec entities not consolidated"}
_NOMBRES_PERSONA = {"NATURAL PERSON", "NATURAL PERSONS", "PRIVATE PERSON", "PRIVATE PERSONS"}

# Columnas que se usan (cabecera normalizada: minúsculas, apóstrofo recto, espacios simples)
_COL = {
    "anio": "year",
    "lc": "reference of the legal commitment (lc)",
    "nombre": "name of beneficiary",
    "vat": "vat number of beneficiary",
    "ciudad": "city",
    "cp": "postal code",
    "pais": "beneficiary country",
    "nuts2": "nuts2",
    "importe_est": "beneficiary's estimated contracted amount (eur)",
    "importe": "beneficiary's contracted amount (eur)",
    "coordinador": "coordinator",
    "proyecto": "project id",
    "acronimo": "project acronym",
    "asunto": "subject of grant or contract",
    "programa": "programme name",
    "tipo": "beneficiary type",
    "inicio": "project start date",
    "fin": "project end date",
}
_COL_OBLIGATORIAS = ("lc", "nombre", "vat", "pais", "importe_est", "programa", "tipo")

# Nombre de la comunidad tal como viene en NUTS2 (sin tildes, minúsculas) -> comunidad de la app
_NUTS2_POR_NOMBRE = (("andaluc", "andalucia"), ("arag", "aragon"), ("asturias", "asturias"),
                     ("balear", "baleares"), ("canarias", "canarias"), ("cantabria", "cantabria"),
                     ("castilla y leon", "castilla_y_leon"), ("castilla-la mancha", "castilla_la_mancha"),
                     ("castilla la mancha", "castilla_la_mancha"), ("catalu", "cataluna"), ("ceuta", "ceuta"),
                     ("valencia", "valenciana"), ("extremadura", "extremadura"), ("galicia", "galicia"),
                     ("rioja", "la_rioja"), ("madrid", "madrid"), ("melilla", "melilla"), ("murcia", "murcia"),
                     ("navarra", "navarra"), ("pais vasco", "pais_vasco"), ("euskadi", "pais_vasco"))
_NUTS2_DE_COMUNIDAD = {c: n for n, c in FUE.LIC.NUTS_COMUNIDAD.items()}


def _sin_tildes(texto):
    return "".join(c for c in unicodedata.normalize("NFD", texto or "") if unicodedata.category(c) != "Mn")


def _norm_cabecera(c):
    return " ".join((c or "").replace("’", "'").replace("﻿", "").strip().lower().split())


def comunidad_de_nuts2(valor):
    """Comunidad de la app a partir de la columna NUTS2 del FTS (trae el nombre, p. ej. "Comunidad de Madrid", o a
    veces el código)."""
    v = (valor or "").strip()
    if re.match(r"^ES\d\d", v.upper()):
        return FUE.LIC.comunidad_de_nuts(v)
    n = _sin_tildes(v).lower()
    for clave, comunidad in _NUTS2_POR_NOMBRE:
        if clave in n:
            return comunidad
    return ""


def provincia_de_cp(cp):
    d = re.sub(r"\D", "", cp or "")
    if len(d) == 4:
        d = "0" + d          # el cero de Álava, Albacete… a veces se pierde
    return FUE._CP_PROVINCIA.get(d[:2], "") if len(d) == 5 else ""


def clasificar(cp="", nuts2=""):
    """(provincia, ambito, comunidad, discordante). `discordante`: el código postal cae fuera de la comunidad NUTS2
    de la fila (manda la comunidad)."""
    comunidad = comunidad_de_nuts2(nuts2)
    provincia = provincia_de_cp(cp)
    if provincia:
        com_prov = FUE.COMUNIDAD_DE_PROVINCIA.get(provincia, "")
        if not comunidad or com_prov == comunidad:
            return provincia, "provincia", com_prov, False
    discordante = bool(provincia)
    if comunidad in FUE.PROVINCIA_UNICA:
        return FUE.PROVINCIA_UNICA[comunidad], "provincia", comunidad, discordante
    if comunidad:
        return "", "regional", comunidad, discordante
    return "", "estatal", "", discordante


def importe(valor):
    s = (valor or "").strip().replace(",", "").replace(" ", "")
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def normalizar_nif(vat):
    v = re.sub(r"[\s.\-/]", "", (vat or "").upper())
    return v[2:] if v.startswith("ES") else v


def _programa_corto(programa):
    """"2.2.32 - Erasmus+" -> "Erasmus+"."""
    codigo, sep, resto = (programa or "").partition(" - ")
    return resto.strip() if sep and re.match(r"^[\dA-Z./]+$", codigo.strip()) else (programa or "").strip()


def nombre_sin_cortes(nombre):
    """El FTS guarda el nombre en trozos de 35 caracteres y los junta con un espacio ("INTERNACIO NALIZACION",
    "S.C OOP"). Quita ese espacio en las posiciones 35, 70… Solo se usa para reconocer la forma jurídica: a veces el
    espacio es de verdad (en 2025, el 66 % de los nombres largos tiene espacio en la posición 35 y ~13 % en las
    vecinas), así que el nombre que se enseña es el de la fuente."""
    s, i = nombre or "", 35
    while len(s) > i and s[i] == " ":
        s = s[:i] + s[i + 1:]
        i += 35
    return s


def nombre_para_mostrar(nombre):
    """Quita la sigla que el FTS pega tras un asterisco ("UNIVERSIDAD DE VIGO*", "… SA*TEL") si es corta."""
    base, sep, sigla = (nombre or "").partition("*")
    return base.strip() if sep and base.strip() and len(sigla.strip()) <= 15 else (nombre or "").strip()


def es_entidad_fts(nombre):
    """es_entidad() de Kohesio sobre el nombre tal cual y sobre el nombre sin los cortes de 35 caracteres."""
    return FUE.es_entidad(nombre) or FUE.es_entidad(nombre_sin_cortes(nombre))


# ─── Descarga ───────────────────────────────────────────────────────────────────────────────────────────────────────
def descargar(sesion, anio, carpeta, reusar=False, intentos=4):
    """Baja el CSV del año a `carpeta` con flujo (bloques de 1 MB) y comprueba el tamaño. Para si no se puede."""
    url = FTS_CSV_URL.format(anio=anio)
    destino = os.path.join(carpeta, f"{anio}_FTS_dataset_en.csv")
    if reusar and os.path.exists(destino):
        try:
            h = sesion.head(url, timeout=60, allow_redirects=True)
            esperado = int(h.headers.get("Content-Length") or -1) if h.status_code == 200 else -1
        except requests.RequestException:
            esperado = -1
        if esperado == os.path.getsize(destino):
            print(f"  {anio}: se reutiliza la descarga ({esperado / 1e6:.1f} MB)", flush=True)
            return destino
    parcial = destino + ".part"
    for intento in range(1, intentos + 1):
        try:
            with sesion.get(url, stream=True, timeout=(30, 300)) as r:
                if r.status_code != 200:
                    print(f"  {anio}: HTTP {r.status_code} (intento {intento} de {intentos})", flush=True)
                else:
                    esperado = int(r.headers.get("Content-Length") or -1)
                    n = 0
                    with open(parcial, "wb") as f:
                        for bloque in r.iter_content(1 << 20):
                            f.write(bloque)
                            n += len(bloque)
                    if esperado in (-1, n) and n > 1_000_000:
                        os.replace(parcial, destino)
                        print(f"  {anio}: descargados {n / 1e6:.1f} MB", flush=True)
                        return destino
                    print(f"  {anio}: tamaño {n} distinto del anunciado {esperado} (intento {intento})", flush=True)
        except requests.RequestException as e:
            print(f"  {anio}: {type(e).__name__} (intento {intento} de {intentos})", flush=True)
        time.sleep(20 * intento)
    raise SystemExit(f"ERROR: no se pudo descargar el FTS de {anio} ({url}); no se genera el fichero")


def proyectos_cordis(ruta_zip):
    """Identificadores de proyecto de un ZIP de CORDIS (project.csv), leídos con flujo."""
    ids = set()
    with zipfile.ZipFile(ruta_zip) as z, z.open("project.csv") as f:
        for row in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"), delimiter=";"):
            if row.get("id"):
                ids.add(row["id"].strip())
    return ids


def detectar_codificacion(ruta):
    """Los CSV no vienen todos igual: 2025 está en Windows-1252 y 2014 en UTF-8 con BOM. Se mira el principio."""
    with open(ruta, "rb") as f:
        muestra = f.read(4 << 20)
    if muestra.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    try:
        muestra.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError as e:
        # un carácter de varios bytes cortado justo al final de la muestra no cuenta
        if e.start >= len(muestra) - 3:
            return "utf-8"
        return "cp1252"


# ─── Lectura de un año ──────────────────────────────────────────────────────────────────────────────────────────────
def _nuevo_resumen():
    return {"filas_csv": 0, "filas_cortas": 0, "filas_espana": 0, "incluidas": 0, "eur": 0.0, "sin_importe": 0,
            "excluidas_horizon": [0, 0.0], "excluidas_cordis_id": [0, 0.0], "excluidas_mrr": [0, 0.0],
            "con_nombre": 0, "sin_nombre_persona_fuente": 0, "sin_nombre_dudoso": 0, "dudoso_con_cif": 0,
            "con_nif": 0, "nif_dni_descartados": 0, "ubicacion_discordante": 0, "por_ambito": {}, "por_programa": {}}


def filas_anio(ruta, anio, resumen, excluir_horizon=True, excluir_mrr=True, cordis_ids=None, vistos=None,
               entidad_ampliada=False):
    """Recorre el CSV de un año y va devolviendo las filas de fondos_ue de España (generador; memoria constante)."""
    csv.field_size_limit(1 << 26)
    vistos = {} if vistos is None else vistos
    codificacion = detectar_codificacion(ruta)
    resumen["codificacion"] = codificacion
    with open(ruta, encoding=codificacion, errors="replace", newline="") as f:
        lector = csv.reader(f)
        cab = [_norm_cabecera(c) for c in next(lector)]
        pos = {k: cab.index(v) for k, v in _COL.items() if v in cab}
        faltan = [_COL[k] for k in _COL_OBLIGATORIAS if k not in pos]
        if faltan:
            raise SystemExit(f"ERROR: al CSV del FTS de {anio} le faltan columnas: {faltan}")
        ancho = len(cab)

        def g(row, k):
            i = pos.get(k)
            return row[i].strip() if i is not None and i < len(row) else ""

        for row in lector:
            resumen["filas_csv"] += 1
            if len(row) < ancho - 2:
                resumen["filas_cortas"] += 1
                continue
            if g(row, "pais") != "Spain":
                continue
            resumen["filas_espana"] += 1
            programa = g(row, "programa")
            nombre = g(row, "nombre")
            eur = importe(g(row, "importe_est"))
            if eur is None:
                eur = importe(g(row, "importe"))
            if eur is None:
                resumen["sin_importe"] += 1
                eur = 0.0
            proyecto = g(row, "proyecto")
            if excluir_horizon and _RE_HORIZON.search(programa):
                resumen["excluidas_horizon"][0] += 1
                resumen["excluidas_horizon"][1] += eur
                continue
            if excluir_mrr and _RE_MRR.search(programa):
                resumen["excluidas_mrr"][0] += 1
                resumen["excluidas_mrr"][1] += eur
                continue
            if cordis_ids and proyecto and proyecto in cordis_ids:
                resumen["excluidas_cordis_id"][0] += 1
                resumen["excluidas_cordis_id"][1] += eur
                continue

            nif = normalizar_nif(g(row, "vat"))
            tipo = g(row, "tipo")
            persona_fuente = tipo.lower().startswith("private person") or nombre.upper() in _NOMBRES_PERSONA
            if _RE_DNI_NIE.match(nif):
                resumen["nif_dni_descartados"] += 1
                persona_fuente = True
            if persona_fuente:
                publico, nif_ok = False, ""
                resumen["sin_nombre_persona_fuente"] += 1
            elif es_entidad_fts(nombre) or (entidad_ampliada and (
                    _RE_NIF_JURIDICA.match(nif) or tipo.lower() in _TIPOS_ENTIDAD)):
                publico, nif_ok = True, (nif if _RE_NIF_JURIDICA.match(nif) else "")
                resumen["con_nombre"] += 1
            else:
                publico, nif_ok = False, ""
                resumen["sin_nombre_dudoso"] += 1
                resumen["dudoso_con_cif"] += 1 if _RE_NIF_JURIDICA.match(nif) else 0
            resumen["con_nif"] += 1 if nif_ok else 0

            if persona_fuente:
                provincia, ambito, comunidad, discordante = clasificar("", g(row, "nuts2"))
            else:
                provincia, ambito, comunidad, discordante = clasificar(g(row, "cp"), g(row, "nuts2"))
            resumen["ubicacion_discordante"] += 1 if discordante else 0

            # identificador estable: año + compromiso + huella del beneficiario (+ orden si se repite)
            lc = g(row, "lc") or "sin-ref"
            huella = hashlib.sha1((nif or nombre or "?").encode("utf-8")).hexdigest()[:10] if publico else "anon"
            clave = f"fts-{anio}-{lc}-{huella}"
            n = vistos.get(clave, 0) + 1
            vistos[clave] = n
            if n > 1:
                clave = f"{clave}-{n}"

            asunto = FUE._titulo(g(row, "asunto"))
            acronimo = g(row, "acronimo")
            if acronimo.upper().startswith("N/A") or acronimo in ("-", "?"):
                acronimo = ""
            titulo = f"{acronimo} - {asunto}" if acronimo and acronimo not in asunto else asunto
            visible = nombre_para_mostrar(nombre)
            if not entidad_ampliada and not es_entidad_fts(visible):
                visible = nombre
            coordinador = g(row, "coordinador").lower()
            resumen["incluidas"] += 1
            resumen["eur"] += eur
            a = resumen["por_ambito"].setdefault(ambito, [0, 0.0])
            a[0] += 1
            a[1] += eur
            p = resumen["por_programa"].setdefault(programa or "(sin programa)", [0, 0.0])
            p[0] += 1
            p[1] += eur
            yield {
                "id": clave,
                "fuente": "fts",
                "provincia": provincia,
                "ambito": ambito,
                "comunidad": comunidad,
                "municipio": g(row, "ciudad").title() if publico else "",
                "nuts_code": _NUTS2_DE_COMUNIDAD.get(comunidad, ""),
                "titulo": "" if persona_fuente else titulo[:500],
                "beneficiario": visible[:300] if publico else "",
                "nif": nif_ok,
                "rol": "coordinator" if coordinador in ("yes", "y", "true") else
                       ("participant" if coordinador in ("no", "n", "false") else ""),
                "importe_num": round(eur, 2),
                "fecha_inicio": g(row, "inicio"),
                "fecha_fin": g(row, "fin"),
                "programa": programa,
                "fondo": _programa_corto(programa),
                "url": FTS_WEB,
                "anio": int(g(row, "anio") or anio) if (g(row, "anio") or str(anio)).isdigit() else anio,
            }


def comprobar_anio(anio, resumen):
    esperado = FILAS_ESPANA_ESPERADAS.get(anio)
    minimo = int(esperado * MINIMO_RELATIVO) if esperado else MINIMO_AÑO_DESCONOCIDO
    if resumen["filas_espana"] < minimo:
        raise SystemExit(f"ERROR: el FTS de {anio} trae {resumen['filas_espana']} filas de España (mínimo {minimo}); "
                         "no se genera el fichero")


def recorrer(anios, carpeta, sesion=None, reusar=False, excluir_horizon=True, excluir_mrr=True, cordis_zip=None,
             resumenes=None, entidad_ampliada=False):
    """Generador de todas las filas de los años pedidos. Rellena `resumenes` {año: resumen}. Si un año falla (descarga
    o pocas filas), lanza SystemExit: el que llama no debe escribir nada a medias."""
    os.makedirs(carpeta, exist_ok=True)
    if sesion is None:
        sesion = requests.Session()
        sesion.headers["User-Agent"] = "dinero-publico.com (fondos UE; datos abiertos de la Comisión Europea)"
    cordis_ids = proyectos_cordis(cordis_zip) if cordis_zip else None
    if cordis_ids is not None:
        print(f"  CORDIS: {len(cordis_ids)} proyectos para quitar duplicados", flush=True)
    resumenes = {} if resumenes is None else resumenes
    for anio in anios:
        ruta = descargar(sesion, anio, carpeta, reusar)
        resumen = resumenes.setdefault(anio, _nuevo_resumen())
        t = time.time()
        yield from filas_anio(ruta, anio, resumen, excluir_horizon, excluir_mrr, cordis_ids,
                              entidad_ampliada=entidad_ampliada)
        comprobar_anio(anio, resumen)
        print(f"  {anio}: {resumen['filas_espana']} filas de España de {resumen['filas_csv']}, {resumen['incluidas']} "
              f"incluidas ({resumen['eur'] / 1e6:,.1f} M€), {resumen['con_nombre']} con nombre "
              f"[{time.time() - t:.0f} s]", flush=True)


def resumen_total(resumenes):
    """Suma de los resúmenes por año. Nunca nombres."""
    tot = _nuevo_resumen()
    for r in resumenes.values():
        for k, v in r.items():
            if isinstance(v, list):
                tot[k] = [tot[k][0] + v[0], tot[k][1] + v[1]]
            elif isinstance(v, dict):
                for kk, (n, e) in v.items():
                    a = tot[k].setdefault(kk, [0, 0.0])
                    a[0] += n
                    a[1] += e
            elif isinstance(v, str):
                tot.setdefault("codificaciones", set()).add(v)
            else:
                tot[k] += v
    tot.pop("codificacion", None)
    tot["codificaciones"] = ",".join(sorted(tot.get("codificaciones", ())))
    return tot


def _millones(r):
    out = {}
    for k, v in r.items():
        if isinstance(v, list):
            out[k] = {"n": v[0], "millones": round(v[1] / 1e6, 2)}
        elif isinstance(v, dict):
            out[k] = {kk: {"n": n, "millones": round(e / 1e6, 2)}
                      for kk, (n, e) in sorted(v.items(), key=lambda x: -x[1][1])}
        elif k == "eur":
            out["millones"] = round(v / 1e6, 2)
        else:
            out[k] = v
    return out


def verificar_salida(ruta, filas_esperadas, eur_esperado, entidad_ampliada=False):
    """Relee el fichero escrito y comprueba filas, suma de importes y que no hay nombres ni NIF donde no debe."""
    n, eur, ids, malas = 0, 0.0, set(), []
    with gzip.open(ruta, "rt", encoding="utf-8") as f:
        for linea in f:
            d = json.loads(linea)
            n += 1
            eur += d["importe_num"]
            if d["id"] in ids:
                malas.append("id repetido")
            ids.add(d["id"])
            if d["nif"] and (not _RE_NIF_JURIDICA.match(d["nif"]) or not d["beneficiario"]):
                malas.append("NIF sin forma de persona jurídica o sin nombre")
            if d["beneficiario"] and not entidad_ampliada and not es_entidad_fts(d["beneficiario"]):
                malas.append("nombre que no es claramente de una entidad")
            if not d["beneficiario"] and d["municipio"]:
                malas.append("fila sin nombre con municipio")
            if d["ambito"] not in FUE.AMBITOS or (d["ambito"] == "provincia" and not d["provincia"]):
                malas.append("ámbito no válido")
    if n != filas_esperadas or abs(eur - eur_esperado) > max(1.0, abs(eur_esperado) * 1e-9):
        malas.append(f"recuento o suma distintos ({n} filas y {eur:.2f} € frente a {filas_esperadas} y "
                     f"{eur_esperado:.2f})")
    if malas:
        raise SystemExit(f"ERROR en la comprobación del fichero: {sorted(set(malas))[:5]}")
    return n, eur


def generar(salida, anios=ANIOS_POR_DEFECTO, carpeta="fts_descargas", reusar=False, excluir_horizon=True,
            excluir_mrr=True, cordis_zip=None, entidad_ampliada=False):
    """Escribe el NDJSON.gz (primero en .part, se renombra solo si todo cuadra) y devuelve el resumen."""
    t0 = time.time()
    resumenes = {}
    parcial = salida + ".part"
    n, eur = 0, 0.0
    try:
        with gzip.open(parcial, "wt", encoding="utf-8") as f:
            for fila in recorrer(anios, carpeta, None, reusar, excluir_horizon, excluir_mrr, cordis_zip, resumenes,
                                 entidad_ampliada):
                f.write(json.dumps(fila, ensure_ascii=False) + "\n")
                n += 1
                eur += fila["importe_num"]
        verificar_salida(parcial, n, eur, entidad_ampliada)
    except BaseException:
        if os.path.exists(parcial):
            os.remove(parcial)
        raise
    os.replace(parcial, salida)
    tot = resumen_total(resumenes)
    if abs(tot["eur"] - eur) > max(1.0, abs(eur) * 1e-6):
        raise SystemExit(f"ERROR: la suma por años ({tot['eur']:.2f}) no cuadra con la del fichero ({eur:.2f})")
    informe = {"filas": n, "millones": round(eur / 1e6, 2), "segundos": round(time.time() - t0),
               "total": _millones(tot),
               "por_anio": {a: {"filas_espana": r["filas_espana"], "incluidas": r["incluidas"],
                                "millones": round(r["eur"] / 1e6, 2), "con_nombre": r["con_nombre"],
                                "excluidas_horizon": r["excluidas_horizon"][0],
                                "excluidas_cordis_id": r["excluidas_cordis_id"][0],
                                "excluidas_mrr": r["excluidas_mrr"][0], "codificacion": r.get("codificacion", ""),
                                "sin_nombre": r["sin_nombre_persona_fuente"] + r["sin_nombre_dudoso"]}
                            for a, r in resumenes.items()}}
    return informe


def _anios(valores):
    out = []
    for v in valores:
        if "-" in v:
            a, b = v.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(v))
    return tuple(sorted(set(out)))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="FTS de la Comisión Europea, beneficiarios de España (NDJSON.gz)")
    ap.add_argument("--salida", required=True)
    ap.add_argument("--anios", nargs="+", default=[f"{ANIOS_POR_DEFECTO[0]}-{ANIOS_POR_DEFECTO[-1]}"],
                    help="años o tramos (2014-2025 por defecto)")
    ap.add_argument("--descargas", default="fts_descargas", help="carpeta para los CSV anuales")
    ap.add_argument("--reusar", action="store_true", help="no volver a bajar un CSV que ya está y mide lo mismo")
    ap.add_argument("--cordis-zip", help="ZIP de CORDIS para quitar también los proyectos que ya están en CORDIS")
    ap.add_argument("--incluir-horizon", action="store_true", help="no excluir Horizon Europe ni Horizon 2020")
    ap.add_argument("--incluir-mrr", action="store_true", help="no excluir el MRR pagado al Reino de España")
    ap.add_argument("--entidad-por-cif-o-tipo", action="store_true",
                    help="publicar también el nombre si el NIF es de persona jurídica o el FTS lo clasifica como "
                         "organismo público, Estado, región u organización internacional (NO es la regla de Kohesio; "
                         "solo si César lo decide)")
    ap.add_argument("--informe", help="guardar también el resumen (sin nombres) en este JSON")
    a = ap.parse_args()
    res = generar(a.salida, _anios(a.anios), a.descargas, a.reusar, not a.incluir_horizon, not a.incluir_mrr,
                  a.cordis_zip, a.entidad_por_cif_o_tipo)
    texto = json.dumps(res, ensure_ascii=False, indent=1)
    print(texto, flush=True)
    if a.informe:
        with open(a.informe, "w", encoding="utf-8") as f:
            f.write(texto)
    sys.exit(0)
