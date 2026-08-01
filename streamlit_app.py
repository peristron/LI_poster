"""li_poster 2.1.0: a reviewed, multi-collection LinkedIn scheduler."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import random
import re
import secrets
import threading
import time as clock
import unicodedata
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlencode, urlparse
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import streamlit as st
from cryptography.fernet import Fernet, InvalidToken


st.set_page_config(
    page_title="li_poster",
    page_icon="🏛️",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Application constants
# ---------------------------------------------------------------------------

APP_NAME = "li_poster"
APP_VERSION = "2.1.0"
GITHUB_API = "https://api.github.com"
LINKEDIN_AUTHORIZE_URL = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
LINKEDIN_POST_URL = "https://api.linkedin.com/v2/ugcPosts"
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
STATE_BRANCH = "runtime-state"
STATE_PATH = "runtime/state.json"
MAX_EVENTS = 500
MAX_HISTORY = 500
MAX_AI_CANDIDATES = 100
MAX_GENERATION_ATTEMPTS = 3
MAX_METADATA_BACKFILL = 10
WORKER_INTERVAL_SECONDS = 45
WORKER_STALE_AFTER_SECONDS = 120
STATE_VERIFY_ATTEMPTS = 5
SCHEMA_VERSION = 7
AUTOMATION_FOOTER = "(Automated post; reviewed before scheduling.)"
COLLECTION_LATIN = "latin_sayings"
COLLECTION_PHYSICS = "physics_facts"
COLLECTION_HISTORY = "history_facts"
COLLECTION_LABELS = {
    COLLECTION_LATIN: "Latin sayings",
    COLLECTION_PHYSICS: "Physics facts",
    COLLECTION_HISTORY: "History facts",
}
COLLECTION_KEYS = list(COLLECTION_LABELS)
SOURCE_MODE_REQUIRED = "One required source language"
SOURCE_MODE_BALANCED = "Balanced coverage across preferred languages"
SOURCE_MODE_PREFERENCES = "Preferred languages only"
SOURCE_MODES = [
    SOURCE_MODE_REQUIRED,
    SOURCE_MODE_BALANCED,
    SOURCE_MODE_PREFERENCES,
]
WEEKDAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


SAYING_FIELDS = [
    "approved",
    "collection",
    "lead",
    "body",
    "latin",
    "translation",
    "attribution",
    "source_title",
    "source_url",
    "source_type",
    "tags",
    "verified_at",
    "latin_kind",
    "primary_theme",
    "source_language",
    "source_period",
    "source_confidence",
    "source_text",
    "origin",
    "verification_status",
    "note",
]


def seed_saying(
    saying_id: str,
    latin: str,
    translation: str,
    attribution: str,
    latin_kind: str = "original Latin",
    source_language: str = "Latin",
    source_text: str = "",
    note: str = "",
    primary_theme: str = "",
    source_period: str = "antiquity",
    source_confidence: str = "curated; verify edition",
) -> dict[str, Any]:
    return {
        "id": saying_id,
        "approved": False,
        "collection": COLLECTION_LATIN,
        "lead": "",
        "body": "",
        "latin": latin,
        "translation": translation,
        "attribution": attribution,
        "source_title": attribution,
        "source_url": "",
        "source_type": "primary text",
        "tags": primary_theme,
        "verified_at": "",
        "latin_kind": latin_kind,
        "primary_theme": primary_theme,
        "source_language": source_language,
        "source_period": source_period,
        "source_confidence": source_confidence,
        "source_text": source_text,
        "origin": "bundled curated library",
        "verification_status": "review source before approval",
        "note": note,
    }


def seed_fact(
    item_id: str,
    collection: str,
    lead: str,
    body: str,
    attribution: str,
    source_title: str,
    source_url: str,
    primary_theme: str,
    source_period: str,
) -> dict[str, Any]:
    """Build an unapproved, source-led starter fact."""
    return {
        "id": item_id,
        "approved": False,
        "collection": collection,
        "lead": lead,
        "body": body,
        "latin": "",
        "translation": "",
        "attribution": attribution,
        "source_title": source_title,
        "source_url": source_url,
        "source_type": "authoritative reference",
        "tags": primary_theme,
        "verified_at": "",
        "latin_kind": "",
        "primary_theme": primary_theme,
        "source_language": "English",
        "source_period": source_period,
        "source_confidence": "starter record; verify source",
        "source_text": "",
        "origin": "bundled starter library",
        "verification_status": "review source before approval",
        "note": "Verify the wording and linked source before approval.",
    }


# The bundled library is deliberately secular. Every entry remains unapproved
# until the administrator reviews it. Excerpts are kept short for social posts.
SEED_SAYINGS: list[dict[str, Any]] = [
    seed_saying(
        "seneca-ep-1",
        "Dum differtur, vita transcurrit.",
        "While it is postponed, life passes by.",
        "Seneca, Epistulae Morales 1.2",
    ),
    seed_saying(
        "seneca-ep-1-3",
        "Omnia aliena sunt, tempus tantum nostrum est.",
        "Everything belongs to others; time alone is ours.",
        "Seneca, Epistulae Morales 1.3",
    ),
    seed_saying(
        "seneca-ep-6-5",
        "Longum iter est per praecepta, breve et efficax per exempla.",
        "The way through precepts is long; through examples it is short and effective.",
        "Seneca, Epistulae Morales 6.5",
    ),
    seed_saying(
        "seneca-ep-71-3",
        "Ignoranti quem portum petat nullus suus ventus est.",
        "No wind is favorable to one who does not know which harbour to seek.",
        "Seneca, Epistulae Morales 71.3",
    ),
    seed_saying(
        "seneca-ep-96-5",
        "Vivere, Lucili, militare est.",
        "To live, Lucilius, is to struggle.",
        "Seneca, Epistulae Morales 96.5",
    ),
    seed_saying(
        "seneca-ep-106-12",
        "Non vitae, sed scholae discimus.",
        "We learn not for life, but for school.",
        "Seneca, Epistulae Morales 106.12",
        note="The familiar modern reversal is not Seneca's original wording.",
    ),
    seed_saying(
        "seneca-hercules-437",
        "Non est ad astra mollis e terris via.",
        "There is no easy way from the earth to the stars.",
        "Seneca, Hercules Furens 437",
    ),
    seed_saying(
        "horace-odes-1-11",
        "Carpe diem, quam minimum credula postero.",
        "Seize the day, trusting as little as possible in tomorrow.",
        "Horace, Odes 1.11",
    ),
    seed_saying(
        "horace-odes-1-37",
        "Nunc est bibendum.",
        "Now is the time to drink.",
        "Horace, Odes 1.37.1",
    ),
    seed_saying(
        "horace-odes-3-30",
        "Exegi monumentum aere perennius.",
        "I have raised a monument more lasting than bronze.",
        "Horace, Odes 3.30.1",
    ),
    seed_saying(
        "horace-odes-4-7",
        "Pulvis et umbra sumus.",
        "We are dust and shadow.",
        "Horace, Odes 4.7.16",
    ),
    seed_saying(
        "horace-ep-1-2-40a",
        "Dimidium facti, qui coepit, habet.",
        "One who has begun has half the deed done.",
        "Horace, Epistles 1.2.40",
    ),
    seed_saying(
        "horace-ep-1-2-40b",
        "Sapere aude; incipe.",
        "Dare to be wise; begin.",
        "Horace, Epistles 1.2.40",
    ),
    seed_saying(
        "horace-ep-1-2-62",
        "Ira furor brevis est.",
        "Anger is a brief madness.",
        "Horace, Epistles 1.2.62",
    ),
    seed_saying(
        "horace-ep-1-11-27",
        "Caelum, non animum, mutant qui trans mare currunt.",
        "Those who cross the sea change their sky, not their state of mind.",
        "Horace, Epistles 1.11.27",
    ),
    seed_saying(
        "horace-satires-1-1-106",
        "Est modus in rebus.",
        "There is a proper measure in things.",
        "Horace, Satires 1.1.106",
    ),
    seed_saying(
        "horace-ars-25",
        "Brevis esse laboro, obscurus fio.",
        "When I strive to be brief, I become obscure.",
        "Horace, Ars Poetica 25",
    ),
    seed_saying(
        "horace-ars-343",
        "Omne tulit punctum qui miscuit utile dulci.",
        "One wins every vote who mixes the useful with the pleasant.",
        "Horace, Ars Poetica 343",
    ),
    seed_saying(
        "horace-ars-361",
        "Ut pictura poesis.",
        "As is painting, so is poetry.",
        "Horace, Ars Poetica 361",
    ),
    seed_saying(
        "terence-heauton-77",
        "Homo sum: humani nihil a me alienum puto.",
        "I am human; I consider nothing human alien to me.",
        "Terence, Heauton Timorumenos 77",
    ),
    seed_saying(
        "terence-andria-68",
        "Obsequium amicos, veritas odium parit.",
        "Compliance makes friends; truth produces hatred.",
        "Terence, Andria 68",
    ),
    seed_saying(
        "terence-phormio-203",
        "Fortis fortuna adiuvat.",
        "Fortune helps the brave.",
        "Terence, Phormio 203",
    ),
    seed_saying(
        "terence-phormio-454",
        "Quot homines, tot sententiae.",
        "So many people, so many opinions.",
        "Terence, Phormio 454",
    ),
    seed_saying(
        "terence-eunuchus-41",
        "Nullum est iam dictum quod non dictum sit prius.",
        "Nothing is now said that has not been said before.",
        "Terence, Eunuchus 41",
    ),
    seed_saying(
        "virgil-aeneid-1-203",
        "Forsan et haec olim meminisse iuvabit.",
        "Perhaps one day it will please us to remember even these things.",
        "Virgil, Aeneid 1.203",
    ),
    seed_saying(
        "virgil-aeneid-2-49",
        "Timeo Danaos et dona ferentes.",
        "I fear the Greeks even when they bring gifts.",
        "Virgil, Aeneid 2.49",
    ),
    seed_saying(
        "virgil-aeneid-2-65",
        "Ab uno disce omnes.",
        "From one, learn about them all.",
        "Virgil, Aeneid 2.65",
    ),
    seed_saying(
        "virgil-aeneid-2-354",
        "Una salus victis nullam sperare salutem.",
        "The one safety for the defeated is to hope for no safety.",
        "Virgil, Aeneid 2.354",
    ),
    seed_saying(
        "virgil-aeneid-5-231",
        "Possunt, quia posse videntur.",
        "They can because they believe they can.",
        "Virgil, Aeneid 5.231",
    ),
    seed_saying(
        "virgil-aeneid-6-126",
        "Facilis descensus Averno.",
        "The descent to Avernus is easy.",
        "Virgil, Aeneid 6.126",
    ),
    seed_saying(
        "virgil-aeneid-6-727",
        "Mens agitat molem.",
        "Mind moves matter.",
        "Virgil, Aeneid 6.727",
    ),
    seed_saying(
        "virgil-aeneid-10-284",
        "Audentis Fortuna iuvat.",
        "Fortune favors the daring.",
        "Virgil, Aeneid 10.284",
    ),
    seed_saying(
        "virgil-eclogues-2-65",
        "Trahit sua quemque voluptas.",
        "Each person is drawn by their own pleasure.",
        "Virgil, Eclogues 2.65",
    ),
    seed_saying(
        "virgil-georgics-1-145",
        "Labor omnia vicit improbus.",
        "Relentless work conquered all.",
        "Virgil, Georgics 1.145–146",
    ),
    seed_saying(
        "virgil-georgics-3-284",
        "Fugit irreparabile tempus.",
        "Irrecoverable time is fleeing.",
        "Virgil, Georgics 3.284",
    ),
    seed_saying(
        "ovid-remedia-91",
        "Principiis obsta; sero medicina paratur.",
        "Resist beginnings; a remedy is prepared too late.",
        "Ovid, Remedia Amoris 91",
    ),
    seed_saying(
        "ovid-met-4-428",
        "Fas est et ab hoste doceri.",
        "It is right to learn even from an enemy.",
        "Ovid, Metamorphoses 4.428",
    ),
    seed_saying(
        "ovid-met-7-20",
        "Video meliora proboque, deteriora sequor.",
        "I see and approve the better course, but follow the worse.",
        "Ovid, Metamorphoses 7.20–21",
    ),
    seed_saying(
        "ovid-met-15-234",
        "Tempus edax rerum.",
        "Time, the devourer of things.",
        "Ovid, Metamorphoses 15.234",
    ),
    seed_saying(
        "ovid-ex-ponto-4-10",
        "Gutta cavat lapidem.",
        "A drop hollows out a stone.",
        "Ovid, Epistulae ex Ponto 4.10.5",
    ),
    seed_saying(
        "cicero-officiis-1-22",
        "Non nobis solum nati sumus.",
        "We are not born for ourselves alone.",
        "Cicero, De Officiis 1.22",
    ),
    seed_saying(
        "cicero-officiis-1-33",
        "Summum ius summa iniuria.",
        "The strictest law can become the greatest injustice.",
        "Cicero, De Officiis 1.33",
    ),
    seed_saying(
        "cicero-pro-milone-11",
        "Silent enim leges inter arma.",
        "For laws fall silent amid arms.",
        "Cicero, Pro Milone 11",
    ),
    seed_saying(
        "cicero-pro-cluentio-146",
        "Legum servi sumus ut liberi esse possimus.",
        "We are servants of the laws so that we may be free.",
        "Cicero, Pro Cluentio 146",
    ),
    seed_saying(
        "cicero-de-legibus-3-8",
        "Salus populi suprema lex esto.",
        "Let the welfare of the people be the highest law.",
        "Cicero, De Legibus 3.8",
    ),
    seed_saying(
        "cicero-in-catilinam-1-2",
        "O tempora, o mores!",
        "Oh, the times! Oh, the customs!",
        "Cicero, In Catilinam 1.2",
    ),
    seed_saying(
        "cicero-orator-120",
        "Nescire quid ante quam natus sis acciderit, id est semper esse puerum.",
        "Not to know what happened before you were born is always to remain a child.",
        "Cicero, Orator 120",
    ),
    seed_saying(
        "ennius-amicus-certus",
        "Amicus certus in re incerta cernitur.",
        "A sure friend is recognized in uncertain circumstances.",
        "Ennius, fragment quoted by Cicero, De Amicitia 64",
    ),
    seed_saying(
        "sallust-jugurtha-10-6",
        "Concordia parvae res crescunt, discordia maximae dilabuntur.",
        "Through harmony small things grow; through discord the greatest collapse.",
        "Sallust, Bellum Iugurthinum 10.6",
    ),
    seed_saying(
        "tacitus-annals-1-1",
        "Sine ira et studio.",
        "Without anger or partiality.",
        "Tacitus, Annales 1.1",
    ),
    seed_saying(
        "tacitus-annals-3-27",
        "Corruptissima re publica plurimae leges.",
        "The more corrupt the state, the more numerous the laws.",
        "Tacitus, Annales 3.27",
    ),
    seed_saying(
        "tacitus-agricola-30a",
        "Omne ignotum pro magnifico est.",
        "Everything unknown is taken as magnificent.",
        "Tacitus, Agricola 30",
    ),
    seed_saying(
        "tacitus-agricola-30b",
        "Ubi solitudinem faciunt, pacem appellant.",
        "Where they make a desert, they call it peace.",
        "Tacitus, Agricola 30",
    ),
    seed_saying(
        "juvenal-satire-6-347",
        "Quis custodiet ipsos custodes?",
        "Who will guard the guards themselves?",
        "Juvenal, Satires 6.347–348",
    ),
    seed_saying(
        "juvenal-satire-10-81",
        "Panem et circenses.",
        "Bread and circuses.",
        "Juvenal, Satires 10.81",
    ),
    seed_saying(
        "juvenal-satire-10-356",
        "Mens sana in corpore sano.",
        "A healthy mind in a healthy body.",
        "Juvenal, Satires 10.356",
    ),
    seed_saying(
        "martial-epigrams-6-70",
        "Non est vivere, sed valere vita est.",
        "Life is not merely being alive, but being well.",
        "Martial, Epigrams 6.70.15",
    ),
    seed_saying(
        "catullus-85",
        "Odi et amo.",
        "I hate and I love.",
        "Catullus, Carmina 85",
    ),
    seed_saying(
        "pliny-nh-35-84",
        "Nulla dies sine linea.",
        "No day without a line.",
        "Traditional Latin rendering of Pliny, Naturalis Historia 35.84",
        "traditional Latin rendering",
        "Greek",
        note="Pliny recounts the saying in relation to the painter Apelles.",
    ),
    seed_saying(
        "suetonius-caesar-32",
        "Iacta alea est.",
        "The die has been cast.",
        "Suetonius, Divus Iulius 32",
        note="Suetonius reports the phrase; compare Plutarch's Greek account.",
    ),
    seed_saying(
        "suetonius-caesar-37",
        "Veni, vidi, vici.",
        "I came, I saw, I conquered.",
        "Suetonius, Divus Iulius 37",
    ),
    seed_saying(
        "epictetus-ench-1",
        "Alia in potestate nostra sunt, alia non sunt.",
        "Some things are within our power; others are not.",
        "Epictetus, Enchiridion 1",
        "modern Latin rendering from Greek",
        "Ancient Greek",
        note="Compare the Ancient Greek original before approval.",
    ),
    seed_saying(
        "marcus-aurelius-4-3",
        "Intra te ipsum recede.",
        "Withdraw into yourself.",
        "Marcus Aurelius, Meditations 4.3",
        "modern Latin rendering from Greek",
        "Ancient Greek",
        note="Compare the Ancient Greek original before approval.",
    ),
    seed_saying(
        "confucius-analects-15-24",
        "Quod tibi fieri non vis, alteri ne feceris.",
        "What you do not wish for yourself, do not do to another.",
        "Confucius, Analects 15.24",
        "modern Latin rendering from Classical Chinese",
        "Classical Chinese",
        note="Compare the Classical Chinese original before approval.",
    ),
    seed_saying(
        "laozi-daodejing-33",
        "Qui alios novit sapiens est; qui se ipsum novit illuminatus est.",
        "One who knows others is wise; one who knows oneself is enlightened.",
        "Laozi, Daodejing 33",
        "modern Latin rendering from Classical Chinese",
        "Classical Chinese",
        note="Compare the Classical Chinese original before approval.",
    ),
]

LEGACY_COMMON_FACTS: list[dict[str, Any]] = [
    seed_fact(
        "physics-speed-of-light",
        COLLECTION_PHYSICS,
        "The speed of light in vacuum is exactly 299,792,458 metres per second.",
        "The metre is defined by fixing this value of the speed of light.",
        "BIPM, The International System of Units (SI Brochure)",
        "The International System of Units (SI Brochure)",
        "https://www.bipm.org/en/publications/si-brochure",
        "measurement",
        "modern physics",
    ),
    seed_fact(
        "physics-gravitational-waves",
        COLLECTION_PHYSICS,
        "Gravitational waves were directly detected for the first time in 2015.",
        "LIGO observed waves from two merging black holes; the result was announced in 2016.",
        "LIGO Laboratory, GW150914",
        "Gravitational Waves Detected 100 Years After Einstein's Prediction",
        "https://www.ligo.caltech.edu/news/ligo20160211",
        "gravitation",
        "2015 CE",
    ),
    seed_fact(
        "physics-atom-mostly-space",
        COLLECTION_PHYSICS,
        "An atom's nucleus occupies only a tiny fraction of the atom's volume.",
        "Most of the atom's spatial extent is the region described by its electron cloud.",
        "U.S. Department of Energy, Office of Science",
        "DOE Explains...Nuclei",
        "https://www.energy.gov/science/doe-explainsnuclei",
        "atomic physics",
        "modern physics",
    ),
    seed_fact(
        "physics-electromagnetic-spectrum",
        COLLECTION_PHYSICS,
        "Radio waves, visible light, and X-rays are all electromagnetic radiation.",
        "They differ in wavelength, frequency, and energy, but all belong to the same spectrum.",
        "NASA Science, Electromagnetic Spectrum",
        "The Electromagnetic Spectrum",
        "https://science.nasa.gov/ems/",
        "electromagnetism",
        "modern physics",
    ),
    seed_fact(
        "physics-standard-model",
        COLLECTION_PHYSICS,
        "The Standard Model describes three fundamental interactions, but not gravity.",
        "It organizes known elementary particles and the electromagnetic, weak, and strong interactions.",
        "CERN, The Standard Model",
        "The Standard Model",
        "https://home.cern/science/physics/standard-model",
        "particle physics",
        "modern physics",
    ),
    seed_fact(
        "physics-absolute-zero",
        COLLECTION_PHYSICS,
        "Absolute zero is 0 kelvin, equal to −273.15 degrees Celsius.",
        "It is the zero point of the thermodynamic temperature scale.",
        "BIPM, SI Brochure",
        "The International System of Units (SI Brochure)",
        "https://www.bipm.org/en/publications/si-brochure",
        "thermodynamics",
        "modern physics",
    ),
    seed_fact(
        "physics-mass-energy",
        COLLECTION_PHYSICS,
        "Mass and energy are related by Einstein's equation E = mc².",
        "The relation shows that a body's mass corresponds to an amount of energy even when the body is at rest.",
        "NIST, CODATA and fundamental constants",
        "Fundamental Physical Constants",
        "https://physics.nist.gov/cuu/Constants/",
        "relativity",
        "20th century CE",
    ),
    seed_fact(
        "physics-neutrinos",
        COLLECTION_PHYSICS,
        "Neutrinos interact so weakly that enormous numbers pass through matter unnoticed.",
        "They are elementary particles with very small masses and no electric charge.",
        "Fermilab, All About Neutrinos",
        "All About Neutrinos",
        "https://neutrinos.fnal.gov/",
        "particle physics",
        "modern physics",
    ),
    seed_fact(
        "history-rosetta-stone",
        COLLECTION_HISTORY,
        "The Rosetta Stone carries one decree in three writing systems.",
        "Its Greek, Demotic, and hieroglyphic texts became central to deciphering Egyptian hieroglyphs.",
        "The British Museum, The Rosetta Stone",
        "The Rosetta Stone",
        "https://www.britishmuseum.org/collection/object/Y_EA24",
        "writing and language",
        "196 BCE",
    ),
    seed_fact(
        "history-magna-carta",
        COLLECTION_HISTORY,
        "Magna Carta was first issued in June 1215.",
        "Although many clauses addressed medieval disputes, later generations treated it as an important symbol of lawful government.",
        "UK Parliament, Magna Carta",
        "Magna Carta",
        "https://www.parliament.uk/magnacarta/",
        "law",
        "1215 CE",
    ),
    seed_fact(
        "history-apollo-11",
        COLLECTION_HISTORY,
        "Apollo 11 landed humans on the Moon in July 1969.",
        "Neil Armstrong and Buzz Aldrin walked on the lunar surface while Michael Collins remained in lunar orbit.",
        "NASA, Apollo 11 Mission Overview",
        "Apollo 11 Mission Overview",
        "https://www.nasa.gov/mission/apollo-11/",
        "spaceflight",
        "1969 CE",
    ),
    seed_fact(
        "history-transcontinental-railroad",
        COLLECTION_HISTORY,
        "The first U.S. transcontinental railroad was joined at Promontory Summit in 1869.",
        "The ceremonial meeting connected the Union Pacific and Central Pacific railroads.",
        "U.S. National Park Service, Golden Spike",
        "Golden Spike National Historical Park",
        "https://www.nps.gov/gosp/learn/historyculture/index.htm",
        "transport",
        "1869 CE",
    ),
    seed_fact(
        "history-gutenberg-bible",
        COLLECTION_HISTORY,
        "The Gutenberg Bible was printed in Mainz in the mid-fifteenth century.",
        "It is a landmark of European printing with movable metal type.",
        "Library of Congress, Gutenberg Bible",
        "The Gutenberg Bible",
        "https://www.loc.gov/exhibits/bibles/the-gutenberg-bible.html",
        "printing",
        "15th century CE",
    ),
    seed_fact(
        "history-decimal-classification",
        COLLECTION_HISTORY,
        "The Dewey Decimal Classification was first published in 1876.",
        "Its numbered hierarchy became a widely used system for organizing library collections.",
        "Library of Congress, Dewey Decimal Classification",
        "Dewey Decimal Classification",
        "https://www.loc.gov/aba/publications/FreeDDC/freedoc.html",
        "libraries",
        "1876 CE",
    ),
    seed_fact(
        "history-code-talkers",
        COLLECTION_HISTORY,
        "Navajo Code Talkers used their language to create a military communications code during World War II.",
        "The code was used by the U.S. Marine Corps in the Pacific and was never broken in combat.",
        "U.S. National Archives, Navajo Code Talkers",
        "Navajo Code Talkers and the Unbreakable Code",
        "https://www.archives.gov/education/lessons/code-talkers",
        "communications",
        "World War II",
    ),
    seed_fact(
        "history-antarctic-treaty",
        COLLECTION_HISTORY,
        "The Antarctic Treaty was signed in 1959 and entered into force in 1961.",
        "It reserves Antarctica for peaceful purposes and supports freedom of scientific investigation.",
        "Antarctic Treaty Secretariat",
        "The Antarctic Treaty",
        "https://www.ats.aq/e/antarctictreaty.html",
        "international cooperation",
        "1959–1961 CE",
    ),
]

# The current starter facts deliberately favor less familiar, well-sourced
# details. They remain unapproved until an administrator follows the linked
# institutional source and reviews the wording.
SEED_FACTS: list[dict[str, Any]] = [
    seed_fact(
        "physics-gps-relativistic-clock-rate",
        COLLECTION_PHYSICS,
        "A GPS satellite clock would run about 38 microseconds per day faster than a clock on Earth without correction.",
        "Special relativity slows it by about 7 microseconds per day, while weaker gravity speeds it by about 45.",
        "NIST, Putting Einstein to the Test",
        "Putting Einstein to the Test",
        "https://www.nist.gov/atomic-clocks/a-powerful-tool-for-science/putting-einstein-test",
        "relativistic timekeeping",
        "modern physics",
    ),
    seed_fact(
        "physics-ligo-proton-scale-displacement",
        COLLECTION_PHYSICS,
        "LIGO's first gravitational-wave signal changed the length of a four-kilometre detector arm by roughly one-thousandth of a proton's diameter.",
        "Laser interferometry measured that minute distortion as two black holes merged more than a billion light-years away.",
        "LIGO Laboratory, The First Detection of Gravitational Waves",
        "The First Detection of Gravitational Waves",
        "https://www.ligo.caltech.edu/video/ligo20160211v7",
        "precision measurement",
        "2015 CE",
    ),
    seed_fact(
        "physics-caesium-second",
        COLLECTION_PHYSICS,
        "One SI second corresponds to exactly 9,192,631,770 periods of radiation from a specified caesium-133 transition.",
        "The definition fixes a microscopic frequency rather than relying on Earth's variable rotation.",
        "BIPM, SI base unit: second",
        "SI base unit: second",
        "https://www.bipm.org/en/si-base-units/second",
        "atomic time",
        "modern metrology",
    ),
    seed_fact(
        "physics-kilogram-planck-constant",
        COLLECTION_PHYSICS,
        "The kilogram is defined by assigning the Planck constant an exact numerical value.",
        "Since 2019, the SI definition has not depended on the mass of a particular metal cylinder.",
        "BIPM, SI base unit: kilogram",
        "SI base unit: kilogram",
        "https://www.bipm.org/en/si-base-units/kilogram",
        "quantum metrology",
        "2019 CE onward",
    ),
    seed_fact(
        "physics-moon-clock-rate",
        COLLECTION_PHYSICS,
        "A clock on the Moon's surface runs about 56 microseconds per Earth day faster than one on Earth.",
        "The difference matters when designing a shared lunar time standard for navigation and communications.",
        "NIST, What Time Is It on the Moon?",
        "What Time Is It on the Moon?",
        "https://www.nist.gov/news-events/news/2024/08/what-time-it-moon",
        "lunar timekeeping",
        "modern physics",
    ),
    seed_fact(
        "physics-variable-length-of-day",
        COLLECTION_PHYSICS,
        "Earth's rotational day is not perfectly constant.",
        "Atmospheric winds, ocean currents, motion in Earth's interior, and the Moon all exchange angular momentum with the planet.",
        "NIST, What Determines the Length of the Day?",
        "What Determines the Length of the Day?",
        "https://www.nist.gov/physics/explainers/what-determines-length-day",
        "Earth rotation",
        "modern geophysics",
    ),
    seed_fact(
        "physics-ligo-quantum-mirror-motion",
        COLLECTION_PHYSICS,
        "Quantum fluctuations can move each of LIGO's 40-kilogram mirrors by about 10^-20 metre.",
        "The detector uses squeezed quantum states of light to reduce this measurement noise.",
        "LIGO Laboratory, Quantum Squeezing",
        "Quantum Squeezing Lets Gravity-Wave Detectors See More",
        "https://www.ligo.caltech.edu/news/ligo20200701",
        "quantum measurement",
        "modern physics",
    ),
    seed_fact(
        "physics-seven-defining-constants",
        COLLECTION_PHYSICS,
        "The modern SI is built from seven defining constants whose numerical values are exact.",
        "Those constants include the speed of light, Planck constant, elementary charge, and caesium hyperfine frequency.",
        "BIPM, SI defining constants",
        "SI defining constants",
        "https://www.bipm.org/en/measurement-units/si-defining-constants",
        "measurement standards",
        "2019 CE onward",
    ),
    seed_fact(
        "history-ea-nasir-copper-complaint",
        COLLECTION_HISTORY,
        "A clay tablet from about 1750 BCE records Nanni's complaint to the merchant Ea-nasir about poor-quality copper.",
        "The letter also objects to delays and the treatment of Nanni's messenger.",
        "The British Museum, tablet 1953,0411.71",
        "Clay tablet: letter from Nanni to Ea-nasir",
        "https://www.britishmuseum.org/collection/object/W_1953-0411-71",
        "commerce and writing",
        "Old Babylonian, about 1750 BCE",
    ),
    seed_fact(
        "history-pony-express-eighteen-months",
        COLLECTION_HISTORY,
        "The Pony Express operated for only eighteen months, from April 1860 to October 1861.",
        "Its relay system could carry mail more than 1,800 miles in about ten days.",
        "U.S. National Park Service, Pony Express National Historic Trail",
        "Pony Express National Historic Trail",
        "https://www.nps.gov/places/pony-express-national-historic-trail.htm",
        "communications",
        "1860–1861 CE",
    ),
    seed_fact(
        "history-phonautogram-recovered-sound",
        COLLECTION_HISTORY,
        "A voice recorded on paper in 1860 became recoverable audio only in 2008.",
        "Édouard-Léon Scott de Martinville's phonautograph traced sound waves but was not designed to play them back.",
        "Library of Congress, Phonautograms",
        "From the Recording Registry: Phonautograms (c. 1853–61)",
        "https://blogs.loc.gov/now-see-hear/2021/08/from-the-recording-registry-phonautograms-c-1853-61/",
        "recorded sound",
        "1850s–1860 CE; recovered 2008",
    ),
    seed_fact(
        "history-zimmermann-telegram-interception",
        COLLECTION_HISTORY,
        "British cryptographers deciphered the Zimmermann Telegram before the United States entered the First World War.",
        "The message proposed a German-Mexican alliance and offered Mexico territory in Texas, New Mexico, and Arizona.",
        "U.S. National Archives, Zimmermann Telegram",
        "Zimmermann Telegram (1917)",
        "https://www.archives.gov/milestone-documents/zimmermann-telegram",
        "cryptography and diplomacy",
        "1917 CE",
    ),
    seed_fact(
        "history-pneumatic-tube-mail",
        COLLECTION_HISTORY,
        "By 1915, six U.S. cities had more than fifty-six miles of pneumatic tubes carrying mail beneath their streets.",
        "Compressed air propelled sealed canisters between main and branch post offices.",
        "Smithsonian National Postal Museum, Pneumatic",
        "Pneumatic",
        "https://postalmuseum.si.edu/exhibition/about-postal-operations-transportation/pneumatic",
        "postal technology",
        "1893–1953 CE",
    ),
    seed_fact(
        "history-harrison-h4-five-ticks",
        COLLECTION_HISTORY,
        "John Harrison's H4 marine timekeeper ticks five times each second.",
        "During its 1761 trial voyage, Harrison's son used it to predict an earlier landfall at Madeira than the ship's crew expected.",
        "Royal Museums Greenwich, Longitude found",
        "Longitude found: the story of Harrison's timekeepers",
        "https://www.rmg.co.uk/stories/time/harrisons-clocks-longitude-problem",
        "navigation and timekeeping",
        "1761 CE",
    ),
    seed_fact(
        "history-hollerith-electrical-census",
        COLLECTION_HISTORY,
        "Herman Hollerith's punched-card tabulator sensed holes using pins, mercury cups, and electrical circuits.",
        "The system helped complete the 1890 U.S. census tabulation in one year after the 1880 census had taken eight.",
        "Library of Congress, Hollerith's Electric Sorting and Tabulating Machine",
        "Plate, punch card, and instructions for Herman Hollerith's Electric Sorting and Tabulating Machine",
        "https://www.loc.gov/item/mcc.023/",
        "data processing",
        "late 19th century CE",
    ),
    seed_fact(
        "history-standard-time-two-noons",
        COLLECTION_HISTORY,
        "When North American railroads adopted standard time in 1883, some communities briefly experienced two versions of noon.",
        "One was local solar noon; the other was noon under the new railway time zone.",
        "Smithsonian National Museum of American History, Synchronizing Time",
        "Synchronizing Time: Time Zones",
        "https://americanhistory.si.edu/ontime/synchronizing/zones.html",
        "time standardization",
        "1883 CE",
    ),
]

COMMON_LATIN_SEED_IDS = {
    "horace-odes-1-11",
    "terence-heauton-77",
    "juvenal-satire-6-347",
    "juvenal-satire-10-81",
    "juvenal-satire-10-356",
    "catullus-85",
    "suetonius-caesar-32",
    "suetonius-caesar-37",
}
LEGACY_COMMON_LATIN = [
    item for item in SEED_SAYINGS if item["id"] in COMMON_LATIN_SEED_IDS
]
SEED_SAYINGS = [
    item for item in SEED_SAYINGS if item["id"] not in COMMON_LATIN_SEED_IDS
]
LEGACY_REPLACEABLE_SEEDS = {
    item["id"]: item
    for item in [*LEGACY_COMMON_LATIN, *LEGACY_COMMON_FACTS]
}

ALL_SEED_CONTENT = [*SEED_SAYINGS, *SEED_FACTS]

# These religious starter entries existed in v1.0.0. Migration removes them
# from the active library without disturbing OAuth, settings, queue, or history.
RETIRED_SEED_IDS = {
    "augustine-conf-1-1",
    "ecclesiastes-3-1",
    "dhammapada-1-5",
}


# ---------------------------------------------------------------------------
# Configuration and state helpers
# ---------------------------------------------------------------------------

def read_secrets() -> dict[str, str]:
    try:
        raw = dict(st.secrets)
    except FileNotFoundError:
        raw = {}
    return {str(key): str(value).strip() for key, value in raw.items()}


def required_secret_names() -> list[str]:
    return [
        "ADMIN_PASSWORD",
        "GITHUB_REPOSITORY",
        "GITHUB_STATE_TOKEN",
        "LINKEDIN_CLIENT_ID",
        "LINKEDIN_CLIENT_SECRET",
        "LINKEDIN_REDIRECT_URI",
        "FERNET_KEY",
    ]


def normalize_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_bool(value: Any) -> bool:
    """Interpret persisted, CSV, pandas, and Streamlit checkbox values safely."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    if isinstance(value, (int, float)):
        return value != 0
    return normalize_space(value).casefold() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
        "checked",
    }


def saying_fingerprint(record: dict[str, Any]) -> str:
    collection = canonical_collection(record.get("collection"))
    primary_text = (
        record.get("latin")
        if collection == COLLECTION_LATIN
        else record.get("lead")
    )
    basis = "|".join(
        [
            collection,
            normalize_space(primary_text).casefold(),
            normalize_space(record.get("attribution")).casefold(),
        ]
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def latin_search_key(value: Any) -> str:
    decomposed = unicodedata.normalize("NFKD", normalize_space(value).casefold())
    without_marks = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z]+", " ", without_marks).strip()


def attribution_author(value: Any) -> str:
    attribution = normalize_space(value).casefold()
    return re.split(r"[,;]", attribution, maxsplit=1)[0].strip()


def parse_list_terms(value: Any) -> list[str]:
    text = normalize_space(value)
    if not text:
        return []
    text = re.sub(r"\s*,?\s+\band\b\s+", ",", text, flags=re.IGNORECASE)
    terms: list[str] = []
    seen: set[str] = set()
    for raw in re.split(r"[,;\n]+", text):
        term = normalize_space(raw)
        key = term.casefold()
        if term and key not in seen:
            terms.append(term)
            seen.add(key)
    return terms


def canonical_language(value: Any) -> str:
    language = latin_search_key(value)
    aliases = {
        "arabic": "Arabic",
        "chinese": "Classical Chinese",
        "greek": "Ancient Greek",
        "latin": "Latin",
        "sanskrit": "Sanskrit",
        "persian": "Persian",
        "hebrew": "Hebrew",
    }
    for token, label in aliases.items():
        if token in language.split():
            return label
    return normalize_space(value)


def canonical_collection(value: Any) -> str:
    key = normalize_space(value).casefold().replace("-", "_").replace(" ", "_")
    aliases = {
        "latin": COLLECTION_LATIN,
        "latin_saying": COLLECTION_LATIN,
        "latin_sayings": COLLECTION_LATIN,
        "physics": COLLECTION_PHYSICS,
        "physics_fact": COLLECTION_PHYSICS,
        "physics_facts": COLLECTION_PHYSICS,
        "history": COLLECTION_HISTORY,
        "history_fact": COLLECTION_HISTORY,
        "history_facts": COLLECTION_HISTORY,
    }
    return aliases.get(key, COLLECTION_LATIN)


def content_lead(record: dict[str, Any]) -> str:
    return normalize_space(
        record.get("latin")
        if canonical_collection(record.get("collection")) == COLLECTION_LATIN
        else record.get("lead")
    )


RELIGIOUS_LANGUAGE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b(god|gods|goddess|deity|divine|prayer|scripture|theology)\b", "English religious language"),
    (r"\b(religion|religious|sacred|holy|worship|salvation|prophet)\b", "English religious language"),
    (r"\b(deus|deum|dei|deo|divin(?:us|um|a|i)|oratio|theologia)\b", "Latin religious language"),
    (r"\b(sacer|sacra|sacrum|sanctus|sancta|sanctum)\b", "Latin religious language"),
)


def religious_language_hits(record: dict[str, Any]) -> list[str]:
    hits: list[str] = []
    # Scan only material that can appear in the post or substantiate it.
    # Internal notes may legitimately discuss why wording needs review.
    for field in (
        "lead",
        "body",
        "latin",
        "translation",
        "attribution",
        "source_text",
    ):
        text = normalize_space(record.get(field)).casefold()
        for pattern, label in RELIGIOUS_LANGUAGE_PATTERNS:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                hits.append(
                    f"{field}: “{match.group(0)}” ({label})"
                )
    return list(dict.fromkeys(hits))


def near_duplicate_match(
    candidate: dict[str, Any],
    existing_records: list[dict[str, Any]],
) -> tuple[dict[str, Any], str] | None:
    collection = canonical_collection(candidate.get("collection"))
    candidate_text = (
        candidate.get("latin")
        if collection == COLLECTION_LATIN
        else candidate.get("lead")
    )
    candidate_key = latin_search_key(candidate_text)
    candidate_tokens = candidate_key.split()
    if not candidate_tokens:
        return None
    candidate_set = set(candidate_tokens)
    candidate_author = attribution_author(candidate.get("attribution"))
    for existing in existing_records:
        if canonical_collection(existing.get("collection")) != collection:
            continue
        existing_text = (
            existing.get("latin")
            if collection == COLLECTION_LATIN
            else existing.get("lead")
        )
        existing_key = latin_search_key(existing_text)
        existing_tokens = existing_key.split()
        if not existing_tokens:
            continue
        if candidate_key == existing_key:
            return existing, "same normalized Latin text"
        existing_set = set(existing_tokens)
        union = candidate_set | existing_set
        similarity = (
            len(candidate_set & existing_set) / len(union) if union else 0.0
        )
        same_author = bool(candidate_author) and candidate_author == (
            attribution_author(existing.get("attribution"))
        )
        shorter, longer = sorted(
            [candidate_key, existing_key],
            key=len,
        )
        contained = len(shorter.split()) >= 2 and shorter in longer
        reordered_same_words = (
            len(candidate_tokens) >= 2
            and len(candidate_tokens) == len(existing_tokens)
            and candidate_set == existing_set
        )
        same_author_subset = (
            same_author
            and min(len(candidate_set), len(existing_set)) >= 2
            and (
                candidate_set.issubset(existing_set)
                or existing_set.issubset(candidate_set)
            )
        )
        if reordered_same_words or (
            same_author
            and (contained or similarity >= 0.72 or same_author_subset)
        ):
            reason = (
                "same words in a different order"
                if reordered_same_words
                else (
                    "same core Latin words with the same attributed author"
                    if same_author_subset
                    else "substantial Latin overlap with the same attributed author"
                )
            )
            return existing, reason
    return None


def normalize_saying(
    record: dict[str, Any],
    *,
    default_origin: str = "manual entry",
) -> dict[str, Any]:
    collection = canonical_collection(record.get("collection"))
    lead = normalize_space(record.get("lead"))
    body = normalize_space(record.get("body"))
    latin = normalize_space(record.get("latin"))
    translation = normalize_space(record.get("translation"))
    if collection != COLLECTION_LATIN:
        lead = lead or latin
        body = body or translation
        latin = ""
        translation = ""
    normalized = {
        "id": normalize_space(record.get("id")) or secrets.token_hex(8),
        "approved": normalize_bool(record.get("approved", False)),
        "collection": collection,
        "lead": lead,
        "body": body,
        "latin": latin,
        "translation": translation,
        "attribution": normalize_space(record.get("attribution")),
        "source_title": normalize_space(record.get("source_title"))
        or normalize_space(record.get("attribution")),
        "source_url": normalize_space(record.get("source_url")),
        "source_type": normalize_space(record.get("source_type"))
        or ("primary text" if collection == COLLECTION_LATIN else "reference"),
        "tags": normalize_space(record.get("tags"))
        or normalize_space(record.get("primary_theme")),
        "verified_at": normalize_space(record.get("verified_at")),
        "latin_kind": normalize_space(record.get("latin_kind"))
        or ("modern Latin rendering" if collection == COLLECTION_LATIN else ""),
        "primary_theme": normalize_space(record.get("primary_theme")),
        "source_language": normalize_space(record.get("source_language"))
        or "unknown",
        "source_period": normalize_space(record.get("source_period"))
        or "unknown",
        "source_confidence": normalize_space(
            record.get("source_confidence")
        ).casefold()
        or "unverified",
        "source_text": normalize_space(record.get("source_text")),
        "origin": normalize_space(record.get("origin")) or default_origin,
        "verification_status": normalize_space(
            record.get("verification_status")
        )
        or "needs human verification",
        "note": normalize_space(record.get("note")),
    }
    ai_review = record.get("ai_review")
    normalized["ai_review"] = (
        copy.deepcopy(ai_review) if isinstance(ai_review, dict) else {}
    )
    status = normalize_space(record.get("review_status")).casefold()
    normalized["review_status"] = (
        status if status in {"unreviewed", "pass", "caution", "reject"} else "unreviewed"
    )
    normalized["reviewed_at"] = normalize_space(record.get("reviewed_at"))
    normalized["review_model"] = normalize_space(record.get("review_model"))
    normalized["duplicate_warning"] = normalize_space(
        record.get("duplicate_warning")
    )
    normalized["policy_warning"] = normalize_space(
        record.get("policy_warning")
    )
    return normalized


def is_untouched_replaceable_seed(raw: dict[str, Any]) -> bool:
    """Return True only for an unchanged, unapproved bundled starter row."""
    seed = LEGACY_REPLACEABLE_SEEDS.get(str(raw.get("id", "")))
    if not seed or normalize_bool(raw.get("approved")):
        return False
    if normalize_space(raw.get("origin")) not in {
        "",
        normalize_space(seed.get("origin")),
    }:
        return False
    fields = (
        ("collection", "latin", "translation", "attribution")
        if canonical_collection(seed.get("collection")) == COLLECTION_LATIN
        else (
            "collection",
            "lead",
            "body",
            "attribution",
            "source_url",
        )
    )
    return all(
        normalize_space(raw.get(field)).casefold()
        == normalize_space(seed.get(field)).casefold()
        for field in fields
    )


def merge_curated_library(
    records: list[dict[str, Any]],
    protected_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    protected_ids = protected_ids or set()
    seed_by_id = {seed["id"]: seed for seed in ALL_SEED_CONTENT}
    active: list[dict[str, Any]] = []
    for raw in records:
        if str(raw.get("id", "")) in RETIRED_SEED_IDS:
            continue
        if (
            str(raw.get("id", "")) not in protected_ids
            and is_untouched_replaceable_seed(raw)
        ):
            continue
        record = normalize_saying(raw)
        seed = seed_by_id.get(record["id"])
        if seed:
            if not normalize_space(raw.get("primary_theme")):
                record["primary_theme"] = seed["primary_theme"]
            if normalize_space(raw.get("source_language")).casefold() in {
                "",
                "unknown",
            }:
                record["source_language"] = seed["source_language"]
            if normalize_space(raw.get("source_period")).casefold() in {
                "",
                "unknown",
            }:
                record["source_period"] = seed["source_period"]
            if normalize_space(raw.get("source_confidence")).casefold() in {
                "",
                "unknown",
                "unverified",
            }:
                record["source_confidence"] = seed["source_confidence"]
            if not normalize_space(raw.get("source_text")):
                record["source_text"] = seed["source_text"]
            if normalize_space(raw.get("origin")).casefold() in {
                "",
                "manual entry",
            }:
                record["origin"] = seed["origin"]
            if normalize_space(raw.get("verification_status")).casefold() in {
                "",
                "needs human verification",
            }:
                record["verification_status"] = seed[
                    "verification_status"
                ]
            if not normalize_space(raw.get("note")) and seed.get("note"):
                record["note"] = seed["note"]
        policy_hits = religious_language_hits(record)
        if policy_hits:
            record["approved"] = False
            record["verification_status"] = (
                "blocked by secular wording policy"
            )
            policy_note = (
                "Secular wording policy: "
                + "; ".join(policy_hits)
                + "."
            )
            if policy_note not in record["note"]:
                record["note"] = normalize_space(
                    f"{record['note']} {policy_note}"
                )
        active.append(record)
    ids = {record["id"] for record in active}
    fingerprints = {saying_fingerprint(record) for record in active}
    for seed in ALL_SEED_CONTENT:
        fingerprint = saying_fingerprint(seed)
        if seed["id"] in ids or fingerprint in fingerprints:
            continue
        active.append(copy.deepcopy(seed))
        ids.add(seed["id"])
        fingerprints.add(fingerprint)
    return active


def normalize_ai_candidates(
    records: list[dict[str, Any]],
    sayings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in records:
        candidate = normalize_saying(
            raw,
            default_origin="DeepSeek candidate",
        )
        policy_hits = religious_language_hits(candidate)
        if policy_hits:
            candidate["policy_warning"] = (
                "Excluded religious or theological wording detected: "
                + "; ".join(policy_hits)
                + "."
            )
            candidate["review_status"] = "reject"
        if not candidate["duplicate_warning"]:
            near_match = near_duplicate_match(
                candidate,
                sayings + normalized,
            )
            if near_match:
                existing, reason = near_match
                if reason == "same normalized Latin text":
                    continue
                candidate["duplicate_warning"] = (
                    f"Possible duplicate of “{content_lead(existing)}” "
                    f"({existing['attribution']}): {reason}."
                )
                if candidate["review_status"] != "reject":
                    candidate["review_status"] = "caution"
        normalized.append(candidate)
    return normalized[-MAX_AI_CANDIDATES:]


def new_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "revision": 0,
        "settings": {
            "automation_enabled": False,
            "dry_run": True,
            "posts_per_week_min": 2,
            "posts_per_week_max": 3,
            "allowed_weekdays": [0, 1, 2, 3, 4],
            "earliest_time": "08:30",
            "latest_time": "18:30",
            "min_spacing_hours": 18,
            "schedule_horizon_days": 21,
            "visibility": "PUBLIC",
            "recent_saying_window": 20,
            "max_post_chars": 600,
            "enabled_collections": COLLECTION_KEYS,
            "collection_weights": {
                COLLECTION_LATIN: 1,
                COLLECTION_PHYSICS: 1,
                COLLECTION_HISTORY: 1,
            },
        },
        "linkedin": {
            "connected": False,
            "encrypted_access_token": "",
            "expires_at": "",
            "person_id": "",
            "display_name": "",
        },
        "oauth": {},
        # `sayings` is retained as the internal key so existing GitHub state,
        # queue records, and worker logic migrate without destructive rewrites.
        "sayings": copy.deepcopy(ALL_SEED_CONTENT),
        "ai_candidates": [],
        "queue": [],
        "history": [],
        "events": [],
    }


def normalize_state(state: dict[str, Any]) -> dict[str, Any]:
    defaults = new_state()
    state["schema_version"] = SCHEMA_VERSION
    state.setdefault("revision", 0)
    state.setdefault("settings", {})
    for key, value in defaults["settings"].items():
        state["settings"].setdefault(key, value)
    state["settings"]["enabled_collections"] = list(
        dict.fromkeys(
            canonical_collection(value)
            for value in state["settings"].get(
                "enabled_collections", COLLECTION_KEYS
            )
        )
    )
    raw_weights = state["settings"].get("collection_weights", {})
    state["settings"]["collection_weights"] = {
        key: max(1, int(raw_weights.get(key, 1)))
        for key in COLLECTION_KEYS
    }
    state.setdefault("linkedin", defaults["linkedin"])
    for key, value in defaults["linkedin"].items():
        state["linkedin"].setdefault(key, value)
    state.setdefault("oauth", {})
    state.setdefault("queue", [])
    state.setdefault("history", [])
    protected_ids = {
        normalize_space(item.get("saying_id"))
        for item in [*state["queue"], *state["history"]]
        if normalize_space(item.get("saying_id"))
    }
    state["sayings"] = merge_curated_library(
        list(state.get("sayings") or []),
        protected_ids=protected_ids,
    )
    state.setdefault("ai_candidates", [])
    state["ai_candidates"] = normalize_ai_candidates(
        list(state["ai_candidates"] or []),
        state["sayings"],
    )
    sayings_by_id = {item["id"]: item for item in state["sayings"]}
    for item in state["queue"]:
        if item.get("status") not in {
            "queued",
            "publishing",
            "needs_review",
            "failed",
        }:
            continue
        saying = sayings_by_id.get(
            normalize_space(item.get("saying_id")),
            item.get("saying_snapshot") or {},
        )
        source_text = item.get("post_text") or (
            format_post(saying) if saying else ""
        )
        item["post_text"] = ensure_automation_footer(source_text)
    state.setdefault("events", [])
    return state


def append_event(
    state: dict[str, Any], level: str, message: str, **details: Any
) -> None:
    event: dict[str, Any] = {
        "at": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "message": message,
    }
    if details:
        event["details"] = details
    state["events"].append(event)
    state["events"] = state["events"][-MAX_EVENTS:]


def ensure_automation_footer(value: Any) -> str:
    """Append exactly one disclosure footer to a formatted post."""
    text = str(value or "").strip()
    footer_pattern = re.compile(
        r"(?:\s*\n\s*)*\(Automated post; reviewed before scheduling\.\)\s*$",
        flags=re.IGNORECASE,
    )
    while footer_pattern.search(text):
        text = footer_pattern.sub("", text).strip()
    return f"{text}\n\n{AUTOMATION_FOOTER}" if text else AUTOMATION_FOOTER


def format_post(saying: dict[str, Any]) -> str:
    collection = canonical_collection(saying.get("collection"))
    if collection == COLLECTION_LATIN:
        parts = [
            normalize_space(saying.get("latin")),
            normalize_space(saying.get("translation")),
            f"— {normalize_space(saying.get('attribution'))}",
        ]
    else:
        prefix = (
            "Physics note"
            if collection == COLLECTION_PHYSICS
            else "History note"
        )
        parts = [
            f"{prefix}: {normalize_space(saying.get('lead'))}",
            normalize_space(saying.get("body")),
            f"Source: {normalize_space(saying.get('attribution'))}",
        ]
    return ensure_automation_footer(
        "\n\n".join(part for part in parts if part)
    )


def encrypt_value(value: str, key: str) -> str:
    return Fernet(key.encode()).encrypt(value.encode()).decode()


def decrypt_value(value: str, key: str) -> str:
    try:
        return Fernet(key.encode()).decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise ValueError(
            "The stored LinkedIn credential cannot be decrypted with FERNET_KEY."
        ) from exc


# ---------------------------------------------------------------------------
# DeepSeek-assisted candidate generation and review
# ---------------------------------------------------------------------------

class DeepSeekError(RuntimeError):
    pass


def parse_json_object(value: str) -> dict[str, Any]:
    text = str(value or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DeepSeekError(
            "DeepSeek returned a response that was not valid JSON."
        ) from exc
    if not isinstance(parsed, dict):
        raise DeepSeekError("DeepSeek returned an unexpected JSON structure.")
    return parsed


def call_deepseek_json(
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    *,
    max_tokens: int = 3000,
) -> dict[str, Any]:
    if not api_key:
        raise DeepSeekError(
            "Add DEEPSEEK_API_KEY to Streamlit Secrets before using AI tools."
        )
    token_budgets = [
        int(max_tokens),
        min(max(int(max_tokens) * 2, int(max_tokens) + 1200), 8000),
    ]
    last_retryable_error = ""
    for attempt, token_budget in enumerate(token_budgets, start=1):
        payload = {
            "model": model or DEFAULT_DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "temperature": 0.2,
            "max_tokens": token_budget,
            "stream": False,
        }
        try:
            response = requests.post(
                DEEPSEEK_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=90,
            )
        except requests.Timeout as exc:
            raise DeepSeekError(
                "DeepSeek timed out. No candidates were saved; try a smaller request."
            ) from exc
        except requests.RequestException as exc:
            raise DeepSeekError(f"DeepSeek request failed: {exc}") from exc
        if response.status_code != 200:
            messages = {
                401: "DeepSeek rejected the API key.",
                402: "The DeepSeek account has insufficient balance.",
                429: "DeepSeek is temporarily rate-limiting this account.",
            }
            detail = messages.get(
                response.status_code,
                f"DeepSeek returned HTTP {response.status_code}.",
            )
            raise DeepSeekError(detail)
        try:
            body = response.json()
            choice = body["choices"][0]
            finish_reason = normalize_space(choice.get("finish_reason"))
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise DeepSeekError(
                "DeepSeek returned an incomplete response."
            ) from exc
        if finish_reason == "length":
            last_retryable_error = (
                "DeepSeek reached its generated-output limit."
            )
        elif not str(content or "").strip():
            last_retryable_error = "DeepSeek returned an empty response."
        else:
            try:
                return parse_json_object(str(content))
            except DeepSeekError as exc:
                last_retryable_error = str(exc)
        if attempt == 1:
            continue
    raise DeepSeekError(
        f"{last_retryable_error} The app retried once with a larger output "
        "allowance and saved nothing. Try fewer candidates."
    )


def validate_ai_candidate(
    raw: dict[str, Any],
    *,
    origin: str,
) -> dict[str, Any]:
    if raw.get("secular") is not True:
        raise ValueError("Candidate was not explicitly classified as secular.")
    candidate = normalize_saying(
        {
            **raw,
            "id": f"ai-{secrets.token_hex(8)}",
            "approved": False,
            "origin": origin,
            "verification_status": "AI candidate; human verification required",
        },
        default_origin=origin,
    )
    collection = candidate["collection"]
    required_fields = (
        ("latin", "translation", "attribution", "latin_kind", "source_language")
        if collection == COLLECTION_LATIN
        else (
            "lead",
            "body",
            "attribution",
            "source_title",
            "source_url",
            "primary_theme",
        )
    )
    missing = [field for field in required_fields if not candidate[field]]
    if missing:
        raise ValueError(f"Candidate is missing: {', '.join(missing)}.")
    if len(format_post(candidate)) > 3000:
        raise ValueError("Candidate exceeds LinkedIn's supported text length.")
    confidence = candidate["source_confidence"]
    if confidence not in {"high", "medium", "low", "unverified"}:
        raise ValueError(
            "Candidate has an invalid source-confidence classification."
        )
    religious_hits = religious_language_hits(candidate)
    if religious_hits:
        raise ValueError(
            "Candidate contains excluded religious or theological language "
            f"({', '.join(religious_hits)})."
        )
    source_language = canonical_language(candidate["source_language"])
    kind_key = latin_search_key(candidate["latin_kind"])
    if (
        collection == COLLECTION_LATIN
        and source_language != "Latin"
        and "rendering" not in kind_key.split()
    ):
        raise ValueError(
            "A non-Latin source must be labelled as a modern Latin rendering."
        )
    if collection != COLLECTION_LATIN:
        parsed_url = urlparse(candidate["source_url"])
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("Fact candidate needs a valid source URL.")
    if confidence == "low" and candidate["review_status"] != "reject":
        candidate["review_status"] = "caution"
        candidate["note"] = normalize_space(
            f"{candidate['note']} Low source confidence; verify before use."
        )
    return candidate


def generate_deepseek_facts(
    api_key: str,
    model: str,
    collection: str,
    quantity: int,
    required_theme: str,
    supporting_themes: str,
    existing_items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Generate source-led physics or history candidates for human review."""
    collection = canonical_collection(collection)
    if collection not in {COLLECTION_PHYSICS, COLLECTION_HISTORY}:
        raise DeepSeekError("Select Physics facts or History facts.")
    domain = "physics" if collection == COLLECTION_PHYSICS else "history"
    system_prompt = f"""
You are a cautious {domain} research editor. Return JSON only. Propose concise,
evergreen, secular fact candidates for a public LinkedIn post. Prefer
less-familiar details that reward a curious reader; avoid textbook-summary
facts and famous headline examples unless the requested theme requires them.
Every factual
claim needs a checkable, authoritative source. Prefer primary institutions,
standards bodies, museums, archives, universities, or peer-reviewed sources.
Do not invent a quotation, citation, title, date, institution, or URL. Avoid
breaking news, partisan framing, disputed superlatives, myths, trivia without
context, medicine or safety advice, and claims whose accuracy depends on the
current date. If uncertain, set source_confidence to low. Generated material is
an editorial lead and is never source verification.

Return:
{{
  "candidates": [
    {{
      "collection": "{collection}",
      "lead": "one self-contained fact",
      "body": "one short explanatory or contextual sentence",
      "attribution": "institution or author, source title",
      "source_title": "exact source title",
      "source_url": "https://...",
      "source_type": "primary source, standard, museum, archive, or reference",
      "primary_theme": "one concise theme",
      "tags": "comma-separated tags",
      "source_language": "language of the source",
      "source_period": "relevant date or period",
      "source_confidence": "high OR medium OR low",
      "source_text": "short supporting excerpt or blank",
      "note": "specific verification caveat or blank",
      "secular": true
    }}
  ]
}}
""".strip()
    quantity = int(quantity)
    existing_compact = [
        {
            "lead": normalize_space(item.get("lead")),
            "attribution": normalize_space(item.get("attribution")),
        }
        for item in existing_items
        if canonical_collection(item.get("collection")) == collection
    ]
    theme_instruction = (
        f"Every candidate must have the primary theme "
        f"“{normalize_space(required_theme)}”. "
        if normalize_space(required_theme)
        else ""
    )
    parsed = call_deepseek_json(
        api_key,
        model,
        system_prompt,
        (
            f"Return exactly {quantity} distinct {domain} candidates. "
            + theme_instruction
            + "Supporting themes may include: "
            + (
                normalize_space(supporting_themes)
                or (
                    "measurement, matter, energy, space"
                    if collection == COLLECTION_PHYSICS
                    else "institutions, technology, daily life, discovery"
                )
            )
            + ". Keep each formatted post under 600 characters including the "
            "automatic disclosure footer. Do not "
            "duplicate these existing records: "
            + json.dumps(existing_compact, ensure_ascii=False)
        ),
        max_tokens=max(2600, quantity * 800),
    )
    raw_candidates = parsed.get("candidates")
    if not isinstance(raw_candidates, list):
        raise DeepSeekError("DeepSeek did not return a candidate list.")
    accepted: list[dict[str, Any]] = []
    warnings: list[str] = []
    required_theme_key = latin_search_key(required_theme)
    for index, raw in enumerate(raw_candidates):
        try:
            if not isinstance(raw, dict):
                raise ValueError("Candidate is not a JSON object.")
            raw["collection"] = collection
            candidate = validate_ai_candidate(
                raw,
                origin=f"DeepSeek {domain} suggestion ({model})",
            )
            if (
                required_theme_key
                and required_theme_key
                not in latin_search_key(candidate["primary_theme"])
            ):
                raise ValueError(
                    f"primary_theme was “{candidate['primary_theme']}”, not "
                    f"the required “{normalize_space(required_theme)}”."
                )
            match = near_duplicate_match(
                candidate,
                existing_items + accepted,
            )
            if match:
                raise ValueError(
                    f"possible duplicate of “{match[0].get('lead')}”: "
                    f"{match[1]}."
                )
            accepted.append(candidate)
        except ValueError as exc:
            warnings.append(f"Candidate {index + 1} was skipped: {exc}")
    if not accepted:
        detail = f" First rejection: {warnings[0]}" if warnings else ""
        raise DeepSeekError(f"No usable {domain} candidates were returned.{detail}")
    if len(accepted) < quantity:
        warnings.append(
            f"Staged {len(accepted)} of {quantity} requested candidates; "
            "filtered candidates were not replaced automatically."
        )
    return accepted[:quantity], warnings


def generate_deepseek_sayings(
    api_key: str,
    model: str,
    quantity: int,
    required_theme: str,
    themes: str,
    required_source_language: str,
    source_preferences: str,
    source_mode: str,
    existing_sayings: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    system_prompt = """
You are a cautious classical-language editorial assistant. Return JSON only.
Propose concise, secular sayings from ancient or pre-modern sources for human
review. Prefer less-overused passages and avoid commonplace mottoes already
widely circulated without context. Latin and Greek material will usually be
from antiquity. When Classical
Arabic is requested, material may come from the medieval Arabic intellectual
tradition through 1500 CE, especially mathematics, medicine, optics, natural
philosophy, ethics, and learning. Exclude scripture, prayers, theology,
devotional teaching, denominational material, and wording that invokes gods,
deities, divine power, worship, prophecy, sacredness, or salvation, even in a
secular criticism. Never invent an author, work, section, original-language
text, or claim of original Latin. For a Latin author, quote the original Latin.
For a source in another language, create a concise modern Latin rendering and
label it honestly. The English translation must match the Latin. A candidate
may be plausible yet must still be treated as unverified. The user will supply
an existing-library list. Do not return the same saying, a shortened excerpt of
it, a reordered version of it, or a close paraphrase attributed to the same
source.

Return this JSON shape:
{
  "candidates": [
    {
      "latin": "...",
      "translation": "...",
      "attribution": "author, work and section where known",
      "latin_kind": "original Latin OR modern Latin rendering from <language>",
      "primary_theme": "one concise theme",
      "source_language": "...",
      "source_period": "century or historical period",
      "source_confidence": "high OR medium OR low",
      "source_text": "original-language text if reliably known, otherwise blank",
      "note": "specific verification caveat or blank",
      "secular": true
    }
  ]
}
""".strip()
    quantity = int(quantity)
    if source_mode not in SOURCE_MODES:
        raise DeepSeekError("Select a valid source-language mode.")
    preferred_languages = [
        canonical_language(item)
        for item in parse_list_terms(source_preferences)
    ]
    preferred_languages = list(dict.fromkeys(preferred_languages))
    required_language = canonical_language(required_source_language)
    if source_mode == SOURCE_MODE_REQUIRED and not required_language:
        raise DeepSeekError(
            "Enter a required source language or select another source mode."
        )
    if source_mode == SOURCE_MODE_BALANCED and not preferred_languages:
        raise DeepSeekError(
            "Enter at least one preferred source language for balanced coverage."
        )
    if (
        source_mode == SOURCE_MODE_BALANCED
        and preferred_languages
        and quantity < len(preferred_languages)
    ):
        raise DeepSeekError(
            "Balanced source coverage needs at least "
            f"{len(preferred_languages)} candidates for the "
            f"{len(preferred_languages)} listed source languages. Increase "
            "the candidate count, reduce the source list, or select a "
            "different source-language mode."
        )
    theme_instruction = (
        f"Every candidate must primarily address this required theme: "
        f"{normalize_space(required_theme)}. "
        if normalize_space(required_theme)
        else ""
    )
    required_theme_key = latin_search_key(required_theme)
    candidates: list[dict[str, Any]] = []
    warnings: list[str] = []

    def missing_balanced_languages() -> list[str]:
        returned = {
            canonical_language(item["source_language"])
            for item in candidates
        }
        return [
            language
            for language in preferred_languages
            if language not in returned
        ]

    def make_room_for_missing_languages() -> None:
        if source_mode != SOURCE_MODE_BALANCED:
            del candidates[quantity:]
            return
        missing = missing_balanced_languages()
        target_size = max(0, quantity - len(missing))
        while len(candidates) > target_size:
            counts: dict[str, int] = {}
            for item in candidates:
                language = canonical_language(item["source_language"])
                counts[language] = counts.get(language, 0) + 1
            removable_index = next(
                (
                    index
                    for index in range(len(candidates) - 1, -1, -1)
                    if counts.get(
                        canonical_language(
                            candidates[index]["source_language"]
                        ),
                        0,
                    )
                    > 1
                    or canonical_language(
                        candidates[index]["source_language"]
                    )
                    not in preferred_languages
                ),
                None,
            )
            if removable_index is None:
                break
            candidates.pop(removable_index)

    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        make_room_for_missing_languages()
        remaining = quantity - len(candidates)
        missing_languages = (
            missing_balanced_languages()
            if source_mode == SOURCE_MODE_BALANCED
            else []
        )
        if remaining <= 0 and not missing_languages:
            break
        if source_mode == SOURCE_MODE_REQUIRED:
            source_instruction = (
                f"Every candidate must originate in {required_language}; do "
                "not substitute another source language. "
            )
        elif source_mode == SOURCE_MODE_BALANCED:
            target_languages = missing_languages or preferred_languages
            source_instruction = (
                "Use only these source languages in this response and include "
                f"each at least once: {', '.join(target_languages)}. "
            )
        else:
            source_instruction = (
                "Treat these as preferences rather than guaranteed coverage: "
                f"{normalize_space(source_preferences) or 'a varied secular selection'}. "
            )
        existing_compact = [
            {
                "latin": normalize_space(item.get("latin")),
                "attribution": normalize_space(item.get("attribution")),
            }
            for item in existing_sayings + candidates
        ]
        user_prompt = "".join(
            [
                f"Return exactly {remaining} distinct candidates in JSON. ",
                (
                    f"This is replacement attempt {attempt}; replace any "
                    "previously rejected or missing result. "
                    if attempt > 1
                    else ""
                ),
                theme_instruction,
                "Optional supporting themes: ",
                (
                    normalize_space(themes)
                    or "wisdom, time, learning, courage, friendship"
                ),
                ". ",
                source_instruction,
                "Keep each finished Latin/translation/attribution post under ",
                "600 characters including the automatic disclosure footer. ",
                "Set source_confidence to low whenever the exact wording, work, ",
                "or section is uncertain. Do not present a Latin translation as ",
                "an original quotation. Do not duplicate or closely overlap any ",
                "entry in this existing library JSON: ",
                json.dumps(existing_compact, ensure_ascii=False),
            ]
        )
        parsed = call_deepseek_json(
            api_key,
            model,
            system_prompt,
            user_prompt,
            max_tokens=max(2400, remaining * 700),
        )
        raw_candidates = parsed.get("candidates", [])
        if not isinstance(raw_candidates, list):
            warnings.append(
                f"Attempt {attempt} did not return a candidate list."
            )
            continue
        if len(raw_candidates) != remaining:
            warnings.append(
                f"Attempt {attempt} returned {len(raw_candidates)} raw "
                f"candidate(s), not the requested {remaining}."
            )
        for index, raw in enumerate(raw_candidates):
            try:
                if not isinstance(raw, dict):
                    raise ValueError("Candidate is not a JSON object.")
                missing_metadata = [
                    field
                    for field in (
                        "primary_theme",
                        "source_period",
                        "source_confidence",
                    )
                    if not normalize_space(raw.get(field))
                ]
                if missing_metadata:
                    raise ValueError(
                        "Candidate is missing structured metadata: "
                        + ", ".join(missing_metadata)
                        + "."
                    )
                candidate = validate_ai_candidate(
                    raw,
                    origin=f"DeepSeek suggestion ({model})",
                )
                candidate_language = canonical_language(
                    candidate["source_language"]
                )
                if (
                    source_mode == SOURCE_MODE_REQUIRED
                    and candidate_language != required_language
                ):
                    raise ValueError(
                        f"source_language was {candidate_language}, not the "
                        f"required {required_language}."
                    )
                if (
                    source_mode == SOURCE_MODE_BALANCED
                    and candidate_language not in preferred_languages
                ):
                    raise ValueError(
                        f"source_language {candidate_language} was outside "
                        "the balanced source list."
                    )
                if (
                    required_theme_key
                    and required_theme_key
                    not in latin_search_key(candidate["primary_theme"])
                ):
                    raise ValueError(
                        f"primary_theme was "
                        f"“{candidate['primary_theme']}”, not the required "
                        f"“{normalize_space(required_theme)}”."
                    )
                near_match = near_duplicate_match(
                    candidate,
                    existing_sayings + candidates,
                )
                if near_match:
                    existing, reason = near_match
                    raise ValueError(
                        f"possible duplicate of “{existing['latin']}”: "
                        f"{reason}."
                    )
                candidates.append(candidate)
            except ValueError as exc:
                warnings.append(
                    f"Attempt {attempt}, candidate {index + 1} was skipped: "
                    f"{exc}"
                )
        make_room_for_missing_languages()
        if (
            len(candidates) >= quantity
            and (
                source_mode != SOURCE_MODE_BALANCED
                or not missing_balanced_languages()
            )
        ):
            break
    if not candidates:
        detail = f" First rejection: {warnings[0]}" if warnings else ""
        raise DeepSeekError(
            "DeepSeek returned no usable secular candidates after automatic "
            f"replacement attempts.{detail}"
        )
    candidates = candidates[:quantity]
    if len(candidates) < quantity:
        warnings.append(
            f"Only {len(candidates)} of {quantity} requested candidates "
            "passed validation after automatic replacement attempts. The "
            "valid partial result was staged."
        )
    if source_mode == SOURCE_MODE_BALANCED:
        missing_languages = missing_balanced_languages()
        if missing_languages:
            warnings.append(
                "Balanced coverage remains incomplete for: "
                + ", ".join(missing_languages)
                + "."
            )
    return candidates, list(dict.fromkeys(warnings))


def translate_with_deepseek(
    api_key: str,
    model: str,
    source_text: str,
    source_language: str,
    attribution: str,
) -> dict[str, Any]:
    system_prompt = """
You are a cautious Latin translator. Return JSON only. Translate the supplied
short text into clear, idiomatic Latin and provide a literal English
back-translation. Do not invent an ancient provenance or attribution. Preserve
the supplied attribution exactly; if none was supplied, use
"User-supplied text". The result must be secular and non-religious.

Return this JSON shape:
{
  "candidate": {
    "latin": "...",
    "translation": "...",
    "attribution": "...",
    "latin_kind": "modern Latin rendering from <language>",
    "primary_theme": "one concise theme",
    "source_language": "...",
    "source_period": "period supplied or inferred cautiously",
    "source_confidence": "medium",
    "source_text": "...",
    "note": "AI translation; verify the Latin before approval.",
    "secular": true
  }
}
""".strip()
    safe_text = str(source_text or "").strip()[:4000]
    if not safe_text:
        raise DeepSeekError("Enter text to translate.")
    user_prompt = json.dumps(
        {
            "source_text": safe_text,
            "source_language": normalize_space(source_language) or "unknown",
            "attribution": normalize_space(attribution)
            or "User-supplied text",
        },
        ensure_ascii=False,
    )
    parsed = call_deepseek_json(
        api_key,
        model,
        system_prompt,
        f"Translate this JSON input and return the requested JSON output: {user_prompt}",
        max_tokens=1400,
    )
    raw = parsed.get("candidate")
    if not isinstance(raw, dict):
        raise DeepSeekError("DeepSeek did not return a translation candidate.")
    raw["attribution"] = normalize_space(attribution) or "User-supplied text"
    raw["source_text"] = safe_text
    raw["source_language"] = normalize_space(source_language) or "unknown"
    return validate_ai_candidate(
        raw,
        origin=f"DeepSeek translation ({model})",
    )


def review_with_deepseek(
    api_key: str,
    model: str,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    if canonical_collection(candidate.get("collection")) == COLLECTION_LATIN:
        system_prompt = """
You are a skeptical classical-language reviewer. Return JSON only. Assess the
candidate without rewriting it. Check Latin grammar, translation fidelity,
whether the Latin is original or modern, whether the attribution is plausible,
and whether it is secular and non-religious. Do not claim external verification.

Return:
{
  "overall": "pass | caution | reject",
  "latin_assessment": "...",
  "translation_assessment": "...",
  "attribution_assessment": "...",
  "source_assessment": "...",
  "secularity_assessment": "...",
  "recommended_action": "...",
  "corrected_latin": "corrected wording when appropriate, otherwise blank",
  "corrected_translation": "matching translation or blank",
  "corrected_attribution": "corrected attribution or blank",
  "corrected_latin_kind": "corrected classification or blank",
  "corrected_source_language": "corrected source language or blank",
  "corrected_source_period": "corrected source period or blank",
  "corrected_source_confidence": "high, medium, low, or blank",
  "correction_reason": "why the correction is suggested or blank"
}
""".strip()
    else:
        system_prompt = """
You are a skeptical research editor. Return JSON only. Assess the supplied
physics or history candidate without rewriting it. Check internal consistency,
chronology where relevant, whether the attribution and URL are plausible,
whether the source appears authoritative, whether the explanation supports the
lead, and whether the item is secular. Do not claim that you opened the URL or
independently verified the source.

Return:
{
  "overall": "pass | caution | reject",
  "latin_assessment": "not applicable",
  "translation_assessment": "assess lead/body consistency",
  "attribution_assessment": "...",
  "source_assessment": "...",
  "secularity_assessment": "...",
  "recommended_action": "...",
  "corrected_latin": "",
  "corrected_translation": "",
  "corrected_attribution": "",
  "corrected_latin_kind": "",
  "corrected_source_language": "",
  "corrected_source_period": "",
  "corrected_source_confidence": "high, medium, low, or blank",
  "correction_reason": ""
}
""".strip()
    parsed = call_deepseek_json(
        api_key,
        model,
        system_prompt,
        "Review this candidate JSON: "
        + json.dumps(candidate, ensure_ascii=False),
        max_tokens=1500,
    )
    required = [
        "overall",
        "latin_assessment",
        "translation_assessment",
        "attribution_assessment",
        "source_assessment",
        "secularity_assessment",
        "recommended_action",
    ]
    if any(not normalize_space(parsed.get(field)) for field in required):
        raise DeepSeekError("DeepSeek returned an incomplete review.")
    result = {field: normalize_space(parsed[field]) for field in required}
    result["overall"] = result["overall"].casefold()
    if result["overall"] not in {"pass", "caution", "reject"}:
        raise DeepSeekError("DeepSeek returned an invalid review status.")
    for field in (
        "corrected_latin",
        "corrected_translation",
        "corrected_attribution",
        "corrected_latin_kind",
        "corrected_source_language",
        "corrected_source_period",
        "corrected_source_confidence",
        "correction_reason",
    ):
        result[field] = normalize_space(parsed.get(field))
    return result


def backfill_candidate_metadata_with_deepseek(
    api_key: str,
    model: str,
    candidates: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, str]], list[str]]:
    pending = [
        item
        for item in candidates
        if (
            not normalize_space(item.get("primary_theme"))
            or normalize_space(item.get("source_period")).casefold()
            in {"", "unknown"}
            or normalize_space(item.get("source_confidence")).casefold()
            in {"", "unknown", "unverified"}
        )
    ][:MAX_METADATA_BACKFILL]
    if not pending:
        return {}, []
    system_prompt = """
You are a cautious classical-source metadata editor. Return JSON only. Fill
metadata for the supplied candidates without changing, correcting, or
rephrasing their Latin, translation, or attribution. Do not invent certainty.
Use low source confidence when an attribution or exact textual source is
uncertain. Source language means the language of the underlying source, not
the Latin rendering. Source period should be a concise century or historical
period.

Return:
{
  "updates": [
    {
      "id": "exact supplied id",
      "primary_theme": "one concise theme",
      "source_language": "...",
      "source_period": "...",
      "source_confidence": "high OR medium OR low"
    }
  ]
}
""".strip()
    supplied = [
        {
            "id": item["id"],
            "latin": item["latin"],
            "translation": item["translation"],
            "attribution": item["attribution"],
            "latin_kind": item["latin_kind"],
            "source_language": item["source_language"],
        }
        for item in pending
    ]
    parsed = call_deepseek_json(
        api_key,
        model,
        system_prompt,
        "Fill only the missing or unverified metadata for these candidates: "
        + json.dumps(supplied, ensure_ascii=False),
        max_tokens=max(2400, len(pending) * 300),
    )
    raw_updates = parsed.get("updates")
    if not isinstance(raw_updates, list):
        raise DeepSeekError("DeepSeek did not return a metadata update list.")
    allowed_ids = {item["id"] for item in pending}
    updates: dict[str, dict[str, str]] = {}
    warnings: list[str] = []
    for index, raw in enumerate(raw_updates):
        if not isinstance(raw, dict):
            warnings.append(
                f"Metadata update {index + 1} was not a JSON object."
            )
            continue
        candidate_id = normalize_space(raw.get("id"))
        confidence = normalize_space(
            raw.get("source_confidence")
        ).casefold()
        fields = {
            "primary_theme": normalize_space(raw.get("primary_theme")),
            "source_language": canonical_language(
                raw.get("source_language")
            ),
            "source_period": normalize_space(raw.get("source_period")),
            "source_confidence": confidence,
        }
        if candidate_id not in allowed_ids:
            warnings.append(
                f"Metadata update {index + 1} had an unknown candidate id."
            )
            continue
        if any(not value for value in fields.values()):
            warnings.append(
                f"Metadata update {index + 1} was incomplete."
            )
            continue
        if confidence not in {"high", "medium", "low"}:
            warnings.append(
                f"Metadata update {index + 1} had invalid source confidence."
            )
            continue
        updates[candidate_id] = fields
    if not updates:
        raise DeepSeekError(
            "DeepSeek returned no usable metadata updates."
        )
    return updates, warnings


# ---------------------------------------------------------------------------
# Persistent GitHub state
# ---------------------------------------------------------------------------

class StateStoreError(RuntimeError):
    pass


class StateConflictError(StateStoreError):
    pass


class GitHubStateStore:
    def __init__(self, repository: str, token: str) -> None:
        self.repository = repository
        self.lock = threading.RLock()
        self.headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @property
    def repo_url(self) -> str:
        return f"{GITHUB_API}/repos/{self.repository}"

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        request_headers = dict(self.headers)
        request_headers.update(kwargs.pop("headers", {}))
        try:
            return requests.request(
                method,
                url,
                headers=request_headers,
                timeout=20,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise StateStoreError(f"GitHub state request failed: {exc}") from exc

    def ensure_ready(self) -> None:
        repository = self.request("GET", self.repo_url)
        if repository.status_code != 200:
            raise StateStoreError(
                f"Cannot access GitHub repository ({repository.status_code})."
            )
        default_branch = repository.json()["default_branch"]
        ref = self.request(
            "GET", f"{self.repo_url}/git/ref/heads/{default_branch}"
        )
        if ref.status_code != 200:
            raise StateStoreError("Cannot read the repository's default branch.")
        create = self.request(
            "POST",
            f"{self.repo_url}/git/refs",
            json={
                "ref": f"refs/heads/{STATE_BRANCH}",
                "sha": ref.json()["object"]["sha"],
            },
        )
        if create.status_code not in (201, 422):
            raise StateStoreError(
                f"Cannot create the runtime-state branch ({create.status_code})."
            )
        try:
            self.load()
        except FileNotFoundError:
            self.save(new_state(), sha=None)

    def load(self) -> tuple[dict[str, Any], str | None]:
        response = self.request(
            "GET",
            f"{self.repo_url}/contents/{STATE_PATH}",
            params={"ref": STATE_BRANCH},
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
            },
        )
        if response.status_code == 404:
            raise FileNotFoundError(STATE_PATH)
        if response.status_code != 200:
            raise StateStoreError(f"Cannot load runtime state ({response.status_code}).")
        body = response.json()
        content = base64.b64decode(body["content"]).decode("utf-8")
        return normalize_state(json.loads(content)), body["sha"]

    def save(self, state: dict[str, Any], sha: str | None) -> None:
        state["revision"] = int(state.get("revision", 0)) + 1
        encoded = base64.b64encode(
            json.dumps(state, ensure_ascii=False, indent=2).encode("utf-8")
        ).decode("ascii")
        payload: dict[str, Any] = {
            "message": f"Update li_poster runtime state ({state['revision']})",
            "content": encoded,
            "branch": STATE_BRANCH,
        }
        if sha:
            payload["sha"] = sha
        response = self.request(
            "PUT", f"{self.repo_url}/contents/{STATE_PATH}", json=payload
        )
        if response.status_code in (409, 422):
            raise StateConflictError("Runtime state changed concurrently.")
        if response.status_code not in (200, 201):
            raise StateStoreError(
                f"Cannot save runtime state ({response.status_code})."
            )

    def update(
        self, mutator: Callable[[dict[str, Any]], Any], retries: int = 5
    ) -> Any:
        with self.lock:
            for attempt in range(retries):
                try:
                    state, sha = self.load()
                except FileNotFoundError:
                    state, sha = new_state(), None
                result = mutator(state)
                try:
                    self.save(state, sha)
                    return result
                except StateConflictError:
                    if attempt == retries - 1:
                        raise
            raise StateConflictError("Runtime state update retry limit exceeded.")

    def update_verified(
        self,
        mutator: Callable[[dict[str, Any]], Any],
        verifier: Callable[[dict[str, Any]], bool],
        description: str,
    ) -> tuple[Any, dict[str, Any]]:
        """Write state, then confirm GitHub returns the intended result."""
        result = self.update(mutator)
        last_state: dict[str, Any] | None = None
        for attempt in range(STATE_VERIFY_ATTEMPTS):
            if attempt:
                clock.sleep(0.2 * attempt)
            last_state, _ = self.load()
            if verifier(last_state):
                return result, last_state
        raise StateStoreError(
            f"{description} was sent to GitHub but could not be verified. "
            "Refresh before trying again."
        )


@st.cache_resource
def get_store_v200(repository: str, token: str) -> GitHubStateStore:
    store = GitHubStateStore(repository, token)
    store.ensure_ready()
    return store


# ---------------------------------------------------------------------------
# LinkedIn OAuth and posting
# ---------------------------------------------------------------------------

class LinkedInError(RuntimeError):
    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        ambiguous: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.ambiguous = ambiguous


def linkedin_authorization_url(
    client_id: str, redirect_uri: str, oauth_state: str
) -> str:
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": oauth_state,
            "scope": "openid profile w_member_social",
        }
    )
    return f"{LINKEDIN_AUTHORIZE_URL}?{query}"


def exchange_linkedin_code(
    code: str, client_id: str, client_secret: str, redirect_uri: str
) -> dict[str, Any]:
    try:
        response = requests.post(
            LINKEDIN_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        raise LinkedInError(f"LinkedIn token exchange failed: {exc}") from exc
    if response.status_code != 200:
        raise LinkedInError(
            f"LinkedIn rejected the authorization ({response.status_code}).",
            response.status_code,
        )
    return response.json()


def get_linkedin_userinfo(access_token: str) -> dict[str, Any]:
    try:
        response = requests.get(
            LINKEDIN_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise LinkedInError(f"LinkedIn profile lookup failed: {exc}") from exc
    if response.status_code != 200:
        raise LinkedInError(
            f"LinkedIn profile lookup failed ({response.status_code}).",
            response.status_code,
        )
    return response.json()


def publish_linkedin_post(
    access_token: str,
    person_id: str,
    text: str,
    visibility: str,
) -> str:
    payload = {
        "author": f"urn:li:person:{person_id}",
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": visibility.upper()
        },
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }
    try:
        response = requests.post(
            LINKEDIN_POST_URL, headers=headers, json=payload, timeout=25
        )
    except (requests.Timeout, requests.ConnectionError) as exc:
        raise LinkedInError(
            "The post result is uncertain because LinkedIn did not confirm it.",
            ambiguous=True,
        ) from exc
    except requests.RequestException as exc:
        raise LinkedInError(f"LinkedIn post request failed: {exc}") from exc

    if response.status_code not in (200, 201):
        ambiguous = response.status_code >= 500
        try:
            detail = str(response.json().get("message", ""))[:300]
        except ValueError:
            detail = ""
        message = f"LinkedIn rejected the post ({response.status_code})"
        if detail:
            message += f": {detail}"
        raise LinkedInError(message, response.status_code, ambiguous)
    return response.headers.get("X-RestLi-Id", "")


def create_oauth_link(
    store: GitHubStateStore, client_id: str, redirect_uri: str
) -> str:
    raw_state = secrets.token_urlsafe(32)
    state_hash = hashlib.sha256(raw_state.encode()).hexdigest()

    def save(current: dict[str, Any]) -> None:
        current["oauth"] = {
            "state_hash": state_hash,
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(minutes=10)
            ).isoformat(),
        }

    store.update(save)
    return linkedin_authorization_url(client_id, redirect_uri, raw_state)


def handle_oauth_callback(
    store: GitHubStateStore, config: dict[str, str]
) -> None:
    code = st.query_params.get("code")
    returned_state = st.query_params.get("state")
    error = st.query_params.get("error")
    if not code and not error:
        return
    if error:
        st.query_params.clear()
        st.error(f"LinkedIn authorization was not completed: {error}")
        return

    current, _ = store.load()
    oauth = current.get("oauth", {})
    expected_hash = str(oauth.get("state_hash", ""))
    expires_at = str(oauth.get("expires_at", ""))
    actual_hash = hashlib.sha256(str(returned_state).encode()).hexdigest()
    valid = (
        bool(returned_state)
        and bool(expected_hash)
        and secrets.compare_digest(actual_hash, expected_hash)
        and bool(expires_at)
        and datetime.fromisoformat(expires_at) > datetime.now(timezone.utc)
    )
    if not valid:
        st.query_params.clear()
        st.error("The LinkedIn authorization link is invalid or expired.")
        return

    try:
        token_data = exchange_linkedin_code(
            str(code),
            config["LINKEDIN_CLIENT_ID"],
            config["LINKEDIN_CLIENT_SECRET"],
            config["LINKEDIN_REDIRECT_URI"],
        )
        profile = get_linkedin_userinfo(token_data["access_token"])
        expiry = datetime.now(timezone.utc) + timedelta(
            seconds=int(token_data.get("expires_in", 5_184_000))
        )

        def connect(state: dict[str, Any]) -> None:
            state["linkedin"] = {
                "connected": True,
                "encrypted_access_token": encrypt_value(
                    token_data["access_token"], config["FERNET_KEY"]
                ),
                "expires_at": expiry.isoformat(),
                "person_id": str(profile["sub"]),
                "display_name": str(profile.get("name", "LinkedIn member")),
            }
            state["oauth"] = {}
            append_event(state, "info", "LinkedIn account connected.")

        store.update(connect)
        st.session_state.pop("linkedin_connect_url", None)
        st.query_params.clear()
        st.success("LinkedIn account connected. Sign in to continue.")
    except (LinkedInError, KeyError, ValueError) as exc:
        st.query_params.clear()
        st.error(f"Could not connect LinkedIn: {exc}")


# ---------------------------------------------------------------------------
# Randomized scheduling
# ---------------------------------------------------------------------------

def parse_clock(value: str) -> time:
    hour, minute = (int(part) for part in value.split(":", 1))
    return time(hour, minute)


def random_local_datetime(
    day: date, earliest: time, latest: time, zone: ZoneInfo
) -> datetime:
    start_minute = earliest.hour * 60 + earliest.minute
    end_minute = latest.hour * 60 + latest.minute
    selected = random.SystemRandom().randint(start_minute, end_minute)
    return datetime.combine(
        day, time(selected // 60, selected % 60), tzinfo=zone
    )


def is_spaced(
    candidate: datetime, occupied: list[datetime], minimum_hours: int
) -> bool:
    return all(
        abs((candidate - existing).total_seconds()) >= minimum_hours * 3600
        for existing in occupied
    )


def generate_schedule(
    state: dict[str, Any],
    timezone_name: str,
    now: datetime | None = None,
) -> int:
    now = now or datetime.now(timezone.utc)
    zone = ZoneInfo(timezone_name)
    local_now = now.astimezone(zone)
    settings = state["settings"]
    enabled_collections = {
        canonical_collection(value)
        for value in settings.get("enabled_collections", COLLECTION_KEYS)
    }
    approved = [
        item
        for item in state["sayings"]
        if normalize_bool(item.get("approved"))
        and canonical_collection(item.get("collection")) in enabled_collections
    ]
    if not approved:
        raise ValueError(
            "Approve at least one item in an enabled collection before "
            "generating a schedule."
        )

    earliest = parse_clock(settings["earliest_time"])
    latest = parse_clock(settings["latest_time"])
    if earliest > latest:
        raise ValueError("Earliest posting time must be before latest posting time.")

    allowed = {int(day) for day in settings["allowed_weekdays"]}
    final_day = local_now.date() + timedelta(
        days=int(settings["schedule_horizon_days"])
    )
    eligible_days: list[date] = []
    cursor = local_now.date()
    while cursor <= final_day:
        if cursor.weekday() in allowed:
            eligible_days.append(cursor)
        cursor += timedelta(days=1)

    days_by_week: dict[tuple[int, int], list[date]] = {}
    for eligible_day in eligible_days:
        iso = eligible_day.isocalendar()
        days_by_week.setdefault((iso.year, iso.week), []).append(eligible_day)

    pending = [
        item
        for item in state["queue"]
        if item["status"] in ("queued", "publishing")
    ]
    occupied = [
        datetime.fromisoformat(item["scheduled_for"]) for item in pending
    ]
    recent_window = int(settings["recent_saying_window"])
    completed_times = [
        datetime.fromisoformat(item.get("posted_at", item["scheduled_for"]))
        for item in state["history"]
        if item.get("posted_at") or item.get("scheduled_for")
    ]
    occupied.extend(completed_times[-recent_window:])

    pending_ids = {item["saying_id"] for item in pending}
    history_block_count = min(
        recent_window,
        max(0, len(approved) - 1),
    )
    recent_history = (
        state["history"][-history_block_count:]
        if history_block_count
        else []
    )
    recently_used = set(pending_ids)
    recently_used.update(item["saying_id"] for item in recent_history)

    rng = random.SystemRandom()
    added = 0
    for week_days in days_by_week.values():
        target = rng.randint(
            int(settings["posts_per_week_min"]),
            int(settings["posts_per_week_max"]),
        )
        existing = sum(
            datetime.fromisoformat(item["scheduled_for"])
            .astimezone(zone)
            .date()
            in week_days
            for item in pending
        )
        existing += sum(
            datetime.fromisoformat(item.get("posted_at", item["scheduled_for"]))
            .astimezone(zone)
            .date()
            in week_days
            for item in state["history"]
        )
        needed = max(0, target - existing)
        candidate_days = rng.sample(
            week_days, min(len(week_days), needed * 2 + 1)
        )
        for candidate_day in candidate_days:
            if needed <= 0:
                break
            candidate = random_local_datetime(
                candidate_day, earliest, latest, zone
            )
            if candidate <= local_now:
                continue
            if not is_spaced(
                candidate, occupied, int(settings["min_spacing_hours"])
            ):
                continue
            choices = [
                item for item in approved if item["id"] not in recently_used
            ]
            if not choices:
                # Never create two active queue entries for the same saying.
                # Once the historical rotation is exhausted, reuse is allowed
                # only when that saying is no longer pending.
                choices = [
                    item for item in approved if item["id"] not in pending_ids
                ]
            if not choices:
                break
            weights = settings.get("collection_weights", {})
            choices_by_collection: dict[str, list[dict[str, Any]]] = {}
            for item in choices:
                choices_by_collection.setdefault(
                    canonical_collection(item.get("collection")),
                    [],
                ).append(item)
            available_collections = list(choices_by_collection)
            selected_collection = rng.choices(
                available_collections,
                weights=[
                    max(
                        1,
                        int(
                            weights.get(
                                collection_key,
                                1,
                            )
                        ),
                    )
                    for collection_key in available_collections
                ],
                k=1,
            )[0]
            saying = rng.choice(choices_by_collection[selected_collection])
            queue_record = {
                "id": str(uuid.uuid4()),
                "saying_id": saying["id"],
                "saying_snapshot": copy.deepcopy(saying),
                "collection": saying["collection"],
                "post_text": format_post(saying),
                "scheduled_for": candidate.astimezone(timezone.utc).isoformat(),
                "status": "queued",
                "created_at": now.isoformat(),
                "attempts": 0,
            }
            state["queue"].append(queue_record)
            pending.append(queue_record)
            occupied.append(candidate)
            pending_ids.add(saying["id"])
            recently_used.add(saying["id"])
            needed -= 1
            added += 1
    state["queue"].sort(key=lambda item: item["scheduled_for"])
    return added


def find_due_item(
    state: dict[str, Any], now: datetime | None = None
) -> dict[str, Any] | None:
    now = now or datetime.now(timezone.utc)
    for item in state["queue"]:
        if (
            item["status"] == "queued"
            and datetime.fromisoformat(item["scheduled_for"]) <= now
        ):
            return item
    return None


# ---------------------------------------------------------------------------
# Background posting worker
# ---------------------------------------------------------------------------

class PosterWorker:
    def __init__(
        self,
        store: GitHubStateStore,
        fernet_key: str,
        timezone_name: str,
    ) -> None:
        self.store = store
        self.fernet_key = fernet_key
        self.timezone_name = timezone_name
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.lifecycle_lock = threading.Lock()
        self.started_at = ""
        self.last_tick = ""
        self.last_error = ""

    def start(self) -> "PosterWorker":
        """Start or revive the worker without creating duplicate live threads."""
        with self.lifecycle_lock:
            if self.thread and self.thread.is_alive():
                return self
            restarting = self.thread is not None
            if restarting:
                try:
                    recover_interrupted_posts(self.store)
                except Exception as exc:
                    self.last_error = (
                        "Worker restart recovery check failed: " + str(exc)
                    )
            self.stop_event.clear()
            self.started_at = datetime.now(timezone.utc).isoformat()
            self.thread = threading.Thread(
                target=self.run, name="li-poster-worker", daemon=True
            )
            self.thread.start()
        return self

    def health(self) -> dict[str, Any]:
        alive = bool(self.thread and self.thread.is_alive())
        tick_age_seconds: float | None = None
        if self.last_tick:
            try:
                tick_age_seconds = max(
                    0.0,
                    (
                        datetime.now(timezone.utc)
                        - datetime.fromisoformat(self.last_tick)
                    ).total_seconds(),
                )
            except ValueError:
                tick_age_seconds = None
        starting = alive and not self.last_tick
        stale = (
            not alive
            or (
                tick_age_seconds is not None
                and tick_age_seconds > WORKER_STALE_AFTER_SECONDS
            )
        )
        ready = alive and not starting and not stale and not self.last_error
        return {
            "alive": alive,
            "starting": starting,
            "stale": stale,
            "ready": ready,
            "last_tick": self.last_tick,
            "tick_age_seconds": tick_age_seconds,
            "started_at": self.started_at,
            "last_error": self.last_error,
        }

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.tick()
                self.last_error = ""
            except Exception as exc:
                self.last_error = str(exc)
            self.last_tick = datetime.now(timezone.utc).isoformat()
            self.stop_event.wait(WORKER_INTERVAL_SECONDS)

    def tick(self) -> None:
        state, _ = self.store.load()
        settings = state["settings"]
        linkedin = state["linkedin"]
        if not settings["automation_enabled"] or settings["dry_run"]:
            return
        if not linkedin.get("connected"):
            return
        if linkedin.get("expires_at") and datetime.fromisoformat(
            linkedin["expires_at"]
        ) <= datetime.now(timezone.utc):

            def expire(current: dict[str, Any]) -> None:
                current["linkedin"]["connected"] = False
                current["settings"]["automation_enabled"] = False
                append_event(
                    current,
                    "warning",
                    "LinkedIn token expired; automation paused.",
                )

            self.store.update(expire)
            return

        candidate = find_due_item(state)
        if candidate is None:
            return
        queue_id = candidate["id"]
        claimed: dict[str, Any] = {}

        def claim(current: dict[str, Any]) -> bool:
            item = next(
                (row for row in current["queue"] if row["id"] == queue_id),
                None,
            )
            if not item or item["status"] != "queued":
                return False
            item["status"] = "publishing"
            item["claimed_at"] = datetime.now(timezone.utc).isoformat()
            item["attempts"] = int(item.get("attempts", 0)) + 1
            claimed.update(copy.deepcopy(item))
            append_event(
                current, "info", "Claimed a scheduled post.", queue_id=queue_id
            )
            return True

        if not self.store.update(claim):
            return

        fresh, _ = self.store.load()
        saying = next(
            (
                row
                for row in fresh["sayings"]
                if row["id"] == claimed["saying_id"]
            ),
            None,
        )
        if not saying or not normalize_bool(saying.get("approved")):

            def stop_unapproved(current: dict[str, Any]) -> None:
                item = next(
                    row for row in current["queue"] if row["id"] == queue_id
                )
                item["status"] = "needs_review"
                item["error"] = (
                    "The saying was removed or unapproved after scheduling."
                )
                current["settings"]["automation_enabled"] = False
                append_event(
                    current,
                    "warning",
                    "Automation paused before an unapproved saying could post.",
                    queue_id=queue_id,
                )

            self.store.update(stop_unapproved)
            return
        post_text = ensure_automation_footer(
            claimed.get("post_text") or format_post(saying)
        )
        max_post_chars = int(fresh["settings"].get("max_post_chars", 600))
        if len(post_text) > max_post_chars:

            def stop_oversized(current: dict[str, Any]) -> None:
                item = next(
                    row for row in current["queue"] if row["id"] == queue_id
                )
                item["status"] = "needs_review"
                item["post_text"] = post_text
                item["error"] = (
                    "The formatted post, including its automation disclosure, "
                    f"is {len(post_text)} characters; the configured maximum "
                    f"is {max_post_chars}."
                )
                current["settings"]["automation_enabled"] = False
                append_event(
                    current,
                    "warning",
                    "Automation paused before an oversized post could publish.",
                    queue_id=queue_id,
                    characters=len(post_text),
                )

            self.store.update(stop_oversized)
            return
        try:
            post_id = publish_linkedin_post(
                decrypt_value(
                    fresh["linkedin"]["encrypted_access_token"],
                    self.fernet_key,
                ),
                fresh["linkedin"]["person_id"],
                post_text,
                fresh["settings"]["visibility"],
            )
        except LinkedInError as exc:

            def fail(current: dict[str, Any]) -> None:
                item = next(
                    row for row in current["queue"] if row["id"] == queue_id
                )
                item["status"] = (
                    "needs_review" if exc.ambiguous else "failed"
                )
                item["error"] = str(exc)
                append_event(
                    current,
                    "error",
                    "LinkedIn post was not confirmed.",
                    queue_id=queue_id,
                    ambiguous=exc.ambiguous,
                )

            self.store.update(fail)
            return

        def complete(current: dict[str, Any]) -> None:
            item = next(
                row for row in current["queue"] if row["id"] == queue_id
            )
            item["status"] = "posted"
            item["post_text"] = post_text
            item["posted_at"] = datetime.now(timezone.utc).isoformat()
            item["linkedin_post_id"] = post_id
            current["history"].append(copy.deepcopy(item))
            current["history"] = current["history"][-MAX_HISTORY:]
            active = [
                row for row in current["queue"] if row["status"] != "posted"
            ]
            posted = [
                row for row in current["queue"] if row["status"] == "posted"
            ][-100:]
            current["queue"] = sorted(
                active + posted, key=lambda row: row["scheduled_for"]
            )
            append_event(
                current, "info", "Post published.", queue_id=queue_id
            )
            generate_schedule(current, self.timezone_name)

        self.store.update(complete)


def recover_interrupted_posts(store: GitHubStateStore) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
    current, _ = store.load()
    recoverable = any(
        item.get("status") == "publishing"
        and item.get("claimed_at")
        and datetime.fromisoformat(item["claimed_at"]) < cutoff
        for item in current["queue"]
    )
    if not recoverable:
        return 0

    def recover(state: dict[str, Any]) -> int:
        count = 0
        for item in state["queue"]:
            if item["status"] != "publishing":
                continue
            if datetime.fromisoformat(item["claimed_at"]) < cutoff:
                item["status"] = "needs_review"
                item["error"] = (
                    "The app stopped while publishing. Verify on LinkedIn."
                )
                count += 1
        if count:
            append_event(
                state,
                "warning",
                "Interrupted posts moved to manual review.",
                count=count,
            )
        return count

    return store.update(recover)


@st.cache_resource
def get_worker_v200(
    _store: GitHubStateStore, fernet_key: str, timezone_name: str
) -> PosterWorker:
    recover_interrupted_posts(_store)
    return PosterWorker(_store, fernet_key, timezone_name)


# ---------------------------------------------------------------------------
# Streamlit interface
# ---------------------------------------------------------------------------

def require_login(admin_password: str) -> bool:
    if st.session_state.get("li_poster_authenticated"):
        return True
    st.title("🏛️ li_poster")
    st.caption("Human-reviewed, multi-collection posts for LinkedIn")
    with st.form("admin_login"):
        entered = st.text_input("Admin password", type="password")
        submitted = st.form_submit_button(
            "Open control panel", type="primary"
        )
    if submitted and secrets.compare_digest(entered, admin_password):
        st.session_state["li_poster_authenticated"] = True
        st.rerun()
    if submitted:
        st.error("Incorrect password.")
    return False


def queue_dataframe(
    state: dict[str, Any], timezone_name: str
) -> pd.DataFrame:
    sayings = {item["id"]: item for item in state["sayings"]}
    rows = []
    for item in state["queue"]:
        saying = sayings.get(
            item["saying_id"],
            item.get("saying_snapshot", {}),
        )
        scheduled = pd.Timestamp(item["scheduled_for"]).tz_convert(timezone_name)
        posted_at = ""
        if item.get("posted_at"):
            posted_at = pd.Timestamp(item["posted_at"]).tz_convert(
                timezone_name
            ).strftime("%Y-%m-%d %H:%M:%S %Z")
        rows.append(
            {
                "scheduled": scheduled.strftime("%Y-%m-%d %H:%M %Z"),
                "published": posted_at,
                "status": item["status"],
                "collection": COLLECTION_LABELS.get(
                    canonical_collection(saying.get("collection")),
                    "Unknown",
                ),
                "lead": content_lead(saying) or "Missing content",
                "detail": (
                    saying.get("translation", "")
                    if canonical_collection(saying.get("collection"))
                    == COLLECTION_LATIN
                    else saying.get("body", "")
                ),
                "attribution": saying.get("attribution", ""),
                "characters": len(
                    str(item.get("post_text") or format_post(saying))
                )
                if saying
                else 0,
                "error": item.get("error", ""),
            }
        )
    return pd.DataFrame(rows)


def render_dashboard(
    store: GitHubStateStore,
    state: dict[str, Any],
    worker: PosterWorker,
    timezone_name: str,
) -> None:
    st.header("Dashboard")
    settings = state["settings"]
    linkedin = state["linkedin"]
    queued = sum(row["status"] == "queued" for row in state["queue"])
    attention = sum(
        row["status"] == "needs_review" for row in state["queue"]
    )
    health = worker.health()
    if health["last_error"]:
        worker_label = "Error"
    elif health["ready"]:
        worker_label = "Active"
    elif health["starting"]:
        worker_label = "Starting"
    elif health["alive"]:
        worker_label = "Stale"
    else:
        worker_label = "Stopped"
    columns = st.columns(5)
    columns[0].metric(
        "Automation", "On" if settings["automation_enabled"] else "Paused"
    )
    columns[1].metric(
        "LinkedIn", "Connected" if linkedin["connected"] else "Not connected"
    )
    columns[2].metric("Queued", queued)
    columns[3].metric("Needs review", attention)
    columns[4].metric("Worker", worker_label)

    if settings["dry_run"]:
        st.warning(
            "Dry-run mode is on. Scheduled items will not be published."
        )
    if health["last_error"]:
        st.error(f"Background worker error: {health['last_error']}")
    if health["stale"]:
        st.error(
            "The background worker is not healthy. Keep automation paused, "
            "refresh this page once, and reboot the Streamlit app if the worker "
            "does not return to Active."
        )
    elif health["last_tick"]:
        age = health["tick_age_seconds"]
        age_text = f" approximately {int(age)} second(s) ago" if age is not None else ""
        st.caption(
            f"Background worker last checked at {health['last_tick']}{age_text}. "
            "This is a page snapshot; use Refresh dashboard to update it."
        )
    else:
        st.caption("The background worker is starting.")

    due_items = [
        item
        for item in state["queue"]
        if item["status"] == "queued"
        and datetime.fromisoformat(item["scheduled_for"])
        <= datetime.now(timezone.utc)
    ]
    if (
        due_items
        and settings["automation_enabled"]
        and not settings["dry_run"]
    ):
        oldest_due = min(
            datetime.fromisoformat(item["scheduled_for"]) for item in due_items
        )
        overdue_minutes = int(
            (datetime.now(timezone.utc) - oldest_due).total_seconds() // 60
        )
        message = (
            f"{len(due_items)} queued post(s) are due; the oldest is "
            f"{max(overdue_minutes, 0)} minute(s) overdue."
        )
        if overdue_minutes >= 3:
            st.error(
                message
                + " Pause automation and inspect Activity if this does not clear "
                "after refreshing."
            )
        else:
            st.info(message + " The worker should process it shortly.")

    if st.button("Refresh dashboard", key="refresh_dashboard"):
        worker.start()
        st.rerun()

    st.subheader("Posting queue")
    frame = queue_dataframe(state, timezone_name)
    if frame.empty:
        st.info("No posts are scheduled yet.")
    else:
        st.dataframe(frame, use_container_width=True, hide_index=True)

    review_items = [
        item
        for item in state["queue"]
        if item["status"] in ("needs_review", "failed")
    ]
    if review_items:
        st.subheader("Resolve posting problems")
        saying_lookup = {item["id"]: item for item in state["sayings"]}
        labels = {
            item["id"]: (
                f"{item['status']}: "
                f"{content_lead(saying_lookup.get(item['saying_id'], {})) or item['id']}"
            )
            for item in review_items
        }
        selected_id = st.selectbox(
            "Queue item",
            options=list(labels),
            format_func=lambda value: labels[value],
        )
        checked = st.checkbox(
            "I checked my LinkedIn profile and know whether this item posted."
        )
        left, right = st.columns(2)
        if left.button("Mark as posted", disabled=not checked):

            def mark_posted(current: dict[str, Any]) -> None:
                item = next(
                    row
                    for row in current["queue"]
                    if row["id"] == selected_id
                )
                item["status"] = "posted"
                item["posted_at"] = datetime.now(timezone.utc).isoformat()
                item["resolution"] = "Confirmed manually on LinkedIn."
                current["history"].append(copy.deepcopy(item))
                current["history"] = current["history"][-MAX_HISTORY:]
                append_event(
                    current,
                    "info",
                    "A posting result was confirmed manually.",
                    queue_id=selected_id,
                )

            store.update(mark_posted)
            st.rerun()
        if right.button("Mark as not posted", disabled=not checked):

            def mark_not_posted(current: dict[str, Any]) -> None:
                item = next(
                    row
                    for row in current["queue"]
                    if row["id"] == selected_id
                )
                item["status"] = "dismissed"
                item["resolution"] = "Confirmed manually as not posted."
                append_event(
                    current,
                    "info",
                    "A posting problem was dismissed manually.",
                    queue_id=selected_id,
                )

            store.update(mark_not_posted)
            st.rerun()

    with st.expander("How to use this app"):
        st.markdown(
            """
### Safe first-time workflow

1. Confirm the Dashboard shows **LinkedIn: Connected**, **Automation:
   Paused**, **Worker: Active**, and **Dry-run mode is on**.
2. Open **Content library**. Review the collection-specific text, attribution,
   source information, source URL, and internal note. Approve only entries
   you are comfortable publishing, then select **Save content**. Wait for the
   persistent “saved and verified” confirmation.
3. Optionally use **Import content from CSV**. Imported rows are forced to
   unapproved status.
4. Optionally use the **DeepSeek AI workshop**. Generated and translated
   material is staged separately and can enter the library only as unapproved
   content. AI review is useful editorial assistance, not source verification.
5. Open **Schedule**. Choose the weekly range, allowed days, randomized time
   window, minimum spacing, visibility, enabled collections, collection
   weights, and schedule horizon. Save the settings.
6. While dry-run remains on, select **Fill randomized schedule** and inspect
   every queued item on the Dashboard.
7. If desired, use **LinkedIn and setup → Publish a connections-only test**.
   This is a real immediate post and bypasses dry-run mode.
8. For live operation, return to **Schedule**, turn dry-run off, save, inspect
   the queue again, and only then select **Enable automation**.

### Collections and AI safeguards

- Internal notes and verification status are never included in LinkedIn text.
- Latin posts contain Latin, English translation, and attribution. Physics and
  history posts contain a labelled fact, short context, and source.
- Every immediate and scheduled post ends with the discrete disclosure
  `(Automated post; reviewed before scheduling.)`. The footer is added exactly
  once, counts toward the configured character limit, and is rechecked by the
  worker immediately before publication.
- Removing or unapproving a scheduled item pauses automation before it can
  publish. Cancel and refill the queue after material library changes.
- The scheduler avoids duplicate active queue entries for an item and rotates
  through approved material before reusing older entries.
- Starter physics and history records are unapproved. Their URLs and wording
  are review leads, not a substitute for opening and checking the source.
- Version 2.1 replaces untouched, unapproved commonplace starter rows with
  less-familiar sourced material. Approved, edited, queued, posted, and
  user-created records are preserved.
- Collection weights influence randomized selection; they are not exact quotas.
- DeepSeek requests use the API account configured by `DEEPSEEK_API_KEY` and
  may incur usage charges. The API key is never displayed or written to GitHub
  runtime state.
- Generation requests include a compact copy of the existing library to reduce
  repeats. Local near-duplicate checks can still flag a result after it returns.
- **Required primary theme** makes every result focus on one theme. Optional
  supporting themes are preferences and do not guarantee coverage by themselves.
- Select one explicit **source-language mode**. **One required source
  language** guarantees a single origin language; enter `Arabic` to request
  only Classical Arabic sources. **Balanced coverage** requires at least one
  candidate from each preferred language. **Preferred languages only** does
  not guarantee coverage.
- Balanced mode requires at least as many candidates as listed languages.
  Classical Arabic sources may be medieval rather than ancient; the app allows
  secular pre-modern Arabic intellectual sources through 1500 CE and labels
  the period explicitly.
- DeepSeek structured requests disable model thinking to preserve the generated
  JSON allowance. A truncated, empty, or malformed response is retried once
  with a larger allowance before the app reports an error.
- Candidate generation makes up to three generation attempts to replace
  filtered, duplicate, off-theme, or wrong-language results. If the requested
  total still cannot be reached, valid partial results are staged with a
  visible warning.
- The local secular-language filter checks Latin, translation, attribution, and
  source text. It reports the exact field and matched wording. Internal notes
  are not scanned because they may legitimately describe editorial concerns.
- Older staged candidates are rescanned under the current policy. Conflicting
  wording is marked `reject`. The optional metadata-maintenance action can fill
  missing theme, source period, language, and confidence for up to ten legacy
  candidates per DeepSeek request without changing their wording.
- AI reviews are saved with each staged candidate. A `caution` result requires
  an explicit override before it can be added as unapproved; a `reject` result
  cannot be added. A proposed correction becomes a separate unreviewed
  candidate and never changes the original automatically.
- Check AI-generated Latin and attribution against a reliable edition or other
  authoritative source before approval.

### LinkedIn token renewal

- The LinkedIn access token normally expires after the date shown under
  **LinkedIn and setup**. When it expires, the worker marks LinkedIn as
  disconnected and pauses automation.
- To renew it, keep automation paused, open **LinkedIn and setup**, select
  **Prepare LinkedIn connection**, then **Continue to LinkedIn**, and authorize
  the app again. The new encrypted token replaces the expired one.
- A prepared authorization link expires after ten minutes. Prepare a new link
  if LinkedIn reports an invalid or expired authorization request.

### Troubleshooting

- **App will not finish launching:** use Python 3.12 in Streamlit App settings,
  inspect **Manage app → Logs**, and reboot once after correcting the reported
  issue.
- **LinkedIn is not connected or returns 401:** reconnect it using the renewal
  steps above. Confirm the developer app still has `openid`, `profile`, and
  `w_member_social`.
- **OAuth redirect error:** the LinkedIn developer app and
  `LINKEDIN_REDIRECT_URI` must both use the exact deployed HTTPS URL, including
  the trailing slash when configured that way.
- **GitHub state cannot initialize:** confirm `GITHUB_STATE_TOKEN` has
  read/write Contents access to only the configured repository and has not
  expired.
- **Stored LinkedIn credential cannot be decrypted:** restore the original
  `FERNET_KEY`. If it was intentionally replaced, reconnect LinkedIn to store a
  token encrypted with the new key.
- **DeepSeek 401:** replace an invalid API key. **402:** check the DeepSeek
  balance. **429:** wait and retry. A truncated, empty, or malformed result is
  retried once automatically; if the second attempt fails, request fewer
  candidates.
- **A requested language is missing:** select **One required source language**
  to guarantee one language, or select **Balanced coverage** and request at
  least as many candidates as there are preferred languages.
- **Generation returns fewer candidates:** read the generation notes. The app
  has already tried to replace rejected results and has staged any valid
  partial result. Exact rejection fields and matched policy terms are shown.
- **Posting result is uncertain:** check LinkedIn directly before choosing
  **Mark as posted** or **Mark as not posted**. Do not blindly retry an
  uncertain request.
- **App hibernation or restart:** the external app waker can bring the
  Streamlit process back. Community hosting and wake-up timing are best-effort,
  so scheduled times should be treated as approximate rather than guaranteed
  to the minute.
- **Worker is Starting, Stale, or Stopped:** select **Refresh dashboard** once.
  If the status does not become **Active**, pause automation and use
  **Manage app → Reboot**. The app now revives a stopped cached worker on every
  Streamlit rerun and blocks new automation while worker health is uncertain.
- **A save or cancellation is uncertain:** do not click repeatedly. The app
  now reads the GitHub state back after each critical write and shows a
  persistent confirmation only after the intended result is verified.
- **Changing schedule or content:** pause automation first. Cancel queued
  posts, make and save the changes, then refill and review the schedule.

Keep all secrets in Streamlit Secrets. Never place API keys, GitHub tokens,
LinkedIn secrets, passwords, access tokens, or the Fernet key in GitHub.
"""
        )


def validate_library_records(
    records: list[dict[str, Any]],
    max_post_chars: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    normalized: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: dict[str, int] = {}
    for index, raw in enumerate(records):
        record = normalize_saying(raw)
        required = (
            ("latin", "translation", "attribution")
            if record["collection"] == COLLECTION_LATIN
            else ("lead", "body", "attribution", "source_title")
        )
        missing = [field for field in required if not record[field]]
        if missing:
            errors.append(
                f"Row {index + 1} is missing: {', '.join(missing)}."
            )
        length = len(format_post(record))
        if length > int(max_post_chars):
            errors.append(
                f"Row {index + 1} is {length} characters; the maximum is "
                f"{max_post_chars}."
            )
        policy_hits = religious_language_hits(record)
        if policy_hits:
            errors.append(
                f"Row {index + 1} conflicts with the secular wording policy: "
                + "; ".join(policy_hits)
                + "."
            )
        fingerprint = saying_fingerprint(record)
        if fingerprint in seen:
            errors.append(
                f"Rows {seen[fingerprint]} and {index + 1} duplicate the "
                "same collection, lead text, and attribution."
            )
        else:
            seen[fingerprint] = index + 1
        normalized.append(record)
    return normalized, errors


def add_unapproved_records(
    current: dict[str, Any],
    records: list[dict[str, Any]],
    event_message: str,
) -> tuple[int, int]:
    fingerprints = {
        saying_fingerprint(item) for item in current["sayings"]
    }
    added = 0
    duplicates = 0
    for raw in records:
        record = normalize_saying(raw)
        record["id"] = (
            record["id"]
            if record["id"]
            and all(
                existing["id"] != record["id"]
                for existing in current["sayings"]
            )
            else secrets.token_hex(8)
        )
        record["approved"] = False
        fingerprint = saying_fingerprint(record)
        near_match = near_duplicate_match(record, current["sayings"])
        if fingerprint in fingerprints or near_match:
            duplicates += 1
            continue
        current["sayings"].append(record)
        fingerprints.add(fingerprint)
        added += 1
    append_event(
        current,
        "info",
        event_message,
        added=added,
        duplicates_skipped=duplicates,
    )
    return added, duplicates


def stage_ai_candidates(
    current: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> tuple[int, int, int]:
    fingerprints = {
        saying_fingerprint(item)
        for item in current["sayings"] + current["ai_candidates"]
    }
    added = 0
    duplicates = 0
    warnings = 0
    for raw in candidates:
        candidate = normalize_saying(
            raw,
            default_origin="DeepSeek candidate",
        )
        policy_hits = religious_language_hits(candidate)
        if policy_hits:
            candidate["policy_warning"] = (
                "Excluded religious or theological wording detected: "
                + "; ".join(policy_hits)
                + "."
            )
            candidate["review_status"] = "reject"
        fingerprint = saying_fingerprint(candidate)
        if fingerprint in fingerprints:
            duplicates += 1
            continue
        near_match = near_duplicate_match(
            candidate,
            current["sayings"] + current["ai_candidates"],
        )
        if near_match:
            existing, reason = near_match
            if reason == "same normalized Latin text":
                duplicates += 1
                continue
            candidate["duplicate_warning"] = (
                f"Possible duplicate of “{content_lead(existing)}” "
                f"({existing['attribution']}): {reason}."
            )
            if candidate["review_status"] != "reject":
                candidate["review_status"] = "caution"
            warnings += 1
        current["ai_candidates"].append(candidate)
        fingerprints.add(fingerprint)
        added += 1
    current["ai_candidates"] = current["ai_candidates"][
        -MAX_AI_CANDIDATES:
    ]
    append_event(
        current,
        "info",
        "DeepSeek candidates staged for human review.",
        added=added,
        duplicates_skipped=duplicates,
        near_duplicate_warnings=warnings,
    )
    return added, duplicates, warnings


def render_sayings(
    store: GitHubStateStore,
    state: dict[str, Any],
    config: dict[str, str],
) -> None:
    st.header("Content library")
    st.caption(
        "Latin sayings, physics facts, and history facts share one reviewed "
        "library. Only approved entries can be scheduled."
    )
    notice = st.session_state.pop("sayings_notice", "")
    if notice:
        st.success(notice)
    warning_notice = st.session_state.pop("sayings_warning", "")
    if warning_notice:
        st.warning(warning_notice)

    display_columns = ["id", *SAYING_FIELDS]
    editor = pd.DataFrame(state["sayings"])[display_columns]
    edited = st.data_editor(
        editor,
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "id": None,
            "approved": st.column_config.CheckboxColumn("approved"),
            "collection": st.column_config.SelectboxColumn(
                "collection",
                options=COLLECTION_KEYS,
                required=True,
            ),
            "lead": st.column_config.TextColumn(
                "fact / lead",
                help="Required for physics and history; blank for Latin sayings.",
            ),
            "body": st.column_config.TextColumn(
                "explanation / context",
                help="Required for physics and history; blank for Latin sayings.",
            ),
            "latin": st.column_config.TextColumn(
                "Latin",
                help="Required only for Latin sayings.",
            ),
            "translation": st.column_config.TextColumn(
                "English translation",
                help="Required only for Latin sayings.",
            ),
            "source_url": st.column_config.LinkColumn("source URL"),
            "note": st.column_config.TextColumn(
                "internal note",
                help="Internal only; this text is never included in a post.",
            ),
        },
        key=f"sayings_editor_{state['revision']}",
    )
    persisted_approved_count = sum(
        normalize_bool(item.get("approved")) for item in state["sayings"]
    )
    editor_approved_count = sum(
        normalize_bool(value) for value in edited["approved"].tolist()
    )
    if editor_approved_count != persisted_approved_count:
        st.info(
            f"Unsaved approval changes: the editor currently selects "
            f"{editor_approved_count}, while GitHub has "
            f"{persisted_approved_count} saved."
        )
    left, right = st.columns(2)
    if left.button("Save content", type="primary"):
        raw_records = edited.fillna("").to_dict("records")
        records, errors = validate_library_records(
            raw_records,
            int(state["settings"]["max_post_chars"]),
        )
        if errors:
            st.error("\n".join(errors))
        else:

            def save(current: dict[str, Any]) -> None:
                current["sayings"] = records
                append_event(
                    current,
                    "info",
                    "Content library updated.",
                    count=len(records),
                )

            expected_approvals = {
                record["id"]: normalize_bool(record.get("approved"))
                for record in records
            }

            def sayings_saved(current: dict[str, Any]) -> bool:
                persisted = {
                    record["id"]: normalize_bool(record.get("approved"))
                    for record in current["sayings"]
                }
                return (
                    len(current["sayings"]) == len(records)
                    and persisted == expected_approvals
                )

            try:
                store.update_verified(
                    save,
                    sayings_saved,
                    "The content library update",
                )
            except StateStoreError as exc:
                st.error(str(exc))
            else:
                saved_count = sum(expected_approvals.values())
                st.session_state["sayings_notice"] = (
                    f"Content saved and verified: {saved_count} of "
                    f"{len(records)} approved."
                )
                st.rerun()

    right.download_button(
        "Download content CSV",
        edited.to_csv(index=False).encode("utf-8"),
        "li_poster_content.csv",
        "text/csv",
    )

    st.caption(
        f"{persisted_approved_count} of {len(state['sayings'])} items are "
        "approved in GitHub state. "
        + " · ".join(
            f"{COLLECTION_LABELS[key]}: "
            f"{sum(canonical_collection(item.get('collection')) == key for item in state['sayings'])}"
            for key in COLLECTION_KEYS
        )
    )

    with st.expander("Import content from CSV"):
        st.write(
            "Upload a UTF-8 CSV using the downloaded schema. Latin rows need "
            "`latin`, `translation`, and `attribution`; fact rows need "
            "`collection`, `lead`, `body`, `attribution`, and `source_title`. "
            "Imported rows are always unapproved."
        )
        upload = st.file_uploader(
            "Content CSV",
            type=["csv"],
            key="sayings_csv_upload",
        )
        if upload is not None and st.button("Import CSV as unapproved"):
            try:
                frame = pd.read_csv(upload, dtype=str).fillna("")
                missing_columns = [
                    field
                    for field in ("collection", "attribution")
                    if field not in frame.columns
                ]
                if missing_columns:
                    raise ValueError(
                        "Missing CSV columns: "
                        + ", ".join(missing_columns)
                    )
                records = frame.to_dict("records")
                normalized, errors = validate_library_records(
                    records,
                    int(state["settings"]["max_post_chars"]),
                )
                if errors:
                    raise ValueError("\n".join(errors))
                added, duplicates = store.update(
                    lambda current: add_unapproved_records(
                        current,
                        normalized,
                        "Content imported from CSV.",
                    )
                )
                st.session_state["sayings_notice"] = (
                    f"Imported {added} item(s); skipped "
                    f"{duplicates} duplicate(s)."
                )
                st.rerun()
            except (ValueError, pd.errors.ParserError) as exc:
                st.error(f"CSV import failed: {exc}")

    with st.expander("DeepSeek AI workshop"):
        model = (
            config.get("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL)
            or DEFAULT_DEEPSEEK_MODEL
        )
        api_key = config.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            st.warning(
                "AI tools are disabled. Add DEEPSEEK_API_KEY to Streamlit "
                "Secrets and allow the app to restart."
            )
        else:
            st.caption(
                f"Model: {model}. Each request uses your DeepSeek API account. "
                "AI output is never approved, scheduled, or published automatically."
            )
            generate_tab, translate_tab, review_tab = st.tabs(
                ["Generate content", "Translate into Latin", "Review candidate"]
            )
            with generate_tab:
                with st.form("deepseek_generate_form"):
                    generation_collection = st.selectbox(
                        "Collection",
                        options=COLLECTION_KEYS,
                        format_func=lambda value: COLLECTION_LABELS[value],
                    )
                    quantity = st.number_input(
                        "Number of candidates",
                        min_value=1,
                        max_value=10,
                        value=4,
                    )
                    required_theme = st.text_input(
                        "Required primary theme (optional)",
                        placeholder="For example: science",
                        help=(
                            "When supplied, every returned candidate must be "
                            "labelled with this primary theme."
                        ),
                    )
                    themes = st.text_input(
                        "Optional supporting themes",
                        value=(
                            "science, observation, nature, mathematics, "
                            "medicine"
                        ),
                    )
                    source_mode = st.selectbox(
                        "Source-language mode",
                        options=SOURCE_MODES,
                        index=1,
                        help=(
                            "Choose one required language, balanced coverage "
                            "across the preferred list, or non-guaranteed "
                            "language preferences."
                        ),
                    )
                    required_source = st.text_input(
                        "Required source language (optional)",
                        placeholder="For example: Arabic",
                        help=(
                            "Used only with “One required source language”. "
                            "Enter Arabic to guarantee Arabic-source "
                            "candidates."
                        ),
                    )
                    sources = st.text_input(
                        "Preferred source languages",
                        value=(
                            "Latin, Ancient Greek, Classical Chinese, Arabic"
                        ),
                        help=(
                            "Used by balanced and preferences-only source "
                            "modes."
                        ),
                    )
                    if generation_collection != COLLECTION_LATIN:
                        st.caption(
                            "For fact collections, DeepSeek uses authoritative "
                            "source requirements; the source-language controls "
                            "above are ignored."
                        )
                    generate = st.form_submit_button(
                        "Ask DeepSeek for candidates",
                        type="primary",
                    )
                if generate:
                    try:
                        with st.spinner("DeepSeek is preparing candidates..."):
                            if generation_collection == COLLECTION_LATIN:
                                candidates, warnings = generate_deepseek_sayings(
                                    api_key,
                                    model,
                                    int(quantity),
                                    required_theme,
                                    themes,
                                    required_source,
                                    sources,
                                    source_mode,
                                    state["sayings"] + state["ai_candidates"],
                                )
                            else:
                                candidates, warnings = generate_deepseek_facts(
                                    api_key,
                                    model,
                                    generation_collection,
                                    int(quantity),
                                    required_theme,
                                    themes,
                                    state["sayings"] + state["ai_candidates"],
                                )
                        added, duplicates, near_warnings = store.update(
                            lambda current: stage_ai_candidates(
                                current,
                                candidates,
                            )
                        )
                        message = (
                            f"Staged {added} candidate(s); skipped "
                            f"{duplicates} duplicate(s)."
                        )
                        if near_warnings:
                            message += (
                                f" Flagged {near_warnings} possible near-"
                                "duplicate(s)."
                            )
                        if warnings:
                            st.session_state["sayings_warning"] = (
                                "DeepSeek generation notes:\n\n- "
                                + "\n- ".join(warnings)
                            )
                        st.session_state["sayings_notice"] = message
                        st.rerun()
                    except DeepSeekError as exc:
                        st.error(str(exc))

            with translate_tab:
                with st.form("deepseek_translate_form"):
                    source_text = st.text_area(
                        "Text to translate into Latin",
                        max_chars=4000,
                    )
                    source_language = st.text_input(
                        "Source language",
                        value="English",
                    )
                    supplied_attribution = st.text_input(
                        "Attribution",
                        help=(
                            "Use an accurate source. Leave blank to label the "
                            "result as user-supplied text."
                        ),
                    )
                    translate = st.form_submit_button(
                        "Ask DeepSeek to translate",
                        type="primary",
                    )
                if translate:
                    try:
                        with st.spinner("DeepSeek is translating..."):
                            candidate = translate_with_deepseek(
                                api_key,
                                model,
                                source_text,
                                source_language,
                                supplied_attribution,
                            )
                        added, duplicates, near_warnings = store.update(
                            lambda current: stage_ai_candidates(
                                current,
                                [candidate],
                            )
                        )
                        st.session_state["sayings_notice"] = (
                            f"Staged {added} translation candidate(s); skipped "
                            f"{duplicates} duplicate(s)."
                        )
                        if near_warnings:
                            st.session_state["sayings_notice"] += (
                                f" Flagged {near_warnings} possible "
                                "near-duplicate(s)."
                            )
                        st.rerun()
                    except (DeepSeekError, ValueError) as exc:
                        st.error(str(exc))

            with review_tab:
                candidates = state["ai_candidates"]
                if not candidates:
                    st.info("There are no staged AI candidates to review.")
                else:
                    labels = {
                        item["id"]: (
                            f"{COLLECTION_LABELS[item['collection']]}: "
                            f"{content_lead(item)} — {item['attribution']}"
                        )
                        for item in candidates
                    }
                    selected_id = st.selectbox(
                        "Candidate",
                        options=list(labels),
                        format_func=lambda value: labels[value],
                    )
                    selected = next(
                        item
                        for item in candidates
                        if item["id"] == selected_id
                    )
                    if st.button("Ask DeepSeek to review this candidate"):
                        try:
                            with st.spinner("DeepSeek is reviewing..."):
                                review_result = review_with_deepseek(
                                    api_key,
                                    model,
                                    selected,
                                )
                            def persist_review(
                                current: dict[str, Any]
                            ) -> None:
                                candidate = next(
                                    item
                                    for item in current["ai_candidates"]
                                    if item["id"] == selected_id
                                )
                                candidate["ai_review"] = review_result
                                candidate["reviewed_at"] = datetime.now(
                                    timezone.utc
                                ).isoformat()
                                candidate["review_model"] = model
                                effective_status = review_result["overall"]
                                if (
                                    candidate.get("duplicate_warning")
                                    and effective_status == "pass"
                                ):
                                    effective_status = "caution"
                                candidate["review_status"] = effective_status
                                append_event(
                                    current,
                                    "info",
                                    "DeepSeek candidate review saved.",
                                    candidate_id=selected_id,
                                    status=effective_status,
                                    model=model,
                                )

                            store.update(persist_review)
                            st.rerun()
                        except DeepSeekError as exc:
                            st.error(str(exc))
                    review = selected.get("ai_review") or {}
                    if review:
                        st.markdown(
                            f"**Saved review status:** "
                            f"`{selected.get('review_status', 'unreviewed')}`"
                        )
                        st.json(review)
                        st.caption(
                            "This is an AI assessment, not independent source verification."
                        )
                        corrected_latin = normalize_space(
                            review.get("corrected_latin")
                        )
                        if (
                            corrected_latin
                            and latin_search_key(corrected_latin)
                            != latin_search_key(selected["latin"])
                        ):
                            st.info(
                                "The review proposed corrected wording. "
                                "Staging it creates a new unreviewed candidate; "
                                "it does not alter or approve the original."
                            )
                            if st.button(
                                "Stage the reviewed correction",
                                key=f"stage_correction_{selected_id}",
                            ):
                                corrected_raw = {
                                    **selected,
                                    "id": f"ai-{secrets.token_hex(8)}",
                                    "approved": False,
                                    "latin": corrected_latin,
                                    "translation": normalize_space(
                                        review.get("corrected_translation")
                                    )
                                    or selected["translation"],
                                    "attribution": normalize_space(
                                        review.get("corrected_attribution")
                                    )
                                    or selected["attribution"],
                                    "latin_kind": normalize_space(
                                        review.get("corrected_latin_kind")
                                    )
                                    or selected["latin_kind"],
                                    "source_language": normalize_space(
                                        review.get(
                                            "corrected_source_language"
                                        )
                                    )
                                    or selected["source_language"],
                                    "source_period": normalize_space(
                                        review.get(
                                            "corrected_source_period"
                                        )
                                    )
                                    or selected.get(
                                        "source_period", "unknown"
                                    ),
                                    "source_confidence": normalize_space(
                                        review.get(
                                            "corrected_source_confidence"
                                        )
                                    )
                                    or selected.get(
                                        "source_confidence", "unverified"
                                    ),
                                    "origin": (
                                        f"DeepSeek reviewed correction ({model})"
                                    ),
                                    "verification_status": (
                                        "AI-corrected candidate; human "
                                        "verification required"
                                    ),
                                    "note": normalize_space(
                                        review.get("correction_reason")
                                    )
                                    or "Correction suggested by AI review.",
                                    "review_status": "unreviewed",
                                    "ai_review": {},
                                    "reviewed_at": "",
                                    "review_model": "",
                                    "duplicate_warning": "",
                                    "policy_warning": "",
                                    "secular": True,
                                }
                                try:
                                    corrected = validate_ai_candidate(
                                        corrected_raw,
                                        origin=corrected_raw["origin"],
                                    )
                                    (
                                        added,
                                        duplicates,
                                        near_warnings,
                                    ) = store.update(
                                        lambda current: stage_ai_candidates(
                                            current,
                                            [corrected],
                                        )
                                    )
                                    st.session_state["sayings_notice"] = (
                                        f"Staged {added} corrected candidate; "
                                        f"skipped {duplicates} exact duplicate."
                                    )
                                    if near_warnings:
                                        st.session_state[
                                            "sayings_notice"
                                        ] += (
                                            " The correction was flagged as "
                                            "a possible near-duplicate."
                                        )
                                    st.rerun()
                                except ValueError as exc:
                                    st.error(
                                        f"Could not stage correction: {exc}"
                                    )

        candidates = state["ai_candidates"]
        st.subheader(f"Staged AI candidates ({len(candidates)})")
        if candidates:
            candidate_rows = []
            for item in candidates:
                candidate_rows.append(
                    {
                        "add": False,
                        "id": item["id"],
                        "collection": item["collection"],
                        "review_status": item.get(
                            "review_status", "unreviewed"
                        ),
                        "source_confidence": item.get(
                            "source_confidence", "unverified"
                        ),
                        "duplicate_warning": item.get(
                            "duplicate_warning", ""
                        ),
                        "policy_warning": item.get(
                            "policy_warning", ""
                        ),
                        "lead": item.get("lead", ""),
                        "body": item.get("body", ""),
                        "latin": item["latin"],
                        "translation": item["translation"],
                        "primary_theme": item.get("primary_theme", ""),
                        "source_language": item["source_language"],
                        "source_period": item.get(
                            "source_period", "unknown"
                        ),
                        "attribution": item["attribution"],
                        "source_title": item.get("source_title", ""),
                        "source_url": item.get("source_url", ""),
                        "latin_kind": item["latin_kind"],
                        "source_text": item["source_text"],
                        "reviewed_at": item.get("reviewed_at", ""),
                        "note": item["note"],
                    }
                )
            candidate_editor = st.data_editor(
                pd.DataFrame(candidate_rows),
                hide_index=True,
                use_container_width=True,
                column_config={
                    "id": None,
                    "add": st.column_config.CheckboxColumn(
                        "add to library"
                    ),
                    "collection": st.column_config.TextColumn("collection"),
                    "source_url": st.column_config.LinkColumn("source URL"),
                },
                disabled=[
                    "collection",
                    "lead",
                    "body",
                    "latin",
                    "translation",
                    "primary_theme",
                    "source_confidence",
                    "attribution",
                    "source_title",
                    "source_url",
                    "latin_kind",
                    "source_language",
                    "source_period",
                    "source_text",
                    "review_status",
                    "duplicate_warning",
                    "policy_warning",
                    "reviewed_at",
                    "note",
                ],
                key=f"ai_candidate_editor_{state['revision']}",
            )
            pending_metadata_count = sum(
                (
                    not normalize_space(item.get("primary_theme"))
                    or normalize_space(
                        item.get("source_period")
                    ).casefold()
                    in {"", "unknown"}
                    or normalize_space(
                        item.get("source_confidence")
                    ).casefold()
                    in {"", "unknown", "unverified"}
                )
                for item in candidates
            )
            if pending_metadata_count:
                with st.expander("Legacy candidate metadata maintenance"):
                    st.write(
                        f"{pending_metadata_count} staged candidate(s) have "
                        "missing or unverified v1.3 metadata. One request "
                        f"updates at most {MAX_METADATA_BACKFILL} candidates. "
                        "Wording and attribution are not changed."
                    )
                    confirm_backfill = st.checkbox(
                        "I understand this uses my DeepSeek API account.",
                        key="confirm_metadata_backfill",
                    )
                    if st.button(
                        "Backfill missing metadata",
                        disabled=not confirm_backfill or not bool(api_key),
                    ):
                        try:
                            with st.spinner(
                                "DeepSeek is preparing metadata..."
                            ):
                                updates, metadata_warnings = (
                                    backfill_candidate_metadata_with_deepseek(
                                        api_key,
                                        model,
                                        candidates,
                                    )
                                )

                            def persist_metadata(
                                current: dict[str, Any],
                            ) -> int:
                                updated = 0
                                for item in current["ai_candidates"]:
                                    fields = updates.get(item["id"])
                                    if not fields:
                                        continue
                                    if not normalize_space(
                                        item.get("primary_theme")
                                    ):
                                        item["primary_theme"] = fields[
                                            "primary_theme"
                                        ]
                                    if normalize_space(
                                        item.get("source_language")
                                    ).casefold() in {"", "unknown"}:
                                        item["source_language"] = fields[
                                            "source_language"
                                        ]
                                    if normalize_space(
                                        item.get("source_period")
                                    ).casefold() in {"", "unknown"}:
                                        item["source_period"] = fields[
                                            "source_period"
                                        ]
                                    if normalize_space(
                                        item.get("source_confidence")
                                    ).casefold() in {
                                        "",
                                        "unknown",
                                        "unverified",
                                    }:
                                        item["source_confidence"] = fields[
                                            "source_confidence"
                                        ]
                                    if (
                                        fields["source_confidence"] == "low"
                                        and item.get("review_status")
                                        not in {"reject", "caution"}
                                    ):
                                        item["review_status"] = "caution"
                                    updated += 1
                                append_event(
                                    current,
                                    "info",
                                    "Legacy AI candidate metadata backfilled.",
                                    updated=updated,
                                    model=model,
                                )
                                return updated

                            updated = store.update(persist_metadata)
                            st.session_state["sayings_notice"] = (
                                f"Backfilled metadata for {updated} staged "
                                "candidate(s)."
                            )
                            if metadata_warnings:
                                st.session_state["sayings_warning"] = (
                                    "Metadata backfill notes:\n\n- "
                                    + "\n- ".join(metadata_warnings)
                                )
                            st.rerun()
                        except DeepSeekError as exc:
                            st.error(str(exc))
            left, right = st.columns(2)
            allow_caution = left.checkbox(
                "Allow adding selected caution candidates",
                help=(
                    "Caution candidates remain unapproved in the library and "
                    "still require human verification before approval."
                ),
                key="allow_caution_candidates",
            )
            if left.button("Add selected candidates as unapproved"):
                selected_ids = set(
                    candidate_editor.loc[
                        candidate_editor["add"] == True, "id"  # noqa: E712
                    ].tolist()
                )
                if not selected_ids:
                    st.error("Select at least one candidate.")
                else:
                    selected_candidates = [
                        item
                        for item in candidates
                        if item["id"] in selected_ids
                    ]
                    rejected = [
                        item
                        for item in selected_candidates
                        if item.get("review_status") == "reject"
                    ]
                    cautions = [
                        item
                        for item in selected_candidates
                        if item.get("review_status") == "caution"
                    ]
                    if rejected:
                        st.error(
                            "Rejected candidates cannot be added. Clear them "
                            "or stage a reviewed correction."
                        )
                        st.stop()
                    if cautions and not allow_caution:
                        st.error(
                            "At least one selected candidate has caution "
                            "status. Enable the explicit caution override or "
                            "deselect it."
                        )
                        st.stop()

                    def accept(current: dict[str, Any]) -> tuple[int, int]:
                        selected = [
                            item
                            for item in current["ai_candidates"]
                            if item["id"] in selected_ids
                        ]
                        result = add_unapproved_records(
                            current,
                            selected,
                            "AI candidates added to the sayings library.",
                        )
                        library_ids = {
                            item["id"] for item in current["sayings"]
                        }
                        current["ai_candidates"] = [
                            item
                            for item in current["ai_candidates"]
                            if item["id"] not in library_ids
                        ]
                        return result

                    added, duplicates = store.update(accept)
                    st.session_state["sayings_notice"] = (
                        f"Added {added} unapproved candidate(s); skipped "
                        f"{duplicates} duplicate(s)."
                    )
                    st.rerun()
            confirm_clear = right.checkbox(
                "Allow clearing all staged candidates",
                key="confirm_clear_ai_candidates",
            )
            if right.button(
                "Clear staged candidates",
                disabled=not confirm_clear,
            ):

                def clear(current: dict[str, Any]) -> None:
                    count = len(current["ai_candidates"])
                    current["ai_candidates"] = []
                    append_event(
                        current,
                        "warning",
                        "Staged AI candidates cleared.",
                        count=count,
                    )

                store.update(clear)
                st.rerun()
        else:
            st.info("No AI candidates are currently staged.")


def render_schedule(
    store: GitHubStateStore,
    state: dict[str, Any],
    timezone_name: str,
    worker: PosterWorker,
) -> None:
    st.header("Schedule")
    notice = st.session_state.pop("schedule_notice", "")
    if notice:
        st.success(notice)
    warning_notice = st.session_state.pop("schedule_warning", "")
    if warning_notice:
        st.warning(warning_notice)
    settings = state["settings"]
    approved_count = sum(
        normalize_bool(item.get("approved")) for item in state["sayings"]
    )
    approved_by_collection = {
        key: sum(
            normalize_bool(item.get("approved"))
            and canonical_collection(item.get("collection")) == key
            for item in state["sayings"]
        )
        for key in COLLECTION_KEYS
    }
    active_unique = {
        item["saying_id"]
        for item in state["queue"]
        if item["status"] in ("queued", "publishing")
    }
    st.caption(
        f"{approved_count} approved item(s); "
        f"{len(active_unique)} unique item(s) currently active in the queue. "
        + " · ".join(
            f"{COLLECTION_LABELS[key]}: {approved_by_collection[key]}"
            for key in COLLECTION_KEYS
        )
    )
    if approved_count < 5:
        st.warning(
            "Approve more content before building a multi-week schedule. "
            "The scheduler will not place duplicate copies of an item in the "
            "active queue."
        )
    with st.form("schedule_settings"):
        left, right = st.columns(2)
        minimum = left.number_input(
            "Minimum posts per week",
            min_value=1,
            max_value=14,
            value=int(settings["posts_per_week_min"]),
        )
        maximum = right.number_input(
            "Maximum posts per week",
            min_value=1,
            max_value=14,
            value=int(settings["posts_per_week_max"]),
        )
        selected_days = st.multiselect(
            "Posting days",
            WEEKDAYS,
            default=[
                WEEKDAYS[index] for index in settings["allowed_weekdays"]
            ],
        )
        earliest = left.time_input(
            "Earliest posting time",
            datetime.strptime(settings["earliest_time"], "%H:%M").time(),
        )
        latest = right.time_input(
            "Latest posting time",
            datetime.strptime(settings["latest_time"], "%H:%M").time(),
        )
        horizon = left.number_input(
            "Schedule horizon in days",
            min_value=7,
            max_value=60,
            value=int(settings["schedule_horizon_days"]),
        )
        spacing = right.number_input(
            "Minimum spacing in hours",
            min_value=1,
            max_value=168,
            value=int(settings["min_spacing_hours"]),
        )
        maximum_characters = left.number_input(
            "Maximum post characters",
            min_value=100,
            max_value=3000,
            value=int(settings["max_post_chars"]),
        )
        visibility = right.selectbox(
            "Post visibility",
            ["PUBLIC", "CONNECTIONS"],
            index=0 if settings["visibility"] == "PUBLIC" else 1,
        )
        enabled_collections = st.multiselect(
            "Enabled collections",
            options=COLLECTION_KEYS,
            default=settings.get("enabled_collections", COLLECTION_KEYS),
            format_func=lambda value: COLLECTION_LABELS[value],
            help="Only approved content from these collections can be queued.",
        )
        st.caption(
            "Collection weights influence the mix when more than one "
            "collection is enabled; they do not guarantee exact quotas."
        )
        weight_columns = st.columns(3)
        collection_weights: dict[str, int] = {}
        saved_weights = settings.get("collection_weights", {})
        for index, collection_key in enumerate(COLLECTION_KEYS):
            collection_weights[collection_key] = int(
                weight_columns[index].number_input(
                    f"{COLLECTION_LABELS[collection_key]} weight",
                    min_value=1,
                    max_value=10,
                    value=max(1, int(saved_weights.get(collection_key, 1))),
                )
            )
        dry_run = st.toggle(
            "Dry-run mode", value=bool(settings["dry_run"])
        )
        submitted = st.form_submit_button(
            "Save schedule settings", type="primary"
        )

    if submitted:
        errors = []
        if settings["automation_enabled"]:
            errors.append("Pause automation before changing schedule settings.")
        if minimum > maximum:
            errors.append("Minimum posts cannot exceed maximum posts.")
        if not selected_days:
            errors.append("Choose at least one posting day.")
        if not enabled_collections:
            errors.append("Enable at least one content collection.")
        if earliest > latest:
            errors.append("Earliest time must be before latest time.")
        if errors:
            st.error("\n".join(errors))
        else:

            def save(current: dict[str, Any]) -> None:
                current["settings"].update(
                    {
                        "posts_per_week_min": int(minimum),
                        "posts_per_week_max": int(maximum),
                        "allowed_weekdays": [
                            WEEKDAYS.index(day) for day in selected_days
                        ],
                        "earliest_time": earliest.strftime("%H:%M"),
                        "latest_time": latest.strftime("%H:%M"),
                        "schedule_horizon_days": int(horizon),
                        "min_spacing_hours": int(spacing),
                        "max_post_chars": int(maximum_characters),
                        "visibility": visibility,
                        "dry_run": bool(dry_run),
                        "enabled_collections": list(enabled_collections),
                        "collection_weights": collection_weights,
                    }
                )
                append_event(current, "info", "Schedule settings updated.")

            expected_settings = {
                "posts_per_week_min": int(minimum),
                "posts_per_week_max": int(maximum),
                "allowed_weekdays": [
                    WEEKDAYS.index(day) for day in selected_days
                ],
                "earliest_time": earliest.strftime("%H:%M"),
                "latest_time": latest.strftime("%H:%M"),
                "schedule_horizon_days": int(horizon),
                "min_spacing_hours": int(spacing),
                "max_post_chars": int(maximum_characters),
                "visibility": visibility,
                "dry_run": bool(dry_run),
                "enabled_collections": list(enabled_collections),
                "collection_weights": collection_weights,
            }

            def settings_saved(current: dict[str, Any]) -> bool:
                return all(
                    current["settings"].get(key) == value
                    for key, value in expected_settings.items()
                )

            try:
                store.update_verified(
                    save,
                    settings_saved,
                    "The schedule settings update",
                )
            except StateStoreError as exc:
                st.error(str(exc))
            else:
                st.session_state["schedule_notice"] = (
                    "Schedule settings saved and verified."
                )
                st.rerun()

    automation_enabled = bool(settings["automation_enabled"])
    left, right = st.columns(2)
    if automation_enabled:
        st.info(
            "Pause automation before refilling or changing the active queue. "
            "Pausing does not cancel already queued posts."
        )
    if left.button(
        "Fill randomized schedule",
        type="primary",
        disabled=automation_enabled,
    ):
        before_ids = {item["id"] for item in state["queue"]}
        added_holder: dict[str, int] = {"count": 0}

        def fill_schedule(current: dict[str, Any]) -> int:
            added_holder["count"] = generate_schedule(current, timezone_name)
            return added_holder["count"]

        def schedule_saved(current: dict[str, Any]) -> bool:
            new_ids = {
                item["id"]
                for item in current["queue"]
                if item["id"] not in before_ids
            }
            return len(new_ids) >= added_holder["count"]

        try:
            added, _ = store.update_verified(
                fill_schedule,
                schedule_saved,
                "The randomized schedule update",
            )
            st.session_state["schedule_notice"] = (
                f"Randomized schedule saved and verified: "
                f"{added} post(s) added."
            )
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))
        except StateStoreError as exc:
            st.error(str(exc))

    action = (
        "Pause automation" if automation_enabled else "Enable automation"
    )
    if right.button(action):
        queued = any(row["status"] == "queued" for row in state["queue"])
        approved = any(
            normalize_bool(row.get("approved"))
            and canonical_collection(row.get("collection"))
            in {
                canonical_collection(value)
                for value in settings.get(
                    "enabled_collections", COLLECTION_KEYS
                )
            }
            for row in state["sayings"]
        )
        if not automation_enabled and not state["linkedin"]["connected"]:
            st.error("Connect LinkedIn before enabling automation.")
        elif not automation_enabled and settings["dry_run"]:
            st.error("Turn off dry-run mode before enabling automation.")
        elif not automation_enabled and not approved:
            st.error("Approve at least one item in an enabled collection first.")
        elif not automation_enabled and not queued:
            st.error("Fill the randomized schedule first.")
        elif not automation_enabled and not worker.health()["ready"]:
            st.error(
                "The background worker is not Active. Refresh the Dashboard "
                "and reboot the Streamlit app if its status remains Starting, "
                "Stale, or Stopped."
            )
        else:

            def toggle(current: dict[str, Any]) -> None:
                current["settings"]["automation_enabled"] = (
                    not automation_enabled
                )
                append_event(
                    current,
                    "warning" if automation_enabled else "info",
                    "Automation paused."
                    if automation_enabled
                    else "Automation enabled.",
                )

            expected_enabled = not automation_enabled
            try:
                store.update_verified(
                    toggle,
                    lambda current: bool(
                        current["settings"]["automation_enabled"]
                    )
                    == expected_enabled,
                    "The automation status update",
                )
            except StateStoreError as exc:
                st.error(str(exc))
            else:
                st.session_state["schedule_notice"] = (
                    "Automation enabled and verified."
                    if expected_enabled
                    else (
                        "Automation paused and verified. Existing queued posts "
                        "remain queued."
                    )
                )
                st.rerun()

    with st.expander("Cancel queued posts"):
        st.warning(
            "This cancels only items that have not started publishing. "
            "Posted items and history remain unchanged."
        )
        confirmed = st.checkbox(
            "I want to cancel every currently queued post.",
            key="confirm_cancel_queue",
        )
        if st.button("Cancel queued posts", disabled=not confirmed):

            def cancel(current: dict[str, Any]) -> int:
                count = 0
                for item in current["queue"]:
                    if item["status"] == "queued":
                        item["status"] = "cancelled"
                        count += 1
                current["settings"]["automation_enabled"] = False
                append_event(
                    current,
                    "warning",
                    "Queued posts cancelled and automation paused.",
                    count=count,
                )
                return count

            try:
                count, _ = store.update_verified(
                    cancel,
                    lambda current: (
                        not any(
                            item["status"] == "queued"
                            for item in current["queue"]
                        )
                        and not bool(
                            current["settings"]["automation_enabled"]
                        )
                    ),
                    "The queue cancellation",
                )
            except StateStoreError as exc:
                st.error(str(exc))
            else:
                st.session_state["schedule_notice"] = (
                    f"Cancelled {count} queued post(s); automation is paused."
                )
                st.rerun()


def render_linkedin_setup(
    store: GitHubStateStore,
    state: dict[str, Any],
    config: dict[str, str],
) -> None:
    st.header("LinkedIn and setup")
    linkedin = state["linkedin"]
    if linkedin["connected"]:
        st.success(f"Connected as {linkedin['display_name']}")
        st.caption(f"Access-token expiry: {linkedin['expires_at']}")
    else:
        st.warning("No LinkedIn account is connected.")

    if st.button("Prepare LinkedIn connection"):
        st.session_state["linkedin_connect_url"] = create_oauth_link(
            store,
            config["LINKEDIN_CLIENT_ID"],
            config["LINKEDIN_REDIRECT_URI"],
        )
    if st.session_state.get("linkedin_connect_url"):
        st.link_button(
            "Continue to LinkedIn",
            st.session_state["linkedin_connect_url"],
            type="primary",
        )
        st.caption(
            "This authorization link expires after ten minutes."
        )

    with st.expander("Publish a connections-only test"):
        approved = [
            item
            for item in state["sayings"]
            if normalize_bool(item.get("approved"))
        ]
        st.warning(
            "This control creates a real LinkedIn post immediately and does "
            "not observe dry-run mode."
        )
        if approved:
            st.caption("Exact text that will be published")
            st.code(format_post(approved[0]))
        else:
            st.info(
                "Approve at least one content item to make a test available."
            )
        confirmed = st.checkbox(
            "I understand this immediately publishes the first approved "
            "content item to my LinkedIn connections."
        )
        if st.button(
            "Publish test now",
            disabled=not confirmed,
            type="primary",
        ):
            if not linkedin["connected"]:
                st.error("Connect LinkedIn first.")
            elif not approved:
                st.error("Approve at least one content item first.")
            else:
                try:
                    post_id = publish_linkedin_post(
                        decrypt_value(
                            linkedin["encrypted_access_token"],
                            config["FERNET_KEY"],
                        ),
                        linkedin["person_id"],
                        format_post(approved[0]),
                        "CONNECTIONS",
                    )

                    def record_test(current: dict[str, Any]) -> None:
                        append_event(
                            current,
                            "info",
                            "Connections-only test post published.",
                            post_id=post_id,
                        )

                    store.update(record_test)
                    st.success("Connections-only test post published.")
                except (LinkedInError, ValueError) as exc:
                    st.error(f"Test post failed: {exc}")

    st.subheader("Configuration")
    checks = [
        {
            "setting": "GitHub state repository",
            "ready": "yes"
            if config["GITHUB_REPOSITORY"]
            and config["GITHUB_STATE_TOKEN"]
            else "no",
        },
        {
            "setting": "LinkedIn application",
            "ready": "yes"
            if config["LINKEDIN_CLIENT_ID"]
            and config["LINKEDIN_CLIENT_SECRET"]
            else "no",
        },
        {
            "setting": "HTTPS redirect URI",
            "ready": "yes"
            if urlparse(config["LINKEDIN_REDIRECT_URI"]).scheme == "https"
            else "no",
        },
        {
            "setting": "Encryption key",
            "ready": "yes" if config["FERNET_KEY"] else "no",
        },
        {
            "setting": "DeepSeek AI (optional)",
            "ready": (
                f"yes — {config.get('DEEPSEEK_MODEL', DEFAULT_DEEPSEEK_MODEL)}"
                if config.get("DEEPSEEK_API_KEY")
                else "not configured"
            ),
        },
    ]
    st.dataframe(pd.DataFrame(checks), hide_index=True, use_container_width=True)
    st.caption("LinkedIn redirect URI")
    st.code(config["LINKEDIN_REDIRECT_URI"])


def render_activity(state: dict[str, Any]) -> None:
    st.header("Activity")
    if not state["events"]:
        st.info("No activity has been recorded yet.")
        return
    st.dataframe(
        pd.DataFrame(list(reversed(state["events"]))),
        hide_index=True,
        use_container_width=True,
    )


def main() -> None:
    config = read_secrets()
    missing = [
        name for name in required_secret_names() if not config.get(name)
    ]
    if missing:
        st.title("li_poster configuration required")
        st.error(
            "Add the following values under Streamlit App settings → Secrets."
        )
        st.code("\n".join(missing))
        st.stop()

    timezone_name = config.get("TIMEZONE", "America/Toronto")
    try:
        ZoneInfo(timezone_name)
        Fernet(config["FERNET_KEY"].encode())
    except Exception as exc:
        st.error(f"TIMEZONE or FERNET_KEY is invalid: {exc}")
        st.stop()

    try:
        store = get_store_v200(
            config["GITHUB_REPOSITORY"],
            config["GITHUB_STATE_TOKEN"],
        )
    except Exception as exc:
        st.error(f"Runtime state could not be initialized: {exc}")
        st.stop()

    # OAuth must be handled before login. Its random state value is validated.
    handle_oauth_callback(store, config)

    # Start before the password gate so an external app-waker visit is enough
    # to restart the posting worker after Streamlit hibernation.
    worker = get_worker_v200(
        store,
        config["FERNET_KEY"],
        timezone_name,
    )
    # This call runs on every Streamlit rerun. It is a no-op while the cached
    # thread is alive and revives it if the cached worker thread has stopped.
    worker.start()

    if not require_login(config["ADMIN_PASSWORD"]):
        st.stop()

    state, _ = store.load()
    st.sidebar.title("🏛️ li_poster")
    st.sidebar.caption(f"Version {APP_VERSION}")
    st.sidebar.caption(f"Timezone: {timezone_name}")
    if st.sidebar.button("Sign out"):
        st.session_state.clear()
        st.rerun()

    dashboard, sayings, schedule, linkedin, activity = st.tabs(
        [
            "Dashboard",
            "Content library",
            "Schedule",
            "LinkedIn and setup",
            "Activity",
        ]
    )
    with dashboard:
        render_dashboard(store, state, worker, timezone_name)
    with sayings:
        render_sayings(store, state, config)
    with schedule:
        render_schedule(store, state, timezone_name, worker)
    with linkedin:
        render_linkedin_setup(store, state, config)
    with activity:
        render_activity(state)


if __name__ == "__main__":
    main()
