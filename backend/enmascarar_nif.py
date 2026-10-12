# encoding: utf-8
"""Ningún fichero del repositorio puede llevar el DNI o el NIE completo de una persona física (decisión de César,
2026-10-11: el repositorio es público). Se enmascaran como hace la web al mostrarlos y como prevé la disposición
adicional 7.ª de la LOPDGDD (***4567** / ****4567*). Los NIF de sociedades y entidades se quedan como están.

La web ya sabe tratar un NIF enmascarado (app._persona_fisica_cm -> "nif_enmascarado"), igual que
administradores_borme.tipo_adjudicatario.

Uso:
    python backend/enmascarar_nif.py backend/contratos_menores_*.json.gz            # solo cuenta (no escribe)
    python backend/enmascarar_nif.py --aplicar backend/contratos_menores_*.json.gz  # reescribe los que lo necesiten
    python backend/enmascarar_nif.py --comprobar backend/*.json.gz                  # código 1 si queda alguno completo
    python backend/enmascarar_nif.py --texto [--aplicar] ...     # además, los DNI/NIE escritos DENTRO de otros textos

Con --texto se miran también los demás campos de texto (nombre del adjudicatario, descripción, título...): ahí solo
se enmascara lo que tiene forma de DNI/NIE Y su letra de control es la correcta, para no tocar números de
expediente. No se miran identificadores, códigos ni direcciones web.

Recorre el JSON entero y solo toca los valores de las claves cuyo nombre lleva "nif", "cif", "dni" o "nie". Nunca
imprime un NIF ni un nombre: solo recuentos."""
import glob
import gzip
import json
import re
import sys

_RE_DNI = re.compile(r"^\d{8}[A-Z]$")
_RE_NIE = re.compile(r"^[XYZ]\d{7}[A-Z]$")
_RE_CLAVE = re.compile(r"nif|cif|dni|\bnie\b", re.I)
_RE_CLAVE_NO_TEXTO = re.compile(r"^(id|url|enlace|link)$|_id$|^id_|codi|codigo|cpv|expediente|referencia|hash|sha", re.I)
_RE_EN_TEXTO = re.compile(r"(?<![0-9A-Za-z])(?:(\d{8})[- .]?([A-Za-z])|([XYZxyz])[- .]?(\d{7})[- .]?([A-Za-z]))(?![0-9A-Za-z])")
_LETRAS = "TRWAGMYFPDXBNJZSQVHLCKE"


def enmascarar_en_texto(v):
    """Enmascara los DNI/NIE que aparezcan dentro de un texto libre, solo si su letra de control es la correcta.
    Devuelve (texto, cuántos)."""
    n = [0]

    def cambia(m):
        if m.group(1):
            if _LETRAS[int(m.group(1)) % 23] != m.group(2).upper():
                return m.group(0)
            n[0] += 1
            return "***" + m.group(1)[3:7] + "**"
        if _LETRAS[int("XYZ".index(m.group(3).upper()) * 10000000 + int(m.group(4))) % 23] != m.group(5).upper():
            return m.group(0)
        n[0] += 1
        return "****" + m.group(4)[3:7] + "*"

    return _RE_EN_TEXTO.sub(cambia, v), n[0]


def enmascarar_nif(v):
    """El DNI/NIE completo de una persona física, enmascarado; cualquier otro valor, tal cual (también el NIF de una
    sociedad, un valor ya enmascarado o un texto vacío)."""
    if not isinstance(v, str) or not v:
        return v
    n = re.sub(r"[^A-Z0-9]", "", v.upper())
    if n.startswith("ES") and len(n) == 11:         # "ES12345678Z" (prefijo de país de PLACE)
        n = n[2:]
    if _RE_DNI.match(n):
        return "***" + n[3:7] + "**"
    if _RE_NIE.match(n):
        return "****" + n[4:8] + "*"
    return v


def enmascarar_estructura(o, texto=False):
    """Enmascara en el sitio los DNI/NIE de un JSON ya leído. Devuelve cuántos ha cambiado."""
    cambiados = 0
    pila = [o]
    while pila:
        x = pila.pop()
        if isinstance(x, dict):
            for k, v in x.items():
                if isinstance(v, str):
                    if _RE_CLAVE.search(k):
                        nuevo = enmascarar_nif(v)
                        if nuevo != v:
                            x[k] = nuevo
                            cambiados += 1
                    elif texto and not _RE_CLAVE_NO_TEXTO.search(k):
                        nuevo, n = enmascarar_en_texto(v)
                        if n:
                            x[k] = nuevo
                            cambiados += n
                elif isinstance(v, (dict, list)):
                    pila.append(v)
        elif isinstance(x, list):
            pila.extend(v for v in x if isinstance(v, (dict, list)))
    return cambiados


def main(argv):
    aplicar, comprobar = "--aplicar" in argv, "--comprobar" in argv
    rutas = sorted({r for a in argv if not a.startswith("--") for r in (glob.glob(a) or [a])})
    total, tocados = 0, 0
    for ruta in rutas:
        try:
            comprimido = ruta.endswith(".gz")
            with (gzip.open(ruta, "rt", encoding="utf-8") if comprimido else open(ruta, encoding="utf-8")) as f:
                datos = json.load(f)
        except (OSError, ValueError) as e:
            print(f"{ruta}: no se pudo leer ({type(e).__name__})")
            continue
        n = enmascarar_estructura(datos, texto="--texto" in argv)
        if n:
            total += n
            tocados += 1
            print(f"{ruta}: {n:,} DNI/NIE completos" + (" -> enmascarados" if aplicar else ""))
            if aplicar:
                # mismo formato que escriben los generadores: compacto y sin escapar los acentos
                with (gzip.open(ruta, "wt", encoding="utf-8", compresslevel=9) if comprimido
                      else open(ruta, "w", encoding="utf-8")) as f:
                    json.dump(datos, f, ensure_ascii=False, separators=(",", ":"))
        del datos
    print(f"{len(rutas)} ficheros revisados; {total:,} DNI/NIE completos en {tocados} ficheros"
          + (" (enmascarados)" if aplicar else ""))
    return 1 if (comprobar and total) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
