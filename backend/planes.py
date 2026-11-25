# encoding: utf-8
"""
Planes de Dinero Público (2026-11-26, encargo de César). ÚNICO sitio del código con los planes, lo que incluye cada
uno y sus precios. La web (app.py) los pinta en /planes y «Mi cuenta», cuentas.py cuenta los informes con CUPOS y
pagos_stripe.py cobra con PRECIOS. Para cambiar un precio o un cupo, se cambia AQUÍ y nada más.

Todo está APAGADO mientras no haya empresa (la S.L.U. está en trámite): sin PLANES_ACTIVOS=1 en Render no existe
ninguna página nueva y la web se ve exactamente igual. Encendido, el pago solo aparece si además están las claves de
Stripe (y, mientras se prueba, en MODO PRUEBA de Stripe: claves sk_test_/pk_test_).

Precios en céntimos y SIN IVA. Se enseñan «IVA no incluido». Con PLANES_IVA_PCT (p. ej. «21»), cuando haya empresa,
se enseña el IVA aparte y se cobra (ver pagos_stripe.py). Sin la variable, o con «0», no se añade nada.

Lo que hoy es gratis en la web SIGUE GRATIS Y SIN REGISTRO: ningún plan cierra ninguna página de consulta.
"""
import os

# (clave, ...). El orden es el de la tabla de /planes.
ORDEN = ("ciudadano", "registrado", "bono", "profesional", "premium", "datos")

# Informes descargables por plan. "mes": cupo que se renueva cada mes el día del alta; None = sin cupo mensual.
# Premium: «ilimitados (uso razonable)»: el tope técnico solo para frenar un abuso o un programa (no se anuncia).
CUPOS = {
    "ciudadano": {"mes": 0},
    "registrado": {"mes": 1},
    "profesional": {"mes": 10},
    "premium": {"mes": None, "tope_razonable_mes": 300},
}
BONO_INFORMES = 5                       # cada bono suma 5 informes
BONO_VALIDEZ_DIAS = 365                 # «no caducan en 12 meses»: valen 12 meses desde la compra

# Precios sin IVA, en céntimos. "unico" = pago único; "mes"/"anio" = suscripción.
PRECIOS = {
    "bono": {"unico": 999},
    "profesional": {"mes": 2900, "anio": 29000},
    "premium": {"mes": 14900, "anio": 149000},
}
DATOS_DESDE = 30000                     # descarga masiva: «desde 300 €, con presupuesto». Sin pago en la web.
CONTACTO_DATOS = "contacto@dinero-publico.com"

# Lo que da cada plan además de los informes (lo usa la web para enseñar o no cada cosa).
DERECHOS = {
    "ciudadano": frozenset(),
    "registrado": frozenset({"favoritos"}),
    "profesional": frozenset({"favoritos", "alertas_pago", "filtro"}),
    "premium": frozenset({"favoritos", "alertas_pago", "filtro", "riesgo", "cuentas_anuales", "soporte"}),
}

# Textos de la tabla. Van marcados para traducir con _t() en app.py (el extractor los recoge de allí): aquí solo
# las claves y, en castellano, lo que pinta la web.
NOMBRES = {"ciudadano": "Ciudadano", "registrado": "Registrado", "bono": "Bono de informes",
           "profesional": "Profesional", "premium": "Premium", "datos": "Datos (descarga masiva)"}

PERIODOS = ("mes", "anio")


def iva_pct(entorno=None):
    """IVA que se añade, en %, o 0 si está apagado (lo normal mientras no haya empresa)."""
    crudo = ((os.environ if entorno is None else entorno).get("PLANES_IVA_PCT") or "").strip().replace(",", ".")
    try:
        v = float(crudo) if crudo else 0.0
    except ValueError:
        return 0.0
    return v if 0 < v < 100 else 0.0


def precio(plan, periodo):
    """Céntimos sin IVA, o None si ese plan no se compra así."""
    return PRECIOS.get(plan, {}).get(periodo)


def con_iva(centimos, entorno=None):
    pct = iva_pct(entorno)
    return int(round(centimos * (100 + pct) / 100)) if pct else centimos


def euros(centimos):
    """2900 -> «29 €»; 999 -> «9,99 €»; 149000 -> «1.490 €» (formato español)."""
    entero, cent = divmod(int(centimos), 100)
    miles = f"{entero:,}".replace(",", ".")
    return f"{miles} €" if not cent else f"{miles},{cent:02d} €"


def cupo_mes(plan):
    """Informes al mes del plan (None = sin cupo: uso razonable)."""
    return CUPOS.get(plan, CUPOS["registrado"])["mes"]


def tope_mes(plan):
    """Tope técnico del mes (el cupo, o el de uso razonable si el plan no tiene cupo)."""
    c = CUPOS.get(plan, CUPOS["registrado"])
    return c["mes"] if c["mes"] is not None else c.get("tope_razonable_mes", 300)


def tiene(plan, derecho):
    return derecho in DERECHOS.get(plan, frozenset())


def es_suscripcion(plan):
    return plan in ("profesional", "premium")


def comprable(plan, periodo):
    return precio(plan, periodo) is not None
