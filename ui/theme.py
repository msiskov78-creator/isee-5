"""Общие цвета и оформление всех окон приложения."""

from pathlib import Path

ICON_DIRECTORY = (Path(__file__).parent / "icons").as_posix()

# Один файл стилей помогает менять дизайн без изменения логики страниц.
APP_STYLE = """
QWidget { background: #090b10; color: #eef2ff; font-family: 'Segoe UI'; font-size: 14px; }
QLabel { background: transparent; }
QLabel[role='title'] { font-size: 28px; font-weight: 650; }
QLabel[role='subtitle'], QLabel[role='muted'] { color: #8d96aa; }
QLabel[role='section'] { font-size: 17px; font-weight: 600; }
QLabel[role='stat'] { font-size: 22px; font-weight: 600; }
QLabel[role='badge'] { color: #8ba7ff; font-size: 11px; font-weight: 700; }
QLabel[role='error'] { color: #ff6868; }
QLabel[role='success'] { color: #26e7a4; }
QFrame#card { background: #151923; border: 1px solid #252c3a; border-radius: 16px; }
QFrame#card QLabel { background: transparent; }
QFrame#sidebar, QFrame#brandPanel { background: #0d1016; border: none; border-right: 1px solid #252c3a; }
QFrame#brandPanel QLabel { background: transparent; }
QLabel#brandTitle { font-size: 32px; font-weight: 650; }
QLabel#logo { font-size: 20px; font-weight: 650; }
QLabel#avatar { background: #1b2a50; border-radius: 20px; color: #9db4ff; font-size: 17px; font-weight: 600; }
QPushButton { background: #151923; border: 1px solid #252c3a; border-radius: 9px; padding: 11px 16px; font-weight: 600; }
QPushButton:hover { background: #202738; border-color: #3c4b68; }
QPushButton:pressed { background: #27344d; }
QPushButton:focus { border-color: #7196ff; }
QPushButton:disabled { color: #606b80; background: #111621; border-color: #1d2330; }
QPushButton#primary, QPushButton[role='primary'] { background: #4f7cff; color: white; border-color: #4f7cff; }
QPushButton#primary:hover, QPushButton[role='primary']:hover { background: #628bff; }
QPushButton#primary:disabled { background: #283d73; color: #94a1bf; border-color: #283d73; }
QPushButton#link { background: transparent; border: none; color: #8ba7ff; padding: 6px; }
QPushButton#link:hover { color: #becfff; }
QPushButton#nav { text-align: left; background: transparent; border: 1px solid transparent; padding: 13px 16px; color: #8d96aa; }
QPushButton#nav:hover { background: #161d2b; color: #eef2ff; }
QPushButton#nav:checked { background: #1a284a; border-color: #273d70; color: #96b0ff; }
QPushButton#danger, QPushButton[role='danger'] { color: #ff8585; }
QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox { background: #111620; border: 1px solid #252c3a; border-radius: 9px; padding: 10px 12px; selection-background-color: #4f7cff; min-height: 22px; }
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus { border-color: #4f7cff; background: #151c2b; }
QLineEdit:disabled { color: #64718a; }
QLineEdit#passwordBox { font-size: 23px; padding: 0; border-radius: 10px; }
QComboBox::drop-down { width: 24px; border: none; }
QComboBox::down-arrow { image: url('$ICONS/chevron_down.svg'); width: 12px; height: 12px; }
QDoubleSpinBox, QSpinBox { padding-right: 30px; }
QDoubleSpinBox::up-button, QSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 26px; border: none; }
QDoubleSpinBox::down-button, QSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 26px; border: none; }
QDoubleSpinBox::up-arrow, QSpinBox::up-arrow { image: url('$ICONS/chevron_up.svg'); width: 10px; height: 10px; }
QDoubleSpinBox::down-arrow, QSpinBox::down-arrow { image: url('$ICONS/chevron_down.svg'); width: 10px; height: 10px; }
QComboBox QAbstractItemView { background: #151923; color: #eef2ff; selection-background-color: #263c70; border: 1px solid #34405a; outline: 0; padding: 6px; }
QListWidget { background: #111620; border: 1px solid #252c3a; border-radius: 10px; padding: 6px; outline: 0; }
QListWidget::item { padding: 15px 12px; border-radius: 6px; }
QListWidget::item:selected { background: #1d3055; color: #a9c0ff; }
QListWidget::item:hover { background: #1c2332; }
QSlider::groove:horizontal { height: 6px; background: #252c3a; border-radius: 3px; }
QSlider::sub-page:horizontal { background: #4f7cff; border-radius: 3px; }
QSlider::handle:horizontal { width: 18px; background: #a6bdff; border-radius: 9px; margin: -6px 0; }
QCheckBox { background: transparent; spacing: 10px; padding: 5px 0; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #3c4b68; border-radius: 4px; background: #111620; }
QCheckBox::indicator:checked { background: #4f7cff; border-color: #8ba7ff; }
QProgressBar { background: #111620; border: 1px solid #252c3a; border-radius: 7px; text-align: center; min-height: 22px; }
QProgressBar::chunk { background: #4f7cff; border-radius: 6px; }
QScrollArea { background: transparent; border: none; }
QScrollBar:vertical { background: #0d1016; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: #303a50; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QToolTip { background: #1b2334; color: #eef2ff; border: 1px solid #33405a; padding: 6px; }
""".replace("$ICONS", ICON_DIRECTORY)
