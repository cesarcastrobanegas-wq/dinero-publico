# encoding: utf-8
"""Genera backend/fondos_ue_place.json.gz: qué licitaciones de PLACE declaran financiación europea (2026-10-17, encargo
de César: «marca del Plan de Recuperación en los contratos de la PLACE»).

PLACE publica en cada licitación los programas que la financian (cac:TenderingTerms/cbc:FundingProgramCode, lista
FundingProgramCode-2.08): PRTR = Plan de Recuperación, Transformación y Resiliencia; FEDER, FSE+, FEADER, FEMP, REU
(REACT-UE), EU (fondos de la UE sin más detalle) y OFE (otros fondos europeos). NO-EU, NAC, AUT, LOC, CPTI y CPP no son
europeos y no se apuntan. El analizador de app.py no leía este campo; desde hoy lo guarda en lo nuevo
(_entry_to_contratos, campo `fondos_ue`) y lo ya guardado se marca con este fichero, que app.py aplica al arrancar
(_aplicar_fondos_ue_place), igual que fechas_formales_place.json.gz.

Qué hace: recorre los ZIP mensuales de PLACE (licitacionesPerfilesContratanteCompleto3_AAAAMM.zip) de más nuevo a más
viejo y, de cada licitación, se queda con los códigos de su versión MÁS RECIENTE (la primera que ve). Clave = idEvl de
la URL de PLACE. No necesita la base de producción ni importa app.py.

Formato: {"generado", "meses": [...], "fondos": {idEvl: "EU,PRTR"}}. Sin datos personales (identificadores de
licitación y códigos de financiación), así que puede ir al repositorio como el de fechas.

Uso:
    python generar_fondos_ue_place.py 202610 202109                          (Actions: descarga los ZIP de uno en uno)
    python generar_fondos_ue_place.py 202608 202607 --zip-local place_cache --salida prueba.json.gz   (en local)
"""
import argparse
import gzip
import json
import os
import re
import tempfile
import time
import zipfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "fondos_ue_place.json.gz")
CODIGOS_UE = ("PRTR", "FEDER", "FSE+", "FEADER", "FEMP", "REU", "EU", "OFE")
NO_UE = ("NO-EU", "NAC", "AUT", "LOC", "CPTI", "CPP")
RE_ENTRY = re.compile(rb"<entry>.*?</entry>", re.S)
RE_IDEVL_B = re.compile(rb"idEvl=([^&#\s\"<]+)")
RE_CODIGO_B = re.compile(rb"<(?:[\w-]+:)?FundingProgramCode\b[^>]*>\s*([^<\s]+)\s*<")


def escribir(ruta, datos):
    contenido = json.dumps(datos, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    tmp = ruta + ".tmp"
    with open(tmp, "wb") as crudo:
        with gzip.GzipFile(filename="", mode="wb", fileobj=crudo, compresslevel=9, mtime=0) as z:
            z.write(contenido)
    os.replace(tmp, ruta)


def meses_atras(desde, hasta):
    y, m = int(desde[:4]), int(desde[4:])
    while f"{y}{m:02d}" >= hasta:
        yield f"{y}{m:02d}"
        m -= 1
        if m == 0:
            y, m = y - 1, 12


def procesar_zip(ruta, vistos, fondos, otros):
    """Apunta en `fondos` los códigos europeos de las licitaciones de este ZIP que no se hayan visto ya en uno más
    nuevo. Devuelve (licitaciones nuevas leídas, con fondos UE)."""
    leidas = con_ue = 0
    with zipfile.ZipFile(ruta) as z:
        nombres = [n for n in z.namelist() if n.endswith(".atom")]
        principal = [n for n in nombres if not re.search(r"_\d{8}_\d{6}", n)]
        for nombre in principal + sorted((n for n in nombres if n not in principal), reverse=True):   # lo más nuevo primero
            raw = z.read(nombre)
            for m in RE_ENTRY.finditer(raw):
                e = m.group(0)
                mk = RE_IDEVL_B.search(e)
                if not mk:
                    continue
                k = mk.group(1).decode("ascii", "replace")
                if k in vistos:
                    continue
                vistos.add(k)
                leidas += 1
                codigos = []
                for c in RE_CODIGO_B.findall(e):
                    c = c.decode("ascii", "replace").strip().upper()
                    if c in CODIGOS_UE:
                        if c not in codigos:
                            codigos.append(c)
                    elif c not in NO_UE:
                        otros[c] = otros.get(c, 0) + 1
                if codigos:
                    fondos[k] = ",".join(sorted(codigos, key=CODIGOS_UE.index))
                    con_ue += 1
            del raw
    return leidas, con_ue


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("desde")
    ap.add_argument("hasta")
    ap.add_argument("--salida", default=FICHERO)
    ap.add_argument("--zip-local", default="", help="directorio con place_AAAAMM.zip o formales_AAAAMM.zip ya descargados")
    args = ap.parse_args()
    t_ini = time.time()
    datos = {"generado": "", "meses": [], "fondos": {}}
    fondos, vistos, otros = datos["fondos"], set(), {}
    tmp = tempfile.mkdtemp(prefix="fondos_place_")
    for mes in meses_atras(args.desde, args.hasta):
        ruta, propio = "", False
        for nombre in (f"place_{mes}.zip", f"formales_{mes}.zip"):
            cand = os.path.join(args.zip_local, nombre) if args.zip_local else ""
            if cand and os.path.exists(cand) and os.path.getsize(cand) > 1_000_000:
                ruta = cand
        t0 = time.time()
        if not ruta:
            if args.zip_local:
                print(f"{mes}: no está en {args.zip_local}; se salta", flush=True)
                continue
            import generar_backfill_nombres_place as G
            G.DESCARGA_PLAZO_S = 7200
            ruta, estado = G.descargar(mes, os.path.join(tmp, f"place_{mes}.zip"))
            propio = True
            if not ruta or not zipfile.is_zipfile(ruta):
                # el mes en curso puede no existir todavía; cualquier otro hueco se dice y se sigue
                print(f"{mes}: ZIP no disponible ({estado}); se salta", flush=True)
                continue
        t_desc = time.time() - t0
        t0 = time.time()
        mb = os.path.getsize(ruta) / 1048576
        leidas, con_ue = procesar_zip(ruta, vistos, fondos, otros)
        if propio:
            os.remove(ruta)
        datos["meses"] = sorted(set(datos["meses"]) | {mes})
        datos["generado"] = time.strftime("%Y-%m-%d")
        escribir(args.salida, datos)
        print(f"{mes}: ZIP de {mb:.0f} MB, descarga {t_desc:.0f} s, lectura {time.time() - t0:.0f} s | "
              f"{leidas:,} licitaciones nuevas, {con_ue:,} con fondos UE | acumulado {len(fondos):,} de {len(vistos):,}",
              flush=True)
    por_codigo = {}
    for v in fondos.values():
        for c in v.split(","):
            por_codigo[c] = por_codigo.get(c, 0) + 1
    print(f"FIN: {len(fondos):,} licitaciones con fondos UE de {len(vistos):,} leídas; por código {por_codigo}; "
          f"códigos desconocidos {otros}; meses {len(datos['meses'])}; fichero "
          f"{os.path.getsize(args.salida) / 1048576 if os.path.exists(args.salida) else 0:.1f} MB; "
          f"{time.time() - t_ini:.0f} s", flush=True)
    if len(datos["meses"]) < 0.9 * len(list(meses_atras(args.desde, args.hasta))) and not args.zip_local:
        raise SystemExit("ERROR: faltan más del 10 % de los meses; el fichero no debe usarse")


if __name__ == "__main__":
    main()
