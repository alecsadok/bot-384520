# BOT 384520

Monitoreo diario de noticias, eventos y normativa de interés para la **lechería argentina, los tambos y el ganado lechero**. El proyecto combina scraping de páginas públicas, RSS, Google News RSS, la Primera Sección del Boletín Oficial y búsqueda web asistida por IA cuando está configurada.

## Enfoque editorial

El radar prioriza:

- Lechería: tambos, producción y precio de la leche, industria láctea, eficiencia, instalaciones y sistemas de producción.
- Ganado lechero: reproducción, genética, crianza y recría de terneros y terneras, manejo del rodeo, sanidad, bienestar y medicina veterinaria.
- Ganadería bovina: noticias sanitarias, productivas, regulatorias y de manejo que afecten al ganado.
- Alimentación animal: nutrición, raciones, forrajes, pasturas, alfalfa, reservas, silaje y maíz destinado a silo o alimentación.
- Fenómeno El Niño: noticias específicas sobre El Niño/ENSO.

No se incorporan pronósticos meteorológicos, observaciones del tiempo ni alertas generales del SMN. Tampoco se priorizan noticias centradas exclusivamente en maíz u otros cultivos, mercados de granos o agricultura sin relación concreta con la alimentación del ganado. Se excluyen las publicaciones enfocadas en producción de carne, faena, feedlots o engorde, salvo que tengan un contenido claramente vinculado también con la lechería.

El filtro combina términos temáticos con reglas de exclusión. Una noticia sobre un cultivo puede ingresar cuando el contenido la relaciona expresamente con forrajes, silaje, nutrición o alimentación animal. Una noticia sobre El Niño puede ingresar como tema específico, aunque no sea una nota meteorológica de pronóstico.

## IA local y gratuita

BOT 384520 utiliza **Qwen3 1.7B** ejecutado localmente mediante Ollama. El modelo se descarga en el runner de GitHub Actions y procesa allí los textos; no se conecta a OpenAI, Gemini ni a otro proveedor de inferencia remota.

- **Sin API keys:** no requiere `OPENAI_API_KEY`, claves de terceros ni cuentas de IA.
- **Sin cobro por tokens:** las inferencias se ejecutan localmente; no se envían prompts a una API facturada.
- **Búsqueda de noticias:** utiliza Google News RSS, un feed público sin clave de API, con consultas ampliadas por temas lecheros y de ganado.
- **Agenda:** agrega búsquedas de jornadas, cursos, seminarios, congresos, exposiciones, webinars y días de campo publicados durante los últimos 30 días. Solo conserva eventos con fecha futura verificable, hasta 90 días.
- **Análisis normativo:** Qwen3 revisa el texto extraído de la Primera Sección del Boletín Oficial, identifica el impacto concreto sobre tambos y ganado lechero, y debe aportar una cita literal del documento para justificar su selección.
- **Exclusiones:** las reglas determinísticas siguen bloqueando noticias centradas en carne, faena, feedlots y cultivos sin relación con alimentación animal.

El modelo Qwen3 1.7B se distribuye bajo licencia Apache 2.0 y ocupa aproximadamente 1,4 GB en la biblioteca de Ollama. La inferencia usa CPU/RAM del runner, no créditos de IA. Referencias: [modelo Qwen3 en Ollama](https://ollama.com/library/qwen3:1.7b), [licencia Apache 2.0 del modelo](https://ollama.com/library/qwen3:1.7b) y [documentación de la API local de Ollama](https://github.com/ollama/ollama/blob/main/docs/api.md).

### Cómo se ejecuta

El workflow instala Ollama, descarga el modelo y lo inicia en `127.0.0.1`. La carpeta de pesos se guarda en la caché de GitHub Actions para evitar descargar 1,4 GB en cada ejecución. No se necesita configurar ningún secreto.

El repositorio BOT 384520 es público. GitHub indica que los runners estándar alojados por GitHub son gratuitos y sin límite de minutos para repositorios públicos. Esta condición dejaría de aplicar si el repositorio se convierte en privado o se utilizan runners de mayor tamaño o servicios adicionales facturados. Ver [facturación de GitHub Actions](https://docs.github.com/en/actions/concepts/billing-and-usage) y [tipos de runners](https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/choose-the-runner-for-a-job).

Si Ollama o el modelo no están disponibles, BOT 384520 continúa con los filtros y resúmenes convencionales. El informe deja constancia del estado de la IA local; no intenta conectarse a una API paga como alternativa.

## Qué genera

Cada ejecución crea o actualiza únicamente los archivos correspondientes a la fecha local del informe dentro de `informes/`:

- `bot384520_DDMMYY.html`
- `bot384520_DDMMYY.txt`

Ejemplo: `bot384520_101126.html` y `bot384520_101126.txt` para el 10/11/2026.

El filtro editorial toma publicaciones con fecha identificable dentro de las 24 horas anteriores al momento de ejecución. Se registra la fecha y hora de publicación, la fuente, el enlace original, las etiquetas temáticas y, cuando corresponde, la fecha futura de un evento. El archivo TXT contiene, para cada publicación, el título, la fecha de publicación y el enlace original, separados por líneas en blanco.

## Ejecución automática

El workflow `.github/workflows/radar-diario.yml` programa el script todos los días a las **23:00 de `America/Argentina/Cordoba`** y permite ejecución manual desde la pestaña **Actions** de GitHub.

El workflow instala dependencias, ejecuta el script y guarda los informes en el propio repositorio mediante un commit de `github-actions[bot]`. Requiere que GitHub Actions esté habilitado, que el archivo esté en la rama predeterminada y que el workflow tenga permiso `contents: write`. GitHub advierte que los eventos programados pueden demorarse en períodos de alta demanda; la hora indicada es la hora programada, no una garantía de inicio al segundo.

## Fuentes incluidas

### Portales de noticias y especialidad

Argentina.gob.ar, SENASA, Todo Lechería, Agrofy News/Lechería, Bichos de Campo, Agrolink, Clarín Rural, Agroverdad, Mundo Agro Córdoba, Agritotal, Revista Chacra/Infobae, La Nación Campo, UNL, Infocampo, Agroempresario, Portal Lechero, OCLA, FCV-UNL Eventos, Colegio de Médicos Veterinarios de Santa Fe, Mundo Rural, InfoLáctea, Secretaría de Agricultura, INDEC y Bolsa de Comercio de Rosario.

La presencia de una fuente generalista no implica que se incorporen todas sus publicaciones: cada resultado debe superar el filtro temático del BOT 384520.

### Búsqueda transversal

Consultas temáticas en Google News RSS, acotadas a la ventana reciente (`when:1d`). Las búsquedas se orientan a lechería, ganado bovino, sanidad, reproducción, alimentación animal y El Niño.

### Boletín Oficial

Consulta de la **Primera Sección – Legislación y Avisos Oficiales**. El recolector identifica las fichas individuales de la edición, descarga el texto de cada publicación candidata y extrae título, área, tipo de norma, fecha y enlace oficial.

Cuando existe `OPENAI_API_KEY`, una llamada de análisis estructurado evalúa en conjunto los documentos candidatos. La selección exige relevancia sectorial, una puntuación mínima y una cita breve que debe coincidir literalmente con el texto oficial. El resultado incluye resumen, impacto potencial, actores alcanzados y puntos que conviene verificar. Si la API no está configurada o falla, se aplica el filtro temático de respaldo y se deja constancia en el estado de la fuente.

La integración toma como referencia el flujo general de extracción y análisis de [Chequeado Botletín Oficial](https://github.com/chequeado/botletin-oficial), pero BOT 384520 mantiene un recolector independiente, orientado a la normativa que afecta a tambos, ganado lechero y producción láctea. No necesita la base de datos, API ni frontend de ese proyecto.

Se deben verificar siempre el articulado, los sujetos alcanzados, los requisitos, los anexos y la vigencia en la publicación oficial antes de comunicar o tomar decisiones.

### Redes sociales

Se consultan perfiles públicos de Instagram y X sin autenticación. Cuando el HTML público expone enlaces a publicaciones, se intenta leer hasta dos posts por perfil para recuperar contenido y fecha. Estas plataformas pueden devolver páginas incompletas, páginas que requieren JavaScript, bloqueos o metadatos sin publicaciones. El informe identifica esos casos como acceso restringido/no verificable; no usa credenciales, no evade controles y no afirma haber leído publicaciones inaccesibles.

## Criterios de calidad y límites

- Las noticias deben tener fecha de publicación verificable dentro de las últimas 24 horas. Los eventos encontrados con IA pueden haberse anunciado antes, pero solo se conservan cuando la fecha de realización es futura, está visible en la página original y se encuentra dentro de los próximos 90 días. Si no se puede verificar la fecha del evento, queda fuera.
- No se inventan fechas de publicación. Las fechas futuras de eventos se extraen del texto cuando pueden identificarse.
- Se eliminan duplicados por título normalizado.
- En las fuentes RSS y portales, los resúmenes son extractivos. En los resultados de búsqueda web con IA, la síntesis es generada por el modelo y se conserva únicamente después de verificar el enlace y el contenido de la página original.
- El análisis de normativa se realiza con IA local y debe incluir evidencia literal de la publicación oficial; si el modelo no está disponible, se utiliza el filtro temático de respaldo. Ningún resumen reemplaza la lectura del articulado ni el asesoramiento legal.
- El filtro editorial reduce resultados ajenos al ganado, pero una mención contextual puede requerir revisión humana. Conviene revisar titulares y enlaces antes de redistribuir el informe.
- El scraping está sujeto a cambios de diseño, disponibilidad, robots, límites de frecuencia, JavaScript y condiciones de cada fuente. Por eso cada informe incluye una tabla de estado de fuentes.
- El script no consulta servicios meteorológicos ni usa cookies privadas, login o cuentas de usuario. La IA se ejecuta localmente; no utiliza claves API ni proveedores de inferencia pagos.

## Prueba local

Requiere Python 3.11 o superior:

```bash
python -m pip install -r requirements.txt
python radar_lechero.py
```

Para desactivar las consultas a perfiles públicos de Instagram/X durante una prueba local:

```bash
RADAR_SCAN_SOCIAL=0 python radar_lechero.py
```

En Windows PowerShell:

```powershell
$env:RADAR_SCAN_SOCIAL="0"
python radar_lechero.py
```

## Dependencias

- `requests`: descarga de páginas y endpoints.
- `beautifulsoup4`: análisis de HTML.
- `feedparser`: RSS/Atom.
- `python-dateutil`: interpretación de fechas.
