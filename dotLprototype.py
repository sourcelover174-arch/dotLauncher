#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dotLauncher — минималистичный лаунчер Minecraft для Fabric-сборок.
Один файл, PyQt6 + minecraft-launcher-lib.
"""

import sys
import os
import json
import zipfile
import subprocess
import shutil
import uuid
import hashlib
import base64
from pathlib import Path
from collections import Counter

import requests

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QPushButton, QLineEdit,
    QComboBox, QTextEdit, QFileDialog, QInputDialog, QMessageBox,
    QSplitter, QFrame, QProgressBar, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import QFont, QPalette, QColor, QDragEnterEvent, QDropEvent

import minecraft_launcher_lib


# ============================================================
#  КОНСТАНТЫ
# ============================================================
CONFIG_FILE = "dot_config.json"
INSTANCES_DB = "instances.json"


# ============================================================
#  ПОТОК ЗАПУСКА / УСТАНОВКИ
# ============================================================
class LauncherThread(QThread):
    log_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, instance_path, version, username, uuid_val, token,
                 java_path="java", elyby=False):
        super().__init__()
        self.instance_path = instance_path
        self.version = version
        self.username = username
        self.uuid_val = uuid_val
        self.token = token
        self.java_path = java_path
        self.elyby = elyby
        self._stop = False
        self.process = None

    def run(self):
        try:
            self.log_signal.emit(f"[dotLauncher] Начинаю установку Minecraft {self.version}...")
            minecraft_dir = os.path.join(self.instance_path, ".minecraft")
            os.makedirs(minecraft_dir, exist_ok=True)

            callback = {
                "setStatus": lambda text: self.status_signal.emit(text),
                "setProgress": lambda progress: self.progress_signal.emit(progress, 0),
                "setMax": lambda max_progress: self.progress_signal.emit(0, max_progress),
            }

            # --- Установка ванильного Minecraft ---
            self.log_signal.emit("[dotLauncher] Установка ванильного Minecraft...")
            minecraft_launcher_lib.install.install_minecraft_version(
                self.version, minecraft_dir, callback=callback
            )

            # --- Установка Fabric ---
            self.log_signal.emit("[dotLauncher] Установка Fabric загрузчика...")
            minecraft_launcher_lib.fabric.install_fabric(
                self.version, minecraft_dir, callback=callback
            )

            # --- Поиск установленной версии Fabric ---
            installed = minecraft_launcher_lib.utils.get_installed_versions(minecraft_dir)
            fabric_id = None
            for v in installed:
                if v["id"].startswith("fabric-loader") and self.version in v["id"]:
                    fabric_id = v["id"]
                    break
            if not fabric_id:
                for v in installed:
                    if v["id"].startswith("fabric-loader"):
                        fabric_id = v["id"]
                        break
            if not fabric_id:
                raise Exception("Не удалось найти установленную версию Fabric")

            self.log_signal.emit(f"[dotLauncher] Fabric версия: {fabric_id}")

            # --- JVM-аргументы (Ely.by skin support) ---
            jvm_args = []
            if self.elyby:
                injector_path = os.path.join(self.instance_path, "authlib-injector.jar")
                if not os.path.exists(injector_path):
                    self.log_signal.emit("[dotLauncher] Скачивание authlib-injector...")
                    url = ("https://github.com/yushijinhun/authlib-injector/"
                           "releases/latest/download/authlib-injector.jar")
                    try:
                        r = requests.get(url, stream=True, timeout=30)
                        r.raise_for_status()
                        with open(injector_path, "wb") as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                f.write(chunk)
                        self.log_signal.emit("[dotLauncher] authlib-injector загружен.")
                    except Exception as e:
                        self.log_signal.emit(
                            f"[Ошибка] Не удалось скачать authlib-injector: {e}"
                        )
                else:
                    self.log_signal.emit("[dotLauncher] authlib-injector уже существует.")
                jvm_args.append(f"-javaagent:{injector_path}=ely.by")

            # --- Опции запуска ---
            options = {
                "username": self.username,
                "uuid": self.uuid_val,
                "token": self.token,
                "executablePath": self.java_path,
                "defaultExecutablePath": "java",
                "jvmArguments": jvm_args,
                "launcherName": "dotLauncher",
                "launcherVersion": "1.0",
                "gameDirectory": minecraft_dir,
                "demo": False,
                "customResolution": False,
                "resolutionWidth": "854",
                "resolutionHeight": "480",
                "server": "",
                "port": "",
                "nativesDirectory": os.path.join(
                    minecraft_dir, "versions", fabric_id, "natives"
                ),
                "enableLoggingConfig": False,
                "disableMultiplayer": False,
                "disableChat": False,
                "quickPlayPath": None,
                "quickPlaySingleplayer": None,
                "quickPlayMultiplayer": None,
                "quickPlayRealms": None,
            }

            command = minecraft_launcher_lib.command.get_minecraft_command(
                fabric_id, minecraft_dir, options
            )

            self.log_signal.emit("[dotLauncher] Запуск Minecraft...")
            self.log_signal.emit(f"[dotLauncher] Команда: {' '.join(command)}")

            # --- Запуск процесса ---
            self.process = subprocess.Popen(
                command,
                cwd=minecraft_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )

            # --- Чтение вывода в реальном времени ---
            for line in iter(self.process.stdout.readline, ""):
                if line:
                    self.log_signal.emit(line.rstrip())
                if self._stop:
                    break

            self.process.wait()
            self.log_signal.emit(
                f"[dotLauncher] Игра завершена с кодом {self.process.returncode}."
            )
            self.finished_signal.emit(True, "Игра завершена")

        except Exception as e:
            self.log_signal.emit(f"[Ошибка] {str(e)}")
            self.finished_signal.emit(False, str(e))

    def stop(self):
        self._stop = True
        if self.process:
            self.process.terminate()


# ============================================================
#  DROP ZONE
# ============================================================
class DropZone(QLabel):
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
        if files and self.parent():
            self.parent().handle_dropped_files(files)
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
        self.init_ui()
        self.load_config()

    # ---------- ИНТЕРФЕЙС ----------
    def init_ui(self):
        self.setWindowTitle("dotLauncher")
        self.setMinimumSize(1050, 720)

        # Тёмная тема
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
        left_layout.addWidget(self.login_status)

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

        self.title_label = QLabel("dotLauncher")
        self.title_label.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_layout.addWidget(self.title_label)

        # Drop-зона
        self.drop_zone = DropZone(self)
        self.drop_zone.setText(
            "Перетащи сюда .jar файлы модов или папку с модами,\n"
            "чтобы создать сборку dotLauncher"
        )
        center_layout.addWidget(self.drop_zone, 1)

        # Информация о сборке (скрыта изначально)
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
        self.console.setFixedHeight(210)
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
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG_FILE)
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    self.config = json.load(f)
                self.log("[dotLauncher] Конфигурация загружена.")
                self.init_workspace()
                return
            except Exception as e:
                self.log(f"[Ошибка] Не удалось загрузить конфигурацию: {e}")

        # Первый запуск
        QMessageBox.information(
            self,
            "Добро пожаловать в dotLauncher!",
            "Пожалуйста, выберите папку на компьютере,\n"
            "где лаунчер создаст свои рабочие файлы\n"
            "и будет хранить сборки."
        )
        folder = QFileDialog.getExistingDirectory(
            self, "Выберите папку для dotLauncher"
        )
        if not folder:
            QMessageBox.critical(
                self,
                "Ошибка",
                "Папка не выбрана. Лаунчер не может работать без рабочей директории."
            )
            sys.exit(1)

        self.config["workspace"] = folder
        self.config["instances_dir"] = os.path.join(folder, "instances")
        self.config["username"] = ""
        self.config["client_token"] = str(uuid.uuid4())
        self.save_config()
        self.init_workspace()

    def init_workspace(self):
        workspace = self.config["workspace"]
        instances_dir = os.path.join(workspace, "instances")
        os.makedirs(instances_dir, exist_ok=True)
        self.config["instances_dir"] = instances_dir

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

        self.log("[dotLauncher] Готов к работе.")

    def save_config(self):
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG_FILE)
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log(f"[Ошибка] Не удалось сохранить конфигурацию: {e}")

    def save_instances(self):
        db_path = os.path.join(self.config["workspace"], INSTANCES_DB)
        try:
            with open(db_path, "w", encoding="utf-8") as f:
                json.dump(self.instances, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log(f"[Ошибка] Не удалось сохранить базу сборок: {e}")

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

        self.login_button.setEnabled(False)
        self.login_status.setText("Авторизация...")

        try:
            url = "https://authserver.ely.by/auth/authenticate"
            client_token = self.config.get("client_token", str(uuid.uuid4()))
            self.config["client_token"] = client_token

            payload = {
                "username": email,
                "password": password,
                "clientToken": client_token,
                "requestUser": True,
            }
            r = requests.post(url, json=payload, timeout=10)
            data = r.json()

            if r.status_code == 200:
                access_token = data.get("accessToken")
                selected = data.get("selectedProfile", {})
                uuid_val = selected.get("id")
                username = selected.get("name")

                self.config["elyby_access_token"] = access_token
                self.config["elyby_uuid"] = uuid_val
                self.config["elyby_username"] = username
                self.save_config()

                self.username_input.setText(username)
                self.login_status.setText(f"Вошли как {username}")
                self.log(f"[dotLauncher] Авторизация Ely.by успешна: {username}")
            else:
                error = data.get("errorMessage", "Неизвестная ошибка")
                self.login_status.setText(f"Ошибка: {error}")
                self.log(f"[Ошибка] Ely.by: {error}")
        except Exception as e:
            self.login_status.setText(f"Ошибка: {str(e)}")
            self.log(f"[Ошибка] Ely.by: {e}")
        finally:
            self.login_button.setEnabled(True)

    # ---------- РАБОТА С DRAG-AND-DROP ----------
    def handle_dropped_files(self, files):
        jar_files = []
        for f in files:
            if os.path.isfile(f) and f.lower().endswith(".jar"):
                jar_files.append(f)
            elif os.path.isdir(f):
                for root, _dirs, filenames in os.walk(f):
                    for fn in filenames:
                        if fn.lower().endswith(".jar"):
                            jar_files.append(os.path.join(root, fn))

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

                    with zf.open("fabric.mod.json") as f:
                        mod_data = json.load(f)
                        depends = mod_data.get("depends", {})
                        mc_ver = depends.get("minecraft", None)

                        if not mc_ver:
                            self.log(
                                f"[dotLauncher] {os.path.basename(jar)} — нет зависимости minecraft, пропускаю."
                            )
                            continue

                        mc_ver = mc_ver.strip()
                        for op in (">=", "<=", ">", "<", "~", "^", "="):
                            if mc_ver.startswith(op):
                                mc_ver = mc_ver[len(op):]
                        mc_ver = mc_ver.strip()
                        if " " in mc_ver:
                            mc_ver = mc_ver.split()[0]

                        versions.append(mc_ver)
                        valid_jars.append(jar)
                        self.log(
                            f"[dotLauncher] {os.path.basename(jar)} → Minecraft {mc_ver}"
                        )
            except Exception as e:
                self.log(
                    f"[Ошибка] Не удалось прочитать мод {os.path.basename(jar)}: {e}, пропускаю."
                )

        if not versions:
            self.log("[Ошибка] Не удалось определить версию Minecraft ни для одного мода.")
            return

        version_counts = Counter(versions)
        common_version = version_counts.most_common(1)[0][0]
        self.log(
            f"[dotLauncher] Определена версия Minecraft: {common_version} "
            f"(на основе {len(versions)} модов)"
        )

        name, ok = QInputDialog.getText(
            self,
            "Создание сборки",
            f"Обнаружена сборка Fabric {common_version}.\n"
            f"Введите название для этой сборки:",
        )
        if not ok or not name.strip():
            self.log("[dotLauncher] Создание сборки отменено.")
            return

        name = name.strip()
        name = "".join(c for c in name if c.isalnum() or c in " _-").strip()
        if not name:
            name = f"Fabric_{common_version}"

        instance_id = str(uuid.uuid4())[:8]
        instance_dir = os.path.join(self.config["instances_dir"], instance_id)
        os.makedirs(instance_dir, exist_ok=True)

        mods_dir = os.path.join(instance_dir, "mods")
        os.makedirs(mods_dir, exist_ok=True)

        for jar in valid_jars:
            try:
                shutil.copy2(jar, mods_dir)
                self.log(f"[dotLauncher] Скопирован {os.path.basename(jar)}")
            except Exception as e:
                self.log(
                    f"[Ошибка] Не удалось скопировать {os.path.basename(jar)}: {e}"
                )

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
        inst = self.instances[self.current_instance]
        reply = QMessageBox.question(
            self,
            "Удаление сборки",
            f"Удалить сборку «{inst['name']}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                shutil.rmtree(inst["path"], ignore_errors=True)
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

        self.play_button.setEnabled(False)
        self.play_button.setText("Загрузка...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        self.launcher_thread = LauncherThread(
            inst["path"],
            inst["version"],
            username,
            uuid_val,
            token,
            elyby=elyby,
        )
        self.launcher_thread.log_signal.connect(self.log)
        self.launcher_thread.status_signal.connect(self.status_bar.showMessage)
        self.launcher_thread.progress_signal.connect(self.update_progress)
        self.launcher_thread.finished_signal.connect(self.on_launch_finished)
        self.launcher_thread.start()

    @staticmethod
    def _offline_uuid(username):
        md5 = hashlib.md5(f"OfflinePlayer:{username}".encode()).digest()
        md5 = bytearray(md5)
        md5[6] = (md5[6] & 0x0F) | 0x30
        md5[8] = (md5[8] & 0x3F) | 0x80
        hex_str = md5.hex()
        return f"{hex_str[:8]}-{hex_str[8:12]}-{hex_str[12:16]}-{hex_str[16:20]}-{hex_str[20:]}"

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
        self.status_bar.showMessage("Готов" if success else f"Ошибка: {message}")

    # ---------- КОНСОЛЬ ----------
    def log(self, text):
        self.console.append(text)
        self.console.verticalScrollBar().setValue(
            self.console.verticalScrollBar().maximum()
        )

    # ---------- ЗАКРЫТИЕ ----------
    def closeEvent(self, event):
        if self.launcher_thread and self.launcher_thread.isRunning():
            self.launcher_thread.stop()
            self.launcher_thread.wait(3000)
        event.accept()


# ============================================================
#  ТОЧКА ВХОДА
# ============================================================
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    launcher = DotLauncher()
    launcher.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()