# encoding: utf-8
"""
Pago con Stripe para los planes (2026-11-26, encargo de César). SOLO Stripe Checkout (la página de pago de Stripe:
aquí no se pide ni se ve ninguna tarjeta) y el Portal del cliente de Stripe para cambiar o cancelar la suscripción.

Sin SDK de Stripe (nada nuevo en requirements.txt): llamadas HTTP con `requests`, que ya está. Las pruebas pasan un
`http` simulado y no llaman nunca a Stripe.

Claves: SOLO en variables de entorno de Render, nunca en el código ni en el repositorio:
  STRIPE_SECRET_KEY        sk_test_... (modo prueba) — la que llama a la API
  STRIPE_PUBLISHABLE_KEY   pk_test_... — no hace falta para Checkout, pero se exige para no encender a medias
  STRIPE_WEBHOOK_SECRET    whsec_... — la firma de los avisos (webhook)
Si falta cualquiera de las tres, el pago no está «configurado» y la web no enseña ningún botón de pago.

SEGURO DE MODO PRUEBA: una clave real (sk_live_/pk_live_) se IGNORA (= sin configurar) salvo que además esté
STRIPE_MODO_REAL=1. Así, encender los planes con las claves equivocadas no cobra a nadie de verdad. Lo mismo con los
avisos: uno de modo real (livemode) sin STRIPE_MODO_REAL=1 se registra y no da nada.

Nada se da por pagado sin el aviso firmado de Stripe (webhook): volver de Checkout a la página de «gracias» no cambia
nada; el plan o el bono se apuntan solo al llegar checkout.session.completed / invoice.paid con la firma buena.

Opcionales:
  STRIPE_TASA_IVA          id de una tasa de impuesto de Stripe (txr_...). Con PLANES_IVA_PCT puesto, Checkout la
                           aplica (factura con el IVA desglosado). Sin ella, el IVA se suma al precio.
  STRIPE_PRECIO_<PLAN>_<PERIODO>   (p. ej. STRIPE_PRECIO_PROFESIONAL_MES=price_...): usar un precio creado en el
                           panel de Stripe en vez del que sale de planes.py. Hace falta para que el Portal deje CAMBIAR
                           de plan (cancelar funciona sin ellos).
"""
import hashlib
import hmac
import json
import os
import time

try:
    from . import planes as PL
except ImportError:
    import planes as PL

API = "https://api.stripe.com/v1"
TOLERANCIA_FIRMA_S = 300
INTERVALOS = {"mes": "month", "anio": "year"}
_PERIODO_DE_INTERVALO = {"month": "mes", "year": "anio"}


class ErrorStripe(Exception):
    pass


def _env(entorno):
    return os.environ if entorno is None else entorno


def _clave_valida(valor, prefijo, real):
    if not valor:
        return False
    if valor.startswith(prefijo + "test_"):
        return True
    return real and valor.startswith(prefijo + "live_")


def modo_real(entorno=None):
    return (_env(entorno).get("STRIPE_MODO_REAL") or "").strip() == "1"


def configurado(entorno=None):
    """¿Están las tres claves (y, si son reales, STRIPE_MODO_REAL=1)?"""
    e = _env(entorno)
    real = modo_real(e)
    return (_clave_valida((e.get("STRIPE_SECRET_KEY") or "").strip(), "sk_", real)
            and _clave_valida((e.get("STRIPE_PUBLISHABLE_KEY") or "").strip(), "pk_", real)
            and (e.get("STRIPE_WEBHOOK_SECRET") or "").strip().startswith("whsec_"))


def en_modo_prueba(entorno=None):
    return (_env(entorno).get("STRIPE_SECRET_KEY") or "").strip().startswith("sk_test_")


def _llamar(metodo, ruta, datos, entorno, http):
    if not configurado(entorno):
        raise ErrorStripe("Stripe sin configurar")
    if http is None:
        import requests
        http = requests.request
    r = http(metodo, API + ruta, data=datos, timeout=20,
             headers={"Authorization": "Bearer " + _env(entorno)["STRIPE_SECRET_KEY"].strip(),
                      "Stripe-Version": "2024-06-20"})
    try:
        cuerpo = r.json()
    except ValueError:
        cuerpo = {}
    if r.status_code >= 300:
        msg = (cuerpo.get("error") or {}).get("message") or f"HTTP {r.status_code}"
        raise ErrorStripe(msg[:200])
    return cuerpo


def _precio_panel(plan, periodo, entorno):
    return (_env(entorno).get(f"STRIPE_PRECIO_{plan.upper()}_{periodo.upper()}") or "").strip()


def datos_checkout(usuario, plan, periodo, url_ok, url_cancelar, entorno=None):
    """Los parámetros (form de Stripe) de la sesión de Checkout. Aparte para poder probarlos sin red."""
    if not PL.comprable(plan, periodo):
        raise ValueError(f"{plan}/{periodo}")
    suscripcion = PL.es_suscripcion(plan)
    e = _env(entorno)
    meta = {"usuario_id": str(usuario["id"]), "plan": plan, "periodo": periodo}
    d = {"mode": "subscription" if suscripcion else "payment", "client_reference_id": str(usuario["id"]),
         "success_url": url_ok, "cancel_url": url_cancelar, "locale": "es", "line_items[0][quantity]": "1"}
    for k, v in meta.items():
        d[f"metadata[{k}]"] = v
        d[f"{'subscription_data' if suscripcion else 'payment_intent_data'}[metadata][{k}]"] = v
    if usuario.get("stripe_cliente"):
        d["customer"] = usuario["stripe_cliente"]
    else:
        d["customer_email"] = usuario["correo"]
        if not suscripcion:
            d["customer_creation"] = "always"
    panel = _precio_panel(plan, periodo, e)
    tasa = (e.get("STRIPE_TASA_IVA") or "").strip() if PL.iva_pct(e) else ""
    if panel:
        d["line_items[0][price]"] = panel
    else:
        base = PL.precio(plan, periodo)
        d["line_items[0][price_data][currency]"] = "eur"
        d["line_items[0][price_data][unit_amount]"] = str(base if tasa or not PL.iva_pct(e) else PL.con_iva(base, e))
        d["line_items[0][price_data][product_data][name]"] = "Dinero Público · " + PL.NOMBRES[plan]
        d["line_items[0][price_data][product_data][metadata][plan]"] = plan
        if suscripcion:
            d["line_items[0][price_data][recurring][interval]"] = INTERVALOS[periodo]
    if tasa:
        d["line_items[0][tax_rates][0]"] = tasa
    return d


def crear_checkout(usuario, plan, periodo, url_ok, url_cancelar, entorno=None, http=None):
    """URL de la página de pago de Stripe."""
    s = _llamar("POST", "/checkout/sessions", datos_checkout(usuario, plan, periodo, url_ok, url_cancelar, entorno),
                entorno, http)
    if not s.get("url"):
        raise ErrorStripe("Stripe no ha devuelto la página de pago")
    return s["url"]


def crear_portal(cliente, url_vuelta, entorno=None, http=None):
    """URL del Portal del cliente (cambiar o cancelar la suscripción, facturas, tarjeta)."""
    s = _llamar("POST", "/billing_portal/sessions", {"customer": cliente, "return_url": url_vuelta}, entorno, http)
    return s["url"]


def cancelar_suscripcion(sub_id, entorno=None, http=None):
    """Cancela YA (al borrar la cuenta: que no se le siga cobrando)."""
    return _llamar("DELETE", f"/subscriptions/{sub_id}", {}, entorno, http)


# ── avisos firmados (webhook) ───────────────────────────────────────────────────────────────────────────────────
def verificar_firma(cuerpo, cabecera, secreto, ahora=None, tolerancia=TOLERANCIA_FIRMA_S):
    """El evento (dict) si la cabecera Stripe-Signature es buena para ESTE cuerpo; si no, ErrorStripe.
    Esquema de Stripe: t=<segundos>,v1=<hmac-sha256 hex de "t.cuerpo" con el secreto>."""
    if not secreto:
        raise ErrorStripe("sin secreto del webhook")
    ahora = time.time() if ahora is None else ahora
    partes = {}
    for trozo in (cabecera or "").split(","):
        k, _, v = trozo.strip().partition("=")
        partes.setdefault(k, []).append(v)
    try:
        t = int(partes.get("t", [""])[0])
    except ValueError:
        raise ErrorStripe("firma sin hora")
    if abs(ahora - t) > tolerancia:
        raise ErrorStripe("firma caducada")
    esperada = hmac.new(secreto.encode(), f"{t}.".encode() + cuerpo, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(esperada, v) for v in partes.get("v1", [])):
        raise ErrorStripe("firma no válida")
    try:
        return json.loads(cuerpo.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ErrorStripe("cuerpo no válido")


def _uid(obj, alm):
    meta = obj.get("metadata") or {}
    for v in (obj.get("client_reference_id"), meta.get("usuario_id")):
        if v and str(v).isdigit():
            return int(v)
    for buscar, campo in ((alm.usuario_por_suscripcion, obj.get("id") if obj.get("object") == "subscription" else None),
                          (alm.usuario_por_suscripcion, obj.get("subscription")),
                          (alm.usuario_por_cliente, obj.get("customer"))):
        u = buscar(campo) if campo and isinstance(campo, str) else None
        if u:
            return u["id"]
    return None


def usuario_del_evento(ev, alm):
    """Número de usuario al que se refiere un evento (o None)."""
    return _uid((ev.get("data") or {}).get("object") or {}, alm)


def _plan_de_suscripcion(sub, entorno):
    """(plan, periodo) de una suscripción: por los metadatos del precio/producto, por el id del precio del panel o,
    si no, por sus metadatos (los que puso Checkout)."""
    item = ((sub.get("items") or {}).get("data") or [{}])[0]
    precio = item.get("price") or {}
    periodo = _PERIODO_DE_INTERVALO.get((precio.get("recurring") or {}).get("interval"), "")
    e = _env(entorno)
    for plan in ("profesional", "premium"):
        for per in PL.PERIODOS:
            if precio.get("id") and precio.get("id") == _precio_panel(plan, per, e):
                return plan, per
    plan = (precio.get("metadata") or {}).get("plan") or (sub.get("metadata") or {}).get("plan") or ""
    if not periodo:
        periodo = (sub.get("metadata") or {}).get("periodo", "")
    return plan, periodo


def _fin_periodo(sub):
    item = ((sub.get("items") or {}).get("data") or [{}])[0]
    return sub.get("current_period_end") or item.get("current_period_end")


def procesar_evento(ev, alm, entorno=None, ahora=None):
    """Aplica un evento ya verificado. Devuelve un texto corto con lo hecho (para el registro, sin datos de nadie).
    Idempotente: el mismo evento dos veces solo cuenta una."""
    ahora = time.time() if ahora is None else ahora
    tipo, obj, eid = ev.get("type", ""), (ev.get("data") or {}).get("object") or {}, ev.get("id", "")
    if not eid:
        return "sin id"
    if ev.get("livemode") and not modo_real(entorno):
        alm.registrar_pago(eid, tipo, None, detalle="ignorado: modo real sin STRIPE_MODO_REAL", ahora=ahora)
        return "ignorado (modo real)"
    if alm.pago_ya_visto(eid):
        return "repetido"
    uid = _uid(obj, alm)
    if tipo == "checkout.session.completed":
        meta = obj.get("metadata") or {}
        plan, periodo = meta.get("plan", ""), meta.get("periodo", "")
        if obj.get("payment_status") != "paid" or uid is None or not alm.usuario(uid):
            alm.registrar_pago(eid, tipo, uid, plan, periodo, obj.get("amount_total"), obj.get("currency") or "",
                               "sin pagar o sin usuario", ahora)
            return "sin efecto"
        if (obj.get("currency") or "").lower() != "eur" or (obj.get("amount_subtotal") or 0) < (PL.precio(plan, periodo) or 10 ** 9):
            alm.registrar_pago(eid, tipo, uid, plan, periodo, obj.get("amount_total"), obj.get("currency") or "",
                               "importe que no cuadra: no se da nada", ahora)
            return "importe no cuadra"
        if not alm.registrar_pago(eid, tipo, uid, plan, periodo, obj.get("amount_total"), "eur", "", ahora):
            return "repetido"
        if obj.get("customer"):
            alm.poner_cliente(uid, obj["customer"])
        if obj.get("mode") == "payment" and plan == "bono":
            alm.sumar_bono(uid, ahora)
            return "bono sumado"
        if obj.get("mode") == "subscription" and PL.es_suscripcion(plan) and periodo in PL.PERIODOS:
            # hasta: provisional (un periodo); invoice.paid / customer.subscription.* lo ponen exacto
            dur = 31 * 86400 if periodo == "mes" else 366 * 86400
            alm.poner_suscripcion(uid, plan, periodo, ahora + dur, obj.get("customer"), obj.get("subscription"))
            return "suscripción activada"
        return "sin efecto"
    if tipo in ("customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"):
        if uid is None or not alm.usuario(uid):
            alm.registrar_pago(eid, tipo, None, detalle="sin usuario", ahora=ahora)
            return "sin usuario"
        alm.registrar_pago(eid, tipo, uid, ahora=ahora)
        estado = obj.get("status", "")
        if tipo == "customer.subscription.deleted" or estado in ("canceled", "unpaid", "incomplete_expired"):
            u = alm.usuario(uid)
            if u and u["stripe_suscripcion"] in (None, obj.get("id")):
                alm.quitar_suscripcion(uid)
            return "suscripción terminada"
        if estado in ("active", "trialing", "past_due"):
            plan, periodo = _plan_de_suscripcion(obj, entorno)
            if PL.es_suscripcion(plan) and periodo in PL.PERIODOS and _fin_periodo(obj):
                alm.poner_suscripcion(uid, plan, periodo, float(_fin_periodo(obj)), obj.get("customer"), obj.get("id"))
                return "suscripción al día"
        return "sin efecto"
    if tipo in ("invoice.paid", "invoice.payment_failed"):
        alm.registrar_pago(eid, tipo, uid, importe=obj.get("amount_paid") if tipo == "invoice.paid" else obj.get("amount_due"),
                           moneda=obj.get("currency") or "", ahora=ahora)
        if tipo == "invoice.paid" and uid is not None:
            u = alm.usuario(uid)
            lineas = (obj.get("lines") or {}).get("data") or []
            fin = max([((l.get("period") or {}).get("end") or 0) for l in lineas] or [0])
            if u and PL.es_suscripcion(u["plan"]) and fin:
                alm.poner_suscripcion(uid, u["plan"], u["periodo"], float(fin))
                return "periodo pagado"
        return "anotado"
    alm.registrar_pago(eid, tipo, uid, detalle="no usado", ahora=ahora)
    return "no usado"
