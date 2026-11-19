# encoding: utf-8
"""
Prueba de forma_pago.py (la capa FORMA_PAGO, 04-11) y de los textos de filtro_formulario.py que la usan. Sin red ni
web: solo variables de entorno simuladas y direcciones INVENTADAS (ejemplo.test). La parte de la web (formulario del
panel con su sesión y csrf, avisos de vencimiento) está en socios_pagado_prueba_web.py.
Uso: python backend/forma_pago_prueba.py      (sale con código 1 si falla algo)
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for _v in ("FORMA_PAGO", "FORMA_PAGO_INSTRUCCIONES"):
    os.environ.pop(_v, None)
import filtro_formulario as FFORM  # noqa: E402
import forma_pago as FP  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
fallos = []
CSRF = '<input type="hidden" name="csrf" value="x">'
FIN = dt.date(2027, 6, 30)
PERFIL = {"cpvs": ["909"], "provincias": ["murcia"], "trabajadores": 5, "facturacion": "150k-300k",
          "clasificacion": [], "certificados": [], "ute": False, "experiencia_publica": True}


def ok(cond, txt):
    print(("OK   " if cond else "FALLO") + " " + txt)
    if not cond:
        fallos.append(txt)


def poner(**v):
    for k in ("FORMA_PAGO", "FORMA_PAGO_INSTRUCCIONES"):
        os.environ.pop(k, None)
    os.environ.update(v)


def textos():
    """Los textos al cliente que pueden llevar la forma de pago."""
    _, t_vence, h_vence = FFORM.correo_vence("vence", FIN, FIN + dt.timedelta(days=7), FIN, "https://v.test", "https://b.test")
    _, t_sig, h_sig = FFORM.correo_sigues("https://m.test", "https://b.test", FIN)
    pag = FFORM.confirmado_html(PERFIL, "v", "b", recibe=False)
    return t_vence, h_vence, t_sig, h_sig, pag


# apagada por defecto
poner()
ok(FP.modo() == "" and not FP.puesta() and FP.texto() == "", "sin variables: apagada")
ok(not FFORM.forma_pago_puesta() and FFORM.forma_pago_texto() == "", "filtro_formulario la lee de la capa: no puesta")
ok(FP.formulario_admin_html(CSRF) == "", "apagada: sin formulario en el panel")
ok("Falta la forma de pago" in FP.estado_panel() and "apagada" in FP.estado_panel(), "apagada: el panel lo avisa")
_, _, t_sig, h_sig, pag = textos()
ok("contratarlo" not in t_sig and "[" not in t_sig and "contratarlo" not in pag, "apagada: ningún texto habla de pagar")
for v in ("apagado", "APAGADO", "", "  ", "0", "no", "transferencia", "manual;rm", "Manuals", "pasarela2"):
    poner(FORMA_PAGO=v, FORMA_PAGO_INSTRUCCIONES="Bizum al 600 000 000")
    ok(FP.modo() == "" and not FP.puesta() and FP.formulario_admin_html(CSRF) == "",
       f"valor raro o apagado ({v!r}): apagada aunque haya instrucciones")

# manual
poner(FORMA_PAGO=" Manual ", FORMA_PAGO_INSTRUCCIONES="transferencia a la cuenta de pagos@ejemplo.test, concepto: tu correo")
ok(FP.modo() == "manual" and FP.puesta(), "manual con instrucciones: puesta (sin distinguir mayúsculas ni espacios)")
ok(FFORM.forma_pago_puesta() and "pagos@ejemplo.test" in FFORM.forma_pago_texto(), "filtro_formulario: puesta")
ok(FP.estado_panel() == "", "manual con instrucciones: el panel no avisa")
f = FP.formulario_admin_html(CSRF)
ok('action="/admin/revision/socios/pagado"' in f and CSRF in f and 'value="poner"' in f and 'value="quitar"' in f,
   "manual: formulario del panel con csrf, poner y quitar")
t_vence, h_vence, t_sig, h_sig, pag = textos()
ok("Para renovarlo: transferencia a la cuenta de pagos@ejemplo.test" in t_vence, "aviso de vencimiento con las instrucciones")
ok("para contratarlo: transferencia" in t_sig and "Para contratarlo: transferencia" in pag,
   "«¿Sigues interesado?» y la página sin servicio llevan las instrucciones")

poner(FORMA_PAGO="manual")
ok(not FP.puesta() and FP.formulario_admin_html(CSRF) != "", "manual sin instrucciones: no puesta, pero el panel sí tiene "
   "formulario (se pueden marcar pagos a mano)")
ok("FORMA_PAGO_INSTRUCCIONES" in FP.estado_panel(), "manual sin instrucciones: el panel dice qué falta")
for v in ("", "   ", "\n\t", "[IBAN]", "Bizum al [TELÉFONO]"):
    poner(FORMA_PAGO="manual", FORMA_PAGO_INSTRUCCIONES=v)
    ok(not FP.puesta() and FP.texto() == "", f"instrucciones vacías o con hueco entre corchetes ({v!r}): no puesta")

raro = {"FORMA_PAGO": "manual", "FORMA_PAGO_INSTRUCCIONES": "línea uno\r\nlínea\x00dos\x07   tres " + "x" * 600}
ok("\n" not in FP.texto(raro) and "\x00" not in FP.texto(raro) and FP.texto(raro).startswith("línea uno línea dos tres")
   and len(FP.texto(raro)) <= FP.INSTRUCCIONES_MAX, "instrucciones sin saltos ni caracteres de control, recortadas a 500")

# escape HTML de las instrucciones
poner(FORMA_PAGO="manual", FORMA_PAGO_INSTRUCCIONES='<script>alert(1)</script> "Bizum" & <b>ya</b>')
t_vence, h_vence, t_sig, h_sig, pag = textos()
for nombre, h in (("correo de vencimiento", h_vence), ("«¿Sigues interesado?»", h_sig), ("página sin servicio", pag)):
    ok("<script>" not in h and "<b>ya</b>" not in h and "&lt;script&gt;" in h, f"{nombre}: instrucciones escapadas en el HTML")
ok("<script>alert(1)</script>" in t_vence, "en el texto plano del correo van tal cual (no es HTML)")

# pasarela
poner(FORMA_PAGO="pasarela", FORMA_PAGO_INSTRUCCIONES="Bizum al 600 000 000")
ok(FP.modo() == "pasarela" and not FP.puesta() and FP.texto() == "", "pasarela: no disponible, cuenta como no puesta")
ok(FP.formulario_admin_html(CSRF) == "" and "pasarela" in FP.estado_panel(), "pasarela: sin formulario; el panel lo avisa")
pas = FP.Pasarela()
ok(pas.disponible is False and pas.texto() == "", "Pasarela.disponible = False")
for nombre, llamada in (("crear_cobro", lambda: pas.crear_cobro(1, 0)), ("webhook", lambda: pas.webhook({}, b""))):
    try:
        llamada()
        ok(False, f"Pasarela.{nombre} debería lanzar NotImplementedError")
    except NotImplementedError:
        ok(True, f"Pasarela.{nombre}: NotImplementedError")

# entorno pasado a mano (sin tocar os.environ)
ok(FP.modo({"FORMA_PAGO": "manual"}) == "manual" and FP.puesta({"FORMA_PAGO": "manual", "FORMA_PAGO_INSTRUCCIONES": "a"}),
   "acepta un entorno pasado como dict")
poner()
print(f"\nFALLOS: {len(fallos)}")
sys.exit(1 if fallos else 0)
