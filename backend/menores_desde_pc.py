# encoding: utf-8
"""Contratos menores de las fuentes que no dejan entrar a GitHub, lanzadas desde el PC de César (09-11-2026).

Hace lo mismo que el flujo semanal (menores-fuentes-semanal.yml) salvo guardar en main:
  1. ejecuta los generadores con la misma salvaguarda (flujo_menores_semanal.py --solo ...): si fallan las descargas
     o traen menos del 90 %, se conserva el fichero anterior;
  2. tapa los DNI/NIE de los ficheros que hayan cambiado (enmascarar_nif.py --texto --aplicar) y lo comprueba;
  3. dice qué ha cambiado y la orden para guardarlo. NO hace commit ni push: eso lo decide César (guardar en main
     reinicia la web; mejor fuera del refresco nocturno, ~05:00-12:30 UTC).

Uso, desde la carpeta del repositorio (una línea, vale en PowerShell y en cmd):
    python backend/menores_desde_pc.py                    # las de por defecto: alicante y santa_cruz
    python backend/menores_desde_pc.py alicante burgos    # las que se digan (nombre del generador)
"""
import os
import subprocess
import sys
import tempfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(BASE_DIR)
POR_DEFECTO = ["alicante", "santa_cruz"]
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main(argv):
    fuentes = [a.strip(",") for a in argv if a.strip(",")] or POR_DEFECTO
    entorno = dict(os.environ, PYTHONIOENCODING="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        salida_gh = os.path.join(tmp, "salida.txt")
        entorno["GITHUB_OUTPUT"] = salida_gh
        entorno.pop("GITHUB_STEP_SUMMARY", None)
        p = subprocess.run([sys.executable, os.path.join(BASE_DIR, "flujo_menores_semanal.py"), "--solo",
                            ",".join(fuentes)], cwd=RAIZ, env=entorno)
        if p.returncode != 0:
            print("\nEl flujo terminó con error: no se ha tocado nada más.")
            return 1
        datos = dict(l.split("=", 1) for l in open(salida_gh, encoding="utf-8").read().splitlines() if "=" in l)
    cambio = [f.strip() for f in datos.get("fuentes_cambio", "").split(",") if f.strip()]
    if not cambio:
        print("\nNinguna fuente ha cambiado: no hay nada que guardar.")
        return 0
    ficheros = [f"backend/contratos_menores_{f}.json.gz" for f in cambio]
    enm = [sys.executable, os.path.join(BASE_DIR, "enmascarar_nif.py"), "--texto"]
    subprocess.run(enm + ["--aplicar"] + ficheros, cwd=RAIZ, env=entorno, check=True)
    if subprocess.run(enm + ["--comprobar"] + ficheros, cwd=RAIZ, env=entorno).returncode != 0:
        print("\n¡OJO! Queda algún DNI/NIE completo: NO guardes estos ficheros.")
        return 1
    print("\nHan cambiado: " + ", ".join(cambio) + ". DNI/NIE tapados y comprobados.")
    print("Para guardarlos en main (reinicia la web; fuera del refresco nocturno):")
    print(f'  git add {" ".join(ficheros)}')
    print(f'  git commit -m "Contratos menores desde el PC ({", ".join(cambio)})"')
    print("  git push")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
