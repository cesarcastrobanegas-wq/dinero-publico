# encoding: utf-8
"""
Prueba de socios.py (perfiles del filtro de licitaciones): las reglas de siempre (28-10) y la fecha «pagado_hasta»
(31-10). Sin red ni web: un socios.db temporal, perfiles INVENTADOS (dominio ejemplo.test) y fechas simuladas.
Uso: python backend/socios_prueba.py      (sale con código 1 si falla algo)
"""
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


def nuevo(alm, correo, t):
    pid = alm.alta(correo, {"cpvs": ["90"], "provincias": ["murcia"]}, ahora=t)["perfil"]["id"]
    alm.confirmar(pid, alm.firma("confirmar", pid, SOC.huella(alm.a_confirmar(alm.perfil(pid)))), ahora=t)
    return pid


def avisables(alm, t):
    return [p["id"] for p in alm.pendientes_aviso(t, t)]


carpeta = tempfile.mkdtemp(prefix="socios_prueba_")
alm = SOC.Almacen(os.path.join(carpeta, "socios.db"))

# ── reglas de siempre, sin pago (no deben cambiar) ──────────────────────────────────────────────────────────────────
a = nuevo(alm, "siempre@ejemplo.test", T0)
ok(alm.perfil(a)["pagado_hasta"] is None, "un alta nueva no tiene pago")
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

c = alm.alta("pendiente@ejemplo.test", {"cpvs": ["90"]}, ahora=T0)["perfil"]["id"]
alm.limpiar(T0 + 8 * DIA)
ok(alm.perfil(c) is None, "sin confirmar: borrado a los 7 días")

# ── poner el pago ───────────────────────────────────────────────────────────────────────────────────────────────────
d = alm.alta("sinconfirmar@ejemplo.test", {"cpvs": ["90"]}, ahora=T0)["perfil"]["id"]
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
ok(e not in avisables(alm, T0 + 499 * DIA), "con pago: a los 499 días tampoco")
alm.limpiar(T0 + 396 * DIA)
ok(alm.perfil(e) is not None, "con pago: a los 13 meses sin uso NO se borra")
alm.limpiar(T0 + 499 * DIA)
ok(alm.perfil(e) is not None, "con pago: el día antes de terminar sigue")

# vence: vuelven las reglas de siempre con el último uso real
t1 = HASTA + 60
r = alm.limpiar(t1)
ok(alm.perfil(e) is not None and r["inactivos"] == 0,
   "al vencer, con 16 meses sin uso: NO se borra de golpe (primero tiene que salir el aviso)")
ok(avisables(alm, t1) == [e], "al vencer, con 16 meses sin uso: toca el aviso en la pasada siguiente")
alm.marcar_aviso(e, t1)
alm.limpiar(t1 + 29 * DIA)
ok(alm.perfil(e) is not None, "vencido y avisado: a los 29 días sigue")
alm.limpiar(t1 + 30 * DIA + 1)
ok(alm.perfil(e) is None, "vencido y avisado sin pulsar: borrado a los 30 días, como siempre")

# vencido y el aviso nunca sale: borrado a los 13 meses desde el fin del pago
f = nuevo(alm, "avisofalla@ejemplo.test", T0)
alm.poner_pagado(f, T0 + 30 * DIA, ahora=T0 + 1)
alm.limpiar(T0 + 30 * DIA + 394 * DIA)
ok(alm.perfil(f) is not None, "vencido, aviso sin salir: a los 394 días del fin del pago sigue")
alm.limpiar(T0 + 30 * DIA + 396 * DIA)
ok(alm.perfil(f) is None, "vencido, aviso sin salir: borrado a los 13 meses del fin del pago")

# vence con uso reciente: nada cambia hasta los 11 meses sin uso
g = nuevo(alm, "usa@ejemplo.test", T0)
alm.poner_pagado(g, T0 + 30 * DIA, ahora=T0 + 1)
alm.usar(g, ahora=T0 + 25 * DIA)
ok(avisables(alm, T0 + 31 * DIA) == [], "vencido con uso reciente: no se avisa")
ok(avisables(alm, T0 + 25 * DIA + 336 * DIA) == [g], "vencido: aviso a los 11 meses del último uso")
alm.baja(g)

# poner el pago anula un aviso ya enviado
h = nuevo(alm, "avisado@ejemplo.test", T0)
alm.marcar_aviso(h, T0 + 336 * DIA)
alm.poner_pagado(h, T0 + 400 * DIA, ahora=T0 + 340 * DIA)
ok(alm.perfil(h)["aviso_inactividad"] is None, "poner el pago anula el aviso ya enviado")
alm.limpiar(T0 + 370 * DIA)
ok(alm.perfil(h) is not None, "avisado y luego paga: no se borra a los 30 días del aviso")

# quitar el pago
i = nuevo(alm, "quita@ejemplo.test", T0)
alm.poner_pagado(i, T0 + 600 * DIA, ahora=T0 + 1)
fila, _ = alm.quitar_pagado(i, ahora=T0 + 450 * DIA)
ok(fila["pagado_hasta"] == T0 + 450 * DIA and not alm.pago_vigente(fila, T0 + 450 * DIA + 1),
   "quitar: el pago termina en ese momento")
r = alm.limpiar(T0 + 450 * DIA + 60)
ok(alm.perfil(i) is not None and r["inactivos"] == 0, "quitar con 15 meses sin uso: no se borra de golpe")
ok(i in avisables(alm, T0 + 450 * DIA + 60), "quitar: desde ya, reglas de siempre (toca el aviso)")
fila, _ = alm.quitar_pagado(i, ahora=T0 + 451 * DIA)
ok(fila["pagado_hasta"] == T0 + 450 * DIA, "quitar otra vez un pago ya terminado: no cambia nada")
ok(alm.quitar_pagado(999999) == (None, "no_existe"), "quitar a un perfil que no existe")

# baja de un clic con pago vigente: se borra todo igual
j = nuevo(alm, "bajapagando@ejemplo.test", T0)
alm.poner_pagado(j, T0 + 300 * DIA, ahora=T0 + 1)
ok(alm.baja(j) and alm.perfil(j) is None, "baja con el pago vigente: borrado entero")

# el pago no cambia el correo semanal
k = nuevo(alm, "semanal@ejemplo.test", T0)
alm.poner_pagado(k, T0 + 300 * DIA, ahora=T0 + 1)
ok(k in [p["id"] for p in alm.pendientes_semanal(T0 + 7 * DIA, T0 + 7 * DIA)], "con pago sigue en el correo semanal")

# panel
ok(alm.resumen()["con_pago_vigente"] == sum(1 for p in alm.lista() if alm.pago_vigente(p)), "recuento del panel")

# ── socios.db de antes del 31-10: se añade la columna sin perder nada ───────────────────────────────────────────────
vieja = os.path.join(carpeta, "vieja.db")
con = sqlite3.connect(vieja)
con.executescript(SOC._ESQUEMA.replace(", pagado_hasta REAL", ""))
con.execute("INSERT INTO perfiles (correo, perfil, estado, alta, confirmado) VALUES ('viejo@ejemplo.test', '{}', 'activo', ?, ?)",
            (T0, T0))
con.commit()
con.close()
alm2 = SOC.Almacen(vieja)
p = alm2.por_correo("viejo@ejemplo.test")
ok(p is not None and p["pagado_hasta"] is None, "socios.db antiguo: columna añadida y el perfil intacto")
ok(alm2.poner_pagado(p["id"], T0 + DIA, ahora=T0)[1] == "", "socios.db antiguo: se le puede poner el pago")
alm2.db.close()
SOC.Almacen(vieja).db.close()                                   # abrirlo otra vez no falla (la columna ya está)
ok(True, "socios.db antiguo: segunda apertura sin error")

alm.db.close()
print(f"\nFALLOS: {len(fallos)}")
sys.exit(1 if fallos else 0)
