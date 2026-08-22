"""Keyword catalog — the query matrix used by the discovery layer.

Expanded 2026-08: 66 keywords x 19 regions, covering prop-firm funding,
instruments (XAUUSD/synthetics), education, and lifestyle niches.

Categories follow the lead-gen brief:
  A = High-intent / Prop Firm      B = General Forex
  C = Learning / Beginner          D = Lifestyle / Aspirational
"""
CATEGORIES = {
    "A": ["fondeo de cuentas", "cuentas fondeadas forex", "empresa de fondeo",
          "prueba de fondeo", "desafío de fondeo", "desafio de fondeo",
          "fases de fondeo", "pasar el challenge", "retiros de fondeo",
          "payout fondeo", "cuenta fondeada", "prop firm español",
          "prop firm challenge", "funded account", "funded trader"],
    "B": ["señales de forex", "señales gratis forex", "senales forex",
          "estrategias de trading", "análisis técnico forex", "analisis tecnico",
          "operar forex", "broker de forex", "trading de divisas",
          "copytrading", "copy trading", "grupo de trading", "telegram trading",
          "xauusd", "oro trading", "trading de oro", "indices sinteticos",
          "índices sintéticos", "sintéticos trading", "nasdaq trading",
          "eurusd trading", "day trading", "day trader", "gold signals"],
    "C": ["curso de trading gratis", "trading para principiantes",
          "academia de trading", "escuela de trading", "clases de trading",
          "trading desde cero", "aprende trading", "aprender a hacer trading",
          "trading en español", "psicotrading", "gestion de riesgo trading",
          "gestor de capital", "asesor financiero trading",
          "trading mentorship", "forex education", "forex signals"],
    "D": ["trader rentable", "vivir del trading", "trader profesional",
          "mentor de trading", "trading en vivo", "forex mentor",
          "libertad financiera trading", "trading lifestyle", "mi vida como trader",
          "trading community", "forex community"],
}
REGIONS = ["España", "México", "Colombia", "Argentina", "Miami", "Chile", "Perú", "Venezuela",
           "República Dominicana", "Ecuador", "Guatemala", "Costa Rica", "Panamá",
           "El Salvador", "Bolivia", "Uruguay", "Paraguay", "Puerto Rico", "Honduras"]
TIKTOK_TERMS = ["day trading", "gold signals", "forex signals", "trading mentor",
                "prop firm", "funded trader", "trading en vivo", "xauusd"]
