"""
Combined PDI Checklists taken exactly from GROK PDI LISTS.xlsx
(Truck / Tanker / Trailer & Tipper). Status: Pass / Fail / N/A
"""

TRUCK_PDI = [
    {"section": '1. WHEELS, TYRES & RIMS', "items": [
        {"num": 1, "item": 'Wheel nuts fastened', "criteria": 'All wheel nuts torqued to manufacturer specification. No looseness or missing nuts.'},
        {"num": 2, "item": 'Wheel studs condition', "criteria": 'Studs undamaged, correct length, threads clean and serviceable.'},
        {"num": 3, "item": 'Tyres – condition & pressure', "criteria": 'Tread depth ≥ 2 mm (legal min), even wear, correct pressure, no cuts, bulges, exposed cords or damage.'},
        {"num": 4, "item": 'Rims / Wheels', "criteria": 'No cracks, dents, elongation of stud holes. Secure and true.'},
        {"num": 5, "item": 'Mudguards (front & rear)', "criteria": 'Securely fitted, undamaged, provide proper coverage.'},
        {"num": 6, "item": 'Mudflaps', "criteria": 'Fitted as required (4/6/8 depending on configuration). Secure and intact.'},
        {"num": 7, "item": 'Mudguard end caps', "criteria": 'Fitted and secure where applicable.'},
        {"num": 8, "item": 'Wheel indicators / markers', "criteria": 'Fitted and functional (where equipped).'},
    ]},
    {"section": '2. BRAKES & AIR SYSTEM', "items": [
        {"num": 9, "item": 'Service brakes', "criteria": 'Pads/linings adequate thickness, drums/discs serviceable, lines free of leaks, pedal firm with good feel.'},
        {"num": 10, "item": 'Brake boosters / chambers', "criteria": 'No air leaks, proper operation, mounting secure.'},
        {"num": 11, "item": 'ABS system', "criteria": 'Warning light extinguishes correctly, system functional (no fault codes).'},
        {"num": 12, "item": 'Air system', "criteria": 'Builds to cut-out pressure promptly, no audible/visible leaks, low-air warning alarm functional.'},
        {"num": 13, "item": 'Hand / park brake', "criteria": 'Holds vehicle securely on incline, handle/lever operation correct, no excessive travel.'},
        {"num": 14, "item": 'Air leaks check', "criteria": 'Full system pressure test – no leaks at fittings, valves, tanks or lines.'},
    ]},
    {"section": '3. SUSPENSION & RUNNING GEAR', "items": [
        {"num": 15, "item": 'Suspension overall', "criteria": 'No cracks, broken leaves, bent components, or excessive wear. Mountings secure.'},
        {"num": 16, "item": 'Airbags (if equipped)', "criteria": 'No cracks, leaks, damage or chafing. Inflate correctly.'},
        {"num": 17, "item": 'Shock absorbers', "criteria": 'No oil leaks, bushes free of cracks/tears/play, mounting secure.'},
        {"num": 18, "item": 'Lift axle (if equipped)', "criteria": 'Raises and lowers smoothly, holds position, no leaks.'},
    ]},
    {"section": '4. LIGHTS, INDICATORS & ELECTRICAL', "items": [
        {"num": 19, "item": 'Headlights', "criteria": 'High and low beam operational and correctly aligned.'},
        {"num": 20, "item": 'Indicators / hazard lights', "criteria": 'All front, side and rear indicators function correctly.'},
        {"num": 21, "item": 'Side marker lights', "criteria": 'All functional and correctly coloured.'},
        {"num": 22, "item": 'Tail lights, brake lights, reverse lights', "criteria": 'All operational.'},
        {"num": 23, "item": 'Fog lights (if fitted)', "criteria": 'Operational.'},
        {"num": 24, "item": 'Reverse buzzer / alarm', "criteria": 'Activates correctly when reverse selected.'},
        {"num": 25, "item": 'Interior lights & dashboard', "criteria": 'All functional, no warning lights remaining after start-up (except as designed).'},
        {"num": 26, "item": 'Battery condition', "criteria": 'Tested with battery tester – report attached if required. Terminals clean and tight.'},
        {"num": 27, "item": 'Battery isolator switch', "criteria": 'Present, functional (On/Off), correctly labelled.'},
        {"num": 28, "item": 'Charge line (trailer)', "criteria": 'Present, secure, correct connection.'},
        {"num": 29, "item": 'Electrical mirrors (if fitted)', "criteria": 'Adjustment and heating (if equipped) operational.'},
        {"num": 30, "item": 'Windows operation', "criteria": 'All windows open/close correctly, no binding.'},
        {"num": 31, "item": 'Wipers & washers', "criteria": 'Blades serviceable, wipe correctly, washer fluid sprays, reservoir filled.'},
    ]},
    {"section": '5. CAB, INTERIOR & CONTROLS', "items": [
        {"num": 32, "item": 'Interior cleanliness', "criteria": 'Cab vacuumed/cleaned, no rubbish, no strong odours.'},
        {"num": 33, "item": 'Seats', "criteria": 'Adjustment and locking mechanisms operational, seatbelts present and functional.'},
        {"num": 34, "item": 'Safety belts', "criteria": 'All belts retract and latch correctly, no fraying or damage.'},
        {"num": 35, "item": 'Doors & locks', "criteria": 'Driver and passenger doors lock/unlock with key, latches secure.'},
        {"num": 36, "item": 'Windscreen', "criteria": 'No cracks or chips in critical vision area. Wipers and demister functional.'},
        {"num": 37, "item": 'Mirrors', "criteria": 'Securely mounted, correctly adjusted, no cracks affecting vision.'},
        {"num": 38, "item": 'Air conditioning / heater', "criteria": 'Operational and effective.'},
        {"num": 39, "item": 'Fault codes on cluster', "criteria": 'No active fault codes displayed (or recorded and addressed).'},
        {"num": 40, "item": 'Document box', "criteria": 'Fitted, secure, undamaged, and contains required documents.'},
    ]},
    {"section": '6. BODY, CHASSIS & CLEANLINESS', "items": [
        {"num": 41, "item": 'Exterior cleanliness', "criteria": 'Vehicle washed – exterior free of excessive dirt, grease and debris.'},
        {"num": 42, "item": 'Chassis spray / underbody protection', "criteria": 'Applied evenly where specified.'},
        {"num": 43, "item": 'Cab spray / paintwork', "criteria": 'Applied evenly, no major defects or incomplete areas.'},
        {"num": 44, "item": 'Oil leaks (visible)', "criteria": 'No visible oil leaks from engine, transmission, differentials or hydraulic components.'},
        {"num": 45, "item": 'Diesel / fuel cap', "criteria": 'Present, seals correctly, opens with key if locking type.'},
    ]},
    {"section": '7. SAFETY EQUIPMENT & TOOLS', "items": [
        {"num": 46, "item": 'Warning triangle', "criteria": 'Present, reflective, undamaged, stored correctly.'},
        {"num": 47, "item": 'Fire extinguisher (cab) 2.5 kg', "criteria": 'Fitted, charged, valid service date, accessible.'},
        {"num": 48, "item": 'Fire extinguisher (rear) 9 kg (if required)', "criteria": 'Fitted, charged, valid service date.'},
        {"num": 49, "item": 'Jack', "criteria": 'Present and serviceable.'},
        {"num": 50, "item": 'Wheel spanner / tools', "criteria": 'Present and fits wheel nuts.'},
        {"num": 51, "item": 'Chevron board', "criteria": 'Present, correctly fitted, reflective and visible.'},
        {"num": 52, "item": 'Reflective tape (cab & chassis)', "criteria": 'Fitted as required by regulation, clean and intact.'},
        {"num": 53, "item": '80 km/h sticker', "criteria": 'Fitted on rear of cab if required for the vehicle.'},
        {"num": 54, "item": 'Orange triangle (front)', "criteria": 'Fitted if required.'},
        {"num": 55, "item": 'Battery isolator sticker / On-Off labels', "criteria": 'Correctly fitted and legible.'},
    ]},
    {"section": '8. FIFTH WHEEL, HYDRAULICS & PTO', "items": [
        {"num": 56, "item": 'Fifth wheel', "criteria": 'Securely mounted, no excessive wear on jaws/plate, correctly greased, locking mechanism functional.'},
        {"num": 57, "item": 'Earth cable (5th wheel)', "criteria": 'Fitted and in good condition where required.'},
        {"num": 58, "item": 'Hydraulics (if equipped)', "criteria": 'Fluid level correct, no leaks on pipes/rams, rams operate smoothly.'},
        {"num": 59, "item": 'PTO', "criteria": 'Pipe fittings secure, PTO engages and operates correctly.'},
        {"num": 60, "item": 'Printer (if equipped)', "criteria": 'Securely fitted and functional.'},
    ]},
    {"section": '9. FINAL WORKSHOP CHECKS', "items": [
        {"num": 61, "item": 'Worklist / repair list completed', "criteria": 'All listed repairs and items completed and signed off.'},
        {"num": 62, "item": 'Worksheet up to date', "criteria": 'Accurate, current, and filed correctly.'},
        {"num": 63, "item": 'Water levels', "criteria": 'Radiator / coolant, windscreen washer, and engine oil checked (dipstick or electronic).'},
        {"num": 64, "item": 'Battery terminals', "criteria": 'Clean, tight, and protected.'},
    ]},
]

TANKER_PDI = [
    {"section": '1. WHEELS, TYRES & RIMS', "items": [
        {"num": 1, "item": 'Wheel nuts fastened', "criteria": 'All wheel nuts torqued to specification. No looseness.'},
        {"num": 2, "item": 'Wheel studs condition', "criteria": 'Undamaged threads, correct length, serviceable.'},
        {"num": 3, "item": 'Tyres – condition & pressure', "criteria": 'Tread depth ≥ 2 mm, even wear, correct pressure, no damage/bulges/cuts.'},
        {"num": 4, "item": 'Rims / Wheels', "criteria": 'No cracks, dents or damage. Secure.'},
        {"num": 5, "item": 'Mudguards (front & rear)', "criteria": 'Secure, undamaged, proper coverage.'},
        {"num": 6, "item": 'Mudflaps', "criteria": 'Fitted as required (4/6/8). Secure.'},
        {"num": 7, "item": 'Mudguard end caps', "criteria": 'Fitted where applicable.'},
        {"num": 8, "item": 'Wheel indicators / markers', "criteria": 'Fitted and functional.'},
    ]},
    {"section": '2. BRAKES & AIR SYSTEM', "items": [
        {"num": 9, "item": 'Service brakes', "criteria": 'Pads/drums adequate, lines free of leaks, firm pedal.'},
        {"num": 10, "item": 'Brake boosters / chambers', "criteria": 'No leaks, proper operation.'},
        {"num": 11, "item": 'ABS system', "criteria": 'Warning lights off, system functional.'},
        {"num": 12, "item": 'Air system', "criteria": 'Builds pressure correctly, no leaks, low-air alarm works.'},
        {"num": 13, "item": 'Air leaks check', "criteria": 'Full system check – no leaks.'},
        {"num": 14, "item": 'Remove all strikers from air pipes', "criteria": 'All protective strikers/caps removed from air connections.'},
    ]},
    {"section": '3. SUSPENSION & RUNNING GEAR', "items": [
        {"num": 15, "item": 'Suspension overall', "criteria": 'No cracks, leaks or damage. Mountings secure.'},
        {"num": 16, "item": 'Airbags (if equipped)', "criteria": 'No cracks, leaks or damage. Inflate correctly.'},
        {"num": 17, "item": 'Shock absorbers', "criteria": 'Bushes free of cracks/tears/play; shocks no leaks or damage.'},
        {"num": 18, "item": 'Lift axle (if equipped)', "criteria": 'Raises/lowers smoothly, holds position.'},
        {"num": 19, "item": 'Tanker ride height / level valves', "criteria": 'Correct height achieved by adjusting level valves for airbags.'},
    ]},
    {"section": '4. LIGHTS & ELECTRICAL', "items": [
        {"num": 20, "item": 'Indicators / hazards', "criteria": 'All function correctly.'},
        {"num": 21, "item": 'Side marker lights & rear tail lights', "criteria": 'All functional.'},
        {"num": 22, "item": 'Reverse buzzer', "criteria": 'Activates correctly.'},
        {"num": 23, "item": 'Power cable / screen / electrical connections', "criteria": 'Secure, complete and functional (incl. ABS/EBS trailer plug if applicable).'},
        {"num": 24, "item": 'Light switch / control box', "criteria": 'Functional.'},
        {"num": 25, "item": 'No loose hanging pipes or wiring', "criteria": 'All secured and clipped correctly.'},
    ]},
    {"section": '5. TANK & CARGO SYSTEM', "items": [
        {"num": 26, "item": 'Tank shell, welds & valves – leaks', "criteria": 'Visual and soap test – no leaks on shell, welds, valves or fittings.'},
        {"num": 27, "item": 'SLP Pressure Test', "criteria": 'Completed and passed – no pressure drop. Certificate available if required.'},
        {"num": 28, "item": 'Calibration', "criteria": 'Tank / meter calibrated and accurate. Certificate current.'},
        {"num": 29, "item": 'API dust caps', "criteria": 'Present, secure and undamaged.'},
        {"num": 30, "item": 'Delivery nozzle & spouts', "criteria": 'Functional, no leaks, spouts intact.'},
        {"num": 31, "item": 'Vent caps', "criteria": 'Secure and functional.'},
        {"num": 32, "item": 'Optic & thermistor dust caps (Scully / overfill plug)', "criteria": 'Present and undamaged.'},
        {"num": 33, "item": 'Delivery hose', "criteria": 'Good condition, no cracks or damage, stored securely.'},
        {"num": 34, "item": 'PTO delivery hose / pipes', "criteria": 'No damage, couplings secure.'},
        {"num": 35, "item": 'Couplings – condition', "criteria": 'Teeth undamaged, secure engagement.'},
        {"num": 36, "item": 'Delivery hose coupler teeth', "criteria": 'Inspected – no damage or excessive wear.'},
        {"num": 37, "item": 'Dome cover / manhole', "criteria": 'Secure, key present if locking type.'},
        {"num": 38, "item": 'Pneumatic pipe straps', "criteria": 'Secure, no loose pipes.'},
        {"num": 39, "item": 'Straps for delivery hose & PTO pipes', "criteria": 'Fitted and secure.'},
        {"num": 40, "item": 'End caps on side rails', "criteria": 'Fitted and secure.'},
        {"num": 65, "item": 'Are all barrel test plates fitted on tanker? (3 / 6 year and 15 year)', "criteria": '3-year, 6-year and 15-year barrel test plates fitted on the tanker as applicable.'},
    ]},
    {"section": '6. HAZCHEM, SAFETY & EARTHING', "items": [
        {"num": 41, "item": 'Yellow tape / Hazchem markings', "criteria": 'Correct labels, visible and intact.'},
        {"num": 42, "item": 'Hazchem boards', "criteria": 'Present, correct and securely fitted.'},
        {"num": 43, "item": 'Hazchem sticker on tank', "criteria": 'Applied correctly and legible.'},
        {"num": 44, "item": 'No smoking / cellphones / open flames sticker', "criteria": 'Present and visible.'},
        {"num": 45, "item": 'Earth reel cable & clamp', "criteria": 'Secure, no damage, full length serviceable.'},
        {"num": 46, "item": 'Bartec / earthing cable', "criteria": 'Present and functional.'},
        {"num": 47, "item": 'Bonding points', "criteria": 'Clean, accessible and functional.'},
        {"num": 48, "item": 'Earth reel sticker / Bonding point sticker', "criteria": 'Fitted and legible.'},
        {"num": 49, "item": 'Emergency stop buttons', "criteria": 'Functional and correctly labelled.'},
        {"num": 50, "item": 'Emergency stop sticker', "criteria": 'Present.'},
        {"num": 51, "item": 'Trailer / park brake sticker', "criteria": 'Present.'},
        {"num": 52, "item": 'Chock blocks', "criteria": 'Present (minimum 2), secure storage.'},
        {"num": 53, "item": 'Cones (6x)', "criteria": 'Fitted / present as required.'},
        {"num": 54, "item": 'Fire extinguisher box', "criteria": 'Present and secure.'},
        {"num": 55, "item": 'Fire extinguishers (x2 – typically 9 kg)', "criteria": 'Present, charged, valid expiry/service dates, correctly mounted.'},
    ]},
    {"section": '7. BODY, CLEANLINESS & STICKERS', "items": [
        {"num": 56, "item": 'Vehicle exterior clean', "criteria": 'Washed and presentable.'},
        {"num": 57, "item": 'Tank spray / coating', "criteria": 'Applied evenly where specified.'},
        {"num": 58, "item": 'Chassis spray', "criteria": 'Applied evenly.'},
        {"num": 59, "item": 'Interior cab clean', "criteria": 'Vacuumed, no odours.'},
        {"num": 60, "item": 'Reflective tape', "criteria": 'Fitted as required, clean and intact.'},
        {"num": 61, "item": '80 km/h sticker (rear of tank)', "criteria": 'Fitted if required.'},
        {"num": 62, "item": 'Oil leaks non-visible', "criteria": 'No visible leaks from running gear or systems.'},
        {"num": 63, "item": 'Fifth wheel', "criteria": 'Secure, no excessive wear, greased.'},
        {"num": 64, "item": 'Hydraulics (if equipped)', "criteria": 'Fluid level correct, no leaks, rams operational.'},
    ]},
]

TRAILER_PDI = [
    {"section": '1. WHEELS, TYRES & RIMS', "items": [
        {"num": 1, "item": 'Wheel nuts fastened', "criteria": 'Torqued to specification. No looseness.'},
        {"num": 2, "item": 'Wheel studs condition', "criteria": 'Undamaged, correct length.'},
        {"num": 3, "item": 'Tyres – condition & pressure', "criteria": 'Tread depth ≥ 2 mm, even wear, correct pressure, no damage/bulges.'},
        {"num": 4, "item": 'Rims / Wheels', "criteria": 'Secure, no cracks or dents.'},
        {"num": 5, "item": 'Mudguards & mudflaps', "criteria": 'Front & rear mudguards and mudflaps fitted and secure.'},
        {"num": 6, "item": 'Wheel markers', "criteria": 'Fitted where required.'},
    ]},
    {"section": '2. BRAKES & AIR SYSTEM', "items": [
        {"num": 7, "item": 'Brakes', "criteria": 'Lines free of leaks, chambers secure and serviceable.'},
        {"num": 8, "item": 'Air system', "criteria": 'Connections secure, no leaks, system builds and holds pressure.'},
        {"num": 9, "item": 'ABS / EBS', "criteria": 'Connections functional, no fault indications.'},
        {"num": 10, "item": 'Park brake', "criteria": 'Holds correctly. Sticker present if required.'},
    ]},
    {"section": '3. SUSPENSION & RUNNING GEAR', "items": [
        {"num": 11, "item": 'Suspension overall', "criteria": 'No cracks, leaks or damage.'},
        {"num": 12, "item": 'Airbags (if equipped)', "criteria": 'No cracks, leaks or damage. Correct inflation.'},
        {"num": 13, "item": 'Shock absorbers', "criteria": 'Bushes OK, no leaks or damage.'},
        {"num": 14, "item": 'Lift axle (if equipped)', "criteria": 'Functional – raises and lowers correctly.'},
        {"num": 15, "item": 'Landing legs', "criteria": 'Operate smoothly, secure in raised and lowered positions, no damage.'},
    ]},
    {"section": '4. COUPLING & STRUCTURE', "items": [
        {"num": 16, "item": 'Fifth wheel / kingpin', "criteria": 'No excessive wear, locking mechanism functional, correctly greased.'},
        {"num": 17, "item": 'No loose hanging pipes or wiring', "criteria": 'All secured and clipped.'},
        {"num": 18, "item": 'Spare wheel', "criteria": 'Present, correctly mounted, secure.'},
        {"num": 19, "item": 'Spare wheel hangers / carrier', "criteria": 'Secure and serviceable.'},
    ]},
    {"section": '5. TIPPER SPECIFIC (if applicable)', "items": [
        {"num": 20, "item": 'Tipper lift cylinder(s)', "criteria": 'Operation smooth, no oil leaks on pipes or glands.'},
        {"num": 21, "item": 'Tipper hydraulics', "criteria": 'Fluid level correct, no leaks, full raise/lower cycle tested.'},
        {"num": 22, "item": 'Chock blocks & holding brackets', "criteria": 'Present and fitted correctly.'},
        {"num": 23, "item": 'Sails / covers (if fitted)', "criteria": 'No holes or major damage, strap-down points secure.'},
        {"num": 24, "item": 'Belt / ratchets to lock sails', "criteria": 'Present and functional.'},
    ]},
    {"section": '6. TAUTLINER / CURTAINSIDER (if applicable)', "items": [
        {"num": 25, "item": 'Tautliner side sails / curtains', "criteria": 'Operate freely, no major tears or damage.'},
        {"num": 26, "item": 'Belts, buckles & ratchets', "criteria": 'Present, secure and lock correctly.'},
    ]},
    {"section": '7. SAFETY EQUIPMENT & MARKINGS', "items": [
        {"num": 27, "item": 'Warning triangle', "criteria": 'Present.'},
        {"num": 28, "item": 'Fire extinguisher(s)', "criteria": 'Present, charged, valid dates.'},
        {"num": 29, "item": 'Chevron board', "criteria": 'Present, reflective and correctly fitted.'},
        {"num": 30, "item": 'Chock blocks', "criteria": 'Present.'},
        {"num": 31, "item": 'Reflective tape', "criteria": 'Fitted as required.'},
        {"num": 32, "item": '80 km/h sticker', "criteria": 'Fitted if required.'},
        {"num": 33, "item": 'Trailer park brake sticker', "criteria": 'Present.'},
    ]},
    {"section": '8. TANKER TRAILER ITEMS (if applicable)', "items": [
        {"num": 34, "item": 'Tank / trailer leaks', "criteria": 'No visible leaks on shell, valves or fittings.'},
        {"num": 35, "item": 'Hazchem / yellow tape / boards', "criteria": 'Correct and present.'},
    ]},
    {"section": '9. CLEANLINESS & FINAL', "items": [
        {"num": 36, "item": 'Vehicle clean & spray applied', "criteria": 'Exterior washed, chassis/body spray applied as required.'},
        {"num": 37, "item": 'Overall condition', "criteria": 'No obvious damage or incomplete work that would prevent safe handover.'},
    ]},
]


def get_pdi_for_type(main_type: str):
    main_type = (main_type or "").strip()
    if main_type == "Tanker":
        return TANKER_PDI
    if main_type in ("Trailer", "Tipper"):
        return TRAILER_PDI
    # Truck Tractor and Other use the truck PDI
    return TRUCK_PDI
