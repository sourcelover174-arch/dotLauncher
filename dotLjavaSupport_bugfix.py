#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dotLauncher — минималистичный лаунчер Minecraft для Fabric-сборок.
Один файл, PyQt6 + minecraft-launcher-lib.
"""

import sys
import os
import re
import json
import zipfile
import subprocess
import shutil
import uuid
import hashlib
import tempfile
import threading
import logging
import traceback
from collections import Counter

import requests

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QPushButton, QLineEdit,
    QComboBox, QTextEdit, QFileDialog, QInputDialog, QMessageBox,
    QSplitter, QFrame, QProgressBar, QSpinBox, QCheckBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QStandardPaths
from PyQt6.QtGui import QFont, QPalette, QColor, QDragEnterEvent, QDropEvent

import minecraft_launcher_lib
import minecraft_launcher_lib.runtime


# ============================================================
#  КОНСТАНТЫ
# ============================================================
APP_NAME = "dotLauncher"
LAUNCHER_VERSION = "1.3.1"
INSTANCES_DB = "instances.json"

AUTHLIB_INJECTOR_VERSION = "1.2.5"
AUTHLIB_INJECTOR_URL = (
    f"https://github.com/yushijinhun/authlib-injector/releases/download/"
    f"v{AUTHLIB_INJECTOR_VERSION}/authlib-injector-{AUTHLIB_INJECTOR_VERSION}.jar"
)
# Если известен точный SHA-256 релиза — впишите сюда (hex). Иначе None.
AUTHLIB_INJECTOR_SHA256 = None
AUTHLIB_INJECTOR_MIN_SIZE = 100_000  # ~100 KB минимум для валидного JAR

DEFAULT_MEMORY_MB = 2048
MIN_MEMORY_MB = 1024
MAX_MEMORY_MB = 32768

# Папки, которые копируем из модпака. ВАЖНО: "mods" НЕ входит — моды
# отбираются и копируются отдельно (только валидные Fabric JAR).
COPYABLE_DIRS = (
    "config", "resourcepacks", "shaderpacks",
    "defaultconfigs", "kubejs", "scripts",
)

# Папки, которые НЕ обходим при поиске модов. ".minecraft" здесь нет —
# нам нужно заходить внутрь, чтобы найти .minecraft/mods.
SKIP_DIRS = {
    "saves", "logs", "crash-reports",
    "versions", "libraries", "assets", "screenshots",
}


# ============================================================
#  УТИЛИТЫ
# ============================================================
def safe_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_config_dir():
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppConfigLocation
    ) or os.path.join(os.path.expanduser("~"), ".config")
    if os.path.basename(os.path.normpath(base)) != APP_NAME:
        base = os.path.join(base, APP_NAME)
    os.makedirs(base, exist_ok=True)
    return base


def is_subpath(child, parent):
    try:
        child = os.path.realpath(child)
        parent = os.path.realpath(parent)
        return os.path.commonpath([child, parent]) == parent
    except (ValueError, OSError):
        return False


def sanitize_instance_name(name):
    name = "".join(c for c in name if c.isalnum() or c in " _-").strip()
    return name or "Unnamed"


def is_valid_zip(path, min_size=1000):
    """Проверка: файл существует, достаточно большой и является корректным ZIP."""
    try:
        if not os.path.isfile(path):
            return False
        if os.path.getsize(path) < min_size:
            return False
        with zipfile.ZipFile(path, "r") as zf:
            return zf.testzip() is None
    except Exception:
        return False


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().lower()


# ============================================================
#  ПОИСК JAVA
# ============================================================
_JAVA_VERSION_RE = re.compile(r'version\s+"(\d+)(?:\.(\d+))?')


def get_java_major(java_path):
    try:
        out = subprocess.run(
            [java_path, "-version"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        text = (out.stderr or "") + (out.stdout or "")
        m = _JAVA_VERSION_RE.search(text)
        if not m:
            return None
        major = int(m.group(1))
        if major == 1 and m.group(2):
            major = int(m.group(2))
        return major
    except Exception:
        return None


def _iter_java_candidates():
    seen = set()

    def add(path):
        if path and path not in seen and os.path.isfile(path):
            seen.add(path)
            return path
        return None

    # JAVA_HOME
    jh = os.environ.get("JAVA_HOME")
    if jh:
        exe = "java.exe" if sys.platform.startswith("win") else "java"
        p = add(os.path.join(jh, "bin", exe))
        if p:
            yield p

    java = shutil.which("java")
    if java:
        yield add(java) or None

    if sys.platform.startswith("win"):
        bases = [
            r"C:\Program Files\Java",
            r"C:\Program Files\Eclipse Adoptium",
            r"C:\Program Files\Microsoft",
            r"C:\Program Files\Amazon Corretto",
            r"C:\Program Files\Zulu",
            r"C:\Program Files\BellSoft",
            r"C:\Program Files (x86)\Java",
        ]
        exe = "java.exe"
    elif sys.platform == "darwin":
        bases = [
            "/Library/Java/JavaVirtualMachines",
            "/System/Library/Java/JavaVirtualMachines",
            os.path.expanduser("~/Library/Java/JavaVirtualMachines"),
            "/opt/homebrew/opt",
            "/usr/local/opt",
        ]
        exe = "java"
    else:
        bases = ["/usr/lib/jvm", "/usr/java", "/opt/java", "/opt"]
        exe = "java"

    for base in bases:
        if not os.path.isdir(base):
            continue
        for root, _dirs, files in os.walk(base):
            if exe in files and os.path.basename(root) == "bin":
                p = add(os.path.join(root, exe))
                if p:
                    yield p


def find_java(min_major=17):
    """Возвращает (path, major) или (None, None), если Java не найдена."""
    fallback = None
    for c in _iter_java_candidates():
        major = get_java_major(c)
        if major is None:
            continue
        if major >= min_major:
            return c, major
        if fallback is None:
            fallback = (c, major)
    if fallback:
        return fallback
    return (None, None)


# ============================================================
#  ПАРСИНГ fabric.mod.json
# ============================================================
def extract_minecraft_versions(mod_data):
    """
    Возвращает список версий Minecraft из depends.minecraft.
    Поддерживает: строку, список, диапазоны '>=1.20.1 <1.21', '~1.20.1',
    '1.20.x', Maven-диапазоны '[1.20.1,1.21)'.
    """
    depends = mod_data.get("depends", {})
    if not isinstance(depends, dict):
        return []
    mc = depends.get("minecraft")
    if mc is None:
        return []

    def strip_ops(s):
        return re.sub(r'^[<>=~^]+', '', s).strip()

    def clean_version(s):
        s = strip_ops(str(s).strip())
        s = re.sub(r'[.\-][xX*]+$', '', s).strip()
        if not s or s in ("*", "x"):
            return ""
        return s

    def parse_one(item):
        s = str(item).strip()
        if not s:
            return []
        # Maven-диапазон
        if s[0] in "[(" and s[-1] in "])":
            inner = s[1:-1]
            parts = [p.strip() for p in inner.split(",")]
            return [v for v in (clean_version(p) for p in parts) if v]
        # Диапазон через пробел
        if " " in s:
            return [v for v in (clean_version(p) for p in s.split()) if v]
        v = clean_version(s)
        return [v] if v else []

    result = []
    if isinstance(mc, list):
        for x in mc:
            result.extend(parse_one(x))
    else:
        result.extend(parse_one(mc))
    return result


def read_mod_mc_versions(jar_path):
    """Возвращает список версий MC или None, если это не Fabric-мод."""
    try:
        with zipfile.ZipFile(jar_path, "r") as zf:
            if "fabric.mod.json" not in zf.namelist():
                return None
            with zf.open("fabric.mod.json") as fm:
                data = json.load(fm)
        vers = extract_minecraft_versions(data)
        return vers or None
    except Exception:
        return None


# ============================================================
#  ПОТОК ЗАПУСКА / УСТАНОВКИ
# ============================================================
class LauncherThread(QThread):
    log_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal(bool, str)
    installing_signal = pyqtSignal(bool)

    def __init__(self, instance_path, version, username, uuid_val, token,
                 java_path="java", elyby=False, memory_mb=DEFAULT_MEMORY_MB,
                 use_managed_java=False):
        super().__init__()
        self.instance_path = instance_path
        self.version = version
        self.username = username
        self.uuid_val = uuid_val
        self.token = token
        self.java_path = java_path
        self.elyby = elyby
        self.memory_mb = memory_mb
        self.use_managed_java = use_managed_java
        self._stop = False
        self.process = None
        self._progress_max = 0

    def _cb_status(self, text):
        self.status_signal.emit(text)

    def _cb_progress(self, progress):
        self.progress_signal.emit(progress, self._progress_max)

    def _cb_max(self, max_progress):
        self._progress_max = max_progress
        self.progress_signal.emit(0, max_progress)

    def _make_callback(self):
        return {
            "setStatus": self._cb_status,
            "setProgress": self._cb_progress,
            "setMax": self._cb_max,
        }

    def _select_fabric_id(self, minecraft_dir):
        installed = minecraft_launcher_lib.utils.get_installed_versions(minecraft_dir)
        exact_suffix = f"-{self.version}"
        for v in installed:
            vid = v["id"]
            if vid.startswith("fabric-loader") and vid.endswith(exact_suffix):
                return vid
        # Для очень старых версий MC формат может быть другим — берём
        # только если это точно единственная fabric-сборка в папке.
        fabric_ids = [v["id"] for v in installed if v["id"].startswith("fabric-loader")]
        if len(fabric_ids) == 1:
            return fabric_ids[0]
        return None

    # ---- Managed Java через minecraft-launcher-lib ----
    def _get_required_runtime_component(self, minecraft_dir):
        """
        Читает versions/<version>/<version>.json и возвращает имя компонента
        рантайма (например, 'java-runtime-gamma'). None, если определить не удалось.
        """
        path = os.path.join(
            minecraft_dir, "versions", self.version, f"{self.version}.json"
        )
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            comp = (data.get("javaVersion") or {}).get("component")
            if comp:
                return comp
        except Exception:
            pass
        return None

    def _ensure_managed_java(self, minecraft_dir, callback):
        """
        Гарантирует наличие managed-Java для этой версии MC.
        Возвращает путь к java или None, если не удалось.
        """
        component = self._get_required_runtime_component(minecraft_dir)
        if not component:
            self.log_signal.emit(
                "[Внимание] Не удалось определить требуемый Java-runtime "
                "для этой версии Minecraft, использую системную Java."
            )
            return None

        self.log_signal.emit(
            f"[dotLauncher] Проверка/установка Java runtime: {component}"
        )
        try:
            minecraft_launcher_lib.runtime.install_jvm_runtime(
                component, minecraft_dir, callback=callback
            )
        except Exception as e:
            self.log_signal.emit(
                f"[Ошибка] Не удалось скачать Java runtime ({component}): {e}"
            )
            return None

        try:
            exe = minecraft_launcher_lib.runtime.get_executable_path(
                component, minecraft_dir
            )
        except Exception as e:
            self.log_signal.emit(
                f"[Ошибка] Java runtime установлен, но путь получить не удалось: {e}"
            )
            return None

        if exe and os.path.isfile(exe):
            self.log_signal.emit(f"[dotLauncher] Managed Java: {exe}")
            return exe
        self.log_signal.emit(
            "[Внимание] Managed Java не найден после установки, "
            "использую системную."
        )
        return None

    # ---- Bugfix: подкладываем Java в PATH для subprocess-вызовов ----
    def _prepend_java_to_path(self, java_path=None):
        """
        install_fabric внутри minecraft-launcher-lib на некоторых версиях
        вызывает `java` через subprocess. На Windows JRE не прописывается
        в PATH автоматически, поэтому добавляем bin-папку Java в PATH
        текущего процесса перед вызовом install_fabric.
        """
        jp = java_path or self.java_path
        if not jp:
            return
        if not os.path.isabs(jp):
            found = shutil.which(jp)
            if not found:
                return
            jp = found
        if not os.path.isfile(jp):
            return
        bin_dir = os.path.dirname(jp)
        if not bin_dir or not os.path.isdir(bin_dir):
            return
        cur = os.environ.get("PATH", "")
        parts = cur.split(os.pathsep) if cur else []
        if bin_dir.lower() not in [p.lower() for p in parts]:
            os.environ["PATH"] = bin_dir + os.pathsep + cur
            self.log_signal.emit(f"[dotLauncher] Добавлено в PATH: {bin_dir}")

    def _download_authlib(self, dest):
        r = requests.get(AUTHLIB_INJECTOR_URL, stream=True, timeout=60)
        r.raise_for_status()
        tmp_path = dest + ".tmp"
        try:
            with open(tmp_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if self._stop:
                        raise Exception("Отменено")
                    f.write(chunk)
            if not is_valid_zip(tmp_path, min_size=AUTHLIB_INJECTOR_MIN_SIZE):
                raise Exception("Скачанный файл не является валидным JAR")
            if AUTHLIB_INJECTOR_SHA256:
                actual = sha256_file(tmp_path)
                if actual != AUTHLIB_INJECTOR_SHA256.lower():
                    raise Exception(
                        f"SHA-256 не совпадает: ожидалось {AUTHLIB_INJECTOR_SHA256}, "
                        f"получено {actual}"
                    )
            os.replace(tmp_path, dest)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def run(self):
        try:
            self.installing_signal.emit(True)
            self.log_signal.emit(
                f"[dotLauncher] Начинаю установку Minecraft {self.version}..."
            )
            minecraft_dir = os.path.join(self.instance_path, ".minecraft")
            os.makedirs(minecraft_dir, exist_ok=True)

            callback = self._make_callback()

            # 1) Ванильный Minecraft (создаёт versions/<ver>/<ver>.json)
            self.log_signal.emit("[dotLauncher] Установка ванильного Minecraft...")
            minecraft_launcher_lib.install.install_minecraft_version(
                self.version, minecraft_dir, callback=callback
            )

            if self._stop:
                self.finished_signal.emit(False, "Отменено пользователем")
                return

            # 2) Определяем эффективную Java и, при managed-режиме,
            #    скачиваем рантайм ДО install_fabric, чтобы подложить её в PATH.
            effective_java = self.java_path
            if self.use_managed_java:
                managed = self._ensure_managed_java(minecraft_dir, callback)
                if managed:
                    effective_java = managed

            # 3) Bugfix: без bin-папки java в PATH install_fabric на Windows
            #    падает с FileNotFoundError: [WinError 2].
            self._prepend_java_to_path(effective_java)

            # 4) Fabric loader
            self.log_signal.emit("[dotLauncher] Установка Fabric загрузчика...")
            minecraft_launcher_lib.fabric.install_fabric(
                self.version, minecraft_dir, callback=callback
            )

            if self._stop:
                self.finished_signal.emit(False, "Отменено пользователем")
                return

            fabric_id = self._select_fabric_id(minecraft_dir)
            if not fabric_id:
                raise Exception(
                    f"Не удалось найти установленную версию Fabric для "
                    f"Minecraft {self.version}"
                )
            self.log_signal.emit(f"[dotLauncher] Fabric версия: {fabric_id}")

            jvm_args = [
                f"-Xmx{self.memory_mb}M",
                f"-Xms{min(self.memory_mb, 1024)}M",
            ]

            if self.elyby:
                injector_path = os.path.join(self.instance_path, "authlib-injector.jar")
                if not is_valid_zip(injector_path, min_size=AUTHLIB_INJECTOR_MIN_SIZE):
                    self.log_signal.emit("[dotLauncher] Скачивание authlib-injector...")
                    try:
                        self._download_authlib(injector_path)
                        self.log_signal.emit(
                            f"[dotLauncher] authlib-injector "
                            f"{AUTHLIB_INJECTOR_VERSION} загружен."
                        )
                    except Exception as e:
                        self.log_signal.emit(
                            f"[Ошибка] Не удалось скачать authlib-injector: {e}"
                        )

                # Обязательно: без валидного инжектора Ely.by работать не будет
                if not is_valid_zip(injector_path, min_size=AUTHLIB_INJECTOR_MIN_SIZE):
                    raise Exception(
                        "authlib-injector недоступен, запуск Ely.by невозможен"
                    )
                jvm_args.append(f"-javaagent:{injector_path}=ely.by")

            options = {
                "username": self.username,
                "uuid": self.uuid_val,
                "token": self.token,
                "executablePath": effective_java,
                "jvmArguments": jvm_args,
                "launcherName": APP_NAME,
                "launcherVersion": LAUNCHER_VERSION,
                "gameDirectory": minecraft_dir,
            }

            command = minecraft_launcher_lib.command.get_minecraft_command(
                fabric_id, minecraft_dir, options
            )

            if self._stop:
                self.finished_signal.emit(False, "Отменено пользователем")
                return

            self.log_signal.emit("[dotLauncher] Запуск Minecraft...")
            self.log_signal.emit(f"[dotLauncher] Рабочая папка: {minecraft_dir}")
            self.log_signal.emit(
                f"[dotLauncher] JVM: {effective_java} ({self.memory_mb} MB)"
            )

            self.installing_signal.emit(False)

            self.process = subprocess.Popen(
                command,
                cwd=minecraft_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                encoding="utf-8",
                errors="replace",
            )

            for line in iter(self.process.stdout.readline, ""):
                if self._stop:
                    break
                if line:
                    self.log_signal.emit(line.rstrip())

            self.process.wait()
            rc = self.process.returncode
            if rc == 0:
                self.log_signal.emit("[dotLauncher] Игра завершена штатно.")
                self.finished_signal.emit(True, "Игра завершена")
            else:
                self.log_signal.emit(
                    f"[dotLauncher] Игра завершилась с кодом {rc}."
                )
                self.finished_signal.emit(False, f"Игра завершилась с кодом {rc}")

        except Exception as e:
            self.log_signal.emit(f"[Ошибка] {type(e).__name__}: {e}")
            try:
                self.log_signal.emit(traceback.format_exc())
            except Exception:
                pass
            self.finished_signal.emit(False, str(e))

    def stop(self):
        self._stop = True
        if self.process:
            try:
                self.process.terminate()
            except Exception:
                pass


# ============================================================
#  ПОТОК АВТОРИЗАЦИИ ELY.BY
# ============================================================
class ElybyLoginThread(QThread):
    finished_signal = pyqtSignal(bool, dict, str)

    def __init__(self, email, password, client_token):
        super().__init__()
        self.email = email
        self.password = password
        self.client_token = client_token

    def run(self):
        try:
            url = "https://authserver.ely.by/auth/authenticate"
            payload = {
                "username": self.email,
                "password": self.password,
                "clientToken": self.client_token,
                "requestUser": True,
            }
            r = requests.post(url, json=payload, timeout=15)
            try:
                data = r.json()
            except ValueError:
                self.finished_signal.emit(False, {}, "Некорректный ответ сервера")
                return
            if r.status_code == 200:
                self.finished_signal.emit(True, data, "")
            else:
                err = data.get("errorMessage", "Неизвестная ошибка")
                self.finished_signal.emit(False, {}, err)
        except requests.exceptions.Timeout:
            self.finished_signal.emit(False, {}, "Таймаут соединения")
        except Exception as e:
            self.finished_signal.emit(False, {}, str(e))


class ElybyRefreshThread(QThread):
    finished_signal = pyqtSignal(bool, dict, str)

    def __init__(self, access_token, client_token):
        super().__init__()
        self.access_token = access_token
        self.client_token = client_token

    def run(self):
        try:
            url = "https://authserver.ely.by/auth/refresh"
            payload = {
                "accessToken": self.access_token,
                "clientToken": self.client_token,
                "requestUser": True,
            }
            r = requests.post(url, json=payload, timeout=15)
            try:
                data = r.json()
            except ValueError:
                self.finished_signal.emit(False, {}, "Некорректный ответ сервера")
                return
            if r.status_code == 200:
                self.finished_signal.emit(True, data, "")
            else:
                err = data.get("errorMessage", "Не удалось обновить сессию")
                self.finished_signal.emit(False, {}, err)
        except Exception as e:
            self.finished_signal.emit(False, {}, str(e))


# ============================================================
#  ПОТОК ИМПОРТА МОДПАКА
# ============================================================
class ModpackImportThread(QThread):
    log_signal = pyqtSignal(str)
    ask_signal = pyqtSignal(list)  # список версий MC для выбора
    finished_signal = pyqtSignal(bool, dict)  # success, {info...} / {error: ...}

    def __init__(self, files, workspace, instances_dir, existing_ids):
        super().__init__()
        self.files = list(files)
        self.workspace = workspace
        self.instances_dir = instances_dir
        self.existing_ids = set(existing_ids)
        self._event = threading.Event()
        self._chosen_version = None
        self._chosen_name = None
        self._cancelled = False
        self._temp_dirs = []

    def set_user_choice(self, version, name):
        self._chosen_version = version
        self._chosen_name = name
        self._event.set()

    def cancel(self):
        self._cancelled = True
        self._event.set()

    # ---- scanning ----
    def _extract_zip(self, zip_path):
        temp = tempfile.mkdtemp(prefix="dotlauncher_import_")
        self._temp_dirs.append(temp)
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.infolist():
                name = member.filename
                # Защита от zip-slip
                if name.startswith("/") or name.startswith("\\"):
                    continue
                parts = re.split(r"[\\/]", name)
                if ".." in parts:
                    continue
                zf.extract(member, temp)
        return temp

    def _scan_folder(self, folder, jars_info, versions_flat, extra_dirs):
        # Сканируем JAR'ы во всём дереве (кроме skip-папок)
        for root, dirs, files in os.walk(folder, followlinks=False):
            # Пруним директории
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

            for fn in files:
                if not fn.lower().endswith(".jar"):
                    continue
                full = os.path.join(root, fn)
                mc_vers = read_mod_mc_versions(full)
                if not mc_vers:
                    continue
                jars_info.append((full, mc_vers))
                versions_flat.extend(mc_vers)
                self.log_signal.emit(
                    f"[dotLauncher] {os.path.basename(full)} → "
                    f"Minecraft {', '.join(mc_vers)}"
                )

        # Ищем копируемые папки в корне и в .minecraft
        for base in (folder, os.path.join(folder, ".minecraft")):
            if not os.path.isdir(base):
                continue
            for name in COPYABLE_DIRS:
                src = os.path.join(base, name)
                if os.path.isdir(src) and name not in extra_dirs:
                    extra_dirs[name] = src

    def _scan(self):
        jars_info = []
        versions_flat = []
        extra_dirs = {}

        for path in self.files:
            if self._cancelled:
                break
            if os.path.isfile(path):
                low = path.lower()
                if low.endswith(".jar"):
                    mc_vers = read_mod_mc_versions(path)
                    if mc_vers:
                        jars_info.append((path, mc_vers))
                        versions_flat.extend(mc_vers)
                        self.log_signal.emit(
                            f"[dotLauncher] {os.path.basename(path)} → "
                            f"Minecraft {', '.join(mc_vers)}"
                        )
                    else:
                        self.log_signal.emit(
                            f"[dotLauncher] {os.path.basename(path)} — "
                            f"не Fabric-мод, пропускаю."
                        )
                elif low.endswith(".zip"):
                    self.log_signal.emit(
                        f"[dotLauncher] Распаковка {os.path.basename(path)}..."
                    )
                    try:
                        temp = self._extract_zip(path)
                        self._scan_folder(temp, jars_info, versions_flat, extra_dirs)
                    except Exception as e:
                        self.log_signal.emit(
                            f"[Ошибка] Не удалось распаковать "
                            f"{os.path.basename(path)}: {e}"
                        )
            elif os.path.isdir(path):
                self._scan_folder(path, jars_info, versions_flat, extra_dirs)

        return jars_info, versions_flat, extra_dirs

    # ---- copying ----
    def _new_instance_id(self):
        while True:
            iid = str(uuid.uuid4())[:8]
            if iid in self.existing_ids:
                continue
            if os.path.exists(os.path.join(self.instances_dir, iid)):
                continue
            return iid

    def _copy_files(self, jars_info, extra_dirs, version, name):
        instance_id = self._new_instance_id()
        instance_dir = os.path.join(self.instances_dir, instance_id)
        minecraft_dir = os.path.join(instance_dir, ".minecraft")
        mods_dir = os.path.join(minecraft_dir, "mods")
        os.makedirs(mods_dir, exist_ok=True)

        # Копируем моды с разрешением коллизий по имени
        copied_names = set()
        for jar, _ in jars_info:
            base = os.path.basename(jar)
            target_name = base
            if target_name in copied_names:
                root, ext = os.path.splitext(base)
                i = 1
                while f"{root}_{i}{ext}" in copied_names:
                    i += 1
                target_name = f"{root}_{i}{ext}"
            copied_names.add(target_name)
            try:
                shutil.copy2(jar, os.path.join(mods_dir, target_name))
                self.log_signal.emit(f"[dotLauncher] Скопирован {target_name}")
            except Exception as e:
                self.log_signal.emit(
                    f"[Ошибка] Не удалось скопировать {base}: {e}"
                )

        # Дополнительные папки
        for dir_name, src in extra_dirs.items():
            dst = os.path.join(minecraft_dir, dir_name)
            try:
                if os.path.isdir(dst):
                    shutil.rmtree(dst, ignore_errors=True)
                shutil.copytree(src, dst, symlinks=False)
                self.log_signal.emit(f"[dotLauncher] Скопирована папка {dir_name}")
            except Exception as e:
                self.log_signal.emit(
                    f"[Ошибка] Не удалось скопировать {dir_name}: {e}"
                )

        path_rel = os.path.relpath(instance_dir, self.workspace)
        return {
            "instance_id": instance_id,
            "name": name,
            "version": version,
            "loader": "fabric",
            "path_rel": path_rel,
        }

    def run(self):
        try:
            self.log_signal.emit(
                f"[dotLauncher] Обработка {len(self.files)} элементов..."
            )
            jars_info, versions_flat, extra_dirs = self._scan()

            if self._cancelled:
                self.finished_signal.emit(False, {"error": "Отменено"})
                return

            if not jars_info:
                self.finished_signal.emit(
                    False, {"error": "Не найдено подходящих Fabric-модов."}
                )
                return

            unique_versions = sorted(set(versions_flat))
            if len(unique_versions) == 1:
                chosen_version = unique_versions[0]
            else:
                self.log_signal.emit(
                    f"[dotLauncher] Обнаружены версии: "
                    f"{', '.join(unique_versions)}"
                )
                # Просим UI выбрать версию и имя
                self.ask_signal.emit(unique_versions)
                self._event.wait()
                self._event.clear()
                if self._cancelled or not self._chosen_version or not self._chosen_name:
                    self.finished_signal.emit(False, {"error": "Отменено"})
                    return
                chosen_version = self._chosen_version

            # Если версия одна — всё равно нужно спросить имя
            if self._chosen_name is None:
                self.ask_signal.emit([chosen_version])
                self._event.wait()
                self._event.clear()
                if self._cancelled or not self._chosen_version or not self._chosen_name:
                    self.finished_signal.emit(False, {"error": "Отменено"})
                    return
                chosen_version = self._chosen_version

            name = sanitize_instance_name(self._chosen_name)
            info = self._copy_files(jars_info, extra_dirs, chosen_version, name)
            self.log_signal.emit(
                f"[dotLauncher] Сборка «{name}» (Fabric {chosen_version}) создана."
            )
            self.finished_signal.emit(True, info)

        except Exception as e:
            self.log_signal.emit(f"[Ошибка] {type(e).__name__}: {e}")
            try:
                self.log_signal.emit(traceback.format_exc())
            except Exception:
                pass
            self.finished_signal.emit(False, {"error": str(e)})
        finally:
            for tmp in self._temp_dirs:
                shutil.rmtree(tmp, ignore_errors=True)
            self._temp_dirs.clear()


# ============================================================
#  DROP ZONE
# ============================================================
class DropZone(QLabel):
    filesDropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFont(QFont("Segoe UI", 14))
        self.setStyleSheet("""
            QLabel {
                border: 2px dashed #555;
                border-radius: 10px;
                padding: 40px;
                color: #888;
                background-color: #2a2a2a;
            }
            QLabel:hover {
                border-color: #777;
                background-color: #303030;
            }
        """)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        if files:
            self.filesDropped.emit(files)
        event.acceptProposedAction()


# ============================================================
#  ГЛАВНОЕ ОКНО
# ============================================================
class DotLauncher(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = {}
        self.instances = {}
        self.current_instance = None
        self.launcher_thread = None
        self.login_thread = None
        self.refresh_thread = None
        self.import_thread = None

        self.config_dir = get_config_dir()
        self.config_path = os.path.join(self.config_dir, "dot_config.json")

        self.init_ui()
        self.load_config()

    # ---------- ИНТЕРФЕЙС ----------
    def init_ui(self):
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1100, 760)

        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(220, 220, 220))
        palette.setColor(QPalette.ColorRole.Base, QColor(25, 25, 25))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(35, 35, 35))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(30, 30, 30))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor(220, 220, 220))
        palette.setColor(QPalette.ColorRole.Text, QColor(220, 220, 220))
        palette.setColor(QPalette.ColorRole.Button, QColor(45, 45, 45))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(220, 220, 220))
        palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 100, 100))
        palette.setColor(QPalette.ColorRole.Link, QColor(100, 180, 255))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(60, 120, 200))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
        self.setPalette(palette)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(2)

        # ---------- ЛЕВАЯ ПАНЕЛЬ ----------
        left = QFrame()
        left.setFrameShape(QFrame.Shape.StyledPanel)
        left.setStyleSheet("QFrame { background-color: #1e1e1e; }")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 12, 12)

        account_label = QLabel("Аккаунт")
        account_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        left_layout.addWidget(account_label)

        self.account_type = QComboBox()
        self.account_type.addItems(["Offline", "Ely.by"])
        self.account_type.currentIndexChanged.connect(self.on_account_type_changed)
        left_layout.addWidget(self.account_type)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Никнейм")
        self.username_input.editingFinished.connect(self.save_account)
        left_layout.addWidget(self.username_input)

        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("Email (Ely.by)")
        self.email_input.setVisible(False)
        self.email_input.editingFinished.connect(self.save_account)
        left_layout.addWidget(self.email_input)

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Пароль (Ely.by)")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setVisible(False)
        left_layout.addWidget(self.password_input)

        self.login_button = QPushButton("Войти")
        self.login_button.setVisible(False)
        self.login_button.clicked.connect(self.elyby_login)
        left_layout.addWidget(self.login_button)

        self.login_status = QLabel("")
        self.login_status.setStyleSheet("color: #888; font-size: 11px;")
        self.login_status.setWordWrap(True)
        left_layout.addWidget(self.login_status)

        left_layout.addSpacing(10)

        memory_label = QLabel("Память (MB)")
        memory_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        left_layout.addWidget(memory_label)

        self.memory_spin = QSpinBox()
        self.memory_spin.setRange(MIN_MEMORY_MB, MAX_MEMORY_MB)
        self.memory_spin.setSingleStep(256)
        self.memory_spin.setValue(DEFAULT_MEMORY_MB)
        self.memory_spin.valueChanged.connect(self.save_memory)
        left_layout.addWidget(self.memory_spin)

        left_layout.addSpacing(6)

        self.java_button = QPushButton("Выбрать Java...")
        self.java_button.clicked.connect(self.choose_java)
        left_layout.addWidget(self.java_button)

        self.java_status = QLabel("Java: авто")
        self.java_status.setStyleSheet("color: #888; font-size: 11px;")
        self.java_status.setWordWrap(True)
        left_layout.addWidget(self.java_status)

        self.managed_java_check = QCheckBox("Скачивать Java автоматически")
        self.managed_java_check.setToolTip(
            "Лаунчер скачает нужную для этой версии Minecraft Java\n"
            "через minecraft-launcher-lib и запустит игру на ней.\n"
            "Системная Java и ручной выбор при этом игнорируются."
        )
        self.managed_java_check.toggled.connect(self.save_managed_java)
        left_layout.addWidget(self.managed_java_check)

        left_layout.addSpacing(10)

        instances_label = QLabel("Сборки")
        instances_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        left_layout.addWidget(instances_label)

        self.instance_list = QListWidget()
        self.instance_list.itemClicked.connect(self.on_instance_selected)
        left_layout.addWidget(self.instance_list)

        self.delete_button = QPushButton("Удалить сборку")
        self.delete_button.clicked.connect(self.delete_instance)
        left_layout.addWidget(self.delete_button)

        left_layout.addStretch()

        # ---------- ЦЕНТРАЛЬНАЯ ПАНЕЛЬ ----------
        center = QFrame()
        center.setFrameShape(QFrame.Shape.StyledPanel)
        center.setStyleSheet("QFrame { background-color: #252525; }")
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(20, 20, 20, 20)

        self.title_label = QLabel(APP_NAME)
        self.title_label.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_layout.addWidget(self.title_label)

        self.drop_zone = DropZone(self)
        self.drop_zone.setText(
            "Перетащи сюда .jar файлы модов, папку модпака\n"
            "или .zip-архив, чтобы создать сборку dotLauncher"
        )
        self.drop_zone.filesDropped.connect(self.handle_dropped_files)
        center_layout.addWidget(self.drop_zone, 1)

        self.instance_info = QWidget()
        self.instance_info.setVisible(False)
        info_layout = QVBoxLayout(self.instance_info)
        info_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.instance_name_label = QLabel("")
        self.instance_name_label.setFont(QFont("Segoe UI", 26, QFont.Weight.Bold))
        self.instance_name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_layout.addWidget(self.instance_name_label)

        self.instance_version_label = QLabel("")
        self.instance_version_label.setFont(QFont("Segoe UI", 16))
        self.instance_version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_layout.addWidget(self.instance_version_label)

        info_layout.addSpacing(30)

        self.play_button = QPushButton("ИГРАТЬ")
        self.play_button.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        self.play_button.setFixedSize(260, 64)
        self.play_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border-radius: 12px;
                padding: 10px;
            }
            QPushButton:hover { background-color: #45a049; }
            QPushButton:disabled { background-color: #555; color: #888; }
        """)
        self.play_button.clicked.connect(self.play_game)
        info_layout.addWidget(self.play_button, alignment=Qt.AlignmentFlag.AlignCenter)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedWidth(320)
        info_layout.addWidget(self.progress_bar, alignment=Qt.AlignmentFlag.AlignCenter)

        center_layout.addWidget(self.instance_info, 1)

        console_label = QLabel("Консоль")
        console_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        console_label.setStyleSheet("color: #aaa;")
        center_layout.addWidget(console_label)

        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(QFont("Consolas", 10))
        self.console.setStyleSheet("""
            QTextEdit {
                background-color: #0a0a0a;
                color: #00ff00;
                border: 1px solid #333;
                border-radius: 6px;
                padding: 6px;
            }
        """)
        self.console.setFixedHeight(220)
        center_layout.addWidget(self.console)

        splitter.addWidget(left)
        splitter.addWidget(center)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        main_layout.addWidget(splitter)

        self.status_bar = self.statusBar()
        self.status_bar.setStyleSheet("background-color: #1a1a1a; color: #aaa;")
        self.status_bar.showMessage("Готов")

    # ---------- КОНФИГ ----------
    def _validate_config(self, cfg):
        """Приводит конфиг к ожидаемому виду, отбрасывая мусор."""
        if not isinstance(cfg, dict):
            return {}
        out = {}
        if isinstance(cfg.get("workspace"), str) and cfg["workspace"]:
            out["workspace"] = cfg["workspace"]
        for key in ("username", "email", "elyby_username", "elyby_uuid",
                    "elyby_access_token", "elyby_refresh_token",
                    "client_token", "java_path"):
            v = cfg.get(key)
            if isinstance(v, str):
                out[key] = v
        mem = safe_int(cfg.get("memory_mb"), DEFAULT_MEMORY_MB)
        out["memory_mb"] = max(MIN_MEMORY_MB, min(MAX_MEMORY_MB, mem))
        out["use_managed_java"] = bool(cfg.get("use_managed_java", False))
        return out

    def load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                self.config = self._validate_config(raw)
                if self.config.get("workspace") and os.path.isdir(self.config["workspace"]):
                    self.log("[dotLauncher] Конфигурация загружена.")
                    self.init_workspace()
                    return
                self.log("[Внимание] Рабочая папка из конфига недоступна.")
            except Exception as e:
                self.log(f"[Ошибка] Не удалось загрузить конфигурацию: {e}")

        # Первый запуск / восстановление
        QMessageBox.information(
            self,
            f"Добро пожаловать в {APP_NAME}!",
            "Пожалуйста, выберите папку на компьютере,\n"
            "где лаунчер создаст свои рабочие файлы\n"
            "и будет хранить сборки."
        )
        folder = QFileDialog.getExistingDirectory(
            self, f"Выберите папку для {APP_NAME}"
        )
        if not folder:
            QMessageBox.critical(
                self, "Ошибка",
                "Папка не выбрана. Лаунчер не может работать без рабочей директории."
            )
            sys.exit(1)

        self.config["workspace"] = folder
        self.config.setdefault("username", "")
        self.config.setdefault("client_token", str(uuid.uuid4()))
        self.config.setdefault("memory_mb", DEFAULT_MEMORY_MB)
        self.config.setdefault("use_managed_java", False)
        self.save_config()
        self.init_workspace()

    def init_workspace(self):
        workspace = self.config["workspace"]
        instances_dir = os.path.join(workspace, "instances")
        os.makedirs(instances_dir, exist_ok=True)
        self.config["instances_dir"] = instances_dir

        mem = safe_int(self.config.get("memory_mb"), DEFAULT_MEMORY_MB)
        self.memory_spin.blockSignals(True)
        self.memory_spin.setValue(mem)
        self.memory_spin.blockSignals(False)

        self.managed_java_check.blockSignals(True)
        self.managed_java_check.setChecked(
            bool(self.config.get("use_managed_java", False))
        )
        self.managed_java_check.blockSignals(False)

        # Загружаем базу сборок
        db_path = os.path.join(workspace, INSTANCES_DB)
        self.instances = {}
        if os.path.exists(db_path):
            try:
                with open(db_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    self.instances = self._migrate_instances(raw, workspace)
            except Exception as e:
                self.log(f"[Ошибка] Не удалось загрузить базу сборок: {e}")

        self.refresh_instance_list()

        # Восстановление аккаунта
        if self.config.get("email"):
            self.account_type.setCurrentIndex(1)
            self.email_input.setText(self.config["email"])
            if self.config.get("elyby_username"):
                self.username_input.setText(self.config["elyby_username"])
                self.login_status.setText(
                    f"Сохранён аккаунт: {self.config['elyby_username']}"
                )
            # Пробуем обновить сессию, если есть refresh-токен
            if self.config.get("elyby_refresh_token"):
                self._try_refresh_elyby()
        elif self.config.get("username"):
            self.username_input.setText(self.config["username"])

        # Java
        if self.config.get("java_path"):
            self.java_status.setText(f"Java: {self.config['java_path']} (вручную)")
        else:
            self.java_status.setText("Java: авто")

        self.log(f"[dotLauncher] Конфиг: {self.config_dir}")
        self.log(f"[dotLauncher] Рабочая папка: {workspace}")
        self.log("[dotLauncher] Готов к работе.")

    def _migrate_instances(self, raw, workspace):
        """Поддержка старых записей с абсолютным 'path' -> 'path_rel'."""
        out = {}
        for iid, inst in raw.items():
            if not isinstance(inst, dict):
                continue
            name = inst.get("name")
            version = inst.get("version")
            loader = inst.get("loader", "fabric")
            if not name or not version:
                continue
            if "path_rel" in inst and isinstance(inst["path_rel"], str):
                path_rel = inst["path_rel"]
            elif "path" in inst and isinstance(inst["path"], str):
                try:
                    path_rel = os.path.relpath(inst["path"], workspace)
                except ValueError:
                    continue
            else:
                continue
            out[iid] = {
                "name": name, "version": version,
                "loader": loader, "path_rel": path_rel,
            }
        return out

    def save_config(self):
        try:
            cfg = dict(self.config)
            cfg.pop("instances_dir", None)  # не сохраняем производное
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            try:
                os.chmod(self.config_path, 0o600)
            except OSError:
                pass
        except Exception as e:
            self.log(f"[Ошибка] Не удалось сохранить конфигурацию: {e}")

    def save_instances(self):
        db_path = os.path.join(self.config["workspace"], INSTANCES_DB)
        try:
            with open(db_path, "w", encoding="utf-8") as f:
                json.dump(self.instances, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log(f"[Ошибка] Не удалось сохранить базу сборок: {e}")

    def save_memory(self, value):
        self.config["memory_mb"] = int(value)
        self.save_config()

    def save_managed_java(self, checked):
        self.config["use_managed_java"] = bool(checked)
        self.save_config()

    def _instance_abs_path(self, inst):
        return os.path.join(self.config["workspace"], inst["path_rel"])

    # ---------- JAVA ----------
    def choose_java(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите исполняемый файл Java", "",
            "Java (java;java.exe);;Все файлы (*)"
        )
        if not path:
            return
        major = get_java_major(path)
        self.config["java_path"] = path
        self.save_config()
        if major is None:
            self.java_status.setText(f"Java: {path} (версия не определена)")
        else:
            self.java_status.setText(f"Java: {path} (major={major})")

    def _resolve_java(self):
        jp = self.config.get("java_path")
        if jp and os.path.isfile(jp):
            return jp, get_java_major(jp)
        if jp:
            self.log(
                f"[Внимание] Java из конфига не найдена: {jp!r}, ищу автоматически."
            )
            self.config.pop("java_path", None)
            self.save_config()
            self.java_status.setText("Java: авто")
        return find_java()

    # ---------- АККАУНТ ----------
    def on_account_type_changed(self, index):
        is_elyby = (index == 1)
        self.username_input.setVisible(not is_elyby)
        self.email_input.setVisible(is_elyby)
        self.password_input.setVisible(is_elyby)
        self.login_button.setVisible(is_elyby)
        self.save_account()

    def save_account(self):
        if self.account_type.currentIndex() == 0:
            self.config["username"] = self.username_input.text()
        else:
            self.config["email"] = self.email_input.text()
        self.save_config()

    def elyby_login(self):
        email = self.email_input.text().strip()
        password = self.password_input.text()
        if not email or not password:
            self.login_status.setText("Введите email и пароль")
            return

        client_token = self.config.get("client_token") or str(uuid.uuid4())
        self.config["client_token"] = client_token
        self.save_config()

        self.login_button.setEnabled(False)
        self.login_status.setText("Авторизация...")

        self.login_thread = ElybyLoginThread(email, password, client_token)
        self.login_thread.finished_signal.connect(self.on_elyby_login_finished)
        self.login_thread.start()

    def on_elyby_login_finished(self, success, data, error):
        # Пароль больше не нужен в памяти/виджете
        self.password_input.clear()
        self.login_button.setEnabled(True)

        if not success:
            self.login_status.setText(f"Ошибка: {error}")
            self.log(f"[Ошибка] Ely.by: {error}")
            return

        access_token = data.get("accessToken")
        refresh_token = data.get("refreshToken")
        selected = data.get("selectedProfile", {})
        uuid_val = selected.get("id")
        username = selected.get("name")
        # clientToken может вернуться другим — обновим
        new_client = data.get("clientToken")
        if new_client:
            self.config["client_token"] = new_client

        if not access_token or not uuid_val or not username:
            self.login_status.setText("Некорректный ответ Ely.by")
            return

        self.config["elyby_access_token"] = access_token
        if refresh_token:
            self.config["elyby_refresh_token"] = refresh_token
        self.config["elyby_uuid"] = uuid_val
        self.config["elyby_username"] = username
        self.save_config()

        self.username_input.setText(username)
        self.login_status.setText(f"Вошли как {username}")
        self.log(f"[dotLauncher] Авторизация Ely.by успешна: {username}")

    def _try_refresh_elyby(self):
        client_token = self.config.get("client_token")
        access_token = self.config.get("elyby_access_token")
        if not client_token or not access_token:
            return
        self.refresh_thread = ElybyRefreshThread(access_token, client_token)
        self.refresh_thread.finished_signal.connect(self.on_elyby_refresh_finished)
        self.refresh_thread.start()

    def on_elyby_refresh_finished(self, success, data, error):
        if not success:
            self.log(f"[dotLauncher] Не удалось обновить сессию Ely.by: {error}")
            return
        access_token = data.get("accessToken")
        refresh_token = data.get("refreshToken")
        if access_token:
            self.config["elyby_access_token"] = access_token
        if refresh_token:
            self.config["elyby_refresh_token"] = refresh_token
        self.save_config()
        self.log("[dotLauncher] Сессия Ely.by обновлена.")

    # ---------- DRAG-AND-DROP / ИМПОРТ ----------
    def handle_dropped_files(self, files):
        if self.import_thread and self.import_thread.isRunning():
            self.log("[Ошибка] Импорт уже выполняется.")
            return
        if self.launcher_thread and self.launcher_thread.isRunning():
            self.log("[Ошибка] Дождитесь завершения текущего запуска.")
            return

        # Собираем подходящие пути
        relevant = []
        for f in files:
            if os.path.isdir(f):
                relevant.append(f)
            elif os.path.isfile(f):
                low = f.lower()
                if low.endswith(".jar") or low.endswith(".zip"):
                    relevant.append(f)

        if not relevant:
            self.log("[Ошибка] Нет .jar, .zip или папок для обработки.")
            return

        self.play_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        self.status_bar.showMessage("Импорт модпака...")

        self.import_thread = ModpackImportThread(
            relevant,
            self.config["workspace"],
            self.config["instances_dir"],
            self.instances.keys(),
        )
        self.import_thread.log_signal.connect(self.log)
        self.import_thread.ask_signal.connect(self.on_import_ask)
        self.import_thread.finished_signal.connect(self.on_import_finished)
        self.import_thread.start()

    def on_import_ask(self, versions):
        """UI-поток: спрашиваем версию и имя, отвечаем потоку."""
        thread = self.import_thread
        if thread is None:
            return

        chosen_version = versions[0]
        if len(versions) > 1:
            chosen_version, ok = QInputDialog.getItem(
                self, "Выбор версии Minecraft",
                "Моды требуют разные версии Minecraft.\nВыберите целевую версию:",
                versions, 0, False,
            )
            if not ok or not chosen_version:
                thread.cancel()
                return
        else:
            # Одна версия — можно молча принять
            self.log(f"[dotLauncher] Целевая версия Minecraft: {chosen_version}")

        name, ok = QInputDialog.getText(
            self, "Создание сборки",
            f"Обнаружена сборка Fabric {chosen_version}.\n"
            f"Введите название для этой сборки:",
        )
        if not ok or not name.strip():
            thread.cancel()
            return

        thread.set_user_choice(chosen_version, name)

    def on_import_finished(self, success, info):
        self.play_button.setEnabled(True)
        self.delete_button.setEnabled(True)
        self.status_bar.showMessage("Готов")

        if not success:
            msg = info.get("error", "Ошибка импорта")
            self.log(f"[dotLauncher] Импорт не завершён: {msg}")
            return

        iid = info["instance_id"]
        self.instances[iid] = {
            "name": info["name"],
            "version": info["version"],
            "loader": info["loader"],
            "path_rel": info["path_rel"],
        }
        self.save_instances()
        self.refresh_instance_list()
        self.log(f"[dotLauncher] Сборка «{info['name']}» добавлена.")

    # ---------- СПИСОК СБОРОК ----------
    def refresh_instance_list(self):
        self.instance_list.clear()
        for iid, inst in self.instances.items():
            item = QListWidgetItem(inst["name"])
            item.setData(Qt.ItemDataRole.UserRole, iid)
            self.instance_list.addItem(item)

        if self.current_instance and self.current_instance in self.instances:
            for i in range(self.instance_list.count()):
                item = self.instance_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) == self.current_instance:
                    self.instance_list.setCurrentItem(item)
                    break

    def on_instance_selected(self, item):
        instance_id = item.data(Qt.ItemDataRole.UserRole)
        if instance_id in self.instances:
            self.current_instance = instance_id
            inst = self.instances[instance_id]
            self.instance_name_label.setText(inst["name"])
            self.instance_version_label.setText(f"Fabric {inst['version']}")
            self.drop_zone.setVisible(False)
            self.instance_info.setVisible(True)
            self.title_label.setVisible(False)
            self.status_bar.showMessage(f"Выбрана сборка: {inst['name']}")

    def delete_instance(self):
        if not self.current_instance:
            return
        if self.launcher_thread and self.launcher_thread.isRunning():
            QMessageBox.warning(self, "Занято", "Дождитесь завершения запуска.")
            return

        inst = self.instances[self.current_instance]
        reply = QMessageBox.question(
            self, "Удаление сборки",
            f"Удалить сборку «{inst['name']}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        path = self._instance_abs_path(inst)
        instances_dir = self.config["instances_dir"]
        deletion_ok = True

        if not is_subpath(path, instances_dir):
            self.log(f"[Ошибка] Небезопасный путь сборки: {path!r}, запись удалена без файлов.")
        elif os.path.exists(path):
            try:
                shutil.rmtree(path, ignore_errors=False)
            except Exception as e:
                deletion_ok = False
                self.log(f"[Ошибка] Не удалось удалить папку: {e}")
                QMessageBox.warning(
                    self, "Ошибка удаления",
                    f"Не удалось удалить файлы сборки:\n{e}\n\n"
                    f"Запись сохранена, чтобы не потерять данные."
                )

        if not deletion_ok:
            return

        del self.instances[self.current_instance]
        self.current_instance = None
        self.save_instances()
        self.refresh_instance_list()
        self.instance_info.setVisible(False)
        self.drop_zone.setVisible(True)
        self.title_label.setVisible(True)
        self.log(f"[dotLauncher] Сборка «{inst['name']}» удалена.")

    # ---------- ЗАПУСК ИГРЫ ----------
    def play_game(self):
        if not self.current_instance:
            return
        if self.launcher_thread and self.launcher_thread.isRunning():
            return

        inst = self.instances[self.current_instance]

        if self.account_type.currentIndex() == 0:
            username = self.username_input.text().strip()
            if not username:
                self.log("[Ошибка] Введите никнейм.")
                return
            uuid_val = self._offline_uuid(username)
            token = "0" * 32
            elyby = False
        else:
            username = self.config.get("elyby_username", "")
            uuid_val = self.config.get("elyby_uuid", "")
            token = self.config.get("elyby_access_token", "")
            if not username or not token:
                self.log("[Ошибка] Сначала авторизуйтесь в Ely.by.")
                return
            elyby = True

        use_managed = self.managed_java_check.isChecked()

        if use_managed:
            self.log(
                "[dotLauncher] Режим: managed Java "
                "(скачается при первом запуске)."
            )
            java_path, java_major = None, None
        else:
            java_path, java_major = self._resolve_java()
            if not java_path:
                QMessageBox.critical(
                    self, "Java не найдена",
                    "Не удалось найти Java 17+ на этом компьютере.\n\n"
                    "Установите JDK/JRE 17 или новее, укажите путь к "
                    "java.exe кнопкой «Выбрать Java...» или включите "
                    "«Скачивать Java автоматически»."
                )
                self.log("[Ошибка] Java не найдена. Установите JDK/JRE 17+.")
                return
            if java_major is None:
                self.log(f"[dotLauncher] Java: {java_path} (версия не определена)")
            else:
                self.log(f"[dotLauncher] Java: {java_path} (major={java_major})")
                if java_major < 17:
                    self.log(
                        f"[Внимание] Java {java_major} может быть недостаточна "
                        f"для современных версий Minecraft."
                    )

        memory = safe_int(self.config.get("memory_mb"), DEFAULT_MEMORY_MB)

        instance_dir = self._instance_abs_path(inst)

        self.play_button.setEnabled(False)
        self.play_button.setText("Загрузка...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.delete_button.setEnabled(False)

        self.launcher_thread = LauncherThread(
            instance_dir, inst["version"], username, uuid_val, token,
            java_path=java_path or "java", elyby=elyby, memory_mb=memory,
            use_managed_java=use_managed,
        )
        self.launcher_thread.log_signal.connect(self.log)
        self.launcher_thread.status_signal.connect(self.status_bar.showMessage)
        self.launcher_thread.progress_signal.connect(self.update_progress)
        self.launcher_thread.finished_signal.connect(self.on_launch_finished)
        self.launcher_thread.installing_signal.connect(self.on_installing_changed)
        self.launcher_thread.start()

    @staticmethod
    def _offline_uuid(username):
        md5 = hashlib.md5(f"OfflinePlayer:{username}".encode()).digest()
        md5 = bytearray(md5)
        md5[6] = (md5[6] & 0x0F) | 0x30
        md5[8] = (md5[8] & 0x3F) | 0x80
        return md5.hex()

    def on_installing_changed(self, installing):
        self.play_button.setText("Установка..." if installing else "Запуск...")

    def update_progress(self, current, total):
        if total > 0:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(current)
        else:
            self.progress_bar.setMaximum(0)

    def on_launch_finished(self, success, message):
        self.play_button.setEnabled(True)
        self.play_button.setText("ИГРАТЬ")
        self.progress_bar.setVisible(False)
        self.delete_button.setEnabled(True)
        self.status_bar.showMessage("Готов" if success else f"Ошибка: {message}")

    # ---------- КОНСОЛЬ ----------
    def log(self, text):
        cursor = self.console.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.console.setTextCursor(cursor)
        self.console.insertPlainText(str(text) + "\n")
        sb = self.console.verticalScrollBar()
        sb.setValue(sb.maximum())
        try:
            logging.info(text)
        except Exception:
            pass

    # ---------- ЗАКРЫТИЕ ----------
    def closeEvent(self, event):
        # 1) Отмена/ожидание импорта
        if self.import_thread and self.import_thread.isRunning():
            self.import_thread.cancel()
            if not self.import_thread.wait(5000):
                self.log("[Внимание] Поток импорта не завершился, принудительное завершение.")
                self.import_thread.terminate()
                self.import_thread.wait(2000)

        # 2) Установка/игра
        if self.launcher_thread and self.launcher_thread.isRunning():
            if self.launcher_thread.process is None:
                # Установка
                reply = QMessageBox.question(
                    self, "Установка в процессе",
                    "Идёт установка Minecraft/Fabric/Java.\n"
                    "Прервать установку и выйти?\n"
                    "Незавершённые файлы будут дозагружены при следующем запуске.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
            else:
                reply = QMessageBox.question(
                    self, "Закрытие",
                    "Игра запущена. Завершить её и выйти?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return

            self.launcher_thread.stop()
            if not self.launcher_thread.wait(5000):
                self.log("[Внимание] Поток лаунчера не завершился, принудительное завершение.")
                self.launcher_thread.terminate()
                self.launcher_thread.wait(2000)

        # 3) Логин/рефреш Ely.by
        for t in (self.login_thread, self.refresh_thread):
            if t and t.isRunning():
                try:
                    t.finished_signal.disconnect()
                except Exception:
                    pass
                if not t.wait(3000):
                    t.terminate()
                    t.wait(1000)

        event.accept()


# ============================================================
#  ТОЧКА ВХОДА
# ============================================================
def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setStyle("Fusion")

    # Логи в файл
    try:
        log_path = os.path.join(get_config_dir(), "dotlauncher.log")
        logging.basicConfig(
            filename=log_path,
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            encoding="utf-8",
        )
    except Exception:
        pass

    launcher = DotLauncher()
    launcher.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()