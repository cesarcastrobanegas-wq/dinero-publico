"""Refresco del registro de contratos menores de la Plataforma de Contratación (ficheros
contratos_menores_place_AAAA-MM.json.gz, unos 850.000 contratos) para el flujo de GitHub Actions
.github/workflows/menores-place-semanal.yml. Hasta el 2026-10-06 se generaba a mano.

Por qué no vale refrescar solo el último mes: cada ZIP mensual de la Plataforma trae los contratos ACTUALIZADOS ese
mes, de cualquier fecha de adjudicación, y el reparto por municipios se aprende del conjunto entero (ver
actualizar_contratos_menores_place.py). Así que cada ejecución necesita TODOS los ZIP desde 09/2021. Lo que sí se
ahorra es la descarga: los ZIP de meses cerrados no cambian y se guardan entre ejecuciones (caché de Actions); solo se
vuelven a bajar el del mes en curso y el del mes anterior, que la Plataforma sigue regenerando.

Pasos: 1) descargar lo que falte; 2) generar los ficheros; 3) comparar cada fichero con el que hay en el repositorio
y dejar solo los que cambian de forma apreciable (ver UMBRAL_*; el resto se restaura: así no se guardan decenas de
MB cada semana por uno o dos contratos). Salvaguarda: si el total de contratos baja más de un 3 %, o algún mes con más de 200 contratos pierde más
de un 10 %, no se toca nada y se avisa.

Uso:  python backend/flujo_menores_place.py [--zips DIR]
Nunca termina con error: escribe `cambios` y `problemas` en GITHUB_OUTPUT y el resumen en GITHUB_STEP_SUMMARY.
"""
import glob
import os
import subprocess
import sys
import tempfile
import time

from flujo_menores_semanal import anterior, huella, registros_de, restaurar

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(BASE_DIR)
GENERADOR = os.path.join(BASE_DIR, "actualizar_contratos_menores_place.py")
PRIMER_MES = "202109"
MIN_TOTAL = 0.97
MIN_MES = 0.90
MES_CON_PESO = 200
# Umbral para guardar un mes (2026-10-07, decisión de César: "solo los meses con un cambio apreciable"). En la
# prueba del 06-10 cambiaban 42 de 62 ficheros, pero 31 de ellos por 1-5 contratos; guardarlos todos reescribía unos
# 50 MB por semana. Un mes se guarda si cambian (nuevos + modificados + desaparecidos) al menos UMBRAL_CONTRATOS
# contratos, o al menos el UMBRAL_PCT % del mes con un mínimo de UMBRAL_MINIMO (para los meses pequeños de 2021).
# Lo que no llega no se pierde: se compara siempre con lo guardado, así que se va acumulando hasta pasar el umbral.
UMBRAL_CONTRATOS = 50
UMBRAL_PCT = 1.0
UMBRAL_MINIMO = 10


def contratos_que_cambian(antes, despues):
    """Contratos nuevos o modificados + contratos que desaparecen, entre dos listas de un mismo mes."""
    h_antes, h_despues = set(huella(antes)), set(huella(despues))
    ids_despues = {r.get("id") for r in despues}
    return len(h_despues - h_antes) + sum(1 for r in antes if r.get("id") not in ids_despues)


def se_guarda(n_antes, cambian):
    if n_antes == 0:
        return cambian > 0                      # mes nuevo
    return cambian >= UMBRAL_CONTRATOS or cambian >= max(UMBRAL_MINIMO, UMBRAL_PCT * n_antes / 100)
MINUTOS_DESCARGA = 200
MINUTOS_GENERAR = 100


def mes_anterior(m):
    y, mm = int(m[:4]), int(m[4:])
    return f"{y - 1}12" if mm == 1 else f"{y}{mm - 1:02d}"


def lanzar(args, minutos):
    print(f"\n$ actualizar_contratos_menores_place.py {' '.join(args)}", flush=True)
    try:
        p = subprocess.run([sys.executable, GENERADOR] + args, cwd=BASE_DIR, timeout=minutos * 60,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        codigo, salida = p.returncode, p.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired as e:
        codigo, salida = -9, (e.stdout or b"").decode("utf-8", "replace") + f"\n(cortado a los {minutos} min)"
    print("\n".join(salida.splitlines()[-45:]), flush=True)
    return codigo


def rutas_rel():
    return sorted("backend/" + os.path.basename(f) for f in glob.glob(os.path.join(BASE_DIR, "contratos_menores_place_*.json.gz")))


def restaurar_todo(antes):
    for rel in set(rutas_rel()) | set(antes):
        restaurar(rel, rel in antes)


def terminar(cambios, problema, lineas):
    resumen = "\n".join(["## Registro de contratos menores de la Plataforma", ""] + lineas)
    print("\n" + resumen, flush=True)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(resumen + "\n")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"cambios={cambios}\nproblemas={1 if problema else 0}\n")
    sys.exit(0)


def main():
    zips = os.path.join(tempfile.gettempdir(), "place_menores_zips")
    if "--zips" in sys.argv:
        zips = sys.argv[sys.argv.index("--zips") + 1]
    os.makedirs(zips, exist_ok=True)
    actual = time.strftime("%Y%m", time.gmtime())
    previo = mes_anterior(actual)

    # Estado de partida (lo que hay guardado en el repositorio)
    antes = {}
    for rel in rutas_rel():
        crudo = anterior(rel)
        if crudo:
            antes[rel] = registros_de(crudo)
    total_antes = sum(len(v) for v in antes.values())
    print(f"En el repositorio: {len(antes)} ficheros mensuales, {total_antes} contratos. ZIP en caché: "
          f"{len(glob.glob(os.path.join(zips, '*.zip')))}", flush=True)

    # 1) Descargas: el mes en curso y el anterior se bajan siempre de nuevo
    for m in (actual, previo):
        for nombre in (f"place_menores_{m}.zip", f"men_{m}.zip", f"place_menores_{m}.zip.part"):
            p = os.path.join(zips, nombre)
            if os.path.exists(p):
                os.remove(p)
    desde = actual
    t0 = time.time()
    if lanzar(["descargar", desde, PRIMER_MES, "--zips", zips], MINUTOS_DESCARGA) != 0:
        # A principios de mes la Plataforma puede no haber publicado todavía el ZIP del mes en curso.
        print(f"No se pudo completar la descarga hasta {actual}: se intenta hasta {previo}.", flush=True)
        desde = previo
        if lanzar(["descargar", desde, PRIMER_MES, "--zips", zips], MINUTOS_DESCARGA) != 0:
            terminar(0, True, [f"**No se pudieron descargar los ZIP de la Plataforma** (ni hasta {actual} ni hasta "
                               f"{previo}). No se ha tocado nada; lo ya descargado queda guardado para la próxima vez."])
    t_desc = time.time() - t0

    # 2) Generación
    t0 = time.time()
    codigo = lanzar(["generar", desde, PRIMER_MES, "--zips", zips], MINUTOS_GENERAR)
    t_gen = time.time() - t0
    if codigo != 0:
        restaurar_todo(antes)
        terminar(0, True, [f"**La generación falló** (código {codigo}). Se conservan los ficheros anteriores."])

    # 3) Comparación fichero a fichero
    despues, ilegibles = {}, []
    for rel in rutas_rel():
        try:
            despues[rel] = registros_de(open(os.path.join(RAIZ, rel), "rb").read())
        except Exception:
            ilegibles.append(rel)
    total_despues = sum(len(v) for v in despues.values())
    menguan = [f"{os.path.basename(r)[24:31]}: {len(antes[r])} -> {len(despues.get(r, []))}" for r in antes
               if len(antes[r]) >= MES_CON_PESO and len(despues.get(r, [])) < MIN_MES * len(antes[r])]
    if ilegibles or menguan or (total_antes and total_despues < MIN_TOTAL * total_antes):
        restaurar_todo(antes)
        terminar(0, True, [f"**Resultado sospechoso: no se guarda nada.** Total {total_antes} -> {total_despues} contratos."]
                 + ([f"Meses que pierden más de un 10 %: {'; '.join(menguan)}."] if menguan else [])
                 + ([f"Ficheros ilegibles: {', '.join(ilegibles)}."] if ilegibles else []))

    guardados, aplazados = [], []
    for rel, regs in despues.items():
        previos = antes.get(rel, [])
        cambian = contratos_que_cambian(previos, regs)
        fila = (os.path.basename(rel)[24:31], len(previos), len(regs), cambian)
        if se_guarda(len(previos), cambian):
            guardados.append(fila)
        else:
            restaurar(rel, rel in antes)            # sin cambios, o por debajo del umbral: se deja el que estaba
            if cambian:
                aplazados.append(fila)
    lineas = [f"ZIP hasta {desde[:4]}-{desde[4:]}. Total generado: {total_antes} -> {total_despues} contratos "
              f"({total_despues - total_antes:+d}). Descarga {t_desc / 60:.0f} min, generación {t_gen / 60:.0f} min.", "",
              f"**Meses que se guardan: {len(guardados)}** de {len(despues)} ({sum(f[3] for f in guardados)} contratos "
              f"nuevos, modificados o retirados). Umbral: {UMBRAL_CONTRATOS} contratos, o el {UMBRAL_PCT:g} % del mes "
              f"(mínimo {UMBRAL_MINIMO}).",
              f"Meses con cambios por debajo del umbral, que esperan a acumular más: {len(aplazados)} "
              f"({sum(f[3] for f in aplazados)} contratos).", ""]
    if guardados:
        lineas += ["| Mes guardado | Antes | Ahora | Contratos que cambian |", "|---|---|---|---|"]
        lineas += [f"| {m} | {a} | {d} ({d - a:+d}) | {c} |" for m, a, d, c in sorted(guardados)]
    if aplazados:
        lineas += ["", "Aplazados: " + ", ".join(f"{m} ({c})" for m, a, d, c in sorted(aplazados)) + "."]
    terminar(len(guardados), False, lineas)


if __name__ == "__main__":
    main()
