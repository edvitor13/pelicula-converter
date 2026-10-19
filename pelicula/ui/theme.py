"""Cores, fontes e folha de estilo (tema escuro com acento âmbar)."""

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette

BG = "#0e0d0c"
PANEL = "#161412"
PANEL2 = "#1d1a17"
PANEL3 = "#25211d"
BORDER = "#2e2924"
TEXT = "#efe7da"
MUTED = "#9b8f80"
FAINT = "#6b6258"
ACCENT = "#f0a63a"
ACCENT_HI = "#ffc76b"
ACCENT_DIM = "#7a5320"
DANGER = "#e5534b"
OK = "#5cc48a"

# Linha do tempo do modo Edição
CLIP_VIDEO = "#a8692a"
CLIP_VIDEO_HI = "#d18a3f"
CLIP_IMAGE = "#8c6a3c"
CLIP_AUDIO = "#2c7a70"
CLIP_AUDIO_HI = "#3fa597"
TRACK_BG = "#141210"
TRACK_BG2 = "#181513"
PLAYHEAD = "#ffcf7a"


def ui_font() -> str:
    fams = set(QFontDatabase.families())
    for f in ("Segoe UI Variable Text", "Segoe UI", "Inter", "Helvetica Neue", "Arial"):
        if f in fams:
            return f
    return "Sans Serif"


def title_font() -> str:
    fams = set(QFontDatabase.families())
    for f in ("Bahnschrift", "Segoe UI Variable Display", "Segoe UI", "Arial"):
        if f in fams:
            return f
    return ui_font()


def font(size: float = 9.5, weight: QFont.Weight = QFont.Weight.Normal, title: bool = False) -> QFont:
    f = QFont(title_font() if title else ui_font())
    f.setPointSizeF(size)
    f.setWeight(weight)
    return f


def palette() -> QPalette:
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor(BG))
    p.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    p.setColor(QPalette.ColorRole.Base, QColor(PANEL2))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor(PANEL3))
    p.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    p.setColor(QPalette.ColorRole.Button, QColor(PANEL2))
    p.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    p.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#1a1206"))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor(PANEL3))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(FAINT))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(FAINT))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(FAINT))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(FAINT))
    return p


def stylesheet(arrow: str = "") -> str:
    f = ui_font()
    t = title_font()
    return f"""
* {{ font-family: "{f}"; font-size: 9.5pt; color: {TEXT}; }}
QMainWindow, QDialog {{ background: {BG}; }}
QToolTip {{ background: {PANEL3}; color: {TEXT}; border: 1px solid {BORDER}; padding: 6px 8px; border-radius: 6px; }}
QWidget#Panel {{ background: {PANEL}; }}
QWidget#TopBar {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; }}
QWidget#ViewerBar, QWidget#Transport {{ background: {PANEL}; }}
QLabel#Muted {{ color: {MUTED}; }}
QLabel#Faint {{ color: {FAINT}; font-size: 8.5pt; }}
QLabel#PanelTitle {{ font-family: "{t}"; font-size: 10.5pt; font-weight: 600; color: {TEXT}; letter-spacing: 0.5px; }}
QLabel#Kicker {{ font-family: "{t}"; font-size: 8pt; font-weight: 600; color: {ACCENT}; letter-spacing: 1.5px; }}
QLabel#Time {{ font-family: "Cascadia Mono", "Consolas", monospace; font-size: 9.5pt; color: {TEXT}; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {PANEL3}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {ACCENT_DIM}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {PANEL3}; border-radius: 4px; min-width: 30px; }}

QPushButton, QToolButton {{
    background: {PANEL2}; border: 1px solid {BORDER}; border-radius: 7px; padding: 6px 12px; color: {TEXT};
}}
QPushButton:hover, QToolButton:hover {{ background: {PANEL3}; border-color: #3d362f; }}
QPushButton:pressed, QToolButton:pressed {{ background: #2c2722; }}
QPushButton:disabled, QToolButton:disabled {{ color: {FAINT}; background: {PANEL}; }}
QPushButton#Primary {{ background: {ACCENT}; color: #1b1205; border: 1px solid {ACCENT}; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {ACCENT_HI}; border-color: {ACCENT_HI}; }}
QPushButton#Primary:disabled {{ background: {ACCENT_DIM}; color: #3a2a12; }}
QPushButton#Danger {{ color: {DANGER}; }}
QToolButton#Flat, QPushButton#Flat {{ background: transparent; border: 1px solid transparent; padding: 5px 8px; }}
QToolButton#Flat:hover, QPushButton#Flat:hover {{ background: {PANEL3}; border-color: {BORDER}; }}
QToolButton#Flat:checked {{ background: {PANEL3}; border-color: {ACCENT_DIM}; color: {ACCENT_HI}; }}
QToolButton#Seg {{ background: transparent; border: none; border-radius: 6px; padding: 5px 10px; color: {MUTED}; }}
QToolButton#Seg:hover {{ color: {TEXT}; background: {PANEL3}; }}
QToolButton#Seg:checked {{ color: #1b1205; background: {ACCENT}; font-weight: 600; }}
QFrame#SegBox {{ background: {PANEL2}; border: 1px solid {BORDER}; border-radius: 8px; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}

QComboBox {{
    background: {PANEL2}; border: 1px solid {BORDER}; border-radius: 7px; padding: 5px 10px; min-height: 18px;
}}
QComboBox:hover {{ border-color: #3d362f; }}
QComboBox:focus {{ border-color: {ACCENT_DIM}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url("{arrow}"); width: 10px; height: 10px; margin-right: 8px; }}
QComboBox QAbstractItemView {{
    background: {PANEL2}; border: 1px solid {BORDER}; selection-background-color: {PANEL3};
    selection-color: {ACCENT_HI}; outline: 0; padding: 4px;
}}
QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit {{
    background: {PANEL2}; border: 1px solid {BORDER}; border-radius: 7px; padding: 5px 8px;
    selection-background-color: {ACCENT}; selection-color: #1b1205;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {ACCENT_DIM}; }}
QLineEdit#Value {{ background: transparent; border: 1px solid transparent; border-radius: 5px; padding: 1px 4px;
    color: {TEXT}; font-family: "Cascadia Mono", "Consolas", monospace; font-size: 8.5pt; }}
QLineEdit#Value:hover {{ border-color: {BORDER}; background: {PANEL2}; }}
QLineEdit#Value:focus {{ border-color: {ACCENT_DIM}; background: {PANEL2}; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid #4a423a; background: {PANEL2}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QRadioButton::indicator {{ width: 14px; height: 14px; border-radius: 8px; border: 1px solid #4a423a; background: {PANEL2}; }}
QRadioButton::indicator:checked {{ background: {ACCENT}; border: 3px solid {PANEL2}; outline: 1px solid {ACCENT}; }}

QMenu {{ background: {PANEL2}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 5px; }}
QMenu::item:selected {{ background: {PANEL3}; color: {ACCENT_HI}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 8px; }}

QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QStatusBar {{ background: {PANEL}; border-top: 1px solid {BORDER}; color: {MUTED}; }}
QStatusBar QLabel {{ color: {MUTED}; font-size: 8.5pt; padding: 0 6px; }}
QProgressBar {{ background: {PANEL3}; border: none; border-radius: 4px; height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT}, stop:1 {ACCENT_HI}); border-radius: 4px; }}
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 10px; margin-top: 14px; padding: 12px 10px 10px 10px; background: {PANEL}; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {ACCENT}; font-family: "{t}"; font-weight: 600; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 8px; }}
QTabBar::tab {{ background: transparent; padding: 7px 14px; color: {MUTED}; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
"""
