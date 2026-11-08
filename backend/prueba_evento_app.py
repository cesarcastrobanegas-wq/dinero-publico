# encoding: utf-8
"""Prueba del límite de /api/evento y de los totales de la app en el panel de visitas (08-11-2026). Sin red, con una
base vacía en una carpeta temporal y con la función WSGI de verdad (app.app). Las IP son de los rangos de
documentación (192.0.2.x, 198.51.100.x, 2001:db8::), no de nadie.

    python backend/prueba_evento_app.py      (proceso pesado: importa la web; de uno en uno, ~2 min)
"""
import io
import os
import sys
import tempfile
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36"
IP_A, IP_B, IP_6 = "192.0.2.10", "198.51.100.20", "2001:db8::7"


def main():
    os.environ.update(DATA_DIR=tempfile.mkdtemp(prefix="evento_app_"), HTTP_PROXY="http://127.0.0.1:9",
                      HTTPS_PROXY="http://127.0.0.1:9")
    import app
    for hilo in threading.enumerate():
        if hilo.name == "carga-place-menores":
            hilo.join(timeout=1800)
    mal = []

    def evento(tipo, ip, ua=UA):
        cuerpo = tipo.encode()
        env = {"REQUEST_METHOD": "POST", "PATH_INFO": "/api/evento", "QUERY_STRING": "", "HTTP_USER_AGENT": ua,
               "HTTP_X_FORWARDED_FOR": ip, "CONTENT_LENGTH": str(len(cuerpo)), "wsgi.input": io.BytesIO(cuerpo)}
        estado = []
        app.app(env, lambda s, h, e=None: estado.append(s))
        return estado[0][:3]

    def contados(nombre):
        with app._visitas_lock:
            return sum(v[0] for (d, c, n), v in app._visitas_pend.items() if c == "evento" and n == nombre)

    cupo = app._EVENTO_CUPO_HORA
    # 1. Hasta el límite cuenta; a partir de ahí no, y la respuesta es siempre la misma (204).
    codigos = {evento("instalacion", IP_A) for _ in range(cupo + 5)}
    if codigos != {"204"}:
        mal.append(f"respuestas distintas de 204: {codigos}")
    if contados("instalacion") != cupo:
        mal.append(f"IP A: contadas {contados('instalacion')} instalaciones, esperaba {cupo}")
    if contados("frenado") != 5:
        mal.append(f"frenados: {contados('frenado')}, esperaba 5")
    # 2. El límite es por conexión: otra IP (y una IPv6) siguen contando; las páginas desde la app comparten límite.
    for _ in range(3):
        evento("app", IP_B)
        evento("app", IP_6)
    if contados("app_pagina") != 6:
        mal.append(f"IP B e IPv6: contadas {contados('app_pagina')} páginas desde la app, esperaba 6")
    evento("app", IP_A)
    if contados("app_pagina") != 6:
        mal.append("IP A ya en el límite: una página desde la app se ha contado igual")
    # 3. Lo que no es un navegador ni gasta cupo ni cuenta.
    antes = dict(app._evento_cupo["cuentas"])
    evento("instalacion", "192.0.2.99", ua="curl/8.0")
    if app._evento_cupo["cuentas"] != antes or contados("instalacion") != cupo:
        mal.append("una petición que no es de navegador ha contado o ha gastado cupo")
    # 4. Sin la IP: solo resúmenes de 8 bytes en memoria, nada parecido a la IP en el estado ni en la base.
    claves = list(app._evento_cupo["cuentas"])
    if not claves or any(not isinstance(k, bytes) or len(k) != 8 for k in claves):
        mal.append("las claves del límite no son resúmenes de 8 bytes")
    estado_txt = repr(app._evento_cupo)
    for ip in (IP_A, IP_B, IP_6, "192.0.2", "198.51.100", "2001:db8"):
        if ip in estado_txt:
            mal.append(f"la IP {ip} está en memoria en el estado del límite")
    # 5. Al cambiar de hora se borra todo y se cambia la sal: vuelve a contar.
    sal = app._evento_cupo["sal"]
    hora = app._evento_cupo["hora"]
    env_a = {"HTTP_X_FORWARDED_FOR": IP_A}
    if app._evento_con_cupo(env_a, ahora_s=(hora + 1) * 3600 + 5) is not True:
        mal.append("en la hora siguiente la IP A sigue frenada")
    if app._evento_cupo["sal"] == sal or len(app._evento_cupo["cuentas"]) != 1:
        mal.append("al cambiar de hora no se han borrado los recuentos o no ha cambiado la sal")
    # 6. Tabla llena (muchas IP en una hora): las nuevas no cuentan, las que ya estaban sí.
    viejo_max = app._EVENTO_CUPO_MAX_CLAVES
    app._EVENTO_CUPO_MAX_CLAVES = 2
    try:
        t = (hora + 1) * 3600 + 10
        r = [app._evento_con_cupo({"HTTP_X_FORWARDED_FOR": f"192.0.2.{i}"}, ahora_s=t) for i in (50, 51, 52)]
        if r != [True, False, False] or app._evento_con_cupo(env_a, ahora_s=t) is not True:
            mal.append(f"con la tabla llena: {r}")
    finally:
        app._EVENTO_CUPO_MAX_CLAVES = viejo_max
    # 7. Panel: bloque «App instalada» con 7 y 30 días (también con ?dias=7), tras volcar a la base.
    app._visitas_volcar()
    with app._db_lock:
        en_base = " ".join(str(f) for f in app._db.execute("SELECT * FROM visitas_dia").fetchall())
    for ip in (IP_A, IP_B, IP_6):
        if ip in en_base:
            mal.append(f"la IP {ip} ha llegado a la base")
    for qs in ({}, {"dias": ["7"]}, {"dias": ["90"]}):
        _c, _h, cuerpo = app._visitas_pagina(qs, autorizado=True)
        html_ = cuerpo.decode("utf-8") if isinstance(cuerpo, bytes) else cuerpo
        if "<h2>App instalada</h2>" not in html_:
            mal.append(f"panel {qs}: no sale el bloque «App instalada»")
            continue
        bloque = html_.split("<h2>App instalada</h2>", 1)[1].split("</table>", 1)[0]
        for fila, n in (("Instalaciones de la app", cupo), ("Páginas vistas desde la app instalada", 6),
                        ("Avisos no contados por pasar del límite", 6)):
            esperado = f"<td>{fila}</td><td>{n}</td><td>{n}</td>"
            if esperado not in bloque:
                mal.append(f"panel {qs}: la fila «{fila}» no dice {n} y {n}")
    if mal:
        print(f"FALLOS: {len(mal)}")
        for m in mal:
            print("  - " + m)
        return 1
    print("TODO BIEN: límite de /api/evento y totales de la app en el panel")
    return 0


if __name__ == "__main__":
    r = main()
    sys.stdout.flush()
    os._exit(r)
