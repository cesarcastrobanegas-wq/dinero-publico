# encoding: utf-8
"""
Informe de mercado público en PDF (3-5 páginas, blanco y negro) para enseñar y vender: encargo del titular del 04-11-2026.

Dos modos:
  - EMPRESA: por NIF de una persona jurídica (nunca personas físicas ni autónomos). Sector(es) = los de sus contratos.
  - SECTOR + PROVINCIA: uno de los sectores de SECTORES (los mismos 21 de la lista de clientes) en una provincia.

Contenido: resumen con cifras, licitaciones abiertas que encajan (de los ZIP mensuales de PLACE), contratos ganados
por la empresa (modo empresa), principales adjudicatarias del sector (solo sociedades; las personas físicas y
autónomos se suman en una línea sin identificar), organismos que más contratan, cuándo se contrata (trimestres y
tamaños) y nota de método.

HERRAMIENTA LOCAL: lee una copia de cache.db en modo solo lectura y ZIP de PLACE ya descargados. No arranca la web, no
escribe en ninguna base, no sale a la red. Producción no tiene reportlab (no está en requirements.txt) y no lo necesita.
Nunca usa el campo «directivo» de los contratos (nombres de administradores).

Uso:
  python backend/informe_mercado.py --db COPIA.db --zip place_202610.zip --zip place_202611.zip \
         (--nif B30000000 | --sector "Limpieza" [--provincia murcia]) --salida informe.pdf [--titulo "..."]
  python backend/informe_mercado.py --sectores        (lista los sectores)
"""
import argparse
import collections
import json
import os
import re
import sqlite3
import sys
import unicodedata
import zipfile
from datetime import date, datetime
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import licitaciones_place as LIC  # noqa: E402

MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre")
NOMBRE_PROVINCIA = {"murcia": "Región de Murcia"}       # el resto: el nombre de la clave con mayúscula
LETRAS_SOCIEDAD = set("ABCDFJNW")
FORMA_JURIDICA = re.compile(r"\b(S\.?\s?L\.?\s?U?\.?|S\.?\s?A\.?\s?U?\.?|S\.?\s?COOP|SOCIEDAD (LIMITADA|ANONIMA|COOPERATIVA)|"
                            r"S\.?\s?L\.?\s?L\.?|S\.?\s?L\.?\s?P\.?|COOPERATIVA|SDAD\.? COOP)\b")

# (nombre, división CPV de referencia, prefijos CPV, palabras del objeto). Un contrato con CPV va al sector del prefijo
# más largo que encaje; sin CPV (los formales de la base no lo guardan), por las palabras del objeto.
SECTORES = [
    ("Limpieza", "90", ("9091", "9092"), r"LIMPIEZA|LIMPIAR|DESINFECC|DESRATIZ|FUMIGA"),
    ("Medio ambiente y residuos", "90", ("905", "90"), r"RESIDUO|BASURA|RECOGIDA DE|VERTED|ECOPARQUE|CONTENEDOR"),
    ("Jardinería y zonas verdes", "77", ("77",), r"JARDIN|PODA|ARBOLADO|ZONAS VERDES|DESBROCE"),
    ("Eventos, cultura y espectáculos", "92", ("7995", "92"),
     r"ACTUACION|ESPECTACULO|CONCIERTO|ORQUESTA|FIESTA|FERIA|FESTIVAL|CARNAVAL|SEMANA SANTA|NAVIDAD|ESCENARIO|SONIDO|"
     r"ILUMINACION ORNAMENTAL|TEATRO|CABALGATA|PIROTECN|FUEGOS|EVENTO|GALA|DISCO MOVIL|CARPA"),
    ("Informática y telecomunicaciones", "72", ("72", "48", "302", "32", "64"),
     r"INFORMATIC|SOFTWARE|LICENCIA|ORDENADOR|SERVIDOR|PLATAFORMA|APLICACION|WEB|TELEFON|FIBRA|INTERNET|CIBERSEG|"
     r"IMPRESORA|TOTEM|DIGITAL|PORTATIL|VIDEOVIGILANCIA|HOSTING|CERTIFICADO ELECTRONICO"),
    ("Publicidad, comunicación e imprenta", "79", ("7934", "7982", "22"),
     r"PUBLICIDAD|PUBLICITAR|CARTEL|IMPRESION|IMPRENTA|FOLLETO|REVISTA|COMUNICACION|DISENO GRAFICO|RADIO|TELEVISION|"
     r"CUNA|LONA|ROTULO|VINILO"),
    ("Seguridad y vigilancia", "79", ("7971", "35"),
     r"VIGILANCIA|SEGURIDAD PRIVADA|ALARMA|CONTROL DE ACCESO|EXTINTOR|CONTRA INCENDIO"),
    ("Mantenimiento e instalaciones", "50", ("50", "51", "31", "42"),
     r"MANTENIMIENTO|REPARACION|INSTALACION|ALUMBRADO|ELECTRIC|CLIMATIZ|FONTANER|ASCENSOR|CALDERA|AIRE ACONDICIONADO|"
     r"SEMAFOR|FOTOVOLTAIC|CERRAJER|PINTURA"),
    ("Construcción y obra civil", "45", ("45", "44"),
     r"OBRA|PAVIMENT|ASFALT|URBANIZ|REHABILIT|CONSTRUC|REFORMA|ACERA|SANEAMIENTO|ABASTECIMIENTO|CAMINO|CARRETERA|"
     r"ALCANTARILL|DEMOLIC|HORMIG|ALBANIL|CUBIERTA"),
    ("Ingeniería y arquitectura", "71", ("71",),
     r"REDACCION DE PROYECTO|PROYECTO TECNICO|DIRECCION DE OBRA|DIRECCION FACULTATIVA|COORDINACION DE SEGURIDAD|"
     r"ARQUITECT|INGENIERI|TOPOGRAF|ESTUDIO GEOTECNICO|AUDITORIA ENERGETICA"),
    ("Formación, educación y servicios sociales", "80", ("80", "85"),
     r"FORMACION|CURSO|TALLER|ESCUELA|EDUCAT|MONITOR|AYUDA A DOMICILIO|DEPENDENCIA|MAYORES|INFANCIA|CONCILIACION|"
     r"LUDOTECA|SOCIAL|PSICOLOG|IGUALDAD|JUVENTUD|CAMPAMENTO"),
    ("Transporte", "60", ("60", "63"), r"TRANSPORTE|AUTOBUS|AUTOCAR|VIAJE|EXCURSION|TRASLADO|GRUA"),
    ("Vehículos y maquinaria", "34", ("34", "43", "16"),
     r"VEHICULO|CAMION|FURGONETA|TURISMO|MAQUINARIA|BARREDORA|NEUMATICO|RENTING"),
    ("Alimentación y restauración", "55", ("55", "15", "03"),
     r"COMIDA|CATERING|ALIMENT|COMEDOR|MENU|ALMUERZO|CENA|BEBIDA|AGUA EMBOTELLADA|RESTAURA|DESAYUNO|VINO DE HONOR"),
    ("Energía y combustibles", "09", ("09", "65"),
     r"COMBUSTIBLE|GASOLEO|GASOIL|CARBURANTE|SUMINISTRO ELECTRICO|ENERGIA ELECTRICA|GAS NATURAL"),
    ("Sanidad y material sanitario", "33", ("33", "851"),     # 851: servicios sanitarios (ambulancias...)
     r"SANITARI|MEDIC|FARMAC|DESFIBRIL|AMBULANCIA|PREVENCION DE RIESGOS|VIGILANCIA DE LA SALUD"),
    ("Deporte y ocio", "37", ("37",), r"DEPORT|PISCINA|GIMNAS|SOCORRIST|CAMPO DE FUTBOL|CESPED ARTIFICIAL|COMPETICION"),
    ("Mobiliario y equipamiento", "39", ("39",), r"MOBILIARIO|MUEBLE|SILLA|MESA|JUEGOS INFANTILES|PAPELERA|BANCO"),
    ("Vestuario y material diverso", "18", ("18", "19", "24"),
     r"VESTUARIO|UNIFORME|ROPA|CALZADO|MATERIAL DE OFICINA|PAPEL|TROFEO|MEDALLA|MATERIAL FUNGIBLE|FERRETER|"
     r"PRODUCTOS QUIMICOS|SENALIZACION"),
    ("Consultoría y servicios a empresas", "79", ("79", "73", "66"),
     r"ASESORAMIENTO|CONSULTORIA|ASISTENCIA TECNICA|SEGURO|POLIZA|GESTION|AUDITORIA|ESTUDIO|PLAN|TRADUCC|NOTIFICAC|"
     r"TURISMO|TURISTIC"),
]
NOMBRES_SECTOR = [s[0] for s in SECTORES]
_POR_CPV = sorted(((p, s[0]) for s in SECTORES for p in s[2]), key=lambda x: -len(x[0]))
_POR_PALABRAS = [(s[0], re.compile(s[3])) for s in SECTORES]


# ───────────────────────────── utilidades ─────────────────────────────

def norm(t):
    t = unicodedata.normalize("NFKD", (t or "").upper())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = re.sub(r"[^A-Z0-9 ]", " ", t)
    t = re.sub(r"\b(SOCIEDAD LIMITADA|SOCIEDAD ANONIMA|S L U|S L|SLU|SL|S A U|S A|SAU|SA|S COOP|COOP|LIMITADA|ANONIMA|"
               r"UNIPERSONAL)\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def nif_ok(n):
    n = (n or "").strip().upper().replace("-", "").replace(" ", "").replace(".", "")
    if n.startswith("ES") and len(n) == 11:
        n = n[2:]
    return n if re.fullmatch(r"[A-Z0-9]{9}", n) else ""


def es_sociedad(nif, nombre):
    """Persona jurídica por la letra del NIF; sin NIF, solo si el nombre lleva la forma jurídica."""
    if nif:
        return nif[0] in LETRAS_SOCIEDAD
    return bool(FORMA_JURIDICA.search((nombre or "").upper()))


def sector_por_cpv(cpv):
    cpv = re.sub(r"\D", "", cpv or "")
    for pref, s in _POR_CPV:
        if cpv.startswith(pref):
            return s
    return ""


def sector_por_texto(texto):
    t = norm(texto)
    for s, rx in _POR_PALABRAS:
        if rx.search(t):
            return s
    return ""


def eur(x, dec=0):
    s = f"{x:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s + " €"


def num(x):
    return f"{x:,}".replace(",", ".")


def pct(a, b):
    return f"{(100 * a / b if b else 0):.0f} %"


def fecha_larga(d):
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def fecha_corta(iso):
    try:
        d = datetime.strptime(iso[:10], "%Y-%m-%d")
        return f"{d:%d/%m/%Y}"
    except ValueError:
        return iso


_RX_ORGANO = re.compile(r"^(junta de gobierno( local)?|pleno|alcald[ií]a(-presidencia)?|presidencia|concejal[ií]a[^,]*?|"
                        r"mesa de contrataci[oó]n|[oó]rgano de contrataci[oó]n|junta de contrataci[oó]n)\s+"
                        r"(del?|de la)\s+(?=ayuntamiento|excmo|ilmo)", re.I)


def organismo_corto(o):
    """"Junta de Gobierno Local del Ayuntamiento de Lorca (Murcia)" -> "Ayuntamiento de Lorca": agrupa los órganos de
    un mismo ayuntamiento (pleno, junta, alcaldía) en uno."""
    o = re.sub(r"\s+", " ", (o or "").strip())
    o2 = _RX_ORGANO.sub("", o)
    o2 = re.sub(r"^(Excmo\.?|Ilmo\.?)\s+", "", o2, flags=re.I)
    o2 = re.sub(r"\s*\((Murcia|Región de Murcia)\)$", "", o2, flags=re.I)
    o2 = ALIAS_ORGANISMO.get(o2.lower().rstrip(". "), o2)
    return o2[:1].upper() + o2[1:] if o2 else o


SIN_ADJUDICATARIO = {"", "NO LOCALIZADA", "NO LOCALIZADO", "DESIERTO", "DESIERTA", "SIN ADJUDICATARIO"}
# nombres largos que se repiten mucho en la Región de Murcia
ALIAS_ORGANISMO = {
    "gerencia de la empresa municipal de aguas y saneamiento de murcia s.a.": "Aguas de Murcia (EMUASA)",
    "intendente de cartagena": "Intendencia de Cartagena (Defensa)",
    "jefatura de la sección económico-administrativa 41 - base aérea de san javier":
        "Base Aérea de San Javier (Defensa)",
    "agencia de desarrollo local y empleo del ayuntamiento de cartagena": "ADLE (Ayuntamiento de Cartagena)",
    "dirección gerente de aguas de lorca, s.a": "Aguas de Lorca",
    "sociedadmercantil servicios comunitarios de molina, s.a": "Servicios Comunitarios de Molina (SERCOMOSA)",
}
ALIAS_ORGANISMO = {k.rstrip(". "): v for k, v in ALIAS_ORGANISMO.items()}


def plural(n, uno, varios):
    return f"{num(n)} {uno if n == 1 else varios}"


def nombre_provincia(p):
    return NOMBRE_PROVINCIA.get(p, (p or "").replace("_", " ").title())


def bonito(t, largo=None):
    """Mayúsculas de las fuentes -> texto normal; recorta con «…»."""
    t = re.sub(r"\s+", " ", (t or "").strip())
    if t.isupper() and len(t) > 6:
        t = t.capitalize()
    if largo and len(t) > largo:
        t = t[:largo - 1].rstrip(" ,.;-") + "…"
    return t


def nombre_empresa(t, largo=None):
    t = re.sub(r"\s+", " ", (t or "").strip()).rstrip(" ,")
    if largo and len(t) > largo:
        t = t[:largo - 1].rstrip(" ,.;-") + "…"
    return t


# ───────────────────────────── datos ─────────────────────────────

def cargar_contratos(db, provincia, desde, hasta):
    """Contratos formales (municipios.data) y menores (contratos_menors_locales) de una provincia, sin repetidos.
    Menor repetido entre fuentes (misma empresa, fecha e importe) = uno. NIF por nombre cuando la fuente no lo trae."""
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    regs = []
    for muni, data in c.execute("SELECT municipio, data FROM municipios WHERE provincia=?", (provincia,)):
        for x in json.loads(data).get("contratos", []):
            f = (x.get("fecha") or "")[:10]
            if not (desde <= f <= hasta):
                continue
            pf = "Persona f" in (x.get("cargo") or "")
            regs.append(dict(nombre=(x.get("empresa") or "").strip(), nif=nif_ok(x.get("nif")), persona_fisica=pf,
                             importe=float(x.get("importe_num") or 0), fecha=f,
                             organismo=organismo_corto(x.get("organo")) or muni.split("|")[0].title(),
                             cpv="", sector=sector_por_texto(x.get("titulo")) or "Otros", tipo="formal",
                             texto=(x.get("titulo") or "").strip(), exp=x.get("licitacion_id") or "",
                             municipio=muni.split("|")[0]))
    for nombre, nif, imp, fch, org, muni, cpv, desc in c.execute(
            "SELECT adjudicatari, nif, import_num, data_adjudicacio, organisme, municipio, codi_cpv, descripcio "
            "FROM contratos_menors_locales WHERE provincia=? AND data_adjudicacio >= ? AND data_adjudicacio <= ?",
            (provincia, desde, hasta + "T99")):
        cpv = re.sub(r"\D", "", cpv or "")
        regs.append(dict(nombre=(nombre or "").strip(), nif=nif_ok(nif), persona_fisica=False,
                         importe=float(imp or 0), fecha=(fch or "")[:10],
                         organismo=organismo_corto(org) or (muni or "").title(), cpv=cpv,
                         sector=sector_por_cpv(cpv) or sector_por_texto(desc) or "Otros", tipo="menor",
                         texto=(desc or "").strip(), exp="", municipio=(muni or "").split("|")[0]))
    c.close()
    # Un mismo expediente adjudicado a varias empresas con el MISMO importe (acuerdos marco, lotes sin desglose): la
    # fuente repite el total en cada una; se reparte a partes iguales para no contarlo varias veces.
    grupos = collections.defaultdict(list)
    for r in regs:
        if r["tipo"] == "formal" and r["exp"] and r["importe"] > 0:
            grupos[(r["organismo"], r["exp"], round(r["importe"]))].append(r)
    for g in grupos.values():
        if len({norm(r["nombre"]) for r in g}) > 1:
            for r in g:
                r["importe"] = r["importe"] / len(g)
                r["repartido"] = len(g)
    por_nombre = collections.defaultdict(collections.Counter)
    for r in regs:
        if r["nif"]:
            por_nombre[norm(r["nombre"])][r["nif"]] += 1
    for r in regs:
        if not r["nif"]:
            cand = por_nombre.get(norm(r["nombre"]))
            if cand:
                r["nif"] = cand.most_common(1)[0][0]
    vistos, unicos = set(), []
    for r in regs:
        if r["tipo"] == "menor" and r["importe"] > 0:
            k = (r["nif"] or norm(r["nombre"]), r["fecha"], round(r["importe"]))
            if k in vistos:
                continue
            vistos.add(k)
        r["sin_adjudicatario"] = not r["nif"] and norm(r["nombre"]) in SIN_ADJUDICATARIO
        r["sociedad"] = not r["persona_fisica"] and not r["sin_adjudicatario"] and es_sociedad(r["nif"], r["nombre"])
        unicos.append(r)
    return unicos


def cargar_licitaciones(zips, provincia, ahora):
    """Licitaciones de PLACE en plazo (estado PUB, fin de plazo posterior a `ahora`) de la provincia."""
    ultimas = {}
    for ruta in zips:
        with zipfile.ZipFile(ruta) as z:
            for nombre in sorted(x for x in z.namelist() if x.endswith(".atom")):
                raw = z.read(nombre)
                for e in LIC.entradas(raw):
                    r = LIC.analizar_entrada(e)
                    if r and (r["id"] not in ultimas or r["actualizado"] >= ultimas[r["id"]]["actualizado"]):
                        ultimas[r["id"]] = r
                for ref, cuando in LIC.borradas(raw):
                    if ref not in ultimas or cuando >= ultimas[ref]["actualizado"]:
                        ultimas[ref] = {"id": ref, "actualizado": cuando, "estado": "BORRADA"}
                del raw
    corte = ahora.strftime("%Y-%m-%d %H:%M")
    return [r for r in ultimas.values() if r.get("estado") in LIC.ESTADOS_ABIERTOS and r.get("provincia") == provincia
            and (r.get("fin_plazo") or "") >= corte]


def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def encaja(lic, sectores, prefijos_propios=()):
    cpvs = [re.sub(r"\D", "", c) for c in (lic.get("cpvs") or [lic.get("cpv") or ""]) if c]
    principal = re.sub(r"\D", "", lic.get("cpv") or "") or (cpvs[0] if cpvs else "")
    s_principal = sector_por_cpv(principal)
    if s_principal:      # manda el CPV principal: un suministro de electricidad no es «mantenimiento»
        return s_principal in sectores or bool(prefijos_propios) and principal.startswith(prefijos_propios)
    if any(sector_por_cpv(c) in sectores for c in cpvs):
        return True
    if prefijos_propios and any(c.startswith(p) for c in cpvs for p in prefijos_propios):
        return True
    return not cpvs and sector_por_texto(lic.get("titulo")) in sectores


def requisitos_txt(lic):
    req = lic.get("req") or {}
    partes = []
    if req.get("clas"):
        partes.append("Clasificación " + ", ".join(req["clas"][:3]))
    if req.get("umbral_eco"):
        partes.append("Solvencia ec. " + eur(_f(req["umbral_eco"])))
    if lic.get("lotes_detalle"):
        partes.append(f"{len(lic['lotes_detalle'])} lotes")
    if (lic.get("procedimiento") or "") == "9" or "simplificado" in (lic.get("procedimiento_txt") or "").lower():
        partes.append("Simplificado")
    return "; ".join(partes) or "Ver pliego"


# ───────────────────────────── análisis ─────────────────────────────

def analizar(contratos, licitaciones, sector=None, nif=None):
    """Devuelve un dict con todo lo que pinta el PDF."""
    empresa = None
    prefijos_propios = ()
    if nif:
        nif = nif_ok(nif)
        if not nif or nif[0] not in LETRAS_SOCIEDAD:
            raise SystemExit("Solo personas jurídicas (NIF que empiece por A, B, C, D, F, J, N o W).")
        propios = [r for r in contratos if r["nif"] == nif]
        if not propios:
            raise SystemExit(f"El NIF {nif} no tiene contratos en el periodo y la provincia.")
        cuenta = collections.Counter(r["sector"] for r in propios if r["sector"] != "Otros")
        if not cuenta:
            raise SystemExit("No se puede deducir el sector de sus contratos; use --sector.")
        if sector:           # el sector lo fija quien encarga el informe (el deducido puede ser demasiado amplio)
            if sector not in NOMBRES_SECTOR:
                raise SystemExit(f"Sector desconocido: {sector}. Use --sectores para ver la lista.")
            sectores = [sector]
        else:
            principal, n1 = cuenta.most_common(1)[0]
            sectores = [principal] + [s for s, n in cuenta.most_common(3)[1:] if n >= max(3, 0.25 * len(propios))]
        cpv4 = collections.Counter(r["cpv"][:4] for r in propios if len(r["cpv"]) >= 4)
        prefijos_propios = tuple(p for p, n in cpv4.most_common(5) if n >= 2)
        empresa = dict(nif=nif, nombre=collections.Counter(r["nombre"] for r in propios).most_common(1)[0][0],
                       contratos=sorted(propios, key=lambda r: r["fecha"], reverse=True))
    else:
        if sector not in NOMBRES_SECTOR:
            raise SystemExit(f"Sector desconocido: {sector}. Use --sectores para ver la lista.")
        sectores = [sector]
    del_sector = [r for r in contratos if r["sector"] in sectores]
    if empresa:      # sus contratos cuentan aunque alguno caiga en otro sector
        ids = {id(r) for r in del_sector}
        del_sector += [r for r in empresa["contratos"] if id(r) not in ids]
    abiertas = sorted((x for x in licitaciones if encaja(x, set(sectores), prefijos_propios)),
                      key=lambda x: x.get("fin_plazo") or "")

    # adjudicatarias: solo sociedades con nombre; el resto en una línea
    adj, otros, sin_adj = {}, dict(n=0, importe=0.0), dict(n=0, importe=0.0)
    for r in del_sector:
        if r["sin_adjudicatario"]:
            sin_adj["n"] += 1
            sin_adj["importe"] += r["importe"]
            continue
        if not r["sociedad"]:
            otros["n"] += 1
            otros["importe"] += r["importe"]
            continue
        k = r["nif"] or "SIN:" + norm(r["nombre"])
        a = adj.setdefault(k, dict(nif=r["nif"], nombres=collections.Counter(), n=0, importe=0.0,
                                   org=collections.Counter(), ultima=""))
        a["nombres"][r["nombre"]] += 1
        a["n"] += 1
        a["importe"] += r["importe"]
        a["org"][r["organismo"]] += 1
        a["ultima"] = max(a["ultima"], r["fecha"])
    ranking = sorted(adj.values(), key=lambda a: (-a["importe"], -a["n"]))
    for i, a in enumerate(ranking, 1):
        a["puesto"] = i
        a["nombre"] = a["nombres"].most_common(1)[0][0]
    ranking_n = sorted(adj.values(), key=lambda a: (-a["n"], -a["importe"]))

    org = {}
    for r in del_sector:
        o = org.setdefault(r["organismo"], dict(nombre=r["organismo"], n=0, importe=0.0, formales=0, menores=0,
                                                ultima="", empresas=set()))
        o["n"] += 1
        o["importe"] += r["importe"]
        o["formales" if r["tipo"] == "formal" else "menores"] += 1
        o["ultima"] = max(o["ultima"], r["fecha"])
        o["empresas"].add(r["nif"] or norm(r["nombre"]))
    organismos = sorted(org.values(), key=lambda o: (-o["importe"], -o["n"]))

    trimestres = collections.Counter()
    for r in del_sector:
        if r["fecha"][:4].isdigit():
            trimestres[f"{r['fecha'][:4]}-T{(int(r['fecha'][5:7]) - 1) // 3 + 1}"] += 1
    tramos = [("Hasta 15.000 €", 0, 15000), ("15.000 – 40.000 €", 15000, 40000), ("40.000 – 100.000 €", 40000, 100000),
              ("100.000 – 500.000 €", 100000, 500000), ("Más de 500.000 €", 500000, float("inf"))]
    con_importe = [r for r in del_sector if r["importe"] > 0]
    tamanos = [(t, sum(1 for r in con_importe if lo <= r["importe"] < hi),
                sum(r["importe"] for r in con_importe if lo <= r["importe"] < hi)) for t, lo, hi in tramos]
    # solo trimestres completos dentro de las fechas con datos (el primero y el último suelen ir a medias)
    fechas = sorted(r["fecha"][:10] for r in del_sector if r["fecha"][:4].isdigit())
    tri = []
    for k, v in sorted(trimestres.items()):
        a, t = int(k[:4]), int(k[-1])
        ini_t = f"{a}-{3 * t - 2:02d}-01"
        fin_t = f"{a}-{3 * t:02d}-{'31' if t in (1, 4) else '30'}"
        if fechas and ini_t >= fechas[0] and fin_t <= fechas[-1]:
            tri.append((k, v))
    return dict(sectores=sectores, empresa=empresa, contratos=del_sector, abiertas=abiertas, ranking=ranking,
                ranking_n=ranking_n, otros=otros, sin_adj=sin_adj, organismos=organismos, trimestres=tri,
                tamanos=tamanos, importe=sum(r["importe"] for r in del_sector),
                n_formales=sum(1 for r in del_sector if r["tipo"] == "formal"),
                n_menores=sum(1 for r in del_sector if r["tipo"] == "menor"),
                prefijos_propios=prefijos_propios)


# ───────────────────────────── PDF ─────────────────────────────

# Recuadro final de contacto. El teléfono NO se escribe aquí (el repositorio es público): se pasa con --contacto-tel o
# la variable INFORME_CONTACTO_TEL al generar el PDF. Correo y web son los públicos de la web.
CONTACTO_EMAIL = os.environ.get("INFORME_CONTACTO_EMAIL", "contacto@dinero-publico.com")
CONTACTO_WEB = os.environ.get("INFORME_CONTACTO_WEB", "dinero-publico.com")
CONTACTO_TEL = os.environ.get("INFORME_CONTACTO_TEL", "")


def informe_pdf(ruta, A, provincia, desde, hasta, ahora, titulo=None, muestra=True, max_paginas=5, contacto=None):
    """contacto: dict con tel, email y web (por defecto, CONTACTO_*). Sin ninguno de los tres, no hay recuadro."""
    from reportlab.graphics.shapes import Drawing, Line, Rect, String
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (CondPageBreak, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,
                                    TableStyle)

    fuente, negrita, cursiva = "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"
    d = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    rutas = {"Arial": "arial.ttf", "Arial-Bold": "arialbd.ttf", "Arial-Italic": "ariali.ttf"}
    if all(os.path.exists(os.path.join(d, f)) for f in rutas.values()):
        for n, f in rutas.items():
            pdfmetrics.registerFont(TTFont(n, os.path.join(d, f)))
        fuente, negrita, cursiva = "Arial", "Arial-Bold", "Arial-Italic"

    NEGRO, GRIS, GRIS_C, GRIS_F = colors.black, colors.Color(.35, .35, .35), colors.Color(.82, .82, .82), \
        colors.Color(.94, .94, .94)
    st = {
        "marca": ParagraphStyle("marca", fontName=negrita, fontSize=9, leading=11, textColor=GRIS),
        "h0": ParagraphStyle("h0", fontName=negrita, fontSize=21, leading=25, spaceAfter=4),
        "sub": ParagraphStyle("sub", fontName=fuente, fontSize=10.5, leading=14, textColor=GRIS, spaceAfter=10),
        "h1": ParagraphStyle("h1", fontName=negrita, fontSize=13, leading=16, spaceBefore=12, spaceAfter=5),
        "p": ParagraphStyle("p", fontName=fuente, fontSize=9.5, leading=13, spaceAfter=5),
        "pc": ParagraphStyle("pc", fontName=fuente, fontSize=8.5, leading=11, textColor=GRIS, spaceAfter=4),
        "td": ParagraphStyle("td", fontName=fuente, fontSize=8, leading=10),
        "tdb": ParagraphStyle("tdb", fontName=negrita, fontSize=8, leading=10),
        "tdr": ParagraphStyle("tdr", fontName=fuente, fontSize=8, leading=10, alignment=TA_RIGHT),
        "tdrb": ParagraphStyle("tdrb", fontName=negrita, fontSize=8, leading=10, alignment=TA_RIGHT),
        "th": ParagraphStyle("th", fontName=negrita, fontSize=7.5, leading=9, textColor=NEGRO),
        "thr": ParagraphStyle("thr", fontName=negrita, fontSize=7.5, leading=9, alignment=TA_RIGHT),
        "kn": ParagraphStyle("kn", fontName=negrita, fontSize=16, leading=19),
        "kt": ParagraphStyle("kt", fontName=fuente, fontSize=8, leading=10, textColor=GRIS),
        "h1c": ParagraphStyle("h1c", fontName=negrita, fontSize=13, leading=16, spaceAfter=3),
        "pcont": ParagraphStyle("pcont", fontName=fuente, fontSize=10, leading=14),
        "li": ParagraphStyle("li", fontName=fuente, fontSize=9.5, leading=13, leftIndent=12, bulletIndent=2,
                             spaceAfter=3),
    }
    P = lambda t, s="td": Paragraph(t, st[s])        # noqa: E731
    datos_contacto = {k: v for k, v in (contacto if contacto is not None else
                                        {"tel": CONTACTO_TEL, "email": CONTACTO_EMAIL, "web": CONTACTO_WEB}).items()
                      if (v or "").strip()}
    E = escape
    ancho = A4[0] - 3.6 * cm
    lugar = nombre_provincia(provincia)
    periodo = f"del {fecha_corta(desde)} al {fecha_corta(hasta)}"
    emp = A["empresa"]
    if not titulo:
        titulo = (nombre_empresa(emp["nombre"]) if emp else f"{A['sectores'][0]} en la {lugar}"
                  if lugar.startswith("Región") else f"{A['sectores'][0]} en {lugar}")

    def tabla(filas, anchos, cabecera=True, resaltar=()):
        t = Table(filas, colWidths=anchos, repeatRows=1 if cabecera else 0)
        estilo = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                  ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5), ("LEFTPADDING", (0, 0), (-1, -1), 3),
                  ("RIGHTPADDING", (0, 0), (-1, -1), 3), ("LINEBELOW", (0, 1), (-1, -1), 0.25, GRIS_C)]
        if cabecera:
            estilo += [("LINEABOVE", (0, 0), (-1, 0), 1, NEGRO), ("LINEBELOW", (0, 0), (-1, 0), 0.75, NEGRO)]
        for i in resaltar:
            estilo += [("BACKGROUND", (0, i), (-1, i), GRIS_F), ("LINEABOVE", (0, i), (-1, i), 0.75, NEGRO),
                       ("LINEBELOW", (0, i), (-1, i), 0.75, NEGRO)]
        t.setStyle(TableStyle(estilo))
        return t

    def kpis(celdas):
        filas = [[[P(n, "kn"), P(t, "kt")] for n, t in celdas]]
        t = Table(filas, colWidths=[ancho / len(celdas)] * len(celdas))
        t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.75, NEGRO), ("INNERGRID", (0, 0), (-1, -1), 0.5, GRIS_C),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 6),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 7), ("LEFTPADDING", (0, 0), (-1, -1), 7)]))
        return t

    def barras(datos, alto=3.4 * cm, etiqueta_y="contratos"):
        """Columnas grises finas, una serie; etiqueta de valor solo en el máximo y en el último trimestre."""
        dw = Drawing(ancho, alto + 0.9 * cm)
        if not datos:
            return dw
        mx = max(v for _, v in datos) or 1
        izq, base = 0.9 * cm, 0.6 * cm
        hueco = (ancho - izq) / len(datos)
        bw = min(hueco * 0.55, 1.1 * cm)
        for k in (0.5, 1.0):
            y = base + alto * k
            dw.add(Line(izq, y, ancho, y, strokeColor=GRIS_C, strokeWidth=0.4))
            dw.add(String(izq - 3, y - 3, num(round(mx * k)), fontName=fuente, fontSize=6.5, fillColor=GRIS,
                          textAnchor="end"))
        dw.add(Line(izq, base, ancho, base, strokeColor=NEGRO, strokeWidth=0.6))
        i_max = max(range(len(datos)), key=lambda i: datos[i][1])
        for i, (et, v) in enumerate(datos):
            x = izq + i * hueco + (hueco - bw) / 2
            h = alto * v / mx
            dw.add(Rect(x, base, bw, h, fillColor=colors.Color(.45, .45, .45), strokeColor=None))
            dw.add(String(x + bw / 2, base - 9, et.replace("-T", " T"), fontName=fuente, fontSize=6.5,
                          fillColor=GRIS, textAnchor="middle"))
            if i in (i_max, len(datos) - 1):
                dw.add(String(x + bw / 2, base + h + 2.5, num(v), fontName=negrita, fontSize=7, fillColor=NEGRO,
                              textAnchor="middle"))
        return dw

    def pie(canvas, doc):
        canvas.saveState()
        canvas.setFont(fuente, 7.5)
        canvas.setFillColor(GRIS)
        canvas.drawString(1.8 * cm, 1.1 * cm, f"Dinero Público · Informe de mercado público · {titulo[:70]}")
        canvas.drawRightString(A4[0] - 1.8 * cm, 1.1 * cm, f"Página {doc.page}")
        canvas.setStrokeColor(GRIS_C)
        canvas.setLineWidth(0.5)
        canvas.line(1.8 * cm, 1.45 * cm, A4[0] - 1.8 * cm, 1.45 * cm)
        if muestra:
            canvas.setFont(negrita, 7.5)
            canvas.drawRightString(A4[0] - 1.8 * cm, A4[1] - 1.1 * cm, "INFORME DE MUESTRA")
        canvas.restoreState()

    def construir(n_lic, n_comp, n_org, n_propios):
        h = []
        h.append(P("DINERO PÚBLICO · INFORME DE MERCADO PÚBLICO", "marca"))
        h.append(Spacer(1, 4))
        h.append(P(E(titulo), "h0"))
        if emp:
            sub = (f"NIF {emp['nif']} · Sector{'es' if len(A['sectores']) > 1 else ''}: "
                   f"{E(', '.join(A['sectores']))} · {E(lugar)}")
        else:
            sub = f"Sector: {E(A['sectores'][0])} · {E(lugar)}"
        h.append(P(f"{sub}<br/>Contratos adjudicados {periodo} · Licitaciones abiertas a {fecha_larga(ahora)}",
                   "sub"))
        ab = A["abiertas"]
        imp_ab = sum(_f(x.get("presupuesto")) for x in ab)
        h.append(kpis([
            (num(len(ab)), f"licitaciones abiertas que encajan<br/>{eur(imp_ab)} sin IVA en juego"),
            (num(len(A["contratos"])), f"contratos adjudicados en 2 años<br/>{eur(A['importe'])}"),
            (num(len(A["ranking"])), "empresas adjudicatarias distintas<br/>(sociedades)"),
            (num(len(A["organismos"])), "organismos que han<br/>contratado en el sector"),
        ]))
        h.append(Spacer(1, 8))
        h.append(P("Lo más importante", "h1"))
        claves = []
        if ab:
            x = ab[0]
            claves.append(f"La próxima licitación que cierra es «{E(bonito(x.get('titulo'), 90))}» "
                          f"({E(bonito(x.get('organo'), 60))}), el {fecha_corta(x['fin_plazo'])}.")
        else:
            claves.append("Hoy no hay licitaciones abiertas en PLACE que encajen; el servicio de alertas avisa en "
                          "cuanto se publique una.")
        if emp:
            pos = next((a for a in A["ranking"] if a["nif"] == emp["nif"]), None)
            imp_e = sum(r["importe"] for r in emp["contratos"])
            if pos:
                claves.append(f"{E(nombre_empresa(emp['nombre']))} ha ganado {num(len(emp['contratos']))} contratos "
                              f"por {eur(imp_e)}: es la n.º {pos['puesto']} de {num(len(A['ranking']))} sociedades "
                              f"del sector por importe en la {E(lugar)}." if lugar.startswith("Región") else
                              f"{E(nombre_empresa(emp['nombre']))} ha ganado {num(len(emp['contratos']))} contratos "
                              f"por {eur(imp_e)}: puesto {pos['puesto']} de {num(len(A['ranking']))}.")
        top5 = sum(a["importe"] for a in A["ranking"][:5])
        if A["importe"] > 0 and A["ranking"]:
            claves.append(f"Las 5 primeras sociedades se llevan el {pct(top5, A['importe'])} del importe adjudicado "
                          f"en el sector.")
        if A["organismos"]:
            o = A["organismos"][0]
            claves.append(f"El organismo que más importe adjudica es {E(bonito(o['nombre'], 120))}: "
                          f"{plural(o['n'], 'contrato', 'contratos')} por {eur(o['importe'])}.")
            o2 = max(A["organismos"], key=lambda o: o["n"])
            if o2 is not o:
                claves.append(f"El que más contratos firma es {E(bonito(o2['nombre'], 80))}: "
                              f"{plural(o2['n'], 'contrato', 'contratos')} con "
                              f"{plural(len(o2['empresas']), 'empresa distinta', 'empresas distintas')}.")
        tot = A["n_formales"] + A["n_menores"]
        if tot:
            claves.append(f"El {pct(A['n_menores'], tot)} de los contratos son menores (adjudicación directa, sin "
                          f"licitación abierta): conviene darse a conocer en los organismos que más compran.")
        for c in claves:
            h.append(Paragraph(c, st["li"], bulletText="•"))

        # 1. licitaciones abiertas
        h.append(P("1. Licitaciones abiertas que le encajan", "h1"))
        if ab:
            h.append(P(f"Publicadas en la Plataforma de Contratación del Sector Público con el plazo abierto hoy, en la "
                       f"{E(lugar)}, del sector{'es' if len(A['sectores']) > 1 else ''} "
                       f"{E(', '.join(A['sectores']))}. Ordenadas por fecha de cierre. Importe de licitación sin IVA.",
                       "pc"))
            filas = [[P("Cierra", "th"), P("Objeto y organismo", "th"), P("Importe", "thr"), P("Requisitos", "th")]]
            for x in ab[:n_lic]:
                url = (x.get("url") or "").replace("&amp;", "&")
                obj = f"<b>{E(bonito(x.get('titulo'), 120))}</b><br/>{E(bonito(x.get('organo'), 80))}"
                if url:
                    obj += f' · <link href="{E(url)}"><u>ver anuncio</u></link>'
                filas.append([P(fecha_corta(x["fin_plazo"]) + "<br/>" + x["fin_plazo"][11:16]), P(obj),
                              P(eur(_f(x.get("presupuesto"))) if _f(x.get("presupuesto")) else "Sin importe", "tdr"), P(E(requisitos_txt(x)))])
            h.append(tabla(filas, [1.7 * cm, ancho - 7.4 * cm, 2.4 * cm, 3.3 * cm]))
            if len(ab) > n_lic:
                h.append(P(f"Y {len(ab) - n_lic} más. El servicio completo las envía todas por correo, con aviso de las "
                           f"nuevas.", "pc"))
        else:
            h.append(P("No hay licitaciones abiertas que encajen en este momento.", "p"))

        # 2. contratos de la empresa
        if emp:
            h.append(CondPageBreak(6 * cm))
            h.append(P(f"2. Contratos ganados por {E(nombre_empresa(emp['nombre']))}", "h1"))
            cs = emp["contratos"]
            orgs = collections.Counter(r["organismo"] for r in cs)
            h.append(P(f"{num(len(cs))} contratos {periodo} por {eur(sum(r['importe'] for r in cs))} "
                       f"({sum(1 for r in cs if r['tipo'] == 'formal')} formales y "
                       f"{sum(1 for r in cs if r['tipo'] == 'menor')} menores). Clientes principales: "
                       + "; ".join(f"{E(bonito(o, 60))} ({n})" for o, n in orgs.most_common(3)) + ".", "p"))
            filas = [[P("Fecha", "th"), P("Objeto", "th"), P("Organismo", "th"), P("Tipo", "th"),
                      P("Importe", "thr")]]
            for r in sorted(cs, key=lambda r: -r["importe"])[:n_propios]:
                filas.append([P(fecha_corta(r["fecha"])), P(E(bonito(r["texto"], 95))),
                              P(E(bonito(r["organismo"], 45))), P("Formal" if r["tipo"] == "formal" else "Menor"),
                              P(eur(r["importe"]) if r["importe"] else "s/d", "tdr")])
            h.append(tabla(filas, [1.7 * cm, ancho - 9.6 * cm, 4.4 * cm, 1.2 * cm, 2.3 * cm]))
            h.append(P(f"Los {min(n_propios, len(cs))} de mayor importe.", "pc"))

        # 3. competidores
        n_sec = 3 if emp else 2
        h.append(CondPageBreak(7 * cm))
        h.append(P(f"{n_sec}. {'Sus competidores' if emp else 'Quién gana en el sector'}: principales adjudicatarias",
                   "h1"))
        h.append(P(f"Sociedades que más importe han ganado en el sector en la {E(lugar)} {periodo}. "
                   f"Cuota = parte del importe adjudicado en el sector.", "pc"))
        filas = [[P("#", "th"), P("Empresa", "th"), P("NIF", "th"), P("Contratos", "thr"), P("Importe", "thr"),
                  P("Cuota", "thr"), P("Organismo principal", "th")]]
        resaltar = []
        lista = A["ranking"][:n_comp]
        if emp and not any(a["nif"] == emp["nif"] for a in lista):
            lista = lista + [a for a in A["ranking"] if a["nif"] == emp["nif"]]
        for a in lista:
            yo = emp and a["nif"] == emp["nif"]
            s = "tdb" if yo else "td"
            filas.append([P(str(a["puesto"]), s), P(E(nombre_empresa(a["nombre"], 48)), s), P(a["nif"] or "—", s),
                          P(num(a["n"]), "tdrb" if yo else "tdr"), P(eur(a["importe"]), "tdrb" if yo else "tdr"),
                          P(pct(a["importe"], A["importe"]), "tdrb" if yo else "tdr"),
                          P(E(bonito(a["org"].most_common(1)[0][0], 40)), s)])
            if yo:
                resaltar.append(len(filas) - 1)
        if A["otros"]["n"]:
            filas.append([P(""), P("<i>Autónomos y personas físicas (no se identifican)</i>"), P(""),
                          P(num(A["otros"]["n"]), "tdr"), P(eur(A["otros"]["importe"]), "tdr"),
                          P(pct(A["otros"]["importe"], A["importe"]), "tdr"), P("")])
        if A["sin_adj"]["n"]:
            filas.append([P(""), P("<i>Adjudicatario no publicado por la fuente</i>"), P(""),
                          P(num(A["sin_adj"]["n"]), "tdr"), P(eur(A["sin_adj"]["importe"]), "tdr"),
                          P(pct(A["sin_adj"]["importe"], A["importe"]), "tdr"), P("")])
        h.append(tabla(filas, [0.7 * cm, ancho - 13.0 * cm, 1.9 * cm, 1.5 * cm, 2.5 * cm, 1.3 * cm, 5.1 * cm],
                       resaltar=resaltar))
        mas = A["ranking_n"][:3]
        if mas:
            h.append(P("Las que más contratos firman (más presencia, aunque sean pequeños): "
                       + "; ".join(f"{E(nombre_empresa(a['nombre'], 40))} ({num(a['n'])})" for a in mas) + ".", "pc"))

        # 4. organismos
        h.append(CondPageBreak(7 * cm))
        h.append(P(f"{n_sec + 1}. Organismos que más contratan en el sector", "h1"))
        filas = [[P("Organismo", "th"), P("Contratos", "thr"), P("Importe", "thr"), P("Formales / menores", "thr"),
                  P("Empresas", "thr"), P("Último", "th")]]
        for o in A["organismos"][:n_org]:
            filas.append([P(E(bonito(o["nombre"], 70))), P(num(o["n"]), "tdr"), P(eur(o["importe"]), "tdr"),
                          P(f"{o['formales']} / {o['menores']}", "tdr"), P(num(len(o["empresas"])), "tdr"),
                          P(fecha_corta(o["ultima"]))])
        h.append(tabla(filas, [ancho - 10.4 * cm, 1.6 * cm, 2.6 * cm, 2.5 * cm, 1.7 * cm, 2.0 * cm]))
        h.append(P("«Empresas» = adjudicatarias distintas de ese organismo en el sector (cuantas menos, más difícil "
                   "entrar; cuantas más, más abierto).", "pc"))

        # 5. cuándo y cuánto
        bloque = [P(f"{n_sec + 2}. Cuándo y de qué tamaño se contrata", "h1"),
                  P("Contratos adjudicados por trimestre (solo trimestres completos)", "tdb"), Spacer(1, 2), barras(A["trimestres"]),
                  P("El último trimestre puede salir bajo: algunas fuentes publican los contratos con semanas de "
                    "retraso.", "pc")]
        filas = [[P("Tamaño del contrato", "th"), P("Contratos", "thr"), P("% contratos", "thr"), P("Importe", "thr"),
                  P("% importe", "thr")]]
        n_ci = sum(n for _, n, _ in A["tamanos"]) or 1
        i_ci = sum(i for _, _, i in A["tamanos"]) or 1
        for t, n, i in A["tamanos"]:
            filas.append([P(t), P(num(n), "tdr"), P(pct(n, n_ci), "tdr"), P(eur(i), "tdr"), P(pct(i, i_ci), "tdr")])
        bloque += [Spacer(1, 6), tabla(filas, [ancho - 10 * cm, 2.5 * cm, 2.5 * cm, 2.5 * cm, 2.5 * cm])]
        h.append(KeepTogether(bloque))

        # método y servicio
        h.append(CondPageBreak(8 * cm))
        h.append(P("Qué incluye el servicio", "h1"))
        for t in ("<b>Alertas de licitaciones</b>: cada semana, las licitaciones nuevas que encajan con su empresa "
                  "(sector, provincias, tamaño, clasificación), separadas en «puede optar», «revise el pliego» y "
                  "«solo en UTE».",
                  "<b>Informe a medida</b> como este, con su empresa, sus competidores y los organismos que le "
                  "interesan, actualizado cuando lo necesite.",
                  "<b>Seguimiento de competidores y organismos</b>: qué ganan, cuándo y por cuánto."):
            h.append(Paragraph(t, st["li"], bulletText="•"))
        h.append(P("Cómo se ha hecho", "h1"))
        h.append(P(
            "Fuentes públicas: Plataforma de Contratación del Sector Público (licitaciones y contratos formales), "
            "Boletín Oficial de la Región de Murcia y los contratos menores que publican los ayuntamientos y la propia "
            "Plataforma. Contratos: los que Dinero Público tiene de organismos de la provincia "
            f"{periodo}; un contrato menor publicado en dos fuentes cuenta una vez. Importes: el adjudicado que "
            "publica cada fuente (con o sin IVA según la fuente); algunos menores se publican sin importe; si un mismo "
            "expediente figura con el mismo importe para varias empresas (acuerdos marco), se reparte entre ellas. "
            "El sector "
            "sale del código CPV y, si no lo hay, del objeto del contrato. Licitaciones abiertas: las publicadas en "
            "la Plataforma con el plazo abierto en la fecha del informe (no incluye las que un organismo publique "
            "solo en su propio perfil). Solo se identifican personas jurídicas; los contratos de autónomos y "
            "personas físicas se cuentan sin nombre. Compruebe siempre los pliegos en el anuncio oficial antes de "
            "presentarse.", "pc"))
        h.append(P(f"Elaborado por Dinero Público el {fecha_larga(ahora)}.", "pc"))
        if datos_contacto:
            h.append(Spacer(1, 10))
            h.append(recuadro_contacto())
        return h

    def recuadro_contacto():
        """«¿Quiere este informe para su empresa?»: borde negro, sin color, sin precios. No se parte entre páginas."""
        lineas = []
        if datos_contacto.get("tel"):
            lineas.append(f"Teléfono: <b>{E(datos_contacto['tel'])}</b>")
        if datos_contacto.get("email"):
            mail = E(datos_contacto["email"])
            lineas.append(f'Correo: <b><link href="mailto:{mail}">{mail}</link></b>')
        if datos_contacto.get("web"):
            web = E(datos_contacto["web"])
            url = web if web.startswith("http") else "https://" + web
            lineas.append(f'Web: <b><link href="{url}">{web}</link></b>')
        celda = [P("¿Quiere este informe para su empresa?", "h1c"),
                 P("Lo preparamos con sus datos, sus competidores y los organismos que le interesan.", "p"),
                 P(" · ".join(lineas), "pcont")]
        t = Table([[celda]], colWidths=[ancho])
        t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1.2, NEGRO), ("BACKGROUND", (0, 0), (-1, -1), GRIS_F),
                               ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                               ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10)]))
        return KeepTogether([t])

    import io

    class Doc(SimpleDocTemplate):
        paginas = 0

        def afterPage(self):
            Doc.paginas = self.page

    # se recorta de menos importante a más hasta caber en max_paginas
    n_lic, n_comp, n_org, n_propios = 15, 12, 10, 10
    while True:
        buf = io.BytesIO()
        doc = Doc(buf, pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=1.6 * cm,
                  bottomMargin=1.8 * cm, title=f"Informe de mercado público - {titulo}", author="Dinero Público")
        doc.build(construir(n_lic, n_comp, n_org, n_propios), onFirstPage=pie, onLaterPages=pie)
        if Doc.paginas <= max_paginas or n_lic <= 6:
            break
        n_lic, n_comp, n_org, n_propios = n_lic - 3, max(8, n_comp - 1), max(6, n_org - 1), max(6, n_propios - 1)
    with open(ruta, "wb") as f:
        f.write(buf.getvalue())
    return Doc.paginas, min(n_lic, len(A["abiertas"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db")
    ap.add_argument("--zip", action="append", default=[])
    ap.add_argument("--nif")
    ap.add_argument("--sector")
    ap.add_argument("--provincia", default="murcia")
    ap.add_argument("--desde")
    ap.add_argument("--hasta", help="último día de contratos (por defecto, el día de la copia o hoy)")
    ap.add_argument("--salida")
    ap.add_argument("--titulo")
    ap.add_argument("--contacto-tel", default=CONTACTO_TEL, help="teléfono del recuadro final (no se guarda en el repo)")
    ap.add_argument("--contacto-email", default=CONTACTO_EMAIL)
    ap.add_argument("--contacto-web", default=CONTACTO_WEB)
    ap.add_argument("--sectores", action="store_true")
    a = ap.parse_args(argv)
    if a.sectores:
        print("\n".join(NOMBRES_SECTOR))
        return
    if not (a.db and a.salida and (a.nif or a.sector)):
        ap.error("hacen falta --db, --salida y --nif o --sector")
    ahora = datetime.now()
    hasta = a.hasta or date.fromtimestamp(os.path.getmtime(a.db)).isoformat()
    desde = a.desde or f"{int(hasta[:4]) - 2}{hasta[4:]}"
    contratos = cargar_contratos(a.db, a.provincia, desde, hasta)
    lic = cargar_licitaciones(a.zip, a.provincia, ahora) if a.zip else []
    A = analizar(contratos, lic, sector=a.sector, nif=a.nif)   # con --nif, --sector fija el sector
    paginas, mostradas = informe_pdf(a.salida, A, a.provincia, desde, hasta, ahora, titulo=a.titulo,
                                     contacto={"tel": a.contacto_tel, "email": a.contacto_email,
                                               "web": a.contacto_web})
    print(f"{a.salida}: {paginas} páginas; {len(A['abiertas'])} licitaciones abiertas ({mostradas} en el PDF); "
          f"{len(A['contratos'])} contratos; {len(A['ranking'])} sociedades; sectores {A['sectores']}")


if __name__ == "__main__":
    main()
