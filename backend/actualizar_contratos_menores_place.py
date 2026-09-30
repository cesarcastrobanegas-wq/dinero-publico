"""Genera backend/contratos_menores_place_AAAA-MM.json.gz (un fichero por mes de adjudicación: al cargarlos, el pico
de memoria es el de un mes, ~20.000 contratos, no el de un año entero, ~245.000 y +330 MB): contratos menores de ayuntamientos (y sus entes: distritos,
organismos autónomos, empresas municipales) del conjunto de datos oficial de Hacienda "Contratos menores publicados en
los perfiles del contratante ubicados en la Plataforma de Contratación del Sector Público" (sindicación 1143,
ZIP mensuales contratosMenoresPerfilesContratantes_AAAAMM.zip).

Decisiones (propuestas el 2026-09-29 y aplicadas al conectar el feed el 2026-09-30 por indicación de César):
- Alcance: toda España salvo Cataluña y País Vasco, que ya tienen agregador regional de menores (RPC, API Euskadi).
- Municipio asignado por la JERARQUÍA oficial del órgano (ParentLocatedParty "<Municipio> / Ayuntamientos /
  <Provincia>"), nunca por el texto del nombre del órgano; nombre + provincia contra las listas de la app. Si en ese
  hueco no hay un municipio (distritos y áreas de Madrid, organismos autónomos, EPE...), se usa el código INE del
  DIR3 del órgano (L01<INE><dígito>) o de su NIF (P<INE>00<letra>), aprendido de los contratos que sí se asignaron
  por nombre. Las entidades locales menores (DIR3 L04..., NIF propio) NO se asignan al municipio: son otra entidad.
- Importe: el SIN IVA del feed (TaxExclusiveAmount del adjudicado, 99,4 % de cobertura). Se guarda también el
  importe con IVA en `import_con_iva`, solo para emparejar duplicados con fuentes propias (ver app.py).
- Duplicados con fuentes propias: los resuelve app.py al cargar (_cargar_contratos_menores_place: manda la fuente
  propia), no este script.
- Ventana: adjudicación desde MENORES_DESDE_FECHA (2021-09-01). Cada ZIP mensual trae los contratos ACTUALIZADOS ese
  mes (de cualquier fecha de adjudicación); con todos los meses desde 202109 y la versión más reciente de cada <id>
  se cubre toda la ventana.

Uso (desde backend/):
    python actualizar_contratos_menores_place.py descargar 202609 202109      # fase A: solo descargas (lenta)
    python actualizar_contratos_menores_place.py generar 202609 202109        # fase B: ficheros por año
Opciones: --zips DIR (caché de ZIP, por defecto %TEMP%/place_menores_zips; se aceptan también men_AAAAMM.zip)."""
import argparse
import collections
import gzip
import json
import os
import re
import sys
import tempfile
import threading
import time
import zipfile

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ZIP_URL = ("https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_1143/"
           "contratosMenoresPerfilesContratantes_{m}.zip")
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36"}
FUENTE = "place-menores"
DESDE_FECHA = "2021-09-01"
HASTA_FECHA = f"{time.localtime().tm_year + 1}-12-31"
LOG_PATH = os.path.join(tempfile.gettempdir(), "contratos_menores_place.log")
_SESION = requests.Session()
_SESION.trust_env = False
TIPOS = {"1": "Suministros", "2": "Servicios", "3": "Obras", "21": "Gestión de Servicios Públicos",
         "22": "Concesión de Servicios", "31": "Concesión de Obras", "7": "Administrativo especial", "8": "Privado",
         "50": "Patrimonial"}


def log(msg):
    linea = f"[{time.strftime('%H:%M:%S')}] {msg}"
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(linea + "\n")
    print(linea, flush=True)


def meses_atras(desde, hasta):
    y, m = int(desde[:4]), int(desde[4:])
    while f"{y}{m:02d}" >= hasta:
        yield f"{y}{m:02d}"
        m -= 1
        if m == 0:
            y, m = y - 1, 12


def ruta_zip(zips, mes):
    for nombre in (f"place_menores_{mes}.zip", f"men_{mes}.zip"):
        p = os.path.join(zips, nombre)
        if os.path.exists(p) and zip_valido(p):
            return p
    return None


def zip_valido(p):
    try:
        with zipfile.ZipFile(p) as z:
            return bool(z.namelist())
    except Exception:
        return False


# ── Fase A: descargas ────────────────────────────────────────────────────────────────────────────────────────────────
def descargar(mes, zips, intentos=6):
    destino = os.path.join(zips, f"place_menores_{mes}.zip")
    parcial = destino + ".part"
    for intento in range(1, intentos + 1):
        t0 = time.time()
        try:
            r = _SESION.get(ZIP_URL.format(m=mes), headers=HEADERS, stream=True, timeout=(20, 90))
            if r.status_code != 200:
                log(f"{mes}: HTTP {r.status_code}")
                return False
            with open(parcial, "wb") as f:
                for trozo in r.iter_content(1 << 20):
                    f.write(trozo)
            if not zip_valido(parcial):
                raise IOError("ZIP no válido (descarga incompleta)")
            os.replace(parcial, destino)
            log(f"{mes}: descargado ({os.path.getsize(destino) >> 20} MB, {time.time() - t0:.0f} s)")
            return True
        except Exception as e:
            log(f"{mes}: descarga fallida (intento {intento}/{intentos}, {time.time() - t0:.0f} s): {type(e).__name__} {e}")
            time.sleep(20 * intento)
    return False


def fase_descargar(meses, zips, paralelas=3):
    pendientes = [m for m in meses if not ruta_zip(zips, m)]
    log(f"descargas: {len(meses) - len(pendientes)} ya en caché, {len(pendientes)} pendientes -> {zips}")
    cola = list(pendientes)
    fallidos = []
    cerrojo = threading.Lock()

    def trabajador():
        while True:
            with cerrojo:
                if not cola:
                    return
                mes = cola.pop(0)
            if not descargar(mes, zips):
                with cerrojo:
                    fallidos.append(mes)
    hilos = [threading.Thread(target=trabajador) for _ in range(paralelas)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    log(f"FIN descargas: fallidos {sorted(fallidos) or 'ninguno'}")
    return not fallidos


# ── Fase B: análisis y asignación ────────────────────────────────────────────────────────────────────────────────────
def _g(pat, e):
    m = re.search(pat, e, re.S)
    return m.group(1).strip() if m else ""


def _num(s):
    try:
        return round(float(s), 2)
    except (TypeError, ValueError):
        return None


def parsear(e):
    lcp = _g(r"<cac-place-ext:LocatedContractingParty>(.*?)</cac-place-ext:LocatedContractingParty>", e)
    propio = lcp.split("<cac-place-ext:ParentLocatedParty>")[0]
    # algunos nodos llevan <cac:PartyIdentification> (DIR3) ANTES del nombre (Baleares, Zamora, Burgos...)
    padres = re.findall(r"<cac-place-ext:ParentLocatedParty>\s*(?:<cac:PartyIdentification>(?:(?!</cac:PartyIdentification>).)*"
                        r"</cac:PartyIdentification>\s*)*<cac:PartyName>\s*<cbc:Name>([^<]+)</cbc:Name>", lcp, re.S)
    wp = _g(r"<cac:WinningParty>(.*?)</cac:WinningParty>", e)
    alt = _g(r"<cac:AwardedTenderedProject>(.*?)</cac:AwardedTenderedProject>", e)
    pp = _g(r"<cac:ProcurementProject>(.*?)</cac:ProcurementProject>", e)
    return {
        "id": _g(r"<id>[^<]*/(\d+)</id>", e) or _g(r"<id>([^<]+)</id>", e),
        "updated": _g(r"<updated>([^<]+)</updated>", e),
        "titulo": _g(r"<title>([^<]*)</title>", e),
        "organo": _g(r"<cac:PartyName>\s*<cbc:Name>([^<]+)</cbc:Name>", propio),
        "dir3": _g(r'<cbc:ID schemeName="DIR3">([^<]+)</cbc:ID>', propio),
        "nif_org": _g(r'<cbc:ID schemeName="NIF">([^<]+)</cbc:ID>', propio),
        "ciudad": _g(r"<cac:PostalAddress>\s*<cbc:CityName>([^<]+)</cbc:CityName>", propio),
        "padres": padres,
        "fecha": _g(r"<cbc:AwardDate>([^<]+)</cbc:AwardDate>", e)[:10],
        "sin_iva": _num(_g(r'<cbc:TaxExclusiveAmount currencyID="EUR">([^<]+)<', alt)),
        "con_iva": _num(_g(r'<cbc:PayableAmount currencyID="EUR">([^<]+)<', alt)),
        "adj": _g(r"<cac:PartyName>\s*<cbc:Name>([^<]+)</cbc:Name>", wp),
        "nif_adj": _g(r"<cac:PartyIdentification>\s*<cbc:ID[^>]*>([^<]+)</cbc:ID>", wp),
        "tipo": TIPOS.get(_g(r"<cbc:TypeCode[^>]*>([^<]+)</cbc:TypeCode>", pp), ""),
        "cpv": _g(r"<cbc:ItemClassificationCode[^>]*>([^<]+)</cbc:ItemClassificationCode>", pp),
    }


def ine_de(r):
    m = re.match(r"^L01(\d{5})\d$", r["dir3"] or "")
    if m:
        return m.group(1)
    m = re.match(r"^P(\d{5})00[A-Z]$", (r["nif_org"] or "").upper())
    return m.group(1) if m else ""


# Alias comprobados a mano (nombre en la jerarquía de PLACE, provincia de la app) -> nombre en las listas de la app.
ALIAS = {("borriana", "castellon"): "Burriana", ("san bartolome de lanzarote", "las_palmas"): "San Bartolomé",
         ("cangas", "pontevedra"): "Cangas de Morrazo", ("las rozas", "madrid"): "Las Rozas de Madrid",
         ("benicassim", "castellon"): "Benicasim", ("lborea", "albacete"): "Alborea",
         ("alcoba", "ciudad_real"): "Alcoba de los Montes", ("herbes", "castellon"): "Herbers",
         ("palma de mallorca", "baleares"): "Palma",
         # grafía valenciana/oficial en PLACE, castellana en las listas de la app (2026-09-30)
         ("alfarp", "valencia"): "Alfarb", ("montitxelvo", "valencia"): "Montichelvo",
         ("el poble nou de benitatxell", "alicante"): "Benitachell", ("cortelazor la real", "huelva"): "Cortelazor"}
# Prefijos que PLACE pone a veces en el hueco del municipio (fórmulas honoríficas u órganos del propio ayuntamiento).
PREFIJOS = r"^(villa de |ciudad de |muy noble y leal villa de |junta de gobierno( local)? del? (excmo\. |ilmo\. )?ayuntamiento de |ayuntamiento de )"
# Entidades locales que NO son el municipio: entidades locales menores/autónomas, mancomunidades, consorcios...
NO_MUNICIPAL = re.compile(r"entidad local menor|entidad local autonoma|parroquia rural|mancomunidad|consorcio|comarca", re.I)


def es_no_municipal(r, A):
    d = r["dir3"] or ""
    if re.match(r"^L0[2-9]", d):
        return True
    p = r["padres"]
    hueco = p[p.index("Ayuntamientos") - 1] if "Ayuntamientos" in p and p.index("Ayuntamientos") > 0 else ""
    return bool(NO_MUNICIPAL.search(A.normalizar(hueco)) or NO_MUNICIPAL.search(A.normalizar(r["organo"])))


class Asignador:
    """Jerarquía (municipio + provincia) -> (nombre en la app, provincia de la app)."""

    def __init__(self, A):
        self.A = A
        self.prov_por_nombre = {}
        for clave, label in A.PROVINCIA_LABEL.items():
            base = re.sub(r"^(Provincia de|Región de|Comunidad de|Comunidad Foral de|Principado de|Ciudad Autónoma de|"
                          r"Illes|Islas)\s+", "", label)
            for n in (base, label, clave.replace("_", " ")):
                self.prov_por_nombre[A.normalizar(n)] = clave
        self.excluidas = set(A.PROVINCIAS_CATALUNYA) | set(A.PROVINCIAS_PAIS_VASCO)
        # País Vasco: fuera solo los municipios que cubre la API de Euskadi; los que no están en KontratazioA (Zalla,
        # Elantxobe) publican en PLACE y sí entran.
        self.cubiertos_euskadi = set(getattr(A, "MUNICIPIOS_PAIS_VASCO_EUSKADI_ID", {}))
        self.idx = collections.defaultdict(set)
        self.laxo = collections.defaultdict(set)
        for prov, lst in A.MUNICIPIOS_POR_PROVINCIA.items():
            for m in lst:
                for f in self._formas(m):
                    self.idx[(prov, f)].add(m)
                self.laxo[(prov, self._laxa(m))].add(m)
        self.por_ine = {}

    def _norm(self, nombre):
        """normalizar() de la app no quita todos los diacríticos ("L'Alcùdia", "Aýna"): se quitan antes."""
        import unicodedata
        sin = "".join(c for c in unicodedata.normalize("NFD", nombre or "") if unicodedata.category(c) != "Mn")
        return self.A.normalizar(sin).replace("´", "'").replace("’", "'")

    def _formas(self, nombre):
        n = self._norm(nombre)
        formas = set()
        for parte in {n} | set(re.split(r"\s*/\s*", n)):
            for f in set(self.A._variantes_nombre_municipio(parte)) | {parte}:
                formas.add(f.replace("-", " "))
        return formas

    def _laxa(self, nombre):
        """Forma laxa: sin artículos, sin 'de/del', sin apóstrofos ni guiones ("Vall de Gallinera, la" = "Vall de
        Gallinera"; "Alqueries, les" = "Les Alqueries"; "San Vicente del Raspeig" = "San Vicente Raspeig"). Solo se usa
        si identifica UN único municipio de esa provincia."""
        n = self._norm(re.split(r"\s*/\s*", nombre)[0])
        n = re.sub(r"\b(el|la|los|las|les|els|l'|d'|s'|es|sa|ses|o|a|os|as|de|del|dels)\b", " ", n.replace("'", "' "))
        return re.sub(r"[^a-z0-9]", "", n)

    def provincia(self, nombre):
        n = self.A.normalizar(nombre)
        for c in [n] + [x.strip() for x in re.split(r"[/-]", n)]:
            if c in self.prov_por_nombre:
                return self.prov_por_nombre[c]
        if n in ("vizcaya", "bizkaia", "guipuzcoa", "gipuzkoa", "alava", "araba"):
            return "pais_vasco"
        return None

    def provincia_de(self, r):
        p = r["padres"]
        if "Ayuntamientos" not in p:
            return None
        i = p.index("Ayuntamientos")
        return self.provincia(p[i + 1] if i + 1 < len(p) else "")

    def nombre_a_municipio(self, nombre, prov):
        n = self._norm(nombre).strip()
        if (n, prov) in ALIAS:
            return ALIAS[(n, prov)]
        for cand in dict.fromkeys([n, re.sub(PREFIJOS, "", n)]):
            cands = set()
            for f in self._formas(cand):
                cands |= self.idx.get((prov, f), set())
            if not cands:
                cands = self.laxo.get((prov, self._laxa(cand)), set())
            if len(cands) == 1:
                return next(iter(cands))
        return None

    def por_jerarquia(self, r):
        p = r["padres"]
        prov = self.provincia_de(r)
        if not prov or p.index("Ayuntamientos") == 0:
            return None, prov
        return self.nombre_a_municipio(p[p.index("Ayuntamientos") - 1], prov), prov

    def por_ciudad(self, r):
        """Último respaldo para entes del ayuntamiento cuyo nombre ocupa el hueco del municipio (Organismo Autónomo
        Madrid Salud...): la localidad de la dirección postal del órgano, en la provincia de la jerarquía."""
        prov = self.provincia_de(r)
        return (self.nombre_a_municipio(r["ciudad"], prov) if prov and r["ciudad"] else None), prov


def fase_generar(meses, zips, A):
    asg = Asignador(A)
    faltan = [m for m in meses if not ruta_zip(zips, m)]
    if faltan:
        log(f"!!! faltan ZIP de {len(faltan)} meses: {faltan}. Primero: descargar.")
        return False
    ultimo = {}      # id -> registro parseado (la versión con <updated> más reciente)
    for mes in sorted(meses):
        t0 = time.time()
        n = 0
        with zipfile.ZipFile(ruta_zip(zips, mes)) as z:
            for nombre in z.namelist():
                x = z.read(nombre).decode("utf-8", "replace")
                for e in x.split("<entry>")[1:]:
                    n += 1
                    if "<cbc:Name>Ayuntamientos</cbc:Name>" not in e:
                        continue            # solo entidades bajo "Ayuntamientos" (descarta AGE, CCAA, diputaciones...)
                    r = parsear(e)
                    if not r["fecha"] or r["fecha"] < DESDE_FECHA or r["fecha"] > HASTA_FECHA:
                        continue            # sin fecha, fuera de ventana o imposible (errata de origen: año 2501)
                    prev = ultimo.get(r["id"])
                    if not prev or r["updated"] >= prev["updated"]:
                        ultimo[r["id"]] = r
                del x
        log(f"{mes}: {n} entradas, acumulados {len(ultimo)} contratos municipales únicos ({time.time() - t0:.0f} s)")

    # 1) por jerarquía; 2) aprender INE -> municipio de los asignados; 3) resto por INE (DIR3 / NIF del órgano)
    est = collections.Counter()
    asignado = {}
    votos = collections.defaultdict(collections.Counter)
    sin = collections.Counter()
    no_municipal = {k for k, r in ultimo.items() if es_no_municipal(r, A)}
    est["entidad local no municipal (ELM, mancomunidad...): se excluye"] = len(no_municipal)
    for k, r in ultimo.items():
        if k in no_municipal:
            continue
        m, prov = asg.por_jerarquia(r)
        if m:
            asignado[k] = (m, prov)
            if ine_de(r):
                votos[ine_de(r)][(m, prov)] += 1
    for ine, c in votos.items():
        (mp, n1), = c.most_common(1)
        if n1 >= 0.95 * sum(c.values()):
            asg.por_ine[ine] = mp
    for k, r in ultimo.items():
        if k in no_municipal:
            continue
        if k in asignado:
            est["por jerarquía"] += 1
            continue
        mp = asg.por_ine.get(ine_de(r))
        m2, prov2 = asg.por_ciudad(r)
        if mp:
            asignado[k] = mp
            est["por DIR3/NIF del órgano"] += 1
        elif m2:
            asignado[k] = (m2, prov2)
            est["por localidad del órgano"] += 1
        else:
            est["sin asignar"] += 1
            p = r["padres"]
            i = p.index("Ayuntamientos") if "Ayuntamientos" in p else 0
            etiqueta = (p[i - 1] if i else "?", p[i + 1] if i + 1 < len(p) else "?")
            prov_h = asg.provincia_de(r)
            if prov_h and (asg._norm(etiqueta[0]), prov_h) in {(asg._norm(m), pv) for m, pv, _ in
                                                                getattr(A, "HOMONIMOS_SIN_RESOLVER", [])}:
                etiqueta = ("[homónimo sin resolver] " + etiqueta[0], etiqueta[1])
            sin[etiqueta] += 1
    log(f"asignación: {dict(est)}")
    log(f"sin asignar (top 40): {sin.most_common(40)}")

    por_anio = collections.defaultdict(list)
    fuera = collections.Counter()
    for k, (m, prov) in asignado.items():
        if prov in asg.excluidas and not (prov == "pais_vasco" and m not in asg.cubiertos_euskadi):
            fuera[prov] += 1
            continue
        r = ultimo[k]
        por_anio[r["fecha"][:7]].append({
            "id": f"{FUENTE}::{k}", "municipio": m, "provincia": prov, "fuente": FUENTE,
            "organisme": r["organo"], "adjudicatari": r["adj"], "nif": r["nif_adj"],
            "import_num": r["sin_iva"], "import_con_iva": r["con_iva"], "data_adjudicacio": r["fecha"],
            "tipus_contracte": r["tipo"], "descripcio": r["titulo"], "codi_cpv": r["cpv"],
            "exercici": r["fecha"][:4]})
    log(f"fuera de alcance (agregador regional propio): {dict(fuera)}")
    for anio, regs in sorted(por_anio.items()):
        regs.sort(key=lambda x: (x["provincia"], x["municipio"], x["data_adjudicacio"], x["id"]))
        ruta = os.path.join(BASE_DIR, f"contratos_menores_place_{anio}.json.gz")      # un fichero por MES (AAAA-MM)
        tmp = ruta + ".tmp"
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump({"generado": time.strftime("%Y-%m-%d"), "meses_zip": [min(meses), max(meses)],
                       "descripcion": ("Contratos menores de ayuntamientos y sus entes, feed oficial de PLACE "
                                       "(sindicación 1143). Importe SIN IVA; import_con_iva solo para emparejar "
                                       "duplicados. Ver actualizar_contratos_menores_place.py."),
                       "registros": regs}, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, ruta)
        log(f"{ruta}: {len(regs)} contratos en {len({(x['municipio'], x['provincia']) for x in regs})} municipios "
            f"({os.path.getsize(ruta) >> 20} MB)")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("fase", choices=["descargar", "generar"])
    ap.add_argument("desde")
    ap.add_argument("hasta")
    ap.add_argument("--zips", default=os.path.join(tempfile.gettempdir(), "place_menores_zips"))
    args = ap.parse_args()
    os.makedirs(args.zips, exist_ok=True)
    meses = list(meses_atras(args.desde, max(args.hasta, "202109")))
    if args.fase == "descargar":
        sys.exit(0 if fase_descargar(meses, args.zips) else 1)
    argv = sys.argv[:]                    # `import app` reasigna sys.argv: se guarda antes (ver lecciones del proyecto)
    import sqlite3
    tmp = tempfile.mkdtemp(prefix="place_menores_")
    sqlite3.connect(os.path.join(tmp, "cache.db")).close()
    os.environ["DATA_DIR"] = tmp
    os.environ["HTTP_PROXY"] = os.environ["HTTPS_PROXY"] = "http://127.0.0.1:9"
    sys.path.insert(0, BASE_DIR)
    real = sys.stdout
    sys.stdout = sys.stderr = open(os.devnull, "w")
    import app as A
    sys.stdout = sys.stderr = real
    sys.argv = argv
    ok = fase_generar(meses, args.zips, A)
    os._exit(0 if ok else 1)


if __name__ == "__main__":
    main()
