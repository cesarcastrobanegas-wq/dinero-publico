# encoding: utf-8
"""
Cuentas de usuario de los planes (2026-11-26, encargo de César): almacén y reglas. La web (app.py) pone las páginas
y envía los correos por Resend (los mismos de las alertas); aquí vive todo lo que toca a los datos guardados.

Los datos van en un fichero PROPIO (usuarios.db, en DATA_DIR: /var/data en Render), NUNCA en el repositorio ni en
cache.db (cache.db se descarga en GitHub Actions y se copia cada semana a otro repositorio; usuarios.db no sale del
disco de Render). Solo se abre con PLANES_ACTIVOS=1.

Qué se guarda de cada persona (RGPD, art. 5.1.c: lo mínimo):
  - el correo y un número interno (id);
  - la fecha de alta y la aceptación de las condiciones y de la privacidad, cada una con su fecha y la versión del
    texto aceptado (prueba del consentimiento, art. 7.1);
  - el plan, hasta cuándo está pagado y los identificadores de cliente y suscripción de Stripe (no la tarjeta: la
    tarjeta solo la ve Stripe);
  - los informes que se ha descargado (cuándo, de qué municipio o empresa) y sus favoritos.
  NADA de contraseña, teléfono, DNI ni dirección. Ni IP: los límites de intentos guardan una huella (HMAC con una
  clave que vive aquí) de la IP y del correo, y se borran a las 24 horas.
  La facturación (NIF, razón social) vendrá cuando haya empresa: el esquema está en ESQUEMA_FACTURACION pero la tabla
  no se crea salvo PLANES_FACTURACION=1 (apagada).

Reglas:
  - Sin contraseña: se entra con un enlace de UN solo uso que llega al correo y caduca a los 15 minutos. El enlace
    lleva un código aleatorio; aquí solo se guarda su huella (sha256), nunca el código.
  - Una cuenta no existe hasta que se pulsa el enlace del primer correo (doble confirmación). Las peticiones sin
    usar se borran solas.
  - Límite de intentos: como mucho 5 correos de acceso por dirección y hora, y 20 por IP y hora.
  - La sesión es una cookie con otro código aleatorio (aquí, su huella), de 30 días.
  - Borrar la cuenta (art. 17) BORRA la fila y todo lo suyo (sesiones, favoritos, descargas, enlaces). Se confirma
    con un enlace al correo. De los pagos queda solo la línea contable (fecha, importe, plan, código del evento de
    Stripe), sin el número de usuario: la ley obliga a guardar la facturación (en Stripe queda la suya).
  - Mes de los informes: empieza el día del mes en que se dio de alta (si el mes no tiene ese día, el último).
  - Bono: 5 informes que valen 12 meses desde la compra; se gastan solo cuando ya no quedan del mes.
"""
import calendar
import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone

try:
    from . import planes as PL
except ImportError:
    import planes as PL

ENLACE_CADUCA_S = 15 * 60
SESION_DURA_S = 30 * 86400
INTENTOS_CORREO_HORA = 5
INTENTOS_IP_HORA = 20
INTENTOS_CADUCAN_S = 86400
GRACIA_PAGO_S = 3 * 86400            # una suscripción sigue viva 3 días tras su fin de periodo (reintentos de cobro)
ACCIONES_ENLACE = ("entrar", "borrar")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS ajustes (clave TEXT PRIMARY KEY, valor TEXT);
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT, correo TEXT NOT NULL UNIQUE, alta REAL NOT NULL, idioma TEXT NOT NULL DEFAULT 'es',
    condiciones_fecha REAL NOT NULL, condiciones_version TEXT NOT NULL,
    privacidad_fecha REAL NOT NULL, privacidad_version TEXT NOT NULL,
    plan TEXT NOT NULL DEFAULT 'registrado', periodo TEXT NOT NULL DEFAULT '', plan_hasta REAL,
    stripe_cliente TEXT, stripe_suscripcion TEXT,
    bono_restantes INTEGER NOT NULL DEFAULT 0, bono_caduca REAL,
    desistimiento_fecha REAL);
CREATE TABLE IF NOT EXISTS enlaces (
    huella TEXT PRIMARY KEY, correo TEXT NOT NULL, accion TEXT NOT NULL, creado REAL NOT NULL, caduca REAL NOT NULL,
    datos TEXT NOT NULL DEFAULT '') WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS sesiones (
    huella TEXT PRIMARY KEY, usuario_id INTEGER NOT NULL, creada REAL NOT NULL, caduca REAL NOT NULL) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_sesiones_usuario ON sesiones (usuario_id);
CREATE TABLE IF NOT EXISTS intentos (clave TEXT NOT NULL, ts REAL NOT NULL);
CREATE INDEX IF NOT EXISTS idx_intentos ON intentos (clave, ts);
CREATE TABLE IF NOT EXISTS favoritos (
    usuario_id INTEGER NOT NULL, tipo TEXT NOT NULL, clave TEXT NOT NULL, nombre TEXT NOT NULL, creado REAL NOT NULL,
    PRIMARY KEY (usuario_id, tipo, clave)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS descargas (
    id INTEGER PRIMARY KEY AUTOINCREMENT, usuario_id INTEGER NOT NULL, ts REAL NOT NULL, tipo TEXT NOT NULL,
    clave TEXT NOT NULL, nombre TEXT NOT NULL, origen TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_descargas_usuario ON descargas (usuario_id, ts);
CREATE TABLE IF NOT EXISTS pagos (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, usuario_id INTEGER, evento TEXT NOT NULL UNIQUE,
    tipo TEXT NOT NULL, plan TEXT NOT NULL DEFAULT '', periodo TEXT NOT NULL DEFAULT '', importe INTEGER,
    moneda TEXT NOT NULL DEFAULT '', detalle TEXT NOT NULL DEFAULT '');
"""

# Preparada para cuando haya empresa (facturas con NIF). NO se crea salvo PLANES_FACTURACION=1.
ESQUEMA_FACTURACION = """
CREATE TABLE IF NOT EXISTS facturacion (
    usuario_id INTEGER PRIMARY KEY, razon_social TEXT NOT NULL, nif TEXT NOT NULL, pais TEXT NOT NULL DEFAULT 'ES',
    actualizado REAL NOT NULL);
"""

_CAMPOS = ("id", "correo", "alta", "idioma", "condiciones_fecha", "condiciones_version", "privacidad_fecha",
           "privacidad_version", "plan", "periodo", "plan_hasta", "stripe_cliente", "stripe_suscripcion",
           "bono_restantes", "bono_caduca", "desistimiento_fecha")


def _huella(texto):
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def inicio_mes(alta, ahora):
    """Comienzo del «mes» de informes que está en curso: el día del mes del alta (o el último día si ese mes no lo
    tiene), a la hora del alta, en UTC."""
    a = datetime.fromtimestamp(alta, timezone.utc)
    n = datetime.fromtimestamp(ahora, timezone.utc)

    def _en(anio, mes):
        dia = min(a.day, calendar.monthrange(anio, mes)[1])
        return a.replace(year=anio, month=mes, day=dia)
    c = _en(n.year, n.month)
    if c > n:
        anio, mes = (n.year, n.month - 1) if n.month > 1 else (n.year - 1, 12)
        c = _en(anio, mes)
    return max(c.timestamp(), alta)


def siguiente_mes(alta, ahora):
    """Cuándo se renueva el cupo (para enseñarlo en «Mi cuenta»)."""
    i = datetime.fromtimestamp(inicio_mes(alta, ahora), timezone.utc)
    a = datetime.fromtimestamp(alta, timezone.utc)
    anio, mes = (i.year, i.month + 1) if i.month < 12 else (i.year + 1, 1)
    return i.replace(year=anio, month=mes, day=min(a.day, calendar.monthrange(anio, mes)[1])).timestamp()


class Almacen:
    def __init__(self, ruta, facturacion=False):
        self.lock = threading.Lock()
        self.db = sqlite3.connect(ruta, check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA secure_delete=ON")      # lo borrado se sobrescribe en el fichero (art. 17)
        self.db.executescript(ESQUEMA)
        if facturacion:
            self.db.executescript(ESQUEMA_FACTURACION)
        with self.lock:
            if not self._ajuste("clave"):
                self.db.execute("INSERT OR IGNORE INTO ajustes VALUES ('clave', ?)", (secrets.token_hex(32),))

    # ── utilidades ──────────────────────────────────────────────────────────────────────────────────────────────
    def _ajuste(self, clave):
        f = self.db.execute("SELECT valor FROM ajustes WHERE clave=?", (clave,)).fetchone()
        return f[0] if f else None

    def _hmac(self, texto):
        return hmac.new(self._ajuste("clave").encode(), texto.encode("utf-8"), hashlib.sha256).hexdigest()

    def firma(self, texto):
        """HMAC con la clave propia de usuarios.db (para el código anti-CSRF de los formularios de la cuenta)."""
        with self.lock:
            return self._hmac(texto)[:32]

    def firma_valida(self, texto, firma):
        try:
            return bool(firma) and hmac.compare_digest(self.firma(texto), firma)
        except (TypeError, ValueError):
            return False

    def _usuario(self, donde, valor):
        f = self.db.execute(f"SELECT {', '.join(_CAMPOS)} FROM usuarios WHERE {donde}=?", (valor,)).fetchone()
        return dict(zip(_CAMPOS, f)) if f else None

    def usuario(self, uid):
        with self.lock:
            return self._usuario("id", uid)

    def usuario_por_correo(self, correo):
        with self.lock:
            return self._usuario("correo", (correo or "").strip().lower())

    def usuario_por_suscripcion(self, sub_id):
        with self.lock:
            return self._usuario("stripe_suscripcion", sub_id) if sub_id else None

    def usuario_por_cliente(self, cliente_id):
        with self.lock:
            return self._usuario("stripe_cliente", cliente_id) if cliente_id else None

    # ── límite de intentos ──────────────────────────────────────────────────────────────────────────────────────
    def intento_permitido(self, correo, ip, ahora=None):
        """¿Se puede mandar otro correo de acceso? Apunta el intento si sí. Guarda huellas, no el correo ni la IP."""
        ahora = time.time() if ahora is None else ahora
        claves = [("c:" + self._hmac("correo:" + (correo or "").lower()), INTENTOS_CORREO_HORA)]
        if ip:
            claves.append(("i:" + self._hmac("ip:" + ip), INTENTOS_IP_HORA))
        with self.lock:
            self.db.execute("DELETE FROM intentos WHERE ts < ?", (ahora - INTENTOS_CADUCAN_S,))
            for clave, tope in claves:
                n = self.db.execute("SELECT count(*) FROM intentos WHERE clave=? AND ts >= ?",
                                    (clave, ahora - 3600)).fetchone()[0]
                if n >= tope:
                    return False
            for clave, _ in claves:
                self.db.execute("INSERT INTO intentos VALUES (?, ?)", (clave, ahora))
        return True

    # ── enlaces de un solo uso ──────────────────────────────────────────────────────────────────────────────────
    def crear_enlace(self, correo, accion, datos="", ahora=None):
        """Código aleatorio para el enlace del correo (se devuelve una vez y aquí solo queda su huella)."""
        if accion not in ACCIONES_ENLACE:
            raise ValueError(accion)
        ahora = time.time() if ahora is None else ahora
        codigo = secrets.token_urlsafe(32)
        with self.lock:
            self.db.execute("DELETE FROM enlaces WHERE caduca < ?", (ahora,))
            self.db.execute("INSERT INTO enlaces VALUES (?, ?, ?, ?, ?, ?)",
                            (_huella(codigo), (correo or "").strip().lower(), accion, ahora, ahora + ENLACE_CADUCA_S, datos))
        return codigo

    def ver_enlace(self, codigo, accion, ahora=None):
        """{correo, datos} si el enlace vale (sin gastarlo), o None."""
        ahora = time.time() if ahora is None else ahora
        with self.lock:
            f = self.db.execute("SELECT correo, datos FROM enlaces WHERE huella=? AND accion=? AND caduca >= ?",
                                (_huella(codigo or ""), accion, ahora)).fetchone()
        return {"correo": f[0], "datos": f[1]} if f else None

    def gastar_enlace(self, codigo, accion, ahora=None):
        """Lo mismo, pero el enlace deja de valer (un solo uso). Atómico: dos clics a la vez, solo uno vale."""
        ahora = time.time() if ahora is None else ahora
        h = _huella(codigo or "")
        with self.lock:
            f = self.db.execute("SELECT correo, datos FROM enlaces WHERE huella=? AND accion=? AND caduca >= ?",
                                (h, accion, ahora)).fetchone()
            if not f:
                return None
            self.db.execute("DELETE FROM enlaces WHERE huella=?", (h,))
        return {"correo": f[0], "datos": f[1]}

    # ── alta y sesiones ─────────────────────────────────────────────────────────────────────────────────────────
    def alta_o_entrada(self, correo, version_condiciones, version_privacidad, idioma="es", ahora=None):
        """Tras pulsar el enlace: crea la cuenta si no existía (con la aceptación de los textos de ESE momento) o
        devuelve la que había. (usuario, nueva)."""
        ahora = time.time() if ahora is None else ahora
        correo = (correo or "").strip().lower()
        with self.lock:
            u = self._usuario("correo", correo)
            if u:
                return u, False
            self.db.execute("INSERT INTO usuarios (correo, alta, idioma, condiciones_fecha, condiciones_version, "
                            "privacidad_fecha, privacidad_version) VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (correo, ahora, idioma, ahora, version_condiciones, ahora, version_privacidad))
            return self._usuario("correo", correo), True

    def aceptar_textos(self, uid, version_condiciones, version_privacidad, ahora=None):
        """Si cambian los textos, la persona los vuelve a aceptar y queda la fecha y la versión nuevas."""
        ahora = time.time() if ahora is None else ahora
        with self.lock:
            self.db.execute("UPDATE usuarios SET condiciones_fecha=?, condiciones_version=?, privacidad_fecha=?, "
                            "privacidad_version=? WHERE id=?",
                            (ahora, version_condiciones, ahora, version_privacidad, uid))

    def crear_sesion(self, uid, ahora=None):
        ahora = time.time() if ahora is None else ahora
        codigo = secrets.token_urlsafe(32)
        with self.lock:
            self.db.execute("DELETE FROM sesiones WHERE caduca < ?", (ahora,))
            self.db.execute("INSERT INTO sesiones VALUES (?, ?, ?, ?)", (_huella(codigo), uid, ahora, ahora + SESION_DURA_S))
        return codigo

    def usuario_de_sesion(self, codigo, ahora=None):
        if not codigo:
            return None
        ahora = time.time() if ahora is None else ahora
        with self.lock:
            f = self.db.execute("SELECT usuario_id FROM sesiones WHERE huella=? AND caduca >= ?",
                                (_huella(codigo), ahora)).fetchone()
            return self._usuario("id", f[0]) if f else None

    def cerrar_sesion(self, codigo):
        with self.lock:
            self.db.execute("DELETE FROM sesiones WHERE huella=?", (_huella(codigo or ""),))

    # ── plan y pagos ────────────────────────────────────────────────────────────────────────────────────────────
    def plan_vigente(self, u, ahora=None):
        """El plan que vale AHORA: una suscripción vencida (más la gracia) vuelve a «registrado»."""
        ahora = time.time() if ahora is None else ahora
        if not u:
            return "ciudadano"
        if PL.es_suscripcion(u["plan"]):
            if u["plan_hasta"] and u["plan_hasta"] + GRACIA_PAGO_S >= ahora:
                return u["plan"]
            return "registrado"
        return "registrado"

    def bono_vigente(self, u, ahora=None):
        ahora = time.time() if ahora is None else ahora
        if not u or not u["bono_restantes"] or not u["bono_caduca"] or u["bono_caduca"] < ahora:
            return 0
        return u["bono_restantes"]

    def pago_ya_visto(self, evento):
        with self.lock:
            return self.db.execute("SELECT 1 FROM pagos WHERE evento=?", (evento,)).fetchone() is not None

    def registrar_pago(self, evento, tipo, uid, plan="", periodo="", importe=None, moneda="", detalle="", ahora=None):
        """Apunta un evento de Stripe UNA vez. False si ya estaba (Stripe reenvía los avisos: idempotencia)."""
        ahora = time.time() if ahora is None else ahora
        with self.lock:
            try:
                self.db.execute("INSERT INTO pagos (ts, usuario_id, evento, tipo, plan, periodo, importe, moneda, detalle) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                (ahora, uid, evento, tipo, plan, periodo, importe, moneda, detalle[:300]))
            except sqlite3.IntegrityError:
                return False
        return True

    def sumar_bono(self, uid, ahora=None):
        ahora = time.time() if ahora is None else ahora
        with self.lock:
            u = self._usuario("id", uid)
            if not u:
                return False
            vigentes = u["bono_restantes"] if (u["bono_caduca"] or 0) >= ahora else 0
            self.db.execute("UPDATE usuarios SET bono_restantes=?, bono_caduca=? WHERE id=?",
                            (vigentes + PL.BONO_INFORMES, ahora + PL.BONO_VALIDEZ_DIAS * 86400, uid))
        return True

    def poner_suscripcion(self, uid, plan, periodo, hasta, cliente=None, suscripcion=None):
        if not PL.es_suscripcion(plan) or periodo not in PL.PERIODOS:
            raise ValueError(plan)
        with self.lock:
            self.db.execute("UPDATE usuarios SET plan=?, periodo=?, plan_hasta=?, stripe_cliente=coalesce(?, stripe_cliente), "
                            "stripe_suscripcion=coalesce(?, stripe_suscripcion) WHERE id=?",
                            (plan, periodo, hasta, cliente, suscripcion, uid))

    def poner_cliente(self, uid, cliente):
        with self.lock:
            self.db.execute("UPDATE usuarios SET stripe_cliente=? WHERE id=?", (cliente, uid))

    def quitar_suscripcion(self, uid):
        with self.lock:
            self.db.execute("UPDATE usuarios SET plan='registrado', periodo='', plan_hasta=NULL, stripe_suscripcion=NULL "
                            "WHERE id=?", (uid,))

    def anotar_desistimiento(self, uid, ahora=None):
        """La persona acepta, antes de su primera descarga de pago, perder el desistimiento (contenido digital)."""
        ahora = time.time() if ahora is None else ahora
        with self.lock:
            self.db.execute("UPDATE usuarios SET desistimiento_fecha=coalesce(desistimiento_fecha, ?) WHERE id=?", (ahora, uid))

    # ── informes ────────────────────────────────────────────────────────────────────────────────────────────────
    def cuenta_informes(self, u, ahora=None):
        """{plan, cupo_mes (None = sin cupo), usados_mes, quedan_mes, bono, total_quedan (None = sin cupo), renueva}."""
        ahora = time.time() if ahora is None else ahora
        plan = self.plan_vigente(u, ahora)
        desde = inicio_mes(u["alta"], ahora)
        with self.lock:
            usados = self.db.execute("SELECT count(*) FROM descargas WHERE usuario_id=? AND ts >= ? AND origen='mes'",
                                     (u["id"], desde)).fetchone()[0]
        cupo = PL.cupo_mes(plan)
        tope = PL.tope_mes(plan)
        quedan = max(0, tope - usados)
        bono = self.bono_vigente(u, ahora)
        return {"plan": plan, "cupo_mes": cupo, "usados_mes": usados, "quedan_mes": quedan if cupo is not None else None,
                "bono": bono, "total_quedan": (quedan + bono) if cupo is not None else None,
                "quedan_tecnico": quedan + bono, "renueva": siguiente_mes(u["alta"], ahora)}

    @staticmethod
    def usa_cupo_mes(plan, tipo):
        """El informe gratuito del plan Registrado es de MUNICIPIO: uno de empresa solo sale del bono."""
        return not (plan == "registrado" and tipo == "empresa")

    def gastar_informe(self, uid, tipo, clave, nombre, ahora=None):
        """Apunta una descarga si le queda alguna: primero las del mes, luego el bono. Volver a bajar el MISMO informe
        el mismo día no gasta otro. Devuelve el origen ("mes", "bono", "repetido") o None si no le quedan."""
        ahora = time.time() if ahora is None else ahora
        with self.lock:
            u = self._usuario("id", uid)
            if not u:
                return None
            if self.db.execute("SELECT 1 FROM descargas WHERE usuario_id=? AND tipo=? AND clave=? AND ts >= ?",
                               (uid, tipo, clave, ahora - 86400)).fetchone():
                return "repetido"
            plan = self.plan_vigente(u, ahora)
            usados = self.db.execute("SELECT count(*) FROM descargas WHERE usuario_id=? AND ts >= ? AND origen='mes'",
                                     (uid, inicio_mes(u["alta"], ahora))).fetchone()[0]
            if self.usa_cupo_mes(plan, tipo) and usados < PL.tope_mes(plan):
                origen = "mes"
            elif self.bono_vigente(u, ahora) > 0:
                origen = "bono"
                self.db.execute("UPDATE usuarios SET bono_restantes=bono_restantes-1 WHERE id=?", (uid,))
            else:
                return None
            self.db.execute("INSERT INTO descargas (usuario_id, ts, tipo, clave, nombre, origen) VALUES (?, ?, ?, ?, ?, ?)",
                            (uid, ahora, tipo, clave, nombre[:200], origen))
        return origen

    def descargas_de(self, uid, limite=50):
        with self.lock:
            filas = self.db.execute("SELECT ts, tipo, clave, nombre, origen FROM descargas WHERE usuario_id=? "
                                    "ORDER BY ts DESC LIMIT ?", (uid, limite)).fetchall()
        return [dict(zip(("ts", "tipo", "clave", "nombre", "origen"), f)) for f in filas]

    # ── favoritos ───────────────────────────────────────────────────────────────────────────────────────────────
    FAVORITOS_MAX = 200

    def poner_favorito(self, uid, tipo, clave, nombre, ahora=None):
        ahora = time.time() if ahora is None else ahora
        if tipo not in ("municipio", "empresa") or not clave:
            return False
        with self.lock:
            n = self.db.execute("SELECT count(*) FROM favoritos WHERE usuario_id=?", (uid,)).fetchone()[0]
            if n >= self.FAVORITOS_MAX:
                return False
            self.db.execute("INSERT OR REPLACE INTO favoritos VALUES (?, ?, ?, ?, ?)", (uid, tipo, clave[:160], nombre[:200], ahora))
        return True

    def quitar_favorito(self, uid, tipo, clave):
        with self.lock:
            self.db.execute("DELETE FROM favoritos WHERE usuario_id=? AND tipo=? AND clave=?", (uid, tipo, clave))

    def favoritos_de(self, uid):
        with self.lock:
            filas = self.db.execute("SELECT tipo, clave, nombre, creado FROM favoritos WHERE usuario_id=? ORDER BY creado DESC",
                                    (uid,)).fetchall()
        return [dict(zip(("tipo", "clave", "nombre", "creado"), f)) for f in filas]

    # ── borrar la cuenta (art. 17 RGPD) ─────────────────────────────────────────────────────────────────────────
    def borrar_cuenta(self, uid):
        """Borra la cuenta y todo lo suyo. De los pagos queda la línea contable SIN el número de usuario."""
        with self.lock:
            u = self._usuario("id", uid)
            if not u:
                return False
            self.db.execute("BEGIN")
            try:
                self.db.execute("DELETE FROM sesiones WHERE usuario_id=?", (uid,))
                self.db.execute("DELETE FROM favoritos WHERE usuario_id=?", (uid,))
                self.db.execute("DELETE FROM descargas WHERE usuario_id=?", (uid,))
                self.db.execute("DELETE FROM enlaces WHERE correo=?", (u["correo"],))
                self.db.execute("UPDATE pagos SET usuario_id=NULL WHERE usuario_id=?", (uid,))
                if self.db.execute("SELECT name FROM sqlite_master WHERE name='facturacion'").fetchone():
                    self.db.execute("DELETE FROM facturacion WHERE usuario_id=?", (uid,))
                self.db.execute("DELETE FROM usuarios WHERE id=?", (uid,))
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise
        return True

    # ── limpieza y panel ────────────────────────────────────────────────────────────────────────────────────────
    def limpiar(self, ahora=None):
        ahora = time.time() if ahora is None else ahora
        with self.lock:
            r = {"enlaces": self.db.execute("DELETE FROM enlaces WHERE caduca < ?", (ahora,)).rowcount,
                 "sesiones": self.db.execute("DELETE FROM sesiones WHERE caduca < ?", (ahora,)).rowcount,
                 "intentos": self.db.execute("DELETE FROM intentos WHERE ts < ?", (ahora - INTENTOS_CADUCAN_S,)).rowcount}
        return r

    def vencidas(self, ahora=None):
        """Suscripciones que ya no valen (fin de periodo + gracia) y siguen apuntadas: se pasan a «registrado» y se
        devuelven sus ids (para bajar también el nivel de sus alertas)."""
        ahora = time.time() if ahora is None else ahora
        with self.lock:
            ids = [f[0] for f in self.db.execute(
                "SELECT id FROM usuarios WHERE plan IN ('profesional', 'premium') AND (plan_hasta IS NULL OR plan_hasta < ?)",
                (ahora - GRACIA_PAGO_S,))]
            for uid in ids:
                self.db.execute("UPDATE usuarios SET plan='registrado', periodo='', plan_hasta=NULL WHERE id=?", (uid,))
        return ids

    def resumen(self):
        """Solo recuentos (para el diagnóstico): ni correos ni identificadores."""
        with self.lock:
            q = lambda sql, *a: self.db.execute(sql, a).fetchone()[0]          # noqa: E731
            return {"usuarios": q("SELECT count(*) FROM usuarios"),
                    "profesional": q("SELECT count(*) FROM usuarios WHERE plan='profesional'"),
                    "premium": q("SELECT count(*) FROM usuarios WHERE plan='premium'"),
                    "con_bono": q("SELECT count(*) FROM usuarios WHERE bono_restantes > 0"),
                    "descargas_30_dias": q("SELECT count(*) FROM descargas WHERE ts >= ?", time.time() - 30 * 86400),
                    "pagos": q("SELECT count(*) FROM pagos")}
