import os

VAPID_PUBLIC_KEY = os.getenv(
    "VAPID_PUBLIC_KEY",
    "BGktUs_1wJR2MiLC0jKo0Y1gpZteagH7n2B9rKPRYRR6_LJownew1N0zPtq5Rg6YBp3wyQgOUpjxWx3FzpfuZ8c",
)
VAPID_PRIVATE_KEY = os.getenv(
    "VAPID_PRIVATE_KEY",
    "vNQt1ig_vOuq9bz3aeY3TlMXxHqIcQ7G-MiXhC4Pzs0",
)
VAPID_EMAIL = os.getenv("VAPID_EMAIL", "mailto:admin@statustrucksales.co.za")
