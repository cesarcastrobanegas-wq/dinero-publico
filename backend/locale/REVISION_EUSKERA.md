# Revisión del euskera: los 79 textos con variables

Generado el 01-10-2026 a partir de backend/locale/eu.po. Página para revisar y dejar correcciones: https://claude.ai/artifact/UVvTXvWAT4o7ZfpPFqg95m (privada hasta que se comparta). Dejar las variables {así} sin traducir.

## 1
- **ES:** Concejales ({n})
- **EU actual:** Zinegotziak ({n})
- **Así queda:** Zinegotziak (1) / Zinegotziak (50)
- **Variables:** {n} = un número (cualquier cantidad)
- **Corrección:** 

## 2
- **ES:** Retribuciones de concejales publicadas por el ayuntamiento ({n})
- **EU actual:** Udalak argitaratutako zinegotzien ordainsariak ({n})
- **Así queda:** Udalak argitaratutako zinegotzien ordainsariak (1) / Udalak argitaratutako zinegotzien ordainsariak (50)
- **Variables:** {n} = un número (cualquier cantidad)
- **Corrección:** 

## 3
- **ES:** en los últimos {n} años ({desde}-{hasta})
- **EU actual:** azken urteetan ({desde}-{hasta}, {n} urte)
- **Así queda:** azken urteetan (2021-2026, 1 urte) / azken urteetan (2022-2026, 50 urte)
- **Variables:** {n} = un número (cualquier cantidad); {desde} = un año; {hasta} = un año
- **Corrección:** 

## 4
- **ES:** La empresa con más contratos menores adjudicados {periodo} es <strong>{empresa}</strong>, que concentra el {pct} % ({num} de {den} con adjudicatario identificado).
- **EU actual:** Kontratu txiki gehien esleitu zaion enpresa {periodo}: <strong>{empresa}</strong>; % {pct} biltzen du ({num}/{den}, esleipendun identifikatua dutenen artean).
- **Así queda:** Kontratu txiki gehien esleitu zaion enpresa azken urteetan (2022-2026, 5 urte): Construcciones Ejemplo S.L.; % 35 biltzen du (12/30, esleipendun identifikatua dutenen artean). / Kontratu txiki gehien esleitu zaion enpresa eskura dauden datuetan: Garbiketak S.A.; % 8 biltzen du (1/8, esleipendun identifikatua dutenen artean).
- **Variables:** {periodo} = otra frase ya traducida con el periodo, p. ej. «azken urteetan (2022-2026, 5 urte)»; {empresa} = el nombre de una empresa; {pct} = un porcentaje, sin el símbolo; {num} = un número; {den} = un número
- **Corrección:** 

## 5
- **ES:** La empresa con más contratos formales de los que tenemos de este municipio es <strong>{empresa}</strong>, que concentra el {pct} % ({num} de {den} con adjudicatario identificado).
- **EU actual:** Udalerri honetatik ditugun kontratu formaletan kontratu gehien dituen enpresa: <strong>{empresa}</strong>; % {pct} biltzen du ({num}/{den}, esleipendun identifikatua dutenen artean).
- **Así queda:** Udalerri honetatik ditugun kontratu formaletan kontratu gehien dituen enpresa: Construcciones Ejemplo S.L.; % 35 biltzen du (12/30, esleipendun identifikatua dutenen artean). / Udalerri honetatik ditugun kontratu formaletan kontratu gehien dituen enpresa: Garbiketak S.A.; % 8 biltzen du (1/8, esleipendun identifikatua dutenen artean).
- **Variables:** {empresa} = el nombre de una empresa; {pct} = un porcentaje, sin el símbolo; {num} = un número; {den} = un número
- **Corrección:** 

## 6
- **ES:** <strong>{empresa}</strong> acumula el {pct}% de las adjudicaciones ({n} de {total} contratos) — posible concentración de contratación.
- **EU actual:** <strong>{empresa}</strong> enpresak esleipenen % {pct} metatzen du ({total} kontratutik {n}) — kontratazioaren kontzentrazio posiblea.
- **Así queda:** Construcciones Ejemplo S.L. enpresak esleipenen % 35 metatzen du (120 kontratutik 1) — kontratazioaren kontzentrazio posiblea. / Garbiketak S.A. enpresak esleipenen % 8 metatzen du (8.131 kontratutik 50) — kontratazioaren kontzentrazio posiblea.
- **Variables:** {empresa} = el nombre de una empresa; {pct} = un porcentaje, sin el símbolo; {n} = un número (cualquier cantidad); {total} = un número total
- **Aviso:** «{total}tik» cambia según el número (50 → «50etik»).
- **Corrección:** 

## 7
- **ES:** <strong>{empresa}</strong> concentra el {pct}% del importe total adjudicado ({importe}).
- **EU actual:** <strong>{empresa}</strong> enpresak esleitutako zenbateko osoaren % {pct} biltzen du ({importe}).
- **Así queda:** Construcciones Ejemplo S.L. enpresak esleitutako zenbateko osoaren % 35 biltzen du (1.234.567,89 €). / Garbiketak S.A. enpresak esleitutako zenbateko osoaren % 8 biltzen du (45.000,00 €).
- **Variables:** {empresa} = el nombre de una empresa; {pct} = un porcentaje, sin el símbolo; {importe} = una cantidad en euros, ya con el símbolo €
- **Corrección:** 

## 8
- **ES:** {n} contrato
- **EU actual:** {n} kontratu
- **Así queda:** 1 kontratu / 50 kontratu
- **Variables:** {n} = un número (cualquier cantidad)
- **Corrección:** 

## 9
- **ES:** {n} contratos
- **EU actual:** {n} kontratu
- **Así queda:** 1 kontratu / 50 kontratu
- **Variables:** {n} = un número (cualquier cantidad)
- **Corrección:** 

## 10
- **ES:** hace {m} min
- **EU actual:** duela {m} min
- **Así queda:** duela 5 min / duela 41 min
- **Variables:** {m} = minutos
- **Corrección:** 

## 11
- **ES:** hace {h}h {m}min
- **EU actual:** duela {h}h {m}min
- **Así queda:** duela 1h 5min / duela 3h 41min
- **Variables:** {h} = horas; {m} = minutos
- **Corrección:** 

## 12
- **ES:** Buscando — {municipio}
- **EU actual:** Bilatzen — {municipio}
- **Así queda:** Bilatzen — Bilbao / Bilatzen — Arrasate/Mondragón
- **Variables:** {municipio} = el nombre de un municipio (en su forma oficial)
- **Corrección:** 

## 13
- **ES:** Descargando datos de {fuente}…
- **EU actual:** Datuak deskargatzen: {fuente}…
- **Así queda:** Datuak deskargatzen: PLACE… / Datuak deskargatzen: Euskadi…
- **Variables:** {fuente} = el nombre corto de una fuente de datos
- **Aviso:** Construcción tipo etiqueta («X: {variable}») para no tener que declinar el nombre: correcta, pero poco natural en una frase.
- **Corrección:** 

## 14
- **ES:** Página {p} de {n} · {t} resultados
- **EU actual:** {p}/{n} orria · {t} emaitza
- **Así queda:** 3/1 orria · 1.234 emaitza / 21/50 orria · 1 emaitza
- **Variables:** {p} = una posición en un ranking; {n} = un número (cualquier cantidad); {t} = número de resultados
- **Corrección:** 

## 15
- **ES:** {n} contratos · total acumulado {importe}
- **EU actual:** {n} kontratu · metatutako guztizkoa: {importe}
- **Así queda:** 1 kontratu · metatutako guztizkoa: 1.234.567,89 € / 50 kontratu · metatutako guztizkoa: 45.000,00 €
- **Variables:** {n} = un número (cualquier cantidad); {importe} = una cantidad en euros, ya con el símbolo €
- **Corrección:** 

## 16
- **ES:**  · mostrando los primeros {n}
- **EU actual:**  · lehenengo {n}ak erakusten
- **Así queda:**  · lehenengo 1ak erakusten /  · lehenengo 50ak erakusten
- **Variables:** {n} = un número (cualquier cantidad)
- **Aviso:** Sufijo pegado al número: «{n}ak». Según el número cambia la forma (p. ej. «lehenengo 50ak», «lehenengo 1ak»).
- **Corrección:** 

## 17
- **ES:** {n} empresa(s) vinculada(s) · total global {importe}
- **EU actual:** {n} enpresa lotu · guztizko orokorra: {importe}
- **Así queda:** 1 enpresa lotu · guztizko orokorra: 1.234.567,89 € / 50 enpresa lotu · guztizko orokorra: 45.000,00 €
- **Variables:** {n} = un número (cualquier cantidad); {importe} = una cantidad en euros, ya con el símbolo €
- **Corrección:** 

## 18
- **ES:** {n} contrato(s)
- **EU actual:** {n} kontratu
- **Así queda:** 1 kontratu / 50 kontratu
- **Variables:** {n} = un número (cualquier cantidad)
- **Corrección:** 

## 19
- **ES:** {n} municipio(s) encontrado(s).
- **EU actual:** {n} udalerri aurkitu dira.
- **Así queda:** 1 udalerri aurkitu dira. / 50 udalerri aurkitu dira.
- **Variables:** {n} = un número (cualquier cantidad)
- **Corrección:** 

## 20
- **ES:** Usamos cookies propias y de terceros (Google Analytics y, en el futuro, publicidad de Google AdSense) para analizar el uso del sitio y, si las aceptas, mostrar anuncios — {enlace}.
- **EU actual:** Cookie propioak eta hirugarrenenak erabiltzen ditugu (Google Analytics eta, etorkizunean, Google AdSenseren publizitatea) webgunearen erabilera aztertzeko eta, onartzen badituzu, iragarkiak erakusteko — {enlace}.
- **Así queda:** Cookie propioak eta hirugarrenenak erabiltzen ditugu (Google Analytics eta, etorkizunean, Google AdSenseren publizitatea) webgunearen erabilera aztertzeko eta, onartzen badituzu, iragarkiak erakusteko — informazio gehiago.
- **Variables:** {enlace} = un enlace con el texto «más información» ya traducido
- **Corrección:** 

## 21
- **ES:** lote {lote}
- **EU actual:** {lote}. lotea
- **Así queda:** 3. lotea / 12. lotea
- **Variables:** {lote} = número de lote
- **Corrección:** 

## 22
- **ES:** {n} lotes
- **EU actual:** {n} lote
- **Así queda:** 1 lote / 50 lote
- **Variables:** {n} = un número (cualquier cantidad)
- **Corrección:** 

## 23
- **ES:** lotes {lotes}
- **EU actual:** loteak: {lotes}
- **Así queda:** loteak: 1, 2, 5 / loteak: 4, 7
- **Variables:** {lotes} = lista de números de lote
- **Corrección:** 

## 24
- **ES:** Buscar {empresa} en el {registro}
- **EU actual:** Bilatu {empresa} hemen: {registro}
- **Así queda:** Bilatu Construcciones Ejemplo S.L. hemen: Registro Mercantil / Bilatu Garbiketak S.A. hemen: Registro de Fundaciones
- **Variables:** {empresa} = el nombre de una empresa; {registro} = nombre del registro donde buscar la empresa
- **Aviso:** Construcción tipo etiqueta («X: {variable}») para no tener que declinar el nombre: correcta, pero poco natural en una frase.
- **Corrección:** 

## 25
- **ES:** {n} contratos menores (fuente agregadora regional); {pct} % con adjudicatario identificado; años cubiertos y frescura: no disponibles (en un registro agregado, no tener contratos recientes significa no haber contratado)
- **EU actual:** {n} kontratu txiki (eskualdeko iturri biltzailea); % {pct} esleipendun identifikatuarekin; estalitako urteak eta freskotasuna: ez daude eskuragarri (erregistro bateratu batean, kontratu berririk ez izateak kontratatu ez izana esan nahi du)
- **Así queda:** 1 kontratu txiki (eskualdeko iturri biltzailea); % 35 esleipendun identifikatuarekin; estalitako urteak eta freskotasuna: ez daude eskuragarri (erregistro bateratu batean, kontratu berririk ez izateak kontratatu ez izana esan nahi du) / 50 kontratu txiki (eskualdeko iturri biltzailea); % 8 esleipendun identifikatuarekin; estalitako urteak eta freskotasuna: ez daude eskuragarri (erregistro bateratu batean, kontratu berririk ez izateak kontratatu ez izana esan nahi du)
- **Variables:** {n} = un número (cualquier cantidad); {pct} = un porcentaje, sin el símbolo
- **Corrección:** 

## 26
- **ES:** {n} contratos menores{origen}; {cubiertos}/{esperados} años desde {desde}; último {ultima}{dias}; {pct} % con adjudicatario identificado
- **EU actual:** {n} kontratu txiki{origen}; {cubiertos}/{esperados} urte {desde}tik; azkena: {ultima}{dias}; % {pct} esleipendun identifikatuarekin
- **Así queda:** 1 kontratu txiki; 4/5 urte 2021tik; azkena: 15/09/2026 (16 egun); % 35 esleipendun identifikatuarekin / 50 kontratu txiki (PLACEren jarioa bakarrik); 5/5 urte 2022tik; azkena: 02/01/2025; % 8 esleipendun identifikatuarekin
- **Variables:** {n} = un número (cualquier cantidad); {origen} = texto opcional (otra frase ya traducida) o vacío; {cubiertos} = años con datos; {esperados} = años que debería haber; {desde} = un año; {ultima} = fecha del último contrato; {dias} = texto opcional entre paréntesis con días (otra frase ya traducida); {pct} = un porcentaje, sin el símbolo
- **Aviso:** Sufijo «-tik» pegado al año: con 2021 debería ser «2021etik», con 2022 «2022tik». Una sola plantilla no sirve para todos.
- **Corrección:** 

## 27
- **ES:**  ({n} días)
- **EU actual:**  ({n} egun)
- **Así queda:**  (1 egun) /  (50 egun)
- **Variables:** {n} = un número (cualquier cantidad)
- **Corrección:** 

## 28
- **ES:** Último ejercicio rendido: {ult} (exigible hoy: {exigible}) -- {estado}
- **EU actual:** Aurkeztutako azken ekitaldia: {ult} (gaur eskatzekoa: {exigible}) -- {estado}
- **Así queda:** Aurkeztutako azken ekitaldia: 2023 (gaur eskatzekoa: 2024) -- egunean / Aurkeztutako azken ekitaldia: 2021 (gaur eskatzekoa: 2024) -- 3 urteko atzerapena
- **Variables:** {ult} = un año (último ejercicio presentado); {exigible} = un año (el que se debería haber presentado); {estado} = otra frase ya traducida: «al día» o «N años de retraso»
- **Corrección:** 

## 29
- **ES:** {n} año de retraso
- **EU actual:** {n} urteko atzerapena
- **Así queda:** 1 urteko atzerapena / 50 urteko atzerapena
- **Variables:** {n} = un número (cualquier cantidad)
- **Corrección:** 

## 30
- **ES:** {n} años de retraso
- **EU actual:** {n} urteko atzerapena
- **Así queda:** 1 urteko atzerapena / 50 urteko atzerapena
- **Variables:** {n} = un número (cualquier cantidad)
- **Corrección:** 

## 31
- **ES:** Publica el sueldo de {n} concejales con nombre e importe y el del alcalde (ISPA)
- **EU actual:** {n} zinegotziren soldata argitaratzen du, izen eta zenbatekoarekin, eta alkatearena (ISPA)
- **Así queda:** 1 zinegotziren soldata argitaratzen du, izen eta zenbatekoarekin, eta alkatearena (ISPA) / 50 zinegotziren soldata argitaratzen du, izen eta zenbatekoarekin, eta alkatearena (ISPA)
- **Variables:** {n} = un número (cualquier cantidad)
- **Corrección:** 

## 32
- **ES:** Publica el sueldo de {n} concejales con nombre e importe
- **EU actual:** {n} zinegotziren soldata argitaratzen du, izen eta zenbatekoarekin
- **Así queda:** 1 zinegotziren soldata argitaratzen du, izen eta zenbatekoarekin / 50 zinegotziren soldata argitaratzen du, izen eta zenbatekoarekin
- **Variables:** {n} = un número (cualquier cantidad)
- **Corrección:** 

## 33
- **ES:** {num}/{den} contratos formales con adjudicatario identificado
- **EU actual:** {num}/{den} kontratu formal esleipendun identifikatuarekin
- **Así queda:** 12/30 kontratu formal esleipendun identifikatuarekin / 1/8 kontratu formal esleipendun identifikatuarekin
- **Variables:** {num} = un número; {den} = un número
- **Corrección:** 

## 34
- **ES:** {num}/{den} adjudicatarios conocidos con directivo identificado ({num_f}/{den_f} formales + {num_m}/{den_m} menores)
- **EU actual:** {num}/{den} esleipendun ezagun zuzendari identifikatuarekin ({num_f}/{den_f} formal + {num_m}/{den_m} txiki)
- **Así queda:** 12/30 esleipendun ezagun zuzendari identifikatuarekin (8/20 formal + 4/10 txiki) / 1/8 esleipendun ezagun zuzendari identifikatuarekin (0/5 formal + 1/3 txiki)
- **Variables:** {num} = un número; {den} = un número; {num_f} = un número; {den_f} = un número; {num_m} = un número; {den_m} = un número
- **Corrección:** 

## 35
- **ES:** {n} contratos formales / {hab} hab. ({por_mil}/1.000 hab.), percentil {pct} entre municipios de tamaño similar
- **EU actual:** {n} kontratu formal / {hab} biz. ({por_mil}/1.000 biz.), {pct}. pertzentila antzeko tamainako udalerrien artean
- **Así queda:** 1 kontratu formal / 45.000 biz. (2,3/1.000 biz.), 35. pertzentila antzeko tamainako udalerrien artean / 50 kontratu formal / 1.200 biz. (11/1.000 biz.), 8. pertzentila antzeko tamainako udalerrien artean
- **Variables:** {n} = un número (cualquier cantidad); {hab} = habitantes, número; {por_mil} = contratos por cada 1.000 habitantes; {pct} = un porcentaje, sin el símbolo
- **Corrección:** 

## 36
- **ES:** peso {peso}%
- **EU actual:** pisua: % {peso}
- **Así queda:** pisua: % 20 / pisua: % 7,5
- **Variables:** {peso} = un porcentaje (peso de un componente)
- **Corrección:** 

## 37
- **ES:** Página {pagina} de {paginas} · {total} {etiqueta}
- **EU actual:** {pagina}/{paginas} orria · {total} {etiqueta}
- **Así queda:** 2/7 orria · 120 udalerri / 1/21 orria · 8.131 alkate
- **Variables:** {pagina} = número de página; {paginas} = total de páginas; {total} = un número total; {etiqueta} = palabra ya traducida: qué se cuenta (p. ej. «udalerri»)
- **Corrección:** 

## 38
- **ES:** {n} municipios sin cobertura de datos suficiente para calcular su índice (menos de {minimo} de {total} componentes disponibles) -- no se muestran en la tabla.
- **EU actual:** {n} udalerrik ez dute datu-estaldura nahikorik indizea kalkulatzeko ({total} osagaietatik {minimo} baino gutxiago eskuragarri) -- ez dira taulan erakusten.
- **Así queda:** 1 udalerrik ez dute datu-estaldura nahikorik indizea kalkulatzeko (120 osagaietatik 5 baino gutxiago eskuragarri) -- ez dira taulan erakusten. / 50 udalerrik ez dute datu-estaldura nahikorik indizea kalkulatzeko (8.131 osagaietatik 5 baino gutxiago eskuragarri) -- ez dira taulan erakusten.
- **Variables:** {n} = un número (cualquier cantidad); {minimo} = un número mínimo; {total} = un número total
- **Aviso:** Tras un numeral, ¿«osagaitatik»? (indefinido).
- **Corrección:** 

## 39
- **ES:** #{p} de {n} (nacional), #{pc} de {nc} en {comunidad}
- **EU actual:** #{p} {n}tik (estatua), #{pc} {nc}tik {comunidad}(e)n
- **Así queda:** #3 1tik (estatua), #2 251tik País Vasco(e)n / #21 50tik (estatua), #11 45tik Región de Murcia(e)n
- **Variables:** {p} = una posición en un ranking; {n} = un número (cualquier cantidad); {pc} = posición dentro de la comunidad; {nc} = número de municipios de la comunidad; {comunidad} = nombre de la comunidad autónoma, en castellano
- **Aviso:** «{n}tik» cambia según el número (50 → «50etik»). Además, «estatua» por «nacional»: ¿«Espainia osoan» / «estatu mailan»?
- **Aviso:** «(e)n» es un apaño para no declinar el nombre de la comunidad; un nativo lo notaría. «{n}tik»/«{nc}tik» cambian según el número.
- **Aviso:** «{n}tik» cambia según el número (50 → «50etik»).
- **Corrección:** 

## 40
- **ES:** #{p} de {n}
- **EU actual:** #{p} {n}tik
- **Así queda:** #3 1tik / #21 50tik
- **Variables:** {p} = una posición en un ranking; {n} = un número (cualquier cantidad)
- **Aviso:** «{n}tik» cambia según el número (50 → «50etik»).
- **Corrección:** 

## 41
- **ES:** <b>{n}</b> contratos
- **EU actual:** <b>{n}</b> kontratu
- **Así queda:** 1 kontratu / 50 kontratu
- **Variables:** {n} = un número (cualquier cantidad)
- **Corrección:** 

## 42
- **ES:** {importe} de deuda viva
- **EU actual:** {importe} zor bizi
- **Así queda:** 1.234.567,89 € zor bizi / 45.000,00 € zor bizi
- **Variables:** {importe} = una cantidad en euros, ya con el símbolo €
- **Corrección:** 

## 43
- **ES:** {n} municipios con dato
- **EU actual:** {n} udalerri daturekin
- **Así queda:** 1 udalerri daturekin / 50 udalerri daturekin
- **Variables:** {n} = un número (cualquier cantidad)
- **Corrección:** 

## 44
- **ES:** De mayor a menor retribución anual ({ambito})
- **EU actual:** Urteko ordainsari handienetik txikienera ({ambito})
- **Así queda:** Urteko ordainsari handienetik txikienera (Espainia) / Urteko ordainsari handienetik txikienera (Gipuzkoa)
- **Variables:** {ambito} = ámbito del ranking (ya traducido)
- **Corrección:** 

## 45
- **ES:** De mayor a menor deuda viva por habitante ({ambito})
- **EU actual:** Biztanleko zor bizi handienetik txikienera ({ambito})
- **Así queda:** Biztanleko zor bizi handienetik txikienera (Espainia) / Biztanleko zor bizi handienetik txikienera (Gipuzkoa)
- **Variables:** {ambito} = ámbito del ranking (ya traducido)
- **Corrección:** 

## 46
- **ES:** Ojo con la base de los importes: las filas de «{fuentes}» van sin IVA (importe adjudicado según PLACE); las demás filas pueden incluir IVA. El total de arriba suma ambas bases.
- **EU actual:** Kontuz zenbatekoen oinarriarekin: «{fuentes}» iturriko errenkadak BEZik gabe daude (PLACEren araberako esleitutako zenbatekoa); gainerako errenkadek BEZa izan dezakete. Goiko guztizkoak bi oinarriak batzen ditu.
- **Así queda:** Kontuz zenbatekoen oinarriarekin: «Bilbao (PLACE)» iturriko errenkadak BEZik gabe daude (PLACEren araberako esleitutako zenbatekoa); gainerako errenkadek BEZa izan dezakete. Goiko guztizkoak bi oinarriak batzen ditu. / Kontuz zenbatekoen oinarriarekin: «Sax (PLACE), Ibi (PLACE)» iturriko errenkadak BEZik gabe daude (PLACEren araberako esleitutako zenbatekoa); gainerako errenkadek BEZa izan dezakete. Goiko guztizkoak bi oinarriak batzen ditu.
- **Variables:** {fuentes} = nombres de fuentes
- **Corrección:** 

## 47
- **ES:** Mismo nombre y apellidos que {cargo} de {municipio}. No implica necesariamente relación — dato para verificar.
- **EU actual:** Izen-abizen berak ditu {municipio}(e)ko {cargo} batek. Ez du nahitaez harremanik adierazten — egiaztatzeko datua.
- **Así queda:** Izen-abizen berak ditu Bilbao(e)ko concejal batek. Ez du nahitaez harremanik adierazten — egiaztatzeko datua. / Izen-abizen berak ditu Arrasate/Mondragón(e)ko alcaldesa batek. Ez du nahitaez harremanik adierazten — egiaztatzeko datua.
- **Variables:** {cargo} = un cargo, en minúsculas y en castellano; {municipio} = el nombre de un municipio (en su forma oficial)
- **Aviso:** «(e)ko» es un apaño para no declinar el nombre del municipio.
- **Corrección:** 

## 48
- **ES:** Por ahora tenemos datos de {n} de las {total} provincias: {lista}. El resto, pendiente de conectar.
- **EU actual:** Oraingoz {total} probintzietatik {n}ren datuak ditugu: {lista}. Gainerakoak konektatzeko daude.
- **Así queda:** Oraingoz 120 probintzietatik 1ren datuak ditugu: Región de Murcia y provincia de Girona. Gainerakoak konektatzeko daude. / Oraingoz 8.131 probintzietatik 50ren datuak ditugu: Gipuzkoa. Gainerakoak konektatzeko daude.
- **Variables:** {n} = un número (cualquier cantidad); {total} = un número total; {lista} = lista de provincias unida con «y»
- **Aviso:** «{n}ren»: con 1 sería «1en»; depende del número.
- **Corrección:** 

## 49
- **ES:** Proyectos y fondos financiados por la Unión Europea (CORDIS, Horizon Europe, Cohesion Data FEDER/FSE) en {lista}.
- **EU actual:** Europar Batasunak finantzatutako proiektuak eta funtsak (CORDIS, Horizon Europe, Cohesion Data FEDER/FSE): {lista}.
- **Así queda:** Europar Batasunak finantzatutako proiektuak eta funtsak (CORDIS, Horizon Europe, Cohesion Data FEDER/FSE): Región de Murcia y provincia de Girona. / Europar Batasunak finantzatutako proiektuak eta funtsak (CORDIS, Horizon Europe, Cohesion Data FEDER/FSE): Gipuzkoa.
- **Variables:** {lista} = lista de provincias unida con «y»
- **Aviso:** Construcción tipo etiqueta («X: {variable}») para no tener que declinar el nombre: correcta, pero poco natural en una frase.
- **Corrección:** 

## 50
- **ES:** Población oficial a 1 de enero de {anio} (INE, Padrón Municipal)
- **EU actual:** Biztanleria ofiziala {anio}ko urtarrilaren 1ean (INE, Udal Errolda)
- **Así queda:** Biztanleria ofiziala 2025ko urtarrilaren 1ean (INE, Udal Errolda) / Biztanleria ofiziala 2024ko urtarrilaren 1ean (INE, Udal Errolda)
- **Variables:** {anio} = un año
- **Aviso:** Con 2025 debe ser «2025eko», no «2025ko» (con 2024 sí «2024ko»). Hoy se muestra «2025ko» en cada ficha.
- **Corrección:** 

## 51
- **ES:** {n} hab.
- **EU actual:** {n} biz.
- **Así queda:** 1 biz. / 50 biz.
- **Variables:** {n} = un número (cualquier cantidad)
- **Corrección:** 

## 52
- **ES:** Saldo presupuestario no financiero ({tipo}) del ejercicio {ejercicio}, Ministerio de Hacienda
- **EU actual:** Aurrekontu-saldo ez-finantzarioa ({tipo}), {ejercicio} ekitaldia, Ogasun Ministerioa
- **Así queda:** Aurrekontu-saldo ez-finantzarioa (consolidado), 2024 ekitaldia, Ogasun Ministerioa / Aurrekontu-saldo ez-finantzarioa (ayuntamiento), 2025 ekitaldia, Ogasun Ministerioa
- **Variables:** {tipo} = tipo de saldo, en minúsculas; {ejercicio} = un año
- **Corrección:** 

## 53
- **ES:** datos {edad}
- **EU actual:** datuak: {edad}
- **Así queda:** datuak: duela 5 min / datuak: duela 2h 10min
- **Variables:** {edad} = antigüedad de los datos, otra frase ya traducida
- **Corrección:** 

## 54
- **ES:** buscar el portal de transparencia de {organismo} ↗
- **EU actual:** bilatu {organismo} erakundearen gardentasun-ataria ↗
- **Así queda:** bilatu Ayuntamiento de Bilbao erakundearen gardentasun-ataria ↗ / bilatu Concello de Vigo erakundearen gardentasun-ataria ↗
- **Variables:** {organismo} = nombre oficial del ayuntamiento
- **Corrección:** 

## 55
- **ES:** <b>Contratos menores:</b> no hay registros de este tipo para {municipio} en las fuentes que consultamos. Los contratos menores no siempre tienen obligación legal de publicación centralizada -- muchos ayuntamientos los tramitan sin subirlos a ningún registro abierto que esta web pueda consultar, así que esto no significa necesariamente que no existan. Cualquier vecino o concejal puede solicitarlos formalmente al ayuntamiento por la vía de acceso a la información pública ({ley}) -- {portal}
- **EU actual:** <b>Kontratu txikiak:</b> ez dago mota honetako erregistrorik {municipio} udalerrirako kontsultatzen ditugun iturrietan. Kontratu txikiek ez dute beti argitalpen zentralizatuko legezko betebeharrik -- udal askok webgune honek kontsulta dezakeen inongo erregistro irekitara igo gabe izapidetzen dituzte, beraz horrek ez du nahitaez esan nahi existitzen ez direnik. Edozein bizilagunek edo zinegotzik formalki eska diezazkioke udalari, informazio publikoa eskuratzeko bidetik ({ley}) -- {portal}
- **Así queda:** Kontratu txikiak: ez dago mota honetako erregistrorik Bilbao udalerrirako kontsultatzen ditugun iturrietan. Kontratu txikiek ez dute beti argitalpen zentralizatuko legezko betebeharrik -- udal askok webgune honek kontsulta dezakeen inongo erregistro irekitara igo gabe izapidetzen dituzte, beraz horrek ez du nahitaez esan nahi existitzen ez direnik. Edozein bizilagunek edo zinegotzik formalki eska diezazkioke udalari, informazio publikoa eskuratzeko bidetik (Ley 19/2013) -- Governalia / Kontratu txikiak: ez dago mota honetako erregistrorik Arrasate/Mondragón udalerrirako kontsultatzen ditugun iturrietan. Kontratu txikiek ez dute beti argitalpen zentralizatuko legezko betebeharrik -- udal askok webgune honek kontsulta dezakeen inongo erregistro irekitara igo gabe izapidetzen dituzte, beraz horrek ez du nahitaez esan nahi existitzen ez direnik. Edozein bizilagunek edo zinegotzik formalki eska diezazkioke udalari, informazio publikoa eskuratzeko bidetik (Ley 9/2017) -- Euskadi
- **Variables:** {municipio} = el nombre de un municipio (en su forma oficial); {ley} = nombre de una ley; {portal} = nombre de un portal
- **Corrección:** 

## 56
- **ES:** Contratos públicos de {municipio}
- **EU actual:** Kontratu publikoak: {municipio}
- **Así queda:** Kontratu publikoak: Bilbao / Kontratu publikoak: Arrasate/Mondragón
- **Variables:** {municipio} = el nombre de un municipio (en su forma oficial)
- **Aviso:** Construcción tipo etiqueta («X: {variable}») para no tener que declinar el nombre: correcta, pero poco natural en una frase.
- **Corrección:** 

## 57
- **ES:** Contratos públicos adjudicados en {municipio} ({territorio}): empresa adjudicataria, importe y directivo/administrador. Datos oficiales {fuente} + Registro Mercantil.
- **EU actual:** Kontratu publikoak: {municipio} ({territorio}): enpresa esleipenduna, zenbatekoa eta zuzendaria/administratzailea. Datu ofizialak: {fuente} + Merkataritza Erregistroa.
- **Así queda:** Kontratu publikoak: Bilbao (Gipuzkoa): enpresa esleipenduna, zenbatekoa eta zuzendaria/administratzailea. Datu ofizialak: PLACE + Merkataritza Erregistroa. / Kontratu publikoak: Arrasate/Mondragón (Región de Murcia): enpresa esleipenduna, zenbatekoa eta zuzendaria/administratzailea. Datu ofizialak: Euskadi + Merkataritza Erregistroa.
- **Variables:** {municipio} = el nombre de un municipio (en su forma oficial); {territorio} = el nombre de una provincia o comunidad, en castellano; {fuente} = el nombre corto de una fuente de datos
- **Aviso:** Construcción tipo etiqueta («X: {variable}») para no tener que declinar el nombre: correcta, pero poco natural en una frase.
- **Corrección:** 

## 58
- **ES:** Ej: {ejemplos}
- **EU actual:** Adib.: {ejemplos}
- **Así queda:** Adib.: Bilbao, Getxo / Adib.: Donostia
- **Variables:** {ejemplos} = nombres de municipios de ejemplo
- **Corrección:** 

## 59
- **ES:** Un dato que no tenemos no cuenta como 0: su peso se reparte entre el resto. Hacen falta al menos {minimo} de los {total} componentes.
- **EU actual:** Ez dugun datu batek ez du 0 gisa zenbatzen: haren pisua gainerakoen artean banatzen da. Gutxienez {total} osagaietatik {minimo} behar dira.
- **Así queda:** Ez dugun datu batek ez du 0 gisa zenbatzen: haren pisua gainerakoen artean banatzen da. Gutxienez 120 osagaietatik 5 behar dira. / Ez dugun datu batek ez du 0 gisa zenbatzen: haren pisua gainerakoen artean banatzen da. Gutxienez 8.131 osagaietatik 5 behar dira.
- **Variables:** {minimo} = un número mínimo; {total} = un número total
- **Aviso:** Tras un numeral, ¿«osagaitatik»? (indefinido).
- **Corrección:** 

## 60
- **ES:** Importe de adjudicación publicado por {fuente}; en contratos plurianuales incluye toda su duración.
- **EU actual:** {fuente} iturriak argitaratutako esleipen-zenbatekoa; urte anitzeko kontratuetan iraupen osoa hartzen du.
- **Así queda:** PLACE iturriak argitaratutako esleipen-zenbatekoa; urte anitzeko kontratuetan iraupen osoa hartzen du. / Euskadi iturriak argitaratutako esleipen-zenbatekoa; urte anitzeko kontratuetan iraupen osoa hartzen du.
- **Variables:** {fuente} = el nombre corto de una fuente de datos
- **Corrección:** 

## 61
- **ES:** Deuda viva a {fecha}, Ministerio de Hacienda
- **EU actual:** Zor bizia {fecha} egunean, Ogasun Ministerioa
- **Así queda:** Zor bizia 30/06/2026 egunean, Ogasun Ministerioa / Zor bizia 31/03/2026 egunean, Ogasun Ministerioa
- **Variables:** {fecha} = una fecha
- **Corrección:** 

## 62
- **ES:** {n} habitantes
- **EU actual:** {n} biztanle
- **Así queda:** 1 biztanle / 50 biztanle
- **Variables:** {n} = un número (cualquier cantidad)
- **Corrección:** 

## 63
- **ES:** Es uno de los {n} ayuntamientos de España sin deuda viva.
- **EU actual:** Zor bizirik gabeko Espainiako {n} udaletako bat da.
- **Así queda:** Zor bizirik gabeko Espainiako 1 udaletako bat da. / Zor bizirik gabeko Espainiako 50 udaletako bat da.
- **Variables:** {n} = un número (cualquier cantidad)
- **Corrección:** 

## 64
- **ES:** Empate a {n} en el primer puesto
- **EU actual:** {n}ko berdinketa lehen postuan
- **Así queda:** 1ko berdinketa lehen postuan / 50ko berdinketa lehen postuan
- **Variables:** {n} = un número (cualquier cantidad)
- **Aviso:** OJO de significado: {n} es el NÚMERO de municipios empatados (p. ej. 3), no una puntuación. «{n}ko berdinketa» parece decir «empate a {n} puntos».
- **Corrección:** 

## 65
- **ES:** {n} municipios con nota · España
- **EU actual:** {n} udalerri notarekin · Espainia
- **Así queda:** 1 udalerri notarekin · Espainia / 50 udalerri notarekin · Espainia
- **Variables:** {n} = un número (cualquier cantidad)
- **Corrección:** 

## 66
- **ES:** Ver más ({n} más) ▾
- **EU actual:** Ikusi gehiago ({n} gehiago) ▾
- **Así queda:** Ikusi gehiago (1 gehiago) ▾ / Ikusi gehiago (50 gehiago) ▾
- **Variables:** {n} = un número (cualquier cantidad)
- **Corrección:** 

## 67
- **ES:** {importe}/hab. de deuda viva
- **EU actual:** {importe}/biz. zor bizi
- **Así queda:** 1.234.567,89 €/biz. zor bizi / 45.000,00 €/biz. zor bizi
- **Variables:** {importe} = una cantidad en euros, ya con el símbolo €
- **Corrección:** 

## 68
- **ES:** {importe} adjudicado
- **EU actual:** {importe} esleituta
- **Así queda:** 1.234.567,89 € esleituta / 45.000,00 € esleituta
- **Variables:** {importe} = una cantidad en euros, ya con el símbolo €
- **Corrección:** 

## 69
- **ES:** Busca en los {n} contratos ya cargados de toda España · mínimo 2 caracteres.
- **EU actual:** Bilatu Espainia osoko {n} kontratu kargatuen artean · gutxienez 2 karaktere.
- **Así queda:** Bilatu Espainia osoko 1 kontratu kargatuen artean · gutxienez 2 karaktere. / Bilatu Espainia osoko 50 kontratu kargatuen artean · gutxienez 2 karaktere.
- **Variables:** {n} = un número (cualquier cantidad)
- **Corrección:** 

## 70
- **ES:** Contratos públicos de los {n} municipios {de_la} {territorio}, cruzados con el Registro Mercantil para saber qué empresa — y qué persona — hay detrás de cada adjudicación.
- **EU actual:** {territorio}: {n} udalerrietako kontratu publikoak, Merkataritza Erregistroarekin gurutzatuta, esleipen bakoitzaren atzean zer enpresa — eta zer pertsona — dagoen jakiteko.
- **Así queda:** Gipuzkoa: 1 udalerrietako kontratu publikoak, Merkataritza Erregistroarekin gurutzatuta, esleipen bakoitzaren atzean zer enpresa — eta zer pertsona — dagoen jakiteko. / Región de Murcia: 50 udalerrietako kontratu publikoak, Merkataritza Erregistroarekin gurutzatuta, esleipen bakoitzaren atzean zer enpresa — eta zer pertsona — dagoen jakiteko.
- **Variables:** {n} = un número (cualquier cantidad); {de_la} = artículo en castellano: «de la», «del», «de»; {territorio} = el nombre de una provincia o comunidad, en castellano
- **Aviso:** Tras un numeral se usa la forma indefinida: «50 udalerritako», no «udalerrietako».
- **Corrección:** 

## 71
- **ES:** Busca en los {n} contratos ya cargados de {territorio} · mínimo 2 caracteres.
- **EU actual:** Bilatu {territorio}: {n} kontratu kargatuen artean · gutxienez 2 karaktere.
- **Así queda:** Bilatu Gipuzkoa: 1 kontratu kargatuen artean · gutxienez 2 karaktere. / Bilatu Región de Murcia: 50 kontratu kargatuen artean · gutxienez 2 karaktere.
- **Variables:** {n} = un número (cualquier cantidad); {territorio} = el nombre de una provincia o comunidad, en castellano
- **Corrección:** 

## 72
- **ES:** Contratos públicos {territorio}
- **EU actual:** Kontratu publikoak: {territorio}
- **Así queda:** Kontratu publikoak: Gipuzkoa / Kontratu publikoak: Región de Murcia
- **Variables:** {territorio} = el nombre de una provincia o comunidad, en castellano
- **Aviso:** Construcción tipo etiqueta («X: {variable}») para no tener que declinar el nombre: correcta, pero poco natural en una frase.
- **Corrección:** 

## 73
- **ES:** Consulta los contratos públicos de los {n} municipios de {territorio} con los directivos de las empresas adjudicatarias.
- **EU actual:** Kontsultatu {territorio}: {n} udalerrietako kontratu publikoak, enpresa esleipendunen zuzendariekin.
- **Así queda:** Kontsultatu Gipuzkoa: 1 udalerrietako kontratu publikoak, enpresa esleipendunen zuzendariekin. / Kontsultatu Región de Murcia: 50 udalerrietako kontratu publikoak, enpresa esleipendunen zuzendariekin.
- **Variables:** {n} = un número (cualquier cantidad); {territorio} = el nombre de una provincia o comunidad, en castellano
- **Aviso:** Tras un numeral se usa la forma indefinida: «50 udalerritako», no «udalerrietako».
- **Corrección:** 

## 74
- **ES:** Mostrando los primeros 300 de {n} resultados.
- **EU actual:** {n} emaitzetatik lehenengo 300ak erakusten.
- **Así queda:** 1 emaitzetatik lehenengo 300ak erakusten. / 50 emaitzetatik lehenengo 300ak erakusten.
- **Variables:** {n} = un número (cualquier cantidad)
- **Corrección:** 

## 75
- **ES:** {n} resultado para "{q}"
- **EU actual:** {n} emaitza "{q}" bilaketarako
- **Así queda:** 1 emaitza "garbiketa" bilaketarako / 50 emaitza "Bilbao" bilaketarako
- **Variables:** {n} = un número (cualquier cantidad); {q} = el texto que ha buscado la persona
- **Corrección:** 

## 76
- **ES:** {n} resultados para "{q}"
- **EU actual:** {n} emaitza "{q}" bilaketarako
- **Así queda:** 1 emaitza "garbiketa" bilaketarako / 50 emaitza "Bilbao" bilaketarako
- **Variables:** {n} = un número (cualquier cantidad); {q} = el texto que ha buscado la persona
- **Corrección:** 

## 77
- **ES:** Búsqueda: {q}
- **EU actual:** Bilaketa: {q}
- **Así queda:** Bilaketa: garbiketa / Bilaketa: Bilbao
- **Variables:** {q} = el texto que ha buscado la persona
- **Corrección:** 

## 78
- **ES:** Resultados de "{q}" en contratos públicos de {territorio}.
- **EU actual:** "{q}" bilaketaren emaitzak kontratu publikoetan: {territorio}.
- **Así queda:** "garbiketa" bilaketaren emaitzak kontratu publikoetan: Gipuzkoa. / "Bilbao" bilaketaren emaitzak kontratu publikoetan: Región de Murcia.
- **Variables:** {q} = el texto que ha buscado la persona; {territorio} = el nombre de una provincia o comunidad, en castellano
- **Aviso:** Construcción tipo etiqueta («X: {variable}») para no tener que declinar el nombre: correcta, pero poco natural en una frase.
- **Corrección:** 

## 79
- **ES:** {n} municipios
- **EU actual:** {n} udalerri
- **Así queda:** 1 udalerri / 50 udalerri
- **Variables:** {n} = un número (cualquier cantidad)
- **Corrección:** 
