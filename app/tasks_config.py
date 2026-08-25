"""
Work / Prep Task rules based on vehicle type.
Locked according to business requirements.
"""

def get_tasks_for_vehicle(main_type: str, year: str = None) -> list:
    """
    Return the list of standard tasks for a given vehicle main_type.
    Each task is a dict: {"task_name": str, "description": str or None}
    """
    main_type = (main_type or "").strip()

    tasks = []

    # ----- Common to most vehicles -----
    common = [
        {"task_name": "Roadworthy", "description": None},
        {"task_name": "Brake tests", "description": None},
    ]

    if main_type == "Tanker":
        tasks.extend([
            {"task_name": "Pressure test (SLP)", "description": None},
            {"task_name": "Barrel test - 3 year", "description": "Always required"},
            {"task_name": "Barrel test - 6 year", "description": "Always required"},
        ])

        # 15 year only if vehicle is 15+ years old
        try:
            vehicle_year = int(year) if year else 0
            current_year = 2026
            if current_year - vehicle_year >= 15:
                tasks.append({"task_name": "Barrel test - 15 year", "description": "Only applicable if tanker is 15 years or older"})
        except (ValueError, TypeError):
            pass

        tasks.append({"task_name": "Calibration (if fitted with meters)", "description": None})
        tasks.extend(common)
        tasks.append({"task_name": "DEKRA Spec", "description": "Standard for fuel tankers"})

    elif main_type == "Truck Tractor":
        tasks.extend(common)
        tasks.extend([
            {"task_name": "Fuel Spec", "description": "Optional"},
            {"task_name": "DEKRA Spec", "description": "Optional"},
            {"task_name": "Spray rims", "description": None},
            {"task_name": "Touch-ups", "description": None},
            {"task_name": "Polish", "description": None},
            {"task_name": "Full refurbishment", "description": None},
            {"task_name": "Already refurbished", "description": "No further refurbishment needed"},
        ])

    elif main_type in ("Trailer", "Tipper"):
        tasks.extend(common)
        tasks.extend([
            {"task_name": "Spray rims", "description": None},
            {"task_name": "Touch-ups", "description": None},
            {"task_name": "Polish", "description": None},
            {"task_name": "Full refurbishment", "description": None},
            {"task_name": "Already refurbished", "description": "No further refurbishment needed"},
        ])

    else:  # Other
        tasks.extend(common)

    # Special options available on relevant types
    if main_type in ("Tanker", "Truck Tractor", "Trailer", "Tipper", "Other"):
        tasks.append({"task_name": "As Is – with Roadworthy only", "description": None})
        tasks.append({"task_name": "As Is – without Roadworthy", "description": None})

    return tasks
