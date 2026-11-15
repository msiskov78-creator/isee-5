import sys
import logging
from importlib.util import find_spec
from app_paths import user_data_directory
from diagnostics import setup_logging

from PySide6.QtWidgets import QApplication
from ui.login_window import LoginWindow


def main():
    log_path = setup_logging(user_data_directory() / "logs")
    # Видно, каким Python запущено приложение и доступны ли библиотеки команд Windows.
    logger = logging.getLogger("Actions")
    logger.info("Новый запуск Gesture Control; журнал: %s", log_path or "только консоль")
    logger.info("Python: %s", sys.executable)
    original_hook = sys.excepthook

    def report_unhandled(kind, error, tb):
        # Ошибки обработчиков Qt иначе теряются при запуске без консоли.
        logger.error("Необработанная ошибка: %s", error, exc_info=(kind, error, tb))
        original_hook(kind, error, tb)

    sys.excepthook = report_unhandled
    missing = [name for name in ("pycaw", "comtypes", "pynput") if find_spec(name) is None]
    if missing:
        logger.error("Отсутствуют библиотеки: %s. Запустите приложение через start_gesture_control.bat в папке проекта.", ", ".join(missing))
    else:
        logger.info("Библиотеки pycaw, comtypes, pynput доступны")
    # Создаём приложение PySide6
    app = QApplication(sys.argv)
    app.setApplicationName("Gesture Control")
    app.setOrganizationName("GestureControl")
    app.setStyle("Fusion")

    # Создаём окно входа
    window = LoginWindow()
    # Ссылка удерживает текущее окно при переходах вход → регистрация → приложение.
    app.current_window = window

    # Показываем окно
    window.show()

    if "--verify-build" in sys.argv:
        # Отдельная проверка сборки: без входа, нажатий клавиш и системных команд.
        from PySide6.QtCore import QTimer
        from tools.verify_runtime import verify_build
        QTimer.singleShot(500, lambda: verify_build(app, window))

    # Запускаем приложение
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
