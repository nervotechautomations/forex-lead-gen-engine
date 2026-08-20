"""Keyword catalog — the query matrix used by the discovery layer.

Categories follow the lead-gen brief:
  A = High-intent / Prop Firm      B = General Forex
  C = Learning / Beginner          D = Lifestyle / Aspirational
  E = English-language expansion   F = Platform-native (TikTok)

Regions target the primary Spanish-speaking forex markets.
"""

CATEGORIES = [
    # A — High-intent / Prop Firm
    "fondeo de cuentas",
    "cuentas fondeadas forex",
    "empresa de fondeo",
    "prueba de fondeo",
    "fondeo para traders",
    # B — General Forex
    "trading de divisas",
    "operar forex",
    "broker de forex",
    "señales de forex",
    "estrategias de trading",
    "análisis técnico forex",
    # C — Learning / Beginner
    "aprender a hacer trading",
    "curso de trading gratis",
    "trading para principiantes",
    "cómo invertir en forex",
    "academia de trading",
    # D — Lifestyle / Aspirational
    "trader rentable",
    "vivir del trading",
    "libertad financiera trading",
    "mentalidad de trader",
    # E — English expansion
    "forex mentor",
    "funded trader",
    "prop firm",
    "trading mentor",
    # F — Platform-native
    "trading en vivo",
    "operando en vivo",
]

REGIONS = [
    "España",
    "México",
    "Colombia",
    "Argentina",
    "Miami",
    "Chile",
    "Perú",
    "Venezuela",
]

# TikTok user-search terms (platform-native discovery)
TIKTOK_TERMS = [
    "trading forex",
    "forex trader",
    "fondeo",
    "prop firm",
    "day trader",
    "trading mentor",
    "cuentas fondeadas",
    "trading en español",
    "XAUUSD",
    "trading tips",
]
