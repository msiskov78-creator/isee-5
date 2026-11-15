"""Проверка именно запущенной сборки; не исполняет назначенные действия."""

import ctypes
import importlib
import json
from pathlib import Path
import sys

from app_paths import APP_DIRECTORY, RESOURCE_DIRECTORY, user_data_directory
from diagnostics import error_text


def verify_build(app, window):
    output = user_data_directory() / "verification"
    output.mkdir(parents=True, exist_ok=True)
    report = {"executable": sys.executable, "frozen": bool(getattr(sys, "frozen", False)),
              "cwd": str(Path.cwd()), "app_directory": str(APP_DIRECTORY), "checks": {}}
    checks = report["checks"]

    def check(name, operation):
        try:
            detail = operation()
            checks[name] = {"ok": True, "detail": detail}
        except Exception as error:
            checks[name] = {"ok": False, "error": error_text(f"{type(error).__name__}: {error}")}

    def ui():
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtSvg import QSvgRenderer
        app.processEvents()
        assert window.isVisible() and ctypes.windll.user32.IsWindowVisible(int(window.winId()))
        for name in ("chevron_up.svg", "chevron_down.svg"):
            assert QSvgRenderer(str(RESOURCE_DIRECTORY / "ui" / "icons" / name)).isValid()
        assert window.grab().save(str(output / "login.png"))
        return {"visible": True, "platform": QGuiApplication.platformName(), "title": window.windowTitle()}

    check("ui_and_icons", ui)
    for name in ("PySide6.QtCore", "cv2", "mediapipe", "supabase", "dotenv", "pycaw.pycaw",
                 "comtypes.client", "pynput.keyboard._win32", "pynput.mouse._win32", "pyautogui", "numpy"):
        check("import:" + name, lambda name=name: bool(importlib.import_module(name)))

    def model():
        import numpy as np
        from hand_tracking.hand_detector import HandDetector
        detector = HandDetector()
        try:
            hand = detector.detect(np.zeros((480, 640, 3), dtype=np.uint8), 1.)
            return {"initialized": True, "inference": True, "hand_found": hand["found"]}
        finally:
            detector.close()

    check("mediapipe_model_inference", model)

    def supabase():
        from supabase_client import AuthService
        client = AuthService()._create_client(auto_refresh_token=False)
        return {"client_created": client is not None}

    check("supabase_client", supabase)

    def connection():
        import httpx
        from supabase_client import SUPABASE_URL, SUPABASE_KEY, _configuration_error
        assert not _configuration_error(), "Некорректная публичная конфигурация"
        # Публичный endpoint настроек Auth: без входа, записи в БД и изменения аккаунта.
        response = httpx.get(SUPABASE_URL.rstrip("/") + "/auth/v1/settings",
                             headers={"apikey": SUPABASE_KEY}, timeout=20)
        assert response.status_code == 200, f"HTTP {response.status_code}"
        assert isinstance(response.json(), dict)
        return {"http_status": response.status_code}

    check("supabase_connection", connection)
    from actions.windows_actions import WindowsActions
    check("audio_read_only", lambda: {"volume_read": isinstance(WindowsActions().get_volume(), float)})
    # Опциональная камера проверяется только по отдельному флагу, через существующий сервис.
    if "--verify-camera" in sys.argv:
        from camera.camera_service import CameraService
        from PySide6.QtCore import QEventLoop, QTimer
        camera = CameraService()
        loop = QEventLoop()
        received, errors = [], []
        camera.frame_ready.connect(lambda packet: (received.append(packet), loop.quit()))
        camera.error.connect(lambda message: (errors.append(message), loop.quit()))
        camera.configure({"camera": 0, "mirror": True}, [])
        camera.start(0)
        QTimer.singleShot(15000, loop.quit)
        loop.exec()
        camera.stop()
        # Не уничтожаем работающий QThread: ждём штатного освобождения устройства.
        if camera.is_busy:
            camera.stopped.connect(loop.quit)
            loop.exec()
        report["camera"] = {"available": bool(received), "recognition_available": bool(received and received[0].get("recognition_available")),
                            "errors": [error_text(e) for e in errors]}
    else:
        report["camera"] = {"tested": False}
    report["ok"] = all(item["ok"] for item in checks.values())
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    app.exit(0 if report["ok"] else 1)
