#!/usr/bin/env bash
# Funciones comunes del refresco nocturno (actualizar-diario.yml), compartidas por sus dos trabajos:
# «provincias» y «extras» (06-11-2026). Se cargan con `source`; necesitan BASE_URL y, para poll_hasta_done,
# INTERVAL y MAX_MIN_PROVINCIA (valor por defecto de su tercer argumento). TOPE_DURO es opcional.

# --- helpers (python3 en una sola línea: si el cuerpo no es JSON
#     válido, json.load lanza, python sale != 0 y el `|| echo` da el
#     valor por defecto -- así nunca aborta el paso) -----------------
get_jobid() {   # job_id de una respuesta JSON, o '' si no hay
  printf '%s' "$1" | python3 -c "import sys,json;print(json.load(sys.stdin).get('job_id',''))" 2>/dev/null || echo ''
}
get_status() {  # status de un job, o 'not_found' ante cualquier fallo
  curl -s --max-time 30 "${BASE_URL}/api/job/$1" | python3 -c "import sys,json;print(json.load(sys.stdin).get('status','not_found'))" 2>/dev/null || echo not_found
}
get_error() {   # campo 'error' de un job (motivo corto, ej. lock de
  # /actualizar-todos ya ocupado) -- distinto de 'log', que en un
  # rechazo por lock viene vacío y no explica nada por sí solo
  curl -s --max-time 30 "${BASE_URL}/api/job/$1" | python3 -c "import sys,json;print(json.load(sys.stdin).get('error') or '(sin detalle)')" 2>/dev/null || echo '(sin detalle)'
}
mostrar_log() {  # imprime el log del job (vive solo en memoria del
  # contenedor -- se pierde en el próximo reinicio, así que hay que
  # volcarlo aquí en cuanto el job termina, no se puede recuperar después)
  curl -s --max-time 30 "${BASE_URL}/api/job/$1" | \
    python3 -c "import sys,json; print('\n'.join(json.load(sys.stdin).get('log', [])))" 2>/dev/null || true
}

# --- Web reiniciándose (2026-10-05) ---------------------------------
# Los dos pasos anteriores guardan en main casi todas las noches y cada guardado hace que Render vuelva a
# desplegar y reinicie la web: durante 1-3 minutos responde 502. Antes se disparaba la primera provincia
# justo en ese hueco, todas las peticiones fallaban y el refresco nocturno se perdía entero (5 de 6 noches
# entre el 30-09 y el 05-10). Ahora:
#  - esperar_web: tras un guardado, espera como mínimo $1 segundos (lo que tarda Render en compilar y
#    reiniciar) y hasta ver 4 respuestas buenas seguidas; como mucho $2 minutos, y si no, fallo de verdad;
#  - post_web: cada disparo reintenta ante 502/503/504/sin respuesta durante como mucho 5 minutos; pasado
#    ese límite devuelve error y queda registrado como fallo (nunca reintenta indefinidamente).
web_responde() {
  [ "$(curl -s --max-time 20 -o /dev/null -w '%{http_code}' "${BASE_URL}/api/diagnostico-arranque" || true)" = "200" ]
}
esperar_web() {
  local min_s="$1" max_min="$2" inicio ok=0 caidas=0 t
  inicio=$(date +%s)
  while true; do
    if web_responde; then ok=$((ok + 1)); else ok=0; caidas=$((caidas + 1)); fi
    t=$(( $(date +%s) - inicio ))
    if [ "$t" -ge "$min_s" ] && [ "$ok" -ge 4 ]; then
      echo "Web estable tras ${t} s (${caidas} comprobaciones sin respuesta durante la espera)."
      return 0
    fi
    if [ "$t" -ge $(( max_min * 60 )) ]; then
      echo "::error::La web no responde de forma estable tras ${max_min} min (${caidas} comprobaciones fallidas)."
      return 1
    fi
    sleep 15
  done
}
post_web() {   # mismos argumentos que curl (el último, la URL); imprime el cuerpo de la respuesta
  local url="${!#}" fin resp codigo
  fin=$(( $(date +%s) + 300 ))
  while true; do
    resp=$(curl -s --max-time 60 -X POST -w $'\n%{http_code}' "$@" || true)
    codigo="${resp##*$'\n'}"
    case "$codigo" in
      000|502|503|504|520|521|522|523|524)
        if [ "$(date +%s)" -ge "$fin" ]; then
          echo "::error::${url#${BASE_URL}}: la web sigue sin responder (HTTP ${codigo}) tras 5 min de reintentos." >&2
          return 1
        fi
        echo "  ${url#${BASE_URL}}: HTTP ${codigo} (¿la web está reiniciándose?), reintento en 30 s" >&2
        sleep 30 ;;
      *)
        printf '%s' "${resp%$'\n'*}"
        return 0 ;;
    esac
  done
}

# Espera a que un job_id llegue a 'done'. Aborta (return 1) si el job
# da 'error', si 'not_found' persiste 3 ciclos seguidos (el
# contenedor se reinició y perdió el estado en memoria), o si se
# agota el presupuesto de ESTA provincia/tarea (return 2: el trabajo
# sigue vivo en el servidor, ver esperar_fin_trabajo). Mientras tanto
# imprime cada ciclo, y ese propio tráfico de polling es el keep-alive.
poll_hasta_done() {
  local job_id="$1" etiqueta="$2" max_min="${3:-$MAX_MIN_PROVINCIA}" notfound=0 st
  local deadline_local=$(( $(date +%s) + max_min * 60 ))
  # 06-11: nunca más allá del tope duro del trabajo (TOPE_DURO, segundos de reloj), si lo hay: una provincia
  # lanzada justo antes de agotarse la noche podía esperar sus 100 min enteros y acercar el job al límite de 6 h.
  if [ "${TOPE_DURO:-0}" -gt 0 ] && [ "$deadline_local" -gt "$TOPE_DURO" ]; then deadline_local=$TOPE_DURO; fi
  while true; do
    st=$(get_status "$job_id")
    echo "$(date -u +%H:%M:%S)Z  ${etiqueta}=${st}"

    if [ "$st" = "error" ]; then
      echo "::error::${etiqueta} terminó en 'error'. No se commitea."
      echo "  motivo: $(get_error "$job_id")"
      echo "--- log de ${etiqueta} ---"
      mostrar_log "$job_id"
      return 1
    fi
    if [ "$st" = "done" ]; then
      echo "--- log de ${etiqueta} ---"
      mostrar_log "$job_id"
      return 0
    fi

    if [ "$st" = "not_found" ]; then
      notfound=$(( notfound + 1 ))
    else
      notfound=0
    fi
    if [ "$notfound" -ge 3 ]; then
      echo "::error::${etiqueta}: job_id no encontrado 3 ciclos seguidos: el contenedor se reinició a mitad del lote y perdió el estado en memoria. Aborto sin commitear."
      return 1
    fi

    if [ "$(date +%s)" -ge "$deadline_local" ]; then
      echo "::warning::${etiqueta} lleva ${max_min} min sin terminar (status=$st)."
      return 2
    fi
    sleep "$INTERVAL"
  done
}
