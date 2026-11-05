# encoding: utf-8
"""
Regenera de una vez el material para salir a llamar o a visitar (HERRAMIENTA LOCAL, 2026-11-04; la web no la usa):

  1. baja de PLACE el ZIP del mes en curso (y el del mes anterior si no está ya), en <base>/llamadas/place;
  2. los 3 informes de muestra en <base>/informes_muestra (mismos nombres de siempre: se sobrescriben);
  3. la lista de llamadas (.xlsx y .pdf), las fichas de llamada y el seguimiento en <base>/llamadas;
  4. un informe de muestra por cada sector de la lista en <base>/informes_muestra/por sector;
  5. el correo para DESPUÉS de la llamada (solo si lo piden), uno por empresa, en <base>/llamadas/correos;
  6. la hoja para dejar en las visitas de cada sector en <base>/hojas para visitas;
  7. con --resumenes, además, el resumen semanal de cada cliente en prueba de <base>/clientes en prueba.
Lo leído de los ZIP se guarda en <base>/llamadas/place/cache_licitaciones.sqlite: solo se relee un ZIP si cambia.

<base> es la carpeta de trabajo del titular (fuera del repositorio): ahí están la copia de la base
(cache_produccion.db), la lista de clientes potenciales y el Excel de contactos. Todo se lee una vez y se reutiliza.
No toca la web ni producción: solo lee la copia local de la base y los ZIP públicos de PLACE.

Uso: python backend/regenerar_venta.py --base CARPETA [--contacto-tel "TELÉFONO"] [--firma "NOMBRE"] [--sin-descarga]
                                       [--resumenes]
"""
import argparse
import os
import sys
import time
import urllib.request
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import informe_mercado as I  # noqa: E402
import llamadas as L  # noqa: E402

URL_PLACE = ("https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_643/"
             "licitacionesPerfilesContratanteCompleto3_{mes}.zip")
MUESTRAS = (  # (nombre del PDF, sector, NIF o None)
    ("1 - Limpieza en la Region de Murcia.pdf", "Limpieza", None),
    ("2 - Informatica y telecomunicaciones en la Region de Murcia.pdf", "Informática y telecomunicaciones", None),
    ("3 - Empresa - Industrias Electricas Brocal (mantenimiento e instalaciones).pdf", "Mantenimiento e instalaciones",
     "A30051130"),
)
CLIENTES_CSV = os.path.join("clientes potenciales", "Clientes potenciales Region de Murcia - 200 sociedades.csv")
CONTACTOS_XLSX = os.path.join("reunion camara comercio", "CLIENTES", "Clientes Region de Murcia (de nuestros datos).xlsx")


def _mes(d, menos=0):
    a, m = d.year, d.month - menos
    while m < 1:
        a, m = a - 1, m + 12
    return f"{a}{m:02d}"


def _huella(ruta):
    import hashlib
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for trozo in iter(lambda: f.read(1 << 20), b""):
            h.update(trozo)
    return os.path.getsize(ruta), h.hexdigest()


def bajar(url, destino, intentos=3):
    tmp = destino + ".part"
    for i in range(1, intentos + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (descarga de datos abiertos)"})
            with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as f:
                while True:
                    trozo = r.read(1 << 20)
                    if not trozo:
                        break
                    f.write(trozo)
            if os.path.exists(destino) and _huella(destino) == _huella(tmp):
                os.remove(tmp)      # igual que el que ya había: se deja el viejo (y su caché sigue valiendo)
                print("  (sin cambios desde la última descarga)", flush=True)
            else:
                os.replace(tmp, destino)
            return
        except OSError as ex:
            print(f"  intento {i} fallido: {ex}", flush=True)
            time.sleep(10 * i)
    raise SystemExit(f"No se pudo bajar {url}")


def zips_place(carpeta, hoy, descargar=True):
    """[ZIP del mes anterior, ZIP del mes en curso]. El del mes en curso se baja SIEMPRE (cambia cada día); el del
    anterior solo si falta (ya no cambia)."""
    os.makedirs(carpeta, exist_ok=True)
    res = []
    for menos in (1, 0):
        mes = _mes(hoy, menos)
        ruta = os.path.join(carpeta, f"place_{mes}.zip")
        if descargar and (menos == 0 or not os.path.exists(ruta)):
            t = time.time()
            print(f"Bajando el ZIP de PLACE de {mes} (puede tardar: el servidor es lento)...", flush=True)
            bajar(URL_PLACE.format(mes=mes), ruta)
            print(f"  {os.path.getsize(ruta) / 1e6:.0f} MB en {(time.time() - t) / 60:.1f} min", flush=True)
        if os.path.exists(ruta):
            res.append(ruta)
    if not res:
        raise SystemExit(f"No hay ningún ZIP de PLACE en {carpeta}")
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", required=True, help="carpeta de trabajo (la de la copia de la base y los clientes)")
    ap.add_argument("--db", help="copia de la base (por defecto, <base>/cache_produccion.db)")
    ap.add_argument("--contacto-tel", default=I.CONTACTO_TEL)
    ap.add_argument("--firma", default=os.environ.get("INFORME_FIRMA", ""),
                    help="nombre para la firma de los correos (no se escribe en el código)")
    ap.add_argument("--sin-descarga", action="store_true", help="usar los ZIP que ya haya, sin bajar nada")
    ap.add_argument("--resumenes", action="store_true", help="también los resúmenes de los clientes en prueba")
    ap.add_argument("--n", type=int, default=30)
    a = ap.parse_args(argv)
    t0 = time.time()
    base = a.base
    db = a.db or os.path.join(base, "cache_produccion.db")
    hasta = date.fromtimestamp(os.path.getmtime(db)).isoformat()
    ahora = datetime.now()
    zips = zips_place(os.path.join(base, "llamadas", "place"), ahora.date(), not a.sin_descarga)
    t1 = time.time()
    print(f"Leyendo licitaciones abiertas de {len(zips)} ZIP...", flush=True)
    lic = I.cargar_licitaciones(zips, "murcia", ahora)
    print(f"  {len(lic)} licitaciones abiertas en la Región de Murcia", flush=True)
    print(f"Leyendo contratos de la copia de la base (hasta el {hasta})...", flush=True)
    contratos = I.cargar_contratos(db, "murcia", L.DESDE_POR_DEFECTO, hasta)
    print(f"  {len(contratos)} contratos", flush=True)
    contacto = {"tel": a.contacto_tel, "email": I.CONTACTO_EMAIL, "web": I.CONTACTO_WEB}
    desde_muestras = f"{int(hasta[:4]) - 2}{hasta[4:]}"
    dos_anios = [r for r in contratos if desde_muestras <= r["fecha"] <= hasta]
    carpeta_muestras = os.path.join(base, "informes_muestra")
    os.makedirs(carpeta_muestras, exist_ok=True)
    for nombre, sector, nif in MUESTRAS:
        A = I.analizar(dos_anios, lic, sector=sector, nif=nif)
        pags, _ = I.informe_pdf(os.path.join(carpeta_muestras, nombre), A, "murcia", desde_muestras, hasta, ahora,
                                contacto=contacto)
        print(f"Muestra: {nombre} ({pags} páginas, {len(A['abiertas'])} licitaciones abiertas)", flush=True)
    t2 = time.time()
    salida = os.path.join(base, "llamadas")
    el = L.generar(contratos, lic, os.path.join(base, CLIENTES_CSV), salida, hasta, ahora,
                   os.path.join(base, CONTACTOS_XLSX), a.n, L.DESDE_POR_DEFECTO, a.contacto_tel)
    print(f"Lista y fichas: {len(el)} empresas ({sum(1 for e in el if e['abiertas'])} con licitaciones abiertas) "
          f"en {salida} ({(time.time() - t2) / 60:.1f} min)", flush=True)
    # un informe de muestra por cada sector de la lista (para llevar a cada llamada el suyo)
    t3 = time.time()
    por_sector = os.path.join(carpeta_muestras, "por sector")
    os.makedirs(por_sector, exist_ok=True)
    sectores_lista = list(dict.fromkeys(e["sector"] for e in el))
    hechos = set()
    for s in sectores_lista:
        nombre = L.nombre_informe_sector(s)
        A = I.analizar(dos_anios, lic, sector=s)
        pags, _ = I.informe_pdf(os.path.join(por_sector, nombre), A, "murcia", desde_muestras, hasta, ahora,
                                contacto=contacto)
        hechos.add(nombre)
        print(f"Sector: {nombre} ({pags} páginas, {len(A['abiertas'])} licitaciones abiertas)", flush=True)
    for viejo in os.listdir(por_sector):      # los de sectores que ya no están en la lista
        if viejo.startswith("Sector - ") and viejo.endswith(".pdf") and viejo not in hechos:
            try:
                os.remove(os.path.join(por_sector, viejo))
            except OSError:
                print(f"  (no he podido quitar {viejo}: ¿está abierto?)", flush=True)
    print(f"  {len(hechos)} informes por sector en {(time.time() - t3) / 60:.1f} min", flush=True)
    # el correo para después de la llamada (solo si lo pide): uno por empresa, con el informe de su sector
    import correo_llamada as C
    correos = C.escribir(salida, el, ahora, a.firma, a.contacto_tel, por_sector)
    print(f"Correos para después de la llamada: {len(correos)} en {os.path.join(salida, C.CARPETA_CORREOS)}",
          flush=True)
    # hoja para dejar en las visitas: una por sector (todos los sectores)
    t4 = time.time()
    import hoja_visita as H
    hojas = H.generar_hojas(dos_anios, lic, base, desde_muestras, hasta, ahora, contacto, I.NOMBRES_SECTOR)
    sin = [s for s, _, ej in hojas if not ej]
    print(f"Hojas para visitas: {len(hojas)} en {os.path.join(base, H.CARPETA_HOJAS)}"
          + (f" ({len(sin)} sin ejemplo hoy: {', '.join(sin)})" if sin else "")
          + f" ({(time.time() - t4) / 60:.1f} min)", flush=True)
    if a.resumenes:
        import prueba_gratis as PG
        carpeta = os.path.join(base, "clientes en prueba")
        for p in PG.clientes(carpeta):
            rp, rt, nuevas, siguen = PG.resumen(carpeta, p, lic, ahora, contacto)
            print(f"Resumen de {p['correo']}: {len(nuevas)} nuevas, {len(siguen)} siguen -> {rt}", flush=True)
    print(f"Hecho en {(time.time() - t0) / 60:.1f} min (descarga {(t1 - t0) / 60:.1f} min, el resto "
          f"{(time.time() - t1) / 60:.1f} min).", flush=True)


if __name__ == "__main__":
    main()
