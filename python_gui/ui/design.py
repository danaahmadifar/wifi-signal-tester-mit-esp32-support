"""
WLAN Signal-Tester - Gestaltungsvorlage (design.py)
Definiert das kontrastoptimierte dunkle Farbschema (QSS) fuer alle Fenster und Bedienelemente.
"""

DUNKLES_DESIGN = """
/* Hauptfenster & allgemeine Elemente */
QWidget {
    background-color: #0c0c0c;
    color: #e0e0e0;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 12px;
}
QMainWindow {
    background-color: #080808;
}
QStatusBar {
    background-color: #111111;
    color: #888888;
    border-top: 1px solid #222222;
}

/* Rahmen & Gruppen */
QFrame.CardFrame, QFrame.MetricCard, QFrame.TargetPanel, QGroupBox {
    background-color: #141414;
    border: 1px solid #262626;
    border-radius: 4px;
}
QGroupBox {
    margin-top: 16px;
    padding-top: 12px;
    font-weight: 600;
    font-size: 11px;
    color: #a0a0a0;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    background-color: #141414;
}

/* Buttons */
QPushButton {
    background-color: #202020;
    color: #dddddd;
    border: 1px solid #333333;
    border-radius: 4px;
    padding: 4px 10px;
    font-weight: 500;
    min-height: 22px;
}
QPushButton:hover {
    background-color: #2c2c2c;
    border-color: #4a4a4a;
    color: #ffffff;
}
QPushButton:pressed {
    background-color: #161616;
}
QPushButton:disabled {
    background-color: #141414;
    color: #4a4a4a;
}
QPushButton.PrimaryButton {
    background-color: #1e3a5f;
    color: #ffffff;
    border: 1px solid #2563eb;
    font-weight: 600;
}
QPushButton.PrimaryButton:hover {
    background-color: #2563eb;
}
QPushButton.DangerButton {
    background-color: #451313;
    color: #ff9999;
    border: 1px solid #7f1d1d;
    font-weight: 600;
}
QPushButton.DangerButton:hover {
    background-color: #7f1d1d;
    color: #ffffff;
}

/* Eingabefelder & Auswahllisten */
QLineEdit, QComboBox {
    background-color: #0d0d0d;
    border: 1px solid #2b2b2b;
    border-radius: 4px;
    padding: 3px 6px;
    color: #e0e0e0;
    min-height: 22px;
}
QSpinBox {
    background-color: #0d0d0d;
    border: 1px solid #2b2b2b;
    border-radius: 4px;
    padding: 3px 20px 3px 6px;
    color: #e0e0e0;
    min-height: 22px;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #3b82f6;
    background-color: #101010;
}
QSpinBox::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 18px;
    border-left: 1px solid #333333;
    border-bottom: 1px solid #222222;
    background-color: #1a1a1a;
}
QSpinBox::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 18px;
    border-left: 1px solid #333333;
    background-color: #1a1a1a;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background-color: #2e2e2e;
}
QComboBox {
    padding-right: 24px;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border-left: 1px solid #333333;
    background-color: #1c1c1c;
}
QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #e0e0e0;
}
QComboBox QAbstractItemView {
    background-color: #141414;
    border: 1px solid #333333;
    selection-background-color: #2563eb;
    color: #e0e0e0;
}

/* Signalbalken & Auswahlkaestchen */
QProgressBar {
    background-color: #1a1a1a;
    border: 1px solid #2b2b2b;
    border-radius: 3px;
    text-align: center;
    color: #ffffff;
    font-size: 10px;
    height: 12px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 #dc2626, stop:0.4 #eab308,
                                stop:0.75 #22c55e, stop:1.0 #06b6d4);
    border-radius: 2px;
}
QCheckBox {
    spacing: 5px;
    color: #cccccc;
}
QCheckBox::indicator:checked {
    background-color: #2563eb;
    border: 1px solid #3b82f6;
}

/* Status-Anzeigen */
QLabel.ModBadge {
    background-color: #1c1c1c;
    border: 1px solid #3a3a3a;
    color: #ffffff;
    border-radius: 3px;
    padding: 2px 6px;
    font-weight: 700;
    font-family: monospace;
}
QLabel.StatusConnected {
    color: #22c55e;
    font-weight: 600;
    padding: 3px 8px;
    border-radius: 3px;
    background-color: #0f2316;
    border: 1px solid #14532d;
}
QLabel.StatusDisconnected {
    color: #888888;
    font-weight: 600;
    padding: 3px 8px;
    border-radius: 3px;
    background-color: #181818;
    border: 1px solid #2b2b2b;
}
"""
