# Embudo de licitaciones — informe del encargo nocturno (1-11-2026)

**Encargo:** que una empresa rellene un formulario corto y vea solo las licitaciones abiertas a las que puede optar.

**Estado:** hecho y probado en local. Rama **`wip/filtro-embudo`**, solo en este PC (no subida a GitHub, sin PR). No he
tocado `main`, ni Render, ni variables de entorno, ni el ADMIN_TOKEN.

---

## 0. Lo primero: por qué la rama no se llama `wip/filtro-licitaciones`

El encargo pedía trabajar en la rama nueva `wip/filtro-licitaciones`, pero **esa rama ya existe: es el PR #6** (filtro
con perfiles guardados en socios.db y correo semanal), que no se toca y cuya fusión está prevista para el **martes
03-11 por la tarde**. Para no pisarlo he creado **`wip/filtro-embudo`**, que sale del último commit del PR #6
(1b9b575) porque necesita su columna `requisitos` (la cifra de solvencia del anuncio, la clasificación pedida, la
duración y los lotes). Consecuencia: **esta rama solo se puede fusionar después del PR #6.**

Carpeta de trabajo: `Desktop/wt_filtro_embudo`.

Commits (pequeños, cada uno probado):

| Commit | Qué |
|---|---|
| 6233676 | Motor y páginas del embudo (`backend/filtro_embudo.py`) |
| 2bf3aad | Ruta en la web, apagada salvo `FILTRO_EMBUDO=1`, y pruebas (`backend/filtro_embudo_prueba.py`) |
| 0b25393 | Este informe y las capturas (`docs/filtro_embudo/`) |
| 2c8ba87 (02-11) | **Cambio pedido por César:** «fuera de alcance» por solvencia solo con la cifra del anuncio (§2 bis) |
| (02-11, 2.º) | **Cambio pedido por César:** «Desproporcionado (estimación nuestra)» a 0,75 × VAM y texto «El anuncio exige X €» (§2 ter) |

---

## 1. Qué está hecho

Página nueva **`/licitaciones/filtro`** (también funciona con `/gl/`, `/ca/`, `/eu/` delante, aunque sin traducir).

**Formulario** (seis preguntas, todas en una pantalla, funciona en móvil y también sin JavaScript):

1. **Sector de actividad**: las 45 divisiones CPV de 2 cifras, con buscador (escribe «limpieza» y quedan las dos que
   sirven). Selección múltiple.
2. **Dónde puede trabajar**: «Toda España», o comunidades (marca todas sus provincias) o provincias sueltas.
3. **Facturación anual** del mejor de los tres últimos años, en tramos (los mismos ocho del PR #6: <60k, 60-150k,
   150-300k, 300-600k, 600k-1,5M, 1,5-3M, 3-10M, >10M).
4. **Personas en plantilla**, en tramos (1-5, 6-10, 11-25, 26-50, 51-250, >250).
5. **¿Clasificación de contratista?** No / Sí → grupo-subgrupo-categoría opcional («C2-4, G6-3»).
6. **Importe que le interesa**, mínimo y máximo opcionales, sin IVA.

**Resultado**, en tres grupos, cada ficha con el porqué en lenguaje llano:

- **ENCAJA** (verde)
- **ENCAJA CON CONDICIONES** (ocre), diciendo cuál: «requiere clasificación…», «depende de su cifra exacta de
  facturación…», «compruebe que su clasificación cubre…»
- **FUERA DE ALCANCE** (gris), con contador y **desplegable cerrado**.

Arriba, tres cifras de resumen; debajo del resultado, el formulario con sus datos para cambiarlos. La página explica
los criterios en un desplegable «Cómo decidimos si una licitación encaja».

**Privacidad, como pedía el encargo:**
- El formulario va por **POST**: los datos no aparecen en la dirección ni en el registro del servidor (lo he
  comprobado en el registro de la prueba: solo sale `POST /licitaciones/filtro`).
- Un GET con parámetros (`?cpv=90&…`) los **ignora** y da el formulario vacío, para que nadie los meta en enlaces que
  acaben en los registros.
- **Sin cookies** (comprobado en la respuesta y en el navegador), `Cache-Control: no-store`, `noindex`,
  `Referrer-Policy: no-referrer`. **No se crea socios.db** ni se escribe nada en disco.
- Sin publicidad, sin analítica, sin recursos de terceros.

---

## 2. Criterios de encaje (y de dónde salen)

Cada **lote** se evalúa por separado (un lote pequeño de un contrato grande puede encajar). Los lotes iguales de una
misma licitación van juntos en una ficha.

| Criterio | Regla | Efecto |
|---|---|---|
| Plazo | Fin de plazo posterior a la hora actual (peninsular) | Si está cerrado, no sale |
| Sector | Algún CPV del contrato o del lote empieza por una división marcada | Si no, no sale |
| Zona | Provincia del lugar de ejecución (NUTS; si falta, la de la fila o el CP del órgano); con solo la comunidad, entra si marcó alguna provincia de ella; «toda España» admite todo | Si no, no sale |
| Importe | Importe sin IVA del lote o del contrato dentro del rango | Si no, no sale |
| **Solvencia económica** (art. 87.3.a LCSP) | Pueden pedir hasta **1,5 × valor anual medio** (VAM = presupuesto sin IVA / duración en años, mínimo 1). **Si el anuncio da la cifra, manda esa.** | Tramo bajo ya llega → encaja. En medio → **con condiciones**. Ni el tope del tramo llega: con cifra del anuncio → **fuera de alcance** («El anuncio exige X € de facturación anual: su empresa no llega»); sin cifra → **con condiciones** («puede que el pliego pida menos: revise la solvencia»), salvo que no llegue ni a **0,75 × VAM** (la mitad del máximo legal) → **fuera de alcance**, etiqueta **«Desproporcionado (estimación nuestra)»** |
| Procedimiento sumario (art. 159.6) | Abierto simplificado con VE < 80.000 € (obras) o < 60.000 € (resto) | No se pide solvencia |
| **Clasificación** (art. 77 LCSP) | Obras con valor estimado ≥ 500.000 € (no sumario) | Sin clasificación → **con condiciones: «requiere clasificación»**. Nunca se oculta por esto solo. Si la suya cubre la pedida, encaja y además le sirve como solvencia |
| **Trabajadores** | Si el VAM pasa de 100.000 € por persona del tope de su tramo | Solo un aviso «su plantilla puede quedarse corta». **No cambia el grupo** |
| Avisos sin efecto | El anuncio pide plantilla mínima, experiencia o certificados; no dice la duración (se supone 1 año) o el lugar; cierra en menos de 2 días | Solo informativos |

Orden: ENCAJA, CON CONDICIONES, FUERA; dentro de cada grupo, por fecha límite. Como mucho 60 fichas por grupo en
pantalla (lo que pase se cuenta y se sugiere afinar).

---

## 2 bis. Cambio del 02-11: «fuera de alcance» solo con la cifra del anuncio

Decisión de César: el 1,5 × VAM es el **máximo** que permite la ley, no lo que pide cada pliego. Si el anuncio no
trae la cifra (`umbral_eco`) y la facturación no llega a ese máximo, la licitación ya **no** va a «fuera de alcance»
sino a **«encaja con condiciones»**, con el texto «su empresa no llega a ese tope, pero puede que el pliego pida menos:
revise la solvencia en el pliego». Solo queda fuera cuando la cifra viene del anuncio (del lote, si es un lote; la
cifra del contrato entero no se aplica a sus lotes).

**Efecto medido** con la copia del 30-10 (4.711 abiertas; solo el 8 % trae la cifra):

| Perfil inventado | Antes (encaja / cond. / fuera) | Ahora |
|---|---|---|
| Limpieza, 1-5 personas, Murcia, 150-300k | 10 / 6 / 5 | 10 / 11 / **0** |
| Constructora 11-25, Murcia + C. Valenciana, 1,5-3M, sin clasificación | 181 / 32 / 16 | 181 / 47 / **1** |
| Constructora clasificada, toda España, 3-10M | 1.277 / 285 / 26 | 1.277 / 309 / **2** |
| Informática 1-5, toda España, <60k, 10k-200k | 62 / 69 / 61 | 62 / 124 / **6** |
| Perfil de las capturas (limpieza, Murcia + C. Valenciana) | 33 / 14 / 13 | 33 / 27 / **0** |

**Ojo:** con esta regla, «fuera de alcance» queda casi vacío y una **obra de 30 millones para una empresa de 5
personas y 300.000 € de facturación sale como «encaja con condiciones»** si el anuncio no trae la cifra (que es lo
normal). Es lo contrario del ejemplo del encargo. **Resuelto con el cambio siguiente (§2 ter).**

## 2 ter. Cambio del 02-11 (2.º): «Desproporcionado (estimación nuestra)»

Decisión de César. Solvencia, de arriba abajo:

1. **Con cifra en el anuncio** y la empresa no llega ni con el tope de su tramo → **fuera de alcance**, texto «El
   anuncio exige X € de facturación anual: su empresa no llega.» Sin etiqueta. La cifra del anuncio siempre manda:
   si el anuncio pide poco, no se aplica la regla de desproporción aunque el contrato sea grande.
2. **Sin cifra en el anuncio** y la empresa no llega ni a **0,75 × VAM** (la mitad del máximo legal) → **fuera de
   alcance**, con la etiqueta **«Desproporcionado (estimación nuestra)»** encima del título y el texto: «Aunque el
   pliego pidiera la mitad del máximo legal (X € al año), su empresa no llegaría; solo sería viable en UTE o
   apoyándose en la solvencia de otra empresa (art. 75 LCSP).»
3. **Sin cifra**, entre 0,75 y 1,5 × VAM → **con condiciones** («revise la solvencia»), como en §2 bis.

Se compara con el **tope** del tramo de facturación (lo más favorable para la empresa). Ejemplo, tramo 150-300k:
un contrato de 400.000 € al año queda con condiciones (0,75 × 400.000 = 300.000, llega justo); uno de 401.000 €,
desproporcionado. La obra de 30 millones para 5 personas vuelve a salir **fuera de alcance (desproporcionado)**.

**Efecto medido** (misma copia del 30-10):

| Perfil inventado | Original | §2 bis | Ahora |
|---|---|---|---|
| Limpieza, 1-5 personas, Murcia, 150-300k | 10 / 6 / 5 | 10 / 11 / 0 | 10 / 9 / **2** |
| Constructora 11-25, Murcia + C. Valenciana, 1,5-3M, sin clasificación | 181 / 32 / 16 | 181 / 47 / 1 | 181 / 42 / **6** |
| Constructora clasificada, toda España, 3-10M | 1.277 / 285 / 26 | 1.277 / 309 / 2 | 1.277 / 299 / **12** |
| Informática 1-5, toda España, <60k, 10k-200k | 62 / 69 / 61 | 62 / 124 / 6 | 62 / 104 / **26** |
| Perfil de las capturas (limpieza, Murcia + C. Valenciana) | 33 / 14 / 13 | 33 / 27 / 0 | 33 / 22 / **5** (las 5 desproporcionadas) |

Al escribir las pruebas apareció un fallo, ya corregido antes del commit: con la cifra del anuncio dentro del tramo
(por ejemplo 200.000 € para una empresa de 150-300k), la regla de desproporción se aplicaba igualmente y la sacaba
de alcance. Ahora solo se aplica cuando el anuncio no trae la cifra.

## 3. Capturas

Con la copia de datos del 30-10 y un perfil inventado (limpieza, Murcia + Comunitat Valenciana, 150-300k, 1-5
personas, sin clasificación), captura hecha el 02-11: **31 encajan, 22 con condiciones, 5 fuera de alcance** (las 5
«desproporcionadas»; en la tabla de §2 ter salen 33 porque se midió la noche del 01-11, antes de que cerraran 2).

| | |
|---|---|
| Formulario (escritorio) | `docs/filtro_embudo/1_formulario_escritorio.png` |
| Formulario (móvil, 375 px) | `docs/filtro_embudo/1_formulario_movil.png` |
| Resultado (escritorio) | `docs/filtro_embudo/3_resultado_escritorio.png` |
| Resultado (móvil) | `docs/filtro_embudo/3_resultado_movil.png` |
| Ficha «Desproporcionado» (escritorio) | `docs/filtro_embudo/5_fuera_desproporcionado_escritorio.png` |
| Ficha «Desproporcionado» (móvil) | `docs/filtro_embudo/5_fuera_desproporcionado_movil.png` |

Las capturas de página entera (16.000 px de alto) están fuera del repositorio, en el scratchpad de esta sesión
(`…/1cee7279-…/scratchpad/capturas/`).

---

## 4. Cómo probarlo en local

**Pruebas del motor** (rápidas, sin web ni base de datos; 46 casos inventados, entre ellos «obra de 30 millones para
una empresa de 5 personas»: desproporcionado sin cifra en el anuncio, «El anuncio exige…» con ella; y el límite exacto
de 0,75 × VAM):

```
cd Desktop/wt_filtro_embudo
python backend/filtro_embudo_prueba.py
```

**La web** (pesado: ~1 GB de RAM y ~1 minuto de arranque; no lanzar junto a otros procesos pesados). Hace falta una
**copia** de cache.db con la columna `requisitos` (la de main no la tiene hasta el PR #6). Yo he usado la copia del
ensayo del 30-10, copiada a mi scratchpad:

```
set DATA_DIR=<carpeta con la COPIA de cache.db>
set DINERO_HILOS_EN_POST_FORK=1          (no arranca los hilos de fondo)
set FILTRO_EMBUDO=1
python servir_wsgi.py Desktop/wt_filtro_embudo/backend     (sirve app.app en 127.0.0.1:8765)
```

y abrir `http://127.0.0.1:8765/licitaciones/filtro`.

La prueba automática completa (Playwright en escritorio, móvil de 375 px y sin JavaScript; 36 comprobaciones,
incluidas cookies, no-store, socios.db y barra horizontal) es `prueba_embudo_web.py` en el scratchpad de la sesión:
`python prueba_embudo_web.py encendido|apagado <backend> <datos> <capturas>`. Resultado: **0 fallos** en los dos modos
(apagado = 404 en GET y POST, como quedaría al desplegar sin la variable).

---

## 5. Decisiones que he tomado y por qué

1. **Rama `wip/filtro-embudo` sobre el PR #6** (ver §0). Alternativa descartada: rama desde main sin `requisitos`;
   habría perdido la cifra de solvencia del anuncio («manda el pliego»), la clasificación pedida y la duración.
2. **Página aparte del formulario del PR #6** (`/filtro-licitaciones`), no una modificación de él: aquel guarda
   perfiles y manda correos; este no guarda nada. Comparten el motor (lotes, lugar, clasificación, sumario).
   He añadido un evaluador propio (`filtro_embudo.evaluar`) en vez de cambiar el del PR #6 porque los grupos son
   distintos (allí «requiere clasificación» sin tenerla es descarte o UTE; aquí es «con condiciones», como pedía el
   encargo).
3. **Apagada salvo `FILTRO_EMBUDO=1`**, como el resto de borradores (alertas, formulario del PR #6). Al fusionar no
   aparece nada hasta que pongas la variable. Ninguna página la enlaza todavía.
4. **POST y no GET**: GET dejaría el perfil de la empresa en los registros de Render y en el historial. Contrapartida:
   el resultado no se puede compartir con un enlace.
5. **Plazo abierto sin margen**: el motor del PR #6 quita las que cierran en menos de 2 días; aquí, como pedía el
   encargo («solo con plazo abierto»), salen todas las abiertas, con el aviso «cierra en menos de 2 días».
6. **Trabajadores = tope del tramo** para el aviso (el más favorable): así el aviso solo sale cuando ni en lo más
   alto del tramo encaja bien. 100.000 € de VAM por persona es la misma cifra orientativa que usa el PR #6.
7. **El tramo de facturación decide tres casos** (llega, no llega, depende; «no llega» solo saca de alcance con la
   cifra del anuncio, ver §2 bis). En el tramo «menos de 60.000 €»
   cualquier contrato con solvencia sale como «depende de su cifra exacta», porque el tramo empieza en 0.
8. **Clasificación con «Sí» sin códigos**: «con condiciones: compruebe que la suya la cubre» (no puedo saberlo).
9. **«Toda España»** también admite obras cuyo anuncio no dice el lugar (el PR #6 las quita para no ofrecer obras de
   Huelva a una constructora de Murcia; aquí la empresa ha dicho que trabaja en toda España).
10. **Tuteo/usted**: la página trata de usted (público empresa). El formulario del PR #6 tutea. Ver §6.

---

## 6. Lo que necesita que decidas

1. **¿Fusionar después del PR #6?** La rama está lista para subirla a GitHub como PR en borrador cuando me lo digas
   (no la he subido: el encargo decía no tocar producción y tu regla es revisar antes de subir).
2. **¿Encender?** Poner `FILTRO_EMBUDO=1` en Render cuando quieras (no lo he tocado).
3. **¿Convivir con el formulario del PR #6 o sustituirlo?** Son dos puertas al mismo motor: una anónima e
   inmediata (esta) y otra con correo semanal y datos guardados. Propuesta: esta como entrada pública y, al pie del
   resultado, un enlace «recibir estas licitaciones cada semana» al del PR #6 cuando se encienda.
4. **Usted o tú** en las dos páginas (ahora están distintas).
5. **Enlace desde la web**: no hay ninguno. ¿Desde /convocatorias («¿Cuáles puede ganar mi empresa?»)?
6. **Traducciones gl/ca/eu**: la página responde con prefijo pero en castellano.
7. **Texto legal**: la página dice «Es una ayuda, no un informe jurídico». Que lo mire el abogado junto con lo del
   PR #6.
8. ~~¿Un tope para lo desproporcionado?~~ **Decidido el 02-11**: 0,75 × VAM con la etiqueta «Desproporcionado
   (estimación nuestra)» (§2 ter).

---

## 7. Lo que no se puede aplicar por falta de datos (no lo he inventado)

Medido en la copia del 30-10 (4.711 licitaciones abiertas con requisitos leídos):

- **Cifra de solvencia del pliego**: solo **382** (8 %) la traen en el anuncio. En el resto se usa el tope legal
  (1,5 × VAM), la ficha lo dice («cálculo nuestro, el anuncio no da la cifra») y, desde el 02-11, si no llega se
  queda en «con condiciones», salvo que no llegue ni a la mitad (desproporcionado, §2 ter). El pliego (PCAP) no lo leemos; esa
  sería la «fase 2» ya apuntada en el PR #6.
- **Clasificación pedida**: 181 de las 270 obras ≥ 500.000 € dicen el grupo; en las otras 89 solo puedo calcular la
  categoría a partir del VAM y la ficha dice «el anuncio no dice el grupo».
- **Duración**: falta en 48 (1 %); se supone un año y se avisa.
- **Lugar de los lotes**: muchos lotes heredan el lugar del contrato. Ejemplo visto en la prueba: un lote «sito en la
  provincia de Alicante» de un contrato del IVASS sale como Valencia. Es un límite del anuncio, no del filtro.
- **Volumen de negocio exacto, experiencia, medios personales y certificados de la empresa**: el formulario no los
  pregunta (no estaban en el encargo). Experiencia y certificados pedidos salen como aviso informativo.
- **Plantilla mínima exigida**: el anuncio solo dice que la piden (OXR-PLANTILLA), no cuántas personas; sale como aviso.
- **Licitaciones sin la columna `requisitos`** (las que la web leyó antes del PR #6): no salen hasta la relectura de
  4 meses que hace el PR #6 al arrancar.
- **Importe**: 21 abiertas sin presupuesto ni valor estimado no se pueden evaluar y no salen.
