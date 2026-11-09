# Contratos menores que se lanzan desde el PC

Algunos ayuntamientos no dejan entrar a GitHub, así que el flujo semanal no puede bajar sus contratos menores. Esos
se lanzan a mano desde el PC.

## Orden (una línea)

Desde la carpeta del repositorio (`Desktop\app_dinero_publico`), en PowerShell o en cmd:

    python backend/menores_desde_pc.py

Por defecto lanza **Alicante y Santa Cruz de Tenerife**. Para otras, se ponen sus nombres:

    python backend/menores_desde_pc.py alicante santa_cruz burgos

## Qué hace

1. Ejecuta los generadores con la misma salvaguarda que el flujo semanal. Si fallan las descargas o traen menos
   del 90 % de los contratos, se queda el fichero anterior.
2. Tapa los DNI/NIE de los ficheros que hayan cambiado y comprueba que no quede ninguno.
3. Dice qué ha cambiado y escribe las tres órdenes para guardarlo (`git add`, `git commit`, `git push`).
   **No guarda nada por sí sola.** Guardar en main reinicia la web unos minutos: hazlo fuera del refresco nocturno
   (de ~05:00 a ~12:30 UTC).

## Qué fuentes van aquí y desde cuándo

| Fuente | Por qué | Desde |
|---|---|---|
| alicante | Desde GitHub todas las descargas tardan demasiado; desde el PC, bien | 09-11-2026 |
| santa_cruz | El servidor no contesta a GitHub; desde el PC, sí | 09-11-2026 |
| burgos, almeria, sevilla, valencia_capital | Manuales desde octubre (ver `EXCLUIDOS` en `backend/flujo_menores_semanal.py`) | 10-2026 |

Hace falta tener instaladas las librerías de lectura de hojas de cálculo y PDF (en el PC ya están):
`pip install pdfplumber openpyxl xlrd odfpy`.
