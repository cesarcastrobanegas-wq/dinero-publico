# encoding: utf-8
"""
Forma de pago del filtro de licitaciones (2026-11-04, BORRADOR APAGADO). Sustituye al hueco «[FORMA DE PAGO]» que
el PR #13 dejó en filtro_formulario.py: lo que antes se leía de esa constante (si la forma de pago está puesta y la
frase que sigue a «Para renovarlo:» / «Para contratarlo:») sale ahora de aquí.

Variable de entorno FORMA_PAGO (se lee en cada llamada; por defecto, apagada):
  ""/"apagado"/cualquier otra cosa   APAGADA: igual que el #13 con el hueco entre corchetes. No salen los avisos de
                                     vencimiento, ningún texto habla de cómo pagar y el panel lo avisa.
  "manual"                           Transferencia o Bizum a mano. El texto que ve el cliente sale de
                                     FORMA_PAGO_INSTRUCCIONES (IBAN, Bizum, a quién escribir...), NUNCA del repositorio
                                     (es público). Sin instrucciones cuenta como no puesta. César comprueba el pago y lo
                                     marca a mano en /admin/revision/socios (formulario que solo sale con "manual") o con
                                     POST /admin/socios-pagado; las reglas son las del #13 (app._socios_pagado).
  "pasarela"                         Hueco para una pasarela futura (Pasarela, abajo): hoy NO está disponible y cuenta
                                     como no puesta. Nada de llamadas a ninguna API ni dependencias.
"""
import html
import os
import re

MODOS = ("manual", "pasarela")
INSTRUCCIONES_MAX = 500
_RE_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def _entorno(entorno):
    return os.environ if entorno is None else entorno


def modo(entorno=None):
    """"manual", "pasarela" o "" (apagada). Cualquier valor que no sea uno de los dos modos cuenta como apagada."""
    valor = (_entorno(entorno).get("FORMA_PAGO") or "").strip().lower()
    return valor if valor in MODOS else ""


def instrucciones(entorno=None):
    """FORMA_PAGO_INSTRUCCIONES limpia (sin saltos ni caracteres de control, como mucho 500 caracteres), o "" si falta
    o si sigue siendo un hueco entre corchetes (la misma regla que el #13)."""
    crudo = _RE_CONTROL.sub(" ", _entorno(entorno).get("FORMA_PAGO_INSTRUCCIONES") or "")
    texto = " ".join(crudo.split())[:INSTRUCCIONES_MAX].strip()
    return "" if not texto or "[" in texto else texto


def texto(entorno=None):
    """La frase que sigue a «Para renovarlo:» o «Para contratarlo:», SIN escapar (quien la pinta en HTML la escapa), o
    "" si la forma de pago no está puesta."""
    m = modo(entorno)
    if m == "manual":
        return instrucciones(entorno)
    if m == "pasarela":
        return Pasarela(entorno).texto()
    return ""


def puesta(entorno=None):
    """¿Se puede decir al cliente cómo pagar? Mientras no, la web no manda avisos de vencimiento (regla del #13)."""
    return bool(texto(entorno))


def admin_manual(entorno=None):
    """¿Sale en el panel el formulario para poner o quitar «pagado hasta»? Solo en modo manual."""
    return modo(entorno) == "manual"


def estado_panel(entorno=None):
    """Aviso para el panel (HTML) o "" si la forma de pago está puesta."""
    m = modo(entorno)
    if m == "manual" and not instrucciones(entorno):
        que = "FORMA_PAGO=manual pero falta FORMA_PAGO_INSTRUCCIONES (o sigue entre corchetes)"
    elif m == "pasarela":
        que = "FORMA_PAGO=pasarela, pero la pasarela todavía no existe"
    elif not m:
        que = "FORMA_PAGO apagada (variable de entorno sin poner, o con un valor que no es manual ni pasarela)"
    else:
        return ""
    return (f'<div class="aviso"><b>Falta la forma de pago</b> ({html.escape(que)}): no salen los avisos de '
            f'vencimiento.</div>')


def formulario_admin_html(csrf_input, accion="/admin/revision/socios/pagado"):
    """Formulario del panel para poner o quitar «pagado hasta» de un correo. "" salvo con FORMA_PAGO=manual.
    csrf_input: el <input type="hidden" name="csrf"...> de la sesión del panel (lo comprueba la ruta POST)."""
    if not admin_manual():
        return ""
    return (f'<h2 style="font-size:16px">Marcar un pago (transferencia o Bizum)</h2>'
            f'<form method="post" action="{html.escape(accion)}" class="acc">{csrf_input}'
            f'<label>Correo <input type="email" name="correo" required maxlength="120"></label> '
            f'<label>Pagado hasta <input type="date" name="hasta"></label> '
            f'<button type="submit" name="accion" value="poner">Poner</button> '
            f'<button type="submit" name="accion" value="quitar" class="sec">Quitar</button></form>'
            f'<p class="sub">Mismas reglas que POST /admin/socios-pagado: solo perfiles confirmados; «Poner» con el último '
            f'día pagado (fecha futura, a menos de 5 años); «Quitar» termina el servicio ahora, sin cortesía.</p>')


class Pasarela:
    """Hueco para una pasarela de pago (tarjeta, domiciliación...) que todavía NO existe. Cuando se elija una, esto
    tendría que:
      1. crear_cobro(): pedir a la pasarela un cobro o una suscripción para un perfil (importe de PRECIO_FILTRO, el
         correo del perfil y una referencia propia que NO sea el correo) y devolver la dirección de pago;
      2. webhook(): recibir el aviso de la pasarela en una ruta POST propia, COMPROBAR SU FIRMA con el secreto de la
         pasarela (variable de entorno, nunca en el repositorio) y rechazar lo que no venga firmado o se repita;
      3. con un cobro confirmado, marcar pagado_hasta con las mismas reglas que el admin (socios.Almacen.poner_pagado,
         a través de app._socios_pagado) y, con una devolución o una baja, quitarlo (quitar_pagado).
    Los datos de facturación irían FUERA de socios.db (decisión de César del 31-10). Mientras tanto todo devuelve
    «no disponible» o lanza NotImplementedError, y FORMA_PAGO=pasarela cuenta como forma de pago no puesta."""
    disponible = False

    def __init__(self, entorno=None):
        self.entorno = _entorno(entorno)

    def texto(self):
        return ""                                         # no hay pasarela: nada que decir al cliente

    def crear_cobro(self, perfil_id, hasta):
        raise NotImplementedError("Pasarela de pago no disponible")

    def webhook(self, cabeceras, cuerpo):
        raise NotImplementedError("Pasarela de pago no disponible")
