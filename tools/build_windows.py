"""Сборка и копирование только проверенной публичной конфигурации."""

from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import dotenv_values
from supabase_client import _public_key_error
from urllib.parse import urlparse


def main():
    assert sys.version_info[:2] == (3, 12), "Требуется Python 3.12"
    source = dotenv_values(ROOT / ".env", interpolate=False, encoding="utf-8-sig")
    url, key = source.get("SUPABASE_URL", ""), source.get("SUPABASE_KEY", "")
    address = urlparse(url or "")
    safe = (bool(key) and not _public_key_error(key) and address.scheme == "https" and address.hostname
            and not address.username and not address.password and not address.query and not address.fragment
            and address.path in ("", "/"))
    print("Конфигурация: публичная, разрешена" if safe else "Конфигурация не прошла проверку; будет скопирован только шаблон", flush=True)
    (ROOT / "build").mkdir(exist_ok=True)
    with (ROOT / "build" / "build.log").open("w", encoding="utf-8") as log:
        result = subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                                 "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build"),
                                 str(ROOT / "GestureControl.spec")], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        print("Ошибка PyInstaller. Подробности: build/build.log")
        return result.returncode
    destination = ROOT / "dist" / "GestureControl"
    for name in (".env.example", "PROJECT_GUIDE.md", "ARCHITECTURE.txt", "requirements-build.lock"):
        shutil.copy2(ROOT / name, destination / name)
    # Исходный .env целиком не копируем: любые дополнительные переменные исключаются.
    if safe:
        public = "SUPABASE_URL=" + url + "\nSUPABASE_KEY=" + key + "\n"
        (destination / ".env").write_text(public, encoding="utf-8")
    else:
        shutil.copy2(ROOT / ".env.example", destination / ".env")
    manifest = subprocess.check_output([sys.executable, "-m", "pip", "list", "--format=json"], text=True)
    (destination / "build-environment.json").write_text(manifest, encoding="utf-8")
    # Приватные конфигурации и исходная среда не должны попадать во внутренние ресурсы.
    forbidden = [p for p in (destination / "_internal").rglob("*")
                 if p.name in {".env", "config.json", ".git", ".venv"}]
    if forbidden:
        raise RuntimeError("Во внутренней папке обнаружена запрещённая конфигурация")
    print("Готово: " + str(destination / "GestureControl.exe"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
