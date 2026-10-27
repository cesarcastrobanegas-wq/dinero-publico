# encoding: utf-8
"""
Filtro de licitaciones por empresa, FASE 1: solo el motor (decisión de César, 2026-10-27; ver "Informe - Filtro de
licitaciones por empresa.txt" en la carpeta de la reunión de la Cámara). Sin formulario, sin pantallas y sin datos de
empresas reales: funciones puras que reciben licitaciones (salida de licitaciones_place.analizar_entrada, o una fila de
la tabla `licitaciones` pasada por desde_fila) y un perfil de empresa.

Cada licitación abierta, y CADA LOTE por separado, cae en uno de estos grupos:
  PUEDE OPTAR               -- cumple lo que se puede comprobar con los datos del feed.
  REVISA EL PLIEGO          -- encaja, pero algo depende del pliego (solvencia justa, clasificación sin código,
                               experiencia, certificados, contrato grande para la plantilla).
  SOLO EN UTE O EN UN LOTE  -- sola no llega (solvencia o clasificación) y el perfil acepta UTE. Lo de "en un lote":
                               los lotes se evalúan uno a uno, así que el lote pequeño de un contrato grande sale en
                               PUEDE OPTAR o REVISA EL PLIEGO con la marca `lote_de_grande`.
  (DESCARTADA               -- no llega ni en UTE; no se enseña al socio, solo se cuenta.)
Las que no son de su sector o provincia, o cierran en menos de MARGEN_DIAS, ni se evalúan.

Reglas (LCSP y RGLCAP; orientativas, a revisar por un jurista antes de un informe de pago):
- Valor anual medio (VAM) = presupuesto sin IVA (del lote, si lo hay) / duración inicial en años, con un mínimo de un
  año. Sin presupuesto se usa el valor estimado; sin duración, un año (marcado como estimado).
- Solvencia económica exigida = el importe del feed (ThresholdQuantity) si viene; si no, 1,5 x VAM (art. 87.1.a LCSP y
  art. 11.4 RGLCAP). Se compara con el tramo de facturación: límite inferior >= exigida -> cumple; límite superior <
  exigida -> no llega; si no, depende del pliego.
- Procedimiento SUMARIO (abierto simplificado, art. 159.6 LCSP: obras < 80.000 EUR, resto < 60.000 EUR de valor
  estimado): no se exige solvencia. PLACE no lo marca: se deduce del procedimiento (9) y el valor estimado.
- Clasificación obligatoria en obras de valor estimado >= 500.000 EUR (art. 77.1.a LCSP): con el código del feed se
  compara grupo, subgrupo y categoría; sin código, depende del pliego si el perfil tiene alguna de categoría
  suficiente. En servicios y obras menores, tenerla en el grupo pedido sustituye a la solvencia económica.
- UTE: las solvencias se suman (art. 69 LCSP), pero no se ofrece una UTE para algo más de UTE_FACTOR_MAX veces lo
  que la empresa factura.
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta

try:
    from . import licitaciones_place as LIC
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import licitaciones_place as LIC

PUEDE = "PUEDE OPTAR"
REVISA = "REVISA EL PLIEGO"
UTE = "SOLO EN UTE O EN UN LOTE"
DESCARTADA = "DESCARTADA"
GRUPOS = (PUEDE, REVISA, UTE)

# Tramos de facturación del formulario (euros/año), alineados con los cortes de la ley
TRAMOS_FACTURACION = {
    # el primero va partido en 60.000 (el corte del sumario): con un tramo "<150k" que empieza en 0, cualquier
    # solvencia, por pequeña que fuera, salía como dudosa
    "<60k": (0, 60_000), "60k-150k": (60_000, 150_000), "150k-300k": (150_000, 300_000), "300k-600k": (300_000, 600_000),
    "600k-1,5M": (600_000, 1_500_000), "1,5M-3M": (1_500_000, 3_000_000), "3M-10M": (3_000_000, 10_000_000),
    ">10M": (10_000_000, float("inf")),
}
FACTOR_SOLVENCIA = 1.5
UMBRAL_CLASIFICACION_OBRAS = 500_000
SUMARIO_MAX = {"obras": 80_000, "otros": 60_000}
TIPOS_OBRAS = {"3"}                      # contrato de obras (las concesiones no entran en el art. 77.1.a)
PROCEDIMIENTO_SIMPLIFICADO = "9"
UTE_FACTOR_MAX = 5                       # en UTE, como mucho 5 veces su facturación máxima
VAM_POR_TRABAJADOR = 100_000             # por encima de esto por persona, se avisa (puede haber subrogación)
SIN_LUGAR = "sin lugar en el anuncio"
MARGEN_DIAS = 2                          # días mínimos hasta el fin de plazo para preparar la oferta
# Categorías de clasificación por VAM (RGLCAP, arts. 26 y 38 tras el RD 773/2015): tope superior de cada una
CATEGORIAS_OBRAS = ((1, 150_000), (2, 360_000), (3, 840_000), (4, 2_400_000), (5, 5_000_000), (6, float("inf")))
# Certificados que cubren cada tipo genérico de solvencia técnica del feed
CERT_POR_TIPO = {"XSX-CERTCALIDAD": {"ISO9001"}, "XSR-CALIDAD": {"ISO9001"}, "OXR-GESTMEDIOAMB": {"ISO14001", "EMAS"}}
_RE_CLAS = re.compile(r"^([A-Z])(\d{1,2}|\*)?-?(\d)?$")
# Código INE de provincia (las dos primeras cifras del código postal) -> provincia de la app, para las entidades locales
# cuyo anuncio no trae la provincia en el NUTS (p. ej. solo "ES")
PROVINCIA_POR_CP = dict(zip(
    [f"{i:02d}" for i in range(1, 53)],
    ["pais_vasco", "albacete", "alicante", "almeria", "avila", "badajoz", "baleares", "barcelona", "burgos", "caceres",
     "cadiz", "castellon", "ciudad_real", "cordoba", "a_coruna", "cuenca", "girona", "granada", "guadalajara",
     "pais_vasco", "huelva", "huesca", "jaen", "leon", "lleida", "la_rioja", "lugo", "madrid", "malaga", "murcia",
     "navarra", "ourense", "asturias", "palencia", "las_palmas", "pontevedra", "salamanca", "santa_cruz_tenerife",
     "cantabria", "segovia", "sevilla", "soria", "tarragona", "teruel", "toledo", "valencia", "valladolid",
     "pais_vasco", "zamora", "zaragoza", "ceuta", "melilla"]))
# provincia de la app -> NUTS2 de su comunidad (para lo que el feed solo sitúa a nivel de comunidad)
_NUTS2_PROVINCIA = {p: n[:4] for n, p in LIC.NUTS_PROVINCIA.items() if len(n) == 5}


def desde_fila(fila):
    """dict de una fila de la tabla `licitaciones` (sqlite3.Row o dict) con el JSON de `requisitos` ya abierto."""
    d = dict(fila)
    try:
        d.update(json.loads(d.get("requisitos") or "{}"))
    except ValueError:
        pass
    return d


def _clas(codigo):
    """"C2-4" -> ("C", "2", 4); "C*-5" -> ("C", "*", 5); None si no se entiende."""
    m = _RE_CLAS.match((codigo or "").strip().upper())
    if not m:
        return None
    return m.group(1), m.group(2) or "*", int(m.group(3)) if m.group(3) else 0


def _categoria_obras(vam):
    return next(c for c, tope in CATEGORIAS_OBRAS if vam <= tope)


def _cumple_clasificacion(exigida, perfil_clas):
    g, s, c = exigida
    for pg, ps, pc in perfil_clas:
        if pg == g and (s == "*" or ps == s) and pc >= c:
            return True
    return False


def _encaja_cpv(cpvs, prefijos):
    return any(c.startswith(p) for c in cpvs for p in prefijos)


def _unidades(lic):
    """[(lote o None, presupuesto, cpvs, nuts, requisitos propios)] -- un lote por unidad, o el contrato entero."""
    lotes = lic.get("lotes_detalle") or []
    cpvs_c = lic.get("cpvs") or ([lic["cpv"]] if lic.get("cpv") else [])
    nuts_c = lic.get("nuts") or ""
    if not lotes:
        return [(None, lic.get("presupuesto") or lic.get("valor_estimado"), cpvs_c, nuts_c, lic.get("req") or {})]
    return [(lo, lo.get("presupuesto"), lo.get("cpvs") or cpvs_c, lo.get("nuts") or nuts_c, lo.get("req") or {})
            for lo in lotes]


def _lugar(nuts, lic, perfil):
    """(texto del lugar, ¿entra?) según el NUTS del lugar de ejecución. Con provincia: tiene que ser una de las del
    perfil. Si el NUTS no la da, se usa la provincia de la fila (la web la deduce del municipio del órgano) y, en las
    entidades locales, el código postal del órgano. Solo con la comunidad (NUTS2, pasa en Canarias, Castilla y León, la Comunitat Valenciana...): entra si el
    perfil tiene alguna provincia de esa comunidad. "ES" (toda España): ámbito nacional, según incluir_sin_provincia.
    Sin ningún lugar: entra igual que las nacionales, pero el resultado avisa (ver SIN_LUGAR)."""
    nuts = (nuts or "").strip().upper()
    provincia = LIC.provincia_de_nuts(nuts) if len(nuts) >= 5 else ""
    if not provincia and len(nuts) < 5:
        cp = (lic.get("cp_organo") or "").strip()
        provincia = lic.get("provincia") or (PROVINCIA_POR_CP.get(cp[:2], "") if lic.get("ambito") == "local"
                                             and len(cp) == 5 else "")
    if provincia:
        return provincia, provincia in perfil["provincias"]
    if len(nuts) >= 4 and nuts[:4] in LIC.NUTS_COMUNIDAD:
        entra = nuts[:4] in {_NUTS2_PROVINCIA.get(p) for p in perfil["provincias"]}
        return "comunidad: " + LIC.NUTS_COMUNIDAD[nuts[:4]], entra
    return ("ámbito nacional" if nuts.startswith("ES") else SIN_LUGAR), perfil.get("incluir_sin_provincia", True)


def evaluar(lic, perfil, ahora=None):
    """Lista de resultados (uno por lote o por contrato) de una licitación para un perfil; vacía si no es de su sector,
    de su provincia o cierra demasiado pronto. Cada resultado: dict con grupo, motivos y datos para el informe.

    perfil: cpvs (prefijos de 2 a 8 cifras), provincias (claves de la app), trabajadores, facturacion (clave de
    TRAMOS_FACTURACION), clasificacion (lista de códigos "C2-4", opcional), ute (bool) y, opcionales,
    incluir_sin_provincia (por defecto True), experiencia_publica (bool) y certificados (["ISO9001", ...])."""
    ahora = ahora or datetime.now()
    fin = lic.get("fin_plazo") or ""
    if not fin or fin < (ahora + timedelta(days=MARGEN_DIAS)).strftime("%Y-%m-%d %H:%M"):
        return []
    lo_f, hi_f = TRAMOS_FACTURACION[perfil["facturacion"]]
    perfil_clas = [c for c in map(_clas, perfil.get("clasificacion") or []) if c]
    ve = lic.get("valor_estimado") or lic.get("presupuesto") or 0
    tipo = lic.get("tipo") or ""
    obras = tipo in TIPOS_OBRAS
    sumario = (lic.get("procedimiento") == PROCEDIMIENTO_SIMPLIFICADO and 0 < ve
               < SUMARIO_MAX["obras" if obras else "otros"])
    dur = lic.get("duracion_meses")
    anios = max(dur / 12, 1) if dur else 1
    req_c = lic.get("req") or {}
    con_lotes = bool(lic.get("lotes_detalle"))
    res = []
    for lote, importe, cpvs, nuts, req_l in _unidades(lic):
        if not _encaja_cpv(cpvs, perfil["cpvs"]):
            continue
        provincia, entra = _lugar(nuts, lic, perfil)
        if not entra:
            continue
        importe = importe or ve
        if not importe:
            continue
        motivos, no_llega, duda = [], [], []
        vam = importe / anios
        if not dur:
            duda.append("sin duración en el anuncio: se toma un año")
        if provincia == SIN_LUGAR:
            duda.append("el anuncio no dice dónde se ejecuta")
        # requisitos: los del lote; si no trae, los del contrato (salvo el importe de solvencia, que en un contrato con
        # lotes puede ser el del total)
        req = dict(req_c, **req_l) if req_l else dict(req_c)
        if con_lotes and "umbral_eco" not in req_l:
            req.pop("umbral_eco", None)
        clas_exig = [c for c in map(_clas, req.get("clas") or []) if c]

        # --- clasificación
        clas_sustituye = False
        if clas_exig and perfil_clas:
            cumplidas = [c for c in clas_exig if _cumple_clasificacion(c, perfil_clas)]
            clas_sustituye = len(cumplidas) == len(clas_exig)
        if obras and ve >= UMBRAL_CLASIFICACION_OBRAS and not sumario:
            if clas_exig:
                if clas_sustituye:
                    motivos.append("tiene la clasificación exigida (" + ", ".join(req["clas"]) + ")")
                elif perfil_clas and any(_cumple_clasificacion(c, perfil_clas) for c in clas_exig):
                    duda.append("cumple solo parte de la clasificación exigida (" + ", ".join(req["clas"]) + ")")
                else:
                    no_llega.append("pide clasificación " + ", ".join(req["clas"]) + " y no la tiene")
            else:
                cat = _categoria_obras(vam)
                tiene = [c for c in perfil_clas if c[2] >= cat]
                if tiene:
                    duda.append(f"pide clasificación (categoría {cat} o más), pero el anuncio no dice el grupo")
                elif lote and importe < UMBRAL_CLASIFICACION_OBRAS:
                    duda.append("obra de más de 500.000 EUR: el pliego puede pedir clasificación también en este lote")
                elif lic.get("ambito") == "otros":
                    duda.append("obra de más de 500.000 EUR: si el órgano es Administración, pedirá clasificación")
                else:
                    no_llega.append(f"obra de más de 500.000 EUR: pide clasificación (categoría {cat} o más)")

        # --- solvencia económica
        umbral = req.get("umbral_eco")
        exigida = umbral or FACTOR_SOLVENCIA * vam
        estimada = not umbral
        if sumario:
            motivos.append("procedimiento sumario: no se exige acreditar solvencia")
        elif clas_sustituye:
            motivos.append("su clasificación acredita la solvencia")
        elif lo_f >= exigida:
            motivos.append(f"solvencia {'estimada ' if estimada else ''}{exigida:,.0f} EUR: la cubre su facturación")
        elif hi_f < exigida:
            no_llega.append(f"solvencia {'estimada ' if estimada else ''}{exigida:,.0f} EUR: no la llega a facturar")
        else:
            duda.append(f"solvencia {'estimada ' if estimada else ''}{exigida:,.0f} EUR: dentro de su tramo de "
                        "facturación")

        # --- avisos que no excluyen
        if not sumario:
            if "OSR-COMPTASK" in (req.get("tec") or []) and perfil.get("experiencia_publica") is False:
                duda.append("pide trabajos similares de los últimos años (valen también los privados)")
            certs = set(req.get("cert") or [])
            if certs:
                necesarios = set()
                for c in certs:
                    necesarios |= CERT_POR_TIPO.get(c, {c})
                tiene = set(perfil.get("certificados") or [])
                if not any(c in tiene for c in necesarios):
                    duda.append("pide certificados (" + ", ".join(sorted(certs)) + ")")
            if "OXR-PLANTILLA" in (req.get("tec") or []):
                duda.append("pide una plantilla media mínima")
            if vam > VAM_POR_TRABAJADOR * max(perfil.get("trabajadores") or 1, 1) and not no_llega:
                duda.append(f"contrato grande para {perfil.get('trabajadores')} personas (VAM {vam:,.0f} EUR)")

        if no_llega:
            grupo = UTE if perfil.get("ute") and exigida <= UTE_FACTOR_MAX * hi_f else DESCARTADA
        elif duda:
            grupo = REVISA
        else:
            grupo = PUEDE
        res.append({
            "grupo": grupo, "id": lic.get("id"), "titulo": lic.get("titulo"), "organo": lic.get("organo"),
            "url": lic.get("url"), "fin_plazo": fin, "provincia": provincia, "tipo": tipo,
            "lote": (lote or {}).get("id"), "titulo_lote": (lote or {}).get("titulo"),
            "importe": importe, "valor_estimado_contrato": ve, "vam": round(vam),
            "solvencia_exigida": round(exigida), "solvencia_estimada": estimada, "sumario": sumario,
            "lote_de_grande": bool(lote) and ve > hi_f * UTE_FACTOR_MAX,
            "motivos": no_llega + duda + motivos,
        })
    return res


def filtrar(licitaciones, perfil, ahora=None):
    """{grupo: [resultados ordenados por fin de plazo, los sumarios primero en cada fecha]} para todas las licitaciones,
    más DESCARTADA (solo para contarlas)."""
    salida = {g: [] for g in GRUPOS + (DESCARTADA,)}
    for lic in licitaciones:
        for r in evaluar(lic, perfil, ahora):
            salida[r["grupo"]].append(r)
    for g in salida:
        salida[g].sort(key=lambda r: (r["fin_plazo"], not r["sumario"]))
    return salida
