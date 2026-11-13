# encoding: utf-8
"""Comprobación general de fechas futuras (12-11-2026): contratos con una fecha posterior a hoy.

Un contrato menor de Vitoria-Gasteiz (BROKER KIROL, S.L.) salía con fecha 16-12-2026. Viene así de la propia fuente
(API de contratación de Euskadi: awardDate y companySignatureDate 2026-12-16). La web NO corrige ni inventa fechas:
muestra la de la fuente con el aviso «Fecha según la fuente, posible error» y no la usa como «última fecha» en el
Índice (ver _fecha_posterior_a_hoy en app.py). Este script lista todos los casos para revisarlos a mano.

    python backend/comprobar_fechas_futuras.py [ruta/a/cache.db] [--detalle]

Abre la base SOLO EN LECTURA. Revisa:
  - contratos menores (contratos_menors_locales.data_adjudicacio), por fuente;
  - contratos formales (campo "fecha" de cada contrato dentro de municipios.data), por fuente.
Sale con código 0 siempre: es un informe, no un freno (las fechas son de la fuente y se muestran con aviso).
"""
import collections
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone

BASE = os.path.dirname(os.path.abspath(__file__))


def hoy_peninsular():
    """Hoy en hora peninsular, sin tzdata (mismo criterio que _ahora_madrid de app.py)."""
    ahora = datetime.now(timezone.utc)

    def ultimo_domingo(mes):
        d = datetime(ahora.year, mes, 31, 1, tzinfo=timezone.utc)
        return d - timedelta(days=(d.weekday() + 1) % 7)
    verano = ultimo_domingo(3) <= ahora < ultimo_domingo(10)
    return (ahora + timedelta(hours=2 if verano else 1)).date()


def es_futura(fecha, hoy):
    t = str(fecha or "").strip()[:10]
    try:
        return date(int(t[:4]), int(t[5:7]), int(t[8:10])) > hoy
    except (ValueError, IndexError):
        return False


CAMPOS = ("tipo", "fuente", "municipio", "organo", "empresa", "fecha", "importe", "enlace", "id")


def comprobar(ruta_db, hoy=None):
    """{"menores": [fila], "formales": [fila]} con las fechas posteriores a hoy; cada fila es un dict con CAMPOS.
    Los contratos menores no guardan enlace en la base (enlace = "")."""
    hoy = hoy or hoy_peninsular()
    con = sqlite3.connect(f"file:{ruta_db}?mode=ro", uri=True)
    out = {"menores": [], "formales": []}
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(contratos_menors_locales)")}
        organo = "organisme" if "organisme" in cols else "''"
        importe = "import_num" if "import_num" in cols else "NULL"
        for f in con.execute(f"SELECT fuente, municipio, {organo}, adjudicatari, data_adjudicacio, {importe}, id "
                             "FROM contratos_menors_locales WHERE data_adjudicacio > ? ORDER BY data_adjudicacio",
                             (hoy.isoformat() + "9",)):
            if es_futura(f[4], hoy):
                out["menores"].append(dict(zip(CAMPOS, ("menor", f[0] or "", f[1] or "", f[2] or "", f[3] or "",
                                                        f[4], f[5], "", f[6]))))
    except sqlite3.OperationalError:
        pass
    try:
        for (data,) in con.execute("SELECT data FROM municipios"):
            try:
                d = json.loads(data)
            except ValueError:
                continue
            for c in d.get("contratos") or []:
                if es_futura(c.get("fecha"), hoy):
                    out["formales"].append(dict(zip(CAMPOS, (
                        "formal", c.get("fuente", ""), d.get("municipio", ""), c.get("organo", ""),
                        c.get("empresa", ""), c.get("fecha", ""), c.get("importe_num"), c.get("url", ""),
                        c.get("licitacion_id", "")))))
    except sqlite3.OperationalError:
        pass
    con.close()
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    ruta = args[0] if args else os.path.join(os.environ.get("DATA_DIR") or BASE, "cache.db")
    if not os.path.exists(ruta):
        print(f"No existe {ruta}")
        return 1
    hoy = hoy_peninsular()
    res = comprobar(ruta, hoy)
    print(f"Fechas posteriores a hoy ({hoy.isoformat()}) en {ruta}")
    for tipo, filas in res.items():
        por_fuente = collections.Counter(f["fuente"] for f in filas)
        print(f"\n{tipo}: {len(filas)}")
        for fuente, n in por_fuente.most_common():
            fechas = [f["fecha"] for f in filas if f["fuente"] == fuente]
            print(f"  {fuente or '(sin fuente)'}: {n} (de {min(fechas)} a {max(fechas)})")
        if "--detalle" in sys.argv:
            print("    " + " | ".join(CAMPOS))
            for f in sorted(filas, key=lambda x: str(x["fecha"]), reverse=True):
                print("    " + " | ".join("" if f[k] is None else str(f[k]) for k in CAMPOS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
