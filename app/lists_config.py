LOCATIONS = [
    "Yard",
    "Bay 1 Reuben",
    "Bay 2 Ricardo",
    "Bay 3 Jonas",
    "Bay 4 Josiah",
    "Bay 5 Josiah 2",
    "Wash Bay",
    "Test Pit Bay 1",
    "Test Pit Bay 2",
    "Test Pit Bay 3",
    "3rd Party",
    "Out / Delivered",
]

# Timer starts when vehicle is in any of these workshop areas
WORKSHOP_BAYS = [
    "Bay 1 Reuben",
    "Bay 2 Ricardo",
    "Bay 3 Jonas",
    "Bay 4 Josiah",
    "Bay 5 Josiah 2",
    "Wash Bay",
    "Test Pit Bay 1",
    "Test Pit Bay 2",
    "Test Pit Bay 3",
]

ACTIVITY_TYPES = [
    "Brakes service",
    "Spray / paint",
    "Engine service",
    "Computer / diagnostics (3rd party)",
    "Auto electrical — MAN Auto (Scotty)",
    "Roadworthy preparation",
    "Calibration",
    "Pressure / barrel test",
    "General mechanical",
    "Other",
]


THIRD_PARTY_SERVICES = [
    {"service": "Barrel Test", "providers": ["STT", "ITL"]},
    {"service": "Pressure Test", "providers": ["PFT", "FK"]},
    {"service": "Calibration Test", "providers": ["Liquid Flow"]},
    {"service": "Roadworthy", "providers": ["East Rand Testing Station"]},
    {"service": "Auto Electrical", "providers": ["MAN Auto (Scotty)"]},
]

EXTRA_WORK_PRESETS = [
    "Brakes service",
    "Spray / paint / touch-up",
    "Engine service",
    "Diagnostics / computer",
    "Auto electrical — MAN Auto (Scotty)",
    "Roadworthy items",
    "Calibration",
    "Pressure / barrel test",
    "Parts waiting",
    "3rd party work",
    "Wash",
    "Test pit",
    "Other",
]


BARREL_INTERVALS = ["3 year", "6 year", "3 and 6 year", "15 year"]


TASK_PROVIDER_MAP = {
    "Pressure test": ["PFT", "FK"],
    "Barrel test": ["STT", "ITL"],
    "Calibration": ["Liquid Flow"],
    "Roadworthy": ["East Rand Testing Station"],
    "Auto electrical": ["MAN Auto (Scotty)"],
}

def providers_for_task(task_name: str):
    name = (task_name or "").lower()
    for key, providers in TASK_PROVIDER_MAP.items():
        if key.lower() in name:
            return providers
    return []

SUPPLY_CATEGORIES = {
    "Delivery hose": [
        "Fuel delivery hose 3\"",
        "Fuel delivery hose 4\"",
        "Fuel delivery hose 6\"",
        "Aviation / JET A1 hose",
        "LPG hose",
        "HFO hose",
        "Bitumen hose",
        "Chemical hose",
        "Other hose",
    ],
    "Coupler": [
        "Camlock male 3\"",
        "Camlock female 3\"",
        "Camlock male 4\"",
        "Camlock female 4\"",
        "Camlock 6\"",
        "Dry-break coupler",
        "API adaptor",
        "BSP adaptor",
        "Other coupler",
    ],
    "Suzi cable": [
        "7-pin suzi",
        "15-pin suzi",
        "ABS / EBS suzi",
        "Dual 7 + 15 pin",
        "Other suzi cable",
    ],
}
