# encoding: utf-8
"""
Prueba de la web para «pagado_hasta» (31-10): la orden POST /admin/socios-pagado, el panel y que SOCIOS_SOLO_CORREOS
siga igual; desde el 04-11, también la capa FORMA_PAGO (forma_pago.py) y el formulario del panel para marcar
pagos a mano, que solo existe con FORMA_PAGO=manual y pide la sesión del panel y su csrf. Llama a app.app (la misma entrada WSGI que usa gunicorn) dentro del propio proceso, sin servidor ni red,
con un DATA_DIR temporal, sin RESEND_API_KEY (no puede salir ningún correo) y perfiles INVENTADOS (ejemplo.test).
Cada caso arranca la app en un proceso aparte, uno detrás de otro, porque FILTRO_FORMULARIO y SOCIOS_SOLO_CORREOS se
leen al importar.
Uso: python backend/socios_pagado_prueba_web.py CARPETA_DATOS [apagado|abierto|prueba]
  CARPETA_DATOS: una COPIA de datos_vacio (con su cache.db); nunca la de producción. Se crea ahí socios.db.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
TOKEN = "token-de-prueba-inventado-31-10"
DIA = 86400
PERFIL_COMPLETO = {"cpvs": ["909"], "provincias": ["murcia"], "trabajadores": 5, "facturacion": "150k-300k",
                   "clasificacion": [], "certificados": [], "ute": False, "experiencia_publica": True}
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def caso(modo, datos):
    """Se ejecuta en el proceso hijo: importa la app con las variables del modo y prueba."""
    sys.path.insert(0, AQUI)
    os.chdir(AQUI)
    from wsgiref.util import setup_testing_defaults
    import app  # noqa: E402
    import socios as SOC  # noqa: E402
    fallos = []

    def ok(cond, txt):
        print(f"[{modo}] " + ("OK   " if cond else "FALLO") + " " + txt, flush=True)
        if not cond:
            fallos.append(txt)

    def post(ruta, cuerpo="", cabecera_token=None, query=""):
        b = cuerpo.encode("utf-8")
        env = {"REQUEST_METHOD": "POST", "PATH_INFO": ruta, "QUERY_STRING": query, "CONTENT_LENGTH": str(len(b)),
               "CONTENT_TYPE": "application/x-www-form-urlencoded", "wsgi.input": io.BytesIO(b)}
        if cabecera_token is not None:
            env["HTTP_X_ADMIN_TOKEN"] = cabecera_token
        setup_testing_defaults(env)
        estado = {}
        cuerpo_r = b"".join(app.app(env, lambda s, h, e=None: estado.update(s=s)))
        codigo = int(estado["s"].split()[0])
        try:
            return codigo, json.loads(cuerpo_r.decode("utf-8"))
        except ValueError:
            return codigo, cuerpo_r.decode("utf-8", "replace")

    def forma_pago(modo_pago="", instrucciones=""):
        """La capa forma_pago.py lee el entorno en cada llamada: se cambia aquí, solo en este proceso de prueba."""
        for k in ("FORMA_PAGO", "FORMA_PAGO_INSTRUCCIONES"):
            os.environ.pop(k, None)
        if modo_pago:
            os.environ["FORMA_PAGO"] = modo_pago
        if instrucciones:
            os.environ["FORMA_PAGO_INSTRUCCIONES"] = instrucciones

    def post_panel(ruta, cuerpo, cookie=None, cabecera_token=None):
        """POST al panel /admin/revision/... con la cookie de sesión: (código, Location)."""
        b = cuerpo.encode("utf-8")
        env = {"REQUEST_METHOD": "POST", "PATH_INFO": ruta, "QUERY_STRING": "", "CONTENT_LENGTH": str(len(b)),
               "CONTENT_TYPE": "application/x-www-form-urlencoded", "wsgi.input": io.BytesIO(b)}
        if cookie:
            env["HTTP_COOKIE"] = f"dp_rev={cookie}"
        if cabecera_token is not None:
            env["HTTP_X_ADMIN_TOKEN"] = cabecera_token
        setup_testing_defaults(env)
        estado = {}
        b"".join(app.app(env, lambda s, h, e=None: estado.update(s=s, h=dict(h))))
        return int(estado["s"].split()[0]), estado["h"].get("Location", "")

    if modo == "apagado":
        sesion = app._revision_cookie_nueva()
        forma_pago("manual", "escríbenos a pagos@ejemplo.test")
        c, _ = post_panel("/admin/revision/socios/pagado", f"csrf={app._revision_csrf(sesion)}&correo=x@ejemplo.test"
                          "&accion=poner&hasta=2027-10-31", sesion)
        ok(c == 404, f"formulario del panel con el filtro apagado (aunque FORMA_PAGO=manual): 404 ({c})")
        forma_pago()
        c, _ = post("/admin/socios-pagado", "correo=x@ejemplo.test&accion=ver", TOKEN)
        ok(c == 404, f"formulario apagado: 404 ({c})")
        ok(not os.path.exists(os.path.join(datos, "socios.db")), "formulario apagado: no se crea socios.db")
        c, _ = post("/admin/socios-pagado", "correo=x@ejemplo.test", None)
        ok(c == 403, f"apagado y sin token: 403 ({c})")
        return fallos

    alm = app._socios_almacen()
    ahora = time.time()

    def nuevo(correo, t):
        pid = alm.alta(correo, {"cpvs": ["90"], "provincias": ["murcia"]}, ahora=t)["perfil"]["id"]
        alm.confirmar(pid, alm.firma("confirmar", pid, SOC.huella(alm.a_confirmar(alm.perfil(pid)))), ahora=t)
        return pid

    if modo == "abierto":
        a = nuevo("cliente@ejemplo.test", ahora - 10 * DIA)
        # token
        c, _ = post("/admin/socios-pagado", "correo=cliente@ejemplo.test&accion=poner&hasta=2027-10-31")
        ok(c == 403, f"sin token: 403 ({c})")
        c, _ = post("/admin/socios-pagado", "correo=cliente@ejemplo.test&accion=poner&hasta=2027-10-31", "malo")
        ok(c == 403, f"token equivocado: 403 ({c})")
        c, _ = post("/admin/socios-pagado", "correo=cliente@ejemplo.test&accion=poner&hasta=2027-10-31", None,
                    query=f"token={TOKEN}")
        ok(c == 403 and alm.perfil(a)["pagado_hasta"] is None, f"token en la dirección (?token=): 403 y no cambia nada ({c})")
        c, r = post("/admin/socios-pagado", "accion=ver", TOKEN, query="correo=cliente@ejemplo.test")
        ok(c == 404, f"correo en la dirección: no se lee (solo el cuerpo) ({c})")
        # poner
        c, r = post("/admin/socios-pagado", "correo=Cliente@Ejemplo.test&accion=poner&hasta=2027-10-31", TOKEN)
        ok(c == 200 and r.get("pago_vigente") and r.get("pagado_hasta") == "31-10-2027", f"poner: {c} {r}")
        ok(r.get("correo") == "cl***@ejemplo.test", "la respuesta lleva el correo tapado, no entero")
        fin = app._ahora_madrid(alm.perfil(a)["pagado_hasta"])
        ok((fin.hour, fin.minute, fin.second) == (23, 59, 59), f"hasta = final del día en hora peninsular ({fin})")
        c, r = post("/admin/socios-pagado", "correo=cliente@ejemplo.test&accion=poner&hasta=2020-01-01", TOKEN)
        ok(c == 400, f"fecha pasada: 400 ({c} {r})")
        c, r = post("/admin/socios-pagado", "correo=cliente@ejemplo.test&accion=poner&hasta=31-10-2027", TOKEN)
        ok(c == 400, f"fecha mal escrita: 400 ({c})")
        c, r = post("/admin/socios-pagado", "correo=cliente@ejemplo.test&accion=poner", TOKEN)
        ok(c == 400, f"sin fecha: 400 ({c})")
        c, r = post("/admin/socios-pagado", "correo=cliente@ejemplo.test&accion=borrar", TOKEN)
        ok(c == 400, f"acción desconocida: 400 ({c})")
        c, r = post("/admin/socios-pagado", "correo=nadie@ejemplo.test&accion=ver", TOKEN)
        ok(c == 404, f"correo sin perfil: 404 ({c})")
        p = alm.alta("sinconfirmar@ejemplo.test", {"cpvs": ["90"]})["perfil"]["id"]
        c, r = post("/admin/socios-pagado", f"p={p}&accion=poner&hasta=2027-01-01", TOKEN)
        ok(c == 409, f"perfil sin confirmar: 409 ({c})")
        c, r = post("/admin/socios-pagado", f"p={a}&accion=ver&token={TOKEN}")
        ok(c == 200 and r.get("pagado_hasta") == "31-10-2027", f"ver por número, con el token en el cuerpo: {c}")
        # panel
        html_ = app._socios_panel_html("cookie-de-prueba")[2].decode("utf-8")
        ok("Pagado hasta" in html_ and "31-10-2027" in html_ and "Con pago vigente" in html_, "el panel enseña la fecha")
        # quitar
        c, r = post("/admin/socios-pagado", "correo=cliente@ejemplo.test&accion=quitar", TOKEN)
        ok(c == 200 and not r.get("pago_vigente"), f"quitar: {c} {r}")
        ok("(terminado)" in app._socios_panel_html("cookie-de-prueba")[2].decode("utf-8"), "el panel lo marca como terminado")
        hoy = app._ahora_madrid().strftime("%Y-%m-%d")
        # pasada 1: semanal solo con pago (la copia no tiene licitaciones: el que toca cuenta como «sin novedades» y
        # se le marca revisado; al que no le toca no se le cambia nada); avisos de pago bloqueados por [FORMA DE PAGO]
        sp = nuevo("sinpago@ejemplo.test", ahora - 10 * DIA)
        cp = nuevo("conpago@ejemplo.test", ahora - 10 * DIA)
        vh = nuevo("vencehoy@ejemplo.test", ahora - 10 * DIA)
        for pid in (sp, cp, vh):
            alm.db.execute("UPDATE perfiles SET revisado=? WHERE id=?", (ahora - 8 * DIA, pid))
        alm.db.commit()
        post("/admin/socios-pagado", "correo=conpago@ejemplo.test&accion=poner&hasta=2027-06-30", TOKEN)
        c, r = post("/admin/socios-pagado", f"correo=vencehoy@ejemplo.test&accion=poner&hasta={hoy}", TOKEN)
        ok(c == 200 and r.get("recibe_semanal"), f"prueba gratis / pago que vence hoy: puesto ({c} {r})")
        r1 = app._socios_pasada(25)
        ok(alm.perfil(cp)["revisado"] > ahora - 60 and alm.perfil(sp)["revisado"] == ahora - 8 * DIA,
           f"semanal: se revisa al que paga y NO al que no paga ({r1})")
        ok(r1["forma_pago_sin_poner"] and r1["avisos_pago"] == 0 and r1["fallidos"] == 0
           and not alm.db.execute("SELECT 1 FROM envios WHERE clase LIKE 'aviso_pago%'").fetchone(),
           "con [FORMA DE PAGO] entre corchetes no sale ningún aviso de vencimiento")
        ok("Falta la forma de pago" in app._socios_panel_html("c")[2].decode("utf-8"), "el panel avisa de que falta")
        # pasada 2: con la forma de pago puesta sale el aviso «vence» (sin Resend: cuenta como fallido)
        # La pasada 1 ya le revisó el semanal hoy (eso marca «intentado hoy» y aplaza a mañana). En la web real no
        # ocurre: en cada pasada los avisos de pago van ANTES que el semanal. Aquí se simula «al día siguiente».
        alm.db.execute("UPDATE perfiles SET intentado=NULL")
        alm.db.commit()
        forma_pago("manual", "escríbenos a pagos@ejemplo.test")
        r2 = app._socios_pasada(25)
        env = alm.db.execute("SELECT clase, perfil_id FROM envios WHERE clase LIKE 'aviso_pago%'").fetchall()
        ok(not r2["forma_pago_sin_poner"] and [tuple(e) for e in env] == [("aviso_pago_vence", vh)],
           f"forma de pago puesta: se intenta el aviso «vence» solo al que vence hoy ({env})")
        ok(r2["fallidos"] == 1, f"sin Resend, el aviso cuenta como fallido y se reintenta mañana ({r2})")
        # textos
        import datetime as _dt
        fin = _dt.date(2027, 6, 30)
        a1, t1, _ = app.FFORM.correo_vence("vence", fin, fin + _dt.timedelta(days=7), fin, "https://v.test", "https://b.test")
        ok(a1 == "Tu servicio de licitaciones vence hoy" and "pagos@ejemplo.test" in t1 and "7 de julio de 2027" in t1
           and "no tengas que rellenarlo" in t1, "correo «vence»: hoy, forma de pago, fin de la cortesía, perfil guardado")
        a2, t2, _ = app.FFORM.correo_vence("vence", fin, fin + _dt.timedelta(days=7), _dt.date(2027, 7, 2), "v", "b")
        ok(a2.startswith("Tu servicio de licitaciones venció el 30 de junio"), "«vence» enviado tarde: dice «venció»")
        a3, t3, _ = app.FFORM.correo_vence("antes", fin, fin + _dt.timedelta(days=7), fin - _dt.timedelta(days=15), "v", "b")
        ok("vence el 30 de junio de 2027" in a3 and "Para renovarlo: escríbenos" in t3, "correo «antes»")
        ok("pagos@ejemplo.test" in app.FFORM.correo_sigues("m", "b", fin)[1], "«¿Sigues interesado?» lleva la forma de pago")
        forma_pago()
        ok("[" not in app.FFORM.correo_sigues("m", "b", fin)[1], "con corchetes, «¿Sigues interesado?» no la enseña")
        pag = app.FFORM.confirmado_html(PERFIL_COMPLETO, "v", "b", recibe=False)
        ok("no tienes el servicio contratado" in pag and "Cada lunes" not in pag, "confirmar sin pago: no promete el lunes")
        ok("Cada lunes" in app.FFORM.confirmado_html(PERFIL_COMPLETO, "v", "b", recibe=True), "confirmar con pago: sí")
        # inactividad: nunca pagó -> como siempre; pagó y se quitó -> cuenta desde el fin
        b = nuevo("viejo@ejemplo.test", ahora - 400 * DIA)
        b2 = nuevo("viejopago@ejemplo.test", ahora - 400 * DIA)
        for pid in (b, b2):
            alm.db.execute("UPDATE perfiles SET ultimo_uso=?, revisado=? WHERE id=?", (ahora - 340 * DIA, ahora, pid))
        alm.db.commit()
        post("/admin/socios-pagado", "correo=viejopago@ejemplo.test&accion=poner&hasta=2027-06-30", TOKEN)
        post("/admin/socios-pagado", "correo=viejopago@ejemplo.test&accion=quitar", TOKEN)
        r3 = app._socios_pasada(25)
        env = [e[0] for e in alm.db.execute("SELECT perfil_id FROM envios WHERE clase='aviso_inactividad'")]
        ok(env == [b] and alm.perfil(b) and alm.perfil(b2), f"aviso de inactividad al que nunca pagó; al otro, no ({env} {r3})")
        # formulario del panel para marcar pagos a mano (04-11, FORMA_PAGO=manual)
        sesion = app._revision_cookie_nueva()
        csrf = app._revision_csrf(sesion)
        fm = nuevo("formulario@ejemplo.test", ahora - 10 * DIA)
        poner_f = f"csrf={csrf}&correo=formulario@ejemplo.test&accion=poner&hasta=2027-12-31"
        panel = lambda q="": app._socios_panel_html(sesion, q)[2].decode("utf-8")      # noqa: E731
        fecha = lambda: app._socios_fecha_pago(alm.perfil(fm)["pagado_hasta"])          # noqa: E731
        forma_pago()
        ok("socios/pagado" not in panel() and "FORMA_PAGO apagada" in panel(), "apagada: sin formulario y el panel lo avisa")
        c, _ = post_panel("/admin/revision/socios/pagado", poner_f, sesion)
        ok(c == 404 and alm.perfil(fm)["pagado_hasta"] is None, f"apagada: el formulario no existe (404) ({c})")
        forma_pago("pasarela", "escríbenos a pagos@ejemplo.test")
        c, _ = post_panel("/admin/revision/socios/pagado", poner_f, sesion)
        ok(c == 404 and "socios/pagado" not in panel() and "pasarela" in panel(), f"pasarela: sin formulario (404) ({c})")
        ok(app._socios_pasada(25)["forma_pago_sin_poner"], "pasarela: cuenta como forma de pago no puesta")
        forma_pago("manual")
        ok("socios/pagado" in panel() and "FORMA_PAGO_INSTRUCCIONES" in panel(),
           "manual sin instrucciones: formulario, pero el panel avisa de que falta el texto")
        ok(app._socios_pasada(25)["forma_pago_sin_poner"], "manual sin instrucciones: no salen avisos de vencimiento")
        forma_pago("manual", "escríbenos a pagos@ejemplo.test")
        ok("socios/pagado" in panel() and f'name="csrf" value="{csrf}"' in panel() and "Falta la forma de pago" not in panel(),
           "manual con instrucciones: formulario con csrf y sin aviso")
        c, _ = post_panel("/admin/revision/socios/pagado", poner_f)
        ok(c == 403, f"formulario sin sesión: 403 ({c})")
        c, _ = post_panel("/admin/revision/socios/pagado", poner_f, cabecera_token=TOKEN)
        ok(c == 403, f"formulario con el token pero sin sesión: 403 ({c})")
        c, _ = post_panel("/admin/revision/socios/pagado", poner_f.replace(csrf, "0" * 32), sesion)
        ok(c == 403, f"formulario con csrf equivocado: 403 ({c})")
        c, _ = post_panel("/admin/revision/socios/pagado", poner_f, "9999999999." + "0" * 64)
        ok(c == 403 and alm.perfil(fm)["pagado_hasta"] is None, f"cookie falsa: 403 y no cambia nada ({c})")
        c, loc = post_panel("/admin/revision/socios/pagado", poner_f, sesion)
        ok(c == 303 and loc.endswith("hecho=pago_poner") and fecha() == "31-12-2027", f"poner desde el panel: {c} {loc}")
        ok("Pago puesto." in panel("pago_poner"), "el panel dice «Pago puesto.»")
        for cuerpo, esperado in ((f"csrf={csrf}&correo=formulario@ejemplo.test&accion=poner", "pago_mal"),
                                 (f"csrf={csrf}&correo=formulario@ejemplo.test&accion=poner&hasta=2020-01-01", "pago_mal"),
                                 (f"csrf={csrf}&correo=nadie@ejemplo.test&accion=poner&hasta=2027-12-31", "pago_no_existe")):
            c, loc = post_panel("/admin/revision/socios/pagado", cuerpo, sesion)
            ok(c == 303 and loc.endswith("hecho=" + esperado), f"{cuerpo.split('&', 1)[1]}: {esperado} ({c} {loc})")
        sc = alm.alta("sinconfirmar2@ejemplo.test", {"cpvs": ["90"]})["perfil"]["id"]
        c, loc = post_panel("/admin/revision/socios/pagado", f"csrf={csrf}&p={sc}&accion=poner&hasta=2027-12-31", sesion)
        ok(c == 303 and loc.endswith("hecho=pago_sin_confirmar"), f"sin confirmar: pago_sin_confirmar ({loc})")
        c, _ = post_panel("/admin/revision/socios/pagado", f"csrf={csrf}&correo=formulario@ejemplo.test&accion=ver", sesion)
        ok(c == 404, f"desde el panel solo poner o quitar ({c})")
        ok(fecha() == "31-12-2027", "los errores no han cambiado la fecha")
        c, loc = post_panel("/admin/revision/socios/pagado", f"csrf={csrf}&correo=formulario@ejemplo.test&accion=quitar",
                            sesion)
        ok(c == 303 and loc.endswith("hecho=pago_quitar") and alm.estado_pago(alm.perfil(fm)) == "vencido",
           f"quitar desde el panel: el servicio termina ahora ({loc})")
        ok("<script>" not in panel("<script>") and "Pago puesto." not in panel("pago_poner2"),
           "el mensaje del panel solo sale de una lista fija")
        forma_pago()
        return fallos

    if modo == "prueba":                                   # SOCIOS_SOLO_CORREOS=permitido@ejemplo.test
        ok(app._socios_alta("fuera@ejemplo.test", {"cpvs": ["90"]}) == "fuera_de_prueba"
           and alm.por_correo("fuera@ejemplo.test") is None, "SOCIOS_SOLO_CORREOS: un correo de fuera ni se guarda")
        # perfiles puestos directamente (como si fueran de antes): uno de la lista y otro de fuera, los dos sin uso
        si = nuevo("permitido@ejemplo.test", ahora - 400 * DIA)
        no = nuevo("noenlista@ejemplo.test", ahora - 400 * DIA)
        for pid in (si, no):
            alm.db.execute("UPDATE perfiles SET ultimo_uso=?, revisado=? WHERE id=?", (ahora - 340 * DIA, ahora, pid))
        alm.db.commit()
        c, r = post("/admin/socios-pagado", "correo=noenlista@ejemplo.test&accion=poner&hasta=2027-06-30", TOKEN)
        ok(c == 200, "se puede poner el pago a uno que no está en la lista (no le da permiso de envío)")
        r1 = app._socios_pasada(25)
        ok(r1["en_prueba"] and r1["fallidos"] == 1 and r1["avisos"] == 0,
           f"solo se intenta el aviso del de la lista; el de fuera ni con pago recibe nada ({r1})")
        envios = alm.db.execute("SELECT perfil_id FROM envios WHERE clase='aviso_inactividad'").fetchall()
        ok([e[0] for e in envios] == [si], f"el único intento es al de la lista ({envios})")
        hoy = app._ahora_madrid().strftime("%Y-%m-%d")
        for correo in ("permitido@ejemplo.test", "noenlista@ejemplo.test"):
            post("/admin/socios-pagado", f"correo={correo}&accion=poner&hasta={hoy}", TOKEN)
        alm.db.execute("UPDATE perfiles SET intentado=NULL")
        alm.db.commit()
        forma_pago("manual", "escríbenos a pagos@ejemplo.test")
        app._socios_pasada(25)
        env = [tuple(e) for e in alm.db.execute("SELECT clase, perfil_id FROM envios WHERE clase LIKE 'aviso_pago%'")]
        ok(env == [("aviso_pago_vence", si)], f"aviso de vencimiento solo al de la lista ({env})")
        return fallos
    return ["modo desconocido"]


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--caso":
        fallos = caso(sys.argv[2], sys.argv[3])
        print(f"[{sys.argv[2]}] FALLOS: {len(fallos)}", flush=True)
        sys.exit(1 if fallos else 0)
    if len(sys.argv) not in (2, 3) or not os.path.isfile(os.path.join(sys.argv[1], "cache.db")):
        sys.exit(__doc__)
    solo = sys.argv[2] if len(sys.argv) == 3 else ""                  # para repetir un solo caso
    total = 0
    for modo, extra in (("apagado", {}), ("abierto", {"FILTRO_FORMULARIO": "1"}),
                        ("prueba", {"FILTRO_FORMULARIO": "1", "SOCIOS_SOLO_CORREOS": "permitido@ejemplo.test"})):
        if solo and modo != solo:
            continue
        datos = tempfile.mkdtemp(prefix=f"socios_web_{modo}_")
        for nombre in os.listdir(sys.argv[1]):              # cache.db y marcadores (sin place_cache)
            origen = os.path.join(sys.argv[1], nombre)
            if os.path.isfile(origen) and not nombre.endswith(("-shm", "-wal")):
                shutil.copy2(origen, datos)
        env = {k: v for k, v in os.environ.items() if k not in ("RESEND_API_KEY", "SOCIOS_SOLO_CORREOS",
                                                                  "FILTRO_FORMULARIO", "ALERTAS_ACTIVAS",
                                                                  "FORMA_PAGO", "FORMA_PAGO_INSTRUCCIONES")}
        env.update(extra, DATA_DIR=datos, ADMIN_TOKEN=TOKEN, DINERO_HILOS_EN_POST_FORK="1", PYTHONIOENCODING="utf-8")
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "--caso", modo, datos], env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        lineas = [l for l in r.stdout.splitlines() if l.startswith(f"[{modo}]")]
        print("\n".join(lineas), flush=True)
        if r.returncode and not any("FALLOS:" in l for l in lineas):          # se cayó: enseñar el error
            print(r.stdout[-1500:] + r.stderr[-3000:], flush=True)
        total += 0 if r.returncode == 0 else 1
        shutil.rmtree(datos, ignore_errors=True)
    print(f"\nCASOS CON FALLOS: {total}")
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
