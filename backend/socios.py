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
  - la fecha de alta y la de último uso, y la de confirmación (prueba del consentimiento, art. 7.1 RGPD).
  Mientras se espera a que confirme un cambio, el perfil nuevo va aparte (perfil_pendiente) y se descarta a los 7 días.
  Ni IP, ni nombre, ni teléfono. De los correos enviados queda solo la fila de envios (cuándo, qué clase, código de
  Resend), que sirve para no reenviar en bucle y para el cupo; al borrar el perfil se queda sin saber de quién era.

Reglas:
  - Un perfil no existe hasta que se confirma desde el correo (doble confirmación). Los perfiles sin confirmar se
    BORRAN a los 7 días.
  - Un cambio en un perfil ya confirmado tampoco vale hasta que se confirma desde el correo: así nadie puede cambiar el
    perfil de otra empresa escribiendo su correo en el formulario.
  - Baja = borrar la fila entera, no marcarla. Hay enlace de baja en todos los correos.
  - Último uso = la última vez que la empresa hizo algo con su perfil: confirmarlo, confirmar un cambio o abrir sus
    licitaciones desde el enlace del correo. Los perfiles sin uso en 12 meses se BORRAN.
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
INACTIVO_CADUCA_S = 365 * 86400
REENVIO_ESPERA_S = 600               # no se repite un correo de confirmación al mismo perfil antes de 10 min
ALTAS_MAX_HORA = 30                  # tope de correos de confirmación por hora (formulario público)
ENVIOS_CADUCAN_S = 90 * 86400
_RE_CORREO = re.compile(r"[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]{1,63}(?:\.[A-Za-z0-9\-]{1,63})+")
_CAMPOS = ("id", "correo", "perfil", "estado", "alta", "confirmado", "ultimo_uso", "perfil_pendiente", "pendiente_desde")

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS ajustes (clave TEXT PRIMARY KEY, valor TEXT);
CREATE TABLE IF NOT EXISTS perfiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT, correo TEXT NOT NULL UNIQUE, perfil TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendiente', alta REAL NOT NULL, confirmado REAL, ultimo_uso REAL,
    perfil_pendiente TEXT, pendiente_desde REAL);
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
    def alta(self, correo, perfil, ahora=None):
        """Guarda lo enviado por el formulario, SIN dar de alta todavía. Devuelve {"resultado", "perfil"}; resultado:
             confirmar  -> hay que mandar el correo de confirmación (alta nueva o cambio de un perfil ya confirmado)
             espera     -> se le acaba de escribir (o hay demasiadas altas en esta hora): no se manda nada
             invalido   -> el correo no vale
           La página responde siempre lo mismo ("revisa tu correo"): así no se puede averiguar desde fuera si una
           dirección está dada de alta."""
        ahora = ahora or time.time()
        correo = correo_valido(correo)
        if not correo:
            return {"resultado": "invalido"}
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
                self.db.execute("INSERT INTO perfiles (correo, perfil, alta) VALUES (?,?,?)", (correo, pj, ahora))
            elif p["estado"] == "pendiente":
                # Sin confirmar: lo último que envía sustituye a lo anterior y el plazo de 7 días vuelve a empezar.
                self.db.execute("UPDATE perfiles SET perfil=?, alta=? WHERE id=?", (pj, ahora, p["id"]))
            else:
                # Ya confirmado: el cambio espera aparte hasta que se confirme; el perfil de ahora no se toca.
                self.db.execute("UPDATE perfiles SET perfil_pendiente=?, pendiente_desde=? WHERE id=?",
                                (pj, ahora, p["id"]))
            self.db.commit()
            return {"resultado": "confirmar", "perfil": self._fila("correo", correo)}

    def confirmar(self, pid, firma, ahora=None):
        """Da de alta el perfil, o aplica el cambio pendiente, si la firma corresponde a ESE perfil. Devuelve la fila
        (con "ya_estaba" si ese enlace ya se había usado) o None si el enlace no vale o ha caducado."""
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
                self.db.execute("UPDATE perfiles SET estado='activo', confirmado=?, ultimo_uso=? WHERE id=?",
                                (ahora, ahora, pid))
                self._sumar("altas")
            else:
                self.db.execute("UPDATE perfiles SET perfil=perfil_pendiente, perfil_pendiente=NULL, pendiente_desde=NULL, "
                                "confirmado=?, ultimo_uso=? WHERE id=?", (ahora, ahora, pid))
                self._sumar("cambios")
            self.db.commit()
            return self._fila("id", pid)

    def usar(self, pid, ahora=None):
        """La empresa ha abierto sus licitaciones desde el enlace del correo: cuenta como uso."""
        with self.lock:
            self.db.execute("UPDATE perfiles SET ultimo_uso=? WHERE id=? AND estado='activo'", (ahora or time.time(), pid))
            self.db.commit()

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
        """Borra los perfiles sin confirmar de hace más de 7 días y los que llevan 12 meses sin usarse; descarta los
        cambios sin confirmar de hace más de 7 días y los envíos de hace más de 90. Devuelve los recuentos."""
        ahora = ahora or time.time()
        with self.lock:
            viejos = [f[0] for f in self.db.execute(
                "SELECT id FROM perfiles WHERE (estado='pendiente' AND alta < ?) "
                "OR (estado='activo' AND coalesce(ultimo_uso, confirmado, alta) < ?)",
                (ahora - PENDIENTE_CADUCA_S, ahora - INACTIVO_CADUCA_S))]
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
            if sin_confirmar:
                self._sumar("caducados_sin_confirmar", sin_confirmar)
            if inactivos:
                self._sumar("caducados_inactivos", inactivos)
            self.db.commit()
        return {"sin_confirmar": sin_confirmar, "inactivos": inactivos, "cambios_descartados": cambios}

    # ── correos ─────────────────────────────────────────────────────────────────────────────────────────────────
    def registrar_envio(self, clase, pid, codigo, detalle, ahora=None):
        with self.lock:
            self.db.execute("INSERT INTO envios (ts, clase, perfil_id, codigo, detalle) VALUES (?,?,?,?,?)",
                            (ahora or time.time(), clase, pid, codigo, (detalle or "")[:300]))
            self.db.commit()

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
