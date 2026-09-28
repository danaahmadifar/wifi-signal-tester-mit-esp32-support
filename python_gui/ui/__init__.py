"""
WLAN Signal-Tester - UI Paket (ui/__init__.py)
Design, Sprachen, UI-Komponenten und Ansichten.
"""

from ui.design import DUNKLES_DESIGN
from ui.sprachen import tr, set_language, is_rtl, LANGUAGES
from ui.komponenten import StatusKartenWidget, ZielKonfigWidget

__all__ = [
    "DUNKLES_DESIGN",
    "tr",
    "set_language",
    "is_rtl",
    "LANGUAGES",
    "StatusKartenWidget",
    "ZielKonfigWidget",
]
