# Локальная модель руки

`hand_landmarker.task.gz` — официальная модель MediaPipe Hand Landmarker float16,
версия 1, сжатая gzip без изменения исходных байтов. HandDetector распаковывает её
в память и передаёт `BaseOptions(model_asset_buffer=...)`. Интернет при запуске не нужен.

- Источник: https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task
- Документация: https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker/python
- Размер исходного файла: 7 819 105 байт.
- SHA256 исходного файла: `fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1`.

При восстановлении можно скачать исходный файл как `hand_landmarker.task` в эту же папку.
Несжатый вариант также поддерживается и имеет приоритет. Временные файлы, кадры камеры
и записи видео в этой папке не создаются.
