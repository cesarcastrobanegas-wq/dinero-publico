# encoding: utf-8
"""Pruebas SIN RED de los planes, el registro de usuarios, el pago con Stripe (simulado) y los informes PDF
(2026-11-26). Nunca llaman a Stripe ni a Resend: Stripe va con avisos firmados aquí mismo y respuestas simuladas, y
los correos se capturan antes de salir. Correos de prueba: solo @example.com.

  1. Módulos sueltos (rápido): planes.py, cuentas.py, pagos_stripe.py, informe_pdf.py.
  2. La web (importa app.py con la red cortada y DATA_DIR en una carpeta temporal; proceso pesado, de uno en uno):
     apagado = igual que ahora; registro con enlace; borrar la cuenta; contador de informes; aviso de pago único y
     de suscripción; sin claves = sin botones; PLANES_SOLO_CORREOS.

    python backend/prueba_planes.py            (todo)
    python backend/prueba_planes.py --rapido   (solo los módulos, sin importar app.py)
"""
import hashlib
import hmac
import json
import os
import re
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from io import BytesIO
from unittest import mock

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import cuentas as CTA          # noqa: E402
import informe_pdf as IPDF     # noqa: E402
import pagos_stripe as STP     # noqa: E402
import planes as PL            # noqa: E402

CLAVES_PRUEBA = {"STRIPE_SECRET_KEY": "sk_test_inventada", "STRIPE_PUBLISHABLE_KEY": "pk_test_inventada",
                 "STRIPE_WEBHOOK_SECRET": "whsec_inventado"}
CORREO = "usuario@example.com"


def ts(anio, mes, dia, h=12):
    return datetime(anio, mes, dia, h, tzinfo=timezone.utc).timestamp()


def firmar(cuerpo, secreto="whsec_inventado", t=None):
    t = int(time.time()) if t is None else t
    return f"t={t},v1=" + hmac.new(secreto.encode(), f"{t}.".encode() + cuerpo, hashlib.sha256).hexdigest()


class Almacen(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.alm = CTA.Almacen(os.path.join(self.tmp.name, "usuarios.db"))

    def tearDown(self):
        self.alm.db.close()
        self.tmp.cleanup()

    def alta(self, ahora=None):
        u, nueva = self.alm.alta_o_entrada(CORREO, "c1", "p1", ahora=ahora)
        self.assertTrue(nueva)
        return u


class T1Planes(unittest.TestCase):
    def test_precios_en_un_sitio(self):
        self.assertEqual(PL.euros(999), "9,99 €")
        self.assertEqual(PL.euros(29000), "290 €")
        self.assertEqual(PL.euros(149000), "1.490 €")
        self.assertEqual(PL.precio("profesional", "mes"), 2900)
        self.assertEqual(PL.precio("premium", "anio"), 149000)
        self.assertIsNone(PL.precio("datos", "unico"))           # datos: sin pago en la web
        self.assertEqual(PL.cupo_mes("registrado"), 1)
        self.assertEqual(PL.cupo_mes("profesional"), 10)
        self.assertIsNone(PL.cupo_mes("premium"))

    def test_iva_apagado_por_defecto(self):
        self.assertEqual(PL.iva_pct({}), 0)
        self.assertEqual(PL.con_iva(2900, {}), 2900)
        self.assertEqual(PL.con_iva(2900, {"PLANES_IVA_PCT": "21"}), 3509)
        self.assertEqual(PL.iva_pct({"PLANES_IVA_PCT": "disparate"}), 0)


class T2Cuentas(Almacen):
    def test_mes_empieza_el_dia_del_alta(self):
        alta = ts(2026, 1, 31)
        self.assertEqual(datetime.fromtimestamp(CTA.inicio_mes(alta, ts(2026, 3, 5)), timezone.utc).day, 28)   # feb
        self.assertEqual(datetime.fromtimestamp(CTA.inicio_mes(alta, ts(2026, 3, 31, 13)), timezone.utc).month, 3)
        self.assertEqual(CTA.inicio_mes(alta, alta + 60), alta)

    def test_enlace_un_solo_uso_y_15_minutos(self):
        ahora = ts(2026, 11, 26)
        c = self.alm.crear_enlace(CORREO, "entrar", ahora=ahora)
        self.assertNotIn(c, json.dumps(self.alm.db.execute("SELECT * FROM enlaces").fetchall()))   # solo la huella
        self.assertIsNotNone(self.alm.ver_enlace(c, "entrar", ahora + 60))
        self.assertIsNone(self.alm.ver_enlace(c, "borrar", ahora + 60))                            # otra acción
        self.assertIsNotNone(self.alm.gastar_enlace(c, "entrar", ahora + 60))
        self.assertIsNone(self.alm.gastar_enlace(c, "entrar", ahora + 61))                         # ya gastado
        c2 = self.alm.crear_enlace(CORREO, "entrar", ahora=ahora)
        self.assertIsNone(self.alm.gastar_enlace(c2, "entrar", ahora + 15 * 60 + 1))               # caducado

    def test_limite_de_intentos(self):
        ahora = ts(2026, 11, 26)
        for _ in range(CTA.INTENTOS_CORREO_HORA):
            self.assertTrue(self.alm.intento_permitido(CORREO, "192.0.2.1", ahora))
        self.assertFalse(self.alm.intento_permitido(CORREO, "192.0.2.1", ahora))
        self.assertTrue(self.alm.intento_permitido(CORREO, "192.0.2.1", ahora + 3601))             # pasada la hora
        for i in range(CTA.INTENTOS_IP_HORA - 1):
            self.alm.intento_permitido(f"otro{i}@example.com", "192.0.2.9", ahora)
        self.assertTrue(self.alm.intento_permitido("ultimo@example.com", "192.0.2.9", ahora))
        self.assertFalse(self.alm.intento_permitido("uno-mas@example.com", "192.0.2.9", ahora))
        crudo = json.dumps(self.alm.db.execute("SELECT * FROM intentos").fetchall())
        self.assertNotIn("192.0.2", crudo)
        self.assertNotIn("example.com", crudo)

    def test_lo_minimo_y_la_version_aceptada(self):
        u = self.alta(ts(2026, 11, 26))
        self.assertEqual((u["condiciones_version"], u["privacidad_version"]), ("c1", "p1"))
        columnas = {r[1] for r in self.alm.db.execute("PRAGMA table_info(usuarios)")}
        for prohibida in ("telefono", "dni", "nif", "direccion", "nombre", "contrasena", "password", "ip"):
            self.assertNotIn(prohibida, columnas)
        self.assertIsNone(self.alm.db.execute("SELECT name FROM sqlite_master WHERE name='facturacion'").fetchone())
        u2, nueva = self.alm.alta_o_entrada(CORREO.upper(), "c2", "p2")
        self.assertFalse(nueva)
        self.assertEqual(u2["id"], u["id"])

    def test_contador_registrado(self):
        alta = ts(2026, 11, 26)
        u = self.alta(alta)
        self.assertEqual(self.alm.gastar_informe(u["id"], "municipio", "a|x", "A", alta + 10), "mes")
        self.assertEqual(self.alm.gastar_informe(u["id"], "municipio", "a|x", "A", alta + 20), "repetido")
        self.assertIsNone(self.alm.gastar_informe(u["id"], "municipio", "b|x", "B", alta + 30))
        self.assertIsNone(self.alm.gastar_informe(u["id"], "empresa", "B12345678", "E", alta + 30))   # sin bono
        self.assertEqual(self.alm.gastar_informe(u["id"], "municipio", "b|x", "B", ts(2026, 12, 26, 13)), "mes")
        c = self.alm.cuenta_informes(self.alm.usuario(u["id"]), ts(2026, 12, 27))
        self.assertEqual((c["cupo_mes"], c["usados_mes"], c["quedan_mes"]), (1, 1, 0))

    def test_bono_cinco_doce_meses_y_despues_del_mes(self):
        alta = ts(2026, 11, 26)
        u = self.alta(alta)
        self.alm.sumar_bono(u["id"], alta)
        self.assertEqual(self.alm.gastar_informe(u["id"], "empresa", "B12345678", "E", alta + 5), "bono")   # empresa: bono
        self.assertEqual(self.alm.gastar_informe(u["id"], "municipio", "a|x", "A", alta + 6), "mes")       # el del mes primero
        self.assertEqual(self.alm.gastar_informe(u["id"], "municipio", "b|x", "B", alta + 7), "bono")
        self.assertEqual(self.alm.bono_vigente(self.alm.usuario(u["id"]), alta + 8), PL.BONO_INFORMES - 2)
        self.assertEqual(self.alm.bono_vigente(self.alm.usuario(u["id"]), alta + 366 * 86400), 0)          # caducado

    def test_suscripcion_y_gracia(self):
        alta = ts(2026, 11, 26)
        u = self.alta(alta)
        self.alm.poner_suscripcion(u["id"], "profesional", "mes", alta + 30 * 86400, "cus_x", "sub_x")
        u = self.alm.usuario(u["id"])
        self.assertEqual(self.alm.plan_vigente(u, alta + 31 * 86400), "profesional")       # gracia de 3 días
        self.assertEqual(self.alm.plan_vigente(u, alta + 34 * 86400), "registrado")
        self.assertEqual(self.alm.vencidas(alta + 34 * 86400), [u["id"]])
        self.assertEqual(self.alm.usuario(u["id"])["plan"], "registrado")

    def test_borrar_cuenta_lo_borra_todo(self):
        u = self.alta()
        uid = u["id"]
        self.alm.crear_sesion(uid)
        self.alm.poner_favorito(uid, "municipio", "a|x", "A")
        self.alm.gastar_informe(uid, "municipio", "a|x", "A")
        self.alm.registrar_pago("evt_1", "checkout.session.completed", uid, "bono", "unico", 999, "eur")
        self.alm.crear_enlace(CORREO, "borrar")
        self.assertTrue(self.alm.borrar_cuenta(uid))
        for tabla in ("usuarios", "sesiones", "favoritos", "descargas", "enlaces"):
            self.assertEqual(self.alm.db.execute(f"SELECT count(*) FROM {tabla}").fetchone()[0], 0, tabla)
        self.assertEqual(self.alm.db.execute("SELECT usuario_id, importe FROM pagos").fetchall(), [(None, 999)])


class T3Stripe(Almacen):
    def test_sin_claves_o_con_claves_reales_no_esta_configurado(self):
        self.assertFalse(STP.configurado({}))
        self.assertTrue(STP.configurado(CLAVES_PRUEBA))
        reales = {"STRIPE_SECRET_KEY": "sk_live_x", "STRIPE_PUBLISHABLE_KEY": "pk_live_x", "STRIPE_WEBHOOK_SECRET": "whsec_x"}
        self.assertFalse(STP.configurado(reales))
        self.assertTrue(STP.configurado(dict(reales, STRIPE_MODO_REAL="1")))
        sin_webhook = dict(CLAVES_PRUEBA)
        del sin_webhook["STRIPE_WEBHOOK_SECRET"]
        self.assertFalse(STP.configurado(sin_webhook))

    def test_datos_de_checkout(self):
        u = {"id": 7, "correo": CORREO, "stripe_cliente": None}
        d = STP.datos_checkout(u, "bono", "unico", "https://x/ok", "https://x/no", CLAVES_PRUEBA)
        self.assertEqual((d["mode"], d["line_items[0][price_data][unit_amount]"], d["client_reference_id"]), ("payment", "999", "7"))
        self.assertNotIn("line_items[0][price_data][recurring][interval]", d)
        d = STP.datos_checkout(u, "premium", "anio", "https://x/ok", "https://x/no", CLAVES_PRUEBA)
        self.assertEqual((d["mode"], d["line_items[0][price_data][recurring][interval]"]), ("subscription", "year"))
        self.assertEqual(d["subscription_data[metadata][usuario_id]"], "7")
        d = STP.datos_checkout(u, "profesional", "mes", "o", "n", dict(CLAVES_PRUEBA, PLANES_IVA_PCT="21"))
        self.assertEqual(d["line_items[0][price_data][unit_amount]"], "3509")
        with self.assertRaises(ValueError):
            STP.datos_checkout(u, "datos", "unico", "o", "n", CLAVES_PRUEBA)

    def test_checkout_con_http_simulado(self):
        llamadas = []

        class R:
            status_code = 200

            def json(self):
                return {"url": "https://checkout.stripe.com/c/pay/inventada"}

        def http(metodo, url, data=None, timeout=None, headers=None):
            llamadas.append((metodo, url, data, headers))
            return R()
        with mock.patch.dict(os.environ, CLAVES_PRUEBA):
            url = STP.crear_checkout({"id": 1, "correo": CORREO, "stripe_cliente": None}, "bono", "unico", "o", "n", http=http)
        self.assertTrue(url.startswith("https://checkout.stripe.com/"))
        self.assertEqual(llamadas[0][1], "https://api.stripe.com/v1/checkout/sessions")
        self.assertEqual(llamadas[0][3]["Authorization"], "Bearer sk_test_inventada")

    def test_firma(self):
        cuerpo = b'{"id":"evt_1","type":"x"}'
        self.assertEqual(STP.verificar_firma(cuerpo, firmar(cuerpo), "whsec_inventado")["id"], "evt_1")
        for cab in (firmar(cuerpo, "whsec_otro"), firmar(cuerpo, t=int(time.time()) - 3600), "", "t=1"):
            with self.assertRaises(STP.ErrorStripe):
                STP.verificar_firma(cuerpo, cab, "whsec_inventado")
        with self.assertRaises(STP.ErrorStripe):
            STP.verificar_firma(cuerpo + b" ", firmar(cuerpo), "whsec_inventado")     # cuerpo cambiado

    def ev(self, eid, tipo, obj, livemode=False):
        return {"id": eid, "type": tipo, "livemode": livemode, "data": {"object": obj}}

    def test_pago_unico(self):
        uid = self.alta()["id"]
        sesion = {"object": "checkout.session", "mode": "payment", "payment_status": "paid", "client_reference_id": str(uid),
                  "metadata": {"usuario_id": str(uid), "plan": "bono", "periodo": "unico"}, "amount_subtotal": 999,
                  "amount_total": 999, "currency": "eur", "customer": "cus_1"}
        self.assertEqual(STP.procesar_evento(self.ev("evt_a", "checkout.session.completed", sesion), self.alm, CLAVES_PRUEBA), "bono sumado")
        self.assertEqual(STP.procesar_evento(self.ev("evt_a", "checkout.session.completed", sesion), self.alm, CLAVES_PRUEBA), "repetido")
        self.assertEqual(self.alm.usuario(uid)["bono_restantes"], PL.BONO_INFORMES)
        sin_pagar = dict(sesion, payment_status="unpaid")
        STP.procesar_evento(self.ev("evt_b", "checkout.session.completed", sin_pagar), self.alm, CLAVES_PRUEBA)
        barato = dict(sesion, amount_subtotal=1)
        self.assertEqual(STP.procesar_evento(self.ev("evt_c", "checkout.session.completed", barato), self.alm, CLAVES_PRUEBA), "importe no cuadra")
        real = STP.procesar_evento(self.ev("evt_d", "checkout.session.completed", sesion, livemode=True), self.alm, CLAVES_PRUEBA)
        self.assertEqual(real, "ignorado (modo real)")
        self.assertEqual(self.alm.usuario(uid)["bono_restantes"], PL.BONO_INFORMES)        # nada más

    def test_suscripcion(self):
        uid = self.alta()["id"]
        sesion = {"object": "checkout.session", "mode": "subscription", "payment_status": "paid", "client_reference_id": str(uid),
                  "metadata": {"usuario_id": str(uid), "plan": "profesional", "periodo": "anio"}, "amount_subtotal": 29000,
                  "amount_total": 29000, "currency": "eur", "customer": "cus_2", "subscription": "sub_2"}
        self.assertEqual(STP.procesar_evento(self.ev("evt_1", "checkout.session.completed", sesion), self.alm, CLAVES_PRUEBA), "suscripción activada")
        u = self.alm.usuario(uid)
        self.assertEqual((u["plan"], u["periodo"], u["stripe_suscripcion"]), ("profesional", "anio", "sub_2"))
        fin = int(time.time()) + 365 * 86400
        sub = {"object": "subscription", "id": "sub_2", "customer": "cus_2", "status": "active",
               "metadata": {"usuario_id": str(uid), "plan": "profesional", "periodo": "anio"},
               "items": {"data": [{"current_period_end": fin, "price": {"id": "price_x", "recurring": {"interval": "year"},
                                                                         "metadata": {"plan": "premium"}}}]}}
        self.assertEqual(STP.procesar_evento(self.ev("evt_2", "customer.subscription.updated", sub), self.alm, CLAVES_PRUEBA), "suscripción al día")
        u = self.alm.usuario(uid)
        self.assertEqual((u["plan"], int(u["plan_hasta"])), ("premium", fin))           # cambio de plan en el Portal
        factura = {"object": "invoice", "subscription": "sub_2", "customer": "cus_2", "amount_paid": 149000, "currency": "eur",
                   "lines": {"data": [{"period": {"end": fin + 100}}]}}
        self.assertEqual(STP.procesar_evento(self.ev("evt_3", "invoice.paid", factura), self.alm, CLAVES_PRUEBA), "periodo pagado")
        self.assertEqual(int(self.alm.usuario(uid)["plan_hasta"]), fin + 100)
        self.assertEqual(STP.procesar_evento(self.ev("evt_4", "customer.subscription.deleted", dict(sub, status="canceled")),
                                             self.alm, CLAVES_PRUEBA), "suscripción terminada")
        self.assertEqual(self.alm.usuario(uid)["plan"], "registrado")


class T4Pdf(unittest.TestCase):
    def test_pdf_valido_con_enlaces(self):
        d = IPDF.Documento("Prueba", pie="pie")
        d.titulo("Villaejemplo — «Ñ» 1.234,56 € 🚩")
        d.tabla(["A", "B"], [[str(i), "texto " * 30] for i in range(120)], [60, 400], enlaces=["https://example.com/x"] * 120)
        d.enlace("Fuente", "https://example.com/fuente")
        pdf = d.bytes()
        self.assertTrue(pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF"))
        self.assertIn(b"/URI (https://example.com/fuente)", pdf)
        xref = int(re.search(rb"startxref\n(\d+)", pdf).group(1))
        self.assertTrue(pdf[xref:].startswith(b"xref"))
        try:
            import pypdf
        except ImportError:
            return
        r = pypdf.PdfReader(BytesIO(pdf))
        self.assertGreater(len(r.pages), 2)
        self.assertIn("Villaejemplo", r.pages[0].extract_text())


# ─── 2. La web ─────────────────────────────────────────────────────────────────────────────────────────────────────
app = None
TMP = None


def cargar_app():
    global app, TMP
    if app is None:
        TMP = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        os.environ.update(DATA_DIR=TMP.name, HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9")
        for k in ("PLANES_ACTIVOS", "PLANES_SOLO_CORREOS", "STRIPE_SECRET_KEY", "STRIPE_PUBLISHABLE_KEY",
                  "STRIPE_WEBHOOK_SECRET", "PLANES_IVA_PCT", "ALERTAS_ACTIVAS"):
            os.environ.pop(k, None)
        import app as _app
        app = _app
    return app


def pedir(metodo, ruta, datos=None, cookie="", cuerpo=None, cabeceras=None):
    """(código, cabeceras, cuerpo) de una petición a la app WSGI, como la haría gunicorn."""
    ruta, _, query = ruta.partition("?")
    if cuerpo is None:
        cuerpo = (app.urlencode(datos or {}) if datos is not None else "").encode()
    env = {"REQUEST_METHOD": metodo, "PATH_INFO": ruta, "QUERY_STRING": query, "REMOTE_ADDR": "192.0.2.10",
           "HTTP_USER_AGENT": "Mozilla/5.0 (prueba)", "HTTP_COOKIE": cookie, "CONTENT_LENGTH": str(len(cuerpo)),
           "wsgi.input": BytesIO(cuerpo), "CONTENT_TYPE": "application/x-www-form-urlencoded"}
    env.update(cabeceras or {})
    out = {}

    def sr(estado, cab, exc=None):
        out["codigo"], out["cab"] = int(estado[:3]), dict(cab)
    trozos = app.app(env, sr)
    return out["codigo"], out["cab"], b"".join(trozos)


def guardar_pdf(nombre, pdf):
    """Con PRUEBA_PLANES_PDF=<carpeta>, guarda los PDF de prueba para mirarlos (datos inventados)."""
    carpeta = os.environ.get("PRUEBA_PLANES_PDF")
    if carpeta:
        with open(os.path.join(carpeta, f"prueba-{nombre}" + ("" if nombre.endswith(".html") else ".pdf")), "wb") as f:
            f.write(pdf)


class Web(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cargar_app()

    def setUp(self):
        self.correos = []
        self.p = [mock.patch.object(app, "_alertas_enviar", lambda alm, payload, clase, sid, *a: self.correos.append((clase, payload)) or True),
                  mock.patch.object(app, "_planes_mandar", lambda payload, clase: self.correos.append((clase, payload)))]
        for x in self.p:
            x.start()

    def tearDown(self):
        for x in self.p:
            x.stop()

    def encender(self, solo=frozenset(), claves=False):
        ps = [mock.patch.object(app, "PLANES_ACTIVOS", True), mock.patch.object(app, "PLANES_SOLO_CORREOS", solo),
              mock.patch.object(app, "PLANES_PUBLICOS", not solo)]
        if claves:
            ps.append(mock.patch.dict(os.environ, CLAVES_PRUEBA))
        for x in ps:
            x.start()
            self.addCleanup(x.stop)

    def entrar(self, correo=CORREO):
        n = len(self.correos)
        c, cab, _ = pedir("POST", "/cuenta/acceso", {"correo": correo, "condiciones": "1", "privacidad": "1", "idioma": "es"})
        self.assertEqual((c, cab["Location"]), (303, "/cuenta/revisa"))
        if len(self.correos) == n:
            return None
        texto = self.correos[-1][1]["text"]
        codigo = re.search(r"/cuenta/entrar\?c=([A-Za-z0-9_\-]+)", texto).group(1)
        c, _, cuerpo = pedir("GET", "/cuenta/entrar?c=" + codigo)
        self.assertEqual(c, 200)
        self.assertIn(b'id="auto"', cuerpo)                       # formulario que se envía solo (POST)
        c, cab, _ = pedir("POST", "/cuenta/entrar", {"c": codigo})
        self.assertEqual(c, 303)
        self.assertIn("HttpOnly", cab["Set-Cookie"])
        self.assertIn("Secure", cab["Set-Cookie"])
        c2, _, cuerpo2 = pedir("POST", "/cuenta/entrar", {"c": codigo})
        self.assertIn("no vale".encode(), cuerpo2)                # un solo uso
        return cab["Set-Cookie"].split(";")[0]

    def csrf(self, cookie):
        _, _, cuerpo = pedir("GET", "/cuenta", cookie=cookie)
        return re.search(rb'name="t" value="([0-9a-f]+)"', cuerpo).group(1).decode()


class T5Apagado(Web):
    def test_apagado_la_web_igual(self):
        self.assertFalse(app.PLANES_ACTIVOS)
        for ruta in ("/planes", "/cuenta", "/cuenta/revisa", "/informe/municipio?muni=X", "/gl/planes"):
            self.assertEqual(pedir("GET", ruta)[0], 404, ruta)
        self.assertEqual(pedir("POST", "/cuenta/acceso", {"correo": CORREO, "condiciones": "1", "privacidad": "1"})[0], 404)
        cuerpo = b'{"id":"evt_x","type":"checkout.session.completed"}'
        with mock.patch.dict(os.environ, CLAVES_PRUEBA):
            c, _, _ = pedir("POST", "/planes/stripe-webhook", cuerpo=cuerpo, cabeceras={"HTTP_STRIPE_SIGNATURE": firmar(cuerpo)})
        self.assertNotEqual(c, 200)
        self.assertEqual(app._planes_pie_html(), "")
        self.assertNotIn('href="/planes"', app._footer_html())
        self.assertEqual(app._planes_ficha_html("municipio", "x|y", "X", "y"), "")
        self.assertEqual(self.correos, [])
        self.assertFalse(os.path.exists(os.path.join(TMP.name, "usuarios.db")))     # ni se crea la base


class T6Registro(Web):
    def test_registro_entrar_y_salir(self):
        self.encender()
        cookie = self.entrar()
        c, cab, cuerpo = pedir("GET", "/cuenta", cookie=cookie)
        self.assertEqual(c, 200)
        self.assertIn("no-store", cab["Cache-Control"])
        self.assertIn(b"us***@example.com", cuerpo)
        self.assertNotIn(CORREO.encode(), cuerpo)                 # el correo, tapado
        self.assertIn("Te quedan 1 de 1 informes".encode(), cuerpo)
        u = app._cuentas_almacen().usuario_por_correo(CORREO)
        self.assertEqual(u["condiciones_version"], app.PLANES_VERSION_CONDICIONES)
        c, cab, _ = pedir("POST", "/cuenta/salir", {"t": self.csrf(cookie)}, cookie=cookie)
        self.assertIn("Max-Age=0", cab["Set-Cookie"])
        self.assertIn("Escribe tu correo".encode(), pedir("GET", "/cuenta", cookie=cookie)[2])

    def test_sin_aceptar_no_hay_correo(self):
        self.encender()
        pedir("POST", "/cuenta/acceso", {"correo": "sinaceptar@example.com", "privacidad": "1"})
        self.assertEqual(self.correos, [])

    def test_solo_correos(self):
        self.encender(solo=frozenset({"permitido@example.com"}))
        self.assertIsNone(self.entrar("otro@example.com"))        # misma respuesta, ningún correo
        self.assertIsNone(app._cuentas_almacen().usuario_por_correo("otro@example.com"))
        self.assertEqual(pedir("GET", "/planes")[0], 404)
        self.assertEqual(app._planes_pie_html(), "")
        cookie = self.entrar("permitido@example.com")
        self.assertEqual(pedir("GET", "/planes", cookie=cookie)[0], 200)


class T7Botones(Web):
    def test_sin_claves_sin_botones(self):
        self.encender()
        cookie = self.entrar("botones@example.com")
        _, _, cuerpo = pedir("GET", "/planes", cookie=cookie)
        self.assertNotIn(b"/planes/pagar", cuerpo)
        self.assertIn("IVA no incluido".encode(), cuerpo)
        self.assertIn("sin datos personales".encode(), cuerpo.lower())

    def test_con_claves_de_prueba_hay_botones(self):
        self.encender(claves=True)
        cookie = self.entrar("botones2@example.com")
        _, _, cuerpo = pedir("GET", "/planes", cookie=cookie)
        self.assertEqual(len(re.findall(rb'action="/planes/pagar"', cuerpo)), 5)   # bono + 2 profesional + 2 premium
        guardar_pdf("planes.html", cuerpo)
        guardar_pdf("cuenta.html", pedir("GET", "/cuenta", cookie=cookie)[2])
        self.assertIn("Modo de prueba de Stripe".encode(), cuerpo)
        with mock.patch.object(app.STP, "crear_checkout", return_value="https://checkout.stripe.com/c/pay/x") as cc:
            c, cab, _ = pedir("POST", "/planes/pagar", {"plan": "bono", "periodo": "unico", "t": self.csrf(cookie)}, cookie=cookie)
            self.assertEqual((c, cab["Location"]), (303, "https://checkout.stripe.com/c/pay/x"))
            c, cab, _ = pedir("POST", "/planes/pagar", {"plan": "bono", "periodo": "unico", "t": "malo"}, cookie=cookie)
            self.assertEqual(cc.call_count, 1)                    # sin el código anti-CSRF no se abre el pago


class T8Webhook(Web):
    def test_webhook_firmado(self):
        self.encender(claves=True)
        self.entrar("pago@example.com")
        uid = app._cuentas_almacen().usuario_por_correo("pago@example.com")["id"]
        obj = {"object": "checkout.session", "mode": "payment", "payment_status": "paid", "client_reference_id": str(uid),
               "metadata": {"usuario_id": str(uid), "plan": "bono", "periodo": "unico"}, "amount_subtotal": 999,
               "amount_total": 999, "currency": "eur", "customer": "cus_w"}
        cuerpo = json.dumps({"id": "evt_web_1", "type": "checkout.session.completed", "livemode": False,
                             "data": {"object": obj}}).encode()
        c, _, _ = pedir("POST", "/planes/stripe-webhook", cuerpo=cuerpo, cabeceras={"HTTP_STRIPE_SIGNATURE": firmar(cuerpo, "whsec_otro")})
        self.assertEqual(c, 400)
        self.assertEqual(app._cuentas_almacen().usuario(uid)["bono_restantes"], 0)
        c, _, _ = pedir("POST", "/planes/stripe-webhook", cuerpo=cuerpo, cabeceras={"HTTP_STRIPE_SIGNATURE": firmar(cuerpo)})
        self.assertEqual(c, 200)
        self.assertEqual(app._cuentas_almacen().usuario(uid)["bono_restantes"], PL.BONO_INFORMES)
        pedir("POST", "/planes/stripe-webhook", cuerpo=cuerpo, cabeceras={"HTTP_STRIPE_SIGNATURE": firmar(cuerpo)})
        self.assertEqual(app._cuentas_almacen().usuario(uid)["bono_restantes"], PL.BONO_INFORMES)   # reenvío: una vez


class T9Informes(Web):
    MUNI = {"municipio": "Villaejemplo", "provincia": "soria", "timestamp": time.time(),
            "contratos": [{"fecha": "2026-05-01", "titulo": "Obra inventada", "empresa": "EMPRESA INVENTADA SL",
                           "importe_num": 1234.5, "url": "https://example.com/c1"},
                          {"fecha": "2026-04-01", "titulo": "Servicio inventado", "empresa": "12345678Z",
                           "importe_num": 99.0, "url": ""}]}

    def setUp(self):
        super().setUp()
        for x in (mock.patch.object(app, "_db_get_municipio", lambda m, p=None: dict(self.MUNI) if m in ("Villaejemplo", "Otroejemplo") else None),
                  mock.patch.object(app, "_db_contratos_menors_por_municipio", lambda m, p=None: [])):
            x.start()
            self.addCleanup(x.stop)

    def test_contador_y_pdf(self):
        self.encender()
        c, _, cuerpo = pedir("GET", "/informe/municipio?muni=Villaejemplo&provincia=soria")
        self.assertIn("cuenta gratuita".encode(), cuerpo)          # sin registro: no se descarga
        cookie = self.entrar("informes@example.com")
        t = self.csrf(cookie)
        c, cab, pdf = pedir("POST", "/informe/municipio", {"muni": "Villaejemplo", "provincia": "soria", "t": t}, cookie=cookie)
        self.assertEqual((c, cab["Content-Type"]), (200, "application/pdf"))
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertNotIn(b"12345678Z", pdf)
        guardar_pdf("municipio", pdf)
        try:
            import pypdf
            texto = "".join(p.extract_text() for p in pypdf.PdfReader(BytesIO(pdf)).pages)
            self.assertIn("Villaejemplo", texto)
            self.assertIn("EMPRESA INVENTADA SL", texto)
            self.assertNotIn("12345678Z", texto)                   # un DNI como nombre sale enmascarado
        except ImportError:
            pass
        c, cab, pdf2 = pedir("POST", "/informe/municipio", {"muni": "Villaejemplo", "provincia": "soria", "t": t}, cookie=cookie)
        self.assertEqual(cab["Content-Type"], "application/pdf")   # el mismo, el mismo día: no gasta
        _, _, cuerpo = pedir("GET", "/informe/municipio?muni=Otroejemplo&provincia=soria", cookie=cookie)
        self.assertIn("Ya has usado los informes".encode(), cuerpo)
        uid = app._cuentas_almacen().usuario_por_correo("informes@example.com")["id"]
        self.assertEqual(len(app._cuentas_almacen().descargas_de(uid)), 1)

    def test_borrar_cuenta_con_confirmacion(self):
        self.encender()
        cookie = self.entrar("borrar@example.com")
        c, cab, _ = pedir("POST", "/cuenta/borrar-pedir", {"t": self.csrf(cookie)}, cookie=cookie)
        self.assertEqual(self.correos[-1][0], "cuenta-borrar")
        codigo = re.search(r"/cuenta/borrar\?c=([A-Za-z0-9_\-]+)", self.correos[-1][1]["text"]).group(1)
        c, _, cuerpo = pedir("GET", "/cuenta/borrar?c=" + codigo)
        self.assertNotIn(b'id="auto"', cuerpo)                     # borrar NO se hace solo: un clic de la persona
        self.assertIsNotNone(app._cuentas_almacen().usuario_por_correo("borrar@example.com"))
        c, cab, _ = pedir("POST", "/cuenta/borrar", {"c": codigo})
        self.assertIn("Max-Age=0", cab["Set-Cookie"])
        self.assertIsNone(app._cuentas_almacen().usuario_por_correo("borrar@example.com"))
        self.assertIn("Escribe tu correo".encode(), pedir("GET", "/cuenta", cookie=cookie)[2])


class T10InformeEmpresa(Web):
    """El informe de empresa con un índice de empresas pequeño e inventado (mismo esquema que _empresas_construir)."""
    NIF = "B00000000"

    def setUp(self):
        super().setUp()
        self.ruta = os.path.join(TMP.name, "empresas_prueba.db")
        if not os.path.exists(self.ruta):
            import sqlite3
            con = sqlite3.connect(self.ruta)
            con.executescript("""
                CREATE TABLE organos (id INTEGER PRIMARY KEY, organo TEXT, municipio TEXT, provincia TEXT, entidad TEXT);
                CREATE TABLE c (clave TEXT, tipo TEXT, fecha TEXT, importe REAL, suma REAL, nota TEXT, iva TEXT,
                                org INTEGER, titulo TEXT, url TEXT, fuente TEXT, estado TEXT, con_nif INTEGER);
                CREATE TABLE variantes (clave TEXT, nombre TEXT, n INTEGER);
                CREATE TABLE alias (nkey TEXT, clave TEXT);
                CREATE TABLE nombre_nif (nkey TEXT, nif TEXT);
                CREATE TABLE empresas (clave TEXT PRIMARY KEY, nombre TEXT, n INTEGER, nf INTEGER, nm INTEGER,
                                       imp_sin REAL, imp_con REAL, imp_nd REAL, sociedad INTEGER);
                INSERT INTO organos VALUES (1, 'Ayuntamiento de Villaejemplo', 'Villaejemplo', 'soria', '');
                INSERT INTO c VALUES ('B00000000', 'F', '2026-03-01', 1000.0, 1000.0, NULL, 'sin', 1, 'Obra inventada',
                                      'https://example.com/c1', 'PLACE', 'ADJ', 1);
                INSERT INTO c VALUES ('B00000000', 'M', '2026-02-01', 200.0, 200.0, NULL, 'con', 1, 'Menor inventado',
                                      NULL, 'place-menores', NULL, 1);
                INSERT INTO variantes VALUES ('B00000000', 'EMPRESA INVENTADA SL', 2);
                INSERT INTO empresas VALUES ('B00000000', 'EMPRESA INVENTADA SL', 2, 1, 1, 1000.0, 200.0, 0.0, 1);""")
            con.commit()
            con.close()
        import sqlite3
        adm = ({"nombre": "ADMINISTRADORA INVENTADA EJEMPLO", "cargo": "Administrador único", "desde": "20250115",
                "fuente": "BORME-A-2025-10-30"}, "EMPRESA INVENTADA SL")
        for x in (mock.patch.object(app, "_empresas_con", lambda: sqlite3.connect(self.ruta)),
                  mock.patch.object(app, "_empresa_administrador", lambda *a, **k: adm)):
            x.start()
            self.addCleanup(x.stop)

    def test_informe_de_empresa_solo_con_bono_y_desistimiento(self):
        self.encender()
        cookie = self.entrar("empresa@example.com")
        alm = app._cuentas_almacen()
        uid = alm.usuario_por_correo("empresa@example.com")["id"]
        _, _, cuerpo = pedir("GET", f"/informe/empresa?nif={self.NIF}", cookie=cookie)
        self.assertIn("van con el bono".encode(), cuerpo)          # Registrado: 1 de MUNICIPIO al mes
        alm.sumar_bono(uid)
        _, _, cuerpo = pedir("GET", f"/informe/empresa?nif={self.NIF}", cookie=cookie)
        self.assertIn(b'name="desistimiento"', cuerpo)
        t = self.csrf(cookie)
        c, cab, _ = pedir("POST", "/informe/empresa", {"nif": self.NIF, "t": t}, cookie=cookie)
        self.assertEqual(c, 303)                                   # sin aceptar la pérdida del desistimiento, no
        c, cab, pdf = pedir("POST", "/informe/empresa", {"nif": self.NIF, "t": t, "desistimiento": "1"}, cookie=cookie)
        self.assertEqual((c, cab["Content-Type"]), (200, "application/pdf"))
        self.assertIn(b"/URI (https://www.boe.es/diario_borme/txt.php?id=BORME-A-2025-10-30)", pdf)
        guardar_pdf("empresa", pdf)
        u = alm.usuario(uid)
        self.assertIsNotNone(u["desistimiento_fecha"])
        self.assertEqual(u["bono_restantes"], PL.BONO_INFORMES - 1)
        self.assertEqual(alm.cuenta_informes(u)["quedan_mes"], 1)  # el del mes (municipio) sigue ahí
        try:
            import pypdf
            texto = "".join(p.extract_text() for p in pypdf.PdfReader(BytesIO(pdf)).pages)
            for trozo in ("EMPRESA INVENTADA SL", "Según el BORME, 15/01/2025", "Ayuntamiento de Villaejemplo", "Obra inventada"):
                self.assertIn(trozo, texto)
        except ImportError:
            pass


if __name__ == "__main__":
    rapido = "--rapido" in sys.argv
    sys.argv = [a for a in sys.argv if a != "--rapido"]
    cargador = unittest.TestLoader()
    clases = [T1Planes, T2Cuentas, T3Stripe, T4Pdf] + ([] if rapido else [T5Apagado, T6Registro, T7Botones, T8Webhook, T9Informes, T10InformeEmpresa])
    suite = unittest.TestSuite(cargador.loadTestsFromTestCase(c) for c in clases)
    r = unittest.TextTestRunner(verbosity=2).run(suite)
    if TMP is not None:
        TMP.cleanup()
    sys.exit(0 if r.wasSuccessful() else 1)
