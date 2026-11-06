# encoding: utf-8
"""
Lista de exclusión de cargos públicos: personas concretas que dejan de mostrarse en los datos de alcaldes/concejales
(alcaldes_concejales.json, concejales.redsara.es) y de sueldos de concejales (sueldos_concejales.json).

El fichero cargos_suprimidos.json NO guarda nombres, fechas ni referencias: cada entrada es una huella
HMAC-SHA256 de municipio + provincia + nombre normalizados, con una clave secreta que se lee de la variable de
entorno EXCLUSION_CLAVE (en Render y en el PC de quien lance las órdenes; nunca en el repositorio). Sin la clave no
se puede saber a quién corresponde una huella probando con los nombres del JSON público.
Sin EXCLUSION_CLAVE la web arranca igual, avisa en el registro y NO puede aplicar la lista (las personas excluidas
volverían a salir): la variable tiene que estar puesta antes de desplegar. Si se cambia la clave, hay que volver a
calcular todas las huellas (orden "excluir" con la clave nueva y borrar las entradas viejas).

Dos modos:
  - "quitar": la persona desaparece del listado (el recuento de concejales baja en uno). Recomendado.
  - "ocultar_nombre": se queda la fila con cargo y partido, sin nombre ("Nombre no mostrado"). En un pleno pequeño
    cargo + partido pueden bastar para identificar a alguien: no es una anonimización completa.
En los sueldos de concejales los dos modos quitan el registro (un importe con cargo y sin nombre sigue señalando
a la persona, y el cargador de la web exige nombre).

Se aplica en dos sitios, con la misma función: al cargar los datos en la web (app.py) y al regenerarlos
(actualizar_alcaldes.py), para que el nombre tampoco vuelva al JSON del repositorio en la próxima descarga.

Uso (sin importar app.py: no arranca nada ni sale a la red; con EXCLUSION_CLAVE puesta):
  python backend/cargos_suprimidos.py excluir --municipio Villaprueba --provincia valencia \\
         --nombre "Nombre Apellido1 Apellido2" --modo quitar
      añade la huella y quita a la persona de alcaldes_concejales.json y sueldos_concejales.json en disco
      (las referencias internas de cada caso se guardan fuera del repositorio)
  python backend/cargos_suprimidos.py comprobar
      dice, para cada entrada, si el nombre ha vuelto a los JSON (p. ej. tras regenerarlos con otra herramienta).
      OJO: la huella exige el mismo nombre; si la fuente lo cambia (otro apellido, una errata corregida) la entrada
      deja de casar y la persona volvería a salir: tras cada regeneración, mirar la ficha a ojo.
"""
import argparse
import hashlib
import hmac
import json
import os
import re
import sys
import unicodedata

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SUPRESIONES_FILE = os.path.join(BASE_DIR, "cargos_suprimidos.json")
ALCALDES_FILE = os.path.join(BASE_DIR, "alcaldes_concejales.json")
SUELDOS_FILE = os.path.join(BASE_DIR, "sueldos_concejales.json")
MODOS = ("quitar", "ocultar_nombre")


def _norm(s):
    """Minúsculas, sin tildes ni diéresis, espacios simples. Propia (no la normalizar() de app.py) para que la huella
    no cambie si un día cambia aquella."""
    s = unicodedata.normalize("NFKD", str(s or "")).lower()
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip()


CLAVE_ENV = "EXCLUSION_CLAVE"
_avisado_sin_clave = False


class SinClave(RuntimeError):
    pass


def _clave():
    """La clave del HMAC, o None. Se lee en cada llamada (las pruebas la cambian)."""
    c = os.environ.get(CLAVE_ENV, "").strip()
    return c.encode("utf-8") if c else None


def _avisar_sin_clave(n):
    global _avisado_sin_clave
    if not _avisado_sin_clave:
        _avisado_sin_clave = True
        print(f"[exclusion] AVISO: falta la variable {CLAVE_ENV}: no se aplican las {n} entradas de la lista de "
              "exclusión de cargos (esas personas se muestran)", file=sys.stderr, flush=True)


def huella(municipio, provincia, nombre, clave=None):
    """HMAC-SHA256 (hex) de municipio|provincia|nombre normalizados. Lanza SinClave si no hay clave."""
    clave = clave or _clave()
    if not clave:
        raise SinClave(f"falta la variable de entorno {CLAVE_ENV}")
    texto = "dp-exclusion-v2|" + "|".join(_norm(x) for x in (municipio, provincia, nombre))
    return hmac.new(clave, texto.encode("utf-8"), hashlib.sha256).hexdigest()


def cargar(ruta=None):
    """{huella: modo}. Fichero ausente o ilegible = sin supresiones (no rompe el arranque de la web).
    CARGOS_SUPRIMIDOS_FILE (variable de entorno) cambia el fichero: solo para las pruebas."""
    ruta = ruta or os.environ.get("CARGOS_SUPRIMIDOS_FILE") or SUPRESIONES_FILE
    try:
        with open(ruta, encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        # con el fichero roto las personas suprimidas volverían a salir: que se vea en el registro de Render
        print(f"[exclusion] ERROR: no se pudo leer {ruta} ({type(e).__name__}: {e})", file=sys.stderr, flush=True)
        return {}
    out = {}
    for e in d.get("entradas", []) if isinstance(d, dict) else []:
        if isinstance(e, dict) and isinstance(e.get("huella"), str) and e.get("modo") in MODOS:
            out[e["huella"]] = e["modo"]
    return out


def aplicar_alcaldes(municipios, supresiones):
    """Aplica EN SU SITIO las supresiones a {clave: {municipio, provincia, alcalde, concejales}}. Devuelve el conjunto
    de huellas que han casado con alguien."""
    usadas = set()
    if not supresiones:
        return usadas
    clave = _clave()
    if not clave:
        _avisar_sin_clave(len(supresiones))
        return usadas
    for info in municipios.values():
        if not isinstance(info, dict):
            continue
        muni, prov = info.get("municipio", ""), info.get("provincia", "")
        alc = info.get("alcalde")
        if isinstance(alc, dict) and alc.get("nombre"):
            h = huella(muni, prov, alc["nombre"], clave)
            if h in supresiones:
                usadas.add(h)
                info["alcalde"] = None if supresiones[h] == "quitar" else {
                    "nombre": "", "partido": alc.get("partido", ""), "suprimido": True}
        nuevos = []
        for c in info.get("concejales") or []:
            h = huella(muni, prov, c.get("nombre", ""), clave) if isinstance(c, dict) and c.get("nombre") else None
            if h in supresiones:
                usadas.add(h)
                if supresiones[h] == "quitar":
                    continue
                c = {"nombre": "", "cargo": c.get("cargo", ""), "partido": c.get("partido", ""), "suprimido": True}
            nuevos.append(c)
        if "concejales" in info:
            info["concejales"] = nuevos
    return usadas


def aplicar_sueldos(registros, supresiones):
    """Lista de registros de sueldos de concejales sin las personas suprimidas (cualquier modo), y huellas usadas."""
    usadas, out = set(), []
    clave = _clave() if supresiones else None
    if supresiones and not clave:
        _avisar_sin_clave(len(supresiones))
        return list(registros), usadas
    if not supresiones:
        return list(registros), usadas
    for r in registros:
        h = (huella(r.get("municipio", ""), r.get("provincia", ""), r.get("nombre", ""), clave)
             if isinstance(r, dict) else None)
        if h in supresiones:
            usadas.add(h)
            continue
        out.append(r)
    return out, usadas


def _leer(ruta):
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def _escribir(ruta, datos):
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, ruta)


def _aplicar_en_disco(supresiones, alcaldes_file=ALCALDES_FILE, sueldos_file=SUELDOS_FILE):
    usadas = set()
    if os.path.exists(alcaldes_file):
        d = _leer(alcaldes_file)
        u = aplicar_alcaldes(d.get("municipios", {}), supresiones)
        if u:
            _escribir(alcaldes_file, d)
        usadas |= u
    if os.path.exists(sueldos_file):
        d = _leer(sueldos_file)
        d["registros"], u = aplicar_sueldos(d.get("registros", []), supresiones)
        if u:
            _escribir(sueldos_file, d)
        usadas |= u
    return usadas


def excluir(municipio, provincia, nombre, modo, ruta=SUPRESIONES_FILE,
            alcaldes_file=ALCALDES_FILE, sueldos_file=SUELDOS_FILE):
    """Añade (o actualiza el modo de) una entrada y la aplica a los JSON en disco. Devuelve la huella y las usadas.
    Solo huella y modo: ni fecha ni referencia (irían al repositorio público)."""
    if modo not in MODOS:
        raise ValueError(f"modo desconocido: {modo}")
    h = huella(municipio, provincia, nombre)
    try:
        d = _leer(ruta)
    except OSError:
        d = {"entradas": []}
    entradas = [e for e in d.get("entradas", []) if e.get("huella") != h]
    entradas.append({"huella": h, "modo": modo})
    d["entradas"] = entradas
    _escribir(ruta, d)
    return h, _aplicar_en_disco({h: modo}, alcaldes_file, sueldos_file)


def _huellas_presentes(alcaldes_file=ALCALDES_FILE, sueldos_file=SUELDOS_FILE):
    clave = _clave()
    if not clave:
        raise SinClave(f"falta la variable de entorno {CLAVE_ENV}")
    presentes = set()
    if os.path.exists(alcaldes_file):
        for info in _leer(alcaldes_file).get("municipios", {}).values():
            personas = [info.get("alcalde") or {}] + list(info.get("concejales") or [])
            presentes |= {huella(info.get("municipio", ""), info.get("provincia", ""), p["nombre"], clave)
                          for p in personas if p.get("nombre")}
    if os.path.exists(sueldos_file):
        presentes |= {huella(r.get("municipio", ""), r.get("provincia", ""), r.get("nombre", ""), clave)
                      for r in _leer(sueldos_file).get("registros", [])}
    return presentes


def main(argv=None):
    p = argparse.ArgumentParser(description="Lista de exclusión de cargos públicos (sin guardar nombres)")
    sub = p.add_subparsers(dest="orden", required=True)
    s = sub.add_parser("excluir")
    s.add_argument("--municipio", required=True)
    s.add_argument("--provincia", required=True, help="clave interna de la app: valencia, murcia, pais_vasco...")
    s.add_argument("--nombre", required=True, help="tal como figura en la web")
    s.add_argument("--modo", choices=MODOS, default="quitar")
    sub.add_parser("comprobar")
    a = p.parse_args(argv)
    if not _clave():
        print(f"ERROR: falta la variable de entorno {CLAVE_ENV} (la misma clave que en Render).", file=sys.stderr)
        return 2
    if a.orden == "excluir":
        h, usadas = excluir(a.municipio, a.provincia, a.nombre, a.modo)
        print(f"Entrada guardada ({a.modo}), huella {h[:12]}...")
        print("Aplicada en alcaldes_concejales.json / sueldos_concejales.json." if usadas else
              "AVISO: no casa con nadie en los JSON (revisa municipio, provincia y nombre tal como salen en la web).")
        return 0
    entradas = cargar()
    usadas = set(entradas) & _huellas_presentes()
    print(f"{len(entradas)} entradas en la lista de exclusión.")
    for h, modo in entradas.items():
        estado = ("VUELVE A ESTAR en los JSON (la web lo oculta al cargar; lanza excluir otra vez para limpiarlo)"
                  if h in usadas else "no está en los JSON con esta clave")
        print(f"  {h[:12]}... {modo}: {estado}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
