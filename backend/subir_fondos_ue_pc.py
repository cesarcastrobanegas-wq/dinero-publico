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

# 26-11-2026: en la consola de Windows, getpass lee tecla a tecla; pegar con Ctrl+V no pega el texto, sino el carácter
# de control \x16, que .strip() no quita. Cloudflare rechaza una cabecera así con un 400 VACÍO, sin que la petición
# llegue a la web (comprobado: una cabecera con \x16 da 400 y 0 bytes; la misma con texto normal, 200).
COMO_PEGAR = ("En la consola de Windows, pega con clic DERECHO (Ctrl+V no pega aquí: mete un carácter de control); "
              "en Windows Terminal, con Ctrl+Shift+V.")


def problema_token(token):
    """Texto con el problema del token, o None si vale. Nunca incluye el token ni ningún trozo suyo."""
    if not token or token == "TU_TOKEN_AQUI":
        return "Falta el token de administración (cambia TU_TOKEN_AQUI por el tuyo, o no pongas --token)."
    raros = [c for c in token if not (33 <= ord(c) <= 126)]
    if raros:
        control = sum(1 for c in raros if ord(c) < 32 or ord(c) == 127)
        return (f"El token tiene {len(raros)} carácter(es) que no son letras, cifras ni signos"
                + (f" ({control} de control: suele ser un Ctrl+V)" if control else "")
                + ". La web lo rechazaría con un 400 vacío. " + COMO_PEGAR)
    return None


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
        if not a.token:
            print(COMO_PEGAR)
        token = (a.token or getpass.getpass("Token de administración (no se ve al escribir): ")).strip()
        problema = problema_token(token)          # antes de generar: no esperar 6-30 min para nada
        if problema:
            sys.exit(problema)
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
        if codigo == 400 and not cuerpo:
            sys.exit("HTTP 400 sin respuesta de la web: lo ha rechazado Cloudflare antes de llegar (casi siempre, una "
                     "cabecera con un carácter raro). No ha cambiado nada. " + COMO_PEGAR)
        sys.exit(f"La web no ha aceptado la subida (HTTP {codigo}). No ha cambiado nada.")
    if falta:
        k = (cuerpo or {}).get("conservado") or {} if isinstance(cuerpo, dict) else {}
        sys.exit(f"Subido, pero SIN {F.FUENTES_NOMBRE.get(falta, falta)}: la web conserva {k.get('conservadas', 0)} "
                 f"operaciones suyas de la carga del {k.get('de_la_carga_del') or '?'}.")
    print(f"Hecho: las cuatro fuentes subidas en {(time.time() - t0) / 60:.0f} min.")
    return cuerpo


if __name__ == "__main__":
    main()
