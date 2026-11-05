# encoding: utf-8
"""
Fondos UE desde el PC del titular (2026-11-05): lo mismo que el flujo «Fondos UE de toda España (semanal)», pero
ejecutado aquí, porque desde el 21-10 la Comisión Europea bloquea por IP a GitHub Actions en Kohesio (403 de su
balanceador; al PC responde). Genera el fichero con las cuatro fuentes (Cohesion Data, CORDIS, Kohesio y los 100
perceptores del Plan) y lo sube a la web con POST /admin/fondos-ue, igual que el flujo:
  - si UNA fuente falla, sube las demás con ?conservar=<fuente> (la web se queda con lo último bueno de esa fuente) y
    termina con código 1, para que se vea;
  - si la subida trae más de un 20 % menos de lo que hay, la web responde 409 y no cambia nada;
  - si la web se está reiniciando (502/503/504...), reintenta durante 5 minutos.
El token NO se guarda en ningún sitio: se pide sin que se vea al escribir (o --token). El fichero generado se borra al
acabar. Tarda alrededor de una hora (casi todo, Kohesio). Fuera del refresco nocturno.

    python backend/subir_fondos_ue_pc.py                     (pide el token)
    python backend/subir_fondos_ue_pc.py --solo-generar      (genera y cuenta, sin subir nada)
"""
import argparse
import getpass
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fondos_ue_espana as F  # noqa: E402

URL = "https://dinero-publico.com/admin/fondos-ue"
_REINTENTABLES = {502, 503, 504, 520, 521, 522, 523, 524}


def subir(ruta, token, url=URL, espera_max=300, pausa=30, requests_mod=None):
    """Sube el fichero como el flujo. Devuelve (código HTTP, respuesta en JSON o texto, fuente conservada o '')."""
    import requests
    rq = requests_mod or requests
    falta = ""
    if os.path.exists(ruta + ".falta"):
        with open(ruta + ".falta", encoding="utf-8") as f:
            falta = f.readline().strip()
    destino = url + (f"?conservar={falta}" if falta else "")
    with open(ruta, "rb") as f:
        datos = f.read()
    fin = time.time() + espera_max
    while True:
        try:
            r = rq.post(destino, data=datos, timeout=600,
                        headers={"Content-Type": "application/gzip", "X-Admin-Token": token})
            codigo = r.status_code
        except rq.RequestException as e:
            codigo, r = 0, None
            print(f"  sin respuesta ({type(e).__name__})", flush=True)
        if codigo in _REINTENTABLES or codigo == 0:
            if time.time() >= fin:
                return codigo, "la web sigue sin responder tras 5 minutos", falta
            print(f"  HTTP {codigo}: ¿la web se está reiniciando? Reintento en {pausa} s", flush=True)
            time.sleep(pausa)
            continue
        try:
            cuerpo = r.json()
        except ValueError:
            cuerpo = r.text[:500]
        return codigo, cuerpo, falta


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--token", help="token de administración (si no, se pide sin que se vea)")
    ap.add_argument("--solo-generar", action="store_true", help="generar y contar, sin subir nada")
    a = ap.parse_args(argv)
    token = ""
    if not a.solo_generar:
        token = (a.token or getpass.getpass("Token de administración (no se ve al escribir): ")).strip()
        if not token or token == "TU_TOKEN_AQUI":
            sys.exit("Falta el token de administración (cambia TU_TOKEN_AQUI por el tuyo, o no pongas --token).")
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="fondos_ue_") as d:
        ruta = os.path.join(d, "fondos_ue.ndjson.gz")
        resumen = F.generar(ruta, con_nombres=True, una_fuente_opcional=True)
        print(f"Generado en {(time.time() - t0) / 60:.0f} min.", flush=True)
        if a.solo_generar:
            print("--solo-generar: no se sube nada.")
            return resumen
        codigo, cuerpo, falta = subir(ruta, token)
    print(f"HTTP {codigo}: {json.dumps(cuerpo, ensure_ascii=False) if not isinstance(cuerpo, str) else cuerpo}")
    if codigo != 200:
        sys.exit(f"La web no ha aceptado la subida (HTTP {codigo}). No ha cambiado nada.")
    if falta:
        k = (cuerpo or {}).get("conservado") or {} if isinstance(cuerpo, dict) else {}
        sys.exit(f"Subido, pero SIN {F.FUENTES_NOMBRE.get(falta, falta)}: la web conserva {k.get('conservadas', 0)} "
                 f"operaciones suyas de la carga del {k.get('de_la_carga_del') or '?'}.")
    print(f"Hecho: las cuatro fuentes subidas en {(time.time() - t0) / 60:.0f} min.")
    return cuerpo


if __name__ == "__main__":
    main()
