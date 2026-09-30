# encoding: utf-8
"""
Extrae los textos de interfaz marcados con _t("...") en app.py y crea o actualiza los catálogos de traducción
backend/locale/<idioma>.po (gallego, catalán, euskera). Ver el bloque "INTERFAZ MULTIIDIOMA" de app.py.

Uso:  python backend/i18n_extraer.py          (sin dependencias: solo la biblioteca estándar)

- Conserva las traducciones ya hechas; los textos nuevos entran con msgstr vacío (el sitio muestra el castellano
  hasta que se traduzcan) y los que ya no existen en el código pasan al final como obsoletos (#~), por si se
  reaprovechan.
- Solo cuenta los LITERALES: _t("Hola") sí, _t(variable) no (el script avisa).
- El formato es gettext estándar: se puede traducir con Poedit, Weblate, Lokalize o a mano.
"""
import ast
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
FUENTES = ["app.py"]
IDIOMAS = {"gl": "Galician", "ca": "Catalan", "eu": "Basque"}
LOCALE = os.path.join(BASE, "locale")
RE_JS = re.compile(r'\bTF?\("([^"\\]*)"')


def _extraer():
    textos, avisos = {}, []   # {msgid: [ "app.py:123", ...]} en orden de aparición
    for fuente in FUENTES:
        ruta = os.path.join(BASE, fuente)
        arbol = ast.parse(open(ruta, encoding="utf-8").read(), filename=fuente)
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name) and nodo.func.id in ("_t", "_td"):
                arg = nodo.args[0] if nodo.args else None
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    textos.setdefault(arg.value, []).append(f"{fuente}:{nodo.lineno}")
                elif not (isinstance(arg, ast.Attribute) and arg.attr == "plantilla"):   # _t_diferido: ya extraído
                    avisos.append(f"{fuente}:{nodo.lineno}: _t() sin literal, no se puede extraer")
        # Textos del JavaScript incrustado: T("...") y TF("...", {...}) (siempre con comillas dobles; ver
        # _i18n_js_head en app.py, que usa esta misma expresión para saber qué textos enviar al navegador).
        for n_linea, linea in enumerate(open(ruta, encoding="utf-8"), 1):
            for m in RE_JS.finditer(linea):
                textos.setdefault(m.group(1), []).append(f"{fuente}:{n_linea}")
    orden = sorted(textos, key=lambda t: (textos[t][0].split(":")[0], int(textos[t][0].split(":")[1])))
    return [(t, textos[t]) for t in orden], avisos


def _esc(s):
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")


def _leer_po(ruta):
    """{msgid: (msgstr, fuzzy)} -- mismo formato simple que escribe este script."""
    sys.path.insert(0, BASE)
    catalogo, entrada, campo, fuzzy = {}, {}, None, False

    def unesc(s):
        return (s.replace("\\\\", "\x00").replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')
                .replace("\x00", "\\"))

    if not os.path.exists(ruta):
        return {}
    for linea in open(ruta, encoding="utf-8").read().splitlines() + [""]:
        linea = linea.strip()
        if linea.startswith("#~"):
            linea = linea[2:].strip()
        if not linea:
            if entrada.get("msgid"):
                catalogo[entrada["msgid"]] = (entrada.get("msgstr", ""), fuzzy)
            entrada, campo, fuzzy = {}, None, False
        elif linea.startswith("#,"):
            fuzzy = fuzzy or "fuzzy" in linea
        elif linea.startswith("#"):
            continue
        elif linea.startswith(("msgid ", "msgstr ")):
            campo, _, resto = linea.partition(" ")
            entrada[campo] = unesc(resto.strip()[1:-1])
        elif linea.startswith('"') and campo:
            entrada[campo] = entrada.get(campo, "") + unesc(linea[1:-1])
    return catalogo


def _escribir_po(ruta, lang, textos, previo):
    lineas = [
        f"# Dinero Público — interfaz en {IDIOMAS[lang]} ({lang}).",
        "# Generado por backend/i18n_extraer.py; se puede editar a mano o con Poedit. Solo la interfaz: el",
        "# contenido editorial y los datos siguen en castellano.",
        'msgid ""',
        'msgstr ""',
        '"Content-Type: text/plain; charset=UTF-8\\n"',
        f'"Language: {lang}\\n"',
        "",
    ]
    hechos = 0
    for msgid, refs in textos:
        msgstr, fuzzy = previo.get(msgid, ("", False))
        hechos += bool(msgstr) and not fuzzy
        lineas.append("#: " + " ".join(refs[:5]))
        if fuzzy:
            lineas.append("#, fuzzy")
        lineas += [f'msgid "{_esc(msgid)}"', f'msgstr "{_esc(msgstr)}"', ""]
    actuales = {m for m, _ in textos}
    obsoletos = [(m, v) for m, v in previo.items() if m not in actuales and v[0]]
    for msgid, (msgstr, _) in obsoletos:
        lineas += [f'#~ msgid "{_esc(msgid)}"', f'#~ msgstr "{_esc(msgstr)}"', ""]
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lineas))
    return hechos, len(obsoletos)


def main():
    textos, avisos = _extraer()
    for a in avisos:
        print("AVISO", a)
    print(f"{len(textos)} textos de interfaz marcados con _t()")
    for lang in IDIOMAS:
        ruta = os.path.join(LOCALE, f"{lang}.po")
        hechos, obsoletos = _escribir_po(ruta, lang, textos, _leer_po(ruta))
        print(f"  {lang}.po: {hechos}/{len(textos)} traducidos"
              + (f", {obsoletos} obsoletos al final" if obsoletos else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
