# BOT 384520


## Criterio editorial

El radar busca material con potencial para comunicar a productores, asesores, profesionales, técnicos y personas vinculadas con la lechería:

- Producción de leche, manejo del tambo, eficiencia, instalaciones, sistemas pastoriles y automatización.
- Vacas lecheras, reproducción, genética, crianza y recría de terneros y vaquillonas.
- Sanidad, medicina veterinaria y bienestar animal.
- Alimentación, nutrición, agua, pasturas, alfalfa, forrajes, silajes y reservas.
- Economía del tambo, costos, precios de la leche, industria láctea y mercados de productos lácteos.
- Investigación aplicada, innovación, tecnología, extensión y transferencia de conocimientos.
- Reglamentaciones, disposiciones sanitarias y medidas que alcancen efectivamente a la actividad.
- Jornadas, capacitaciones, cursos, seminarios, congresos, demostraciones y días de campo.

Se excluyen las noticias centradas exclusivamente en carne, faena, feedlots, novillos, agricultura o mercados de granos sin relación demostrable con la alimentación del rodeo. Los temas climáticos —incluido El Niño, lluvias o sequías— solo se conservan cuando la publicación explica consecuencias concretas para tambos, animales, pasturas o reservas. No se incorporan pronósticos meteorológicos generales.

## Fuentes incluidas

Se conservan las páginas compartidas previamente y se agregan fuentes directas del INTA. El directorio de sitios está declarado en `WEB_SOURCES` dentro de `radar_lechero.py`.

### INTA y fuentes institucionales

- Argentina.gob.ar – Noticias: https://www.argentina.gob.ar/noticias
- INTA – Noticias: https://www.argentina.gob.ar/inta/noticias
- INTA Informa – Noticias: https://intainforma.inta.gob.ar/noticias/
- INTA – Centro Regional Santa Fe: https://www.argentina.gob.ar/inta/cr-santa-fe/noticias
- INTA – Centro Regional Entre Ríos: https://www.argentina.gob.ar/inta/cr-entre-rios/noticias
- INTA – Centro Regional Córdoba: https://www.argentina.gob.ar/inta/cr-cordoba/noticias
- INTA – Centro Regional Corrientes: https://www.argentina.gob.ar/inta/cr-corrientes/noticias
- INTA – Centro Regional Misiones: https://www.argentina.gob.ar/inta/cr-misiones/noticias
- SENASA: https://www.argentina.gob.ar/senasa
- Secretaría de Agricultura: https://www.argentina.gob.ar/economia/agricultura
- CONICET – Prensa: https://www.conicet.gov.ar/prensa/

### Universidades, observatorios y entidades

UNL – Noticias, FCV-UNL – Eventos, OCLA, Colegio de Médicos Veterinarios de Santa Fe, INDEC y Bolsa de Comercio de Rosario.

### Medios y portales sectoriales

Todo Lechería, Agrofy – Lechería, Agrofy News, Bichos de Campo, Agrolink, Clarín Rural, Agroverdad, Mundo Agro Córdoba, Agritotal, Infobae – Revista Chacra, La Nación – Campo, Infocampo, Agroempresario, Portal Lechero, Mundo Rural e InfoLáctea.

**Ninguna de las páginas de noticias enumeradas por el usuario fue eliminada.** El directorio puede ampliarse manteniendo la misma estructura. Que una URL esté configurada no garantiza que su sitio publique RSS o permita lectura automatizada; el informe registra el resultado de cada consulta.

### Búsqueda transversal de Google News

Se utiliza Google News RSS como vía de descubrimiento complementaria. Se incorporó también la búsqueda amplia que compartió el usuario —INTA Lechero, INTA, bovinos, vacas, leucosis, INTA Rafaela, lechería, tambo, veterinaria, entre otros términos—, adaptada a RSS para evitar depender del HTML de resultados de Google.

Las consultas cubren fuentes del INTA y del resto del sector. Se ejecutan todas antes de aplicar el límite final de resultados, de modo que los primeros términos de búsqueda no agoten el cupo y desplacen a los demás medios o instituciones.

## Ventanas de búsqueda y selección

- **Noticias:** publicaciones dentro de los últimos 7 días. La ventana ampliada permite reunir más alternativas que una búsqueda limitada a las últimas 24 horas.
- **Agenda:** se buscan anuncios publicados durante los últimos 30 días. Se conservan actividades con fecha futura verificable, hasta 90 días desde la ejecución.
- **Boletín Oficial:** se revisa la Primera Sección y se analiza cada documento candidato por separado. La normativa aparece en su propio bloque.
- **Orden:** primero se evalúan pertinencia temática, actualidad, novedad y utilidad para la audiencia. El origen de la publicación se muestra para identificar la fuente, pero no aumenta ni reduce automáticamente la puntuación.

Los candidatos que superan la selección pueden mostrar un resumen y una **idea de enfoque para Instagram**, además de un formato orientativo: Carrusel, Reel, Placa, Historias o Revisar. Es una ayuda de planificación, no un copy listo para publicar. El formato se sugiere solo cuando el contenido recuperado ofrece una base razonable; no se inventan fotografías, testimonios, resultados o recursos audiovisuales.

## Perfiles públicos de Instagram y X

Se conservó el listado completo de perfiles aportado por el usuario en `config/perfiles_sociales.txt` (112 direcciones). Para evitar realizar más de cien consultas a Instagram en cada ejecución, se revisan **16 perfiles por día**, de manera rotativa. Con la lista actual, el ciclo completo es de aproximadamente 7 días.

El acceso depende de lo que cada página entregue públicamente. Instagram y X pueden ocultar publicaciones, requerir JavaScript, bloquear solicitudes o no exponer la fecha. El bot no inicia sesión, no utiliza cookies privadas ni intenta eludir controles. Por lo tanto, el monitoreo social es complementario y oportunista: una cuenta configurada no equivale a una lectura garantizada de todas sus publicaciones.

Se pueden sumar o quitar perfiles editando ese archivo de texto, con una URL por línea.

## IA local y gratuita

El análisis editorial utiliza **Qwen3 1.7B** mediante Ollama, ejecutado localmente en el runner de GitHub Actions.

- No se conecta a OpenAI, Gemini ni otros servicios de inferencia remota.
- No requiere claves API ni consume tokens pagos.
- Evalúa candidatos de fuentes institucionales y periodísticas con el mismo criterio.
- Resume el material recibido y puede proponer enfoques y formatos de Instagram.
- Si Ollama no está disponible, el radar utiliza filtros convencionales y conserva los resultados de páginas directas que ya superaron el análisis temático.

El modelo Qwen3 1.7B publicado en Ollama ocupa aproximadamente 1,4 GB y tiene licencia Apache 2.0. Referencias: [modelo en Ollama](https://ollama.com/library/qwen3:1.7b), [modelo Qwen3-1.7B](https://huggingface.co/Qwen/Qwen3-1.7B) y [API local de Ollama](https://github.com/ollama/ollama/blob/main/docs/api.md).

## Qué genera

Cada ejecución crea o actualiza los archivos de la fecha local dentro de `informes/`:

- `bot384520_DDMMYY.html`: informe navegable con fuente, categoría, fecha, resumen, enlace, enfoque posible para Instagram, formato sugerido, agenda y estado de las fuentes.
- `bot384520_DDMMYY.txt`: versión de texto con la misma información editorial básica.

El enlace de cada contenido abre la publicación original. Los resúmenes automáticos no reemplazan la lectura de la fuente.

## Ejecución automática

El workflow `.github/workflows/radar-diario.yml` se ejecuta diariamente a las **23:00 de Argentina** y permite ejecución manual desde la pestaña **Actions** de GitHub.

Antes de generar el informe valida la sintaxis Python y ejecuta las pruebas automatizadas. Luego inicia Ollama, descarga o recupera de caché el modelo, ejecuta el radar y publica los archivos generados en el repositorio.

## Criterios de verificación y límites

- Las fechas de publicación y de realización de eventos se tratan por separado. Una actividad no se muestra como futura si su fecha no puede verificarse en el contenido original.
- Los eventos antiguos se conservan solo cuando la fecha futura y el contenido de la actividad están documentados.
- Se eliminan duplicados por título normalizado.
- Los datos, cifras, personas, alcances y conclusiones deben verificarse en el enlace original antes de preparar el copy.
- El ángulo y el formato sugeridos por IA son orientativos. La decisión editorial y la redacción final requieren revisión humana.
- Una fuente sin resultados no demuestra que no haya publicado: puede no exponer RSS, cambiar su diseño o limitar el acceso automatizado.
- La normativa debe verificarse en el texto completo, sus anexos y vigencia antes de difundir obligaciones, requisitos o beneficios.
- El bot no consulta servicios meteorológicos ni utiliza credenciales para acceder a redes sociales.

## Prueba local

Requiere Python 3.11 o superior:

```bash
python -m pip install -r requirements.txt
python radar_lechero.py
```

Para desactivar la consulta rotativa de perfiles sociales:

```bash
RADAR_SCAN_SOCIAL=0 python radar_lechero.py
```

En Windows PowerShell:

```powershell
$env:RADAR_SCAN_SOCIAL="0"
python radar_lechero.py
```

## Dependencias

- `requests`: descarga de páginas.
- `beautifulsoup4`: extracción de información de HTML.
- `feedparser`: lectura de RSS/Atom.
- `python-dateutil`: interpretación de fechas.
