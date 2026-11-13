# Dinero Público

Contratación pública, cuentas y sueldos de los ayuntamientos españoles a partir de fuentes oficiales:
https://dinero-publico.com. La aplicación está en `backend/app.py`.

## Pendientes

- **Enlace por contrato en la API de Euskadi** (anotado el 12-11-2026, para otro PR). En
  `_render_fila_contrato_menor` (`backend/app.py`), la nota de los importes sospechosos de Euskadi dice que «esta
  fuente no publica un enlace por contrato». No es así: cada contrato de la API (`api.euskadi.eus/procurements/contracts/...`)
  trae `mainEntityOfPage`, con la página del anuncio en contratacion.euskadi.eus. Hay que guardar ese enlace al
  cargar los contratos (`actualizar_contratos_menores_euskadi.py` y `_euskadi_item_a_contrato`), enlazarlo en la
  fila y cambiar la nota.
- **Unir `_portada_contadores` (#43) y `_portada_cabecera` (#46)** cuando estén fusionados los dos: hacen lo mismo
  (una sola cuenta de la portada para todos los idiomas, y volver a montar las demás si cambia), una para las
  convocatorias y otra para las cifras de arriba y la fecha.
- **Fechas futuras de las fuentes**: `python backend/comprobar_fechas_futuras.py [cache.db] --detalle` las lista.
  La web las muestra tal cual, con aviso; revisarlas una a una y, si procede, avisar a la fuente.
