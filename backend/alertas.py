# encoding: utf-8
"""
Alertas por correo (2026-10-13, encargo de César): almacén y reglas. La web (app.py) pone las páginas, busca las
novedades en cache.db y envía por Resend; aquí vive todo lo que toca a los suscriptores.

Los datos van en un fichero PROPIO (alertas.db, en DATA_DIR), no en cache.db: cache.db se descarga en GitHub Actions
y se copia cada semana a otro repositorio, y las direcciones de correo no deben viajar con ella. La copia de
alertas.db va cifrada (flujo copia-alertas-cifrada.yml).

Qué se guarda de cada persona: el correo, el idioma en que se apuntó, el nivel y sus alertas (tipo y filtros). Nada
más: ni nombre, ni teléfono, ni IP. La baja borra la fila entera.

Reglas:
  - Una alerta no existe hasta que se confirma desde el correo (doble confirmación). Las altas sin confirmar se
    borran a los 7 días.
  - Nivel gratis: 1 alerta, resumen semanal. Nivel pago: 10 alertas, aviso diario. El nivel solo se cambia desde el
    panel de administración; no hay pasarela de pago conectada.
  - "Novedad" = algo que la pasada de envío ve por primera vez (tabla vistos). La primera vez que se mira una lista
    (las licitaciones abiertas, los contratos de un municipio) todo lo que hay queda como ya visto: una alerta
    nueva nunca manda de golpe lo que ya estaba.
  - Los enlaces de los correos (confirmar, baja, gestionar) van firmados con una clave que se genera sola y vive en
    alertas.db: no hay ningún secreto que configurar.
"""
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
import time

NIVELES = {"gratis": {"alertas": 1, "frecuencia": "semanal"},
           "pago": {"alertas": 10, "frecuencia": "diaria"}}
TIPOS = ("contratos", "licitaciones", "subvenciones")
PENDIENTE_CADUCA_S = 7 * 86400
REENVIO_ESPERA_S = 600               # no se repite un correo de confirmación a la misma dirección antes de 10 min
ALTAS_MAX_HORA = 30                  # tope de correos de confirmación por hora (formulario público)
VISTOS_CADUCAN_S = 400 * 86400
_RE_CORREO = re.compile(r"[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]{1,63}(?:\.[A-Za-z0-9\-]{1,63})+")

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS ajustes (clave TEXT PRIMARY KEY, valor TEXT);
CREATE TABLE IF NOT EXISTS suscriptores (
    id INTEGER PRIMARY KEY AUTOINCREMENT, correo TEXT NOT NULL UNIQUE, idioma TEXT NOT NULL DEFAULT 'es',
    nivel TEXT NOT NULL DEFAULT 'gratis', estado TEXT NOT NULL DEFAULT 'pendiente',
    creado REAL NOT NULL, confirmado REAL, ultimo_correo REAL);
CREATE TABLE IF NOT EXISTS alertas (
    id INTEGER PRIMARY KEY AUTOINCREMENT, suscriptor_id INTEGER NOT NULL, tipo TEXT NOT NULL,
    filtros TEXT NOT NULL, etiqueta TEXT NOT NULL, estado TEXT NOT NULL DEFAULT 'pendiente',
    creado REAL NOT NULL, revisado REAL, intentado REAL, ultimo_envio REAL);
CREATE INDEX IF NOT EXISTS idx_alertas_suscriptor ON alertas (suscriptor_id);
CREATE TABLE IF NOT EXISTS envios (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, clase TEXT NOT NULL, suscriptor_id INTEGER,
    alertas INTEGER NOT NULL DEFAULT 0, novedades INTEGER NOT NULL DEFAULT 0, codigo INTEGER, detalle TEXT);
CREATE INDEX IF NOT EXISTS idx_envios_ts ON envios (ts);
CREATE TABLE IF NOT EXISTS vistos (lista TEXT NOT NULL, item TEXT NOT NULL, primera_vez REAL NOT NULL,
    PRIMARY KEY (lista, item)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS sembrado (lista TEXT PRIMARY KEY, ts REAL NOT NULL);
"""


def correo_valido(correo):
    correo = (correo or "").strip().lower()
    return correo if len(correo) <= 120 and _RE_CORREO.fullmatch(correo) else ""


def correo_tapado(correo):
    usuario, _, dominio = (correo or "").partition("@")
    return f"{usuario[:2]}***@{dominio}" if dominio else ""


class Almacen:
    def __init__(self, ruta):
        self.ruta = ruta
        self.lock = threading.RLock()
        self.db = sqlite3.connect(ruta, check_same_thread=False, timeout=30)
        with self.lock:
            self.db.executescript(_ESQUEMA)
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

    def firma(self, accion, identificador):
        return hmac.new(self._clave, f"{accion}|{int(identificador)}".encode(), hashlib.sha256).hexdigest()[:32]

    def firma_valida(self, accion, identificador, firma):
        try:
            return hmac.compare_digest((firma or "").encode(), self.firma(accion, identificador).encode())
        except (TypeError, ValueError):
            return False

    def _suscriptor(self, donde, valor):
        f = self.db.execute(f"SELECT id, correo, idioma, nivel, estado, creado, confirmado, ultimo_correo "
                            f"FROM suscriptores WHERE {donde}=?", (valor,)).fetchone()
        return dict(zip(("id", "correo", "idioma", "nivel", "estado", "creado", "confirmado", "ultimo_correo"), f)) if f else None

    def suscriptor(self, sid):
        with self.lock:
            return self._suscriptor("id", sid)

    def _alertas(self, donde, valor):
        filas = self.db.execute(f"SELECT id, suscriptor_id, tipo, filtros, etiqueta, estado, creado, revisado, "
                                f"ultimo_envio FROM alertas WHERE {donde}=? ORDER BY id", (valor,)).fetchall()
        return [dict(zip(("id", "suscriptor_id", "tipo", "filtros", "etiqueta", "estado", "creado", "revisado",
                          "ultimo_envio"), f[:3] + (json.loads(f[3]),) + f[4:])) for f in filas]

    def alertas_de(self, sid, solo_activas=False):
        with self.lock:
            return [a for a in self._alertas("suscriptor_id", sid) if a["estado"] == "activa" or not solo_activas]

    def alerta(self, aid):
        with self.lock:
            filas = self._alertas("id", aid)
        return filas[0] if filas else None

    # ── alta, confirmación y baja ───────────────────────────────────────────────────────────────────────────────
    def alta(self, correo, idioma, tipo, filtros, etiqueta, ahora=None):
        """Pide una alerta. Devuelve {"resultado", "suscriptor", "alerta_id"}; resultado:
             confirmar  -> hay que mandar el correo de confirmación de esa alerta
             limite     -> ya tiene todas las alertas de su nivel: correo con el enlace para gestionarlas
             espera     -> se le acaba de escribir (o hay demasiadas altas en esta hora): no se manda nada
             invalido   -> el correo no vale
           La página responde siempre lo mismo ("revisa tu correo"): así no se puede averiguar desde fuera si una
           dirección está apuntada."""
        ahora = ahora or time.time()
        correo = correo_valido(correo)
        if not correo or tipo not in TIPOS:
            return {"resultado": "invalido"}
        with self.lock:
            s = self._suscriptor("correo", correo)
            if s and s["ultimo_correo"] and ahora - s["ultimo_correo"] < REENVIO_ESPERA_S:
                return {"resultado": "espera", "suscriptor": s}
            recientes = self.db.execute("SELECT count(*) FROM envios WHERE clase IN ('confirmacion', 'limite') "
                                        "AND ts > ?", (ahora - 3600,)).fetchone()[0]
            if recientes >= ALTAS_MAX_HORA:
                return {"resultado": "espera", "suscriptor": s}
            if not s:
                self.db.execute("INSERT INTO suscriptores (correo, idioma, creado) VALUES (?,?,?)",
                                (correo, idioma, ahora))
                s = self._suscriptor("correo", correo)
            activas = [a for a in self._alertas("suscriptor_id", s["id"]) if a["estado"] == "activa"]
            if len(activas) >= NIVELES[s["nivel"]]["alertas"]:
                self.db.execute("UPDATE suscriptores SET ultimo_correo=? WHERE id=?", (ahora, s["id"]))
                self.db.commit()
                return {"resultado": "limite", "suscriptor": s}
            # Una sola alerta pendiente por persona: la última que pide sustituye a la anterior sin confirmar.
            self.db.execute("DELETE FROM alertas WHERE suscriptor_id=? AND estado='pendiente'", (s["id"],))
            cur = self.db.execute("INSERT INTO alertas (suscriptor_id, tipo, filtros, etiqueta, creado) VALUES (?,?,?,?,?)",
                                  (s["id"], tipo, json.dumps(filtros, ensure_ascii=False, sort_keys=True),
                                   etiqueta[:200], ahora))
            self.db.execute("UPDATE suscriptores SET ultimo_correo=?, idioma=? WHERE id=?", (ahora, idioma, s["id"]))
            self.db.commit()
            return {"resultado": "confirmar", "suscriptor": self._suscriptor("id", s["id"]), "alerta_id": cur.lastrowid}

    def confirmar(self, alerta_id, ahora=None):
        """Activa la alerta (y a la persona, si era su primera). Devuelve la alerta, o None si ya no existe o si
        entretanto ha llenado su cupo."""
        ahora = ahora or time.time()
        with self.lock:
            filas = self._alertas("id", alerta_id)
            if not filas:
                return None
            a = filas[0]
            if a["estado"] == "activa":
                return dict(a, ya_estaba=True)
            s = self._suscriptor("id", a["suscriptor_id"])
            activas = [x for x in self._alertas("suscriptor_id", s["id"]) if x["estado"] == "activa"]
            if len(activas) >= NIVELES[s["nivel"]]["alertas"]:
                return None
            self.db.execute("UPDATE alertas SET estado='activa', revisado=? WHERE id=?", (ahora, alerta_id))
            self.db.execute("UPDATE suscriptores SET estado='activo', confirmado=coalesce(confirmado, ?) WHERE id=?",
                            (ahora, s["id"]))
            self.db.commit()
            return self._alertas("id", alerta_id)[0]

    def poner_revisado(self, alerta_id, ahora):
        """Desde cuándo cuenta "nuevo" para esa alerta."""
        with self.lock:
            self.db.execute("UPDATE alertas SET revisado=? WHERE id=?", (ahora, alerta_id))
            self.db.commit()

    def borrar_alerta(self, sid, alerta_id):
        with self.lock:
            n = self.db.execute("DELETE FROM alertas WHERE id=? AND suscriptor_id=?", (alerta_id, sid)).rowcount
            self.db.commit()
        return bool(n)

    def baja(self, sid, motivo="baja"):
        """Borra a la persona y sus alertas. De los envíos queda la fila sin saber de quién era."""
        with self.lock:
            n = self.db.execute("DELETE FROM suscriptores WHERE id=?", (sid,)).rowcount
            self.db.execute("DELETE FROM alertas WHERE suscriptor_id=?", (sid,))
            self.db.execute("UPDATE envios SET suscriptor_id=NULL WHERE suscriptor_id=?", (sid,))
            if n:
                self._sumar("bajas_" + motivo)
            self.db.commit()
        return bool(n)

    def cambiar_nivel(self, sid, nivel):
        if nivel not in NIVELES:
            return False
        with self.lock:
            self.db.execute("UPDATE suscriptores SET nivel=? WHERE id=?", (nivel, sid))
            self.db.commit()
        return True

    def limpiar(self, ahora=None):
        """Altas sin confirmar de hace más de 7 días, personas que se han quedado sin ninguna alerta y vistos viejos."""
        ahora = ahora or time.time()
        with self.lock:
            self.db.execute("DELETE FROM alertas WHERE estado='pendiente' AND creado < ?", (ahora - PENDIENTE_CADUCA_S,))
            n = self.db.execute("DELETE FROM suscriptores WHERE creado < ? AND id NOT IN (SELECT suscriptor_id FROM alertas)",
                                (ahora - PENDIENTE_CADUCA_S,)).rowcount
            if n:
                self._sumar("caducados", n)
            self.db.execute("DELETE FROM vistos WHERE primera_vez > 0 AND primera_vez < ?", (ahora - VISTOS_CADUCAN_S,))
            self.db.execute("DELETE FROM envios WHERE ts < ?", (ahora - VISTOS_CADUCAN_S,))
            self.db.commit()

    # ── novedades ───────────────────────────────────────────────────────────────────────────────────────────────
    def registrar_vistos(self, lista, items, ahora):
        """Apunta lo que hay ahora en una lista. La primera vez queda todo como "ya estaba" (primera_vez = 0)."""
        with self.lock:
            sembrada = self.db.execute("SELECT 1 FROM sembrado WHERE lista=?", (lista,)).fetchone()
            marca = ahora if sembrada else 0
            self.db.executemany("INSERT OR IGNORE INTO vistos VALUES (?,?,?)", ((lista, str(i), marca) for i in items))
            if not sembrada:
                self.db.execute("INSERT INTO sembrado VALUES (?, ?)", (lista, ahora))
            self.db.commit()

    def nuevos_desde(self, lista, desde):
        with self.lock:
            return {f[0] for f in self.db.execute("SELECT item FROM vistos WHERE lista=? AND primera_vez > ?",
                                                  (lista, desde or 0))}

    # ── pasada de envío ─────────────────────────────────────────────────────────────────────────────────────────
    def pendientes(self, inicio_semana, inicio_dia):
        """Personas con alguna alerta que toca mirar: [(suscriptor, [alertas])], las que más llevan esperando
        primero. Semanal (gratis): no revisada desde el lunes. Diaria (pago): no revisada hoy. Una alerta que ya se
        ha intentado hoy (envío fallido) no vuelve a salir hasta mañana."""
        with self.lock:
            filas = self.db.execute(
                "SELECT a.id, s.id, s.nivel FROM alertas a JOIN suscriptores s ON s.id = a.suscriptor_id "
                "WHERE a.estado='activa' AND s.estado='activo' AND coalesce(a.intentado, 0) < ? "
                "ORDER BY coalesce(a.revisado, 0), a.id", (inicio_dia,)).fetchall()
            por_persona = {}
            for aid, sid, nivel in filas:
                a = self._alertas("id", aid)[0]
                corte = inicio_semana if NIVELES[nivel]["frecuencia"] == "semanal" else inicio_dia
                if (a["revisado"] or 0) < corte:
                    por_persona.setdefault(sid, []).append(a)
            return [(self._suscriptor("id", sid), alertas) for sid, alertas in por_persona.items()]

    def marcar(self, alerta_ids, ahora, enviado, revisada=True):
        with self.lock:
            for aid in alerta_ids:
                if revisada:
                    self.db.execute("UPDATE alertas SET revisado=?, intentado=?, ultimo_envio=coalesce(?, ultimo_envio) "
                                    "WHERE id=?", (ahora, ahora, ahora if enviado else None, aid))
                else:
                    self.db.execute("UPDATE alertas SET intentado=? WHERE id=?", (ahora, aid))
            self.db.commit()

    def registrar_envio(self, clase, sid, codigo, detalle, alertas=0, novedades=0, ahora=None):
        with self.lock:
            self.db.execute("INSERT INTO envios (ts, clase, suscriptor_id, alertas, novedades, codigo, detalle) "
                            "VALUES (?,?,?,?,?,?,?)", (ahora or time.time(), clase, sid, alertas, novedades, codigo,
                                                       (detalle or "")[:300]))
            self.db.commit()

    def envios_desde(self, desde):
        """Correos que Resend aceptó desde `desde` (los que cuentan para el cupo)."""
        with self.lock:
            return self.db.execute("SELECT count(*) FROM envios WHERE ts >= ? AND codigo BETWEEN 200 AND 299",
                                   (desde,)).fetchone()[0]

    # ── panel ───────────────────────────────────────────────────────────────────────────────────────────────────
    def resumen(self):
        with self.lock:
            q = lambda sql, *a: self.db.execute(sql, a).fetchone()[0]
            return {
                "suscriptores_activos": q("SELECT count(*) FROM suscriptores WHERE estado='activo'"),
                "suscriptores_pendientes": q("SELECT count(*) FROM suscriptores WHERE estado='pendiente'"),
                "de_pago": q("SELECT count(*) FROM suscriptores WHERE estado='activo' AND nivel='pago'"),
                "alertas_activas": q("SELECT count(*) FROM alertas WHERE estado='activa'"),
                "alertas_pendientes": q("SELECT count(*) FROM alertas WHERE estado='pendiente'"),
                "por_tipo": dict(self.db.execute("SELECT tipo, count(*) FROM alertas WHERE estado='activa' GROUP BY tipo")),
                "bajas": int(self._ajuste("bajas_baja") or 0),
                "bajas_desde_el_panel": int(self._ajuste("bajas_panel") or 0),
                "altas_caducadas": int(self._ajuste("caducados") or 0),
            }

    def lista_suscriptores(self, limite=500):
        with self.lock:
            filas = self.db.execute(
                "SELECT s.id, s.correo, s.idioma, s.nivel, s.estado, s.creado, s.confirmado, "
                "(SELECT count(*) FROM alertas a WHERE a.suscriptor_id = s.id AND a.estado='activa'), "
                "(SELECT max(ultimo_envio) FROM alertas a WHERE a.suscriptor_id = s.id) "
                "FROM suscriptores s ORDER BY s.id DESC LIMIT ?", (limite,)).fetchall()
        return [dict(zip(("id", "correo", "idioma", "nivel", "estado", "creado", "confirmado", "alertas", "ultimo_envio"), f))
                for f in filas]

    def lista_alertas(self, limite=500):
        with self.lock:
            filas = self.db.execute(
                "SELECT a.id, a.tipo, a.etiqueta, a.estado, a.creado, a.revisado, a.ultimo_envio, s.correo, s.nivel "
                "FROM alertas a JOIN suscriptores s ON s.id = a.suscriptor_id ORDER BY a.id DESC LIMIT ?",
                (limite,)).fetchall()
        return [dict(zip(("id", "tipo", "etiqueta", "estado", "creado", "revisado", "ultimo_envio", "correo", "nivel"), f))
                for f in filas]

    def lista_envios(self, limite=100):
        with self.lock:
            filas = self.db.execute("SELECT ts, clase, alertas, novedades, codigo, detalle FROM envios "
                                    "ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
        return [dict(zip(("ts", "clase", "alertas", "novedades", "codigo", "detalle"), f)) for f in filas]

    def municipios_con_alerta(self):
        """Filtros de las alertas activas de tipo contratos, sin repetir."""
        with self.lock:
            filas = self.db.execute("SELECT DISTINCT filtros FROM alertas WHERE tipo='contratos' AND estado='activa'").fetchall()
        return [json.loads(f[0]) for f in filas]

    def tipos_activos(self):
        with self.lock:
            return {f[0] for f in self.db.execute("SELECT DISTINCT tipo FROM alertas WHERE estado='activa'")}

    def copia(self):
        """Bytes de una copia íntegra del fichero (para la copia cifrada)."""
        with self.lock:
            self.db.commit()
            return self.db.serialize()
