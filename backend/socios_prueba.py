# encoding: utf-8
"""
Prueba de socios.py (perfiles del filtro de licitaciones): las reglas de siempre (28-10) y el pago (31-10): fecha
«pagado_hasta», semanal solo con pago vigente o en los 7 días de cortesía, avisos de vencimiento (15 días antes y el
día que vence) y plazos de borrado contados desde el fin del pago. Sin red ni web: un socios.db temporal, perfiles
INVENTADOS (dominio ejemplo.test) y fechas simuladas.
Uso: python backend/socios_prueba.py      (sale con código 1 si falla algo)
"""
import inspect
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import socios as SOC  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
DIA = 86400
T0 = 1_800_000_000.0
fallos = []


def ok(cond, txt):
    print(("OK   " if cond else "FALLO") + " " + txt)
    if not cond:
        fallos.append(txt)


def alta(alm, correo, perfil, **kw):
    """alta(alm, ...) de las pruebas. Con el PR #25 el alta exige la versión de las condiciones aceptadas (sin ella no
    guarda nada); antes de fusionarlo ese parámetro no existe. Así la misma prueba vale con y sin el #25."""
    if "condiciones" in inspect.signature(alm.alta).parameters:
        kw.setdefault("condiciones", "version-de-prueba")
    return alm.alta(correo, perfil, **kw)


def nuevo(alm, correo, t):
    pid = alta(alm, correo, {"cpvs": ["90"], "provincias": ["murcia"]}, ahora=t)["perfil"]["id"]
    alm.confirmar(pid, alm.firma("confirmar", pid, SOC.huella(alm.a_confirmar(alm.perfil(pid)))), ahora=t)
    return pid


def avisables(alm, t):
    return [p["id"] for p in alm.pendientes_aviso(t, t)]


def semanal(alm, t):
    return [p["id"] for p in alm.pendientes_semanal(t, t, t)]


def aviso_pago(alm, pid, t):
    return dict((p["id"], c) for p, c in alm.pendientes_aviso_pago(t, t)).get(pid, "")


carpeta = tempfile.mkdtemp(prefix="socios_prueba_")
alm = SOC.Almacen(os.path.join(carpeta, "socios.db"))

# ── reglas de siempre (sin pago): borrado igual que antes ───────────────────────────────────────────────────────────
a = nuevo(alm, "siempre@ejemplo.test", T0)
ok(alm.perfil(a)["pagado_hasta"] is None and alm.estado_pago(alm.perfil(a)) == "sin_pago", "un alta nueva no tiene pago")
ok(avisables(alm, T0 + 334 * DIA) == [], "sin pago, 334 días sin uso: aún no se avisa")
ok(avisables(alm, T0 + 336 * DIA) == [a], "sin pago, 336 días: toca el aviso")
alm.marcar_aviso(a, T0 + 336 * DIA)
alm.limpiar(T0 + 365 * DIA)
ok(alm.perfil(a) is not None, "sin pago, 29 días tras el aviso: sigue")
r = alm.limpiar(T0 + 366 * DIA + 1)
ok(alm.perfil(a) is None and r["inactivos"] == 1, "sin pago, 30 días tras el aviso sin pulsar: borrado")

b = nuevo(alm, "sinaviso@ejemplo.test", T0)
alm.limpiar(T0 + 394 * DIA)
ok(alm.perfil(b) is not None, "sin pago y sin aviso: a los 394 días sigue")
alm.limpiar(T0 + 396 * DIA)
ok(alm.perfil(b) is None, "sin pago y sin aviso: borrado a los 13 meses")

c = alta(alm, "pendiente@ejemplo.test", {"cpvs": ["90"]}, ahora=T0)["perfil"]["id"]
alm.limpiar(T0 + 8 * DIA)
ok(alm.perfil(c) is None, "sin confirmar: borrado a los 7 días")

# ── correo semanal: solo con pago vigente o en la cortesía ──────────────────────────────────────────────────────────
s1 = nuevo(alm, "nopaga@ejemplo.test", T0)
ok(s1 not in semanal(alm, T0 + 7 * DIA), "sin pago ni prueba: NO recibe el semanal")
alm.poner_pagado(s1, T0 + 20 * DIA, ahora=T0 + 1)                  # prueba gratis o pago, es lo mismo
ok(s1 in semanal(alm, T0 + 7 * DIA), "con pago (o prueba) vigente: recibe el semanal")
ok(s1 in semanal(alm, T0 + 26 * DIA) and alm.estado_pago(alm.perfil(s1), T0 + 26 * DIA) == "cortesia",
   "vencido hace 6 días: cortesía, sigue recibiendo el semanal")
ok(s1 not in semanal(alm, T0 + 27 * DIA + 60) and alm.estado_pago(alm.perfil(s1), T0 + 27 * DIA + 60) == "vencido",
   "vencido hace más de 7 días: deja de recibirlo")
ok(alm.perfil(s1) is not None, "vencido: el perfil se conserva")
alm.poner_pagado(s1, T0 + 400 * DIA, ahora=T0 + 60 * DIA)
ok(s1 in semanal(alm, T0 + 61 * DIA), "renueva: vuelve a recibirlo sin rellenar nada")
alm.baja(s1)

# ── poner el pago ───────────────────────────────────────────────────────────────────────────────────────────────────
d = alta(alm, "sinconfirmar@ejemplo.test", {"cpvs": ["90"]}, ahora=T0)["perfil"]["id"]
fila, motivo = alm.poner_pagado(d, T0 + 100 * DIA, ahora=T0 + 1)
ok(fila is None and motivo == "sin_confirmar", "no se pone el pago a un perfil sin confirmar")
alm.limpiar(T0 + 8 * DIA)
ok(alm.perfil(d) is None, "un perfil sin confirmar se borra a los 7 días igual (el pago no lo salta)")

e = nuevo(alm, "paga@ejemplo.test", T0)
ok(alm.poner_pagado(e, T0 - DIA, ahora=T0 + 1) == (None, "fecha"), "fecha pasada: rechazada")
ok(alm.poner_pagado(e, T0 + 6 * 366 * DIA, ahora=T0 + 1) == (None, "fecha"), "fecha a más de 5 años: rechazada")
ok(alm.poner_pagado(999999, T0 + DIA, ahora=T0) == (None, "no_existe"), "perfil que no existe")
HASTA = T0 + 500 * DIA                                         # pagado ~16 meses, sin usar nunca el servicio
fila, motivo = alm.poner_pagado(e, HASTA, ahora=T0 + 1)
ok(fila and motivo == "" and fila["pagado_hasta"] == HASTA, "pago puesto")
ok(alm.pago_vigente(fila, T0 + 2) and not alm.pago_vigente(fila, HASTA + 1), "pago_vigente antes y después de la fecha")
ok(e not in avisables(alm, T0 + 336 * DIA), "con pago: a los 336 días sin uso NO se avisa")
alm.limpiar(T0 + 396 * DIA)
ok(alm.perfil(e) is not None, "con pago: a los 13 meses sin uso NO se borra")

# vence: el perfil se conserva y las reglas de borrado cuentan desde el fin del pago
r = alm.limpiar(HASTA + 60)
ok(alm.perfil(e) is not None, "al vencer, con 16 meses sin uso: NO se borra")
ok(e not in avisables(alm, HASTA + 60), "al vencer: tampoco se avisa todavía (cuenta desde el fin del pago)")
ok(e not in avisables(alm, HASTA + 334 * DIA), "334 días después del fin del pago: aún no se avisa")
ok(e in avisables(alm, HASTA + 336 * DIA), "336 días después del fin del pago: toca el aviso")
alm.marcar_aviso(e, HASTA + 336 * DIA)
alm.limpiar(HASTA + 365 * DIA)
ok(alm.perfil(e) is not None, "avisado: a los 29 días sigue")
alm.limpiar(HASTA + 366 * DIA + 1)
ok(alm.perfil(e) is None, "avisado sin pulsar: borrado a los 30 días, como siempre")

f = nuevo(alm, "avisofalla@ejemplo.test", T0)
alm.poner_pagado(f, T0 + 30 * DIA, ahora=T0 + 1)
alm.limpiar(T0 + 30 * DIA + 394 * DIA)
ok(alm.perfil(f) is not None, "vencido, aviso sin salir: a los 394 días del fin del pago sigue")
alm.limpiar(T0 + 30 * DIA + 396 * DIA)
ok(alm.perfil(f) is None, "vencido, aviso sin salir: borrado a los 13 meses del fin del pago")

g = nuevo(alm, "usa@ejemplo.test", T0)
alm.poner_pagado(g, T0 + 30 * DIA, ahora=T0 + 1)
alm.usar(g, ahora=T0 + 200 * DIA)                               # lo usa después de vencer (enlace de un correo viejo)
ok(g not in avisables(alm, T0 + 30 * DIA + 340 * DIA), "uso posterior al fin del pago: cuenta el uso, no se avisa")
ok(g in avisables(alm, T0 + 200 * DIA + 336 * DIA), "aviso a los 11 meses del último uso, si es más tarde")
alm.baja(g)

# poner el pago anula un aviso ya enviado
h = nuevo(alm, "avisado@ejemplo.test", T0)
alm.marcar_aviso(h, T0 + 336 * DIA)
alm.poner_pagado(h, T0 + 400 * DIA, ahora=T0 + 340 * DIA)
ok(alm.perfil(h)["aviso_inactividad"] is None, "poner el pago anula el aviso ya enviado")
alm.limpiar(T0 + 370 * DIA)
ok(alm.perfil(h) is not None, "avisado y luego paga: no se borra a los 30 días del aviso")
alm.baja(h)

# ── avisos de vencimiento ───────────────────────────────────────────────────────────────────────────────────────────
v = nuevo(alm, "vence@ejemplo.test", T0)
FIN = T0 + 100 * DIA                                           # «final del último día pagado»
alm.poner_pagado(v, FIN, ahora=T0 + 1)
ok(aviso_pago(alm, v, FIN - 16 * DIA) == "", "16 días antes: nada")
ok(aviso_pago(alm, v, FIN - 15 * DIA) == "antes", "15 días antes: aviso «antes»")
ok(aviso_pago(alm, v, FIN - 13 * DIA) == "antes", "13 días antes (la pasada falló dos días): aún sale")
ok(aviso_pago(alm, v, FIN - 12 * DIA + 1) == "", "pasados 3 días de la ventana: ya no sale (queda el del día)")
alm.marcar_aviso_pago(v, FIN - 15 * DIA)
ok(aviso_pago(alm, v, FIN - 14 * DIA) == "", "«antes» enviado: no se repite")
ok(aviso_pago(alm, v, FIN - DIA) == "", "el día anterior al último: nada")
ok(aviso_pago(alm, v, FIN - DIA + 2) == "vence", "el último día pagado: aviso «vence»")
alm.marcar_aviso_pago(v, FIN - DIA + 2)
ok(aviso_pago(alm, v, FIN - 3600) == "" and aviso_pago(alm, v, FIN + 3 * DIA) == "", "«vence» enviado: no se repite")
# renovación: umbrales nuevos solos
alm.poner_pagado(v, FIN + 365 * DIA, ahora=FIN + 2 * DIA)
ok(aviso_pago(alm, v, FIN + 3 * DIA) == "", "renovado: nada hasta 15 días antes de la fecha nueva")
ok(aviso_pago(alm, v, FIN + 350 * DIA) == "antes", "renovado: «antes» de la fecha nueva")
# «vence» que no pudo salir el día: sale en la cortesía, no después
w = nuevo(alm, "tarde@ejemplo.test", T0)
alm.poner_pagado(w, FIN, ahora=T0 + 1)
ok(aviso_pago(alm, w, FIN + 5 * DIA) == "vence", "«vence» no salió el día: sale durante la cortesía")
ok(aviso_pago(alm, w, FIN + 7 * DIA + 1) == "", "acabada la cortesía: ya no sale")
# prueba corta (7 días): solo el del día
x = nuevo(alm, "prueba@ejemplo.test", T0)
alm.poner_pagado(x, T0 + 7 * DIA, ahora=T0 + 1)
ok(all(aviso_pago(alm, x, T0 + n * DIA) == "" for n in range(0, 6)), "prueba de 7 días: no hay aviso «antes»")
ok(aviso_pago(alm, x, T0 + 6 * DIA + 2) == "vence", "prueba de 7 días: aviso el último día")
# un fallo hoy (intentado) espera a mañana
alm.marcar_intentado(x, T0 + 6 * DIA + 10)
ok(x not in [p["id"] for p, _ in alm.pendientes_aviso_pago(T0 + 6 * DIA + 20, T0 + 6 * DIA + 1)], "fallo hoy: espera a mañana")
ok(aviso_pago(alm, x, T0 + 7 * DIA + 10) == "vence", "mañana se reintenta")
# sin pago: nunca
ok(aviso_pago(alm, b if alm.perfil(b) else nuevo(alm, "nunca@ejemplo.test", T0), T0 + 10 * DIA) == "",
   "sin pago: ningún aviso de vencimiento")

# ── quitar el pago: termina en el acto, sin cortesía ni avisos ──────────────────────────────────────────────────────
i = nuevo(alm, "quita@ejemplo.test", T0)
alm.poner_pagado(i, T0 + 600 * DIA, ahora=T0 + 1)
Q = T0 + 450 * DIA
fila, _ = alm.quitar_pagado(i, ahora=Q)
ok(alm.estado_pago(fila, Q + 1) == "vencido" and i not in semanal(alm, Q + 1), "quitar: deja de recibir el semanal ya")
ok(aviso_pago(alm, i, Q + 60) == "", "quitar: no salen avisos de vencimiento")
r = alm.limpiar(Q + 60)
ok(alm.perfil(i) is not None, "quitar con 15 meses sin uso: no se borra")
ok(i not in avisables(alm, Q + 60) and i in avisables(alm, Q + 336 * DIA),
   "quitar: aviso de inactividad a los 11 meses (desde el fin)")
fila, _ = alm.quitar_pagado(i, ahora=Q + DIA)
ok(fila["pagado_hasta"] == Q - SOC.CORTESIA_S, "quitar otra vez: no cambia nada")
j2 = nuevo(alm, "quitacortesia@ejemplo.test", T0)
alm.poner_pagado(j2, T0 + 10 * DIA, ahora=T0 + 1)
alm.quitar_pagado(j2, ahora=T0 + 12 * DIA)
ok(j2 not in semanal(alm, T0 + 12 * DIA + 1), "quitar durante la cortesía: la corta")
ok(alm.quitar_pagado(999999) == (None, "no_existe"), "quitar a un perfil que no existe")

# baja de un clic con pago vigente: se borra todo igual
j = nuevo(alm, "bajapagando@ejemplo.test", T0)
alm.poner_pagado(j, T0 + 300 * DIA, ahora=T0 + 1)
ok(alm.baja(j) and alm.perfil(j) is None, "baja con el pago vigente: borrado entero")

# panel
ok(alm.resumen()["con_pago_vigente"] == sum(1 for p in alm.lista() if alm.pago_vigente(p)), "recuento del panel")
ok("en_cortesia" in alm.resumen(), "el panel cuenta los que están en cortesía")

# ── socios.db de antes del 31-10: se añaden las columnas sin perder nada ────────────────────────────────────────────
vieja = os.path.join(carpeta, "vieja.db")
con = sqlite3.connect(vieja)
con.executescript(SOC._ESQUEMA.replace(", pagado_hasta REAL, aviso_pago REAL", ""))
con.execute("INSERT INTO perfiles (correo, perfil, estado, alta, confirmado) VALUES ('viejo@ejemplo.test', '{}', 'activo', ?, ?)",
            (T0, T0))
con.commit()
con.close()
alm2 = SOC.Almacen(vieja)
p = alm2.por_correo("viejo@ejemplo.test")
ok(p is not None and p["pagado_hasta"] is None and p["aviso_pago"] is None, "socios.db antiguo: columnas añadidas")
ok(alm2.poner_pagado(p["id"], T0 + DIA, ahora=T0)[1] == "", "socios.db antiguo: se le puede poner el pago")
alm2.db.close()
SOC.Almacen(vieja).db.close()
ok(True, "socios.db antiguo: segunda apertura sin error")

alm.db.close()
print(f"\nFALLOS: {len(fallos)}")
sys.exit(1 if fallos else 0)
