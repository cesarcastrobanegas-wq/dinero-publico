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
Las que no son de su sector, provincia o tipo de contrato, o cierran en menos de MARGEN_DIAS, ni se evalúan.

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
- Empresas de nueva creación (menos de 5 años desde el año de constitución): en contratos NO armonizados (el feed lo
  dice: OverThresholdIndicator) no se les exige la relación de trabajos ejecutados (arts. 88.2 obras, 89.1.h
  suministros y 90.4 servicios LCSP); sale como motivo. En los armonizados la exención no aplica y se avisa.
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
TRAMOS_TEXTO = {
    "<60k": "menos de 60.000 €", "60k-150k": "de 60.000 a 150.000 €", "150k-300k": "de 150.000 a 300.000 €",
    "300k-600k": "de 300.000 a 600.000 €", "600k-1,5M": "de 600.000 € a 1,5 millones",
    "1,5M-3M": "de 1,5 a 3 millones de €", "3M-10M": "de 3 a 10 millones de €", ">10M": "más de 10 millones de €",
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
# Nombres en lenguaje llano de los certificados y de los tipos genéricos del feed
CERT_NOMBRES = {"ISO9001": "ISO 9001 (calidad)", "ISO14001": "ISO 14001 (medio ambiente)",
                "ISO45001": "ISO 45001 (seguridad y salud en el trabajo)", "ENS": "Esquema Nacional de Seguridad",
                "EMAS": "EMAS (gestión ambiental europea)", "XSX-CERTCALIDAD": "un certificado de calidad",
                "XSR-CALIDAD": "un certificado de calidad", "OXR-GESTMEDIOAMB": "un certificado de gestión ambiental"}
# Casillas de certificados del formulario (lo que no esté aquí va en "otros", como texto: "ISO27001", "UNE-EN...")
CERTIFICADOS = ("ISO9001", "ISO14001", "ISO45001", "ENS", "EMAS")
# Empresas de nueva creación (antigüedad inferior a 5 años): en contratos NO armonizados no se les puede exigir la
# relación de trabajos ejecutados. Mismo criterio en obras, suministros y servicios, cada uno en su artículo.
ANIOS_NUEVA_CREACION = 5
ARTICULO_NUEVA_CREACION = {"3": "art. 88.2 LCSP", "1": "art. 89.1.h LCSP", "2": "art. 90.4 LCSP"}
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


# Nombres para mostrar (portada del PDF, formulario y fichas)
NOMBRE_PROVINCIA = {
    "a_coruna": "A Coruña", "alicante": "Alicante", "albacete": "Albacete", "almeria": "Almería", "asturias": "Asturias",
    "avila": "Ávila", "badajoz": "Badajoz", "baleares": "Illes Balears", "barcelona": "Barcelona", "burgos": "Burgos",
    "caceres": "Cáceres", "cadiz": "Cádiz", "cantabria": "Cantabria", "castellon": "Castellón", "ceuta": "Ceuta",
    "ciudad_real": "Ciudad Real", "cordoba": "Córdoba", "cuenca": "Cuenca", "girona": "Girona", "granada": "Granada",
    "guadalajara": "Guadalajara", "huelva": "Huelva", "huesca": "Huesca", "jaen": "Jaén", "la_rioja": "La Rioja",
    "las_palmas": "Las Palmas", "leon": "León", "lleida": "Lleida", "lugo": "Lugo", "madrid": "Madrid",
    "malaga": "Málaga", "melilla": "Melilla", "murcia": "Región de Murcia", "navarra": "Navarra", "ourense": "Ourense",
    "palencia": "Palencia", "pais_vasco": "País Vasco", "pontevedra": "Pontevedra", "salamanca": "Salamanca",
    "santa_cruz_tenerife": "Santa Cruz de Tenerife", "segovia": "Segovia", "sevilla": "Sevilla", "soria": "Soria",
    "tarragona": "Tarragona", "teruel": "Teruel", "toledo": "Toledo", "valencia": "Valencia",
    "valladolid": "Valladolid", "zamora": "Zamora", "zaragoza": "Zaragoza",
}
NOMBRE_COMUNIDAD = {
    "galicia": "Galicia", "asturias": "Asturias", "cantabria": "Cantabria", "pais_vasco": "País Vasco",
    "navarra": "Navarra", "la_rioja": "La Rioja", "aragon": "Aragón", "madrid": "Comunidad de Madrid",
    "castilla_y_leon": "Castilla y León", "castilla_la_mancha": "Castilla-La Mancha", "extremadura": "Extremadura",
    "cataluna": "Cataluña", "valenciana": "Comunitat Valenciana", "baleares": "Illes Balears",
    "andalucia": "Andalucía", "murcia": "Región de Murcia", "ceuta": "Ceuta", "melilla": "Melilla",
    "canarias": "Canarias",
}
TIPO_TXT = {"1": "suministro", "2": "servicios", "3": "obras", "21": "gestión de servicios públicos",
            "22": "concesión de servicios", "31": "concesión de obras públicas", "32": "concesión de obras"}


def lugar_txt(clave):
    if clave.startswith("comunidad: "):
        c = clave[len("comunidad: "):]
        return NOMBRE_COMUNIDAD.get(c, c)
    if clave in (SIN_LUGAR, "ámbito nacional"):
        return "Toda España" if clave == "ámbito nacional" else "No consta en el anuncio"
    return NOMBRE_PROVINCIA.get(clave, clave.replace("_", " ").title())


def perfil_texto(perfil, ahora=None):
    """[(etiqueta, valor)] con los datos del perfil en lenguaje llano (portada del PDF, correo de
    confirmación y página del socio)."""
    ahora = ahora or datetime.now()
    sector = perfil.get("sector_texto") or ", ".join(
        dict.fromkeys(LIC.CPV_DIVISIONES.get(c[:2], c) for c in perfil["cpvs"]))
    tipos = perfil.get("tipos") or []
    filas = []
    if perfil.get("descripcion"):
        filas.append(("Empresa", perfil["descripcion"]))
    filas += [
        ("Sector", sector),
        ("Provincias", ", ".join(NOMBRE_PROVINCIA.get(p, p) for p in perfil["provincias"])),
        ("Tipo de contrato", ", ".join(tipos).capitalize() if tipos else "Todos (obras, servicios y suministros)"),
        ("Personas en plantilla", str(perfil.get("trabajadores") or "No lo ha dicho")),
        ("Facturación anual", TRAMOS_TEXTO.get(perfil["facturacion"], perfil["facturacion"]).capitalize()),
        ("Clasificación de contratista", "; ".join(map(clas_llano, perfil.get("clasificacion") or []))
         or "No tiene"),
        ("Certificados", ", ".join(map(cert_llano, perfil.get("certificados") or [])) or "Ninguno"),
    ]
    a = perfil.get("anio_constitucion")
    if a:
        nueva = ahora.year - a < ANIOS_NUEVA_CREACION
        filas.append(("Año de constitución", f"{a}" + (" (menos de 5 años: empresa de nueva creación)" if nueva else "")))
    exp = perfil.get("experiencia_publica")
    filas.append(("Ha trabajado para la Administración", "Sí" if exp else "No" if exp is False else "No lo ha dicho"))
    filas.append(("Iría en UTE (junto a otra empresa)", "Sí" if perfil.get("ute") else "No"))
    return filas


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


def eur(x):
    """1234567.8 -> "1.234.568 €" (formato español)."""
    return f"{x:,.0f}".replace(",", ".") + " €"


def clas_llano(codigo):
    """"C2-4" -> "grupo C, subgrupo 2, categoría 4"; "C*-3" -> "grupo C (cualquier subgrupo), categoría 3"."""
    c = _clas(codigo)
    if not c:
        return codigo
    g, sub, cat = c
    return (f"grupo {g}" + (" (cualquier subgrupo)" if sub == "*" else f", subgrupo {sub}")
            + (f", categoría {cat}" if cat else ""))


def cert_llano(c):
    """"ISO9001" -> "ISO 9001 (calidad)"; los que no tienen nombre, con su espacio: "ISO27001" -> "ISO 27001"."""
    return CERT_NOMBRES.get(c) or re.sub(r"^(ISO|UNE-EN)(\d)", r"\1 \2", c)


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
    if (lic.get("tipo") or "") in TIPOS_OBRAS:
        # una obra siempre está en algún sitio: "ES" o nada es que el anuncio no lo dice, y no se ofrece a todas las
        # provincias (27-10: a una constructora de Murcia le salían obras de Huelva y de Toledo)
        return SIN_LUGAR, False
    return ("ámbito nacional" if nuts.startswith("ES") else SIN_LUGAR), perfil.get("incluir_sin_provincia", True)


def evaluar(lic, perfil, ahora=None):
    """Lista de resultados (uno por lote o por contrato) de una licitación para un perfil; vacía si no es de su sector,
    de su provincia o cierra demasiado pronto. Cada resultado: dict con grupo, motivos y datos para el informe.

    perfil: cpvs (prefijos de 2 a 8 cifras), provincias (claves de la app), trabajadores, facturacion (clave de
    TRAMOS_FACTURACION), clasificacion (lista de códigos "C2-4", opcional), ute (bool) y, opcionales,
    incluir_sin_provincia (por defecto True), experiencia_publica (bool), certificados (de CERTIFICADOS, más los que
    escriba en "otros"), anio_constitucion (int) y tipos (["obras", "servicios", "suministros"]; vacío = todos). El
    tipo evita, por ejemplo, que a una consultora le salgan lotes de suministro que heredan el CPV de software del
    contrato (decisión de César, 2026-10-27). Ver validar_perfil()."""
    ahora = ahora or datetime.now()
    fin = lic.get("fin_plazo") or ""
    if not fin or fin < (ahora + timedelta(days=MARGEN_DIAS)).strftime("%Y-%m-%d %H:%M"):
        return []
    tipos = perfil.get("tipos")
    if tipos and not any((lic.get("tipo") or "") in LIC.TIPOS_FILTRO[t] for t in tipos):
        return []
    lo_f, hi_f = TRAMOS_FACTURACION[perfil["facturacion"]]
    perfil_clas = [c for c in map(_clas, perfil.get("clasificacion") or []) if c]
    antiguedad = ahora.year - perfil["anio_constitucion"] if perfil.get("anio_constitucion") else None
    nueva = antiguedad is not None and antiguedad < ANIOS_NUEVA_CREACION
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
            duda.append("El anuncio no dice cuánto dura el contrato: hemos supuesto un año.")
        if provincia == SIN_LUGAR:
            duda.append("El anuncio no dice dónde se hace el trabajo.")
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
                    motivos.append("Tiene la clasificación de contratista que piden ("
                                   + "; ".join(map(clas_llano, req["clas"])) + ").")
                elif perfil_clas and any(_cumple_clasificacion(c, perfil_clas) for c in clas_exig):
                    duda.append("Piden varias clasificaciones de contratista ("
                                + "; ".join(map(clas_llano, req["clas"])) + ") y su empresa solo tiene parte.")
                else:
                    no_llega.append("Piden clasificación de contratista (" + "; ".join(map(clas_llano, req["clas"]))
                                    + ") y su empresa no la tiene.")
            else:
                cat = _categoria_obras(vam)
                tiene = [c for c in perfil_clas if c[2] >= cat]
                if tiene:
                    duda.append(f"Obra de más de 500.000 €: piden clasificación de contratista (categoría {cat} o "
                                "superior), pero el anuncio no dice de qué grupo.")
                elif lote and importe < UMBRAL_CLASIFICACION_OBRAS:
                    duda.append("Obra de más de 500.000 € en total: el pliego puede pedir clasificación de "
                                "contratista también para este lote.")
                elif lic.get("ambito") == "otros":
                    duda.append("Obra de más de 500.000 €: si quien contrata es una Administración, pedirá "
                                "clasificación de contratista.")
                else:
                    no_llega.append(f"Obra de más de 500.000 €: piden clasificación de contratista (categoría {cat} o "
                                    "superior) y su empresa no la tiene.")

        # --- solvencia económica
        umbral = req.get("umbral_eco")
        exigida = umbral or FACTOR_SOLVENCIA * vam
        estimada = not umbral
        pide = (f"Piden facturar al año al menos {eur(exigida)}"
                + (" (cálculo nuestro: el anuncio no da la cifra)" if estimada else " (según el anuncio)"))
        if sumario:
            motivos.append("Procedimiento simplificado sumario: no piden demostrar solvencia económica ni técnica.")
        elif clas_sustituye:
            motivos.append("Su clasificación de contratista le sirve para demostrar la solvencia.")
        elif lo_f >= exigida:
            motivos.append(pide + ": su empresa lo cubre.")
        elif hi_f < exigida:
            no_llega.append(pide + ": su empresa no llega.")
        else:
            duda.append(pide + ": puede que su empresa llegue o no; depende de su cifra exacta.")

        # --- avisos que no excluyen
        if not sumario:
            if "OSR-COMPTASK" in (req.get("tec") or []):
                articulo = ARTICULO_NUEVA_CREACION.get(tipo)
                if nueva and articulo and lic.get("sara") is False:
                    motivos.append(f"Piden experiencia, pero su empresa tiene {antiguedad} años (menos de 5) y el "
                                   "contrato no está sujeto a las normas europeas (no armonizado): no se la pueden "
                                   f"exigir ({articulo}).")
                elif nueva and articulo and lic.get("sara") is None:
                    duda.append("Piden experiencia. A una empresa de menos de 5 años no se la pueden exigir si el "
                                f"contrato no está sujeto a las normas europeas ({articulo}), pero el anuncio no lo "
                                "dice.")
                elif perfil.get("experiencia_publica") is False or nueva:
                    duda.append("Piden haber hecho trabajos parecidos en los últimos años (valen también los hechos "
                                "para clientes privados)."
                                + (" Al ser un contrato sujeto a las normas europeas, no vale la excepción para "
                                   "empresas de menos de 5 años." if nueva and articulo and lic.get("sara") else ""))
            certs = set(req.get("cert") or [])
            if certs:
                necesarios = set()
                for c in certs:
                    necesarios |= CERT_POR_TIPO.get(c, {c})
                tiene = set(perfil.get("certificados") or [])
                if not any(c in tiene for c in necesarios):
                    concretos = {c for c in certs if c not in CERT_POR_TIPO}      # los genéricos, solo si no hay
                    duda.append("Piden certificados que su empresa no ha marcado: "
                                + ", ".join(sorted({cert_llano(c) for c in (concretos or certs)})) + ".")
            if "OXR-PLANTILLA" in (req.get("tec") or []):
                duda.append("Piden un número mínimo de personas en plantilla.")
            if vam > VAM_POR_TRABAJADOR * max(perfil.get("trabajadores") or 1, 1) and not no_llega:
                duda.append(f"Contrato grande para una plantilla de {perfil.get('trabajadores')} personas "
                            f"(unos {eur(vam)} al año).")

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
            "importe": importe, "valor_estimado_contrato": ve, "vam": round(vam), "duracion_meses": dur,
            "solvencia_exigida": round(exigida), "solvencia_estimada": estimada, "sumario": sumario,
            "lote_de_grande": bool(lote) and ve > hi_f * UTE_FACTOR_MAX,
            "motivos": no_llega + duda + motivos,
        })
    return res


def validar_perfil(perfil, ahora=None):
    """Lista de errores de un perfil (vacía si está bien), para cuando haya formulario."""
    ahora = ahora or datetime.now()
    err = []
    if not perfil.get("cpvs") or not all(re.fullmatch(r"\d{2,8}", c) for c in perfil["cpvs"]):
        err.append("sector: marca al menos un sector (o escribe códigos CPV de 2 a 8 cifras)")
    if not perfil.get("provincias"):
        err.append("provincias: marca al menos una")
    elif not set(perfil["provincias"]) <= set(LIC.NUTS_PROVINCIA.values()):
        err.append("provincias: alguna no existe")
    if perfil.get("facturacion") not in TRAMOS_FACTURACION:
        err.append("facturación: elige un tramo")
    if any(_clas(c) is None or not _clas(c)[2] for c in perfil.get("clasificacion") or []):
        err.append('clasificación: formato "C2-4" (grupo, subgrupo y categoría)')
    if any(t not in LIC.TIPOS_FILTRO for t in perfil.get("tipos") or []):
        err.append("tipo de contrato: obras, servicios o suministros")
    a = perfil.get("anio_constitucion")
    if a is not None and not (isinstance(a, int) and 1850 <= a <= ahora.year):
        err.append("año de constitución: no válido")
    if any(not re.fullmatch(r"[A-Z0-9 .-]{2,20}", c) for c in perfil.get("certificados") or []):
        err.append('certificados: casillas de CERTIFICADOS o texto corto en "otros" ("ISO27001")')
    return err


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
