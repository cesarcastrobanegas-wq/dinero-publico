# encoding: utf-8
"""
Resumen pequeño de los adjudicatarios para el flujo de administradores del BORME (06-11-2026, ancho de banda de
Render).

administradores_borme.py solo necesita de la base de producción dos cosas: los adjudicatarios agregados (clave de
directores, NIF, grafías y recuentos/importes de contratos formales y menores) y la tabla `directores`. Hasta ahora
el flujo diario se bajaba la base entera (1.509 MB sin comprimir) para eso. Este módulo calcula exactamente lo mismo
(con la MISMA función, administradores_borme.adjudicatarios) y lo guarda en un JSON comprimido de unos pocos MB:

  - en la web: /admin/resumen-administradores lo ejecuta como proceso aparte (la memoria se libera al acabar) y
    sirve el fichero; si hay uno de menos de --vigencia segundos, lo reutiliza;
  - en el flujo: administradores_borme.py --resumen fichero.json.gz lo lee en lugar de --cache.

No imprime nunca nombres ni NIF: solo recuentos. Lleva los mismos datos que ya viajaban dentro de la base (nada nuevo
sale de la web), solo que muchos menos.

    python backend/resumen_adjudicatarios.py --cache ruta/cache.db --salida ruta/resumen.json.gz [--vigencia 7200]
"""
import argparse
import gzip
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

VERSION = 1


def construir(cache_path):
    """Dict serializable con lo que administradores_borme.adjudicatarios() saca de la base."""
    from administradores_borme import adjudicatarios
    adj, directores = adjudicatarios(cache_path)
    return {"version": VERSION, "generado": time.strftime("%Y-%m-%d %H:%M:%S"),
            "adjudicatarios": {k: dict(v, nombres=list(v["nombres"])) for k, v in adj.items()},
            "directores": {k: [n, cg] for k, (n, cg) in directores.items()}}


def escribir(cache_path, salida):
    """Escribe el resumen comprimido (escritura atómica). Devuelve (adjudicatarios, directores, bytes)."""
    datos = construir(cache_path)
    crudo = json.dumps(datos, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    tmp = salida + ".nuevo"
    with open(tmp, "wb") as f:
        f.write(gzip.compress(crudo, compresslevel=6, mtime=0))
    os.replace(tmp, salida)
    return len(datos["adjudicatarios"]), len(datos["directores"]), os.path.getsize(salida)


def leer(ruta):
    """(adj, directores) con las mismas estructuras que administradores_borme.adjudicatarios(). ValueError si el
    fichero no es un resumen válido de esta versión."""
    with open(ruta, "rb") as f:
        crudo = f.read()
    try:
        datos = json.loads(gzip.decompress(crudo) if crudo[:2] == b"\x1f\x8b" else crudo)
    except Exception as e:
        raise ValueError(f"resumen ilegible: {type(e).__name__}") from None
    if not isinstance(datos, dict) or datos.get("version") != VERSION or not datos.get("adjudicatarios"):
        raise ValueError("no es un resumen de adjudicatarios válido (versión o contenido)")
    adj = {k: dict(v, nombres=dict.fromkeys(v["nombres"])) for k, v in datos["adjudicatarios"].items()}
    directores = {k: (v[0], v[1]) for k, v in datos["directores"].items()}
    return adj, directores


def al_dia(salida, vigencia):
    return os.path.exists(salida) and time.time() - os.path.getmtime(salida) < vigencia


# ── En la web: /admin/resumen-administradores ─────────────────────────────────────────────────────────────────────
# Preparar el resumen lleva su tiempo (recorrer todas las fichas) y una petición larga la corta el proxy de Render
# (~100 s). Por eso la ruta NO espera: si no hay un resumen reciente, lanza su preparación en un hilo (que a su vez
# la ejecuta como PROCESO APARTE, para que la memoria se libere al acabar y no se toque _db_lock) y contesta 202;
# el flujo vuelve a preguntar hasta recibir el 200 con el fichero.
VIGENCIA_WEB_S = 2 * 3600
_estado_web = {"hilo": None, "error": "", "desde": 0.0}
_cerrojo_web = __import__("threading").Lock()


def _preparar_web(db_file, ruta):
    import subprocess
    try:
        subprocess.run([sys.executable, os.path.abspath(__file__), "--cache", db_file, "--salida", ruta],
                       check=True, timeout=3600, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        _estado_web["error"] = ""
    except subprocess.CalledProcessError as e:
        ultima = ((e.stderr or b"").decode("utf-8", "replace").strip().splitlines() or ["?"])[-1]
        _estado_web["error"] = f"código {e.returncode}: {ultima[:200]}"
    except Exception as e:
        _estado_web["error"] = type(e).__name__


def servir_web(db_file, data_dir):
    """(código, cabeceras, cuerpo) para la ruta de la web: 200 con el resumen, 202 mientras se prepara o 500 si la
    última preparación falló (la siguiente petición lo vuelve a intentar)."""
    import hashlib
    import threading
    ruta = os.path.join(data_dir, ".resumen_administradores.json.gz")
    with _cerrojo_web:
        hilo = _estado_web["hilo"]
        en_marcha = hilo is not None and hilo.is_alive()
        if not en_marcha and al_dia(ruta, VIGENCIA_WEB_S):
            with open(ruta, "rb") as f:
                cuerpo = f.read()
            return 200, {"Content-Type": "application/gzip", "Cache-Control": "no-store",
                         "Content-Disposition": 'attachment; filename="resumen_administradores.json.gz"',
                         "X-Resumen-Sha256": hashlib.sha256(cuerpo).hexdigest(),
                         "Content-Length": str(len(cuerpo))}, cuerpo
        if not en_marcha and hilo is not None and _estado_web["error"]:
            error, _estado_web["hilo"], _estado_web["error"] = _estado_web["error"], None, ""
            cuerpo = json.dumps({"error": "No se pudo preparar el resumen: " + error}, ensure_ascii=False).encode()
            return 500, {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store",
                         "Content-Length": str(len(cuerpo))}, cuerpo
        if not en_marcha:
            _estado_web["hilo"] = threading.Thread(target=_preparar_web, args=(db_file, ruta), daemon=True,
                                                   name="resumen-administradores")
            _estado_web["desde"] = time.time()
            _estado_web["hilo"].start()
        cuerpo = json.dumps({"estado": "preparando", "segundos": round(time.time() - _estado_web["desde"])}).encode()
        return 202, {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store",
                     "Retry-After": "30", "Content-Length": str(len(cuerpo))}, cuerpo


def comprobar(ruta, minimo=1000):
    """True si `ruta` es un resumen legible con al menos `minimo` adjudicatarios (imprime solo recuentos)."""
    try:
        adj, directores = leer(ruta)
    except (OSError, ValueError) as e:
        print(f"resumen no válido: {e}")
        return False
    print(f"resumen: {len(adj)} adjudicatarios, {len(directores)} directores")
    if len(adj) < minimo:
        print(f"resumen no válido: menos de {minimo} adjudicatarios")
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache")
    ap.add_argument("--salida")
    ap.add_argument("--vigencia", type=int, default=0, help="segundos: si hay un resumen más reciente, no se rehace")
    ap.add_argument("--comprobar", metavar="RUTA", help="solo comprueba un resumen ya bajado (sale con 1 si no vale)")
    a = ap.parse_args()
    if a.comprobar:
        sys.exit(0 if comprobar(a.comprobar) else 1)
    if not a.cache or not a.salida:
        ap.error("hacen falta --cache y --salida")
    if a.vigencia and al_dia(a.salida, a.vigencia):
        print("resumen reutilizado", flush=True)
        return
    cerrojo = None
    try:                                  # dos peticiones a la vez: la segunda espera y reutiliza el de la primera
        import fcntl
        cerrojo = open(a.salida + ".cerrojo", "w")
        fcntl.flock(cerrojo, fcntl.LOCK_EX)
        if a.vigencia and al_dia(a.salida, a.vigencia):
            print("resumen reutilizado", flush=True)
            return
    except ImportError:                   # Windows (pruebas en local): sin cerrojo
        pass
    t0 = time.time()
    n_adj, n_dir, tam = escribir(a.cache, a.salida)
    print(f"resumen: {n_adj} adjudicatarios, {n_dir} directores, {tam} bytes, {time.time() - t0:.0f} s", flush=True)
    if cerrojo:
        cerrojo.close()


if __name__ == "__main__":
    main()
