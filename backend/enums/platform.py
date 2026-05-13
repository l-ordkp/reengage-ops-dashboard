"""Delivery platforms supported."""
from enum import Enum


class Platform(str, Enum):
    DOORDASH = "Doordash"
    UBEREATS = "UberEats"


# Days within which the platform allows a reply
RESPONSE_WINDOW_DAYS = {
    Platform.DOORDASH: 7,
    Platform.UBEREATS: 14,
}
