# Colour palette — mirrors the React CSS variables exactly
# --background: 222 47% 6%   → #080e1a
# --card:       222 44% 8%   → #0c1421
# --secondary:  217 33% 14%  → #182537
# --border:     217 33% 18%  → #1e2d3f
# --primary:    142 71% 45%  → #22c55e  (green)
# --accent:      45 93% 58%  → #eab308  (gold)
# --destructive:  0 84% 60%  → #ef4444  (red)
# --foreground: 210 40% 96%  → #e2e8f0
# --muted-fg:   215 20% 55%  → #7a8fa6

COLOR_GREEN  = "#22c55e"
COLOR_RED    = "#ef4444"
COLOR_GOLD   = "#eab308"
COLOR_BLUE   = "#74c0fc"   # kept for legacy references
COLOR_MUTED  = "#7a8fa6"
COLOR_FG     = "#e2e8f0"
COLOR_BG     = "#080e1a"
COLOR_PANEL  = "#0c1421"
COLOR_CARD   = "#182537"
COLOR_BORDER = "#1e2d3f"

DARK_THEME = """
/* ── Base ─────────────────────────────────────────────────────────── */
QMainWindow, QDialog {
    background-color: #080e1a;
}

QWidget {
    background-color: #080e1a;
    color: #e2e8f0;
    font-family: 'Inter', 'Segoe UI', sans-serif;
    font-size: 13px;
}

/* ── Tabs ─────────────────────────────────────────────────────────── */
QTabWidget::pane {
    border: 1px solid #1e2d3f;
    border-top: none;
    background-color: #080e1a;
}

QTabBar {
    background: transparent;
}

QTabBar::tab {
    background-color: #0c1421;
    color: #7a8fa6;
    padding: 9px 20px;
    border: 1px solid #1e2d3f;
    border-bottom: none;
    margin-right: 2px;
    border-radius: 6px 6px 0 0;
    font-size: 12px;
    font-weight: 500;
}

QTabBar::tab:selected {
    background-color: #080e1a;
    color: #e2e8f0;
    border-bottom: 2px solid #22c55e;
}

QTabBar::tab:hover:!selected {
    background-color: #182537;
    color: #b4c6d8;
}

/* ── Tables ───────────────────────────────────────────────────────── */
QTableWidget {
    background-color: #0c1421;
    gridline-color: #1e2d3f;
    border: 1px solid #1e2d3f;
    border-radius: 8px;
    selection-background-color: #1a3a5c;
    font-family: 'JetBrains Mono', 'Cascadia Code', 'Consolas', monospace;
    font-size: 12px;
    alternate-background-color: #0e1828;
}

QTableWidget::item {
    padding: 5px 10px;
    border-bottom: 1px solid #1e2d3f;
    color: #e2e8f0;
}

QTableWidget::item:selected {
    background-color: #1a3a5c;
    color: #e2e8f0;
}

QTableWidget::item:hover {
    background-color: #182537;
}

QHeaderView::section {
    background-color: #182537;
    color: #7a8fa6;
    padding: 7px 10px;
    border: none;
    border-bottom: 1px solid #1e2d3f;
    border-right: 1px solid #1e2d3f;
    font-weight: 600;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.6px;
    font-family: 'Inter', 'Segoe UI', sans-serif;
}

QHeaderView::section:last {
    border-right: none;
}

/* ── Buttons ──────────────────────────────────────────────────────── */
QPushButton {
    background-color: #22c55e;
    color: #080e1a;
    border: none;
    padding: 7px 16px;
    border-radius: 6px;
    font-weight: 700;
    font-size: 12px;
}

QPushButton:hover {
    background-color: #16a34a;
}

QPushButton:pressed {
    background-color: #15803d;
}

QPushButton:disabled {
    background-color: #1e2d3f;
    color: #4a5a6a;
}

QPushButton#btn_stop, QPushButton[role="stop"] {
    background-color: #ef4444;
    color: #ffffff;
}

QPushButton#btn_stop:hover, QPushButton[role="stop"]:hover {
    background-color: #dc2626;
}

QPushButton#btn_start, QPushButton[role="start"] {
    background-color: #22c55e;
    color: #080e1a;
}

QPushButton#btn_start:hover, QPushButton[role="start"]:hover {
    background-color: #16a34a;
}

QPushButton[role="outline"] {
    background-color: transparent;
    color: #7a8fa6;
    border: 1px solid #1e2d3f;
}

QPushButton[role="outline"]:hover {
    background-color: #182537;
    color: #e2e8f0;
}

QPushButton[role="ghost"] {
    background-color: transparent;
    color: #7a8fa6;
    border: none;
}

QPushButton[role="ghost"]:hover {
    background-color: #182537;
    color: #e2e8f0;
}

/* ── Inputs ───────────────────────────────────────────────────────── */
QLineEdit, QSpinBox, QDoubleSpinBox {
    background-color: #182537;
    color: #e2e8f0;
    border: 1px solid #1e2d3f;
    border-radius: 6px;
    padding: 6px 10px;
    font-family: 'JetBrains Mono', 'Consolas', monospace;
    font-size: 12px;
    selection-background-color: #1a3a5c;
}

QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #22c55e;
    background-color: #0e1c2e;
}

QComboBox {
    background-color: #182537;
    color: #e2e8f0;
    border: 1px solid #1e2d3f;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
    min-width: 80px;
}

QComboBox:focus {
    border: 1px solid #22c55e;
}

QComboBox::drop-down {
    border: none;
    width: 22px;
}

QComboBox::down-arrow {
    width: 10px;
    height: 10px;
}

QComboBox QAbstractItemView {
    background-color: #0c1421;
    border: 1px solid #1e2d3f;
    border-radius: 6px;
    selection-background-color: #1a3a5c;
    color: #e2e8f0;
    padding: 2px;
}

/* ── Text / console ───────────────────────────────────────────────── */
QTextEdit, QPlainTextEdit {
    background-color: #0c1421;
    color: #b4c6d8;
    border: 1px solid #1e2d3f;
    border-radius: 8px;
    font-family: 'JetBrains Mono', 'Cascadia Code', 'Consolas', monospace;
    font-size: 11.5px;
    selection-background-color: #1a3a5c;
}

/* ── Frames / cards ───────────────────────────────────────────────── */
QFrame#card {
    background-color: #0c1421;
    border: 1px solid #1e2d3f;
    border-radius: 10px;
}

QFrame {
    border: none;
}

/* ── Labels ───────────────────────────────────────────────────────── */
QLabel {
    background: transparent;
    border: none;
}

QLabel#stat_value {
    font-size: 26px;
    font-weight: 700;
    color: #e2e8f0;
    font-family: 'JetBrains Mono', 'Consolas', monospace;
}

QLabel#stat_label {
    font-size: 10px;
    color: #7a8fa6;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    font-weight: 600;
}

QLabel#green  { color: #22c55e; font-weight: 700; }
QLabel#red    { color: #ef4444; font-weight: 700; }
QLabel#gold   { color: #eab308; font-weight: 700; }
QLabel#blue   { color: #74c0fc; font-weight: 700; }
QLabel#muted  { color: #7a8fa6; }
QLabel#profit { color: #22c55e; font-weight: 700; font-family: 'JetBrains Mono', monospace; }
QLabel#loss   { color: #ef4444; font-weight: 700; font-family: 'JetBrains Mono', monospace; }
QLabel#mono   { font-family: 'JetBrains Mono', 'Consolas', monospace; }

/* ── ScrollArea ───────────────────────────────────────────────────── */
QScrollArea {
    background-color: transparent;
    border: none;
}

QScrollArea > QWidget > QWidget {
    background-color: transparent;
}

QScrollBar:vertical {
    background-color: #0c1421;
    width: 8px;
    border: none;
    border-radius: 4px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background-color: #1e2d3f;
    border-radius: 4px;
    min-height: 24px;
}

QScrollBar::handle:vertical:hover {
    background-color: #2a3d54;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }

QScrollBar:horizontal {
    background-color: #0c1421;
    height: 8px;
    border: none;
    border-radius: 4px;
}

QScrollBar::handle:horizontal {
    background-color: #1e2d3f;
    border-radius: 4px;
    min-width: 24px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #2a3d54;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ── GroupBox ─────────────────────────────────────────────────────── */
QGroupBox {
    border: 1px solid #1e2d3f;
    border-radius: 8px;
    margin-top: 14px;
    padding-top: 10px;
    color: #7a8fa6;
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.8px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 5px;
    background-color: #080e1a;
}

/* ── CheckBox ─────────────────────────────────────────────────────── */
QCheckBox {
    spacing: 8px;
    color: #e2e8f0;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #1e2d3f;
    border-radius: 4px;
    background-color: #182537;
}

QCheckBox::indicator:checked {
    background-color: #22c55e;
    border-color: #22c55e;
}

/* ── Sliders ──────────────────────────────────────────────────────── */
QSlider::groove:horizontal {
    background-color: #1e2d3f;
    height: 4px;
    border-radius: 2px;
}

QSlider::handle:horizontal {
    background-color: #22c55e;
    width: 14px;
    height: 14px;
    border-radius: 7px;
    margin: -5px 0;
}

QSlider::sub-page:horizontal {
    background-color: #22c55e;
    border-radius: 2px;
}

/* ── Splitter ─────────────────────────────────────────────────────── */
QSplitter::handle {
    background-color: #1e2d3f;
    width: 2px;
    height: 2px;
}

/* ── Status bar ───────────────────────────────────────────────────── */
QStatusBar {
    background-color: #0c1421;
    border-top: 1px solid #1e2d3f;
    color: #7a8fa6;
    font-size: 11px;
    font-family: 'JetBrains Mono', 'Consolas', monospace;
}

QStatusBar::item {
    border: none;
}

/* ── ToolTip ──────────────────────────────────────────────────────── */
QToolTip {
    background-color: #0c1421;
    color: #e2e8f0;
    border: 1px solid #1e2d3f;
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 11px;
}

/* ── Splitter handle ──────────────────────────────────────────────── */
QSplitter::handle:horizontal { background-color: #1e2d3f; width: 2px; }
QSplitter::handle:vertical   { background-color: #1e2d3f; height: 2px; }
"""
