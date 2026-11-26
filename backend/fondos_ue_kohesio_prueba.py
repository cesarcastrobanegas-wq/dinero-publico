# encoding: utf-8
"""
Prueba SIN RED de la descarga de Kohesio y de la subida desde el PC (2026-11-05). Datos de EJEMPLO inventados, sesión
y servidor simulados (nunca la web real ni la Comisión): la red queda cortada en todo el proceso.
  1. el 403 del balanceador de la Comisión (bloqueo por IP) para a la primera, con el aviso y el comando del PC;
     un 503 o un corte sí se reintentan; un 403 sin balanceador sigue reintentándose como antes;
  2. la lista de Kohesio se pide por páginas de 1.000 hasta numberResults (con el formato de su API);
  3. generar(..., una_fuente_opcional=True) con Kohesio bloqueado: el fichero sale con las demás y la marca .falta
     dice «kohesio» y el motivo;
  4. subir_fondos_ue_pc.subir: token en la cabecera, ?conservar=kohesio si falta, reintento si la web se reinicia,
     409 sin reintentar; el script no acepta TU_TOKEN_AQUI y el token no se escribe en ningún fichero;
  5. el flujo: sigue saliendo en rojo si falta una fuente y el resumen dice cómo cargar Kohesio desde el PC.
Uso: python backend/fondos_ue_kohesio_prueba.py
"""
import gzip
import json
import os
import socket
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def _sin_red(*a, **k):
    raise OSError("red cortada en la prueba")


socket.create_connection = _sin_red
socket.socket.connect = lambda self, *a, **k: _sin_red()

import requests  # noqa: E402
import fondos_ue_espana as F  # noqa: E402
import subir_fondos_ue_pc as P  # noqa: E402

FALLOS = []


def ok(cond, txt):
    print(("OK   " if cond else "FALLO") + " " + txt)
    if not cond:
        FALLOS.append(txt)


class Resp:
    def __init__(self, codigo, cuerpo=None, server="", texto=""):
        self.status_code, self._cuerpo, self.text = codigo, cuerpo, texto or json.dumps(cuerpo or {})
        self.headers = {"Server": server} if server else {}

    def json(self):
        if self._cuerpo is None:
            raise ValueError("sin JSON")
        return self._cuerpo


class Sesion:
    def __init__(self, respuestas):
        self.respuestas, self.pedidas = list(respuestas), []

    def get(self, url, **kw):
        self.pedidas.append(url)
        r = self.respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r(url) if callable(r) else r


def main():
    F.time.sleep = lambda s: None
    P.time.sleep = lambda s: None
    url_k = F.KOHESIO_API + "/projects?country=x"
    bloqueo = Resp(403, server="awselb/2.0", texto="<html><title>403 Forbidden</title></html>")

    # 1) bloqueo por IP: una sola petición, aviso claro
    s = Sesion([bloqueo] * 4)
    try:
        F._pedir(s, url_k)
        ok(False, "bloqueo por IP: debía pararse")
    except SystemExit as e:
        ok(len(s.pedidas) == 1, f"bloqueo por IP: para a la primera petición ({len(s.pedidas)})")
        ok("bloquea" in str(e) and "subir_fondos_ue_pc.py" in str(e) and "403" in str(e),
           "el error explica el bloqueo y da el comando del PC")
    s = Sesion([Resp(503), requests.ConnectionError("corte"), Resp(200, {"x": 1})])
    ok(F._pedir(s, url_k).json() == {"x": 1} and len(s.pedidas) == 3, "503 y un corte sí se reintentan")
    s = Sesion([Resp(403), Resp(200, {"x": 2})])
    ok(F._pedir(s, url_k).json() == {"x": 2}, "un 403 sin el balanceador se reintenta como antes")
    ok(F.bloqueo_por_ip(Resp(403, server="awselb/2.0")) and not F.bloqueo_por_ip(Resp(403, server="nginx"))
       and not F.bloqueo_por_ip(Resp(200, server="awselb/2.0")), "bloqueo_por_ip solo con 403 + awselb")

    # 2) paginación de la lista (formato de su API: list / item / numberResults), datos de ejemplo
    total = 2350

    def pagina(url):
        desde = int(url.split("offset=")[1].split("&")[0])
        lote = [{"item": f"Q{i}", "labels": [f"Proyecto de ejemplo {i}"], "totalBudget": "1000,50"}
                for i in range(desde, min(desde + F._KOHESIO_LOTE, total))]
        return Resp(200, {"list": lote, "numberResults": total})
    s = Sesion([pagina] * 5)
    ids = F._kohesio_ids(s, "&fund=ejemplo")
    ok(len(ids) == total and len(s.pedidas) == 3, f"lista por páginas de 1.000: {len(ids)} en {len(s.pedidas)} peticiones")
    ok(all("limit=1000" in u and "&fund=ejemplo" in u for u in s.pedidas)
       and [u.split("offset=")[1].split("&")[0] for u in s.pedidas] == ["0", "1000", "2000"],
       "offset 0, 1000, 2000 y el filtro en cada página")
    ok(F._k_importe(["239977467,04"]) == F._k_importe("+239977467.04"), "importe de la lista y de la ficha, igual")

    # 3) generar con Kohesio bloqueado: sale con las demás y la marca dice por qué
    d = tempfile.mkdtemp(prefix="fondos_ue_prueba_")
    ruta = os.path.join(d, "fondos_ue.ndjson.gz")
    reales = F.descargar_cohesion, F.descargar_cordis, F.descargar_kohesio, F.descargar_mrr100
    fila = lambda i, fuente: {"id": f"{fuente}-{i}", "fuente": fuente, "importe_num": 1000.0, "ambito": "provincia",
                               "provincia": "murcia", "beneficiario": ""}  # noqa: E731
    F.descargar_cohesion = lambda ses, con_nombres=False: [fila(i, "cohesion") for i in range(50000)]
    F.descargar_cordis = lambda ses, con_nombres=False: [fila(i, "cordis") for i in range(5000)]
    F.descargar_mrr100 = lambda ses: [fila(1, "mrr100")]
    F.descargar_kohesio = lambda ses, con_nombres=True: F._pedir(Sesion([bloqueo]), url_k)
    try:
        F.generar(ruta, con_nombres=True, una_fuente_opcional=True)
    finally:
        F.descargar_cohesion, F.descargar_cordis, F.descargar_kohesio, F.descargar_mrr100 = reales
    marca = open(ruta + ".falta", encoding="utf-8").read().splitlines()
    with gzip.open(ruta, "rt", encoding="utf-8") as f:
        fuentes = {json.loads(x)["fuente"] for x in f}
    ok(marca[0] == "kohesio" and "bloquea" in marca[1], f"marca .falta: kohesio y el motivo ({marca[0]})")
    ok(fuentes == {"cohesion", "cordis", "mrr100"}, f"el fichero lleva las otras tres fuentes ({sorted(fuentes)})")

    # 4) la subida desde el PC (servidor simulado)
    class RQ:
        RequestException = requests.RequestException

        def __init__(self, respuestas):
            self.respuestas, self.llamadas = list(respuestas), []

        def post(self, url, data=None, headers=None, timeout=None):
            self.llamadas.append((url, headers, len(data)))
            r = self.respuestas.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
    rq = RQ([Resp(503), requests.ConnectionError("reinicio"),
             Resp(200, {"conservado": {"fuente": "kohesio", "conservadas": 28061, "de_la_carga_del": "2026-10-21 22:06"}})])
    codigo, cuerpo, falta = P.subir(ruta, "token-de-prueba", url="https://web.ejemplo.test/admin/fondos-ue", requests_mod=rq)
    ok(codigo == 200 and falta == "kohesio" and len(rq.llamadas) == 3, f"subida: reintenta si la web se reinicia ({codigo})")
    ok(all(u == "https://web.ejemplo.test/admin/fondos-ue?conservar=kohesio" for u, _, _ in rq.llamadas),
       "sin Kohesio: ?conservar=kohesio")
    ok(rq.llamadas[0][1] == {"Content-Type": "application/gzip", "X-Admin-Token": "token-de-prueba"},
       "el token va en la cabecera X-Admin-Token, como en el flujo")
    os.remove(ruta + ".falta")
    rq = RQ([Resp(409, {"error": "trae menos del 80 %"}), Resp(200, {})])
    codigo, cuerpo, falta = P.subir(ruta, "t", url="https://web.ejemplo.test/x", requests_mod=rq)
    ok(codigo == 409 and len(rq.llamadas) == 1 and rq.llamadas[0][0] == "https://web.ejemplo.test/x" and not falta,
       "409 (trae de menos): no se reintenta; con todo, sin ?conservar")
    rq = RQ([Resp(503)] * 50)
    codigo, cuerpo, _ = P.subir(ruta, "t", url="https://web.ejemplo.test/x", requests_mod=rq, espera_max=0)
    ok(codigo == 503 and "sin responder" in cuerpo, "si la web no vuelve, se rinde y lo dice")
    for malo in (["--token", "TU_TOKEN_AQUI"], ["--token", "  "]):
        try:
            P.main(malo)
            ok(False, f"{malo}: debía pararse")
        except SystemExit as e:
            ok("token" in str(e), f"token {malo[1]!r}: se para sin generar ni subir")
    fuente = open(P.__file__, encoding="utf-8").read()
    ok(".write(" not in fuente and "json.dump(" not in fuente, "el script no escribe nada a disco: el token no se guarda")

    # 5) el flujo
    yml = open(os.path.join(os.path.dirname(AQUI), ".github", "workflows", "fondos-ue-espana.yml"), encoding="utf-8").read()
    ok("--una-fuente-opcional" in yml and 'if [ -n "$falta" ]; then exit 1; fi' in yml,
       "el flujo sigue saliendo EN ROJO si falta una fuente")
    ok("subir_fondos_ue_pc.py" in yml and '"$falta" = "kohesio"' in yml, "el resumen dice cómo cargar Kohesio desde el PC")
    ok(not os.path.exists(os.path.join(os.path.dirname(AQUI), ".github", "workflows", "kohesio-diagnostico.yml")),
       "no queda el flujo de diagnóstico temporal")
    print(f"\n{'TODO BIEN' if not FALLOS else str(len(FALLOS)) + ' FALLOS'}")
    sys.exit(1 if FALLOS else 0)


if __name__ == "__main__":
    main()
