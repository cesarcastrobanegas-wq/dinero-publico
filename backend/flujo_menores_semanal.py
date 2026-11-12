"""Ejecuta uno a uno los generadores de contratos menores de ayuntamientos (actualizar_contratos_menores_*.py) y
decide, fuente a fuente, si el fichero nuevo sustituye al que hay en el repositorio. Lo lanza el flujo semanal de
GitHub Actions (.github/workflows/menores-fuentes-semanal.yml): allí se pueden instalar las librerías de lectura de
PDF y hojas de cálculo que producción no tiene, y hasta el 2026-10-06 estos generadores solo se ejecutaban a mano.

Salvaguarda (misma idea que _fusionar_fuente en actualizar_contratos_menores_murcia_manual.py): el fichero nuevo solo
se queda si el generador terminó bien, el fichero se puede leer y no trae menos del 90 % de los contratos que ya
había dentro de la ventana de 5 años (los que salen de la ventana no cuentan como pérdida, y se vuelven a meter en el
fichero nuevo: lo ya guardado no se borra). Si no, se restaura el anterior con git y la fuente sale en el resumen como problema. Un fichero que solo
cambia de fecha de generación (mismos contratos) también se restaura, para no guardar ni reiniciar la web por nada.

Si el generador avisa de errores de descarga («!! ...: error de descarga») y no llega a escribir su fichero, es que
fallaron TODAS las descargas: cuenta como problema («fallan las descargas»), no como «sin cambios» (Alicante y
Fuenlabrada, 01-11 y 08-11-2026, salían «sin cambios» con los datos parados). En los problemas, el resumen dice desde
qué fecha están sin actualizar (la «generado» del fichero que se conserva).

Uso:  python backend/flujo_menores_semanal.py [--solo gijon,zaragoza]
Nunca termina con error por una fuente: escribe `cambios` y `problemas` en GITHUB_OUTPUT y el resumen en
GITHUB_STEP_SUMMARY, y el flujo decide.
"""
import glob
import gzip
import json
import os
import re
import subprocess
import sys
import time

from alcance import alcance_desde

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PREFIJO = "actualizar_contratos_menores_"

# Fuera del flujo semanal, con su motivo (se listan en el resumen para que no se olviden).
EXCLUIDOS = {
    "place": "registro de menores de la Plataforma: necesita todos los ZIP mensuales desde 2021 (flujo aparte)",
    "cadiz": "el ayuntamiento solo publicó el listado de 2023",
    "salamanca": "el ayuntamiento no publica nada posterior al primer trimestre de 2024",
    # Sus servidores rechazan las conexiones desde GitHub (prueba del 2026-10-06: Sevilla no contesta, València
    # devuelve 403). Los generadores funcionan desde un PC; hasta darles otra vía, siguen siendo manuales.
    "sevilla": "el servidor del ayuntamiento no contesta a las conexiones desde GitHub (sigue manual)",
    "valencia_capital": "el servidor del ayuntamiento rechaza las conexiones desde GitHub, error 403 (sigue manual)",
    # Fallos del 2026-10-18 y 2026-10-25 (decisión de César del 2026-10-27: a manual).
    "burgos": "el servidor del ayuntamiento no contesta a las conexiones desde GitHub (sigue manual)",
    "almeria": "el servidor del ayuntamiento corta la conexión al agente del proyecto (sigue manual)",
    # Fallos del 2026-11-01 y 2026-11-08: desde GitHub no conectan; desde el PC, sí (decisión de César del 09-11).
    # Se lanzan desde el PC con: python backend/menores_desde_pc.py (ver MENORES_DESDE_PC.md).
    "alicante": "desde GitHub todas las descargas tardan demasiado; desde un PC, bien (manual: menores_desde_pc.py)",
    "santa_cruz": "el servidor del ayuntamiento no contesta a las conexiones desde GitHub (manual: menores_desde_pc.py)",
}
MINUTOS = {"murcia_manual": 150, "euskadi": 210}      # el resto, MINUTOS_POR_DEFECTO
MINUTOS_POR_DEFECTO = 40
MINIMO_RELATIVO = 0.9
PROBLEMAS = ("fallo", "menos contratos", "fallan las descargas")   # se conserva el fichero anterior y se avisa
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


def fuera_de_ventana(r):
    """True si el contrato es anterior al corte de 5 años (alcance.py). Los que no traen fecha cuentan como dentro."""
    return bool(r.get("data_adjudicacio")) and str(r["data_adjudicacio"])[:10] < alcance_desde()


def dentro_de_ventana(registros):
    """Cuántos contratos siguen dentro de la ventana de 5 años. Los generadores ya no traen los anteriores al corte,
    así que el 90 % se mide solo con estos: si no, cada mes que avanza la ventana parecería que la fuente pierde
    contratos (Leganés, 2026-10-18 y 25: 254 -> 215, que eran 39 de antes de 2021-10-01)."""
    return sum(1 for r in registros if not fuera_de_ventana(r))


def con_antiguos(ruta, crudo_nuevo, registros_antes):
    """Vuelve a meter en el fichero nuevo los contratos del anterior que ya están fuera de la ventana y el generador
    ya no trae: lo ya guardado no se borra por salir de la ventana (alcance.py; decisión de César del 2026-10-27).
    Reescribe `ruta` y devuelve los bytes nuevos; si no hay nada que añadir o no se puede leer, no toca nada."""
    try:
        d = json.loads(gzip.decompress(crudo_nuevo).decode("utf-8"))
        nuevos = registros_de(crudo_nuevo)
    except Exception:
        return crudo_nuevo                  # decidir() lo marcará como ilegible
    ids = {r.get("id") for r in nuevos}
    antiguos = [r for r in registros_antes if fuera_de_ventana(r) and r.get("id") not in ids]
    if not antiguos or not isinstance(d, dict):
        return crudo_nuevo
    d["registros" if "registros" in d else "contratos"] = nuevos + antiguos
    with gzip.open(ruta, "wt", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    print(f"(se conservan {len(antiguos)} contratos anteriores a {alcance_desde()} que ya no trae la fuente)",
          flush=True)
    return open(ruta, "rb").read()


RE_ERROR_DESCARGA = re.compile(r"!!.*error de descarga")


def errores_de_descarga(salida):
    """Cuántas descargas dice el generador que han fallado (líneas «!! ...: error de descarga»)."""
    return sum(1 for l in salida.splitlines() if RE_ERROR_DESCARGA.search(l))


def generado_de(crudo):
    """Fecha «generado» de un fichero guardado (la última vez que se actualizó de verdad), o None."""
    try:
        d = json.loads(gzip.decompress(crudo).decode("utf-8"))
        return str(d.get("generado") or "")[:10] or None if isinstance(d, dict) else None
    except Exception:
        return None


def marca_fichero(ruta):
    try:
        st = os.stat(ruta)
        return st.st_mtime_ns, st.st_size
    except OSError:
        return None


def huella(registros):
    return sorted(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in registros)


def decidir(n_antes, registros_antes, codigo, crudo_nuevo, errores_descarga=0, escribio=True):
    """(estado, detalle, conservar_nuevo).
    estado: actualizada | sin cambios | fallo | menos contratos | fallan las descargas."""
    if codigo != 0:
        return "fallo", f"el generador terminó con código {codigo}", False
    if errores_descarga and not escribio:
        return ("fallan las descargas", f"fallaron las {errores_descarga} descargas y no escribió nada"
                if errores_descarga > 1 else "falló la descarga y no escribió nada", False)
    if crudo_nuevo is None:
        return "fallo", "el generador no dejó fichero", False
    try:
        nuevos = registros_de(crudo_nuevo)
    except Exception as e:
        return "fallo", f"fichero ilegible ({type(e).__name__})", False
    n_nuevos = dentro_de_ventana(nuevos)    # sin los antiguos que con_antiguos() haya vuelto a meter
    if n_antes is not None and n_antes >= MINIMO_PARA_COMPARAR and n_nuevos < MINIMO_RELATIVO * n_antes:
        return "menos contratos", f"{n_nuevos} frente a {n_antes} que había (dentro de la ventana)", False
    if not nuevos and not n_antes:
        return "fallo", "0 contratos", False
    if registros_antes is not None and huella(nuevos) == huella(registros_antes):
        return "sin cambios", f"{len(nuevos)} contratos", False
    if n_antes is None:
        return "actualizada", f"fichero nuevo, {len(nuevos)} contratos", True
    antes = len(registros_antes)
    return "actualizada", f"{antes} -> {len(nuevos)} contratos ({len(nuevos) - antes:+d})", True


def ejecutar(nombre):
    script = os.path.join(BASE_DIR, f"{PREFIJO}{nombre}.py")
    ruta_rel = f"backend/contratos_menores_{nombre}.json.gz"
    ruta = os.path.join(os.path.dirname(BASE_DIR), ruta_rel)
    crudo_antes = anterior(ruta_rel)
    registros_antes = n_antes = None
    if crudo_antes:
        try:
            registros_antes = registros_de(crudo_antes)
            n_antes = dentro_de_ventana(registros_antes)
        except Exception:
            pass
    minutos = MINUTOS.get(nombre, MINUTOS_POR_DEFECTO)
    marca_antes = marca_fichero(ruta)
    t0 = time.time()
    print(f"\n===== {nombre} (hasta {minutos} min; había {n_antes} contratos) =====", flush=True)
    try:
        p = subprocess.run([sys.executable, script], cwd=BASE_DIR, timeout=minutos * 60,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        codigo, salida = p.returncode, p.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired as e:
        codigo, salida = -9, (e.stdout or b"").decode("utf-8", "replace") + f"\n(cortado a los {minutos} min)"
    print("\n".join(salida.splitlines()[-25:]), flush=True)       # el final del registro del generador
    errores = errores_de_descarga(salida)
    escribio = marca_fichero(ruta) != marca_antes
    crudo_nuevo = open(ruta, "rb").read() if os.path.exists(ruta) else None
    if codigo == 0 and escribio and crudo_nuevo is not None and registros_antes:
        crudo_nuevo = con_antiguos(ruta, crudo_nuevo, registros_antes)
    estado, detalle, conservar = decidir(n_antes, registros_antes, codigo, crudo_nuevo, errores, escribio)
    if codigo == -9:
        detalle = f"cortado a los {minutos} min"
    if estado in PROBLEMAS:
        desde = generado_de(crudo_antes) if crudo_antes else None
        detalle += f"; sin actualizar desde el {desde}" if desde else "; no hay datos anteriores"
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
    problemas = [f for f in filas if f["estado"] in PROBLEMAS]
    lineas = ["## Contratos menores de ayuntamientos", "",
              f"{len(filas)} fuentes ejecutadas: {len(cambios)} actualizadas, "
              f"{len(filas) - len(cambios) - len(problemas)} sin cambios, {len(problemas)} con problemas "
              "(en esas se conserva el fichero anterior).", "",
              "| Fuente | Resultado | Detalle | Tiempo |", "|---|---|---|---|"]
    orden = {**{e: 0 for e in PROBLEMAS}, "actualizada": 1, "sin cambios": 2}
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
            f.write(f"cambios={len(cambios)}\nproblemas={len(problemas)}\nejecutadas={len(filas)}\n")
            # 06-11: el detalle de cada fuente con problemas, para el aviso y el histórico semanal del flujo
            f.write("detalle_problemas=" + "; ".join(f"{p['fuente']} ({p['detalle']})".replace("\n", " ")
                                                     for p in problemas) + "\n")
            f.write("fuentes_problema=" + ", ".join(p["fuente"] for p in problemas) + "\n")
            f.write("fuentes_cambio=" + ", ".join(c["fuente"] for c in cambios) + "\n")


if __name__ == "__main__":
    main()
