from __future__ import annotations
import os
from dotenv import load_dotenv

# Charge .env
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(ENV_PATH)

def getenv(key: str, default: str = "") -> str:
    return os.getenv(key, default)

# Capture
CAP_LEFT   = int(getenv("CAP_LEFT", "40"))
CAP_TOP    = int(getenv("CAP_TOP", "40"))
CAP_WIDTH  = int(getenv("CAP_WIDTH", "1200"))
CAP_HEIGHT = int(getenv("CAP_HEIGHT", "700"))

# OCR
OCR_LANG = getenv("OCR_LANG", "fra")
OCR_OEM  = getenv("OCR_OEM", "3")
OCR_PSM  = getenv("OCR_PSM", "6")
TESSERACT_CMD = getenv("TESSERACT_CMD", "")

# IA
PROVIDER = getenv("PROVIDER", "OpenAI")
MODEL    = getenv("MODEL", "gpt-4o-mini")
PROMPT   = getenv("PROMPT", "Default (Raisonnement Général)")
LLM_TEMP = float(getenv("LLM_TEMP", "0.0"))  # surtout pas 'TEMP'

# Webhook & logs
DISCORD_WEBHOOK = getenv("DISCORD_WEBHOOK", "")
LOG_DIR = getenv("LOG_DIR", "logs")

# API keys
OPENAI_API_KEY    = getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = getenv("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY    = getenv("GEMINI_API_KEY", "")

# Prompts
PROMPTS = {
    "Default (Raisonnement Général)": (
        "Tu es un expert en logique et en raisonnement, ta précision est primordiale.\n"
        "CONTEXTE: Tu vas recevoir un texte brut extrait d'une image par un OCR.\n"
        "Ce texte contient une question à choix multiples et plusieurs propositions de réponse.\n"
        "--- TEXTE BRUT DE L'OCR ---\n{text}\n--- FIN DU TEXTE BRUT ---\n"
        "MISSION: Analyse le texte brut. Ignore le bruit et les erreurs de l'OCR.\n"
        "Identifie la question principale et les différentes propositions de réponse.\n"
        "Choisis la proposition qui répond le mieux à la question.\n"
        "FORMAT DE RÉPONSE: Réponds UNIQUEMENT avec le texte complet de la proposition."
    ),
    "Pensée Critique (Conclusion/Idée)": (
        "Tu es un expert en analyse de texte et en synthèse.\n"
        "CONTEXTE: Paragraphe + question de conclusion/idée principale + choix.\n"
        "--- TEXTE BRUT DE L'OCR ---\n{text}\n--- FIN DU TEXTE BRUT ---\n"
        "MISSION: Choisis l'option la plus synthétique, pas un détail.\n"
        "FORMAT: Réponds UNIQUEMENT avec l'option."
    ),
    "Aptitude Numérique (Maths/Logique)": (
        "Tu es un mathématicien rigoureux.\n"
        "CONTEXTE: Problème mathématique/logique sous forme de QCM.\n"
        "--- TEXTE BRUT DE L'OCR ---\n{text}\n--- FIN DU TEXTE BRUT ---\n"
        "MISSION: Décompose, calcule précisément, compare aux options.\n"
        "FORMAT: Réponds UNIQUEMENT avec l'option."
    ),
    "Conditions Minimales": (
        "Tu es expert en suffisance de données.\n"
        "CONTEXTE: Question + (1) et (2).\n"
        "--- TEXTE BRUT DE L'OCR ---\n{text}\n--- FIN DU TEXTE BRUT ---\n"
        "MISSION: Évalue (1) seul, (2) seul, puis ensemble. Choisis la bonne option.\n"
        "FORMAT: Réponds UNIQUEMENT avec l'option."
    ),
    "Capacité Rédactionnelle (Français)": (
        "Tu es linguiste/grammairien.\n"
        "CONTEXTE: Vocabulaire, syntaxe, cohérence.\n"
        "--- TEXTE BRUT DE L'OCR ---\n{text}\n--- FIN DU TEXTE BRUT ---\n"
        "MISSION: Choisis la réponse la plus correcte.\n"
        "FORMAT: Réponds UNIQUEMENT avec l'option."
    ),
}

# Providers dispo
PROVIDERS = [
    ("OpenAI",  ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"]),
    ("Anthropic", ["claude-3-5-sonnet-20240620", "claude-3-opus-20240229"]),
    ("Gemini", ["gemini-1.5-pro", "gemini-1.5-flash"]),
]
