# encoding: utf-8
"""
Prueba de la web para «pagado_hasta» (31-10): la orden POST /admin/socios-pagado, el panel y que SOCIOS_SOLO_CORREOS
siga igual. Llama a app.app (la misma entrada WSGI que usa gunicorn) dentro del propio proceso, sin servidor ni red,
con un DATA_DIR temporal, sin RESEND_API_KEY (no puede salir ningún correo) y perfiles INVENTADOS (ejemplo.test).
Cada caso arranca la app en un proceso aparte, uno detrás de otro, porque FILTRO_FORMULARIO y SOCIOS_SOLO_CORREOS se
leen al importar.
Uso: python backend/socios_pagado_prueba_web.py CARPETA_DATOS
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

    if modo == "apagado":
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
        # la pasada: con pago no hay aviso; sin pago, sí (no sale porque no hay RESEND_API_KEY: cuenta como fallido)
        b = nuevo("viejo@ejemplo.test", ahora - 400 * DIA)
        alm.db.execute("UPDATE perfiles SET ultimo_uso=?, revisado=? WHERE id=?", (ahora - 340 * DIA, ahora, b))
        alm.db.commit()
        c, r = post("/admin/socios-pagado", "correo=viejo@ejemplo.test&accion=poner&hasta=2027-06-30", TOKEN)
        r1 = app._socios_pasada(25)
        ok(r1["avisos"] == 0 and r1["fallidos"] == 0 and alm.perfil(b) is not None,
           f"pasada con pago vigente: ni aviso ni borrado ({r1})")
        post("/admin/socios-pagado", "correo=viejo@ejemplo.test&accion=quitar", TOKEN)
        r2 = app._socios_pasada(25)
        ok(r2["fallidos"] == 1 and alm.perfil(b) is not None,
           f"pasada sin pago: intenta el aviso (sin Resend, fallido) y no lo borra ({r2})")
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
        return fallos
    return ["modo desconocido"]


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--caso":
        fallos = caso(sys.argv[2], sys.argv[3])
        print(f"[{sys.argv[2]}] FALLOS: {len(fallos)}", flush=True)
        sys.exit(1 if fallos else 0)
    if len(sys.argv) != 2 or not os.path.isfile(os.path.join(sys.argv[1], "cache.db")):
        sys.exit(__doc__)
    total = 0
    for modo, extra in (("apagado", {}), ("abierto", {"FILTRO_FORMULARIO": "1"}),
                        ("prueba", {"FILTRO_FORMULARIO": "1", "SOCIOS_SOLO_CORREOS": "permitido@ejemplo.test"})):
        datos = tempfile.mkdtemp(prefix=f"socios_web_{modo}_")
        for nombre in os.listdir(sys.argv[1]):              # cache.db y marcadores (sin place_cache)
            origen = os.path.join(sys.argv[1], nombre)
            if os.path.isfile(origen) and not nombre.endswith(("-shm", "-wal")):
                shutil.copy2(origen, datos)
        env = {k: v for k, v in os.environ.items() if k not in ("RESEND_API_KEY", "SOCIOS_SOLO_CORREOS",
                                                                  "FILTRO_FORMULARIO", "ALERTAS_ACTIVAS")}
        env.update(extra, DATA_DIR=datos, ADMIN_TOKEN=TOKEN, DINERO_HILOS_EN_POST_FORK="1", PYTHONIOENCODING="utf-8")
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "--caso", modo, datos], env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        lineas = [l for l in r.stdout.splitlines() if l.startswith(f"[{modo}]")]
        print("\n".join(lineas) or r.stdout[-3000:] + r.stderr[-3000:], flush=True)
        total += 0 if r.returncode == 0 else 1
        shutil.rmtree(datos, ignore_errors=True)
    print(f"\nCASOS CON FALLOS: {total}")
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
