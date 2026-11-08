# encoding: utf-8
"""Prueba del bloque «¿Tienes una empresa?» de la portada (08-11-2026). Sin red, con una base vacía en una carpeta
temporal, licitaciones y subvenciones inventadas (organismos «Organismo de prueba N», sin nadie real) y la función
WSGI de verdad (app.app) para el contador de clics.

Comprueba: el bloque va lo primero, antes del titular; N es el número real de abiertas (singular con 1); salen las 3
que cierran antes (con 2 días de margen como mínimo), con organismo, objeto corto, importe sin IVA y plazo, y enlace a su anuncio; no salen las cerradas
ni las que no tienen enlace; sin licitaciones no hay bloque; el botón del aviso solo sale con FILTRO_FORMULARIO; la
caché de 5 minutos; la banda «¿Cuál es tu municipio?» va debajo del titular; cuadros de convocatorias y botón del menú
en verde; textos en gl/ca/eu; los clics se cuentan y salen en el panel de visitas.

    python backend/prueba_portada_empresas.py      (proceso pesado: importa la web; de uno en uno)
"""
import io
import os
import re
import sys
import tempfile
import threading
from datetime import timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
IP = "192.0.2.44"        # rango de documentación


def main():
    os.environ.update(DATA_DIR=tempfile.mkdtemp(prefix="portada_empresas_"), HTTP_PROXY="http://127.0.0.1:9",
                      HTTPS_PROXY="http://127.0.0.1:9")
    os.environ.pop("FILTRO_FORMULARIO", None)
    import app
    for hilo in threading.enumerate():
        if hilo.name == "carga-place-menores":
            hilo.join(timeout=1800)
    mal = []
    bien = [0]

    def comprobar(cond, texto):
        if cond:
            bien[0] += 1
        else:
            mal.append(texto)

    def portada(idioma=None):
        app._portada_empresas_cache.update(ts=0.0, datos=None)
        tok = app._I18N_IDIOMA.set(idioma) if idioma else None
        try:
            return app.render_landing_nacional_html(app._db_municipios_ligeros(), rk_comunidad="todas")
        finally:
            if tok:
                app._I18N_IDIOMA.reset(tok)

    def cuerpo(html_):
        return html_[html_.index("<body"):] if "<body" in html_ else html_

    ahora = app._ahora_madrid()
    f = lambda d, h=0: (ahora + timedelta(days=d, hours=h)).strftime("%Y-%m-%d %H:%M")
    # 0. Sin licitaciones: no hay bloque.
    comprobar('class="emp-bloque"' not in portada(), "sin licitaciones sale el bloque")
    # Licitaciones inventadas: 5 abiertas con enlace, 1 abierta sin enlace, 1 cerrada (plazo pasado), 1 adjudicada.
    filas = [
        ("L1", f(-5), "PUB", f(10), "Servicio de limpieza de prueba uno", "https://ejemplo.test/l1", "Organismo de prueba 1", 0),
        ("L2", f(-1), "PUB", f(3), "Suministro de prueba dos " + "con un objeto larguísimo " * 10, "https://ejemplo.test/l2", "Organismo de prueba 2", 250000.5),
        ("L3", f(-2), "PUB", f(1), "Obra de prueba tres", "https://ejemplo.test/l3", "Organismo de prueba 3", 0),
        ("L4", f(-3), "PUB", f(2, 1), "Servicio de prueba cuatro", "https://ejemplo.test/l4", "Organismo de prueba 4", 9000.0),
        ("L5", f(-9), "PUB", f(2, -1), "Servicio de prueba cinco", "https://ejemplo.test/l5", "Organismo de prueba 5", 100.0),
        ("L6", f(0, -1), "PUB", f(5), "Sin enlace de prueba seis", "", "Organismo de prueba 6", 100.0),
        ("L7", f(0, -1), "PUB", f(-1), "Cerrada de prueba siete", "https://ejemplo.test/l7", "Organismo de prueba 7", 100.0),
        ("L8", f(0, -1), "ADJ", f(9), "Adjudicada de prueba ocho", "https://ejemplo.test/l8", "Organismo de prueba 8", 100.0),
    ]
    with app._db_lock:
        app._db.executemany("INSERT INTO licitaciones (id, actualizado, estado, fin_plazo, titulo, url, organo, "
                            "presupuesto) VALUES (?,?,?,?,?,?,?,?)", filas)
        app._db.execute("INSERT INTO subvenciones (bdns, titulo, inicio, fin) VALUES ('999001', 'Subvención de prueba', '', ?)",
                        (f(15)[:10],))
        app._db.commit()
    app.SUBVENCIONES_PUBLICAS = True

    h = cuerpo(portada())
    # 1. Va lo primero: antes del titular y del panel del buscador.
    i_emp, i_hero = h.find('class="emp-bloque"'), h.find('class="hero-panel"')
    comprobar(0 <= i_emp < i_hero, "el bloque de empresas no va antes del titular")
    comprobar(h.find("<header") < i_emp, "el bloque va antes de la cabecera")
    bloque = h[i_emp:i_hero]
    # 2. N real: 6 abiertas (L1-L6); la cerrada y la adjudicada no cuentan.
    comprobar("Hoy hay <b>6</b> licitaciones públicas abiertas." in bloque, "N no es 6 o falta el título")
    # Con el filtro apagado no se promete «te decimos cuáles encajan»: se invita a ver la lista.
    comprobar("mientras tú no te enteras. Míralas todas aquí, ordenadas y con su plazo." in bloque,
              "apagado: falta el texto «Míralas todas aquí»")
    comprobar("Te decimos" not in bloque, "apagado: sale «Te decimos cuáles encajan»")
    # 3. «Cierran pronto»: las 3 de plazo más cercano con al menos 2 días de margen y con enlace. Fuera L3 (cierra en
    #    1 día) y L5 (en 2 días menos 1 hora, el borde); L6 no tiene enlace. Quedan L4 (2 días y 1 hora), L2 y L1.
    comprobar('<div class="emp-ultimas-tit">Cierran pronto</div>' in bloque and "últimas publicadas" not in bloque,
              "falta el título «Cierran pronto»")
    enlaces = re.findall(r'class="emp-obj" href="([^"]+)"', bloque)
    comprobar(enlaces == ["https://ejemplo.test/l4", "https://ejemplo.test/l2", "https://ejemplo.test/l1"],
              f"cierran pronto: {enlaces}")
    comprobar("l3" not in bloque and "l5" not in bloque, "sale una con menos de 2 días de margen")
    comprobar("l7" not in bloque and "l8" not in bloque and "seis" not in bloque, "sale una cerrada o sin enlace")
    comprobar("Organismo de prueba 2" in bloque and "Organismo de prueba 4" in bloque, "falta el organismo")
    comprobar("larguísimo …" not in bloque and "…" in bloque and "larguísimo " * 10 not in bloque,
              "el objeto largo no se corta")
    comprobar(app.fmt_eur("250000.5") in bloque and "sin IVA" in bloque, "falta el importe sin IVA")
    comprobar(bloque.count('<span class="emp-imp">') == 2, "una licitación sin importe pinta importe")
    comprobar(f"plazo hasta el {app._conv_fecha(f(2, 1))[:10]} ({app._conv_dias(f(2, 1))})" in bloque,
              "falta el plazo de L4")
    comprobar('target="_blank" rel="noopener"' in bloque, "los enlaces externos no abren aparte")
    # 4. Botones: principal siempre; el del aviso, solo con FILTRO_FORMULARIO.
    comprobar('href="/convocatorias" data-dp-evento="portada_licitaciones"' in bloque, "falta el botón principal")
    comprobar("data-dp-evento=\"portada_aviso\"" not in h and app.FFORM.RUTA not in h,
              "con el filtro apagado sale el botón del aviso o un enlace al formulario")
    app.FILTRO_FORMULARIO = True
    h_on = cuerpo(portada())
    comprobar(f'href="{app.FFORM.RUTA}" data-dp-evento="portada_aviso"' in h_on, "encendido no sale el botón del aviso")
    comprobar("Te decimos cuáles encajan con tu empresa." in h_on and "Míralas todas" not in h_on,
              "encendido: el texto no es «Te decimos cuáles encajan»")
    h_on_gl = cuerpo(portada("gl"))
    comprobar("Dicímosche cales encaixan" in h_on_gl, "encendido en gallego: falta el texto traducido")
    app.FILTRO_FORMULARIO = False
    # 5. Singular con una sola abierta y caché de 5 minutos.
    with app._db_lock:
        app._db.execute("UPDATE licitaciones SET estado='ADJ' WHERE id IN ('L2','L3','L4','L5','L6')")
        app._db.commit()
    app._portada_empresas_cache.update(ts=0.0, datos=None)
    comprobar("Hoy hay 1 licitación pública abierta." in app._portada_empresas_html(), "falta el singular")
    with app._db_lock:
        app._db.execute("UPDATE licitaciones SET estado='PUB' WHERE id IN ('L2','L3','L4','L5','L6')")
        app._db.commit()
    comprobar("Hoy hay 1 licitación" in app._portada_empresas_html(), "la caché no guarda los datos")
    app._portada_empresas_cache["ts"] -= app._PORTADA_EMPRESAS_TTL + 1
    comprobar("<b>6</b>" in app._portada_empresas_html(), "pasado el tiempo de caché no se recalcula")
    # 6. La banda «¿Cuál es tu municipio?» va debajo del titular y antes del buscador.
    i_tag, i_banda, i_busc = h.find('class="hero-tagline"'), h.find('id="personaliza-banner"'), h.find('id="adv-search"')
    comprobar(i_hero < i_tag < i_banda < i_busc, "la banda del municipio no va entre el titular y el buscador")
    comprobar(h.count('id="personaliza-banner"') == 1, "la banda del municipio sale más de una vez")
    # 7. Verde: cuadros de convocatorias y botón del menú.
    comprobar('class="stat stat-enlace stat-conv" href="/convocatorias"' in h, "el cuadro de licitaciones no es verde")
    comprobar('class="stat stat-enlace stat-conv" href="/convocatorias?tab=subvenciones"' in h,
              "el cuadro de subvenciones no es verde")
    comprobar(h.count("stat-conv") == 2, "hay otros cuadros en verde")
    comprobar('<a href="/convocatorias" class="nav-conv">' in h, "el botón del menú no es verde")
    css = app._ALL_CSS_CONTENT
    comprobar(".header-nav>a.nav-conv{" in css and ".emp-bloque{" in css and "--conv:#0d7a3f" in css, "falta el CSS")
    movil = css[css.index("@media (max-width:700px){\n  .emp-bloque{"):]
    movil = movil[:movil.index("\n}")]
    comprobar(".emp-ultimas li:nth-child(n+3){display:none;}" in movil, "en el móvil no se quedan 2 licitaciones")
    # 8. Idiomas: los textos nuevos traducidos (y nada en castellano dentro del bloque).
    for idioma, esperado, frase in (("gl", "Hoxe hai <b>6</b> licitacións públicas abertas.", "Aquí podes velas todas"),
                                    ("ca", "Avui hi ha <b>6</b> licitacions públiques obertes.", "Mira-les totes aquí"),
                                    ("eu", "Gaur <b>6</b> lizitazio publiko daude irekita.", "Ikusi hemen guztiak")):
        hb = cuerpo(portada(idioma))
        bl = hb[hb.find('class="emp-bloque"'):hb.find('class="hero-panel"')]
        comprobar(esperado in bl, f"{idioma}: falta el título traducido")
        comprobar(frase in bl, f"{idioma}: falta el texto traducido (filtro apagado)")
        cierran = {"gl": "Pechan pronto", "ca": "Tanquen aviat", "eu": "Laster ixten dira"}[idioma]
        comprobar(f'<div class="emp-ultimas-tit">{cierran}</div>' in bl, f"{idioma}: falta «Cierran pronto» traducido")
        comprobar("Ver las licitaciones abiertas" not in bl and "Cierran pronto" not in bl
                  and "Míralas" not in bl and "plazo hasta" not in bl, f"{idioma}: queda castellano en el bloque")

    # 9. Contador: los dos botones cuentan; un nombre inventado no; y salen en el panel de visitas.
    def evento(tipo, ua=UA):
        c = tipo.encode()
        env = {"REQUEST_METHOD": "POST", "PATH_INFO": "/api/evento", "QUERY_STRING": "", "HTTP_USER_AGENT": ua,
               "HTTP_X_FORWARDED_FOR": IP, "CONTENT_LENGTH": str(len(c)), "wsgi.input": io.BytesIO(c)}
        estado = []
        app.app(env, lambda s, hh, e=None: estado.append(s))
        return estado[0][:3]

    def contados(nombre):
        with app._visitas_lock:
            return sum(v[0] for (d, cl, n), v in app._visitas_pend.items() if cl == "evento" and n == nombre)

    for _ in range(3):
        evento("portada_licitaciones")
    evento("portada_aviso")
    comprobar(evento("portada_inventado") == "204", "un evento desconocido no responde 204")
    evento("portada_licitaciones", ua="curl/8.0")
    comprobar(contados("clic_portada_licitaciones") == 3, f"clics principal: {contados('clic_portada_licitaciones')}")
    comprobar(contados("clic_portada_aviso") == 1, f"clics aviso: {contados('clic_portada_aviso')}")
    comprobar(contados("portada_inventado") == 0 and contados("clic_portada_inventado") == 0, "cuenta un evento inventado")
    _c, _h, b = app._visitas_pagina({"dias": ["7"]}, autorizado=True)
    pag = b.decode("utf-8") if isinstance(b, bytes) else str(b)
    comprobar("Portada: clics en el bloque para empresas" in pag, "falta la tabla de clics en el panel")
    comprobar(re.search(r"Ver las licitaciones abiertas»</td><td>3</td><td>3</td>", pag) is not None,
              "el panel no da 3 clics al botón principal")
    comprobar(re.search(r"Avisarme de las de mi sector»</td><td>1</td><td>1</td>", pag) is not None,
              "el panel no da 1 clic al botón del aviso")
    # 10. Sin datos personales: el contador no guarda la IP.
    with app._visitas_lock:
        comprobar(IP not in repr(app._visitas_pend), "la IP aparece en el contador")

    print(f"{bien[0]} bien, {len(mal)} mal")
    for m in mal:
        print("  MAL:", m)
    sys.exit(1 if mal else 0)


if __name__ == "__main__":
    main()
