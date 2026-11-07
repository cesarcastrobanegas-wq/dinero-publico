# encoding: utf-8
"""Pasa, una detrás de otra, las pruebas de los 8 PR del día del alta (#18 #13 #24 #22 #25 #20 #19 #26) en una carpeta
del repositorio. Sin red, sin Resend, con una carpeta de datos temporal con un cache.db VACÍO (nunca la base real).
  python pruebas_dia_del_alta.py CARPETA_DEL_REPO apagado      todo apagado (como hoy la web)
  python pruebas_dia_del_alta.py CARPETA_DEL_REPO encendido    todo encendido con valores de PRUEBA inventados
Las pruebas que aún no existen en esa carpeta (PR sin fusionar) se saltan. Tarda unos 50 minutos por modo.
Con una tercera ruta (la carpeta backend de una copia de origin/main), «listo para vender» compara además las páginas.
Deja la salida de cada prueba en esta carpeta (salida_<modo>_<prueba>.txt)."""
import os, sys, subprocess, tempfile, shutil, sqlite3, time
raiz, modo = sys.argv[1], sys.argv[2]
B = os.path.join(raiz, "backend")
MAIN_B = sys.argv[3] if len(sys.argv) > 3 else ""
VARS = ("FILTRO_FORMULARIO", "FILTRO_EMBUDO", "SOCIOS_SOLO_CORREOS", "ALERTAS_ACTIVAS", "RESEND_API_KEY", "ADMIN_TOKEN",
        "FORMA_PAGO", "FORMA_PAGO_INSTRUCCIONES", "TEXTOS_LEGALES_NUEVOS", "PRECIOS_VISIBLE", "PRECIOS_NOTA_IVA",
        "PRECIOS_CONTACTO", "PAC_ACTIVO", "CONVOCATORIAS_SUBVENCIONES", "DATA_DIR")
env = {k: v for k, v in os.environ.items() if k not in VARS and not k.startswith(("TITULAR_", "PRECIO_"))}
env["PYTHONIOENCODING"] = "utf-8"
if modo == "encendido":     # todo encendido, con valores de PRUEBA inventados
    env.update(FILTRO_FORMULARIO="1", TEXTOS_LEGALES_NUEVOS="1", PRECIOS_VISIBLE="1", FORMA_PAGO="manual",
               FORMA_PAGO_INSTRUCCIONES="Transferencia a ES00 0000 0000 0000 0000 0000 (prueba)",
               TITULAR_NOMBRE="Titular De Prueba", TITULAR_NIF="00000000T", TITULAR_DOMICILIO="Calle Inventada 1, 30001 Murcia",
               TITULAR_REGISTRO="no", PRECIO_FILTRO="15", PRECIO_FILTRO_PERIODO="mes", PRECIO_ALERTAS="5",
               PRECIO_ALERTAS_PERIODO="mes", PRECIO_INFORME="50", PRECIO_INFORME_PERIODO="por informe",
               PRECIOS_NOTA_IVA="IVA no incluido", PRECIOS_CONTACTO="contacto@ejemplo.test",
               SOCIOS_SOLO_CORREOS="permitido@ejemplo.test")
def datos():
    d = tempfile.mkdtemp(prefix="ensayo_datos_"); sqlite3.connect(os.path.join(d, "cache.db")).close(); return d
pruebas = [["prueba_copia_cache_cifrada.py"], ["socios_prueba.py"], ["socios_pagado_prueba_web.py", "DATOS"],
           ["forma_pago_prueba.py"], ["alta_condiciones_prueba.py"], ["textos_legales_prueba.py"],
           ["precios_prueba.py", "DATOS"], ["listo_vender_prueba.py"] + (["--comparar-con", MAIN_B] if MAIN_B else [])]
res = []
for p in pruebas:
    if not os.path.exists(os.path.join(B, p[0])):
        print(f"{p[0]:34} (no está en esta carpeta: se salta)"); continue
    d = datos(); args = [d if a == "DATOS" else a for a in p]
    t = time.time()
    r = subprocess.run([sys.executable, os.path.join(B, p[0])] + args[1:], cwd=raiz, env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=1800)
    out = r.stdout + r.stderr
    nok = sum(1 for l in out.splitlines() if l.lstrip().startswith("OK"))
    fall = [l for l in out.splitlines() if "FALLO" in l and "FALLOS: 0" not in l and "CON FALLOS: 0" not in l
        and "DIFERENCIAS: 0" not in l]
    res.append((p[0], r.returncode, nok, round(time.time() - t), fall))
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), f"salida_{modo}_{p[0]}.txt"), "w", encoding="utf-8") as f:
        f.write(out)
    shutil.rmtree(d, ignore_errors=True)
    print(f"{p[0]:34} resultado {r.returncode}  OK {nok:4}  {round(time.time()-t):4}s  fallos {len(fall)}", flush=True)
    for l in fall[:15]: print("    " + l[:220], flush=True)
print("TODO BIEN" if all(x[1] == 0 for x in res) else "HAY FALLOS")
