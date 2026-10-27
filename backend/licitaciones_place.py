# encoding: utf-8
"""
Licitaciones de PLACE (sindicacion_643, el mismo feed del que salen los contratos del Índice) para la sección
"Convocatorias abiertas" (decisión de César 2026-10-04, ver INFORME_LICITACIONES_SUBVENCIONES.md).

Funciones puras, sin estado ni base de datos: analizar una <entry> CODICE, recorrer las de un .atom y sus
<at:deleted-entry>, y el enlace a la página anterior del Atom. La ingesta (tabla `licitaciones`, hilo de fondo) vive en
app.py.

Reglas (decididas por César):
- "Vigente" la decide la FECHA FIN de presentación de ofertas, nunca el estado de PLACE (medido el 04-10: dos tercios
  de las licitaciones que PLACE sigue marcando PUB ya tienen el plazo vencido). El estado solo sirve para descartar las
  que ya pasaron a evaluación, adjudicación, resolución o anulación (una versión posterior de la misma entrada).
- Sin anuncios previos (PRE) en esta primera versión.
"""
import html
import json
import re

_RE_ENTRY = re.compile(rb"<entry\b.*?</entry>", re.S)
_RE_BORRADA = re.compile(rb'<at:deleted-entry\b[^>]*?ref="([^"]+)"[^>]*?when="([^"]+)"', re.S)
_RE_SIGUIENTE = re.compile(rb'<link\b[^>]*href="([^"]+)"[^>]*rel="next"', re.S)

ESTADOS_ABIERTOS = {"PUB"}

# Tipo de contrato (ContractCode de CODICE)
TIPOS = {"1": "Suministros", "2": "Servicios", "3": "Obras", "7": "Administrativo especial", "8": "Privado",
         "21": "Gestión de servicios públicos", "22": "Concesión de servicios", "31": "Concesión de obras públicas",
         "32": "Concesión de obras", "40": "Colaboración público-privada", "50": "Patrimonial", "999": "Otros"}
TIPOS_FILTRO = {"obras": {"3", "31", "32"}, "servicios": {"2", "21", "22"}, "suministros": {"1"}}

# Procedimiento (TenderingProcess/ProcedureCode)
PROCEDIMIENTOS = {"1": "Abierto", "2": "Restringido", "3": "Negociado sin publicidad", "4": "Negociado con publicidad",
                  "5": "Diálogo competitivo", "6": "Contrato menor", "7": "Derivado de acuerdo marco",
                  "8": "Concurso de proyectos", "9": "Abierto simplificado", "10": "Asociación para la innovación",
                  "11": "Derivado de asociación para la innovación", "12": "Basado en sistema dinámico",
                  "13": "Licitación con negociación", "100": "Normas internas", "999": "Otros"}

# Divisiones CPV (2 primeras cifras) con nombre corto, para el filtro por sector
CPV_DIVISIONES = {
    "03": "Agricultura y ganadería", "09": "Combustibles y energía", "14": "Minería", "15": "Alimentación y bebidas",
    "16": "Maquinaria agrícola", "18": "Ropa y calzado", "19": "Cuero y textil", "22": "Impresos y publicaciones",
    "24": "Productos químicos", "30": "Equipos de oficina e informáticos", "31": "Material eléctrico",
    "32": "Radio, televisión y telecomunicaciones", "33": "Material médico y farmacéutico",
    "34": "Vehículos y transporte", "35": "Seguridad y defensa", "37": "Instrumentos musicales y deporte",
    "38": "Laboratorio y precisión", "39": "Mobiliario y limpieza", "41": "Agua", "42": "Maquinaria industrial",
    "43": "Maquinaria de minería y construcción", "44": "Materiales de construcción", "45": "Obras de construcción",
    "48": "Software", "50": "Reparación y mantenimiento", "51": "Instalación", "55": "Hostelería y restauración",
    "60": "Transporte", "63": "Servicios de transporte auxiliares", "64": "Correos y telecomunicaciones",
    "65": "Suministros públicos", "66": "Financieros y seguros", "70": "Inmobiliarios", "71": "Arquitectura e ingeniería",
    "72": "Servicios informáticos", "73": "Investigación y desarrollo", "75": "Administración pública",
    "76": "Servicios petrolíferos", "77": "Agricultura, jardinería y forestales", "79": "Servicios a empresas",
    "80": "Educación y formación", "85": "Salud y servicios sociales", "90": "Limpieza, residuos y medio ambiente",
    "92": "Cultura, ocio y deporte", "98": "Otros servicios comunitarios",
}

# NUTS3 (y NUTS2 de comunidades uniprovinciales) -> clave de provincia de la app (MUNICIPIOS_POR_PROVINCIA)
NUTS_PROVINCIA = {
    "ES111": "a_coruna", "ES112": "lugo", "ES113": "ourense", "ES114": "pontevedra", "ES120": "asturias",
    "ES130": "cantabria", "ES211": "pais_vasco", "ES212": "pais_vasco", "ES213": "pais_vasco", "ES220": "navarra",
    "ES230": "la_rioja", "ES241": "huesca", "ES242": "teruel", "ES243": "zaragoza", "ES300": "madrid",
    "ES411": "avila", "ES412": "burgos", "ES413": "leon", "ES414": "palencia", "ES415": "salamanca",
    "ES416": "segovia", "ES417": "soria", "ES418": "valladolid", "ES419": "zamora", "ES421": "albacete",
    "ES422": "ciudad_real", "ES423": "cuenca", "ES424": "guadalajara", "ES425": "toledo", "ES431": "badajoz",
    "ES432": "caceres", "ES511": "barcelona", "ES512": "girona", "ES513": "lleida", "ES514": "tarragona",
    "ES521": "alicante", "ES522": "castellon", "ES523": "valencia", "ES531": "baleares", "ES532": "baleares",
    "ES533": "baleares", "ES611": "almeria", "ES612": "cadiz", "ES613": "cordoba", "ES614": "granada",
    "ES615": "huelva", "ES616": "jaen", "ES617": "malaga", "ES618": "sevilla", "ES620": "murcia", "ES630": "ceuta",
    "ES640": "melilla", "ES703": "santa_cruz_tenerife", "ES704": "las_palmas", "ES705": "las_palmas",
    "ES706": "santa_cruz_tenerife", "ES707": "santa_cruz_tenerife", "ES708": "las_palmas",
    "ES709": "santa_cruz_tenerife",
    # comunidades uniprovinciales que a veces vienen solo a nivel NUTS2
    "ES12": "asturias", "ES13": "cantabria", "ES22": "navarra", "ES23": "la_rioja", "ES30": "madrid",
    "ES53": "baleares", "ES62": "murcia", "ES63": "ceuta", "ES64": "melilla",
}
# NUTS2 -> comunidad autónoma de la app (COMUNIDAD_AUTONOMA_LABEL), para lo que solo trae la región
NUTS_COMUNIDAD = {
    "ES11": "galicia", "ES12": "asturias", "ES13": "cantabria", "ES21": "pais_vasco", "ES22": "navarra",
    "ES23": "la_rioja", "ES24": "aragon", "ES30": "madrid", "ES41": "castilla_y_leon", "ES42": "castilla_la_mancha",
    "ES43": "extremadura", "ES51": "cataluna", "ES52": "valenciana", "ES53": "baleares", "ES61": "andalucia",
    "ES62": "murcia", "ES63": "ceuta", "ES64": "melilla", "ES70": "canarias",
}


def provincia_de_nuts(nuts):
    nuts = (nuts or "").strip().upper()
    return NUTS_PROVINCIA.get(nuts[:5]) or NUTS_PROVINCIA.get(nuts[:4]) or ""


def comunidad_de_nuts(nuts):
    return NUTS_COMUNIDAD.get((nuts or "").strip().upper()[:4], "")


def _tag(nombre, x):
    m = re.search(r"<(?:[\w-]+:)?" + nombre + r"\b[^>]*>([^<]*)</", x)
    return html.unescape(m.group(1).strip()) if m else ""


def _bloque(nombre, x):
    m = re.search(r"<(?:[\w-]+:)?" + nombre + r"\b[^>]*>(.*?)</(?:[\w-]+:)?" + nombre + r">", x, re.S)
    return m.group(1) if m else ""


def _importe(txt):
    try:
        v = float(txt.replace(",", "."))
        return v if v > 0 else None
    except ValueError:
        return None


def _ambito(lcp):
    """estatal / autonomico / local / otros, por la cadena ParentLocatedParty del órgano de contratación."""
    nombres = " | ".join(re.findall(r"<cbc:Name>([^<]*)</cbc:Name>", lcp)).upper()
    if "ENTIDADES LOCALES" in nombres:
        return "local"
    if "COMUNIDADES Y CIUDADES AUT" in nombres or "COMUNIDADES AUT" in nombres:
        return "autonomico"
    if "ADMINISTRACI" in nombres and "ESTADO" in nombres:
        return "estatal"
    return "otros"


# Requisitos para el filtro de licitaciones por empresa (fase 1, 2026-10-27; ver "Informe - Filtro de licitaciones por
# empresa.txt"). Medido en el ZIP de septiembre (1.635 PUB): duración 92,5 %, lotes 14,3 % (todos con importe propio),
# tipo de solvencia económica 38,7 %, su importe mínimo solo 1,9 %, clasificación 4,6 %. Lo que no viene está en el PCAP.
_RE_LOTE = re.compile(r"<cac:ProcurementProjectLot>.*?</cac:ProcurementProjectLot>", re.S)
_MESES_UNIDAD = {"MON": 1, "ANN": 12, "DAY": 1 / 30.4}
# Tipos de solvencia técnica (TechnicalCapabilityTypeCode) que piden un certificado de calidad o de gestión ambiental
TIPOS_CERTIFICADO = {"XSX-CERTCALIDAD", "OXR-GESTMEDIOAMB", "XSR-CALIDAD"}
_RE_CERT = re.compile(r"\b(?:ISO|UNE[- ]EN|EMAS|ENS)\b[ -]?(?:\d{4,5})?", re.I)


def _cpvs(pp):
    """Todos los CPV de un ProcurementProject, sin repetir y en orden."""
    return list(dict.fromkeys(re.findall(r"<cbc:ItemClassificationCode[^>]*>(\d{8})", pp)))


def _duracion_meses(pp):
    """Duración inicial en meses (PlannedPeriod: DurationMeasure o fechas de inicio y fin), o None."""
    pl = _bloque("PlannedPeriod", pp)
    m = re.search(r'<cbc:DurationMeasure unitCode="(\w+)"[^>]*>([\d.,]+)<', pl)
    if m and m.group(1) in _MESES_UNIDAD:
        try:
            v = float(m.group(2).replace(",", ".")) * _MESES_UNIDAD[m.group(1)]
            return round(v, 1) if v > 0 else None
        except ValueError:
            return None
    ini, fin = _tag("StartDate", pl), _tag("EndDate", pl)
    if re.fullmatch(r"\d{4}-\d\d-\d\d", ini) and re.fullmatch(r"\d{4}-\d\d-\d\d", fin):
        dias = (int(fin[:4]) - int(ini[:4])) * 365 + (int(fin[5:7]) - int(ini[5:7])) * 30.4 + int(fin[8:]) - int(ini[8:])
        return round(dias / 30.4, 1) if dias > 0 else None
    return None


def _requisitos(tt):
    """De un bloque TenderingTerms: clasificación exigida, tipos de solvencia, importe mínimo de solvencia económica
    (ThresholdQuantity, si viene) y certificados. Claves cortas: van en JSON en la tabla."""
    tqr = _bloque("TendererQualificationRequest", tt)
    if not tqr:
        return {}
    r = {}
    clas = list(dict.fromkeys(c.strip().upper() for c in re.findall(r"<cbc:CodeValue>([^<]+)</cbc:CodeValue>", tqr)))
    if clas:
        r["clas"] = clas
    eco = re.findall(r"<cac:FinancialEvaluationCriteria>(.*?)</cac:FinancialEvaluationCriteria>", tqr, re.S)
    tec = re.findall(r"<cac:TechnicalEvaluationCriteria>(.*?)</cac:TechnicalEvaluationCriteria>", tqr, re.S)
    if eco:
        r["eco"] = list(dict.fromkeys(_tag("EvaluationCriteriaTypeCode", x) for x in eco))
        umbrales = [_importe(_tag("ThresholdQuantity", x)) for x in eco]
        umbrales = [u for u in umbrales if u]
        if umbrales:
            r["umbral_eco"] = max(umbrales)
    if tec:
        r["tec"] = list(dict.fromkeys(_tag("EvaluationCriteriaTypeCode", x) for x in tec))
        certs = set()
        for x in tec:
            if _tag("EvaluationCriteriaTypeCode", x) in TIPOS_CERTIFICADO:
                certs.add(_tag("EvaluationCriteriaTypeCode", x))
            certs.update(c.upper().replace(" ", "") for c in _RE_CERT.findall(_tag("Description", x)))
        if certs:
            r["cert"] = sorted(certs)
    return r


def _lote(lo):
    pp = _bloque("ProcurementProject", lo)
    nuts = _tag("CountrySubentityCode", _bloque("RealizedLocation", pp))
    d = {"id": _tag("ID", lo), "titulo": _tag("Name", pp)[:300],
         "presupuesto": _importe(_tag("TaxExclusiveAmount", _bloque("BudgetAmount", pp))),
         "cpvs": _cpvs(pp), "nuts": nuts}
    req = _requisitos(_bloque("TenderingTerms", lo))
    if req:
        d["req"] = req
    return d


def analizar_entrada(e):
    """dict con lo necesario para la ficha de una licitación, o None si no es una entrada válida. Para las que no
    están en PUB solo importan id, actualizado y estado (sirven para retirar la versión abierta anterior)."""
    eid = _tag("id", e)
    if not eid:
        return None
    r = {"id": eid, "actualizado": _tag("updated", e), "estado": _tag("ContractFolderStatusCode", e).upper()}
    if r["estado"] not in ESTADOS_ABIERTOS:
        return r
    lcp = _bloque("LocatedContractingParty", e)
    party = _bloque("Party", lcp)
    pp = _bloque("ProcurementProject", e)
    ba = _bloque("BudgetAmount", pp)
    tp = _bloque("TenderingProcess", e)
    plazo = _bloque("TenderSubmissionDeadlinePeriod", tp)
    fin_d, fin_h = _tag("EndDate", plazo), _tag("EndTime", plazo)
    m = re.search(r'<link\b[^>]+href="([^"]+)"', e)
    nif = re.search(r'<cbc:ID schemeName="NIF">([^<]+)</cbc:ID>', party)
    dir3 = re.search(r'<cbc:ID schemeName="DIR3">([^<]+)</cbc:ID>', party)
    cpv = re.search(r"<cbc:ItemClassificationCode[^>]*>(\d{8})", pp)
    nuts = _tag("CountrySubentityCode", _bloque("RealizedLocation", pp))
    r.update({
        "titulo": _tag("title", e),
        "url": html.unescape(m.group(1)) if m else "",
        "expediente": _tag("ContractFolderID", e),
        "organo": _tag("Name", _bloque("PartyName", party)),
        "nif_organo": nif.group(1).strip() if nif else "",
        "dir3": dir3.group(1).strip() if dir3 else "",
        "cp_organo": _tag("PostalZone", _bloque("PostalAddress", party)),
        "ambito": _ambito(lcp),
        "nuts": nuts,
        "provincia": provincia_de_nuts(nuts),
        "comunidad": comunidad_de_nuts(nuts),
        "cpv": cpv.group(1) if cpv else "",
        "tipo": _tag("TypeCode", pp),
        "procedimiento": _tag("ProcedureCode", tp),
        "presupuesto": _importe(_tag("TaxExclusiveAmount", ba)),
        "valor_estimado": _importe(_tag("EstimatedOverallContractAmount", ba)),
        "lotes": len(re.findall(r"<cac:ProcurementProjectLot>", e)),
        # hora local de España, como la publica PLACE; sin hora -> fin del día
        "fin_plazo": f"{fin_d} {fin_h[:5] if fin_h else '23:59'}" if re.fullmatch(r"\d{4}-\d\d-\d\d", fin_d) else "",
    })
    # Requisitos del contrato (fuera de los lotes) y de cada lote, para el filtro por empresa
    sin_lotes = _RE_LOTE.sub("", e)
    pp_contrato = _bloque("ProcurementProject", sin_lotes)
    r.update({
        "cpvs": _cpvs(pp_contrato),
        "duracion_meses": _duracion_meses(pp_contrato),
        "prorrogas": "ContractExtension" in pp_contrato,
        "req": _requisitos(_bloque("TenderingTerms", sin_lotes)),
        "lotes_detalle": [_lote(lo) for lo in _RE_LOTE.findall(e)],
        # sujeto a regulación armonizada (SARA): True/False, None si no lo dice (medido el 27-10: lo dice el 100 %)
        "sara": {"true": True, "false": False}.get(_tag("OverThresholdIndicator", tp).lower()),
    })
    return r


def requisitos_json(r):
    """Lo que el filtro por empresa necesita y la tabla no tiene en columnas propias, en JSON compacto."""
    d = {k: r[k] for k in ("nuts", "cp_organo", "cpvs", "duracion_meses", "prorrogas", "req", "lotes_detalle")
         if r.get(k)}
    if r.get("sara") is not None:       # False también cuenta: es el caso de la exención de nueva creación
        d["sara"] = r["sara"]
    return json.dumps(d, ensure_ascii=False, separators=(",", ":")) if d else ""


def entradas(raw):
    """Cada <entry> de un .atom (bytes) como texto, de una en una."""
    for m in _RE_ENTRY.finditer(raw):
        yield m.group(0).decode("utf-8", "replace")


def borradas(raw):
    """[(id, cuándo)] de los <at:deleted-entry> de un .atom."""
    return [(a.decode(), b.decode()) for a, b in _RE_BORRADA.findall(raw)]


def pagina_siguiente(raw):
    """URL de la página anterior (más antigua) del Atom, o ""."""
    m = _RE_SIGUIENTE.search(raw[:5000])
    return html.unescape(m.group(1).decode()) if m else ""
