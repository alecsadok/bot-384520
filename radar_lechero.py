#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Radar INTA Lechero: recopilación determinística de noticias, eventos, normativa y clima.

No utiliza modelos de IA ni servicios de generación de texto. Los resúmenes son
extractivos y los textos sobre normativa se construyen mediante reglas explícitas.
"""

from __future__ import annotations

import concurrent.futures
import html
import json
import logging
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, asdict
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote_plus, urljoin, urlparse
from zoneinfo import ZoneInfo

import feedparser
import requests
import xlwt
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------------------------------------------------------------------------
# Configuración general
# ---------------------------------------------------------------------------
TZ_NAME = "America/Argentina/Cordoba"
TZ = ZoneInfo(TZ_NAME)
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "informes"
LOG = logging.getLogger("radar_lechero")
USER_AGENT = (
    "RadarINTALechero/1.0 (+https://github.com/alecsadok/radarIL; "
    "contact: repository-maintainer) Python requests"
)
REQUEST_TIMEOUT = (8, 18)
MAX_WORKERS = 10
MAX_LINKS_PER_SOURCE = 12
MAX_FEED_ITEMS_PER_SOURCE = 15
MAX_GOOGLE_NEWS_ITEMS = 30

# Fuentes editoriales y técnicas. Se priorizan sitios oficiales y especializados.
WEB_SOURCES: list[dict[str, str]] = [
    {"name": "Argentina.gob.ar – Noticias", "url": "https://www.argentina.gob.ar/noticias", "kind": "institucional"},
    {"name": "INTA Informa", "url": "https://intainforma.inta.gob.ar/noticias/", "kind": "institucional"},
    {"name": "SENASA", "url": "https://www.argentina.gob.ar/senasa", "kind": "institucional"},
    {"name": "Todo Lechería", "url": "https://www.todolecheria.com.ar/noticias/", "kind": "especializada"},
    {"name": "Agrofy – Lechería", "url": "https://news.agrofy.com.ar/lecheria", "kind": "especializada"},
    {"name": "Agrofy News", "url": "https://news.agrofy.com.ar/", "kind": "agro"},
    {"name": "Bichos de Campo", "url": "https://bichosdecampo.com/", "kind": "agro"},
    {"name": "Agrolink", "url": "https://agrolink.com.ar/ultimas-noticias/", "kind": "agro"},
    {"name": "Clarín Rural", "url": "https://www.clarin.com/rural/", "kind": "agro"},
    {"name": "Agroverdad", "url": "https://agroverdad.com.ar/todas-las-noticias", "kind": "agro"},
    {"name": "Mundo Agro Córdoba", "url": "https://mundoagrocba.com.ar/", "kind": "agro"},
    {"name": "Agritotal", "url": "https://www.agritotal.com/", "kind": "agro"},
    {"name": "Infobae – Revista Chacra", "url": "https://www.infobae.com/revista-chacra/", "kind": "agro"},
    {"name": "La Nación – Campo", "url": "https://www.lanacion.com.ar/economia/campo/", "kind": "agro"},
    {"name": "UNL – Noticias", "url": "https://www.unl.edu.ar/noticias/", "kind": "academica"},
    {"name": "Infocampo", "url": "https://www.infocampo.com.ar/", "kind": "agro"},
    {"name": "Agroempresario", "url": "https://agroempresario.com/", "kind": "agro"},
    {"name": "Portal Lechero", "url": "https://portalechero.com/", "kind": "especializada"},
    {"name": "OCLA", "url": "https://www.ocla.org.ar/", "kind": "especializada"},
    {"name": "FCV UNL – Eventos", "url": "https://www.fcv.unl.edu.ar/eventos/", "kind": "eventos"},
    {"name": "Colegio de Médicos Veterinarios de Santa Fe", "url": "https://cmver.com.ar/", "kind": "profesional"},
    {"name": "Mundo Rural", "url": "https://mundorural.com.ar/", "kind": "agro"},
    {"name": "InfoLáctea", "url": "https://www.infolactea.com.ar/", "kind": "especializada"},
    {"name": "INTA – Agenda y actividades", "url": "https://www.argentina.gob.ar/inta", "kind": "institucional"},
    {"name": "Secretaría de Agricultura", "url": "https://www.argentina.gob.ar/economia/agricultura", "kind": "institucional"},
    {"name": "INDEC", "url": "https://www.indec.gob.ar/", "kind": "estadistica"},
    {"name": "Bolsa de Comercio de Rosario", "url": "https://www.bcr.com.ar/es/mercados/investigacion-y-desarrollo/informativo-semanal", "kind": "economia"},
    {"name": "SMN – Servicio Meteorológico Nacional", "url": "https://www.smn.gob.ar/", "kind": "clima"},
]

# El Boletín Oficial se procesa por separado para leer la Primera Sección.
BOLETIN_URL = "https://www.boletinoficial.gob.ar/seccion/primera"
BOLETIN_HOME = "https://www.boletinoficial.gob.ar/"

# Perfiles solicitados. Se consultan como páginas públicas; no se inicia sesión,
# no se evita CAPTCHA ni se accede a endpoints privados. Meta/HTML no siempre
# contiene publicaciones, por lo que se registra cada limitación de acceso.
SOCIAL_PROFILES = [
    "https://www.instagram.com/inta_informa",
    "https://www.instagram.com/aer_inta_huinca.renanco",
    "https://www.instagram.com/aer_intariocuarto",
    "https://www.instagram.com/aercarlospellegriniinta",
    "https://www.instagram.com/asociacion_cooperadora_inta",
    "https://www.instagram.com/chacradebarrow",
    "https://www.instagram.com/eeafamailla",
    "https://www.instagram.com/extension.inta",
    "https://www.instagram.com/inta.apicultura",
    "https://www.instagram.com/inta.argentina",
    "https://www.instagram.com/inta.ascasubi",
    "https://www.instagram.com/inta.basail",
    "https://www.instagram.com/inta.bolivar",
    "https://www.instagram.com/inta.chascomus",
    "https://www.instagram.com/inta.cia",
    "https://www.instagram.com/inta.ciep",
    "https://www.instagram.com/inta.cuencadelsalado",
    "https://www.instagram.com/inta.estacion.forestal.vd",
    "https://www.instagram.com/inta.fitopatologia",
    "https://www.instagram.com/inta.floricultura",
    "https://www.instagram.com/inta.jardinbotanico",
    "https://www.instagram.com/inta.nogoya",
    "https://www.instagram.com/inta.recursosnaturales",
    "https://www.instagram.com/inta.redagua",
    "https://www.instagram.com/inta.saltajujuy",
    "https://www.instagram.com/inta.tandil",
    "https://www.instagram.com/inta.tdf",
    "https://www.instagram.com/inta_25demayo",
    "https://www.instagram.com/inta_aer_castellanos",
    "https://www.instagram.com/inta_aer_virasoro",
    "https://www.instagram.com/inta_angelgallardo",
    "https://www.instagram.com/inta_chajari",
    "https://www.instagram.com/inta_esquel",
    "https://www.instagram.com/inta_ing.juarez",
    "https://www.instagram.com/inta_laboulaye",
    "https://www.instagram.com/inta_norte_neuquino",
    "https://www.instagram.com/inta_villegas",
    "https://www.instagram.com/intaaeradeliamaria",
    "https://www.instagram.com/intaaercordoba",
    "https://www.instagram.com/intaaersanfrancisco",
    "https://www.instagram.com/intaamba",
    "https://www.instagram.com/intaangelgallardo",
    "https://www.instagram.com/intaanguil",
    "https://www.instagram.com/intaarrecifes",
    "https://www.instagram.com/intabalcarce",
    "https://www.instagram.com/intabariloche",
    "https://www.instagram.com/intabellavista",
    "https://www.instagram.com/intabellavista.forestales",
    "https://www.instagram.com/intabellavista_horticultura",
    "https://www.instagram.com/intabellville",
    "https://www.instagram.com/intabordenave",
    "https://www.instagram.com/intabordenave.agroecologia",
    "https://www.instagram.com/intacaacati",
    "https://www.instagram.com/intacatamarca",
    "https://www.instagram.com/intachacoformosa",
    "https://www.instagram.com/intachicos",
    "https://www.instagram.com/intachivilcoy",
    "https://www.instagram.com/intaciap",
    "https://www.instagram.com/intacicvya",
    "https://www.instagram.com/intacipaf",
    "https://www.instagram.com/intaconcepcion",
    "https://www.instagram.com/intaconcordia",
    "https://www.instagram.com/intacoronelsuarez",
    "https://www.instagram.com/intacorrientes",
    "https://www.instagram.com/intacrban",
    "https://www.instagram.com/intacrespo",
    "https://www.instagram.com/intacrmisiones",
    "https://www.instagram.com/intacrtucumansantiago",
    "https://www.instagram.com/intadelta",
    "https://www.instagram.com/intadiamante",
    "https://www.instagram.com/intaeeaquimili",
    "https://www.instagram.com/intaelbolson",
    "https://www.instagram.com/intaelcolorado",
    "https://www.instagram.com/intaentrerios",
    "https://www.instagram.com/intagcal",
    "https://www.instagram.com/intageneralcabrera",
    "https://www.instagram.com/intagualeguaychu",
    "https://www.instagram.com/intajesusmaria",
    "https://www.instagram.com/intajuninba",
    "https://www.instagram.com/intajuninmza",
    "https://www.instagram.com/intalarioja",
    "https://www.instagram.com/intalasbrenas",
    "https://www.instagram.com/intamakalle",
    "https://www.instagram.com/intamanfredi",
    "https://www.instagram.com/intamarcosjuarez",
    "https://www.instagram.com/intamendoza",
    "https://www.instagram.com/intamercedes",
    "https://www.instagram.com/intamercedesba",
    "https://www.instagram.com/intamontecaseros",
    "https://www.instagram.com/intanaredo",
    "https://www.instagram.com/intaolavarria",
    "https://www.instagram.com/intaparana",
    "https://www.instagram.com/intapatagonianorte",
    "https://www.instagram.com/intapergamino",
    "https://www.instagram.com/intaramacaida",
    "https://www.instagram.com/intarecursosgeneticos",
    "https://www.instagram.com/intarojas",
    "https://www.instagram.com/intasada",
    "https://www.instagram.com/intasaenzpe",
    "https://www.instagram.com/intasalta",
    "https://www.instagram.com/intasanjuan",
    "https://www.instagram.com/intasanluis",
    "https://www.instagram.com/intasanpedro",
    "https://www.instagram.com/intasantafe",
    "https://www.instagram.com/intasantiago",
    "https://www.instagram.com/intaucacha",
    "https://www.instagram.com/intavillaguay",
    "https://www.instagram.com/intavillamaria",
    "https://www.instagram.com/intayuto",
    "https://www.instagram.com/nuevapalmira.inta",
    "https://www.instagram.com/vamos_al_inta",
    "https://x.com/pamperotv?lang=es",
    "https://x.com/senasaar",
]

# ---------------------------------------------------------------------------
# Diccionario temático. Se puede ampliar en keywords_extra.txt sin tocar código.
# ---------------------------------------------------------------------------
KEYWORDS: dict[str, list[str]] = {
    "Lechería y producción láctea": [
        "lechería", "vacas", "ganado", "inta rafaela", "inta paraná", "sector lechero",
        "actividad lechera", "producción lechera", "producción de leche", "producción láctea",
        "cadena láctea", "cadena de valor láctea", "industria láctea", "industria lechera",
        "tambo", "tambos", "establecimiento lechero", "establecimientos lecheros",
        "establecimiento tambero", "establecimientos tamberos", "productor lechero",
        "productores lecheros", "productor tambero", "productores tamberos", "cuenca lechera",
        "cuencas lecheras", "sistemas de producción de leche", "sistemas lecheros",
        "sistemas pastoriles", "tambo pastoril", "tambo estabulado", "tambo robotizado",
        "tambo automatizado", "ordeño", "ordeño mecánico", "ordeño robotizado", "sala de ordeño",
        "equipos de ordeño", "máquinas de ordeño", "instalaciones de ordeño", "rutina de ordeño",
        "eficiencia de ordeño", "bienestar animal en el tambo", "gestión del tambo", "gestión lechera",
        "administración de tambos", "manejo del rodeo lechero", "eficiencia productiva", "productividad lechera",
    ],
    "Leche y productos lácteos": [
        "leche", "leche cruda", "leche bovina", "leche fluida", "leche refrigerada", "leche pasteurizada",
        "leche ultrapasteurizada", "leche en polvo", "leche concentrada", "leche en sachet",
        "productos lácteos", "productos derivados de la leche", "derivados lácteos", "quesos", "yogur",
        "manteca", "crema de leche", "dulce de leche", "suero lácteo", "lactosuero", "proteínas lácteas",
        "grasa láctea", "sólidos lácteos", "composición de la leche", "calidad de leche",
        "calidad higiénico-sanitaria de la leche", "inocuidad de productos lácteos", "análisis de leche",
        "recuento de células somáticas", "recuento bacteriano", "células somáticas",
        "residuos de antibióticos en leche", "adulteración de leche", "contaminantes en leche",
        "refrigeración de leche", "conservación de leche", "transporte de leche", "recepción de leche", "leche de calidad",
    ],
    "Rodeo lechero y reproducción": [
        "rodeo lechero", "vacas lecheras", "vacas en producción", "vacas en ordeño", "vacas secas",
        "vacas de descarte", "descarte de vacas", "vaquillonas", "vaquillonas lecheras", "reposición de vientres",
        "reposición de vaquillonas", "terneros de tambo", "terneras de tambo", "crianza artificial de terneros",
        "crianza de terneras", "recría de vaquillonas", "reproducción bovina", "reproducción en rodeos lecheros",
        "eficiencia reproductiva", "inseminación artificial", "inseminación artificial a tiempo fijo",
        "transferencia embrionaria", "genética lechera", "mejoramiento genético bovino", "selección genética",
        "biotecnología reproductiva", "fertilidad", "índices reproductivos", "parto", "período de transición",
        "período seco", "lactancia", "curva de lactancia", "producción individual", "control lechero",
        "control de producción de leche",
    ],
    "Sanidad y bienestar del rodeo": [
        "sanidad del rodeo lechero", "salud del rodeo", "sanidad bovina", "mastitis", "mastitis bovina",
        "mastitis ambiental", "mastitis contagiosa", "leucosis bovina", "brucelosis bovina", "tuberculosis bovina",
        "queratoconjuntivitis infecciosa bovina", "enfermedades del ganado lechero", "enfermedades de las vacas lecheras",
        "enfermedades de los terneros", "salud de terneros", "bienestar animal", "bienestar animal en bovinos",
        "bienestar de vacas lecheras", "estrés calórico", "estrés térmico", "índice de temperatura y humedad", "ith",
        "mortalidad de terneros", "mortalidad en rodeos lecheros", "vacunación bovina", "productos veterinarios",
        "medicamentos veterinarios", "antibióticos veterinarios", "residuos de medicamentos en leche",
        "trazabilidad animal", "identificación animal", "identificación electrónica bovina", "identificación electrónica animal",
    ],
    "Alimentación, nutrición y forrajes": [
        "alimentación de vacas lecheras", "nutrición de vacas lecheras", "nutrición bovina", "alimentación del rodeo lechero",
        "dieta de vacas lecheras", "ración para vacas lecheras", "balanceado para vacas lecheras", "suplementación",
        "suplementación alimenticia", "suplementación de vacas lecheras", "concentrados", "forrajes", "reservas forrajeras",
        "heno", "pasturas", "pasturas implantadas", "pasturas megatérmicas", "alfalfa", "verdeos", "maíz para silo",
        "sorgo forrajero", "calidad de forrajes", "calidad nutricional", "balance nutricional", "eficiencia alimenticia",
        "conversión alimenticia", "agua para consumo animal", "bebederos", "comederos", "alimentación de terneros",
        "sustitutos lácteos", "reemplazantes lácteos", "calostro",
    ],
    "Economía y comercialización": [
        "economía lechera", "economía del tambo", "costos de producción de leche", "costos de producción lechera",
        "costo por litro de leche", "precio de la leche", "precio al productor", "precio de leche cruda", "mercado lácteo",
        "mercado de la leche", "comercialización de leche", "comercialización de productos lácteos",
        "industria procesadora de leche", "exportación de productos lácteos", "importación de productos lácteos",
        "retenciones a productos lácteos", "derechos de exportación de lácteos", "rentabilidad del tambo",
        "financiamiento para tambos", "créditos para productores lecheros", "emergencia agropecuaria para productores lecheros",
        "precio internacional de la leche", "exportaciones lácteas", "mercado internacional de lácteos",
    ],
    "Regulación y organismos": [
        "senasa", "secretaría de agricultura", "inta", "registro de establecimientos lácteos",
        "habilitación de establecimientos lácteos", "habilitación de tambos", "habilitación de plantas lácteas",
        "transporte de productos lácteos", "buenas prácticas lecheras", "buenas prácticas de ordeño",
        "buenas prácticas de manufactura", "inocuidad alimentaria", "higiene del tambo", "higiene de la leche",
        "fiscalización de productos lácteos", "regulación de productos lácteos", "rotulado de productos lácteos",
        "código alimentario argentino", "ren spa", "renspa", "sigsa", "documento de tránsito electrónico",
        "identificación animal", "sanidad animal", "registro sanitario", "emergencia agropecuaria",
        "declaración de emergencia", "declaracion de emergencia", "régimen de promoción", "regimen de promocion",
        "alivio fiscal", "reducción de impuestos", "reduccion de impuestos", "crédito", "credito", "financiamiento",
        "línea de crédito", "linea de credito", "comercio exterior", "derechos de exportación", "derechos de exportacion",
        "retenciones", "exportación", "exportacion", "importación", "importacion", "aranceles", "semillas",
        "fertilizantes", "fitosanitarios", "alimentos balanceados", "zoonosis", "transporte de animales",
        "transporte de alimentos", "faena bovina", "ganadería", "ganaderia", "agropecuario", "agropecuaria",
        "tarifa eléctrica", "tarifa electrica", "combustibles", "energía", "energia", "costos logísticos",
        "costos logisticos", "iva", "industria alimenticia",
    ],
    "Clima y ambiente": [
        "clima", "tiempo", "pronóstico", "pronostico", "alerta meteorológica", "alerta por tormentas", "lluvias",
        "precipitaciones", "temperatura", "ola de calor", "ola de frío", "sequía", "inundación", "granizo",
        "vientos", "humedad", "índice de temperatura y humedad", "ith", "estrés calórico", "estrés térmico",
        "balance hídrico", "agua", "anegamiento", "exceso hídrico", "déficit hídrico", "heladas",
        "cambio climático", "variabilidad climática", "pronóstico agroclimático", "suelos", "barbecho",
    ],
}

EVENT_WORDS = [
    "jornada", "jornadas", "curso", "cursos", "capacitación", "capacitacion", "seminario", "congreso",
    "encuentro", "taller", "día de campo", "dia de campo", "webinar", "charla", "conferencia", "expo",
    "exposición", "exposicion", "feria", "inscripción", "inscripcion", "convocatoria", "reunión", "reunion",
    "demostración", "demostracion", "entrenamiento", "actualización", "actualizacion", "foro",
]
BROAD_TERMS = {"leche", "vaca", "vacas", "ganado", "campo", "inta", "agro", "rural", "producción", "produccion"}

# ---------------------------------------------------------------------------
# Modelos y utilidades
# ---------------------------------------------------------------------------
@dataclass
class Item:
    title: str
    url: str
    source: str
    published_at: datetime
    summary: str = ""
    section: str = "Noticia"
    tags: list[str] | None = None
    event_date: str = ""
    legal_copy: str = ""
    relevance: int = 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["published_at"] = self.published_at.isoformat()
        d["tags"] = self.tags or []
        return d


def make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "es-AR,es;q=0.9,en;q=0.5"})
    return session


def normalize(text: str) -> str:
    text = html.unescape(text or "").lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_text(value: str, limit: int = 900) -> str:
    value = BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)
    value = html.unescape(re.sub(r"\s+", " ", value)).strip()
    return value[:limit]


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip()
        if not raw:
            return None
        raw = raw.replace("Z", "+00:00")
        # ISO-8601 debe parsearse sin dayfirst: de otro modo 2026-11-10
        # puede interpretarse erróneamente como 11 de octubre.
        if re.match(r"^\d{4}-\d{2}-\d{2}(?:T|\s|$)", raw):
            try:
                dt = datetime.fromisoformat(raw)
            except ValueError:
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TZ)
            return dt.astimezone(TZ)
        months = {
            "enero": "January", "febrero": "February", "marzo": "March", "abril": "April",
            "mayo": "May", "junio": "June", "julio": "July", "agosto": "August",
            "septiembre": "September", "setiembre": "September", "octubre": "October",
            "noviembre": "November", "diciembre": "December",
        }
        low = normalize(raw)
        for es, en in months.items():
            low = re.sub(rf"\b{normalize(es)}\b", en, low)
        # dateutil con fuzzy rescata fechas que aparecen dentro de etiquetas o frases.
        try:
            dt = date_parser.parse(low, fuzzy=True, dayfirst=True)
        except (ValueError, TypeError, OverflowError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def extract_text_dates(text: str) -> list[datetime]:
    results: list[datetime] = []
    patterns = [
        r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{1,2}\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)(?:\s+de)?\s+\d{4}\b",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, text or "", flags=re.IGNORECASE):
            dt = parse_datetime(match)
            if dt:
                results.append(dt)
    return results


def all_keywords() -> list[str]:
    return sorted({kw for group in KEYWORDS.values() for kw in group}, key=len, reverse=True)


def classify(text: str) -> tuple[list[str], int]:
    ntext = normalize(text)
    tags: list[str] = []
    score = 0
    for category, terms in KEYWORDS.items():
        hits = [term for term in terms if normalize(term) in ntext]
        if hits:
            tags.append(category)
            score += sum(3 if len(normalize(term).split()) > 1 else 1 for term in hits[:12])
    # Se penalizan coincidencias genéricas si no hay términos de lechería concretos.
    matched = [kw for kw in all_keywords() if normalize(kw) in ntext]
    specific = [kw for kw in matched if normalize(kw) not in BROAD_TERMS]
    if not specific and len(matched) < 2:
        score = 0
        tags = []
    return tags, score


def is_relevant(text: str, min_score: int = 1) -> tuple[bool, list[str], int]:
    tags, score = classify(text)
    return score >= min_score, tags, score


def extract_jsonld_dates(soup: BeautifulSoup) -> list[datetime]:
    values: list[datetime] = []
    for script in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                for key in ("datePublished", "dateCreated", "uploadDate"):
                    if node.get(key):
                        dt = parse_datetime(node[key])
                        if dt:
                            values.append(dt)
                for val in node.values():
                    if isinstance(val, (dict, list)):
                        stack.append(val)
            elif isinstance(node, list):
                stack.extend(node)
    return values


def extract_published_date(soup: BeautifulSoup, fallback: datetime | None = None) -> datetime | None:
    # Prioridad a campos semánticos de publicación; no usar fechas de modificación
    # porque una nota antigua actualizada hoy no debe entrar en la ventana de 24 h.
    for tag in soup.find_all("meta"):
        key = (tag.get("property") or tag.get("name") or tag.get("itemprop") or "").lower()
        if "modified" in key or "updated" in key:
            continue
        if any(k in key for k in ("published_time", "datepublished", "pubdate", "publishdate", "publication_date")):
            dt = parse_datetime(tag.get("content"))
            if dt:
                return dt
    jsonld_dates = extract_jsonld_dates(soup)
    if jsonld_dates:
        return min(jsonld_dates)
    for tag in soup.find_all("time"):
        dt = parse_datetime(tag.get("datetime") or tag.get_text(" ", strip=True))
        if dt:
            return dt
    for tag in soup.find_all("meta"):
        key = (tag.get("property") or tag.get("name") or tag.get("itemprop") or "").lower()
        if "modified" in key or "updated" in key:
            continue
        if any(k in key for k in ("date", "created", "publication")):
            dt = parse_datetime(tag.get("content"))
            if dt:
                return dt
    body = clean_text(soup.get_text(" ", strip=True), 10000)
    text_dates = extract_text_dates(body[:3000])
    if text_dates:
        return text_dates[0]
    return fallback


def is_within_window(dt: datetime | None, now: datetime, hours: int = 24) -> bool:
    if dt is None:
        return False
    return now - timedelta(hours=hours) <= dt <= now + timedelta(minutes=10)


def guess_event_date(text: str, now: datetime) -> str:
    dates = extract_text_dates(text)
    future = [dt for dt in dates if dt.date() >= now.date() and dt <= now + timedelta(days=365)]
    if future:
        return min(future).strftime("%d/%m/%Y")
    return ""


def summarize(text: str, max_chars: int = 320) -> str:
    text = clean_text(text, 8000)
    if not text:
        return "No se encontró una descripción textual accesible en la fuente. Consultar el enlace original."
    # Descarta navegación, rótulos y encabezados excesivamente cortos.
    parts = re.split(r"(?<=[.!?])\s+", text)
    selected = " ".join(p for p in parts if len(p.strip()) > 35)[:max_chars].strip()
    return selected or text[:max_chars]


def absolute_url(base: str, href: str) -> str:
    return urljoin(base, href.strip())


def host_matches(a: str, b: str) -> bool:
    try:
        ha, hb = urlparse(a).netloc.lower(), urlparse(b).netloc.lower()
        return ha == hb or ha.endswith("." + hb) or hb.endswith("." + ha)
    except Exception:
        return False


def fetch(url: str, timeout: tuple[int, int] = REQUEST_TIMEOUT) -> tuple[str, str, int]:
    try:
        response = make_session().get(url, timeout=timeout, allow_redirects=True)
        content_type = response.headers.get("content-type", "")
        if response.status_code >= 400:
            return "", response.url, response.status_code
        if "html" not in content_type.lower() and "xml" not in content_type.lower() and "text" not in content_type.lower():
            return "", response.url, response.status_code
        response.encoding = response.apparent_encoding or response.encoding
        return response.text, response.url, response.status_code
    except requests.RequestException as exc:
        LOG.debug("No se pudo consultar %s: %s", url, exc)
        return "", url, 0


def discover_feed_urls(page_url: str, html_doc: str) -> list[str]:
    soup = BeautifulSoup(html_doc, "html.parser")
    feeds = []
    for link in soup.find_all("link", href=True):
        typ = (link.get("type") or "").lower()
        rel = " ".join(link.get("rel", [])).lower()
        if "alternate" in rel and any(x in typ for x in ("rss", "atom", "xml")):
            feeds.append(absolute_url(page_url, link["href"]))
    # Respaldo acotado para WordPress cuando no hay autodiscovery.
    generator = soup.find("meta", attrs={"name": "generator"})
    if not feeds and generator and "wordpress" in normalize(generator.get("content", "")):
        parsed = urlparse(page_url)
        feeds.append(f"{parsed.scheme}://{parsed.netloc}/feed/")
    return list(dict.fromkeys(feeds))[:4]


def parse_feed(feed_url: str, source_name: str, now: datetime) -> list[Item]:
    feed_raw, _, _ = fetch(feed_url)
    if not feed_raw:
        return []
    parsed = feedparser.parse(feed_raw)
    output: list[Item] = []
    for entry in parsed.entries[:MAX_FEED_ITEMS_PER_SOURCE]:
        title = clean_text(entry.get("title", ""), 300)
        link = entry.get("link", "")
        if not title or not link:
            continue
        pub = None
        for key in ("published_parsed", "updated_parsed"):
            st = entry.get(key)
            if st:
                try:
                    pub = datetime(*st[:6], tzinfo=timezone.utc).astimezone(TZ)
                    break
                except Exception:
                    pass
        if pub is None:
            pub = parse_datetime(entry.get("published") or entry.get("updated"))
        summary = clean_text(entry.get("summary", ""), 700)
        text = f"{title} {summary}"
        relevant, tags, score = is_relevant(text)
        # Listados especializados pueden publicar eventos de formación sin repetir términos técnicos en el título.
        if not relevant and source_name in ("FCV UNL – Eventos", "Todo Lechería", "OCLA"):
            relevant, tags, score = is_relevant(f"{text} lechería tambo vacas")
        if not relevant or not is_within_window(pub, now):
            continue
        is_event = any(normalize(w) in normalize(text) for w in EVENT_WORDS)
        output.append(Item(
            title=title,
            url=link,
            source=source_name,
            published_at=pub,
            summary=summary or summarize(text),
            section="Evento" if is_event else "Noticia",
            tags=tags,
            event_date=guess_event_date(text, now),
            relevance=score,
        ))
    return output


def candidate_links(page_url: str, page_html: str, now: datetime) -> list[tuple[str, str, str]]:
    soup = BeautifulSoup(page_html, "html.parser")
    found: dict[str, tuple[str, str]] = {}
    for anchor in soup.find_all("a", href=True):
        title = clean_text(anchor.get_text(" ", strip=True), 260)
        href = absolute_url(page_url, anchor["href"])
        if len(title) < 18 or len(title) > 260:
            continue
        if not href.startswith("http") or not host_matches(href, page_url):
            continue
        parsed_path = urlparse(href).path.lower()
        if any(x in parsed_path for x in ("/tag/", "/category/", "/author/", "/contact", "/login", "/wp-json", "/page/")):
            continue
        if href.rstrip("/") == page_url.rstrip("/"):
            continue
        context_node = anchor
        for _ in range(3):
            if context_node.parent:
                context_node = context_node.parent
        context = clean_text(context_node.get_text(" ", strip=True), 700)
        relevant, tags, score = is_relevant(f"{title} {context}")
        # Los sitios de eventos y especializados admiten títulos más generales, siempre que el contexto lo vincule.
        if not relevant:
            continue
        if href not in found:
            found[href] = (title, context)
    return [(u, t, c) for u, (t, c) in list(found.items())[:MAX_LINKS_PER_SOURCE]]


def parse_article(url: str, title_hint: str, context_hint: str, source_name: str, now: datetime) -> Item | None:
    raw, final_url, status = fetch(url)
    if not raw:
        return None
    soup = BeautifulSoup(raw, "html.parser")
    title = ""
    og_title = soup.find("meta", attrs={"property": "og:title"})
    h1 = soup.find("h1")
    title = clean_text((og_title.get("content") if og_title else "") or (h1.get_text(" ", strip=True) if h1 else "") or title_hint, 300)
    if len(title) < 10:
        title = title_hint
    description = ""
    for attrs in ({"property": "og:description"}, {"name": "description"}, {"name": "twitter:description"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            description = clean_text(tag.get("content"), 900)
            break
    article_node = soup.find("article") or soup.find("main") or soup.body or soup
    body_text = clean_text(article_node.get_text(" ", strip=True), 12000)
    text = f"{title} {description} {context_hint} {body_text}"
    relevant, tags, score = is_relevant(text)
    if not relevant:
        return None
    published = extract_published_date(soup)
    if not is_within_window(published, now):
        return None
    is_event = any(normalize(w) in normalize(f"{title} {description} {context_hint}") for w in EVENT_WORDS)
    # No se toma la fecha de una jornada pasada como fecha futura del evento.
    event_date = guess_event_date(f"{title} {description} {context_hint} {body_text[:5000]}", now) if is_event else ""
    return Item(
        title=title,
        url=final_url or url,
        source=source_name,
        published_at=published,
        summary=summarize(description or body_text or context_hint),
        section="Evento" if is_event else "Noticia",
        tags=tags,
        event_date=event_date,
        relevance=score,
    )


def scan_web_source(source: dict[str, str], now: datetime) -> tuple[list[Item], dict[str, Any]]:
    name, url = source["name"], source["url"]
    raw, final_url, status = fetch(url)
    status_row = {"fuente": name, "url": url, "estado": "consultada" if raw else f"sin acceso (HTTP {status or 'error'})"}
    if not raw:
        return [], status_row

    results: list[Item] = []
    soup = BeautifulSoup(raw, "html.parser")
    feeds = discover_feed_urls(final_url, raw)
    for feed_url in feeds:
        try:
            results.extend(parse_feed(feed_url, name, now))
        except Exception as exc:
            LOG.debug("Feed %s: %s", feed_url, exc)

    links = candidate_links(final_url, raw, now)
    if not results and not links:
        status_row["estado"] = "consultada; sin resultados detectables en el HTML público"
    elif links:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(parse_article, u, t, c, name, now) for u, t, c in links]
            for future in concurrent.futures.as_completed(futures):
                try:
                    item = future.result()
                    if item:
                        results.append(item)
                except Exception as exc:
                    LOG.debug("Artículo de %s: %s", name, exc)
    status_row["resultados"] = len(results)
    return results, status_row


def google_news_queries() -> list[str]:
    # Consultas separadas para evitar búsquedas de términos excesivamente amplios.
    return [
        '(lechería OR lechero OR tambo OR tambos) Argentina when:1d',
        '("vacas lecheras" OR "rodeo lechero" OR "producción de leche") Argentina when:1d',
        '(mastitis OR terneros OR vaquillonas OR reproducción bovina) lechería Argentina when:1d',
        '(OCLA OR "precio de la leche" OR "industria láctea" OR lácteos) Argentina when:1d',
        '(INTA Rafaela OR INTA lechería OR INTA tambo) Argentina when:1d',
        '(SENASA bovinos OR trazabilidad animal OR identificación electrónica bovina) Argentina when:1d',
        '(forrajes OR alfalfa OR silo OR nutrición bovina) tambo Argentina when:1d',
        '(clima OR lluvias OR sequía OR calor OR ITH) tambo Santa Fe Argentina when:1d',
    ]


def scan_google_news(now: datetime) -> tuple[list[Item], dict[str, Any]]:
    results: list[Item] = []
    seen: set[str] = set()
    for query in google_news_queries():
        url = "https://news.google.com/rss/search?q=" + quote_plus(query) + "&hl=es-419&gl=AR&ceid=AR:es-419"
        try:
            feed_raw, _, _ = fetch(url)
            if not feed_raw:
                continue
            parsed = feedparser.parse(feed_raw)
        except Exception:
            continue
        for entry in parsed.entries[:MAX_GOOGLE_NEWS_ITEMS]:
            title = clean_text(entry.get("title", ""), 300)
            link = entry.get("link", "")
            if not title or not link or link in seen:
                continue
            seen.add(link)
            st = entry.get("published_parsed")
            pub = None
            if st:
                try:
                    pub = datetime(*st[:6], tzinfo=timezone.utc).astimezone(TZ)
                except Exception:
                    pass
            if pub is None:
                pub = parse_datetime(entry.get("published"))
            source_obj = entry.get("source", {}) or {}
            source_name = clean_text(source_obj.get("title", "Google News"), 120)
            summary = clean_text(entry.get("summary", ""), 600)
            relevant, tags, score = is_relevant(f"{title} {summary}")
            if relevant and is_within_window(pub, now):
                event = any(normalize(w) in normalize(title) for w in EVENT_WORDS)
                results.append(Item(
                    title=title,
                    url=link,
                    source=f"Google News · {source_name}",
                    published_at=pub,
                    summary=summary or "Resultado detectado por Google News; abrir la fuente para consultar el contenido completo.",
                    section="Evento" if event else "Noticia",
                    tags=tags,
                    event_date=guess_event_date(f"{title} {summary}", now) if event else "",
                    relevance=score,
                ))
    return results, {"fuente": "Google News RSS", "url": "https://news.google.com/", "estado": "consultada", "resultados": len(results)}

# ---------------------------------------------------------------------------
# Boletín Oficial: Primera Sección (Legislación y Avisos Oficiales)
# ---------------------------------------------------------------------------
def legal_impact_copy(title: str, body: str, url: str, pub: datetime, tags: list[str]) -> str:
    text = normalize(f"{title} {body}")
    effects: list[str] = []
    rules = [
        (("credito", "financiamiento", "financiacion", "subsidio", "bonificacion", "tasa preferencial", "asistencia financiera"),
         "La norma contempla herramientas de financiamiento, asistencia o condiciones económicas que podrían ser relevantes para productores alcanzados. Conviene verificar requisitos, beneficiarios, plazos y organismo de aplicación."),
        (("emergencia agropecuaria", "desastre agropecuario", "prorroga", "alivio fiscal", "exencion", "beneficio fiscal"),
         "Puede habilitar alivios, prórrogas o tratamientos especiales para quienes cumplan las condiciones previstas. El productor debe comprobar si su establecimiento y su zona están incluidos."),
        (("retencion", "derechos de exportacion", "arancel", "exportacion", "importacion", "comercializacion"),
         "Puede modificar condiciones de comercialización, costos o incentivos de la cadena láctea. El efecto sobre el precio de la leche al productor no es automático y depende de la implementación y del mercado."),
        (("sanidad animal", "vacunacion", "brucelosis", "tuberculosis", "trazabilidad", "identificacion electronica", "renspa", "sigsa"),
         "Incide en obligaciones o procedimientos sanitarios y de identificación del ganado. Para el tambo, el valor práctico está en conocer qué animales, registros, plazos y responsables quedan alcanzados."),
        (("leche", "lacteo", "lacteos", "tambo", "establecimiento lechero", "producto alimenticio", "codigo alimentario"),
         "Tiene relación con la producción, elaboración, inocuidad o circulación de leche y productos lácteos. Puede requerir adecuaciones documentales, operativas o sanitarias según el tipo de establecimiento alcanzado."),
        (("forraje", "semilla", "pastura", "fertilizante", "agroquimico", "agua", "riego"),
         "Puede relacionarse con insumos y recursos que integran los costos de alimentación y producción del tambo. Es necesario confirmar qué productos, actividades y sujetos quedan comprendidos."),
    ]
    for tokens, message in rules:
        if any(token in text for token in tokens):
            effects.append(message)
    if not effects:
        effects.append(
            "La publicación contiene términos vinculados con el sector agropecuario, pero el texto disponible no permite afirmar un beneficio directo para todos los tambos. Antes de comunicar un impacto, hay que revisar el alcance, los sujetos obligados, la vigencia y los anexos de la norma."
        )
    distinct = list(dict.fromkeys(effects))
    tag_text = ", ".join(tags[:4]) if tags else "actividad agropecuaria"
    # Copy institucional, sin atribuir efectos jurídicos que el articulado no exprese.
    return (
        f"📌 {title}\n\n"
        f"El Boletín Oficial publicó esta disposición el {pub.strftime('%d/%m/%Y')}. "
        f"Su contenido se relaciona con {tag_text}.\n\n"
        f"¿Qué debe mirar el sector tambero?\n"
        + " ".join(distinct)
        + "\n\n"
        "Antes de tomar decisiones, revisar el texto oficial completo, sus anexos, la fecha de entrada en vigencia "
        "y la autoridad de aplicación. Este resumen es orientativo y no reemplaza la lectura de la norma.\n\n"
        f"🔎 Texto oficial: {url}"
    )


def scrape_bulletin(now: datetime) -> tuple[list[Item], dict[str, Any]]:
    raw, final_url, status = fetch(BOLETIN_URL)
    status_row = {"fuente": "Boletín Oficial – Primera Sección", "url": BOLETIN_URL, "estado": "consultada" if raw else f"sin acceso (HTTP {status or 'error'})"}
    if not raw:
        return [], status_row
    soup = BeautifulSoup(raw, "html.parser")
    page_text = clean_text(soup.get_text(" ", strip=True), 16000)
    edition_dates = extract_text_dates(page_text[:2500])
    edition_date = edition_dates[0] if edition_dates else None
    results: list[Item] = []

    anchors = soup.find_all("a", href=True)
    candidates: dict[str, str] = {}
    for a in anchors:
        href = absolute_url(final_url, a["href"])
        title = clean_text(a.get_text(" ", strip=True), 300)
        if len(title) < 14:
            continue
        # Se aceptan las páginas individuales y los enlaces internos con título de norma.
        p = urlparse(href)
        if not host_matches(href, BOLETIN_HOME):
            continue
        context_node = a
        for _ in range(2):
            if context_node.parent:
                context_node = context_node.parent
        local_context = clean_text(context_node.get_text(" ", strip=True), 700)
        relevant, tags, score = is_relevant(f"{title} {local_context}")
        is_notice_link = any(word in normalize(href) for word in ("detalleaviso", "aviso", "norma"))
        if relevant or (is_notice_link and any(normalize(term) in normalize(local_context) for term in ("leche", "bovino", "agropecuario", "agricultura", "ganaderia", "sanidad animal"))):
            candidates[href] = title or local_context[:250]
    # Respaldo: filas/tarjetas que no tienen un href individual pueden contener títulos.
    if not candidates:
        for node in soup.find_all(["article", "li", "tr", "div"]):
            txt = clean_text(node.get_text(" ", strip=True), 500)
            relevant, _, _ = is_relevant(txt)
            if relevant and len(txt) > 35:
                a = node.find("a", href=True)
                link = absolute_url(final_url, a["href"]) if a else BOLETIN_URL
                candidates[link] = txt[:300]

    candidate_pairs = [(href, title_hint) for href, title_hint in list(candidates.items())[:50] if href != BOLETIN_URL]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(fetch, href) for href, _ in candidate_pairs]
        for future, (href, title_hint) in zip(futures, candidate_pairs):
            try:
                article_html, article_url, article_status = future.result()
            except Exception:
                continue
            if not article_html:
                pub = edition_date
                relevant, tags, score = is_relevant(title_hint)
                anchor_text = normalize(title_hint)
                sector_anchor = any(term in anchor_text for term in ("leche", "lact", "tambo", "bovino", "ganad", "agropec", "agricultur", "animal", "forraj", "semilla", "veterin", "inta", "senasa"))
                if relevant and sector_anchor and is_within_window(pub, now):
                    fallback_summary = "Publicación detectada en la edición diaria. La ficha o el texto completo no pudo recuperarse automáticamente; abrir el enlace oficial para revisar el articulado."
                    results.append(Item(
                        title=title_hint,
                        url=href,
                        source="Boletín Oficial – Primera Sección",
                        published_at=pub,
                        summary=fallback_summary,
                        section="Normativa",
                        tags=tags,
                        legal_copy=legal_impact_copy(title_hint, title_hint, href, pub, tags),
                        relevance=score + 5,
                    ))
                continue
            article_soup = BeautifulSoup(article_html, "html.parser")
            title_tag = article_soup.find("h1") or article_soup.find("title")
            title = clean_text(title_tag.get_text(" ", strip=True) if title_tag else title_hint, 320)
            article_node = article_soup.find("article") or article_soup.find("main") or article_soup.body or article_soup
            body = clean_text(article_node.get_text(" ", strip=True), 14000)
            full = f"{title} {body}"
            relevant, tags, score = is_relevant(full)
            anchor_text = normalize(full)
            sector_anchor = any(term in anchor_text for term in ("leche", "lact", "tambo", "bovino", "ganad", "agropec", "agricultur", "animal", "forraj", "semilla", "veterin", "inta", "senasa"))
            if not relevant or not sector_anchor:
                continue
            pub = extract_published_date(article_soup) or edition_date
            # La Primera Sección muestra la edición consultada. Sin fecha visible no se inventa.
            if not is_within_window(pub, now):
                continue
            summary = summarize(body, 450)
            item = Item(
                title=title,
                url=article_url or href,
                source="Boletín Oficial – Primera Sección",
                published_at=pub,
                summary=summary,
                section="Normativa",
                tags=tags,
                legal_copy=legal_impact_copy(title, body, article_url or href, pub, tags),
                relevance=score + 5,
            )
            results.append(item)

    # Si el sitio no expone ficha individual detectable, el reporte conserva estado transparente.
    status_row["edicion"] = edition_date.strftime("%d/%m/%Y") if edition_date else "fecha no identificada en HTML"
    status_row["enlaces_candidatos"] = len(candidates)
    status_row["resultados"] = len(results)
    if not candidates:
        status_row["estado"] = "consultada; el HTML no expuso fichas individuales detectables"
    return results, status_row

# ---------------------------------------------------------------------------
# Redes sociales (consulta de páginas públicas, sin autenticación)
# ---------------------------------------------------------------------------
def scan_social_profile(url: str, now: datetime) -> tuple[list[Item], dict[str, Any]]:
    raw, final_url, status = fetch(url, timeout=(3, 6))
    handle = urlparse(url).path.strip("/")
    if not raw:
        return [], {"fuente": handle, "url": url, "estado": f"acceso restringido o bloqueado (HTTP {status or 'error'})"}
    soup = BeautifulSoup(raw, "html.parser")
    description = ""
    for attrs in ({"property": "og:description"}, {"name": "description"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            description = clean_text(tag.get("content"), 260)
            break

    # Cuando la propia página pública entrega enlaces a posts, se consultan hasta
    # dos publicaciones recientes. No se intenta iniciar sesión ni eludir bloqueos.
    is_instagram = "instagram.com" in urlparse(final_url).netloc.lower()
    post_urls: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = absolute_url(final_url, anchor["href"])
        path = urlparse(href).path.lower()
        if is_instagram and re.search(r"/(p|reel|tv)/[a-z0-9_-]+", path):
            post_urls.append(href)
        elif not is_instagram and re.search(r"/status/\d+", path):
            post_urls.append(href)
    post_urls = list(dict.fromkeys(post_urls))[:2]
    source_name = ("Instagram " if is_instagram else "X ") + "@" + handle.split("/")[0]
    items: list[Item] = []
    if post_urls:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(parse_article, post_url, f"Publicación de {source_name}", "", source_name, now) for post_url in post_urls]
            for future in concurrent.futures.as_completed(futures):
                try:
                    item = future.result()
                    if item:
                        items.append(item)
                except Exception as exc:
                    LOG.debug("Publicación social %s: %s", url, exc)
    state = "posts públicos consultados" if items else (
        "página pública consultada; no se expusieron publicaciones fechadas en el HTML" if not post_urls
        else "se detectaron enlaces a publicaciones, pero no se pudo verificar contenido y fecha"
    )
    return items, {
        "fuente": handle,
        "url": final_url,
        "estado": state,
        "metadatos": description,
        "resultados": len(items),
    }

# ---------------------------------------------------------------------------
# Tiempo y clima: Servicio Meteorológico Nacional (SMN)
# ---------------------------------------------------------------------------
def recursive_records(data: Any) -> Iterable[dict[str, Any]]:
    if isinstance(data, dict):
        yield data
        for value in data.values():
            yield from recursive_records(value)
    elif isinstance(data, list):
        for value in data:
            yield from recursive_records(value)


def smn_get(url: str) -> Any:
    try:
        response = make_session().get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        LOG.warning("SMN no disponible (%s): %s", url, exc)
        return None


def get_weather(now: datetime) -> dict[str, Any]:
    observations = smn_get("https://ws.smn.gob.ar/map_items/weather")
    forecasts = smn_get("https://ws.smn.gob.ar/map_items/forecast/3")
    alerts = smn_get("https://ws.smn.gob.ar/alerts/type/AL")
    city_rows: list[dict[str, Any]] = []
    if observations:
        for row in recursive_records(observations):
            label = normalize(str(row.get("name") or row.get("station") or row.get("localidad") or ""))
            province = normalize(str(row.get("province") or row.get("provincia") or ""))
            if "rafaela" in label or ("santa fe" in province and "rafaela" in label):
                weather = row.get("weather") if isinstance(row.get("weather"), dict) else row
                updated = row.get("updated") or row.get("timestamp")
                updated_dt = None
                if isinstance(updated, (int, float)):
                    updated_dt = datetime.fromtimestamp(updated, tz=timezone.utc).astimezone(TZ)
                city_rows.append({
                    "localidad": row.get("name") or "Rafaela",
                    "provincia": row.get("province") or "Santa Fe",
                    "temperatura": weather.get("temp") or weather.get("temperature") or weather.get("temperature_c"),
                    "humedad": weather.get("humidity") or weather.get("relative_humidity"),
                    "presion": weather.get("pressure") or weather.get("pressure_hpa"),
                    "viento": weather.get("wind_speed") or weather.get("wind_speed_kmh"),
                    "descripcion": weather.get("description") or weather.get("weather_desc") or weather.get("name"),
                    "actualizado": updated_dt.strftime("%d/%m/%Y %H:%M") if updated_dt else "no informado por la API",
                    "fuente": "SMN – observaciones",
                    "url": "https://ws.smn.gob.ar/map_items/weather",
                })
                if len(city_rows) >= 3:
                    break
    forecast_rows: list[dict[str, Any]] = []
    if forecasts:
        for row in recursive_records(forecasts):
            label = normalize(str(row.get("name") or row.get("localidad") or row.get("city") or ""))
            if "rafaela" in label:
                forecast_rows.append({"dato": row, "fuente": "SMN – pronóstico", "url": "https://ws.smn.gob.ar/map_items/forecast/3"})
                if len(forecast_rows) >= 2:
                    break
    alert_rows: list[dict[str, Any]] = []
    if alerts:
        for row in recursive_records(alerts):
            blob = normalize(json.dumps(row, ensure_ascii=False))
            if "santa fe" in blob or "rafaela" in blob:
                # No se expanden objetos internos; se conserva el texto oficial resumido.
                alert_rows.append({"texto": clean_text(json.dumps(row, ensure_ascii=False), 700), "fuente": "SMN – alertas vigentes", "url": "https://ws.smn.gob.ar/alerts/type/AL"})
                if len(alert_rows) >= 5:
                    break
    return {
        "consultado": now.strftime("%d/%m/%Y %H:%M %Z"),
        "observaciones_rafaela": city_rows,
        "pronostico_rafaela": forecast_rows,
        "alertas_santa_fe": alert_rows,
        "fuentes": [
            {"nombre": "SMN – observaciones", "url": "https://ws.smn.gob.ar/map_items/weather"},
            {"nombre": "SMN – pronóstico a 3 días", "url": "https://ws.smn.gob.ar/map_items/forecast/3"},
            {"nombre": "SMN – alertas vigentes", "url": "https://ws.smn.gob.ar/alerts/type/AL"},
        ],
    }

# ---------------------------------------------------------------------------
# Dedupe, HTML y XLS
# ---------------------------------------------------------------------------
def deduplicate(items: list[Item]) -> list[Item]:
    best: dict[str, Item] = {}
    for item in items:
        key = normalize(item.title)
        if not key:
            key = item.url
        current = best.get(key)
        if current is None or item.relevance > current.relevance:
            best[key] = item
    return sorted(best.values(), key=lambda x: (x.section != "Normativa", x.section != "Evento", -x.relevance, x.published_at), reverse=False)


def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def render_html(items: list[Item], weather: dict[str, Any], statuses: list[dict[str, Any]], now: datetime, window_start: datetime) -> str:
    day_label = now.strftime("%d/%m/%Y")
    counts = {
        "total": len(items),
        "noticias": sum(i.section == "Noticia" for i in items),
        "eventos": sum(i.section == "Evento" for i in items),
        "normativa": sum(i.section == "Normativa" for i in items),
    }
    sections = [("Normativa", "Normativa y Boletín Oficial"), ("Evento", "Agenda y eventos"), ("Noticia", "Noticias del sector")]
    cards = []
    for section, heading in sections:
        subset = [i for i in items if i.section == section]
        cards.append(f'<section class="section"><h2>{heading} <span>{len(subset)}</span></h2>')
        if not subset:
            cards.append('<p class="empty">No se detectaron publicaciones que cumplan el filtro de las últimas 24 horas.</p>')
        for item in subset:
            tags = " · ".join(item.tags or [])
            pub = item.published_at.strftime("%d/%m/%Y %H:%M")
            event = f'<p class="event-date">Fecha del evento: <strong>{esc(item.event_date)}</strong></p>' if item.event_date else ""
            legal = f'<div class="copy"><h4>Copy institucional sugerido (borrador automático)</h4><pre>{esc(item.legal_copy)}</pre></div>' if item.legal_copy else ""
            cards.append(
                '<article class="item">'
                f'<div class="meta"><span>{esc(item.source)}</span><span>Publicado: {pub}</span></div>'
                f'<h3><a href="{esc(item.url)}" target="_blank" rel="noopener">{esc(item.title)}</a></h3>'
                f'<p>{esc(item.summary)}</p>{event}'
                f'<p class="tags">{esc(tags)}</p>{legal}'
                '</article>'
            )
        cards.append('</section>')

    weather_parts = []
    for row in weather.get("observaciones_rafaela", []):
        weather_parts.append(
            '<div class="weather-card"><strong>Rafaela, Santa Fe</strong>'
            f'<p>Temperatura: {esc(row.get("temperatura", "s/d"))} °C · Humedad: {esc(row.get("humedad", "s/d"))}%</p>'
            f'<p>Viento: {esc(row.get("viento", "s/d"))} · Presión: {esc(row.get("presion", "s/d"))}</p>'
            f'<p>{esc(row.get("descripcion", ""))} · Observación: {esc(row.get("actualizado", ""))}</p>'
            f'<a href="{esc(row.get("url"))}" target="_blank" rel="noopener">Datos del SMN</a></div>'
        )
    if not weather_parts:
        weather_parts.append('<p class="empty">No se pudo recuperar una observación específica de Rafaela desde el endpoint público del SMN.</p>')
    alert_html = "".join(f'<li>{esc(a.get("texto"))} <a href="{esc(a.get("url"))}">Fuente SMN</a></li>' for a in weather.get("alertas_santa_fe", []))
    forecast_html = "".join(f'<li><a href="{esc(f.get("url"))}" target="_blank" rel="noopener">Consultar pronóstico del SMN para Rafaela</a></li>' for f in weather.get("pronostico_rafaela", []))
    source_rows = "".join(f'<tr><td>{esc(s.get("fuente"))}</td><td>{esc(s.get("estado"))}</td><td>{esc(s.get("resultados", "—"))}</td></tr>' for s in statuses)
    social_rows = "".join(f'<tr><td><a href="{esc(s.get("url"))}" target="_blank" rel="noopener">{esc(s.get("fuente"))}</a></td><td>{esc(s.get("estado"))}</td></tr>' for s in statuses if s.get("social"))

    return f'''<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Radar INTA Lechero – {day_label}</title>
<style>
:root{{--ink:#1f2937;--muted:#64748b;--line:#e2e8f0;--paper:#f8fafc;--green:#1f6b4f;--gold:#b7791f;}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 Arial,Helvetica,sans-serif}}
header{{background:#174b3a;color:white;padding:34px max(22px,calc((100% - 1100px)/2)) 28px}}
header h1{{margin:0;font-size:30px}}header p{{margin:6px 0;color:#d7e9df}}main{{max-width:1100px;margin:24px auto;padding:0 18px}}
.metrics{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:24px}}
.metric,.section,.weather,.sources{{background:white;border:1px solid var(--line);border-radius:12px;padding:18px}}
.metric strong{{display:block;font-size:27px;color:var(--green)}}.metric span{{font-size:13px;color:var(--muted)}}
h2{{font-size:21px;margin:0 0 14px}}h2 span{{font-size:13px;color:var(--muted);font-weight:normal}}
.section{{margin:18px 0}}.item{{padding:17px 0;border-top:1px solid var(--line)}}.item:first-of-type{{border-top:0}}
.item h3{{font-size:19px;line-height:1.3;margin:8px 0}}a{{color:#135f48;text-decoration:none}}a:hover{{text-decoration:underline}}
.item p{{margin:7px 0}}.meta{{display:flex;gap:16px;flex-wrap:wrap;color:var(--muted);font-size:12px}}
.tags{{color:#64748b;font-size:12px}}.event-date{{color:#854d0e}}.copy{{background:#fffbeb;border:1px solid #f4d58d;border-radius:8px;padding:13px;margin-top:13px}}
.copy h4{{margin:0 0 8px;color:#854d0e}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.5 Arial,sans-serif;margin:0}}
.empty{{color:var(--muted);font-size:14px}}.weather,.sources{{margin:18px 0}}.weather-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}}
.weather-card{{border:1px solid var(--line);border-radius:8px;padding:14px}}table{{width:100%;border-collapse:collapse;font-size:13px}}td,th{{padding:9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}
footer{{text-align:center;padding:28px;color:var(--muted);font-size:12px}}@media(max-width:620px){{.metrics{{grid-template-columns:repeat(2,1fr)}}header h1{{font-size:24px}}}}
</style></head><body>
<header><h1>Radar INTA Lechero</h1><p>Noticias, eventos, normativa y contexto agroclimático del sector lácteo</p>
<p>Informe del {day_label} · Ventana: {window_start.strftime('%d/%m/%Y %H:%M')} a {now.strftime('%d/%m/%Y %H:%M')} ({TZ_NAME})</p></header>
<main>
<div class="metrics"><div class="metric"><strong>{counts['total']}</strong><span>Publicaciones relevantes</span></div><div class="metric"><strong>{counts['noticias']}</strong><span>Noticias</span></div><div class="metric"><strong>{counts['eventos']}</strong><span>Eventos</span></div><div class="metric"><strong>{counts['normativa']}</strong><span>Normas detectadas</span></div></div>
<section class="weather"><h2>Tiempo y clima · Rafaela y Santa Fe</h2><p>Consulta: {esc(weather.get('consultado',''))}. Información de observación y pronóstico del SMN; no integra el filtro de publicaciones de 24 horas.</p><div class="weather-grid">{''.join(weather_parts)}</div><h3>Pronóstico</h3><ul>{forecast_html or '<li>Sin dato específico de Rafaela en la respuesta del servicio.</li>'}</ul><h3>Alertas vigentes para Santa Fe</h3><ul>{alert_html or '<li>No se detectaron alertas para Santa Fe en la respuesta consultada.</li>'}</ul></section>
{''.join(cards)}
<section class="sources"><h2>Estado de las fuentes consultadas</h2><p>Una fuente sin resultados no significa que no haya publicado: puede no exponer RSS, bloquear solicitudes automatizadas o requerir JavaScript.</p><table><thead><tr><th>Fuente</th><th>Estado</th><th>Resultados</th></tr></thead><tbody>{source_rows}</tbody></table>
<h3>Redes sociales incluidas en el monitoreo</h3><p>Instagram y X pueden limitar el acceso automatizado. Este informe solo muestra metadatos públicos que la página haya entregado; no inicia sesión ni afirma haber leído publicaciones que no fueron accesibles.</p><table><thead><tr><th>Perfil</th><th>Estado de acceso</th></tr></thead><tbody>{social_rows or '<tr><td colspan="2">No hubo perfiles accesibles en esta ejecución.</td></tr>'}</tbody></table></section>
</main><footer>Radar INTA Lechero · Recolección automática sin IA · Las fuentes originales prevalecen sobre el resumen. Verificar vigencia y alcance de toda normativa en el texto oficial.</footer>
</body></html>'''


def write_xls(path: Path, items: list[Item], weather: dict[str, Any], statuses: list[dict[str, Any]], now: datetime, window_start: datetime) -> None:
    book = xlwt.Workbook(encoding="utf-8")
    header_style = xlwt.easyxf("font: bold on, color white; pattern: pattern solid, fore_colour dark_green; align: wrap on, vert centre")
    body_style = xlwt.easyxf("align: wrap on, vert top")
    date_style = xlwt.easyxf("align: vert top", num_format_str="DD/MM/YYYY HH:MM")
    widths = [4200, 5000, 10500, 4200, 3300, 5000, 10000, 5000, 11000, 15000]

    sheet = book.add_sheet("Noticias y eventos")
    headers = ["Tipo", "Fuente", "Titular", "Fecha de publicación", "Fecha del evento", "Etiquetas", "Enlace", "Relevancia", "Resumen", "Copy sugerido – normativa"]
    for col, label in enumerate(headers):
        sheet.write(0, col, label, header_style)
        sheet.col(col).width = widths[col]
    sheet.row(0).height = 540
    for row_idx, item in enumerate(items, start=1):
        values = [
            item.section,
            item.source,
            item.title,
            item.published_at.replace(tzinfo=None),
            item.event_date,
            "; ".join(item.tags or []),
            item.url,
            item.relevance,
            item.summary,
            item.legal_copy,
        ]
        for col, value in enumerate(values):
            style = date_style if col == 3 else body_style
            sheet.write(row_idx, col, value if value is not None else "", style)
        sheet.row(row_idx).height = 720
    sheet.set_panes_frozen(True)
    sheet.set_horz_split_pos(1)
    sheet.set_remove_splits(True)
    sheet.autofilter(0, 0, max(1, len(items)), len(headers) - 1)

    weather_sheet = book.add_sheet("Clima SMN")
    weather_headers = ["Tipo de dato", "Localidad / área", "Dato", "Actualización / consulta", "Fuente"]
    for col, label in enumerate(weather_headers):
        weather_sheet.write(0, col, label, header_style)
        weather_sheet.col(col).width = [5000, 6000, 12000, 6500, 11000][col]
    wr = 1
    for row in weather.get("observaciones_rafaela", []):
        vals = ["Observación", "Rafaela, Santa Fe", json.dumps(row, ensure_ascii=False), row.get("actualizado", ""), row.get("url", "")]
        for c, val in enumerate(vals): weather_sheet.write(wr, c, val, body_style)
        wr += 1
    for row in weather.get("pronostico_rafaela", []):
        vals = ["Pronóstico", "Rafaela, Santa Fe", json.dumps(row.get("dato", {}), ensure_ascii=False), weather.get("consultado", ""), row.get("url", "")]
        for c, val in enumerate(vals): weather_sheet.write(wr, c, val, body_style)
        wr += 1
    for row in weather.get("alertas_santa_fe", []):
        vals = ["Alerta", "Santa Fe", row.get("texto", ""), weather.get("consultado", ""), row.get("url", "")]
        for c, val in enumerate(vals): weather_sheet.write(wr, c, val, body_style)
        wr += 1
    if wr == 1:
        weather_sheet.write(1, 0, "Sin datos meteorológicos disponibles en esta ejecución", body_style)

    status_sheet = book.add_sheet("Fuentes")
    for col, label in enumerate(["Fuente", "URL", "Estado", "Resultados"]):
        status_sheet.write(0, col, label, header_style)
    for row_idx, s in enumerate(statuses, start=1):
        vals = [s.get("fuente", ""), s.get("url", ""), s.get("estado", ""), s.get("resultados", "")]
        for col, val in enumerate(vals): status_sheet.write(row_idx, col, val, body_style)
    for col, width in enumerate([8000, 14000, 14000, 3500]): status_sheet.col(col).width = width
    status_sheet.set_panes_frozen(True)
    status_sheet.set_horz_split_pos(1)
    status_sheet.set_remove_splits(True)

    meta = book.add_sheet("Sobre el informe")
    metadata = [
        ("Informe", f"Radar INTA Lechero – {now.strftime('%d/%m/%Y')}"),
        ("Zona horaria", TZ_NAME),
        ("Ventana de publicaciones", f"{window_start.isoformat()} a {now.isoformat()}"),
        ("Criterio", "Publicaciones con fecha identificable dentro de las últimas 24 horas. Los datos meteorológicos son una consulta de contexto."),
        ("IA", "No se utiliza IA. Clasificación por palabras clave y resúmenes extractivos/reglas determinísticas."),
        ("Normativa", "El copy sugerido es orientativo. Verificar el texto oficial, alcance, vigencia y sujetos alcanzados."),
        ("Redes sociales", "Instagram y X pueden limitar el acceso automatizado. No se simula lectura de contenido inaccesible."),
    ]
    meta.col(0).width = 7500
    meta.col(1).width = 22000
    for r, (label, value) in enumerate(metadata):
        meta.write(r, 0, label, header_style if r == 0 else body_style)
        meta.write(r, 1, value, body_style)
    book.save(str(path))

# ---------------------------------------------------------------------------
# Ejecución
# ---------------------------------------------------------------------------
def run() -> tuple[Path, Path, int]:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    now = datetime.now(TZ)
    window_start = now - timedelta(hours=24)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = now.strftime("%d%m%y")
    html_path = OUTPUT_DIR / f"noticiasinta_{suffix}.html"
    xls_path = OUTPUT_DIR / f"noticiasinta_{suffix}.xls"

    LOG.info("Inicio de Radar INTA Lechero: %s (%s)", now.isoformat(), TZ_NAME)
    LOG.info("Ventana: %s – %s", window_start.isoformat(), now.isoformat())

    all_items: list[Item] = []
    statuses: list[dict[str, Any]] = []

    # Fuentes principales, en paralelo con concurrencia acotada.
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {executor.submit(scan_web_source, source, now): source for source in WEB_SOURCES}
        for future in concurrent.futures.as_completed(future_map):
            source = future_map[future]
            try:
                items, status = future.result()
                all_items.extend(items)
                statuses.append(status)
                LOG.info("%s: %s resultados", source["name"], len(items))
            except Exception as exc:
                statuses.append({"fuente": source["name"], "url": source["url"], "estado": f"error de procesamiento: {exc}"})
                LOG.exception("Error en fuente %s", source["name"])

    # Google News RSS añade descubrimiento transversal, independiente de la lista de sitios.
    try:
        google_items, google_status = scan_google_news(now)
        all_items.extend(google_items)
        statuses.append(google_status)
        LOG.info("Google News: %s resultados", len(google_items))
    except Exception as exc:
        statuses.append({"fuente": "Google News RSS", "url": "https://news.google.com/", "estado": f"error: {exc}"})

    # Legislación de la Primera Sección del Boletín Oficial.
    try:
        legal_items, legal_status = scrape_bulletin(now)
        all_items.extend(legal_items)
        statuses.append(legal_status)
        LOG.info("Boletín Oficial: %s normas relevantes", len(legal_items))
    except Exception as exc:
        statuses.append({"fuente": "Boletín Oficial – Primera Sección", "url": BOLETIN_URL, "estado": f"error: {exc}"})
        LOG.exception("Error leyendo Boletín Oficial")

    # Consulta de perfiles públicos: no se autentica ni se fuerza el acceso a contenido restringido.
    social_statuses: list[dict[str, Any]] = []
    if os.getenv("RADAR_SCAN_SOCIAL", "1").lower() not in ("0", "false", "no"):
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(scan_social_profile, url, now): url for url in SOCIAL_PROFILES}
            for future in concurrent.futures.as_completed(futures):
                try:
                    social_items, row = future.result()
                    all_items.extend(social_items)
                    row["social"] = True
                    social_statuses.append(row)
                except Exception as exc:
                    social_statuses.append({"fuente": futures[future], "url": futures[future], "estado": f"error: {exc}", "social": True})
        statuses.extend(social_statuses)

    # Clima/alertas como apartado de contexto (no se presenta como noticia de 24 h).
    weather = get_weather(now)

    items = deduplicate([item for item in all_items if is_within_window(item.published_at, now)])
    # Orden explícito: normas, eventos y después noticias; dentro de cada bloque, más recientes primero.
    priority = {"Normativa": 0, "Evento": 1, "Noticia": 2}
    items.sort(key=lambda x: (priority.get(x.section, 9), -x.relevance, -x.published_at.timestamp()))

    html_content = render_html(items, weather, statuses, now, window_start)
    html_path.write_text(html_content, encoding="utf-8")
    write_xls(xls_path, items, weather, statuses, now, window_start)

    # El nombre de archivo es diario. Si se re-ejecuta en la misma fecha, se
    # actualiza el informe de ese día; nunca se modifican informes de otras fechas.
    LOG.info("Informe HTML: %s", html_path)
    LOG.info("Informe XLS: %s", xls_path)
    LOG.info("Total: %s publicaciones (%s normas, %s eventos)", len(items), sum(i.section == "Normativa" for i in items), sum(i.section == "Evento" for i in items))
    return html_path, xls_path, len(items)


if __name__ == "__main__":
    try:
        html_file, xls_file, total = run()
        print(f"OK: {total} publicaciones")
        print(f"HTML: {html_file}")
        print(f"XLS: {xls_file}")
    except Exception as exc:
        LOG.exception("La ejecución falló: %s", exc)
        sys.exit(1)
