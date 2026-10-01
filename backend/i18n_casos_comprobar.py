# encoding: utf-8
"""
Comprueba que cada traducción de /casos (backend/casos_i18n/<idioma>/<slug>.html) tiene EXACTAMENTE las mismas cifras
que la pieza original en castellano tal como se publica: cada número del original (13.560, 2.291, 71,5, 2024...) debe
aparecer igual y las mismas veces en la traducción, y la traducción no puede traer números que no estén en el
original. Es el mismo control que hace app.py antes de servir una traducción (_comparar_cifras_caso): si no cuadra, la
web sirve el castellano.

Uso (desde la raíz del repo o desde backend/):  python backend/i18n_casos_comprobar.py
Sale con código 1 si alguna traducción no cuadra (para usarlo antes de cada commit que toque una pieza o su traducción).

Ojo: comprueba las CIFRAS, no la traducción. Una cifra bien copiada con un sufijo mal declinado en euskera ("2025ko"
en lugar de "2025eko") pasa el control.
"""
import io
import os
import sqlite3
import sys
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))


def main():
    tmp = tempfile.mkdtemp(prefix="casos_i18n_")
    sqlite3.connect(os.path.join(tmp, "cache.db")).close()      # base vacía: las piezas no dependen de los datos
    os.environ["DATA_DIR"] = tmp
    os.environ["HTTP_PROXY"] = os.environ["HTTPS_PROXY"] = "http://127.0.0.1:9"    # sin red
    sys.path.insert(0, BASE)
    os.chdir(BASE)
    sys.argv = [sys.argv[0]]
    salida = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stdout = sys.stderr = open(os.path.join(tmp, "log.txt"), "w", encoding="utf-8")   # app.py habla mucho al importar
    import app as A

    errores = total = 0
    for lang in sorted(os.listdir(A.CASOS_I18N_DIR)):
        carpeta = os.path.join(A.CASOS_I18N_DIR, lang)
        if not os.path.isdir(carpeta):
            continue
        for nombre in sorted(os.listdir(carpeta)):
            if not nombre.endswith(".html"):
                continue
            total += 1
            slug = nombre[:-5]
            ok, faltan, sobran = A._comparar_cifras_caso(slug, lang)
            n = sum(A._cifras_texto(A._caso_es_fragmento(slug)[1]).values()) if ok else 0
            if ok:
                salida.write(f"OK     {lang}/{slug} ({n} cifras)\n")
            else:
                errores += 1
                salida.write(f"FALLO  {lang}/{slug}\n        faltan en la traducción: {dict(faltan)}\n"
                             f"        sobran en la traducción: {dict(sobran)}\n")
    salida.write(f"\n{total - errores} de {total} traducciones con las cifras idénticas al original.\n")
    salida.flush()
    os._exit(1 if errores else 0)


if __name__ == "__main__":
    main()
