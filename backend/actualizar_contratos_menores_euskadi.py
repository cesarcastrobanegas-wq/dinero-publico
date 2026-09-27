# encoding: utf-8
"""
Descarga contratos MENORES (minor-contract=true) de la API REST pública de Euskadi (api.euskadi.eus/procurements)
para TODOS los municipios vascos ya mapeados en MUNICIPIOS_PAIS_VASCO_EUSKADI_ID (251 municipios -- cubre el 100 %
de los municipios de País Vasco que ya tenemos conectados para contratos formales, ver buscar_en_euskadi en app.py).

Es el MISMO mecanismo/API que los contratos formales (Mecanismo B, sin ambigüedad de nombre: identificador numérico
propio de cada ayuntamiento), con el parámetro `minor-contract=true` en vez de `false` -- ver
_piloto_medir_pais_vasco en app.py, que ya probó ese parámetro en 2026-09-03 pero solo para una medición piloto de
formales, nunca se explotó para menores hasta ahora (2026-09-27).

Cadencia manual/periódica -- mismo patrón que actualizar_contratos_menores_murcia_manual.py: genera
contratos_menores_euskadi.json.gz, que app.py carga al arrancar y vuelca a la tabla compartida
contratos_menors_locales (ver _cargar_contratos_menores_euskadi en app.py). No hay nada que "cronear" a diario --
la API se puede volver a barrer entera cuando se quiera ampliar/refrescar.

Alcance de 5 años: se descartan aquí mismo (antes de escribir el fichero) los contratos con `awardDate` anterior a
MENORES_DESDE_FECHA -- igual que hace _guardar_contratos_menors_locales en el arranque, pero conviene no escribir
en el fichero del repo filas que de todas formas se van a descartar.

Uso (desde backend/):
    python actualizar_contratos_menores_euskadi.py                 # todos los municipios
    python actualizar_contratos_menores_euskadi.py Amurrio Getxo    # solo estos (pruebas rápidas)

Es INCREMENTAL respecto al fichero de salida si ya existe (se puede repetir sin miedo; un registro con el mismo id
se sustituye por la versión más reciente del scrapeo)."""
import gzip
import json
import os
import sys
import tempfile
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FICHERO = os.path.join(BASE_DIR, "contratos_menores_euskadi.json.gz")
_ARGV_PEDIDOS = sys.argv[1:]   # capturado ANTES de que `import app` reasigne sys.argv = ["x"] más abajo

# `import app` arranca en segundo plano el enriquecimiento de directivos sobre el cache.db de DATA_DIR y siembra
# desde el cache.db real si no hay marcadores -- se apunta DATA_DIR a un directorio temporal vacío CON los
# marcadores ya puestos para no tocar nada real ni hacer peticiones de más (mismo patrón que
# generar_backfill_galicia_place.py / los tests de esta noche).
_tmp = tempfile.mkdtemp(prefix="euskadi_menores_")
import sqlite3
sqlite3.connect(os.path.join(_tmp, "cache.db")).close()
open(os.path.join(_tmp, ".disco_inicializado"), "w").write("x")
open(os.path.join(_tmp, "recuperacion_historico_20260722.marker"), "w").write("x")
os.environ["DATA_DIR"] = _tmp
sys.path.insert(0, BASE_DIR)
sys.argv = ["x"]
import app as A  # noqa: E402


def _importe_euskadi(item):
    """Mismo saneado de IVA que _euskadi_item_a_contrato en app.py (incidente Prismaglobal/Vitoria-Gasteiz,
    2026-09-17): si awardAmount supera en más de un 25 % a awardAmountWithoutVAT, el dato de origen está corrupto
    y se prefiere el importe sin IVA."""
    con_iva = item.get("awardAmount") or 0.0
    sin_iva = item.get("awardAmountWithoutVAT") or 0.0
    if sin_iva > 0 and con_iva > sin_iva * 1.25:
        return float(sin_iva)
    return float(con_iva) if con_iva else float(sin_iva)


def _item_a_registro(item, municipio):
    fecha = (item.get("awardDate") or "")[:10]
    return {
        "id":               f"{municipio}::EUSKADI::{item.get('id', '')}",
        "municipio":         municipio,
        "provincia":         "pais_vasco",
        "fuente":            "euskadi",
        "organisme":         f"Ayuntamiento de {municipio}",
        "adjudicatari":      (item.get("socialReason") or "").strip() or "No localizada",
        "nif":               item.get("CIF") or "",
        "import_num":        round(_importe_euskadi(item), 2),
        "data_adjudicacio":  fecha,
        "tipus_contracte":   (item.get("contractType") or {}).get("name", ""),
        "descripcio":        (item.get("object") or "").strip(),
        "codi_cpv":          item.get("CPV", "") or "",
        "exercici":          fecha[:4] if fecha else "",
    }


LIM_PAGINAS_MUNICIPIO = 700     # 700*50 = 35.000 contratos por municipio -- Eibar (el más grande medido, 24.126
                                 # contratos/483 páginas) queda cubierto entero con margen; tope de seguridad, no
                                 # un límite normal (evita un bucle infinito si totalPages viniera mal calculado).
LIM_SEGUNDOS_MUNICIPIO = 900     # 15 min máx. por municipio -- si una ciudad tarda más que esto (servidor lento,
                                 # no volumen) se corta y se sigue con el resto; se avisa en el log para revisarla
                                 # a mano después (relanzar solo esa: `python actualizar_contratos_menores_euskadi.py <Municipio>`).


def buscar_menores_municipio(municipio, authority_id):
    """Trae TODOS los contratos menores (minor-contract=true) de un ayuntamiento, paginando (50/página, el
    máximo documentado -- ver buscar_en_euskadi). Descarta aquí mismo lo anterior al alcance de 5 años."""
    registros = []
    descartados = 0
    pagina = 1
    t0_municipio = time.time()
    while True:
        if time.time() - t0_municipio > LIM_SEGUNDOS_MUNICIPIO:
            print(f"  !! {municipio}: cortado por tiempo ({LIM_SEGUNDOS_MUNICIPIO} s) en la página {pagina}, "
                  "relanzar este municipio solo más tarde", flush=True)
            break
        try:
            r = A.session.get(
                f"{A.EUSKADI_API_BASE}/contracts",
                params={
                    "contracting-authority-id": authority_id,
                    "minor-contract": "true",
                    "itemsOfPage": 50,
                    "currentPage": pagina,
                    "lang": "SPANISH",
                },
                timeout=20,
            )
            if r.status_code != 200:
                print(f"  !! {municipio}: HTTP {r.status_code} en página {pagina}", flush=True)
                break
            d = r.json()
        except Exception as e:
            print(f"  !! {municipio}: error de red ({type(e).__name__}: {e})", flush=True)
            break
        for item in d.get("items", []):
            fecha = (item.get("awardDate") or "")[:10]
            if fecha and fecha < A.MENORES_DESDE_FECHA:
                descartados += 1
                continue
            registros.append(_item_a_registro(item, municipio))
        total_paginas = d.get("totalPages", 1)
        if pagina >= total_paginas or pagina >= LIM_PAGINAS_MUNICIPIO:
            break
        pagina += 1
        time.sleep(0.2)   # mismo ritmo respetuoso que buscar_en_euskadi/_piloto_medir_pais_vasco
    return registros, descartados


def _leer_existente():
    if not os.path.exists(FICHERO):
        return {}
    with gzip.open(FICHERO, "rt", encoding="utf-8") as f:
        d = json.load(f)
    return {r["id"]: r for r in d.get("registros", [])}


def _guardar(existentes):
    """Escritura atómica del fichero completo -- se llama tanto al final como periódicamente durante el barrido
    (ver main): un barrido de 251 municipios con ciudades grandes puede tardar bastante, y sin guardado
    intermedio perder el proceso a mitad significaría perder TODO el progreso, no solo lo último."""
    tmp = f"{FICHERO}.tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump({
            "generado": time.strftime("%Y-%m-%d"),
            "descripcion": ("Contratos menores (minor-contract=true) de la API REST de Euskadi (api.euskadi.eus/"
                            "procurements), municipios de MUNICIPIOS_PAIS_VASCO_EUSKADI_ID. fecha = awardDate real "
                            "de la API. Ver actualizar_contratos_menores_euskadi.py y _cargar_contratos_menores_"
                            "euskadi en app.py."),
            "registros": list(existentes.values()),
        }, f, ensure_ascii=False)
    os.replace(tmp, FICHERO)


def main():
    pedidos = _ARGV_PEDIDOS or sorted(A.MUNICIPIOS_PAIS_VASCO_EUSKADI_ID)
    desconocidos = [m for m in pedidos if m not in A.MUNICIPIOS_PAIS_VASCO_EUSKADI_ID]
    if desconocidos:
        sys.exit(f"Municipio(s) sin authority-id mapeado: {desconocidos}")

    existentes = _leer_existente()
    total_nuevos = 0
    total_descartados = 0
    sin_contratos = []
    umbral_obras = 40000 * 1.25   # ~40.000 € + margen de IVA/redondeo (ver _NOTAS_CONTRATO_MENOR en app.py)
    sospechosos = []

    t0 = time.time()
    for i, municipio in enumerate(pedidos, 1):
        authority_id = A.MUNICIPIOS_PAIS_VASCO_EUSKADI_ID[municipio]
        registros, descartados = buscar_menores_municipio(municipio, authority_id)
        total_descartados += descartados
        if not registros:
            sin_contratos.append(municipio)
        for reg in registros:
            existentes[reg["id"]] = reg
            if reg["import_num"] > umbral_obras:
                sospechosos.append((municipio, reg["adjudicatari"], reg["import_num"], reg["descripcio"][:80]))
        total_nuevos += len(registros)
        if i % 10 == 0 or i == len(pedidos) or len(registros) > 50:
            print(f"  [{i}/{len(pedidos)}] {municipio}: {len(registros)} contratos "
                  f"({descartados} descartados por fecha) -- {time.time() - t0:.0f} s transcurridos", flush=True)
        if i % 10 == 0 or i == len(pedidos):
            _guardar(existentes)   # progreso a salvo aunque el proceso se corte antes de terminar todos los municipios

    print(f"\nHecho: {len(existentes)} registros en {FICHERO} ({total_nuevos} nuevos/actualizados esta ejecución, "
          f"{total_descartados} descartados por fecha < {A.MENORES_DESDE_FECHA}).")
    print(f"Municipios sin ningún contrato menor: {len(sin_contratos)} -> {sin_contratos[:15]}"
          f"{'...' if len(sin_contratos) > 15 else ''}")
    if sospechosos:
        print(f"\nSANITY CHECK -- {len(sospechosos)} contratos por encima de ~{umbral_obras:.0f} € "
              "(techo legal de un contrato menor de obras + margen de IVA; revisar a mano, NO se han excluido):")
        for m, adj, imp, desc in sospechosos[:30]:
            print(f"  {m}: {adj} -- {imp:.2f} € -- {desc}")


if __name__ == "__main__":
    main()
