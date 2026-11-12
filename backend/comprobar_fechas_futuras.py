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


def comprobar(ruta_db, hoy=None):
    """{"menores": [(fuente, municipio, fecha, id, adjudicatario)], "formales": [...]} con las fechas posteriores a hoy."""
    hoy = hoy or hoy_peninsular()
    con = sqlite3.connect(f"file:{ruta_db}?mode=ro", uri=True)
    out = {"menores": [], "formales": []}
    try:
        filas = con.execute("SELECT fuente, municipio, data_adjudicacio, id, adjudicatari FROM contratos_menors_locales "
                            "WHERE data_adjudicacio > ? ORDER BY data_adjudicacio",
                            (hoy.isoformat() + "9",)).fetchall()
        out["menores"] = [f for f in filas if es_futura(f[2], hoy)]
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
                    out["formales"].append((c.get("fuente", ""), d.get("municipio", ""), c.get("fecha", ""),
                                            c.get("licitacion_id", ""), c.get("empresa", "")))
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
        por_fuente = collections.Counter(f[0] for f in filas)
        print(f"\n{tipo}: {len(filas)}")
        for fuente, n in por_fuente.most_common():
            fechas = [f[2] for f in filas if f[0] == fuente]
            print(f"  {fuente or '(sin fuente)'}: {n} (de {min(fechas)} a {max(fechas)})")
        if "--detalle" in sys.argv:
            for f in filas:
                print("   ", " | ".join(str(x) for x in f))
    return 0


if __name__ == "__main__":
    sys.exit(main())
