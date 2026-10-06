"""Ejecuta uno a uno los generadores de contratos menores de ayuntamientos (actualizar_contratos_menores_*.py) y
decide, fuente a fuente, si el fichero nuevo sustituye al que hay en el repositorio. Lo lanza el flujo semanal de
GitHub Actions (.github/workflows/menores-fuentes-semanal.yml): allí se pueden instalar las librerías de lectura de
PDF y hojas de cálculo que producción no tiene, y hasta el 2026-10-06 estos generadores solo se ejecutaban a mano.

Salvaguarda (misma idea que _fusionar_fuente en actualizar_contratos_menores_murcia_manual.py): el fichero nuevo solo
se queda si el generador terminó bien, el fichero se puede leer y no trae menos del 90 % de los contratos que ya
había. Si no, se restaura el anterior con git y la fuente sale en el resumen como problema. Un fichero que solo
cambia de fecha de generación (mismos contratos) también se restaura, para no guardar ni reiniciar la web por nada.

Uso:  python backend/flujo_menores_semanal.py [--solo gijon,zaragoza]
Nunca termina con error por una fuente: escribe `cambios` y `problemas` en GITHUB_OUTPUT y el resumen en
GITHUB_STEP_SUMMARY, y el flujo decide.
"""
import glob
import gzip
import json
import os
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PREFIJO = "actualizar_contratos_menores_"

# Fuera del flujo semanal, con su motivo (se listan en el resumen para que no se olviden).
EXCLUIDOS = {
    "place": "registro de menores de la Plataforma: necesita todos los ZIP mensuales desde 2021 (flujo aparte)",
    "cadiz": "el ayuntamiento solo publicó el listado de 2023",
    "salamanca": "el ayuntamiento no publica nada posterior al primer trimestre de 2024",
}
MINUTOS = {"murcia_manual": 150, "euskadi": 150}      # el resto, MINUTOS_POR_DEFECTO
MINUTOS_POR_DEFECTO = 40
MINIMO_RELATIVO = 0.9
MINIMO_PARA_COMPARAR = 20       # con menos contratos que esto no se aplica el 90 % (un contrato menos ya sería un 5 %)


def registros_de(crudo):
    """Lista de contratos de un fichero de salida (bytes del .json.gz). Lanza si no se puede leer."""
    d = json.loads(gzip.decompress(crudo).decode("utf-8"))
    if isinstance(d, dict):
        d = d.get("registros", d.get("contratos"))
    if not isinstance(d, list):
        raise ValueError("el fichero no trae una lista de contratos")
    return d


def anterior(ruta_rel):
    """Bytes del fichero tal como está guardado en el repositorio (HEAD), o None si es nuevo."""
    r = subprocess.run(["git", "show", f"HEAD:{ruta_rel}"], capture_output=True, cwd=os.path.dirname(BASE_DIR))
    return r.stdout if r.returncode == 0 and r.stdout else None


def restaurar(ruta_rel, habia):
    raiz = os.path.dirname(BASE_DIR)
    if habia:
        subprocess.run(["git", "checkout", "HEAD", "--", ruta_rel], cwd=raiz, check=True)
    elif os.path.exists(os.path.join(raiz, ruta_rel)):
        os.remove(os.path.join(raiz, ruta_rel))


def huella(registros):
    return sorted(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in registros)


def decidir(n_antes, registros_antes, codigo, crudo_nuevo):
    """(estado, detalle, conservar_nuevo). estado: actualizada | sin cambios | fallo | menos contratos."""
    if codigo != 0:
        return "fallo", f"el generador terminó con código {codigo}", False
    if crudo_nuevo is None:
        return "fallo", "el generador no dejó fichero", False
    try:
        nuevos = registros_de(crudo_nuevo)
    except Exception as e:
        return "fallo", f"fichero ilegible ({type(e).__name__})", False
    if n_antes is not None and n_antes >= MINIMO_PARA_COMPARAR and len(nuevos) < MINIMO_RELATIVO * n_antes:
        return "menos contratos", f"{len(nuevos)} frente a {n_antes} que había", False
    if not nuevos and not n_antes:
        return "fallo", "0 contratos", False
    if registros_antes is not None and huella(nuevos) == huella(registros_antes):
        return "sin cambios", f"{len(nuevos)} contratos", False
    if n_antes is None:
        return "actualizada", f"fichero nuevo, {len(nuevos)} contratos", True
    return "actualizada", f"{n_antes} -> {len(nuevos)} contratos ({len(nuevos) - n_antes:+d})", True


def ejecutar(nombre):
    script = os.path.join(BASE_DIR, f"{PREFIJO}{nombre}.py")
    ruta_rel = f"backend/contratos_menores_{nombre}.json.gz"
    ruta = os.path.join(os.path.dirname(BASE_DIR), ruta_rel)
    crudo_antes = anterior(ruta_rel)
    registros_antes = n_antes = None
    if crudo_antes:
        try:
            registros_antes = registros_de(crudo_antes)
            n_antes = len(registros_antes)
        except Exception:
            pass
    minutos = MINUTOS.get(nombre, MINUTOS_POR_DEFECTO)
    t0 = time.time()
    print(f"\n===== {nombre} (hasta {minutos} min; había {n_antes} contratos) =====", flush=True)
    try:
        p = subprocess.run([sys.executable, script], cwd=BASE_DIR, timeout=minutos * 60,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        codigo, salida = p.returncode, p.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired as e:
        codigo, salida = -9, (e.stdout or b"").decode("utf-8", "replace") + f"\n(cortado a los {minutos} min)"
    print("\n".join(salida.splitlines()[-25:]), flush=True)       # el final del registro del generador
    crudo_nuevo = open(ruta, "rb").read() if os.path.exists(ruta) else None
    estado, detalle, conservar = decidir(n_antes, registros_antes, codigo, crudo_nuevo)
    if codigo == -9:
        detalle = f"cortado a los {minutos} min"
    if not conservar:
        restaurar(ruta_rel, crudo_antes is not None)
    print(f"-> {nombre}: {estado} ({detalle}), {time.time() - t0:.0f} s", flush=True)
    return {"fuente": nombre, "estado": estado, "detalle": detalle, "segundos": round(time.time() - t0)}


def main():
    solo = []
    if "--solo" in sys.argv:
        solo = [x.strip() for x in sys.argv[sys.argv.index("--solo") + 1].split(",") if x.strip()]
    todos = sorted(os.path.basename(f)[len(PREFIJO):-3] for f in glob.glob(os.path.join(BASE_DIR, PREFIJO + "*.py")))
    desconocidos = [s for s in solo if s not in todos]
    if desconocidos:
        sys.exit(f"Fuente(s) desconocida(s): {desconocidos}. Válidas: {todos}")
    pedidos = solo or [n for n in todos if n not in EXCLUIDOS]
    filas = [ejecutar(n) for n in pedidos]

    cambios = [f for f in filas if f["estado"] == "actualizada"]
    problemas = [f for f in filas if f["estado"] in ("fallo", "menos contratos")]
    lineas = ["## Contratos menores de ayuntamientos", "",
              f"{len(filas)} fuentes ejecutadas: {len(cambios)} actualizadas, "
              f"{len(filas) - len(cambios) - len(problemas)} sin cambios, {len(problemas)} con problemas "
              "(en esas se conserva el fichero anterior).", "",
              "| Fuente | Resultado | Detalle | Tiempo |", "|---|---|---|---|"]
    orden = {"fallo": 0, "menos contratos": 0, "actualizada": 1, "sin cambios": 2}
    for f in sorted(filas, key=lambda f: (orden[f["estado"]], f["fuente"])):
        lineas.append(f"| {f['fuente']} | {f['estado']} | {f['detalle']} | {f['segundos']} s |")
    if not solo:
        lineas += ["", "Fuera de este flujo: " + "; ".join(f"{k} ({v})" for k, v in sorted(EXCLUIDOS.items())) + "."]
    resumen = "\n".join(lineas)
    print("\n" + resumen, flush=True)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(resumen + "\n")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"cambios={len(cambios)}\nproblemas={len(problemas)}\n")
            f.write("fuentes_problema=" + ", ".join(p["fuente"] for p in problemas) + "\n")
            f.write("fuentes_cambio=" + ", ".join(c["fuente"] for c in cambios) + "\n")


if __name__ == "__main__":
    main()
