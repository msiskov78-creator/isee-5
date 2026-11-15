"""Основное окно: боковое меню, страницы и выход из аккаунта."""

import logging

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QMessageBox, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget

from app_state import AppState
from camera.camera_service import CameraService
from control_runtime import ControlRuntime
from database.repository import SupabaseRepository
from supabase_client import AuthService, get_username
from ui.async_request import RequestWindow
from ui.camera_preview import CameraDialog
from ui.onboarding_wizard import OnboardingWizard
from ui.pages.account_page import AccountPage
from ui.pages.actions_page import ActionsPage
from ui.pages.gestures_page import GesturesPage
from ui.pages.home_page import HomePage
from ui.pages.profiles_page import ProfilesPage
from ui.pages.settings_page import SettingsPage
from ui.theme import APP_STYLE
from ui.widgets import label, message_label, set_message, switch_window


class MainWindow(RequestWindow):
    def __init__(self, user, auth_service=None):
        super().__init__()
        self.user = user
        self.user_id = getattr(user, "id", None)
        self.username = get_username(user)
        self.auth_service = auth_service if auth_service is not None else AuthService()
        # Для каждого входа создаём своё состояние, чтобы не смешивать данные аккаунтов.
        self.state = AppState()
        # Страницы получают этот же state; ID аккаунта не заменяется ID control_profile.
        self.state.user_id = self.user_id
        logging.getLogger("Auth").info("MainWindow получил user.id: %s", self.user_id)
        self.camera_service = CameraService(self)
        self.controller = ControlRuntime(self.state, self.camera_service, self)
        self._shutdown_kind = None
        self._discard_on_logout = False
        self._finishing_close = False
        self._onboarding = None
        self._camera_dialog = None
        self._data_loaded = False
        self.camera_service.stopped.connect(self._continue_shutdown, Qt.ConnectionType.QueuedConnection)
        self.state.idle.connect(self._continue_shutdown, Qt.ConnectionType.QueuedConnection)
        self.state.loaded.connect(self._loaded)
        self.state.persistence_status.connect(self._persistence_status)
        self.state.save_failed.connect(self._save_failed)
        self.setWindowTitle("Gesture Control")
        self.resize(1100, 700)
        self.setMinimumSize(1000, 660)
        self.setStyleSheet(APP_STYLE)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(228)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(18, 28, 18, 20)
        side.setSpacing(8)
        logo = label("◈  Gesture Control")
        logo.setObjectName("logo")
        side.addWidget(logo)
        side.addWidget(label("ВАШЕ ПРОСТРАНСТВО", "badge"))
        side.addSpacing(30)
        self.nav_buttons = {}
        navigation = [("home", "Главная"), ("gestures", "Жесты"), ("actions", "Действия"),
                      ("profiles", "Профили управления"), ("settings", "Настройки")]
        for name, title in navigation:
            side.addWidget(self.create_nav_button(name, title))
        side.addStretch()
        side.addWidget(label("АККАУНТ", "badge"))
        side.addWidget(self.create_nav_button("account", "Аккаунт"))
        self.logout_button = QPushButton("Выйти")
        self.logout_button.setObjectName("danger")
        self.logout_button.clicked.connect(self.logout)
        side.addWidget(self.logout_button)
        side.addSpacing(14)
        side.addWidget(label("Версия 2.2.0 · Gesture Control", "muted"))
        root.addWidget(self.sidebar)

        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(30, 22, 30, 20)
        column.setSpacing(18)
        top = QHBoxLayout()
        self.breadcrumb = label("ОБЗОР / ГЛАВНАЯ", "badge")
        top.addWidget(self.breadcrumb, 1)
        top.addWidget(label(self.username, "muted"))
        avatar = label(self.username[:1].upper())
        avatar.setObjectName("avatar")
        avatar.setFixedSize(40, 40)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(avatar)
        column.addLayout(top)
        self.stack = QStackedWidget()
        column.addWidget(self.stack, 1)
        self.status_label = message_label()
        self.status_label.hide()
        column.addWidget(self.status_label)
        self.retry_button = QPushButton("Повторить загрузку / сохранение")
        self.retry_button.clicked.connect(self._retry_data)
        self.retry_button.hide()
        column.addWidget(self.retry_button)
        self.discard_logout_button = QPushButton("Выйти без сохранения…")
        self.discard_logout_button.clicked.connect(self.logout_without_saving)
        self.discard_logout_button.hide()
        column.addWidget(self.discard_logout_button)
        root.addWidget(content, 1)

        # ==========================================
        # СОЗДАНИЕ И ПОДКЛЮЧЕНИЕ СТРАНИЦ
        # ==========================================
        self.pages = {
            "home": HomePage(self.username, self.state, self.camera_service, self.controller),
            "gestures": GesturesPage(self.state, self.camera_service),
            "actions": ActionsPage(self.state),
            "profiles": ProfilesPage(self.state),
            "settings": SettingsPage(self.state, self.camera_service),
            "account": AccountPage(self.username, user),
        }
        self.page_indices = {}
        for name, page in self.pages.items():
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(page)
            self.page_indices[name] = self.stack.addWidget(scroll)
        self.pages["home"].navigate_requested.connect(self.show_page)
        self.pages["home"].expand_requested.connect(self.expand_camera)
        self.pages["home"].onboarding_requested.connect(self.open_onboarding)
        self.pages["gestures"].wizard_opened.connect(self.controller.suspend)
        self.pages["gestures"].wizard_closed.connect(self.controller.resume)
        self.pages["profiles"].test_gesture_requested.connect(self.test_gesture)
        self.pages["actions"].test_gesture_requested.connect(self.test_gesture)
        self.pages["account"].logout_requested.connect(self.logout)
        self.show_page("home")
        client = getattr(self.auth_service, "_client", None)
        if client is not None and getattr(user, "id", None):
            self.state.attach_repository(SupabaseRepository(client, user.id))

    def _persistence_status(self, text, success):
        set_message(self.status_label, text, "success" if success else "error")
        self.status_label.show()
        self.retry_button.setVisible(not success)
        if success:
            self.discard_logout_button.hide()

    def _retry_data(self):
        if self.state.persistence_busy:
            return
        if self._data_loaded:
            self.state.flush_async()
        else:
            self.state.load_async()

    def _save_failed(self, revision, message):
        self.discard_logout_button.show()
        if self._shutdown_kind:
            # Не теряем изменения, если последний запрос завершился ошибкой при выходе.
            self._shutdown_kind = None
            self.setEnabled(True)
            self.stack.setEnabled(True)
            self.logout_button.setEnabled(True)
            self.pages["account"].logout_button.setEnabled(True)
            self.setWindowTitle("Gesture Control")
            set_message(self.status_label, message + " Изменения не сохранены. Повторите сохранение или выберите выход без сохранения.")
            self.retry_button.show()

    def _loaded(self):
        self._data_loaded = True
        self.pages["account"].account_profile = self.state.account_profile
        self.retry_button.hide()
        if self._shutdown_kind:
            return
        # Камера включается после загрузки выбранного устройства и пользовательских настроек.
        if not self.state.settings.get("onboarding_completed", False):
            QTimer.singleShot(0, self.open_onboarding)
        else:
            if self.state.settings.get("auto_start", False):
                self.controller.set_enabled(True)

    def open_onboarding(self):
        if self._shutdown_kind:
            return
        if self._onboarding is not None:
            self._onboarding.raise_()
            return
        self.controller.suspend()
        self._onboarding = OnboardingWizard(self.state, self.camera_service, self)
        self._onboarding.finished.connect(self._onboarding_closed)
        self._onboarding.open()

    def _onboarding_closed(self, result):
        wizard = self._onboarding
        self._onboarding = None
        if wizard is not None:
            wizard.deleteLater()
        self.controller.resume()
        if not self._shutdown_kind and self.state.settings.get("onboarding_completed") and self.state.settings.get("auto_start"):
            self.controller.set_enabled(True)

    def expand_camera(self):
        if self._camera_dialog is not None:
            self._camera_dialog.raise_()
            return
        self.camera_service.start()
        self._camera_dialog = CameraDialog(self.camera_service, self.state, self.controller, self)
        self._camera_dialog.finished.connect(self._camera_dialog_closed)
        self._camera_dialog.show()

    def _camera_dialog_closed(self, result):
        self._camera_dialog = None

    def test_gesture(self, name):
        self.controller.suspend()
        self.camera_service.start()
        dialog = CameraDialog(self.camera_service, self.state, self.controller, self, target_gesture=name)
        dialog.finished.connect(self.controller.resume)
        dialog.open()

    def create_nav_button(self, name, title):
        button = QPushButton(title)
        button.setObjectName("nav")
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda checked=False, page=name: self.show_page(page))
        self.nav_buttons[name] = button
        return button

    def show_page(self, name):
        if name not in self.page_indices:
            return
        # Переключаем страницу в QStackedWidget; новых окон здесь нет.
        self.stack.setCurrentIndex(self.page_indices[name])
        for key, button in self.nav_buttons.items():
            button.setChecked(key == name)
        self.breadcrumb.setText("ПРОСТРАНСТВО / " + self.nav_buttons[name].text().upper())

    def logout(self):
        if self.worker is not None or self._shutdown_kind:
            return
        self._shutdown_kind = "logout"
        self.controller.set_enabled(False)
        self._close_dialogs()
        self.logout_button.setEnabled(False)
        self.pages["account"].logout_button.setEnabled(False)
        self.stack.setEnabled(False)
        set_message(self.status_label, "Завершаем сохранение и освобождаем камеру…", "muted")
        self.status_label.show()
        self.camera_service.stop()
        if not self._discard_on_logout and self.state.has_unsaved_changes and self.state.can_persist and not self.state.persistence_busy:
            self.state.flush_async()
        self._continue_shutdown()

    def logout_without_saving(self):
        if self.state.persistence_busy or self.worker is not None or self._shutdown_kind:
            set_message(self.status_label, "Дождитесь завершения текущего запроса перед выходом.")
            return
        # Несохранённые изменения теряются только после явного решения пользователя.
        answer = QMessageBox.question(self, "Выход без сохранения",
            "Выйти из аккаунта? Несохранённые изменения текущего сеанса будут потеряны. Уже записанные данные останутся в Supabase.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._discard_on_logout = True
        self.logout()

    def _close_dialogs(self):
        from PySide6.QtWidgets import QDialog
        for dialog in self.findChildren(QDialog):
            dialog.reject()

    def _continue_shutdown(self):
        if not self._shutdown_kind or self.camera_service.is_busy or self.state.persistence_busy or self.worker is not None:
            return
        if self._shutdown_kind == "close":
            self._finishing_close = True
            self.close()
            return
        # Авторизованный клиент нужен до завершения последнего запроса сохранения.
        set_message(self.status_label, "Выходим из аккаунта…", "muted")
        self.start_request(self.auth_service.sign_out, self.logout_finished)

    def logout_finished(self, result, error):
        if self._shutdown_kind == "close":
            self._continue_shutdown()
            return
        if error:
            self._shutdown_kind = None
            self._discard_on_logout = False
            self.stack.setEnabled(True)
            self.logout_button.setEnabled(True)
            self.pages["account"].logout_button.setEnabled(True)
            set_message(self.status_label, error)
            return
        from ui.login_window import LoginWindow
        self._finishing_close = True
        switch_window(self, LoginWindow(self.auth_service))

    def closeEvent(self, event):
        if self._finishing_close:
            super().closeEvent(event)
            return
        # Освобождаем камеру при закрытии приложения, не блокируя цикл событий Qt.
        self._shutdown_kind = "close"
        self.controller.set_enabled(False)
        self._close_dialogs()
        self.setEnabled(False)
        self.camera_service.stop()
        if self.state.has_unsaved_changes and self.state.can_persist and not self.state.persistence_busy:
            self.state.flush_async()
        if self.camera_service.is_busy or self.state.persistence_busy or self.worker is not None:
            self.setWindowTitle("Gesture Control — завершение работы…")
            event.ignore()
            QTimer.singleShot(50, self._continue_shutdown)
        else:
            self._finishing_close = True
            super().closeEvent(event)
