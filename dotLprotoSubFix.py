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
from collections import Counter

import requests

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QPushButton, QLineEdit,
    QComboBox, QTextEdit, QFileDialog, QInputDialog, QMessageBox,
    QSplitter, QFrame, QProgressBar, QSpinBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QStandardPaths
from PyQt6.QtGui import QFont, QPalette, QColor, QDragEnterEvent, QDropEvent

import minecraft_launcher_lib


# ============================================================
#  КОНСТАНТЫ
# ============================================================
APP_NAME = "dotLauncher"
LAUNCHER_VERSION = "1.1"
INSTANCES_DB = "instances.json"

AUTHLIB_INJECTOR_VERSION = "1.2.5"
AUTHLIB_INJECTOR_URL = (
    f"https://github.com/yushijinhun/authlib-injector/releases/download/"
    f"v{AUTHLIB_INJECTOR_VERSION}/authlib-injector-{AUTHLIB_INJECTOR_VERSION}.jar"
)

DEFAULT_MEMORY_MB = 2048
MIN_MEMORY_MB = 1024
MAX_MEMORY_MB = 32768

# Папки, которые копируем из перетащенного модпака (если есть)
COPYABLE_DIRS = (
    "mods", "config", "resourcepacks", "shaderpacks",
    "defaultconfigs", "kubejs", "scripts",
)

# Папки/файлы, которые НЕ копируем
SKIP_DIRS = {".minecraft", "saves", "logs", "crash-reports", "versions",
             "libraries", "assets", "screenshots"}


# ============================================================
#  ПУТИ И УТИЛИТЫ
# ============================================================
def get_config_dir():
    """Возвращает папку для конфига (пользовательскую, не рядом со скриптом)."""
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppConfigLocation
    )
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".config")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def is_subpath(child, parent):
    """True, если child лежит внутри parent (защита от path traversal)."""
    try:
        child = os.path.realpath(child)
        parent = os.path.realpath(parent)
        return os.path.commonpath([child, parent]) == parent
    except (ValueError, OSError):
        return False


def sanitize_instance_name(name):
    """Оставляет только безопасные символы в имени сборки."""
    name = "".join(c for c in name if c.isalnum() or c in " _-").strip()
    return name or "Unnamed"


def is_valid_jar(path):
    """Проверяет, что файл — валидный JAR (ZIP)."""
    try:
        with zipfile.ZipFile(path, "r"):
            return True
    except Exception:
        return False


# ============================================================
#  ПОИСК JAVA
# ============================================================
_JAVA_VERSION_RE = re.compile(r'version\s+"(\d+)(?:\.(\d+))?')


def get_java_major(java_path):
    """Возвращает major-версию Java или None."""
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


def find_java(min_major=17):
    """
    Ищет Java. Возвращает (path, major) или (fallback_path, None).
    Предпочитает Java с major >= min_major.
    """
    candidates = []

    java = shutil.which("java")
    if java:
        candidates.append(java)

    if sys.platform.startswith("win"):
        bases = [
            r"C:\Program Files\Java",
            r"C:\Program Files\Eclipse Adoptium",
            r"C:\Program Files\Microsoft",
            r"C:\Program Files\Amazon Corretto",
            r"C:\Program Files\Zulu",
            r"C:\Program Files (x86)\Java",
        ]
        for base in bases:
            if not os.path.isdir(base):
                continue
            for root, _dirs, files in os.walk(base):
                if "java.exe" in files:
                    candidates.append(os.path.join(root, "java.exe"))

    fallback = None
    for c in candidates:
        if not os.path.isfile(c):
            continue
        major = get_java_major(c)
        if major is None:
            continue
        if major >= min_major:
            return c, major
        if fallback is None:
            fallback = (c, major)

    if fallback:
        return fallback
    return ("java", None)


# ============================================================
#  ПАРСИНГ fabric.mod.json
# ============================================================
def extract_minecraft_versions(mod_data):
    """
    Возвращает список версий Minecraft, заявленных в depends.
    Обрабатывает строки, списки и диапазоны ('>=1.20.1 <1.21', '~1.20.1', '1.20.x').
    """
    depends = mod_data.get("depends", {})
    mc = depends.get("minecraft")
    if mc is None:
        return []

    def parse_one(s):
        s = str(s).strip()
        if not s:
            return ""
        # Убираем операторы в начале
        s = re.sub(r'^[<>=~^]+', '', s).strip()
        # Если через пробел (диапазон) — берём первую часть
        if " " in s:
            s = s.split()[0]
        # Убираем .x / .* / -x в конце
        s = re.sub(r'[.\-][xX*]+$', '', s)
        return s.strip()

    if isinstance(mc, list):
        return [v for v in (parse_one(x) for x in mc) if v]
    v = parse_one(mc)
    return [v] if v else []


# ============================================================
#  ПОТОК ЗАПУСКА / УСТАНОВКИ
# ============================================================
class LauncherThread(QThread):
    log_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal(bool, str)
    installing_signal = pyqtSignal(bool)  # True — установка, False — игра

    def __init__(self, instance_path, version, username, uuid_val, token,
                 java_path="java", elyby=False, memory_mb=DEFAULT_MEMORY_MB):
        super().__init__()
        self.instance_path = instance_path
        self.version = version
        self.username = username
        self.uuid_val = uuid_val
        self.token = token
        self.java_path = java_path
        self.elyby = elyby
        self.memory_mb = memory_mb
        self._stop = False
        self.process = None
        self._progress_max = 0

    # --- Колбэки для minecraft-launcher-lib ---
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

    def run(self):
        try:
            self.installing_signal.emit(True)
            self.log_signal.emit(
                f"[dotLauncher] Начинаю установку Minecraft {self.version}..."
            )
            minecraft_dir = os.path.join(self.instance_path, ".minecraft")
            os.makedirs(minecraft_dir, exist_ok=True)

            callback = self._make_callback()

            self.log_signal.emit("[dotLauncher] Установка ванильного Minecraft...")
            minecraft_launcher_lib.install.install_minecraft_version(
                self.version, minecraft_dir, callback=callback
            )

            self.log_signal.emit("[dotLauncher] Установка Fabric загрузчика...")
            minecraft_launcher_lib.fabric.install_fabric(
                self.version, minecraft_dir, callback=callback
            )

            if self._stop:
                self.finished_signal.emit(False, "Отменено пользователем")
                return

            # --- Поиск установленной версии Fabric (точное совпадение!) ---
            installed = minecraft_launcher_lib.utils.get_installed_versions(minecraft_dir)
            fabric_id = None
            # Сначала ищем точное совпадение с суффиксом -<version>
            exact_suffix = f"-{self.version}"
            for v in installed:
                vid = v["id"]
                if vid.startswith("fabric-loader") and vid.endswith(exact_suffix):
                    fabric_id = vid
                    break
            # Fallback — любой fabric-loader
            if not fabric_id:
                for v in installed:
                    if v["id"].startswith("fabric-loader"):
                        fabric_id = v["id"]
                        break
            if not fabric_id:
                raise Exception("Не удалось найти установленную версию Fabric")

            self.log_signal.emit(f"[dotLauncher] Fabric версия: {fabric_id}")

            # --- JVM-аргументы ---
            jvm_args = [
                f"-Xmx{self.memory_mb}M",
                f"-Xms{min(self.memory_mb, 1024)}M",
            ]

            if self.elyby:
                injector_path = os.path.join(self.instance_path, "authlib-injector.jar")
                if not (os.path.exists(injector_path) and is_valid_jar(injector_path)):
                    self.log_signal.emit("[dotLauncher] Скачивание authlib-injector...")
                    try:
                        r = requests.get(AUTHLIB_INJECTOR_URL, stream=True, timeout=60)
                        r.raise_for_status()
                        tmp_path = injector_path + ".tmp"
                        with open(tmp_path, "wb") as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                f.write(chunk)
                        # Проверяем, что это валидный JAR, а не HTML-заглушка
                        if not is_valid_jar(tmp_path):
                            os.remove(tmp_path)
                            raise Exception("Скачанный файл не является валидным JAR")
                        os.replace(tmp_path, injector_path)
                        self.log_signal.emit(
                            f"[dotLauncher] authlib-injector "
                            f"{AUTHLIB_INJECTOR_VERSION} загружен."
                        )
                    except Exception as e:
                        self.log_signal.emit(
                            f"[Ошибка] Не удалось скачать authlib-injector: {e}"
                        )
                else:
                    self.log_signal.emit("[dotLauncher] authlib-injector уже существует.")

                if os.path.exists(injector_path):
                    jvm_args.append(f"-javaagent:{injector_path}=ely.by")

            # --- Опции запуска ---
            options = {
                "username": self.username,
                "uuid": self.uuid_val,
                "token": self.token,
                "executablePath": self.java_path,
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
            self.log_signal.emit(f"[dotLauncher] JVM: {self.java_path} ({self.memory_mb} MB)")

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
            self.log_signal.emit(
                f"[dotLauncher] Игра завершена с кодом {self.process.returncode}."
            )
            self.finished_signal.emit(True, "Игра завершена")

        except Exception as e:
            self.log_signal.emit(f"[Ошибка] {type(e).__name__}: {e}")
            self.finished_signal.emit(False, str(e))

    def stop(self):
        """Просит поток остановиться и убивает игровой процесс, если он есть."""
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
    finished_signal = pyqtSignal(bool, dict, str)  # success, data, error

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

        # Папка конфига (пользовательская, не рядом со скриптом)
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
        self.username_input.textChanged.connect(self.save_account)
        left_layout.addWidget(self.username_input)

        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("Email (Ely.by)")
        self.email_input.setVisible(False)
        self.email_input.textChanged.connect(self.save_account)
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

        # Настройки памяти
        memory_label = QLabel("Память (MB)")
        memory_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        left_layout.addWidget(memory_label)

        self.memory_spin = QSpinBox()
        self.memory_spin.setRange(MIN_MEMORY_MB, MAX_MEMORY_MB)
        self.memory_spin.setSingleStep(256)
        self.memory_spin.setValue(DEFAULT_MEMORY_MB)
        self.memory_spin.valueChanged.connect(self.save_memory)
        left_layout.addWidget(self.memory_spin)

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
            "Перетащи сюда .jar файлы модов или папку с модами,\n"
            "чтобы создать сборку dotLauncher"
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
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #555;
                color: #888;
            }
        """)
        self.play_button.clicked.connect(self.play_game)
        info_layout.addWidget(self.play_button, alignment=Qt.AlignmentFlag.AlignCenter)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedWidth(320)
        info_layout.addWidget(self.progress_bar, alignment=Qt.AlignmentFlag.AlignCenter)

        center_layout.addWidget(self.instance_info, 1)

        # ---------- КОНСОЛЬ ----------
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

    # ---------- ЗАГРУЗКА КОНФИГА ----------
    def load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self.config = json.load(f)
                self.log("[dotLauncher] Конфигурация загружена.")
                self.init_workspace()
                return
            except Exception as e:
                self.log(f"[Ошибка] Не удалось загрузить конфигурацию: {e}")

        # Первый запуск
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
        self.config["instances_dir"] = os.path.join(folder, "instances")
        self.config["username"] = ""
        self.config["client_token"] = str(uuid.uuid4())
        self.config["memory_mb"] = DEFAULT_MEMORY_MB
        self.save_config()
        self.init_workspace()

    def init_workspace(self):
        workspace = self.config["workspace"]
        instances_dir = os.path.join(workspace, "instances")
        os.makedirs(instances_dir, exist_ok=True)
        self.config["instances_dir"] = instances_dir

        # Восстанавливаем память
        mem = self.config.get("memory_mb", DEFAULT_MEMORY_MB)
        self.memory_spin.blockSignals(True)
        self.memory_spin.setValue(int(mem))
        self.memory_spin.blockSignals(False)

        db_path = os.path.join(workspace, INSTANCES_DB)
        if os.path.exists(db_path):
            try:
                with open(db_path, "r", encoding="utf-8") as f:
                    self.instances = json.load(f)
            except Exception as e:
                self.log(f"[Ошибка] Не удалось загрузить базу сборок: {e}")
                self.instances = {}
        else:
            self.instances = {}

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
        elif self.config.get("username"):
            self.username_input.setText(self.config["username"])

        self.log(f"[dotLauncher] Конфиг: {self.config_dir}")
        self.log(f"[dotLauncher] Рабочая папка: {workspace}")
        self.log("[dotLauncher] Готов к работе.")

    def save_config(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
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

    # ---------- АККАУНТ ----------
    def on_account_type_changed(self, index):
        is_elyby = (index == 1)
        self.username_input.setVisible(not is_elyby)
        self.email_input.setVisible(is_elyby)
        self.password_input.setVisible(is_elyby)
        self.login_button.setVisible(is_elyby)

    def save_account(self):
        if self.account_type.currentIndex() == 0:
            self.config["username"] = self.username_input.text()
        else:
            self.config["email"] = self.email_input.text()
        self.save_config()

    def elyby_login(self):
        email = self.email_input.text().strip()
        password = self.password_input.text().strip()
        if not email or not password:
            self.login_status.setText("Введите email и пароль")
            return

        client_token = self.config.get("client_token")
        if not client_token:
            client_token = str(uuid.uuid4())
            self.config["client_token"] = client_token
            self.save_config()

        self.login_button.setEnabled(False)
        self.login_status.setText("Авторизация...")

        self.login_thread = ElybyLoginThread(email, password, client_token)
        self.login_thread.finished_signal.connect(self.on_elyby_login_finished)
        self.login_thread.start()

    def on_elyby_login_finished(self, success, data, error):
        self.login_button.setEnabled(True)
        if not success:
            self.login_status.setText(f"Ошибка: {error}")
            self.log(f"[Ошибка] Ely.by: {error}")
            return

        access_token = data.get("accessToken")
        selected = data.get("selectedProfile", {})
        uuid_val = selected.get("id")
        username = selected.get("name")

        if not access_token or not uuid_val or not username:
            self.login_status.setText("Некорректный ответ Ely.by")
            return

        self.config["elyby_access_token"] = access_token
        self.config["elyby_uuid"] = uuid_val
        self.config["elyby_username"] = username
        self.save_config()

        self.username_input.setText(username)
        self.login_status.setText(f"Вошли как {username}")
        self.log(f"[dotLauncher] Авторизация Ely.by успешна: {username}")

    # ---------- РАБОТА С DRAG-AND-DROP ----------
    def handle_dropped_files(self, files):
        if self.launcher_thread and self.launcher_thread.isRunning():
            self.log("[Ошибка] Дождитесь завершения текущего запуска.")
            return

        jar_files = []
        extra_dirs = {}  # имя_папки -> путь источника

        for f in files:
            if os.path.isfile(f) and f.lower().endswith(".jar"):
                jar_files.append(f)
            elif os.path.isdir(f):
                # Ищем моды
                for root, _dirs, filenames in os.walk(f):
                    # Пропускаем служебные
                    parts = set(os.path.relpath(root, f).split(os.sep))
                    if parts & SKIP_DIRS:
                        continue
                    for fn in filenames:
                        if fn.lower().endswith(".jar"):
                            jar_files.append(os.path.join(root, fn))
                # Запоминаем, какие папки можно скопировать
                for name in COPYABLE_DIRS:
                    src = os.path.join(f, name)
                    if os.path.isdir(src):
                        extra_dirs[name] = src

        if not jar_files:
            self.log("[Ошибка] Не найдено .jar файлов для обработки.")
            return

        self.log(f"[dotLauncher] Обработка {len(jar_files)} модов...")

        versions = []
        valid_jars = []

        for jar in jar_files:
            try:
                with zipfile.ZipFile(jar, "r") as zf:
                    if "fabric.mod.json" not in zf.namelist():
                        self.log(
                            f"[dotLauncher] {os.path.basename(jar)} — не Fabric-мод, пропускаю."
                        )
                        continue
                    with zf.open("fabric.mod.json") as fm:
                        mod_data = json.load(fm)
                    mc_vers = extract_minecraft_versions(mod_data)
                    if not mc_vers:
                        self.log(
                            f"[dotLauncher] {os.path.basename(jar)} — "
                            f"нет зависимости minecraft, пропускаю."
                        )
                        continue
                    for mv in mc_vers:
                        versions.append(mv)
                    valid_jars.append(jar)
                    self.log(
                        f"[dotLauncher] {os.path.basename(jar)} → "
                        f"Minecraft {', '.join(mc_vers)}"
                    )
            except Exception as e:
                self.log(
                    f"[Ошибка] Не удалось прочитать мод {os.path.basename(jar)}: {e}, пропускаю."
                )

        if not versions:
            self.log("[Ошибка] Не удалось определить версию Minecraft ни для одного мода.")
            return

        unique_versions = sorted(set(versions))
        if len(unique_versions) == 1:
            common_version = unique_versions[0]
        else:
            self.log(
                f"[dotLauncher] Обнаружены разные версии: {', '.join(unique_versions)}"
            )
            common_version, ok = QInputDialog.getItem(
                self, "Выбор версии Minecraft",
                "Моды требуют разные версии Minecraft.\nВыберите целевую версию:",
                unique_versions, 0, False,
            )
            if not ok or not common_version:
                self.log("[dotLauncher] Создание сборки отменено.")
                return

        counts = Counter(versions)
        self.log(
            f"[dotLauncher] Целевая версия Minecraft: {common_version} "
            f"(по {counts[common_version]} из {len(versions)} модов)"
        )

        name, ok = QInputDialog.getText(
            self, "Создание сборки",
            f"Обнаружена сборка Fabric {common_version}.\n"
            f"Введите название для этой сборки:",
        )
        if not ok or not name.strip():
            self.log("[dotLauncher] Создание сборки отменено.")
            return

        name = sanitize_instance_name(name)
        instance_id = str(uuid.uuid4())[:8]
        instance_dir = os.path.join(self.config["instances_dir"], instance_id)
        minecraft_dir = os.path.join(instance_dir, ".minecraft")
        os.makedirs(minecraft_dir, exist_ok=True)

        # Копируем моды
        mods_dir = os.path.join(minecraft_dir, "mods")
        os.makedirs(mods_dir, exist_ok=True)
        for jar in valid_jars:
            try:
                shutil.copy2(jar, mods_dir)
                self.log(f"[dotLauncher] Скопирован {os.path.basename(jar)}")
            except Exception as e:
                self.log(f"[Ошибка] Не удалось скопировать {os.path.basename(jar)}: {e}")

        # Копируем дополнительные папки модпака
        for name_dir, src in extra_dirs.items():
            dst = os.path.join(minecraft_dir, name_dir)
            try:
                if os.path.isdir(dst):
                    shutil.rmtree(dst, ignore_errors=True)
                shutil.copytree(src, dst)
                self.log(f"[dotLauncher] Скопирована папка {name_dir}")
            except Exception as e:
                self.log(f"[Ошибка] Не удалось скопировать {name_dir}: {e}")

        self.instances[instance_id] = {
            "name": name,
            "version": common_version,
            "loader": "fabric",
            "path": instance_dir,
        }
        self.save_instances()
        self.refresh_instance_list()
        self.log(f"[dotLauncher] Сборка «{name}» создана!")

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
            QMessageBox.warning(self, "Занято",
                                "Дождитесь завершения запуска.")
            return

        inst = self.instances[self.current_instance]
        reply = QMessageBox.question(
            self, "Удаление сборки",
            f"Удалить сборку «{inst['name']}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Защита от path traversal: путь должен лежать внутри instances_dir
        path = inst.get("path", "")
        instances_dir = self.config["instances_dir"]
        if not path or not is_subpath(path, instances_dir):
            self.log(f"[Ошибка] Небезопасный путь сборки: {path!r}, не удаляю.")
        else:
            try:
                shutil.rmtree(path, ignore_errors=False)
            except Exception as e:
                self.log(f"[Ошибка] Не удалось удалить папку: {e}")

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

        java_path, java_major = find_java()
        if java_major is None:
            self.log(f"[dotLauncher] Java: {java_path} (версия не определена)")
        else:
            self.log(f"[dotLauncher] Java: {java_path} (major={java_major})")
            if java_major < 17:
                self.log(
                    f"[Внимание] Java {java_major} может быть недостаточна "
                    f"для современных версий Minecraft."
                )

        memory = int(self.config.get("memory_mb", DEFAULT_MEMORY_MB))

        self.play_button.setEnabled(False)
        self.play_button.setText("Загрузка...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.delete_button.setEnabled(False)

        self.launcher_thread = LauncherThread(
            inst["path"], inst["version"], username, uuid_val, token,
            java_path=java_path, elyby=elyby, memory_mb=memory,
        )
        self.launcher_thread.log_signal.connect(self.log)
        self.launcher_thread.status_signal.connect(self.status_bar.showMessage)
        self.launcher_thread.progress_signal.connect(self.update_progress)
        self.launcher_thread.finished_signal.connect(self.on_launch_finished)
        self.launcher_thread.installing_signal.connect(self.on_installing_changed)
        self.launcher_thread.start()

    @staticmethod
    def _offline_uuid(username):
        """Offline UUID без дефисов (32 hex)."""
        md5 = hashlib.md5(f"OfflinePlayer:{username}".encode()).digest()
        md5 = bytearray(md5)
        md5[6] = (md5[6] & 0x0F) | 0x30
        md5[8] = (md5[8] & 0x3F) | 0x80
        return md5.hex()

    def on_installing_changed(self, installing):
        if installing:
            self.play_button.setText("Установка...")
        else:
            self.play_button.setText("Запуск...")

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
        # insertPlainText не парсит HTML — безопаснее, чем append()
        cursor = self.console.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.console.setTextCursor(cursor)
        self.console.insertPlainText(str(text) + "\n")
        sb = self.console.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ---------- ЗАКРЫТИЕ ----------
    def closeEvent(self, event):
        if self.launcher_thread and self.launcher_thread.isRunning():
            # Во время установки отмена может быть небезопасна — ждём
            if self.launcher_thread.process is None:
                QMessageBox.warning(
                    self, "Установка в процессе",
                    "Дождитесь завершения установки Minecraft.\n"
                    "Закрытие отменено."
                )
                event.ignore()
                return

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
                self.log("[Внимание] Поток не завершился, принудительное завершение.")
                self.launcher_thread.terminate()
                self.launcher_thread.wait(2000)

        if self.login_thread and self.login_thread.isRunning():
            self.login_thread.wait(2000)

        event.accept()


# ============================================================
#  ТОЧКА ВХОДА
# ============================================================
def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setStyle("Fusion")
    launcher = DotLauncher()
    launcher.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()