import unittest
from datetime import datetime

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


if __name__ == "__main__":
    unittest.main()
