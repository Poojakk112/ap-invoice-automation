"""Synthetic reference vocabularies: vendor names, product catalogue, locations.

Everything here is invented. No external or personal data is used.
"""

import math

from apflow.money import q2

# category -> settings. price/qty ranges drive realistic, skewed distributions.
CATEGORIES = {
    "OFF": {"name": "Office Supplies", "price": (2, 90), "qty": (5, 200), "tax": "TX8", "uom": "EA",
            "nouns": ["Ballpoint Pens", "Copy Paper Ream", "Stapler", "Desk Organizer", "Sticky Notes",
                      "File Folders", "Whiteboard Markers", "Toner Cartridge", "Notebook", "Label Roll"]},
    "ITH": {"name": "IT Hardware", "price": (120, 3800), "qty": (1, 25), "tax": "TX8", "uom": "EA",
            "nouns": ["Laptop", "Monitor 27in", "Docking Station", "Network Switch", "Keyboard Set",
                      "Wireless Access Point", "Rack Server", "SSD 2TB", "Headset", "Webcam"]},
    "SWL": {"name": "Software Licences", "price": (40, 1800), "qty": (1, 60), "tax": "TX5", "uom": "SEAT",
            "nouns": ["CRM Licence", "Design Suite Seat", "Endpoint Security", "Analytics Seat",
                      "Backup Licence", "Project Tool Seat", "Database Licence", "VPN Seat"]},
    "IND": {"name": "Industrial Parts", "price": (4, 850), "qty": (2, 300), "tax": "TX8", "uom": "EA",
            "nouns": ["Bearing Assembly", "Hydraulic Hose", "Steel Bracket", "Gear Motor", "Valve Kit",
                      "Drive Belt", "Pressure Gauge", "Coupling", "Filter Element", "Fastener Kit"]},
    "PKG": {"name": "Packaging", "price": (0.4, 35), "qty": (100, 4000), "tax": "TX8", "uom": "CS",
            "nouns": ["Corrugated Box", "Stretch Wrap", "Packing Tape", "Bubble Mailer", "Pallet Label",
                      "Foam Insert", "Shipping Bag", "Void Fill"]},
    "FDS": {"name": "Cafeteria Supplies", "price": (3, 60), "qty": (10, 400), "tax": "TX5", "uom": "CS",
            "nouns": ["Coffee Beans", "Paper Cups", "Bottled Water", "Tea Assortment", "Napkins",
                      "Snack Box", "Sugar Sachets", "Compostable Cutlery"]},
    "SAF": {"name": "Safety & First Aid", "price": (8, 320), "qty": (5, 150), "tax": "TX0", "uom": "EA",
            "nouns": ["Safety Helmet", "Hi-Vis Vest", "First Aid Kit", "Safety Gloves", "Ear Protection",
                      "Eye Wash Station", "Safety Boots", "Respirator Mask"]},
    "SRV": {"name": "Professional Services", "price": (400, 2500), "qty": (1, 15), "tax": "TX10", "uom": "DAY",
            "nouns": ["Consulting Day", "Facilities Maintenance", "Training Session", "Audit Support",
                      "Cleaning Service", "IT Support Day"]},
}
PO_CATEGORIES = [c for c in CATEGORIES if c != "SRV"]   # SRV is billed without a PO

ADJECTIVES = ["Standard", "Premium", "Heavy Duty", "Compact", "Eco", "Pro", "Basic", "Industrial",
              "Ergonomic", "Recycled", "Large", "Small"]
SKUS_PER_CATEGORY = 50

NAME_A = ["Apex", "Blue Ridge", "Cedar", "Summit", "Harbor", "Pioneer", "Granite", "Northwind", "Silver Oak",
          "Riverbend", "Keystone", "Lakeside", "Ironwood", "Bright Path", "Evergreen", "Crescent", "Falcon",
          "Meridian", "Prairie", "Redstone", "Tidewater", "Union", "Vista", "Westfield", "Zenith", "Copper Hill",
          "Orchard", "Beacon", "Frontier", "Juniper"]
NAME_B = ["Industrial", "Office", "Logistics", "Tech", "Facility", "Packaging", "Safety", "Data",
          "Commercial", "Precision", "Global", "Metro", "Coastal", "Allied"]
NAME_C = ["Supply", "Solutions", "Partners", "Systems", "Works", "Traders", "Group", "Distributors", "Services"]
NAME_D = ["LLC", "Inc", "Co", "Corp"]

US_STATES = ["VA", "NC", "TX", "CA", "NY", "GA", "OH", "IL", "PA", "FL", "WA", "MA", "NJ", "CO", "AZ", "MI"]

# Synthetic EINs use prefixes the IRS does not issue, so they cannot collide
# with a real business tax ID.
UNISSUED_EIN_PREFIXES = ["07", "08", "09", "17", "18", "19", "28", "29", "49", "69", "70", "78", "79", "89"]

COST_CENTERS = [f"CC-{n}" for n in (1001, 1002, 1105, 1210, 2001, 2050, 3100, 3300, 4100, 5200)]
WAREHOUSES = ["WH-EAST", "WH-WEST", "WH-CENTRAL"]

PAYMENT_TERMS = {"NET15": 15, "NET30": 30, "NET45": 45, "NET60": 60}


def log_uniform(rng, low, high):
    """Skewed distribution: many cheap items, few expensive ones (realistic)."""
    return math.exp(rng.uniform(math.log(low), math.log(high)))


def build_catalog(rng):
    """Return {sku: {...}} with a deterministic base price per SKU."""
    catalog = {}
    for cat, cfg in CATEGORIES.items():
        for n in range(1, SKUS_PER_CATEGORY + 1):
            noun = cfg["nouns"][(n - 1) % len(cfg["nouns"])]
            adj = ADJECTIVES[rng.randrange(len(ADJECTIVES))]
            catalog[f"SKU-{cat}-{n:04d}"] = {
                "sku": f"SKU-{cat}-{n:04d}",
                "category": cat,
                "description": f"{adj} {noun}",
                "base_price": q2(log_uniform(rng, *cfg["price"])),
                "tax_code": cfg["tax"],
                "uom": cfg["uom"],
            }
    return catalog


def skus_by_category(catalog):
    out = {c: [] for c in CATEGORIES}
    for sku, item in catalog.items():
        out[item["category"]].append(sku)
    return out
