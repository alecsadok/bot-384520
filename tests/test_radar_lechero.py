import unittest
from datetime import datetime, timedelta

from unittest.mock import patch

import radar_lechero as radar


class EditorialFilterTests(unittest.TestCase):
    def test_dairy_news_is_relevant(self):
        text = "Tambos de Santa Fe incorporan tecnología para mejorar el ordeño y la producción de leche."
        relevant, tags, score = radar.is_relevant(text)
        self.assertTrue(relevant)
        self.assertGreater(score, 0)
        self.assertTrue(tags)

    def test_bovine_health_news_is_relevant(self):
        text = "SENASA actualiza medidas de sanidad bovina para prevenir brucelosis en rodeos."
        self.assertTrue(radar.editorially_relevant(text))

    def test_meat_only_news_is_excluded(self):
        text = "Aumentó la faena bovina, las exportaciones de carne y el ingreso de novillos a feedlots."
        self.assertFalse(radar.editorially_relevant(text))

    def test_grain_only_news_is_excluded(self):
        text = "La cosecha de maíz y soja avanzó en las principales regiones agrícolas."
        self.assertFalse(radar.editorially_relevant(text))

    def test_silage_and_animal_feed_are_included(self):
        text = "Productores preparan maíz para silo y reservas forrajeras para alimentar vacas lecheras."
        self.assertTrue(radar.editorially_relevant(text))

    def test_enso_must_be_a_whole_word(self):
        self.assertFalse(radar.contains_term("consenso de productores tamberos", "enso"))
        self.assertTrue(radar.contains_term("alerta por ENSO", "enso"))

    def test_ai_hard_exclusion_blocks_meat_focus(self):
        text = "Resolución sobre faena bovina, exportaciones de carne y feedlots."
        self.assertTrue(radar.ai_hard_excluded(text))

    def test_ai_hard_exclusion_blocks_grain_only(self):
        text = "Disposición sobre siembra de maíz y comercialización de soja."
        self.assertTrue(radar.ai_hard_excluded(text))

    def test_local_ai_rejects_remote_hosts(self):
        with patch.object(radar, "OLLAMA_HOST", "https://api.example.com"):
            available, message = radar.local_ai_is_available()
        self.assertFalse(available)
        self.assertIn("localhost", message)

    def test_google_news_fallback_keeps_only_relevant_items(self):
        published = datetime(2026, 11, 11, 10, 0, tzinfo=radar.TZ)
        items = [
            radar.Item(
                title="Los tambos incorporan tecnología para mejorar el ordeño",
                url="https://example.com/tambo",
                source="Google News",
                published_at=published,
                summary="La innovación mejora la producción de leche.",
            ),
            radar.Item(
                title="Sube la faena bovina y las exportaciones de carne",
                url="https://example.com/carne",
                source="Google News",
                published_at=published,
                summary="Crecen los feedlots y la faena de novillos.",
            ),
            radar.Item(
                title="Avanza la cosecha de maíz y soja",
                url="https://example.com/granos",
                source="Google News",
                published_at=published,
                summary="Resultados de la campaña agrícola.",
            ),
        ]
        filtered = radar.filter_google_news_fallback(items)
        self.assertEqual([item.url for item in filtered], ["https://example.com/tambo"])

    def test_source_and_workflow_do_not_reference_paid_openai_api(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        source = (root / "radar_lechero.py").read_text(encoding="utf-8")
        workflow = (root / ".github" / "workflows" / "radar-diario.yml").read_text(encoding="utf-8")
        self.assertNotIn("OPENAI_API_KEY", source)
        self.assertNotIn("api.openai.com", source)
        self.assertNotIn("OPENAI_API_KEY", workflow)
        self.assertNotIn("secrets.OPENAI_API_KEY", workflow)


class BulletinOfficialTests(unittest.TestCase):
    def test_listing_finds_sector_specific_official_notice(self):
        html = """
        <html><body>
          <div id="avisosSeccionDiv">
            <article>
              <h2>Resolución sobre sanidad bovina</h2>
              <a href="/detalleAviso/123">Resolución sobre sanidad bovina</a>
              <p>Requisitos para establecimientos lecheros y trazabilidad animal.</p>
            </article>
          </div>
        </body></html>
        """
        soup = radar.BeautifulSoup(html, "html.parser")
        rows = radar.bulletin_listing_candidates(soup, radar.BOLETIN_URL)
        self.assertEqual(len(rows), 1)
        self.assertIn("detalleAviso/123", rows[0]["url"])

    def test_detail_extracts_title_area_type_and_body(self):
        html = """
        <html><head><meta property="article:published_time" content="2026-11-11T09:00:00-03:00"></head>
        <body>
          <div id="tituloDetalleAviso">
            <h1>Servicio Nacional de Sanidad y Calidad Agroalimentaria</h1>
            <h2>Resolución 123/2026</h2>
          </div>
          <span class="puntero first-section">Resolución</span>
          <div id="cuerpoDetalleAviso">
            <p>Se establecen requisitos sanitarios y de identificación animal para establecimientos
            bovinos y establecimientos dedicados a la producción de leche.</p>
          </div>
        </body></html>
        """
        candidate = {
            "url": "https://www.boletinoficial.gob.ar/detalleAviso/123",
            "title_hint": "Resolución 123/2026",
            "context": "sanidad bovina",
            "discovery_score": "4",
        }
        publication_date = datetime(2026, 11, 11, 9, 0, tzinfo=radar.TZ)
        with patch.object(radar, "fetch", return_value=(
            html, candidate["url"], 200
        )):
            doc = radar.fetch_bulletin_detail(candidate, publication_date)
        self.assertIsNotNone(doc)
        self.assertEqual(doc["title"], "Resolución 123/2026")
        self.assertIn("Sanidad", doc["area"])
        self.assertEqual(doc["notice_type"], "Resolución")
        self.assertIn("producción de leche", doc["body"])
        self.assertEqual(doc["published_at"], publication_date)

    def test_ai_event_date_does_not_accept_previous_year(self):
        future_date = datetime(2026, 11, 18, tzinfo=radar.TZ)
        self.assertFalse(
            radar.ai_event_date_visible(future_date, "Jornada realizada el 18/11/2025.")
        )
        self.assertTrue(
            radar.ai_event_date_visible(future_date, "La jornada se realizará el 18 de noviembre.")
        )


class InstagramEditorialTests(unittest.TestCase):
    def test_all_previously_supplied_web_pages_are_kept(self):
        configured = {source["url"] for source in radar.WEB_SOURCES}
        required = {
            "https://www.argentina.gob.ar/noticias",
            "https://www.argentina.gob.ar/inta/noticias",
            "https://intainforma.inta.gob.ar/noticias/",
            "https://www.argentina.gob.ar/senasa",
            "https://www.todolecheria.com.ar/noticias/",
            "https://news.agrofy.com.ar/lecheria",
            "https://news.agrofy.com.ar/",
            "https://bichosdecampo.com/",
            "https://agrolink.com.ar/ultimas-noticias/",
            "https://www.clarin.com/rural/",
            "https://agroverdad.com.ar/todas-las-noticias",
            "https://mundoagrocba.com.ar/",
            "https://www.agritotal.com/",
            "https://www.infobae.com/revista-chacra/",
            "https://www.lanacion.com.ar/economia/campo/",
            "https://www.unl.edu.ar/noticias/",
            "https://www.infocampo.com.ar/",
            "https://agroempresario.com/",
            "https://portalechero.com/",
            "https://www.ocla.org.ar/",
            "https://www.fcv.unl.edu.ar/eventos/",
            "https://cmver.com.ar/",
            "https://mundorural.com.ar/",
            "https://www.infolactea.com.ar/",
            "https://www.argentina.gob.ar/economia/agricultura",
            "https://www.indec.gob.ar/",
            "https://www.bcr.com.ar/es/mercados/investigacion-y-desarrollo/informativo-semanal",
        }
        self.assertTrue(required.issubset(configured))
        self.assertTrue(radar.GOOGLE_SEARCH_REFERENCE_URL.startswith("https://www.google.com/search?"))

    def test_all_social_profiles_are_loaded_and_previous_accounts_remain(self):
        self.assertGreaterEqual(len(radar.SOCIAL_PROFILES), 100)
        self.assertIn("https://www.instagram.com/chacradebarrow", radar.SOCIAL_PROFILES)
        self.assertIn("https://www.instagram.com/eeafamailla", radar.SOCIAL_PROFILES)
        self.assertIn("https://x.com/pamperotv?lang=es", radar.SOCIAL_PROFILES)
        self.assertIn("https://x.com/senasaar", radar.SOCIAL_PROFILES)

    def test_social_rotation_covers_every_profile_without_overlap(self):
        batch_count = (
            len(radar.SOCIAL_PROFILES) + radar.SOCIAL_SCAN_BATCH_SIZE - 1
        ) // radar.SOCIAL_SCAN_BATCH_SIZE
        start_date = datetime(2026, 11, 1, tzinfo=radar.TZ)
        batches = [
            radar.social_profiles_for_run(start_date + timedelta(days=offset))
            for offset in range(batch_count)
        ]
        flattened = [url for batch in batches for url in batch]
        self.assertEqual(len(flattened), len(radar.SOCIAL_PROFILES))
        self.assertEqual(set(flattened), set(radar.SOCIAL_PROFILES))

    def test_press_and_institutional_sources_keep_equal_base_weight(self):
        published = datetime(2026, 11, 11, 10, 0, tzinfo=radar.TZ)
        institutional = radar.Item(
            title="Investigación para tambos",
            url="https://www.argentina.gob.ar/inta/noticias/ejemplo",
            source="INTA",
            published_at=published,
            relevance=60,
        )
        press = radar.Item(
            title="Investigación para tambos",
            url="https://www.todolecheria.com.ar/noticias/ejemplo",
            source="Todo Lechería",
            published_at=published,
            relevance=60,
        )
        radar.assign_editorial_metadata([institutional, press])
        self.assertEqual(institutional.relevance, press.relevance)
        self.assertNotEqual(institutional.editorial_group, press.editorial_group)

    def test_general_climate_news_is_excluded_but_dairy_impact_is_kept(self):
        self.assertFalse(
            radar.editorially_relevant(
                "Pronóstico de lluvias y temperaturas para el centro del país."
            )
        )
        self.assertTrue(
            radar.editorially_relevant(
                "La sequía reduce la disponibilidad de pasturas para tambos y vacas lecheras."
            )
        )

    def test_non_google_direct_source_survives_fallback_after_full_article_filter(self):
        published = datetime(2026, 11, 11, 10, 0, tzinfo=radar.TZ)
        direct = radar.Item(
            title="Un avance técnico en un ensayo",
            url="https://www.argentina.gob.ar/inta/noticias/ensayo",
            source="INTA",
            published_at=published,
            summary="La nota desarrolla una experiencia de investigación aplicada.",
        )
        generic_google = radar.Item(
            title="Novedades del campo",
            url="https://example.com/agro",
            source="Medio general",
            published_at=published,
            summary="Información general sin conexión con el sector pecuario.",
            discovered_via_google_news=True,
        )
        filtered = radar.filter_google_news_fallback([direct, generic_google])
        self.assertEqual([item.url for item in filtered], [direct.url])

    def test_verified_future_event_is_kept_even_if_announcement_is_older_than_news_window(self):
        now = datetime(2026, 11, 11, 12, 0, tzinfo=radar.TZ)
        event = radar.Item(
            title="Jornada técnica para tambos",
            url="https://example.com/evento",
            source="Universidad",
            published_at=now - timedelta(days=14),
            section="Evento",
            event_date=(now + timedelta(days=20)).strftime("%d/%m/%Y"),
            event_date_verified=True,
        )
        self.assertTrue(radar.should_keep_item(event, now))
        event.event_date_verified = False
        self.assertFalse(radar.should_keep_item(event, now))

    def test_editorial_schema_has_instagram_angle_and_format(self):
        properties = radar.NEWS_AI_SCHEMA["properties"]["items"]["items"]["properties"]
        self.assertIn("instagram_angle", properties)
        self.assertIn("format_suggestion", properties)
        self.assertEqual(
            properties["format_suggestion"]["enum"],
            ["Carrusel", "Reel", "Placa", "Historias", "Revisar"],
        )


if __name__ == "__main__":
    unittest.main()
