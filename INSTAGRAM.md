# Cómo trabajar la cuenta @hayminga

Guía paso a paso para publicar desde la hoja `Instagram` del Google Sheet.
Está escrita asumiendo cero experiencia previa con Instagram.

La hoja es una **cola de trabajo**: cada fila es una cosa por hacer, con el
texto ya escrito. No hay que decidir ni redactar nada, solo ejecutar.

---

## Antes de empezar: configurar la cuenta (una sola vez)

**1. Pasar la cuenta a profesional.** Sin esto no hay estadísticas y no se
puede saber si algo funciona.
> Perfil → menú ☰ (arriba a la derecha) → Configuración → Tipo de cuenta y
> herramientas → Cambiar a cuenta profesional → Categoría: *Sitio web* o
> *Organización comunitaria*

**2. Poner el link en la bio.** Instagram da **un solo link clickeable** en
todo el perfil: es la única puerta al sitio, así que es lo más importante
de la cuenta.
> Editar perfil → Sitio web → pegar:
> `https://hayminga.org?utm_source=instagram&utm_medium=bio`

Ese `?utm_source=...` no cambia nada para el visitante, pero permite ver en
las estadísticas cuánta gente entró desde Instagram. Sin eso no se puede
medir si esto sirve.

**3. Escribir la bio.** Que diga qué es, no qué sentimos:
> `Todos los eventos de bioconstrucción de Argentina, en un solo lugar.`
> `Publicá el tuyo con #hayminga 🌿`

**4. Crear las historias destacadas.** Son los circulitos abajo de la bio y
funcionan como menú, porque no se pueden poner links en las publicaciones.
Van cuatro: *Qué es hayminga* · *Cómo publicar tu evento* · *Directorio* ·
*Eventos del mes*. Se crean subiendo una historia y después tocando
"Destacar" abajo a la derecha.

---

## ⚠️ Lo más importante si la cuenta es nueva

Instagram desconfía de las cuentas recién creadas. Hacer muchas acciones
seguidas —seguir, mandar mensajes, comentar— se parece a un bot y puede
terminar con la cuenta limitada o bloqueada por unos días.

**En la cola hay 35 mensajes directos. No los mandes todos el mismo día.**

Ritmo seguro para el primer mes:

| Acción | Máximo por día |
|---|---|
| Mensajes directos | **5 a 8** |
| Cuentas nuevas seguidas | 10 a 15 |
| Historias | sin problema, 3 a 5 está bien |
| Publicaciones al feed | 1 |

Con 5 mensajes por día, los 35 organizadores están cubiertos en una semana.
No hay apuro: la cola no se vence.

---

## Tipo `dm_organizador` — invitar a un organizador al Directorio

Son 35 y es lo más valioso que hay en la cola: cada uno es alguien que ya
está publicado en el sitio sin saberlo. Vienen ordenados por cuánto
aportaron, así que hacelos de arriba hacia abajo.

1. Copiá el `@cuenta` de la columna **Mencionar**.
2. En Instagram, tocá la lupa 🔍 y pegalo para buscar la cuenta.
3. **Seguila primero.** Un mensaje de alguien que no te sigue cae en
   "Solicitudes de mensaje", una bandeja aparte que mucha gente no mira
   nunca. Si la seguís antes, es bastante más probable que lo lean.
4. Entrá al perfil y tocá **Mensaje**.
5. Pegá el texto de la columna **Texto** y enviá.
6. En la hoja, poné la columna `Estado` en `publicado`.

**Ojo con el trato:** los mensajes están escritos en "ustedes" porque casi
todas son cuentas de proyectos. Si es claramente una persona, cambiá
*quieren→querés*, *les→te*, *taggean→taggeás*, *publiquen→publiques*,
*mandan→mandás*, *hacen→hacés*.

---

## Tipo `historia_evento` — compartir un evento a la historia

Las historias duran 24 horas. Son lo que más se hace y lo más rápido.

1. Abrí el link de la columna **Link_Origen** (se abre el post original en
   Instagram).
2. Debajo del post, tocá el ícono de **avioncito de papel** ✈️.
3. Elegí **"Agregar a tu historia"**.
4. El post aparece como una tarjeta que podés mover y agrandar con los dedos.
5. Tocá el ícono de **stickers** (la carita cuadrada arriba) → elegí
   **"@ MENCIÓN"** → escribí la cuenta de la columna **Mencionar**.
   Esto le manda una notificación al organizador, que es medio punto del
   ejercicio: muchos re-comparten la historia que los menciona y así su
   público ve hayminga.
6. Opcional: sticker **"ENLACE"** apuntando a `hayminga.org`.
7. Opcional: agregar el texto de la columna **Texto**.
8. Tocá **"Tu historia"** abajo a la izquierda.
9. En la hoja, `Estado` = `publicado`.

**Si no aparece "Agregar a tu historia":** esa cuenta tiene desactivado el
recompartir, o es privada. No se puede hacer nada — marcá la fila como
`descartado` y seguí con la siguiente.

---

## Tipo `carrusel_semanal` — la publicación de la semana

Es la única que lleva trabajo de diseño. Una por semana.

**Armar las placas (en Canva, gratis):**

1. Entrá a canva.com → Crear diseño → **Publicación de Instagram (1080x1080)**.
2. La columna **Texto** trae el contenido dividido en `[placa 1]`,
   `[placa 2]`, etc. Cada una es una imagen del carrusel.
3. Hacé una página por placa y pegá el texto correspondiente. Mismo fondo y
   misma tipografía en todas, que se vea que son una serie.
4. Descargar → PNG → se baja un archivo por página.

**Publicar:**

5. En Instagram: **+** → **Publicación** → tocá el ícono de **capas** (los
   cuadraditos superpuestos) para elegir varias imágenes.
6. Elegilas **en orden**: placa 1 primero, que es la portada.
7. En la pantalla de texto, pegá lo que está después de `--- CAPTION ---`.
8. Pegá también la columna **Hashtags** al final del texto.
9. Tocá **"Etiquetar personas"** y etiquetá las cuentas de la columna
   **Mencionar** (les llega notificación).
10. Compartir. Y en la hoja, `Estado` = `publicado`.

---

## Las dos reglas de la hoja

**Marcá `descartado`, nunca borres la fila.** El generador se fija en las
claves que ya existen para no repetir. Si borrás una fila, esa clave se
libera y la próxima corrida la vuelve a crear. Marcada como `descartado`,
no vuelve nunca.

**No hace falta hacer todo.** La cola se llena sola cada 3 horas con lo
nuevo que vayas confirmando en `?pendientes`. Si una semana hacés tres
historias y dos mensajes, está bien. Lo que no se hizo sigue ahí.

---

## Qué mirar para saber si sirve

Una vez por semana, en el perfil → **Estadísticas**:

- **Visitas al enlace de la bio** — el número que importa. Es gente que
  efectivamente entró a hayminga.org.
- **Alcance** — cuántas cuentas distintas vieron algo. Sirve para comparar
  qué tipo de pieza funciona mejor.
- **Compartidos y guardados** de cada publicación — es la señal más fuerte
  para el algoritmo, más que los "me gusta".

Y del lado del sitio: cuántos de los 35 organizadores terminaron dándose de
alta en el Directorio. Ese es el resultado real del trabajo, no los
seguidores.
