# encoding: utf-8
"""Prueba del freno del despliegue (comprobar_despliegue.py): con el app.py de verdad pasa, y con copias estropeadas a
propósito (filtro quitado, apagado por defecto, letras cambiadas, una salida que se lo salta...) PARA el despliegue.

    python backend/prueba_comprobar_despliegue.py        (~1-2 min: lee app.py una vez por caso; sin red ni datos)
"""
import os
import re
import subprocess
import sys
import tempfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(BASE_DIR, "app.py")
GUARDIA = os.path.join(BASE_DIR, "comprobar_despliegue.py")


def _cambiar(texto, viejo, nuevo, cuantas=1):
    assert texto.count(viejo) >= 1, viejo[:80]
    return texto.replace(viejo, nuevo, cuantas)


CASOS = [
    ("sin cambios", None, 0),
    ("filtro quitado de _app_wsgi",
     lambda s: re.sub(r"\n    code, headers, body = _filtro_salida_dni\(.*?\n(.*?\n)", "\n", s, count=1, flags=re.S), 1),
    ("filtro apagado por defecto",
     lambda s: _cambiar(s, 'os.environ.get("FILTRO_SALIDA_DNI", "1")', 'os.environ.get("FILTRO_SALIDA_DNI", "0")'), 1),
    ("letras de control cambiadas",
     lambda s: _cambiar(s, '_LETRAS_DNI = b"TRWAGMYFPDXBNJZSQVHLCKE"', '_LETRAS_DNI = b"RWAGMYFPDXBNJZSQVHLCKET"'), 1),
    ("una respuesta que sale antes del filtro",
     lambda s: _cambiar(s, "    if path == \"/admin/revision\" or path.startswith(\"/admin/revision/\"):",
                        "    if path == \"/atajo\":\n        start_response(\"200 OK\", [])\n        return [b\"x\"]\n"
                        "    if path == \"/admin/revision\" or path.startswith(\"/admin/revision/\"):"), 1),
    ("la respuesta se cambia después del filtro",
     lambda s: _cambiar(s, "    status_line = f\"{code} {_HTTP_STATUS_TEXT.get(code, 'OK')}\"",
                        "    body = body + b\"\"\n    status_line = f\"{code} {_HTTP_STATUS_TEXT.get(code, 'OK')}\""), 1),
    ("otra salida WSGI con estado variable",
     lambda s: s + "\n\ndef otra_salida(environ, start_response):\n    estado = '200 OK'\n"
                   "    start_response(estado, [])\n    return [b'x']\n", 1),
    ("el filtro no se ejecuta",
     lambda s: _cambiar(s, "def enmascarar_dni_en_bytes(b):", "_ROTO = no_existe()\n\n\ndef enmascarar_dni_en_bytes(b):"), 1),
    ("app.py con un error de sintaxis", lambda s: s + "\ndef (:\n", 1),
]


def main():
    with open(APP, encoding="utf-8", newline="") as f:
        original = f.read()
    tmp = tempfile.mkdtemp(prefix="freno_despliegue_")
    mal = []
    for nombre, cambio, esperado in CASOS:
        ruta = APP
        if cambio is not None:
            texto = cambio(original)
            if texto == original:
                mal.append(f"{nombre}: el cambio de prueba no ha cambiado nada (¿ha cambiado app.py?)")
                continue
            ruta = os.path.join(tmp, "app.py")
            with open(ruta, "w", encoding="utf-8", newline="") as f:
                f.write(texto)
        r = subprocess.run([sys.executable, GUARDIA, "--app", ruta], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        bien = r.returncode == esperado
        motivo = next((x.strip() for x in r.stdout.splitlines() if x.startswith("  - ")), "")
        print(f"  {'bien' if bien else 'MAL '}  {nombre}: salida {r.returncode} (esperada {esperado}) {motivo}"[:220],
              flush=True)
        if not bien:
            mal.append(nombre)
            print("      " + (r.stdout + r.stderr).strip().replace("\n", "\n      ")[-1500:], flush=True)
    if mal:
        print(f"FALLOS: {len(mal)}: " + "; ".join(mal))
        return 1
    print(f"TODO BIEN: {len(CASOS)} casos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
