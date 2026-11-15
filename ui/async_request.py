"""Выполнение одного сетевого запроса без остановки интерфейса."""

from PySide6.QtCore import QThread, Slot, Qt
from PySide6.QtWidgets import QWidget

from supabase_client import AuthError


class RequestThread(QThread):
    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation
        self.result = None
        self.error = ""

    def run(self):
        # В рабочем потоке не обращаемся к виджетам Qt.
        try:
            self.result = self.operation()
        except AuthError as error:
            self.error = str(error)
        except Exception:
            # Не показываем сырые ответы сервера: в них могут оказаться служебные данные.
            self.error = "Не удалось выполнить запрос. Попробуйте ещё раз."
        finally:
            self.operation = None


class RequestWindow(QWidget):
    """Общая для окон защита от повторных запросов и закрытия активного потока."""

    def __init__(self):
        super().__init__()
        self.worker = None
        self._request_callback = None
        self._close_after_request = False
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    def start_request(self, operation, callback):
        if self.worker is not None:
            return
        self._request_callback = callback
        self.worker = RequestThread(operation, self)
        self.worker.finished.connect(self._request_finished)
        self.worker.start()

    @Slot()
    def _request_finished(self):
        # Слот принадлежит окну, поэтому выполняется в основном потоке.
        worker = self.worker
        callback = self._request_callback
        self.worker = None
        self._request_callback = None
        result, error = worker.result, worker.error
        worker.deleteLater()
        if self._close_after_request:
            self.close()
            return
        callback(result, error)

    def closeEvent(self, event):
        if self.worker is not None:
            # Дожидаемся ответа асинхронно; не уничтожаем работающий QThread.
            self._close_after_request = True
            self.setWindowTitle("Gesture Control — завершение запроса…")
            event.ignore()
            return
        super().closeEvent(event)
