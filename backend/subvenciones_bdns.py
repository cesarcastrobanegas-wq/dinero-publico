# encoding: utf-8
"""
Convocatorias de subvenciones de la BDNS (Base de Datos Nacional de Subvenciones, API oficial de
infosubvenciones.es) para la pestaña "Subvenciones" de Convocatorias abiertas (decisión de César 2026-10-04).

Por qué así (medido el 04-10, ver INFORME_LICITACIONES_SUBVENCIONES.md):
- la API no tiene filtro de "abiertas" (el parámetro soloAbiertas que circula no existe y se ignora en silencio) y la
  búsqueda no trae el plazo: hay que pedir el detalle de cada convocatoria, una petición por convocatoria;
- el campo "abierto" del detalle no es fiable (dice cerrada estando en plazo): la vigencia se calcula con las fechas;
- la API avisa de que puede restringir el acceso ante abusos: 1 petición por segundo, identificados, sin repetir.

Corre en GitHub Actions (subvenciones-bdns.yml), nunca en Render: la carga inicial desde 2024 son ~200.000 detalles
(~55 h a 1 por segundo), repartidos en varias noches; el estado vive en BDNS_DB (caché de Actions). Cada noche:
    python backend/subvenciones_bdns.py actualizar --desde 2024-01-01 --minutos 320
    python backend/subvenciones_bdns.py exportar --salida subvenciones.ndjson.gz
y el flujo sube el fichero a POST /admin/subvenciones. Solo imprime recuentos.
"""
import argparse
import datetime as dt
import gzip
import json
import os
import sqlite3
import sys
import time

import requests

API = "https://www.infosubvenciones.es/bdnstrans/api"
BDNS_DB = os.environ.get("BDNS_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "bdns.db"))
UA = {"User-Agent": "DineroPublico/1.0 (transparencia; contacto@dinero-publico.com)", "Accept": "application/json"}
PAUSA = 1.0                      # segundos entre peticiones
REVISAR_SIN_FECHA_DIAS = 14      # las que no traen fecha fin se vuelven a mirar cada 2 semanas
REVISAR_SIN_FECHA_MESES = 6      # ...solo las registradas en los últimos 6 meses


def conectar():
    db = sqlite3.connect(BDNS_DB)
    db.execute("CREATE TABLE IF NOT EXISTS meses (mes TEXT PRIMARY KEY, total INTEGER, listado TEXT)")
    db.execute("CREATE TABLE IF NOT EXISTS convocatorias (bdns TEXT PRIMARY KEY, registrada TEXT, datos TEXT, "
               "revisado TEXT)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_conv_pend ON convocatorias(revisado)")
    db.commit()
    return db


class Cliente:
    def __init__(self, fin_s):
        self.s = requests.Session()
        self.s.headers.update(UA)
        self.fin_s = fin_s
        self.peticiones = 0
        self.fallos_seguidos = 0

    def tiempo(self):
        return time.time() < self.fin_s

    def get(self, ruta, params):
        """JSON de la API, o None. Ante errores repetidos para del todo (mejor seguir otra noche que insistir)."""
        for intento in range(4):
            time.sleep(PAUSA)
            self.peticiones += 1
            try:
                r = self.s.get(f"{API}/{ruta}", params=dict(params, vpd="GE"), timeout=60)
                if r.status_code == 200:
                    self.fallos_seguidos = 0
                    return r.json()
                if r.status_code == 404:
                    return None
                if r.status_code == 429:
                    time.sleep(120)
            except (requests.RequestException, ValueError):
                pass
            time.sleep(10 * (intento + 1))
        self.fallos_seguidos += 1
        if self.fallos_seguidos >= 5:
            raise RuntimeError("la API de la BDNS falla de forma repetida: se para hasta la próxima ejecución")
        return None


def _meses(desde, hasta):
    m = dt.date(desde.year, desde.month, 1)
    while m <= hasta:
        yield m
        m = dt.date(m.year + (m.month == 12), m.month % 12 + 1, 1)


def listar_mes(cli, db, mes, hasta):
    """Números de las convocatorias registradas en `mes` (páginas de 10.000)."""
    fin = min(dt.date(mes.year + (mes.month == 12), mes.month % 12 + 1, 1) - dt.timedelta(days=1), hasta)
    nuevos, pagina, total = 0, 0, None
    while cli.tiempo():
        d = cli.get("convocatorias/busqueda", {"page": pagina, "pageSize": 10000, "fechaDesde": mes.strftime("%d/%m/%Y"),
                                               "fechaHasta": fin.strftime("%d/%m/%Y")})
        if d is None:
            return None
        total = d.get("totalElements", 0)
        filas = [(str(c["numeroConvocatoria"]), c.get("fechaRecepcion", "")) for c in d.get("content", [])
                 if c.get("numeroConvocatoria")]
        cur = db.executemany("INSERT OR IGNORE INTO convocatorias (bdns, registrada) VALUES (?, ?)", filas)
        nuevos += cur.rowcount
        db.commit()
        if d.get("last", True):
            break
        pagina += 1
    return total, nuevos


def resumir(d):
    """Lo que necesita la ficha, a partir del detalle de la API."""
    org = d.get("organo") or {}
    regiones = [r.get("descripcion", "") for r in (d.get("regiones") or [])]
    nuts = ""
    for r in regiones:                                   # la región más concreta (NUTS3 > NUTS2 > ES)
        codigo = r.split(" - ")[0].strip()
        if codigo.startswith("ES") and len(codigo) > len(nuts):
            nuts = codigo
    return {
        "bdns": str(d.get("codigoBDNS") or ""),
        "registrada": d.get("fechaRecepcion") or "",
        "titulo": d.get("descripcion") or "",
        "titulo_cooficial": d.get("descripcionLeng") or "",
        "nivel1": org.get("nivel1") or "", "nivel2": org.get("nivel2") or "", "organo": org.get("nivel3") or "",
        "nuts": nuts,
        "presupuesto": d.get("presupuestoTotal"),
        "beneficiarios": " | ".join(b.get("descripcion", "").strip() for b in (d.get("tiposBeneficiarios") or [])),
        "sector": "; ".join(s.get("descripcion", "") for s in (d.get("sectores") or [])[:3]),
        "finalidad": d.get("descripcionFinalidad") or "",
        "instrumento": "; ".join(i.get("descripcion", "").strip() for i in (d.get("instrumentos") or [])),
        "inicio": d.get("fechaInicioSolicitud") or "",
        "fin": d.get("fechaFinSolicitud") or "",
        "texto_fin": d.get("textFin") or "",
        "url_bases": d.get("urlBasesReguladoras") or "",
        "mrr": bool(d.get("mrr")),
    }


def detalles(cli, db, where, args, etiqueta):
    hechos = 0
    hoy = dt.date.today().isoformat()
    while cli.tiempo():
        lote = db.execute(f"SELECT bdns FROM convocatorias WHERE {where} ORDER BY registrada DESC LIMIT 200",
                          args).fetchall()
        if not lote:
            break
        for (bdns,) in lote:
            if not cli.tiempo():
                break
            d = cli.get("convocatorias", {"numConv": bdns})
            datos = json.dumps(resumir(d), ensure_ascii=False) if d else ""
            db.execute("UPDATE convocatorias SET datos=?, revisado=? WHERE bdns=?", (datos, hoy, bdns))
            hechos += 1
            if hechos % 100 == 0:
                db.commit()
        db.commit()
    print(f"{etiqueta}: {hechos} detalles pedidos", flush=True)


def actualizar(desde, minutos):
    db = conectar()
    cli = Cliente(time.time() + minutos * 60)
    hoy = dt.date.today()
    try:
        # 1. Listados: los meses que falten enteros, y siempre el mes en curso y el anterior (convocatorias nuevas).
        recientes = {dt.date(hoy.year, hoy.month, 1), dt.date(hoy.year - (hoy.month == 1), (hoy.month - 2) % 12 + 1, 1)}
        for mes in sorted(_meses(desde, hoy), reverse=True):
            clave = mes.strftime("%Y-%m")
            hecho = db.execute("SELECT listado FROM meses WHERE mes=?", (clave,)).fetchone()
            if hecho and mes not in recientes:
                continue
            if not cli.tiempo():
                break
            res = listar_mes(cli, db, mes, hoy)
            if res is None:
                continue
            total, nuevos = res
            db.execute("INSERT OR REPLACE INTO meses VALUES (?, ?, ?)", (clave, total, hoy.isoformat()))
            db.commit()
            print(f"listado {clave}: {total} convocatorias ({nuevos} nuevas)", flush=True)
        # 2. Detalles que faltan (las más recientes primero) y 3. revisión de las que no traen fecha fin.
        detalles(cli, db, "revisado IS NULL", (), "nuevas")
        corte_rev = (hoy - dt.timedelta(days=REVISAR_SIN_FECHA_DIAS)).isoformat()
        corte_reg = (hoy - dt.timedelta(days=30 * REVISAR_SIN_FECHA_MESES)).isoformat()
        detalles(cli, db, "revisado < ? AND registrada >= ? AND datos LIKE '%\"fin\": \"\"%'", (corte_rev, corte_reg),
                 "revisadas sin fecha fin")
    except RuntimeError as e:
        print(f"AVISO: {e}", flush=True)
    estado(db)
    print(f"peticiones a la API en esta ejecución: {cli.peticiones}", flush=True)


def exportar(salida):
    """NDJSON en gzip con las convocatorias no cerradas por fechas (fin vacío o fin >= hoy)."""
    db = conectar()
    hoy = dt.date.today().isoformat()
    n = 0
    with gzip.open(salida, "wt", encoding="utf-8") as f:
        for (datos,) in db.execute("SELECT datos FROM convocatorias WHERE datos IS NOT NULL AND datos != ''"):
            d = json.loads(datos)
            if d.get("fin") and d["fin"] < hoy:
                continue
            if not d.get("bdns"):
                continue
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
            n += 1
    print(f"exportadas {n} convocatorias no cerradas -> {os.path.basename(salida)} "
          f"({os.path.getsize(salida) // 1024} KB)", flush=True)
    return n


def estado(db=None):
    db = db or conectar()
    meses = db.execute("SELECT count(*), min(mes), max(mes) FROM meses").fetchone()
    tot, con = db.execute("SELECT count(*), sum(revisado IS NOT NULL) FROM convocatorias").fetchone()
    print(f"meses listados: {meses[0]} ({meses[1]} a {meses[2]}) | convocatorias: {tot}, con detalle: {con or 0} "
          f"({(con or 0) * 100 // max(tot, 1)} %)", flush=True)


def carga_completa(desde, salida_github=""):
    """¿Ha terminado la carga inicial? Todos los meses desde `desde` listados y ninguna convocatoria sin detalle.
    La PRIMERA vez que se cumple lo anota en la base (tabla avisos) y devuelve True; después, siempre False: el aviso
    a César (issue + correo de GitHub, ver subvenciones-bdns.yml) sale una sola vez. Con salida_github escribe
    completa=true|false en $GITHUB_OUTPUT."""
    db = conectar()
    db.execute("CREATE TABLE IF NOT EXISTS avisos (clave TEXT PRIMARY KEY, cuando TEXT)")
    hoy = dt.date.today()
    esperados = {m.strftime("%Y-%m") for m in _meses(desde, hoy)}
    listados = {r[0] for r in db.execute("SELECT mes FROM meses")}
    faltan_meses = len(esperados - listados)
    pendientes = db.execute("SELECT count(*) FROM convocatorias WHERE revisado IS NULL").fetchone()[0]
    total = db.execute("SELECT count(*) FROM convocatorias").fetchone()[0]
    ya = db.execute("SELECT cuando FROM avisos WHERE clave='carga_inicial_completa'").fetchone()
    completa = faltan_meses == 0 and pendientes == 0 and total > 0
    primera = completa and not ya
    if primera:
        db.execute("INSERT INTO avisos VALUES ('carga_inicial_completa', ?)", (dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")[:16],))
        db.commit()
    print(f"carga inicial: {total} convocatorias, {pendientes} pendientes de detalle, {faltan_meses} meses sin listar"
          f" -> {'COMPLETA (primera vez: se avisa)' if primera else ('completa (ya avisado el ' + ya[0] + ')' if ya else 'en curso')}",
          flush=True)
    if salida_github:
        with open(salida_github, "a", encoding="utf-8") as f:
            f.write(f"completa={'true' if primera else 'false'}\n")
            f.write(f"total={total}\n")
    return primera


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    a = sub.add_parser("actualizar")
    a.add_argument("--desde", default="2024-01-01")
    a.add_argument("--minutos", type=float, default=320)
    e = sub.add_parser("exportar")
    e.add_argument("--salida", required=True)
    sub.add_parser("estado")
    c = sub.add_parser("carga-completa")
    c.add_argument("--desde", default="2024-01-01")
    args = ap.parse_args()
    if args.cmd == "actualizar":
        actualizar(dt.date.fromisoformat(args.desde), args.minutos)
    elif args.cmd == "exportar":
        sys.exit(0 if exportar(args.salida) else 1)
    elif args.cmd == "carga-completa":
        carga_completa(dt.date.fromisoformat(args.desde), os.environ.get("GITHUB_OUTPUT", ""))
    elif args.cmd == "estado":
        estado()
    else:
        ap.print_help()
