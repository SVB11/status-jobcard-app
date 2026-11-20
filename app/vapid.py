import logging
import os

logger = logging.getLogger(__name__)

VAPID_PUBLIC_KEY = (os.getenv("VAPID_PUBLIC_KEY") or "").strip() or None
VAPID_PRIVATE_KEY = (os.getenv("VAPID_PRIVATE_KEY") or "").strip() or None
VAPID_EMAIL = os.getenv("VAPID_EMAIL", "mailto:admin@statustrucksales.co.za")
PUSH_ENABLED = bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY)

if not PUSH_ENABLED:
    logger.warning(
        "VAPID_PRIVATE_KEY/VAPID_PUBLIC_KEY missing - push notifications disabled"
    )
