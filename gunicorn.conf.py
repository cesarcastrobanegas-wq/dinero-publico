"""Configuración de gunicorn. Se lee sola: gunicorn busca ./gunicorn.conf.py en el directorio desde el que arranca
(en Render, la raíz del repositorio). El resto de opciones siguen en el startCommand de render.yaml y en la variable
GUNICORN_CMD_ARGS del panel de Render (--preload).

Con --preload la app se importa una vez en el proceso maestro y cada trabajador es una copia hecha después. Los hilos
de fondo de la app (feed de menores, precálculo del Índice, directivos...) no pueden lanzarse al importar: se
quedarían en el maestro y el trabajador que atiende las peticiones no tendría ninguno (comprobado en producción el
2026-10-03 con /api/diagnostico-arranque). Por eso se avisa a la app de que no los lance al importar y se lanzan
aquí, en post_fork, dentro de cada trabajador."""
import os
import sys

# Antes de que gunicorn importe la app (este fichero se carga primero): la app no lanza sus hilos al importar.
os.environ["DINERO_HILOS_EN_POST_FORK"] = "1"


def post_fork(server, worker):
    # Con --preload la app ya está importada (como "backend.app") y el trabajador la hereda; sin --preload se importa
    # aquí mismo, ya dentro del trabajador.
    modulo = sys.modules.get("backend.app")
    if modulo is None:
        import backend.app as modulo
    modulo._tras_fork()
    server.log.info("post_fork: hilos de fondo lanzados en el trabajador %s", os.getpid())
