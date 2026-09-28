"""
WLAN Signal-Tester - Views Paket (ui/views/__init__.py)
Die drei Hauptansichten der Anwendung:
- SignalAnalyzerWidget (Signal-Analyzer & Echtzeit-Pegeldiagramm)
- NetzwerkDiagnoseWidget (Latenz- & Verbindungstests)
- GrundrissWidget (Heatmap-Erstellung auf Gebäudeplänen)
"""

from ui.views.analyzer_ansicht import SignalAnalyzerWidget
from ui.views.diagnose_ansicht import NetzwerkDiagnoseWidget, WlanDiagnoseFenster
from ui.views.grundriss_ansicht import GrundrissWidget, GrundrissFenster

__all__ = [
    "SignalAnalyzerWidget",
    "NetzwerkDiagnoseWidget",
    "WlanDiagnoseFenster",
    "GrundrissWidget",
    "GrundrissFenster",
]
