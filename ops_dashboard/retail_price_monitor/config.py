"""Configuration for the retail price monitor.

Defines the Israeli retail chains to monitor, the Leiman Schlissel product
catalogue used as the canonical reference, and the thresholds that drive the
alert engine.

The catalogue here is intentionally static and public-domain (generic product
descriptors such as "Halva Pistachio 500g") — no proprietary information is
hard-coded. Real production deployments would replace :data:`PRODUCT_CATALOG`
with a feed from the Leiman Schlissel master data system.
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RPM_DB_PATH = os.path.join(BASE_DIR, "retail_price.db")

BRAND_NAME = "Leiman Schlissel"
MANUFACTURER = "Leiman Schlissel Ltd."

# ── Retail chains ─────────────────────────────────────────────────────────
# Each entry mirrors the major Israeli retail chains enumerated in the spec.
RETAILERS = [
    {"code": "shufersal",   "name_he": "שופרסל",        "name_en": "Shufersal",        "source_url": "https://www.shufersal.co.il"},
    {"code": "rami_levy",   "name_he": "רמי לוי",        "name_en": "Rami Levy",        "source_url": "https://www.rami-levy.co.il"},
    {"code": "yochananof",  "name_he": "יוחננוף",        "name_en": "Yochananof",       "source_url": "https://www.yochananof.co.il"},
    {"code": "carrefour",   "name_he": "קרפור",          "name_en": "Carrefour Israel", "source_url": "https://www.carrefour.co.il"},
    {"code": "victory",     "name_he": "ויקטורי",        "name_en": "Victory",          "source_url": "https://www.victoryonline.co.il"},
    {"code": "tiv_taam",    "name_he": "טיב טעם",        "name_en": "Tiv Ta'am",        "source_url": "https://www.tivtaam.co.il"},
    {"code": "hatzi_hinam", "name_he": "חצי חינם",       "name_en": "Hatzi Hinam",      "source_url": "https://www.hazi-hinam.co.il"},
    {"code": "mahsanei",    "name_he": "מחסני השוק",     "name_en": "Mahsanei HaShuk",  "source_url": "https://mahsaneihashuk.co.il"},
    {"code": "yenot_bitan", "name_he": "יינות ביתן",     "name_en": "Yenot Bitan",      "source_url": "https://www.ybitan.co.il"},
]

# ── Canonical product catalogue ───────────────────────────────────────────
# Barcodes are fictional EAN-13 placeholders. Base prices are illustrative
# shelf prices in ILS and are used only to seed mock observations.
PRODUCT_CATALOG = [
    # Halva line
    {"name_he": "חלבה פיסטוק 500 גרם",        "name_en": "Halva Pistachio 500g",      "barcode": "7290000100011", "category": "ממתקים",    "subcategory": "חלבה",       "size_value": 500, "size_unit": "gr", "package": "קרטון",     "base_price": 39.90},
    {"name_he": "חלבה שוקולד 500 גרם",        "name_en": "Halva Chocolate 500g",      "barcode": "7290000100028", "category": "ממתקים",    "subcategory": "חלבה",       "size_value": 500, "size_unit": "gr", "package": "קרטון",     "base_price": 37.90},
    {"name_he": "חלבה וניל 500 גרם",          "name_en": "Halva Vanilla 500g",        "barcode": "7290000100035", "category": "ממתקים",    "subcategory": "חלבה",       "size_value": 500, "size_unit": "gr", "package": "קרטון",     "base_price": 34.90},
    {"name_he": "חלבה עם שקדים 250 גרם",      "name_en": "Halva Almond 250g",         "barcode": "7290000100042", "category": "ממתקים",    "subcategory": "חלבה",       "size_value": 250, "size_unit": "gr", "package": "קרטון",     "base_price": 21.90},
    {"name_he": "חלבה פרווה קלאסית 400 גרם",  "name_en": "Halva Classic 400g",        "barcode": "7290000100059", "category": "ממתקים",    "subcategory": "חלבה",       "size_value": 400, "size_unit": "gr", "package": "קרטון",     "base_price": 29.90},

    # Tehina line
    {"name_he": "טחינה גולמית 500 גרם",       "name_en": "Raw Tehina 500g",           "barcode": "7290000100066", "category": "ממרחים",    "subcategory": "טחינה",      "size_value": 500, "size_unit": "gr", "package": "צנצנת",     "base_price": 22.90},
    {"name_he": "טחינה מוכנה לימון 350 גרם",  "name_en": "Ready Tehina Lemon 350g",   "barcode": "7290000100073", "category": "ממרחים",    "subcategory": "טחינה",      "size_value": 350, "size_unit": "gr", "package": "צנצנת",     "base_price": 18.90},
    {"name_he": "טחינה אורגנית 500 גרם",      "name_en": "Organic Tehina 500g",       "barcode": "7290000100080", "category": "ממרחים",    "subcategory": "טחינה",      "size_value": 500, "size_unit": "gr", "package": "צנצנת",     "base_price": 28.90},
    {"name_he": "טחינה גולמית 1 קג",          "name_en": "Raw Tehina 1kg",            "barcode": "7290000100097", "category": "ממרחים",    "subcategory": "טחינה",      "size_value": 1000,"size_unit": "gr", "package": "צנצנת",     "base_price": 39.90},

    # Candy / snacks
    {"name_he": "סוכריות לוקום מגוון 300 גרם","name_en": "Turkish Delight Mixed 300g","barcode": "7290000100103", "category": "ממתקים",    "subcategory": "לוקום",      "size_value": 300, "size_unit": "gr", "package": "שקית",      "base_price": 24.90},
    {"name_he": "עוגיות טחינה 200 גרם",       "name_en": "Tehina Cookies 200g",       "barcode": "7290000100110", "category": "עוגיות",    "subcategory": "עוגיות טחינה","size_value": 200,"size_unit": "gr","package": "חבילה",     "base_price": 16.90},
    {"name_he": "חטיף חלבה עטוף 40 גרם",     "name_en": "Halva Bar 40g",             "barcode": "7290000100127", "category": "חטיפים",    "subcategory": "חטיף חלבה",  "size_value": 40,  "size_unit": "gr", "package": "יחידה",     "base_price": 4.90},
    {"name_he": "מארז חטיפי חלבה 10 יחידות", "name_en": "Halva Bar Pack 10",         "barcode": "7290000100134", "category": "חטיפים",    "subcategory": "חטיף חלבה",  "size_value": 400, "size_unit": "gr", "package": "מארז",      "base_price": 32.90},

    # Honey / spreads
    {"name_he": "דבש טהור 500 גרם",           "name_en": "Pure Honey 500g",           "barcode": "7290000100141", "category": "ממרחים",    "subcategory": "דבש",        "size_value": 500, "size_unit": "gr", "package": "צנצנת",     "base_price": 34.90},
    {"name_he": "סילאן תמרים 450 גרם",        "name_en": "Date Syrup 450g",           "barcode": "7290000100158", "category": "ממרחים",    "subcategory": "סילאן",      "size_value": 450, "size_unit": "gr", "package": "בקבוק",     "base_price": 19.90},
    {"name_he": "ריבת תאנים 370 גרם",         "name_en": "Fig Jam 370g",              "barcode": "7290000100165", "category": "ממרחים",    "subcategory": "ריבות",      "size_value": 370, "size_unit": "gr", "package": "צנצנת",     "base_price": 17.90},

    # Nuts & seeds
    {"name_he": "שומשום קלוי 200 גרם",        "name_en": "Toasted Sesame 200g",       "barcode": "7290000100172", "category": "אגוזים",    "subcategory": "שומשום",     "size_value": 200, "size_unit": "gr", "package": "שקית",      "base_price": 12.90},
    {"name_he": "תערובת אגוזים ופירות 250 גרם","name_en": "Nut & Fruit Mix 250g",     "barcode": "7290000100189", "category": "אגוזים",    "subcategory": "תערובות",    "size_value": 250, "size_unit": "gr", "package": "שקית",      "base_price": 26.90},

    # Seasonal / gift
    {"name_he": "מארז מתנה חלבה 3 יחידות",    "name_en": "Halva Gift Pack x3",        "barcode": "7290000100196", "category": "מארזי מתנה","subcategory": "מארזים",     "size_value": 1500,"size_unit": "gr", "package": "מארז מתנה","base_price": 79.90},
    {"name_he": "מארז ראש השנה דבש וחלבה",    "name_en": "Rosh Hashana Honey & Halva","barcode": "7290000100202", "category": "מארזי מתנה","subcategory": "מארזי חג",   "size_value": 1200,"size_unit": "gr", "package": "מארז מתנה","base_price": 89.90},

    # Low-sugar / health line
    {"name_he": "חלבה ללא סוכר 400 גרם",      "name_en": "Sugar-Free Halva 400g",     "barcode": "7290000100219", "category": "ממתקים",    "subcategory": "חלבה",       "size_value": 400, "size_unit": "gr", "package": "קרטון",     "base_price": 42.90},
    {"name_he": "חלבה דלת קלוריות 350 גרם",   "name_en": "Low-Cal Halva 350g",        "barcode": "7290000100226", "category": "ממתקים",    "subcategory": "חלבה",       "size_value": 350, "size_unit": "gr", "package": "קרטון",     "base_price": 36.90},

    # Baking
    {"name_he": "שקדים טחונים 200 גרם",       "name_en": "Ground Almonds 200g",       "barcode": "7290000100233", "category": "אפייה",     "subcategory": "שקדים",      "size_value": 200, "size_unit": "gr", "package": "שקית",      "base_price": 27.90},
    {"name_he": "קוקוס טחון 250 גרם",         "name_en": "Ground Coconut 250g",       "barcode": "7290000100240", "category": "אפייה",     "subcategory": "קוקוס",      "size_value": 250, "size_unit": "gr", "package": "שקית",      "base_price": 14.90},
]

# ── Retailer pricing profiles ─────────────────────────────────────────────
# Multipliers applied to the catalogue base price when seeding the mock data.
# Values mirror the public reputation of each chain (discounters < premium).
RETAILER_PRICE_PROFILE = {
    "shufersal":   {"mult": 1.02, "promo_freq": 0.18, "noise": 0.04},
    "rami_levy":   {"mult": 0.93, "promo_freq": 0.14, "noise": 0.03},
    "yochananof":  {"mult": 0.97, "promo_freq": 0.20, "noise": 0.04},
    "carrefour":   {"mult": 1.00, "promo_freq": 0.22, "noise": 0.05},
    "victory":     {"mult": 0.99, "promo_freq": 0.15, "noise": 0.04},
    "tiv_taam":    {"mult": 1.08, "promo_freq": 0.10, "noise": 0.05},
    "hatzi_hinam": {"mult": 0.95, "promo_freq": 0.17, "noise": 0.03},
    "mahsanei":    {"mult": 0.94, "promo_freq": 0.16, "noise": 0.03},
    "yenot_bitan": {"mult": 1.01, "promo_freq": 0.19, "noise": 0.04},
}

# ── Alert thresholds ──────────────────────────────────────────────────────
ALERT_THRESHOLDS = {
    # Percentage change vs. the previous day that counts as "significant".
    "daily_change_pct": 5.0,
    # Number of consecutive daily observations required to call a trend.
    "trend_consecutive": 3,
    # Coefficient-of-variation across retailers (std / mean) above which the
    # product is flagged as highly volatile across the market.
    "cross_retailer_cov": 0.08,
    # How far below the market average a retailer must be to be "cheapest".
    "cheapest_margin_pct": 6.0,
    # How far above the market average a retailer must be to be "most expensive".
    "expensive_margin_pct": 6.0,
}

# How many days of history to keep in the mock generator / default queries.
HISTORY_DAYS = 60

# How long to cache the "morning brief" result (seconds).
MORNING_BRIEF_CACHE_SECONDS = 300
