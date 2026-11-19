# encoding: utf-8
"""
Perfiles del filtro de licitaciones por empresa (2026-10-28, encargo de César): almacén y reglas. La web (app.py) pone
las páginas y envía los correos por Resend; los textos están en filtro_formulario.py y aquí vive todo lo que toca a
los datos guardados.

Los datos van en un fichero PROPIO (socios.db, en DATA_DIR: /var/data en Render), nunca en el repositorio ni en
cache.db (que se descarga en GitHub Actions y se copia a otro repositorio). La copia de socios.db va cifrada (flujo
copia-socios-cifrada.yml, igual que la de alertas.db).

Qué se guarda de cada empresa (decisión de César del 28-10: solo lo necesario):
  - el correo;
  - el perfil del formulario (sector, provincias, plantilla, tramo de facturación, clasificación, certificados, año
    de constitución, tipo de contrato, experiencia con la Administración, UTE). Son datos de la empresa, no de una
    persona; el formulario no pide nombre ni teléfono;
  - la fecha de alta y la de último uso, y la de confirmación (prueba del consentimiento, art. 7.1 RGPD);
  - las fechas que necesita el envío: hasta cuándo se le ha revisado (revisado), el último correo semanal, el último
    intento fallido y cuándo se le avisó de que su perfil iba a borrarse.
  Mientras se espera a que confirme un cambio, el perfil nuevo va aparte (perfil_pendiente) y se descarta a los 7 días.
  - pagado_hasta (31-10, decisión del titular): hasta cuándo ha pagado el servicio, y nada más del pago. Los datos de
    facturación van FUERA de socios.db. La pone o la quita el titular desde el admin (POST /admin/socios-pagado, con el
    token en la cabecera).
  - condiciones_aceptadas y condiciones_version (04-11): cuándo marcó la casilla «He leído y acepto las condiciones de
    contratación y la política de privacidad» y qué versión de esos textos aceptó (filtro_formulario.CONDICIONES_VERSION).
    Sin aceptación no se guarda nada. En un alta (o un alta aún sin confirmar) se apuntan al enviar el formulario; en
    un cambio de un perfil ya confirmado, al confirmar el cambio desde el correo (así nadie cambia la aceptación de otra
    empresa escribiendo su correo). Nada más: ni IP ni otros datos.
  Ni IP, ni nombre, ni teléfono. De los correos enviados queda solo la fila de envios (cuándo, qué clase, código de
  Resend), que sirve para no reenviar en bucle y para el cupo; al borrar el perfil se queda sin saber de quién era.

Reglas:
  - Un perfil no existe hasta que se confirma desde el correo (doble confirmación). Los perfiles sin confirmar se
    BORRAN a los 7 días.
  - Un cambio en un perfil ya confirmado tampoco vale hasta que se confirma desde el correo: así nadie puede cambiar el
    perfil de otra empresa escribiendo su correo en el formulario.
  - Baja = borrar la fila entera, no marcarla. Hay enlace de baja en todos los correos.
  - Último uso = la última vez que la empresa hizo algo con su perfil: confirmarlo, confirmar un cambio, abrir sus
    licitaciones desde el enlace del correo o pulsar «mantener mi perfil». Recibir los correos no cuenta.
  - Borrado por falta de uso (cambio de César del 28-10): a los 11 meses sin uso se manda un correo «¿Sigues
    interesado?» con un enlace para mantener el perfil; si no lo pulsa, se BORRA 30 días después del aviso (a los 12
    meses). Si el aviso no ha podido salir (cupo, fallo de Resend), se borra igual a los 13 meses: nunca se guarda más.
  - Correo semanal: solo las licitaciones NUEVAS desde el correo anterior. "Nueva" = vista por primera vez después de
    la última revisión de ese perfil (tabla vistos, una sola lista para todos, sin datos de nadie). La primera vez que
    se registra la lista todo queda como "ya estaba"; al confirmar un perfil, lo que hay en ese momento también.
  - Pago (31-10, decisiones del titular):
    * El correo semanal solo sale a quien tiene el pago vigente o está en los 7 días de cortesía después de que venza
      (CORTESIA_S). Sin pagado_hasta (nunca ha pagado ni tiene prueba) no recibe el semanal. La prueba gratis es poner
      pagado_hasta a mano.
    * Avisos de vencimiento: uno 15 días antes (solo si la pasada llega en los 3 primeros días de esa ventana: con un
      pago o una prueba de menos de 12 días no sale) y otro el día que vence (hasta que acaba la cortesía, si la pasada
      no pudo antes). aviso_pago guarda cuándo salió el último: al poner una fecha nueva, los umbrales cambian solos.
    * Al vencer, el perfil se CONSERVA para que pueda renovar sin rellenarlo otra vez, con las reglas de borrado de
      siempre contadas desde la fecha mayor entre el último uso y el fin del pago: aviso «¿Sigues interesado?» a los
      11 meses, borrado 30 días después si no lo pulsa, o a los 13 meses si el aviso no pudo salir.
    * Poner la fecha anula un aviso de inactividad ya enviado. Quitarla termina el servicio en el acto, sin cortesía y
      sin avisos (la fecha queda 7 días atrás, no en blanco, para no borrar a nadie de golpe sin aviso).
    * El pago NO salta el plazo de 7 días sin confirmar ni SOCIOS_SOLO_CORREOS, y la baja de un clic lo borra todo.
  - Los enlaces van firmados con una clave que se genera sola y vive en socios.db: no hay ningún secreto que configurar.
"""
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
import time

PENDIENTE_CADUCA_S = 7 * 86400
INACTIVO_AVISO_S = 335 * 86400       # sin uso: aviso «¿Sigues interesado?» (un mes antes de los 12 meses)
AVISO_PLAZO_S = 30 * 86400           # tras el aviso, si no pulsa, se borra
INACTIVO_MAXIMO_S = 395 * 86400      # sin uso: se borra aunque el aviso no haya podido salir
PAGADO_MAXIMO_S = 5 * 366 * 86400    # una fecha de pago a más de 5 años vista es una errata
CORTESIA_S = 7 * 86400               # tras vencer el pago, 7 días más de correo semanal
AVISO_PAGO_ANTES_S = 15 * 86400      # aviso de vencimiento 15 días antes...
AVISO_PAGO_VENTANA_S = 3 * 86400     # ...si la pasada llega en los 3 primeros días de esa ventana
VISTOS_CADUCAN_S = 400 * 86400
REENVIO_ESPERA_S = 600               # no se repite un correo de confirmación al mismo perfil antes de 10 min
ALTAS_MAX_HORA = 30                  # tope de correos de confirmación por hora (formulario público)
ENVIOS_CADUCAN_S = 90 * 86400
_RE_CORREO = re.compile(r"[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]{1,63}(?:\.[A-Za-z0-9\-]{1,63})+")
_CAMPOS = ("id", "correo", "perfil", "estado", "alta", "confirmado", "ultimo_uso", "perfil_pendiente", "pendiente_desde",
           "revisado", "ultimo_envio", "intentado", "aviso_inactividad", "pagado_hasta", "aviso_pago",
           "condiciones_aceptadas", "condiciones_version")
_USO = "coalesce(ultimo_uso, confirmado, alta)"
_SIN_PAGO = "coalesce(pagado_hasta, 0) <= ?"          # ? = ahora: no hay pago vigente
_USO_O_PAGO = f"max({_USO}, coalesce(pagado_hasta, 0))"  # el último uso o el fin del pago, lo más tarde
_RECIBE = f"coalesce(pagado_hasta, 0) + {CORTESIA_S} > ?"  # ? = ahora: pago vigente o en la cortesía

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS ajustes (clave TEXT PRIMARY KEY, valor TEXT);
CREATE TABLE IF NOT EXISTS perfiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT, correo TEXT NOT NULL UNIQUE, perfil TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendiente', alta REAL NOT NULL, confirmado REAL, ultimo_uso REAL,
    perfil_pendiente TEXT, pendiente_desde REAL, revisado REAL, ultimo_envio REAL, intentado REAL,
    aviso_inactividad REAL, pagado_hasta REAL, aviso_pago REAL, condiciones_aceptadas REAL, condiciones_version TEXT);
CREATE TABLE IF NOT EXISTS vistos (item TEXT PRIMARY KEY, primera_vez REAL NOT NULL) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS envios (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, clase TEXT NOT NULL, perfil_id INTEGER,
    codigo INTEGER, detalle TEXT);
CREATE INDEX IF NOT EXISTS idx_envios_ts ON envios (ts);
"""


def correo_valido(correo):
    correo = (correo or "").strip().lower()
    return correo if len(correo) <= 120 and _RE_CORREO.fullmatch(correo) else ""


def correo_tapado(correo):
    usuario, _, dominio = (correo or "").partition("@")
    return f"{usuario[:2]}***@{dominio}" if dominio else ""


def _json(perfil):
    return json.dumps(perfil, ensure_ascii=False, sort_keys=True)


def huella(perfil_json):
    """Resumen corto del perfil que se confirma: un enlace de confirmación solo vale para ESE perfil."""
    return hashlib.sha256((perfil_json or "").encode("utf-8")).hexdigest()[:16]


class Almacen:
    def __init__(self, ruta):
        self.ruta = ruta
        self.lock = threading.RLock()
        self.db = sqlite3.connect(ruta, check_same_thread=False, timeout=30)
        with self.lock:
            self.db.executescript(_ESQUEMA)
            columnas = {f[1] for f in self.db.execute("PRAGMA table_info(perfiles)")}
            for col, tipo in (("pagado_hasta", "REAL"), ("aviso_pago", "REAL"),             # socios.db de antes del 31-10
                              ("condiciones_aceptadas", "REAL"), ("condiciones_version", "TEXT")):   # y del 04-11
                if col not in columnas:
                    self.db.execute(f"ALTER TABLE perfiles ADD COLUMN {col} {tipo}")
            if not self._ajuste("clave_firma"):
                self.db.execute("INSERT INTO ajustes VALUES ('clave_firma', ?)", (secrets.token_hex(32),))
            self.db.commit()
        self._clave = self._ajuste("clave_firma").encode()

    # ── utilidades ──────────────────────────────────────────────────────────────────────────────────────────────
    def _ajuste(self, clave):
        fila = self.db.execute("SELECT valor FROM ajustes WHERE clave=?", (clave,)).fetchone()
        return fila[0] if fila else ""

    def _sumar(self, clave, n=1):
        self.db.execute("INSERT INTO ajustes VALUES (?, ?) ON CONFLICT(clave) DO UPDATE SET "
                        "valor = CAST(valor AS INTEGER) + ?", (clave, str(n), n))

    def firma(self, accion, identificador, extra=""):
        return hmac.new(self._clave, f"{accion}|{int(identificador)}|{extra}".encode(), hashlib.sha256).hexdigest()[:32]

    def firma_valida(self, accion, identificador, firma, extra=""):
        try:
            return hmac.compare_digest((firma or "").encode(), self.firma(accion, identificador, extra).encode())
        except (TypeError, ValueError):
            return False

    def _fila(self, donde, valor):
        f = self.db.execute(f"SELECT {', '.join(_CAMPOS)} FROM perfiles WHERE {donde}=?", (valor,)).fetchone()
        if not f:
            return None
        d = dict(zip(_CAMPOS, f))
        d["perfil_json"], d["perfil"] = d["perfil"], json.loads(d["perfil"])
        d["pendiente_json"] = d["perfil_pendiente"]
        d["perfil_pendiente"] = json.loads(d["perfil_pendiente"]) if d["perfil_pendiente"] else None
        return d

    def perfil(self, pid):
        with self.lock:
            return self._fila("id", pid)

    def por_correo(self, correo):
        with self.lock:
            return self._fila("correo", correo_valido(correo))

    def a_confirmar(self, p):
        """El perfil que confirmaría un enlace de confirmación de esa fila: el nuevo si es un alta, el cambio
        pendiente si ya estaba confirmado. "" si no hay nada que confirmar."""
        if p["estado"] == "pendiente":
            return p["perfil_json"]
        return p["pendiente_json"] or ""

    # ── alta, confirmación y baja ───────────────────────────────────────────────────────────────────────────────
    def alta(self, correo, perfil, ahora=None, condiciones=""):
        """Guarda lo enviado por el formulario, SIN dar de alta todavía. Devuelve {"resultado", "perfil"}; resultado:
             confirmar  -> hay que mandar el correo de confirmación (alta nueva o cambio de un perfil ya confirmado)
             espera     -> se le acaba de escribir (o hay demasiadas altas en esta hora): no se manda nada
             invalido   -> el correo no vale
             sin_condiciones -> no se han aceptado las condiciones (`condiciones`: la versión aceptada): no se guarda nada
           La página responde siempre lo mismo ("revisa tu correo"): así no se puede averiguar desde fuera si una
           dirección está dada de alta."""
        ahora = ahora or time.time()
        correo = correo_valido(correo)
        if not correo:
            return {"resultado": "invalido"}
        condiciones = (condiciones or "").strip()[:60]
        if not condiciones:
            return {"resultado": "sin_condiciones"}
        pj = _json(perfil)
        with self.lock:
            p = self._fila("correo", correo)
            if p:
                ultimo = self.db.execute("SELECT max(ts) FROM envios WHERE perfil_id=? AND clase='confirmacion'",
                                         (p["id"],)).fetchone()[0]
                if ultimo and ahora - ultimo < REENVIO_ESPERA_S:
                    return {"resultado": "espera", "perfil": p}
            recientes = self.db.execute("SELECT count(*) FROM envios WHERE clase='confirmacion' AND ts > ?",
                                        (ahora - 3600,)).fetchone()[0]
            if recientes >= ALTAS_MAX_HORA:
                return {"resultado": "espera", "perfil": p}
            if not p:
                self.db.execute("INSERT INTO perfiles (correo, perfil, alta, condiciones_aceptadas, condiciones_version) "
                                "VALUES (?,?,?,?,?)", (correo, pj, ahora, ahora, condiciones))
            elif p["estado"] == "pendiente":
                # Sin confirmar: lo último que envía sustituye a lo anterior y el plazo de 7 días vuelve a empezar.
                self.db.execute("UPDATE perfiles SET perfil=?, alta=?, condiciones_aceptadas=?, condiciones_version=? "
                                "WHERE id=?", (pj, ahora, ahora, condiciones, p["id"]))
            else:
                # Ya confirmado: el cambio espera aparte hasta que se confirme; el perfil de ahora no se toca.
                self.db.execute("UPDATE perfiles SET perfil_pendiente=?, pendiente_desde=? WHERE id=?",
                                (pj, ahora, p["id"]))
            self.db.commit()
            return {"resultado": "confirmar", "perfil": self._fila("correo", correo)}

    def confirmar(self, pid, firma, ahora=None, condiciones=""):
        """Da de alta el perfil, o aplica el cambio pendiente, si la firma corresponde a ESE perfil. Devuelve la fila
        (con "ya_estaba" si ese enlace ya se había usado) o None si el enlace no vale o ha caducado. Al aplicar un
        cambio, `condiciones` (la versión aceptada en el formulario del cambio) pasa a ser la aceptación del perfil."""
        ahora = ahora or time.time()
        with self.lock:
            p = self._fila("id", pid)
            if not p:
                return None
            objetivo = self.a_confirmar(p)
            if not (objetivo and self.firma_valida("confirmar", pid, firma, huella(objetivo))):
                # Un enlace ya usado (el perfil que confirmaba es el de ahora) no da error: dice que ya estaba.
                if p["estado"] == "activo" and self.firma_valida("confirmar", pid, firma, huella(p["perfil_json"])):
                    return dict(p, ya_estaba=True)
                return None
            if p["estado"] == "pendiente":
                self.db.execute("UPDATE perfiles SET estado='activo', confirmado=?, ultimo_uso=?, revisado=? WHERE id=?",
                                (ahora, ahora, ahora, pid))
                self._sumar("altas")
            else:
                self.db.execute("UPDATE perfiles SET perfil=perfil_pendiente, perfil_pendiente=NULL, pendiente_desde=NULL, "
                                "confirmado=?, ultimo_uso=?, aviso_inactividad=NULL WHERE id=?", (ahora, ahora, pid))
                if condiciones:
                    self.db.execute("UPDATE perfiles SET condiciones_aceptadas=?, condiciones_version=? WHERE id=?",
                                    (ahora, condiciones.strip()[:60], pid))
                self._sumar("cambios")
            self.db.commit()
            return self._fila("id", pid)

    def usar(self, pid, ahora=None):
        """La empresa ha abierto sus licitaciones o ha pulsado «mantener mi perfil»: cuenta como uso y anula el aviso de
        borrado. Devuelve True si el perfil existe y está confirmado."""
        with self.lock:
            n = self.db.execute("UPDATE perfiles SET ultimo_uso=?, aviso_inactividad=NULL WHERE id=? AND estado='activo'",
                                (ahora or time.time(), pid)).rowcount
            self.db.commit()
        return bool(n)

    def poner_pagado(self, pid, hasta, ahora=None):
        """Pago hasta `hasta` (segundos; el final del último día pagado). Solo perfiles confirmados y con una fecha
        futura de menos de 5 años. Anula el aviso de inactividad ya enviado. Devuelve (fila, "") o (None, motivo):
        "no_existe", "sin_confirmar", "fecha"."""
        ahora = ahora or time.time()
        with self.lock:
            p = self._fila("id", pid)
            if not p:
                return None, "no_existe"
            if p["estado"] != "activo":
                return None, "sin_confirmar"
            if not (ahora < hasta <= ahora + PAGADO_MAXIMO_S):
                return None, "fecha"
            self.db.execute("UPDATE perfiles SET pagado_hasta=?, aviso_inactividad=NULL WHERE id=?", (hasta, pid))
            self._sumar("pagos_puestos")
            self.db.commit()
            return self._fila("id", pid), ""

    def quitar_pagado(self, pid, ahora=None):
        """El servicio termina AHORA, sin cortesía ni avisos: si el pago estaba vigente o en la cortesía, la fecha pasa a
        ser hace 7 días (así deja de recibir el semanal en el acto); si no, no cambia nada. Devuelve (fila, "") o
        (None, "no_existe")."""
        ahora = ahora or time.time()
        with self.lock:
            p = self._fila("id", pid)
            if not p:
                return None, "no_existe"
            if p["pagado_hasta"] and p["pagado_hasta"] + CORTESIA_S > ahora:
                self.db.execute("UPDATE perfiles SET pagado_hasta=?, aviso_pago=? WHERE id=?",
                                (ahora - CORTESIA_S, ahora, pid))
                self._sumar("pagos_quitados")
                self.db.commit()
            return self._fila("id", pid), ""

    def pago_vigente(self, p, ahora=None):
        return bool(p and p.get("pagado_hasta") and p["pagado_hasta"] > (ahora or time.time()))

    @staticmethod
    def estado_pago(p, ahora=None):
        """"vigente", "cortesia" (vencido hace menos de 7 días: sigue recibiendo el semanal), "vencido" o "sin_pago"."""
        fin, ahora = (p or {}).get("pagado_hasta"), ahora or time.time()
        if not fin:
            return "sin_pago"
        return "vigente" if fin > ahora else ("cortesia" if fin + CORTESIA_S > ahora else "vencido")

    def recibe_semanal(self, p, ahora=None):
        return self.estado_pago(p, ahora) in ("vigente", "cortesia")

    def baja(self, pid, motivo="baja"):
        """BORRA el perfil entero (no lo marca). De los envíos queda la fila sin saber de quién era."""
        with self.lock:
            n = self.db.execute("DELETE FROM perfiles WHERE id=?", (pid,)).rowcount
            self.db.execute("UPDATE envios SET perfil_id=NULL WHERE perfil_id=?", (pid,))
            if n:
                self._sumar("bajas_" + motivo)
            self.db.commit()
        return bool(n)

    def limpiar(self, ahora=None):
        """Borra los perfiles sin confirmar de hace más de 7 días y los confirmados sin uso a los que se avisó hace 30
        días o más (o, sin aviso, con 13 meses sin uso desde el último uso o el fin del pago), nunca uno con el pago
        vigente; descarta los cambios sin confirmar de hace más de 7 días, los
        envíos de hace más de 90 y los vistos de hace más de 400. Devuelve los recuentos."""
        ahora = ahora or time.time()
        with self.lock:
            viejos = [f[0] for f in self.db.execute(
                f"SELECT id FROM perfiles WHERE (estado='pendiente' AND alta < ?) "
                f"OR (estado='activo' AND {_SIN_PAGO} AND aviso_inactividad IS NOT NULL AND aviso_inactividad <= ?) "
                f"OR (estado='activo' AND {_SIN_PAGO} AND {_USO_O_PAGO} < ?)",
                (ahora - PENDIENTE_CADUCA_S, ahora, ahora - AVISO_PLAZO_S, ahora, ahora - INACTIVO_MAXIMO_S))]
            sin_confirmar = inactivos = 0
            for pid in viejos:
                estado = self.db.execute("SELECT estado FROM perfiles WHERE id=?", (pid,)).fetchone()[0]
                self.db.execute("DELETE FROM perfiles WHERE id=?", (pid,))
                self.db.execute("UPDATE envios SET perfil_id=NULL WHERE perfil_id=?", (pid,))
                if estado == "pendiente":
                    sin_confirmar += 1
                else:
                    inactivos += 1
            cambios = self.db.execute("UPDATE perfiles SET perfil_pendiente=NULL, pendiente_desde=NULL "
                                      "WHERE pendiente_desde < ?", (ahora - PENDIENTE_CADUCA_S,)).rowcount
            self.db.execute("DELETE FROM envios WHERE ts < ?", (ahora - ENVIOS_CADUCAN_S,))
            self.db.execute("DELETE FROM vistos WHERE primera_vez > 0 AND primera_vez < ?", (ahora - VISTOS_CADUCAN_S,))
            if sin_confirmar:
                self._sumar("caducados_sin_confirmar", sin_confirmar)
            if inactivos:
                self._sumar("caducados_inactivos", inactivos)
            self.db.commit()
        return {"sin_confirmar": sin_confirmar, "inactivos": inactivos, "cambios_descartados": cambios}

    # ── novedades ───────────────────────────────────────────────────────────────────────────────────────────────
    def registrar_vistos(self, items, ahora):
        """Apunta las licitaciones abiertas de ahora. La primera vez queda todo como "ya estaba" (primera_vez = 0)."""
        with self.lock:
            sembrada = bool(self._ajuste("vistos_sembrado"))
            marca = ahora if sembrada else 0
            self.db.executemany("INSERT OR IGNORE INTO vistos VALUES (?,?)", ((str(i), marca) for i in items))
            if not sembrada:
                self.db.execute("INSERT INTO ajustes VALUES ('vistos_sembrado', ?)", (str(ahora),))
            self.db.commit()

    def nuevos_desde(self, desde):
        with self.lock:
            return {f[0] for f in self.db.execute("SELECT item FROM vistos WHERE primera_vez > ?", (desde or 0,))}

    # ── pasada de envío ─────────────────────────────────────────────────────────────────────────────────────────
    def pendientes_aviso(self, ahora, inicio_dia):
        """Perfiles a los que toca el aviso «¿Sigues interesado?» (11 meses sin uso, contados desde el último uso o el
        fin del pago, y aún sin avisar), los que llevan
        más tiempo sin uso primero; nunca a uno con el pago vigente. Uno que ya se ha intentado hoy (envío fallido) no vuelve a salir hasta mañana."""
        with self.lock:
            filas = self.db.execute(
                f"SELECT id FROM perfiles WHERE estado='activo' AND aviso_inactividad IS NULL AND {_USO_O_PAGO} < ? "
                f"AND {_SIN_PAGO} AND coalesce(intentado, 0) < ? ORDER BY {_USO_O_PAGO}, id",
                (ahora - INACTIVO_AVISO_S, ahora, inicio_dia)).fetchall()
            return [self._fila("id", f[0]) for f in filas]

    def pendientes_semanal(self, inicio_semana, inicio_dia, ahora=None):
        """Perfiles confirmados CON PAGO VIGENTE O EN LA CORTESÍA sin revisar desde el lunes de esta semana, los que más
        llevan esperando primero. A los demás no se les toca nada: si renuevan, el correo siguiente trae lo nuevo desde
        su última revisión que siga abierto."""
        with self.lock:
            filas = self.db.execute(
                f"SELECT id FROM perfiles WHERE estado='activo' AND {_RECIBE} AND coalesce(revisado, confirmado, 0) < ? "
                "AND coalesce(intentado, 0) < ? ORDER BY coalesce(revisado, confirmado, 0), id",
                (ahora or time.time(), inicio_semana, inicio_dia)).fetchall()
            return [self._fila("id", f[0]) for f in filas]

    def marcar_revisado(self, pid, ahora, enviado):
        """Revisado hasta `ahora` (con correo o sin novedades): lo visto hasta aquí ya no vuelve a salir."""
        with self.lock:
            self.db.execute("UPDATE perfiles SET revisado=?, intentado=?, ultimo_envio=coalesce(?, ultimo_envio) WHERE id=?",
                            (ahora, ahora, ahora if enviado else None, pid))
            self.db.commit()

    def marcar_intentado(self, pid, ahora):
        """Envío fallido: no se marca como revisado (mañana se vuelve a intentar, con lo nuevo que haya entonces)."""
        with self.lock:
            self.db.execute("UPDATE perfiles SET intentado=? WHERE id=?", (ahora, pid))
            self.db.commit()

    def pendientes_aviso_pago(self, ahora, inicio_dia):
        """[(perfil, "antes" | "vence")]: a quién toca hoy un aviso de vencimiento. «vence» desde el comienzo del último
        día pagado hasta que acaba la cortesía; «antes», 15 días antes, si la pasada llega en los 3 primeros días de esa
        ventana. Cada uno sale una sola vez por fecha de pago (aviso_pago). Uno con un envío fallido hoy espera a mañana."""
        with self.lock:
            filas = self.db.execute(
                f"SELECT id FROM perfiles WHERE estado='activo' AND pagado_hasta IS NOT NULL AND {_RECIBE} "
                "AND coalesce(intentado, 0) < ? ORDER BY pagado_hasta, id", (ahora, inicio_dia)).fetchall()
            out = []
            for (pid,) in filas:
                p = self._fila("id", pid)
                clase = self.aviso_pago_toca(p, ahora)
                if clase:
                    out.append((p, clase))
            return out

    @staticmethod
    def aviso_pago_toca(p, ahora):
        fin, avisado = p["pagado_hasta"], p.get("aviso_pago") or 0
        if not fin or ahora >= fin + CORTESIA_S:
            return ""
        dia_vence = fin - 86400 + 1                                       # 00:00 del último día pagado
        if ahora >= dia_vence:
            return "vence" if avisado < dia_vence else ""
        antes = dia_vence - AVISO_PAGO_ANTES_S                         # 00:00 de 15 días antes de ese día
        if antes <= ahora < antes + AVISO_PAGO_VENTANA_S and avisado < antes:
            return "antes"
        return ""

    def marcar_aviso_pago(self, pid, ahora):
        """Aviso de vencimiento enviado. También marca «intentado hoy» (como marcar_aviso): ese día ya no recibe el
        correo semanal en ninguna tanda; le llega en la pasada del día siguiente (arreglo del 04-11)."""
        with self.lock:
            self.db.execute("UPDATE perfiles SET aviso_pago=?, intentado=? WHERE id=?", (ahora, ahora, pid))
            self.db.commit()

    def marcar_aviso(self, pid, ahora):
        with self.lock:
            self.db.execute("UPDATE perfiles SET aviso_inactividad=?, intentado=? WHERE id=?", (ahora, ahora, pid))
            self.db.commit()

    # ── correos ─────────────────────────────────────────────────────────────────────────────────────────────────
    def registrar_envio(self, clase, pid, codigo, detalle, ahora=None):
        with self.lock:
            self.db.execute("INSERT INTO envios (ts, clase, perfil_id, codigo, detalle) VALUES (?,?,?,?,?)",
                            (ahora or time.time(), clase, pid, codigo, (detalle or "")[:300]))
            self.db.commit()

    def envios_desde(self, desde):
        """Correos que Resend aceptó desde `desde` (cuentan para el cupo, que es el mismo que el de las alertas)."""
        with self.lock:
            return self.db.execute("SELECT count(*) FROM envios WHERE ts >= ? AND codigo BETWEEN 200 AND 299",
                                   (desde,)).fetchone()[0]

    # ── panel ───────────────────────────────────────────────────────────────────────────────────────────────────
    def resumen(self):
        with self.lock:
            q = lambda sql, *a: self.db.execute(sql, a).fetchone()[0]      # noqa: E731
            return {
                "activos": q("SELECT count(*) FROM perfiles WHERE estado='activo'"),
                "sin_confirmar": q("SELECT count(*) FROM perfiles WHERE estado='pendiente'"),
                "cambios_pendientes": q("SELECT count(*) FROM perfiles WHERE perfil_pendiente IS NOT NULL"),
                "bajas": int(self._ajuste("bajas_baja") or 0),
                "bajas_desde_el_panel": int(self._ajuste("bajas_panel") or 0),
                "caducados_sin_confirmar": int(self._ajuste("caducados_sin_confirmar") or 0),
                "caducados_inactivos": int(self._ajuste("caducados_inactivos") or 0),
                "avisados_inactividad": q("SELECT count(*) FROM perfiles WHERE aviso_inactividad IS NOT NULL"),
                "con_pago_vigente": q("SELECT count(*) FROM perfiles WHERE pagado_hasta > ?", time.time()),
                "en_cortesia": q("SELECT count(*) FROM perfiles WHERE pagado_hasta <= ? AND pagado_hasta + ? > ?",
                                 time.time(), CORTESIA_S, time.time()),
            }

    def lista(self, limite=500):
        with self.lock:
            filas = self.db.execute("SELECT id FROM perfiles ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
            return [self._fila("id", f[0]) for f in filas]

    def lista_envios(self, limite=100):
        with self.lock:
            filas = self.db.execute("SELECT ts, clase, codigo, detalle FROM envios ORDER BY id DESC LIMIT ?",
                                    (limite,)).fetchall()
        return [dict(zip(("ts", "clase", "codigo", "detalle"), f)) for f in filas]

    def copia(self):
        """Bytes de una copia íntegra del fichero (para la copia cifrada)."""
        with self.lock:
            self.db.commit()
            return self.db.serialize()
