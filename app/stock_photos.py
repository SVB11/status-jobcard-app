"""Match a stock photo from existing job type + description. No new fields."""

PHOTOS = [
    {"file": "grw-50000lt-fuel-tanker.png", "need": ["grw"], "any": ["50000", "50 000", "50,000"], "type": ["fuel", "tanker"]},
    {"file": "tankclinic-49000lt-fuel-tanker.png", "need": ["tank clinic", "tankclinic"], "any": ["49000", "49 000", "49,000"], "type": ["fuel", "tanker"]},
    {"file": "henred-50000lt-fuel-tanker.png", "need": ["henred"], "any": ["50000", "50 000", "50,000"], "type": ["fuel", "tanker"]},
    {"file": "grw-38000lt-hfo-tanker.png", "need": ["grw"], "any": ["38000", "38 000", "38,000", "hfo"], "type": ["hfo", "tanker"]},
    {"file": "henred-38000lt-hfo-tanker.png", "need": ["henred"], "any": ["38000", "38 000", "38,000", "hfo"], "type": ["hfo", "tanker"]},
    {"file": "tankclinic-60m3-lpg-gas-tanker.png", "need": ["lpg", "lp.gas", "lp gas", "gas tanker"], "any": [], "type": ["lpg", "gas", "tanker"]},
    {"file": "mercedes-18000lt-fuel-rigid.png", "need": ["rigid"], "any": ["mercedes", "benz", "18000", "18 000"], "type": ["rigid", "tanker"]},
    {"file": "mercedes-actros-truck-tractor.png", "need": ["actros"], "any": ["mercedes", "benz"], "type": ["tractor", "horse"]},
    {"file": "volvo-fh440-truck-tractor.png", "need": ["volvo"], "any": ["fh440", "fh 440", "440"], "type": ["tractor", "horse"]},
    {"file": "man-tgs-truck-tractor.png", "need": ["man"], "any": ["tgs"], "type": ["tractor", "horse"]},
    {"file": "faw-28-500-truck-tractor.png", "need": ["faw"], "any": ["28-500", "28.500", "28500", "jh6"], "type": ["tractor", "horse"]},
    {"file": "scania-truck-tractor.png", "need": ["scania"], "any": [], "type": ["tractor", "horse"]},
    {"file": "afrit-40cube-sidetipper.png", "need": ["side tipper", "sidetipper", "side-tipper"], "any": ["afrit", "40"], "type": ["tipper", "trailer"]},
    {"file": "afrit-superlink-tautliner.png", "need": ["tautliner", "taut liner", "curtainsider"], "any": ["afrit", "superlink"], "type": ["tautliner", "trailer"]},
]

FALLBACK = [
    ("hfo", "grw-38000lt-hfo-tanker.png"),
    ("lpg", "tankclinic-60m3-lpg-gas-tanker.png"),
    ("gas tanker", "tankclinic-60m3-lpg-gas-tanker.png"),
    ("side tipper", "afrit-40cube-sidetipper.png"),
    ("sidetipper", "afrit-40cube-sidetipper.png"),
    ("tautliner", "afrit-superlink-tautliner.png"),
    ("rigid", "mercedes-18000lt-fuel-rigid.png"),
    ("actros", "mercedes-actros-truck-tractor.png"),
    ("volvo", "volvo-fh440-truck-tractor.png"),
    ("scania", "scania-truck-tractor.png"),
    (" faw", "faw-28-500-truck-tractor.png"),
    ("man ", "man-tgs-truck-tractor.png"),
    ("man/", "man-tgs-truck-tractor.png"),
    ("grw", "grw-50000lt-fuel-tanker.png"),
    ("tank clinic", "tankclinic-49000lt-fuel-tanker.png"),
    ("henred", "henred-50000lt-fuel-tanker.png"),
    ("fuel tanker", "grw-50000lt-fuel-tanker.png"),
    ("tanker", "grw-50000lt-fuel-tanker.png"),
    ("truck tractor", "mercedes-actros-truck-tractor.png"),
    ("tractor", "mercedes-actros-truck-tractor.png"),
    ("tipper", "afrit-40cube-sidetipper.png"),
    ("trailer", "afrit-superlink-tautliner.png"),
]


def match_stock_photo(vehicle_description="", main_type="", sub_type="", year=""):
    blob = " ".join([
        str(vehicle_description or ""),
        str(main_type or ""),
        str(sub_type or ""),
        str(year or ""),
    ]).lower()
    blob = blob.replace("-", " ").replace("_", " ")

    best = None
    best_score = 0
    for row in PHOTOS:
        score = 0
        if any(n in blob for n in row["need"]):
            score += 4
        else:
            continue
        if row["any"] and any(a in blob for a in row["any"]):
            score += 3
        if row["type"] and any(t in blob for t in row["type"]):
            score += 1
        if score > best_score:
            best_score = score
            best = row["file"]
    if best:
        return "/static/images/stock/" + best

    for key, file in FALLBACK:
        if key in blob:
            return "/static/images/stock/" + file
    return None
