DARK_THEME = """
QMainWindow, QWidget {
    background-color: #1e1e1e;
    color: #d4d4d4;
    font-family: 'Segoe UI', sans-serif;
    font-size: 13px;
}

QTabWidget::pane {
    border: 1px solid #3d3d3d;
    background-color: #1e1e1e;
}

QTabBar::tab {
    background-color: #2d2d2d;
    color: #858585;
    padding: 8px 18px;
    border: 1px solid #3d3d3d;
    border-bottom: none;
    margin-right: 2px;
    border-radius: 4px 4px 0 0;
}

QTabBar::tab:selected {
    background-color: #1e1e1e;
    color: #d4d4d4;
    border-bottom: 2px solid #0078d4;
}

QTabBar::tab:hover:!selected {
    background-color: #333333;
    color: #cccccc;
}

QTableWidget {
    background-color: #252525;
    gridline-color: #3d3d3d;
    border: 1px solid #3d3d3d;
    border-radius: 4px;
    selection-background-color: #264f78;
}

QTableWidget::item {
    padding: 5px 8px;
    border-bottom: 1px solid #2d2d2d;
}

QTableWidget::item:selected {
    background-color: #264f78;
}

QHeaderView::section {
    background-color: #2d2d2d;
    color: #858585;
    padding: 6px 8px;
    border: none;
    border-bottom: 1px solid #3d3d3d;
    font-weight: bold;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

QPushButton {
    background-color: #0078d4;
    color: #ffffff;
    border: none;
    padding: 7px 16px;
    border-radius: 4px;
    font-weight: bold;
}

QPushButton:hover {
    background-color: #1084d8;
}

QPushButton:pressed {
    background-color: #006bbf;
}

QPushButton:disabled {
    background-color: #3d3d3d;
    color: #666666;
}

QPushButton#btn_stop {
    background-color: #c42b1c;
}

QPushButton#btn_stop:hover {
    background-color: #d32f1e;
}

QPushButton#btn_start {
    background-color: #107c10;
}

QPushButton#btn_start:hover {
    background-color: #1a8f1a;
}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: #3c3c3c;
    color: #d4d4d4;
    border: 1px solid #555555;
    border-radius: 4px;
    padding: 5px 8px;
}

QLineEdit:focus, QComboBox:focus {
    border: 1px solid #0078d4;
}

QComboBox::drop-down {
    border: none;
    width: 20px;
}

QComboBox QAbstractItemView {
    background-color: #3c3c3c;
    border: 1px solid #555555;
    selection-background-color: #264f78;
}

QSlider::groove:horizontal {
    background-color: #3d3d3d;
    height: 4px;
    border-radius: 2px;
}

QSlider::handle:horizontal {
    background-color: #0078d4;
    width: 16px;
    height: 16px;
    border-radius: 8px;
    margin: -6px 0;
}

QSlider::sub-page:horizontal {
    background-color: #0078d4;
    border-radius: 2px;
}

QTextEdit {
    background-color: #1a1a1a;
    color: #cccccc;
    border: 1px solid #3d3d3d;
    border-radius: 4px;
    font-family: 'Cascadia Code', 'Consolas', monospace;
    font-size: 12px;
}

QLabel#stat_value {
    font-size: 24px;
    font-weight: bold;
    color: #d4d4d4;
}

QLabel#stat_label {
    font-size: 11px;
    color: #858585;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

QFrame#card {
    background-color: #252525;
    border: 1px solid #3d3d3d;
    border-radius: 8px;
}

QLabel#green { color: #51cf66; font-weight: bold; }
QLabel#red   { color: #f03e3e; font-weight: bold; }
QLabel#blue  { color: #74c0fc; font-weight: bold; }
QLabel#muted { color: #858585; }

QScrollBar:vertical {
    background-color: #252525;
    width: 10px;
    border: none;
}

QScrollBar::handle:vertical {
    background-color: #555555;
    border-radius: 5px;
    min-height: 20px;
}

QScrollBar::handle:vertical:hover {
    background-color: #666666;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

QGroupBox {
    border: 1px solid #3d3d3d;
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 8px;
    color: #858585;
    font-size: 11px;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}

QCheckBox {
    spacing: 8px;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #555555;
    border-radius: 3px;
    background-color: #3c3c3c;
}

QCheckBox::indicator:checked {
    background-color: #0078d4;
    border-color: #0078d4;
}

QSplitter::handle {
    background-color: #3d3d3d;
}
"""

COLOR_GREEN = "#51cf66"
COLOR_RED   = "#f03e3e"
COLOR_BLUE  = "#74c0fc"
COLOR_GOLD  = "#ffd43b"
COLOR_MUTED = "#858585"
COLOR_BG    = "#1e1e1e"
COLOR_PANEL = "#252525"
COLOR_CARD  = "#2d2d2d"
COLOR_BORDER = "#3d3d3d"
