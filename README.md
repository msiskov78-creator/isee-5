# Gesture Control

Приложение для Windows: управление компьютером статическими и динамическими жестами руки.
Интерфейс — PySide6, камера — OpenCV, распознавание — MediaPipe, аккаунты и данные — Supabase.

## Запуск из исходников

Требуется Python 3.12 x64 и камера. В PowerShell из папки проекта:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.lock
Copy-Item .env.example .env
```

Заполните `.env`: `SUPABASE_URL` и `SUPABASE_KEY` (публичный publishable или anon key).
Серверные service_role/secret keys использовать нельзя. Нужен настроенный проект Supabase
с таблицами и политиками доступа, соответствующими `database/repository.py`.

Запуск: `start_gesture_control.bat` или `.\.venv\Scripts\python.exe -B main.py`.
После входа выберите профиль, назначьте действия и включите управление.
Локальная модель MediaPipe включена в `hand_tracking/models/`.

## Структура

- `main.py` — запуск; `app_state.py` — данные аккаунта и очередь сохранения.
- `control_runtime.py` — связь распознанных жестов с действиями.
- `actions/` — удержание, повторы и команды Windows.
- `camera/` — общий сервис камеры и поток обработки.
- `hand_tracking/` — MediaPipe и оценка landmarks.
- `gesture_control/` — распознавание и запись поз/движений, pinch.
- `database/` — работа с Supabase; `supabase_client.py` — авторизация.
- `ui/` — окна, страницы, оформление и SVG.
- `tests/` — автоматические проверки; `tools/` — инструменты проверки и сборки.
- `packaging/` — подготовка среды запуска EXE.

## Проверка

```powershell
.\.venv\Scripts\python.exe -B main.py --verify-build --verify-camera
.\.venv\Scripts\python.exe -B -m unittest discover -s tests
```

Диагностический запуск проверяет UI, модель, зависимости, публичное подключение Supabase,
чтение громкости и камеру; назначенные системные команды не исполняет.
Журналы и отчёт сохраняются в `%LOCALAPPDATA%\GestureControl`.

15.11.2026 проверены запуск исходников, камера, MediaPipe, подключение Supabase и 29 тестов
обработки команд. Вход в аккаунт и выполнение команд по живым жестам требуют ручной проверки.
В текущей копии отсутствуют SQL-миграции; тест наличия `005_more_action_types.sql` известен
как проблемный. Скрипт сборки требует отдельно восстановить `GestureControl.spec` и указанные
в нём/скрипте файлы документации: полный комплект сборки в эту копию исходников не входит.

`.env`, виртуальное окружение, журналы, резервные копии и готовые EXE в репозиторий не включены.
Происхождение модели и её контрольная сумма описаны в `hand_tracking/models/README.md`.
