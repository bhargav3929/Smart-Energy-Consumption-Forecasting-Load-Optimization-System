"""Four one-click demo presets. Fields: appliance, watts, hours_per_day, peak_hour (preferred start hour), shiftable."""


def _r(name, watts, hours, start, shiftable):
    return {"name": name, "watts": watts, "hours_per_day": hours, "peak_hour": start, "shiftable": shiftable}


PRESETS = [
    {
        "id": "household-hyd",
        "title": "3BHK Smart Household — Hyderabad, India (AC, Geyser, EV Charger, Refrigerator, Washing Machine)",
        "short": "3BHK Household",
        "city": "Hyderabad",
        "appliances": [
            _r("Air Conditioner (1.5 ton)", 1500, 8, 21, False),
            _r("Geyser (Water Heater)", 2000, 1.5, 19, True),
            _r("EV Charger (3.3 kW)", 3300, 4, 19, True),
            _r("Refrigerator", 75, 24, 0, False),
            _r("Washing Machine", 500, 1.5, 18, True),
            _r("Fans & Lighting", 250, 7, 18, False),
        ],
    },
    {
        "id": "campus-blr",
        "title": "University Computer Lab & Hostel Block — Bengaluru, India (45 Workstations, Central HVAC, Water Heaters)",
        "short": "Campus Lab & Hostel",
        "city": "Bengaluru",
        "appliances": [
            _r("45 Lab Workstations (120 W each)", 5400, 9, 9, False),
            _r("Central HVAC", 9000, 10, 9, False),
            _r("Hostel Water Heaters", 12000, 3, 18, True),
            _r("Lab & Hostel Lighting", 3000, 12, 17, False),
            _r("Water Pump", 1500, 2, 18, True),
            _r("Network & Server Rack", 800, 24, 0, False),
        ],
    },
    {
        "id": "apartment-maa",
        "title": "2BHK Apartment Summer Peak — Chennai, India (2x Split AC, Induction Stove, Microwave, Mixer)",
        "short": "2BHK Summer Peak",
        "city": "Chennai",
        "appliances": [
            _r("Split AC #1 (Bedroom)", 1600, 9, 21, False),
            _r("Split AC #2 (Hall)", 1400, 7, 19, False),
            _r("Induction Stove", 1800, 2, 19, False),
            _r("Microwave Oven", 1200, 0.5, 19, False),
            _r("Mixer Grinder", 500, 0.5, 18, True),
            _r("Refrigerator", 85, 24, 0, False),
            _r("Water Pump", 750, 1, 18, True),
        ],
    },
    {
        "id": "clinic-pune",
        "title": "Small Retail Clinic & Pharmacy — Pune, India (Medical Chiller, HVAC, Lighting, Autoclave)",
        "short": "Clinic & Pharmacy",
        "city": "Pune",
        "appliances": [
            _r("Medical Vaccine Chiller", 200, 24, 0, False),
            _r("Clinic HVAC", 5500, 10, 9, False),
            _r("Clinic & Shop Lighting", 1200, 11, 9, False),
            _r("Autoclave Sterilizer", 3000, 2, 17, True),
            _r("Pharmacy Display Fridge", 300, 24, 0, False),
            _r("Water Heater", 1500, 2, 18, True),
        ],
    },
]
