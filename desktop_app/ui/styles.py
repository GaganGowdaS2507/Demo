"""
desktop_app/ui/styles.py
Modern Windows 11 Fluent-inspired Dark Theme for AttendAI Desktop.
Crisp typography, soft borders, modern cards, and distinctive status badges.
"""

MODERN_DARK_STYLE = """
/* Global Application Style */
QWidget {
    background-color: #0f172a;
    color: #f8fafc;
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    font-size: 13px;
}

/* Window & Panels */
QMainWindow, QDialog {
    background-color: #0f172a;
}

QFrame#card {
    background-color: #1e293b;
    border-radius: 10px;
    border: 1px solid #334155;
    padding: 12px;
}

QFrame#sidebar {
    background-color: #0b1120;
    border-right: 1px solid #1e293b;
}

/* Labels */
QLabel {
    color: #cbd5e1;
}

QLabel#heading {
    font-size: 20px;
    font-weight: bold;
    color: #ffffff;
}

QLabel#subheading {
    font-size: 14px;
    font-weight: 600;
    color: #94a3b8;
}

QLabel#badge {
    background-color: #3b82f6;
    color: white;
    font-weight: bold;
    padding: 4px 10px;
    border-radius: 12px;
}

/* Buttons */
QPushButton {
    background-color: #2563eb;
    color: #ffffff;
    font-weight: 600;
    padding: 8px 18px;
    border-radius: 6px;
    border: none;
    min-height: 24px;
}

QPushButton:hover {
    background-color: #1d4ed8;
}

QPushButton:pressed {
    background-color: #1e40af;
}

QPushButton:disabled {
    background-color: #334155;
    color: #64748b;
}

QPushButton#secondary {
    background-color: #334155;
    color: #f1f5f9;
}

QPushButton#secondary:hover {
    background-color: #475569;
}

QPushButton#success {
    background-color: #16a34a;
    color: #ffffff;
}

QPushButton#success:hover {
    background-color: #15803d;
}

QPushButton#danger {
    background-color: #dc2626;
    color: #ffffff;
}

QPushButton#danger:hover {
    background-color: #b91c1c;
}

/* Text Inputs & Combos */
QLineEdit, QComboBox, QSpinBox {
    background-color: #1e293b;
    color: #f8fafc;
    border: 1px solid #475569;
    border-radius: 6px;
    padding: 8px 12px;
    selection-background-color: #2563eb;
}

QLineEdit:focus, QComboBox:focus {
    border: 1px solid #3b82f6;
    background-color: #0f172a;
}

QComboBox::drop-down {
    border: none;
    padding-right: 8px;
}

QComboBox QAbstractItemView {
    background-color: #1e293b;
    border: 1px solid #475569;
    selection-background-color: #2563eb;
    color: #f8fafc;
}

/* Tables */
QTableWidget {
    background-color: #1e293b;
    gridline-color: #334155;
    border: 1px solid #334155;
    border-radius: 8px;
    color: #f8fafc;
    selection-background-color: #2563eb;
    selection-color: #ffffff;
}

QTableWidget::item {
    padding: 8px;
    border-bottom: 1px solid #334155;
}

QHeaderView::section {
    background-color: #0f172a;
    color: #94a3b8;
    padding: 8px;
    border: none;
    border-bottom: 2px solid #334155;
    font-weight: bold;
    text-transform: uppercase;
    font-size: 11px;
}

/* Progress Bar */
QProgressBar {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 6px;
    text-align: center;
    color: #ffffff;
    font-weight: bold;
    height: 18px;
}

QProgressBar::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563eb, stop:1 #38bdf8);
    border-radius: 5px;
}

/* Scrollbars */
QScrollBar:vertical {
    border: none;
    background: #0f172a;
    width: 10px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background: #475569;
    min-height: 20px;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover {
    background: #64748b;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

/* Tab Widget */
QTabWidget::pane {
    border: 1px solid #1e293b;
    background-color: #0f172a;
}

QTabBar::tab {
    background: #0f172a;
    color: #94a3b8;
    padding: 10px 20px;
    font-weight: 600;
    border-bottom: 2px solid transparent;
}

QTabBar::tab:selected {
    color: #38bdf8;
    border-bottom: 2px solid #38bdf8;
    background: #1e293b;
}

QTabBar::tab:hover {
    color: #f1f5f9;
}
"""
