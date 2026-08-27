"""
Sales-facing Work / Prep instructions.
These are the company pre-approved options a salesman ticks on create.
"""

def get_tasks_for_vehicle(main_type: str, year: str = None) -> list:
    main_type = (main_type or "").strip()

    common = [
        {"task_name": "Roadworthy", "description": "Prepare and take the vehicle for roadworthy"},
        {"task_name": "Brake tests", "description": "Brake test to be done before delivery"},
        {"task_name": "Wash / clean for delivery", "description": "Wash and present the vehicle for handover"},
        {"task_name": "Touch-ups", "description": "Paint / body touch-ups as needed"},
        {"task_name": "Polish", "description": "Polish cab / body for delivery"},
        {"task_name": "Spray rims", "description": "Spray or refurbish rims"},
    ]

    tanker = [
        {"task_name": "Pressure test (SLP)", "description": "Book SLP pressure test before delivery"},
        {"task_name": "Barrel test - 3 year", "description": "3-year barrel test required"},
        {"task_name": "Barrel test - 6 year", "description": "6-year barrel test required"},
        {"task_name": "Barrel test - 3 and 6 year", "description": "Both 3-year and 6-year barrel tests"},
        {"task_name": "Calibration (if fitted with meters)", "description": "Calibrate meters if fitted"},
        {"task_name": "DEKRA spec", "description": "Prepare to DEKRA spec (normal for fuel tankers)"},
    ]

    truck = [
        {"task_name": "Fuel Spec", "description": "Prepare truck tractor to fuel spec"},
        {"task_name": "DEKRA Spec", "description": "Prepare truck tractor to DEKRA spec"},
        {"task_name": "Full refurbishment", "description": "Full workshop refurbishment before delivery"},
        {"task_name": "Already refurbished", "description": "Refurbishment already done — no further refurb work"},
        {"task_name": "Service before delivery", "description": "Workshop service before handover"},
    ]

    trailer = [
        {"task_name": "Full refurbishment", "description": "Full workshop refurbishment before delivery"},
        {"task_name": "Already refurbished", "description": "Refurbishment already done — no further refurb work"},
        {"task_name": "Tautliner / sail work", "description": "Sails, belts and ratchets to be checked or repaired"},
        {"task_name": "Tipper bin / hydraulics check", "description": "Tipper cylinder, pipes and bin condition"},
        {"task_name": "Side tipper tarps", "description": "Side tipper tarps to be fitted, repaired or checked"},
        {"task_name": "Crack repairs", "description": "Crack repairs on bin / body / chassis as required"},
    ]

    as_is = [
        {"task_name": "As Is – with Roadworthy only", "description": "Sell as is. Only roadworthy to be done"},
        {"task_name": "As Is – without Roadworthy", "description": "Sell as is. No roadworthy"},
    ]

    tasks = []
    if main_type == "Tanker":
        tasks.extend(tanker)
        try:
            vehicle_year = int(year) if year else 0
            if vehicle_year and 2026 - vehicle_year >= 15:
                tasks.append({"task_name": "Barrel test - 15 year", "description": "Vehicle is 15 years or older — 15-year barrel test applies"})
        except (ValueError, TypeError):
            pass
        tasks.extend(common)
    elif main_type == "Truck Tractor":
        tasks.extend(common)
        tasks.extend(truck)
    elif main_type in ("Trailer", "Tipper"):
        tasks.extend(common)
        tasks.extend(trailer)
    else:
        tasks.extend(common)
        tasks.extend(truck)

    tasks.extend(as_is)
    return tasks
