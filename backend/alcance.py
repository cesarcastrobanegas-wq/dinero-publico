# encoding: utf-8
"""
Alcance temporal del proyecto: los ÚLTIMOS 5 AÑOS, como ventana MÓVIL (decisión de César, 2026-10-10).

El corte ya no es la constante "2021-09-01": se calcula solo -- hoy menos 5 años, llevado al día 1 de ese mes -- y lo
usan por igual la web (app.py) y todos los generadores de datos, que antes llevaban cada uno su copia de la constante
("mantener sincronizado a mano").

Qué significa el corte:
  - Se aplica a lo que ENTRA NUEVO, en todas las fuentes: un contrato anterior al corte ya no se incorpora.
  - Lo ya guardado NO se archiva ni se borra por quedar fuera de la ventana, y se sigue mostrando en la web. Por eso
    el archivado automático que ya existía (contratos menores y formales de PSCP/Euskadi/Navarra anteriores a
    septiembre de 2021) sigue con su corte FIJO de entonces, ARCHIVO_HASTA: al moverse la ventana no archiva nada más.
  - El Índice de Transparencia se calcula solo con contratos dentro de la ventana.
  - Los fondos UE quedan FUERA de esta regla (decisión de César, 2026-10-10): sus operaciones son de periodos de
    programación largos (casi toda la de Cohesión empezó antes del corte) y no se recortan por fecha.

Sin dependencias: lo importan los scripts sueltos (`from alcance import ...`) y app.py.
"""
import datetime

ANIOS_ALCANCE = 5
ARCHIVO_HASTA = "2021-09-01"      # corte FIJO del archivado que se hizo el 2026-09-25/27; no se mueve nunca


def _dia_uno(hoy=None):
    hoy = hoy or datetime.date.today()
    return datetime.date(hoy.year - ANIOS_ALCANCE, hoy.month, 1)


def alcance_desde(hoy=None):
    """Primer día dentro de la ventana, "AAAA-MM-01" (el 10-10-2026 -> "2021-10-01")."""
    return _dia_uno(hoy).isoformat()


def alcance_mes(hoy=None):
    """Primer mes dentro de la ventana, "AAAAMM" (para los ZIP mensuales de PLACE)."""
    return _dia_uno(hoy).strftime("%Y%m")


def alcance_anio(hoy=None):
    """Año del corte (para las fuentes que solo permiten consultar o filtrar por año)."""
    return _dia_uno(hoy).year


def dentro_del_alcance(fecha, hoy=None):
    """¿Un contrato con esta fecha (ISO, "AAAA-MM-DD...") está dentro de la ventana? Sin fecha -> True: no se puede
    descartar lo que no se sabe cuándo fue."""
    fecha = (fecha or "")[:10]
    if fecha[:4] < "1990":            # sin fecha, o una fecha absurda en origen ("0026-09-01"): no se sabe cuándo fue
        return True
    return fecha >= alcance_desde(hoy)
