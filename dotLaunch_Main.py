#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dotLauncher — минималистичный лаунчер Minecraft для Fabric/Forge/NeoForge сборок.
Один файл, PyQt6 + minecraft-launcher-lib. Поддержка Modrinth.
Стилизация: Windows 98.
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
import socket
import base64

_orig_getaddrinfo = socket.getaddrinfo
def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = _ipv4_getaddrinfo

from collections import Counter

import requests

try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # pip install tomli
    except ImportError:
        tomllib = None

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QPushButton, QLineEdit,
    QComboBox, QTextEdit, QFileDialog, QInputDialog, QMessageBox,
    QSplitter, QFrame, QProgressBar, QSpinBox, QCheckBox,
    QDialog, QStackedWidget, QScrollArea, QMenu,
)
from PyQt6.QtCore import (
    Qt, QThread, pyqtSignal, QStandardPaths,
    QPoint, QBuffer, QIODevice, QTimer,
)
from PyQt6.QtGui import (
    QFont, QPalette, QColor, QDragEnterEvent, QDropEvent,
    QPixmap, QPainter, QPolygon, QPen, QIcon,
)

import minecraft_launcher_lib
import minecraft_launcher_lib.runtime


# ============================================================
#  КОНСТАНТЫ
# ============================================================
APP_NAME = "dotLauncher"
LAUNCHER_VERSION = "0.5"
INSTANCES_DB = "instances.json"

AUTHLIB_INJECTOR_VERSION = "1.2.5"
AUTHLIB_INJECTOR_URL = (
    f"https://github.com/yushijinhun/authlib-injector/releases/download/"
    f"v{AUTHLIB_INJECTOR_VERSION}/authlib-injector-{AUTHLIB_INJECTOR_VERSION}.jar"
)
AUTHLIB_INJECTOR_SHA256 = None
AUTHLIB_INJECTOR_MIN_SIZE = 100_000

DEFAULT_MEMORY_MB = 2048
MIN_MEMORY_MB = 1024
MAX_MEMORY_MB = 32768

MOD_LOADERS = {
    "fabric": "Fabric",
    "forge": "Forge",
    "neoforge": "NeoForge",
}

LOADER_TO_MODRINTH = {
    "fabric": "fabric",
    "forge": "forge",
    "neoforge": "neoforge",
}

MODRINTH_API = "https://api.modrinth.com/v2"
MODRINTH_USER_AGENT = f"{APP_NAME}/{LAUNCHER_VERSION} (dotLauncher)"

COPYABLE_DIRS = (
    "config", "resourcepacks", "shaderpacks",
    "defaultconfigs", "kubejs", "scripts",
)

SKIP_DIRS = {
    "saves", "logs", "crash-reports",
    "versions", "libraries", "assets", "screenshots",
    "disabledMods",
}

APP_ICON_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXA"
    "vmHAAALiUlEQVR4AdRZa4xV1RX+1jlz77yY9wMURn"
    "AUEVEoIwIzaDvDvAFtrY0toqURfCDoH2JtmyYmklp"
    "Di8RXxPqYgfpIbSpBEkxji2JF0yY1bU1rq1YiUMbA"
    "MMPMMMx9nHtOv7XPOZc7PAaEMYQ9Z+2119qPtb611"
    "97n3jvWli1bvM2bz09S3y3XBW688cPzktR3C+ewbN"
    "tWg/fem29I2+rK9deXY+fOBqPTvtWrq1SNPXuWor/"
    "/PkNdXcuMTqtzCqCgoAC1tbWGtK0OKc2ePdvotE9l"
    "pby8POgYpfz8fFUZOqcAjAdnWZ1TAH19fdixY4chb"
    "YdYdu7caXTaF+r6+/vR09NjKHPsOQWwaNHfUF//ri"
    "Ftq7Nbt3YbOdSvW7dH1bj44pdQVva0oaqqjUanlWU"
    "Rgh6g85HUd0tE0N7ePurU2taKefPnkOZC21+FDREB"
    "449RLwPxXvTHD8Izfy76Ez0YSPTC87xRtzWqAGLOI"
    "Hpj++F4SeO657mGg3XKc9CX6MbhRN+oghgVAI6bxK"
    "H4AcRSRyAihiyxyS1QIlkm+h53IOnGDcghgh0NJNb"
    "ZLOIxwgNMl8Fkv3FSnQ3X86DRV/IYfxci7M2gOMEq"
    "6EQqFk45I37GAAYT/eiL9yDlpYxhBeMSkMcoGwUrb"
    "XtpHQHwyElAYBG2dSf6eF50F3EG5UsDiDlDJgUSTI"
    "VMeyLhUpmOihkiotzjTviH2OPuaIdHjc9dHE4eYkA"
    "Owg0CovrTodDqKcemXId53o0hZyAYS2dEKRDJRAR8"
    "2PIfISg9C77Eo8zd0B3jLKMSUwPCP7B4BKa70c8d8"
    "TiWqlM+pwTgMSX6mSoDyV4u5kFEyJHmdItx1Fx3ER"
    "aPxpVCWSCm6ZmaM7im3/T1YL9LnUcCi4Ls57WraUp"
    "xxGdEADHnCKN+gHnumFtEVwqNGB56pB0Bqd4jJCWX"
    "6eAxqh5l7eZbk64CylX22KdcHVYeLifcOZUdXscHB"
    "/Zr86Q0MoBEDENx3hICiLACAi50IrwmLQj/EBQRSh"
    "kUqA3zggiHXGBBi80r16LTogLJ4w46joPeg/1wnKM"
    "7y67jHn+F49S+onrCpZhYXm3i56SYJgyRZ5xg7Ex0"
    "lbvcIZeHzzO7JAQjdCwkZMgWHTX9BAgWz+yAx/XVS"
    "Q8iQi2QjLtY1PxNXDy+2sgjVSMC0Ci4rpeen+J3OD"
    "WVVtC02vTN+lqX0fNIKnnDHFQN6KQFIUCwiOESyGI"
    "cTwzRAk1ecOEF0OI4SWUnJeukPexQAOqgF/cgKSqC"
    "hyYAbjmCopHVNABdgRbhQTXOq8A2d83VHUsD80yHD"
    "xBIMU0SQw7clK8XGrBhmzGxIaawaZ24sk6s9rWplL"
    "6k6A1FOw7YXOvP7/0F99/3Q3Q82wmHBnWDXn3lt1h"
    "6y+0QEUO7P9+DG1q/bVJqzYMP49LxlyOZSOJ7Ny1B"
    "3dXX4WB3N1ckMDqajDl4bN0TaK5vwaO/WI9UyoEw6"
    "LEYjXGUQtq+fTvWrl1rvsxQNewZEYDHyIkIrJRAy7"
    "QrZ2Jh4/V0fiNW33s/KseMY+67+PH9P8WW117nEDU"
    "HrHtkPf60410M0Ym3/vA2DffigpKL8Pttb+Jf//wI"
    "V11Wg2QshVTCxXduvBkPPbgG//j7h1j787WoGjuR6"
    "xAcbWujdlYdGhsb8cADD/DLTBlcprHqQ7LCxol4Go"
    "Bn4Vs33Yyuri60LmjBpt90orik2ERYx/Qd6kNWVhb"
    "ijLJLw/v+t88sd+TwIMIv4Gp4/ZO/xIyZMzB0ZIhz"
    "gX9/9B/seOsdzKmdg84XO/Do4+vo7Hzuok73g9F9o"
    "BtLlizBqlWrVInPPvvM8LA6JQB1TJ3c8c47KOSvCD"
    "+45VbUzp0DJ+nAtm2knBRc5rZlW0ZWswMDh8362dk"
    "56O3RFyCw5Pu3YMqUqbjkkktMXyKewLKly017xcq7"
    "0dDYgLb5zVh6220Ex9Ohucnea+fNw+LFi7FgwQJKw"
    "CeffGJ4WI0IQKNmWxa84CaYPmMGWpqbUJ5XgrzcXL"
    "OGAoxGotCxzDaji2ZHDRfO3b//gGkvumEhaq6uwcD"
    "AgJHjiQQ+/fS/qKiowNy6OcjJyUZFeQVaW1q4A0IQ"
    "PCAcecfyZVi4cCEmTZpECdi7d6/hYTUiAI18NBqFn"
    "WWb8V980cUo+1Oqqqp8py1BaVmp2RFahj3oIWJlmf"
    "EigiODg1QLZs2aBcsBLhzrX496qBX8wOEBlJSUmPF"
    "aHeo7BD1xsRhvDSr0NyIylJaWKsPHH39seFj53gTS"
    "7t27UV1djcyfLSLRCHsFxcVFJmK3L7sT3128BH/94"
    "ANGycPnuz5H7bVzOQaYUjUVE6svw/btbxtZKw2A8o"
    "K8Auj1WDNzporo2rUXtzK39Zq8asp0rFh+D8ZfNBG"
    "TmWbJZBIHuv2dy+cPWjqhvLxcGd5//33Dw2oYgA0b"
    "NmDXrl3YvHmz6Y9EIrhi6lS+roBn2VdYWIjXtryON"
    "/+4HdfOq4OIoONXnfjJgz9ihEp4PfaYFNFxuoDHmd"
    "O/Nh3Z2dlmrOrm8Pwo38/Dee+qlfwxoQ2aZq/9bjN"
    "SvLbvumM5kjxXNTNrUDVhAnfc333btqH+7Nu3T6en"
    "aRiA1atX45lnnsHkyZPNgFdfeRkr7rrTtL/x9euw4"
    "akn8dKmjXh5UydWrrgbL27sQNN19Zg0tgpPPf4Y+z"
    "oNbXjqCbzw6+dMiq155CFseO5pEAvEzuLvO9XoeP4"
    "5jBtXSQfH496V92BTZwc2drxAeh5NTY0G8F133oGH"
    "f7YGUZMBxgXw12isX7/eF4J6GICysjLM46kP866tt"
    "QXtLU2wRcxC7fyppKG+Hg0NDVjU3opWHuh5dXWwXM"
    "EC9jU1zkczaWF7G66eNRP6e+blUy5Ha30TLF7FatO"
    "2LNTVzsWVV1yhImZfcw1ampvNjjbzvm/k2hbP1dQp"
    "l6G9rS29czq4hQe8jTpth2SFjZBPmzbNbJWR6biI+"
    "E3WXBe5uTkmQhSRzehEmWbaVsphquRkR2kUGD9hvKq"
    "Y9x70sBqBHydAKmegRI6um8VLoqioyNh1+R7xe8w"
    "MZLY1jTQd/R6/Pg6Ar/ZrvYVSvI+V+5qjNe2kBYvO"
    "aNRChRrNiguEt47q2A1LPxtlTOKyw5yDZUOd1/FK+"
    "j4RbZyCRgSQOdfianzSKn4MAj+DAeodAO2zOUgdgx"
    "Z6YCcEtiOmD0FRDOkx1HEYYOm1K5RgxhodTq+MCEA"
    "XyoyKWf3Yde0okEUK9OqcAtO5gcowldV5IwSVjj2q"
    "82AxGCI+EB0iIhARbZ6UrJP2ZHQoiKOG/I6ILTSIo"
    "Ag01Vz1KNBkMnU+Uz62LW6KZyWVVqstpbRihMaIAH"
    "LzxjA1/XtYnfAg0KswXE9TxkrxjRlY89iRxRWJjS3"
    "/UZ3fAkR8QlA04roG9I4NdJnnzbJtFJdXBj0nZjR3"
    "4g7VimWhsKQcY4rLaJzWqRQeNiuSzbcwheCx3AR8R"
    "3yFOmpxOB+jEJH0fKNgJUpakeujQEPnRfjm501VVF"
    "p+3Dwdm0kjAggH2vyoXFBagdwxRaEKmlaaNmo4VCq"
    "IYDOMin4gE4hRHlPpOplr5I0pQFnlWGRlRY4ZeWLx"
    "tACEUyPRKAp5X2fn5IQqsxOZqa/OqCzpEUGDyIbph"
    "BcrdUEvonyHlFaOQ05efqg6Lf6lAIQr6suksKwSke"
    "zcUEUgnqG0gt5q9FUeHmWB2FkwW8NOiylZwjwvKCq"
    "h9OWfMwIQmsnldhcytexI5jXqwc2IbDhWue4ORFtK"
    "gsLiUpTwO4DFs6aaM6GzAmAMiiC/sBj5POxi+zeW6"
    "oWeiog2uTO8Z4z3RkQuvwyV8eNxJBr1FWdRnz2AwL"
    "gwp/OLyqC3lpwkohHuVFlFJfIy/lEdTD9jNmoAQg8"
    "s20YR0yq3QG8sfwcUUClTpbCklMN8HRuj8hgAev+O"
    "Nlm8BvP4/hhTVAp1XkGMtg2NgKWLbt26FV8VbXvjj"
    "a9sbfX9/wAAAP//31RJ1wAAAAZJREFUAwDRh2MbCE"
    "VJHwAAAABJRU5ErkJggg=="
)


def load_app_icon():
    """Возвращает QIcon, декодированный из APP_ICON_B64."""
    if not APP_ICON_B64 or APP_ICON_B64 == "ВСТАВЬ СЮДА BASE64":
        return QIcon()
    try:
        data = base64.b64decode(APP_ICON_B64)
    except Exception:
        return QIcon()
    pm = QPixmap()
    if not pm.loadFromData(data, "PNG"):
        return QIcon()
    return QIcon(pm)


# ============================================================
#  ГЕНЕРАЦИЯ WIN98-ИКОНОК (Base64 data URL)
# ============================================================
_ICON_CACHE = {}


def _win98_icon(kind, w, h, bg="#c0c0c0"):
    key = (kind, w, h, bg)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]

    pm = QPixmap(w, h)
    pm.fill(QColor(bg))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0))

    if kind == "down":
        p.drawPolygon(QPolygon([
            QPoint(0, 0), QPoint(w - 1, 0), QPoint(w // 2, h - 1)
        ]))
    elif kind == "up":
        p.drawPolygon(QPolygon([
            QPoint(0, h - 1), QPoint(w - 1, h - 1), QPoint(w // 2, 0)
        ]))
    elif kind == "left":
        p.drawPolygon(QPolygon([
            QPoint(w - 1, 0), QPoint(w - 1, h - 1), QPoint(0, h // 2)
        ]))
    elif kind == "right":
        p.drawPolygon(QPolygon([
            QPoint(0, 0), QPoint(0, h - 1), QPoint(w - 1, h // 2)
        ]))
    elif kind == "check":
        pen = QPen(QColor(0, 0, 0))
        pen.setWidth(2)
        pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        p.setPen(pen)
        p.drawLine(2, h // 2, w // 2, h - 3)
        p.drawLine(w // 2, h - 3, w - 2, 2)
    elif kind == "radio":
        p.setBrush(QColor(0, 0, 0))
        p.drawEllipse(4, 4, w - 8, h - 8)
    elif kind == "indeterminate":
        p.drawRect(w // 3, h // 3, w - 2 * (w // 3), h - 2 * (h // 3))

    p.end()

    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pm.save(buf, "PNG")
    b64 = bytes(buf.data().toBase64()).decode("ascii")
    buf.close()

    url = f"url(data:image/png;base64,{b64})"
    _ICON_CACHE[key] = url
    return url


def build_win98_qss():
    icons = {
        "ICON_DOWN":   _win98_icon("down",   7, 4, bg="#c0c0c0"),
        "ICON_UP":     _win98_icon("up",     7, 4, bg="#c0c0c0"),
        "ICON_LEFT":   _win98_icon("left",   4, 7, bg="#c0c0c0"),
        "ICON_RIGHT":  _win98_icon("right",  4, 7, bg="#c0c0c0"),
        "ICON_CHECK":  _win98_icon("check", 13, 13, bg="#ffffff"),
    }
    qss = WIN98_QSS_TEMPLATE
    for name, url in icons.items():
        qss = qss.replace(f"__{name}__", url)
    return qss


# ============================================================
#  WIN98 THEME (шаблон QSS)
# ============================================================
WIN98_QSS_TEMPLATE = """
* {
    font-family: "Tahoma", "Microsoft Sans Serif", "MS Sans Serif", sans-serif;
    font-size: 8pt;
}

QMainWindow, QDialog, QWidget {
    background-color: #c0c0c0;
    color: #000000;
}

QLabel {
    background-color: transparent;
    color: #000000;
}

QFrame {
    background-color: #c0c0c0;
    border: none;
}

QSplitter {
    background-color: #c0c0c0;
    border: none;
}
QSplitter::handle {
    background-color: #c0c0c0;
    border: none;
}
QSplitter::handle:hover {
    background-color: #808080;
}

QPushButton {
    background-color: #c0c0c0;
    color: #000000;
    border-top: 2px solid #ffffff;
    border-left: 2px solid #ffffff;
    border-bottom: 2px solid #404040;
    border-right: 2px solid #404040;
    padding: 3px 12px;
    min-height: 18px;
}
QPushButton:pressed {
    border-top: 2px solid #404040;
    border-left: 2px solid #404040;
    border-bottom: 2px solid #ffffff;
    border-right: 2px solid #ffffff;
    padding-top: 4px;
    padding-left: 13px;
    padding-bottom: 2px;
    padding-right: 11px;
}
QPushButton:disabled {
    color: #808080;
}

QLineEdit {
    background-color: #ffffff;
    color: #000000;
    border-top: 2px solid #404040;
    border-left: 2px solid #404040;
    border-bottom: 2px solid #ffffff;
    border-right: 2px solid #ffffff;
    padding: 2px 4px;
    min-height: 16px;
    selection-background-color: #000080;
    selection-color: #ffffff;
}

QSpinBox {
    background-color: #ffffff;
    color: #000000;
    border-top: 2px solid #404040;
    border-left: 2px solid #404040;
    border-bottom: 2px solid #ffffff;
    border-right: 2px solid #ffffff;
    padding: 2px 18px 2px 4px;
    min-height: 16px;
    selection-background-color: #000080;
    selection-color: #ffffff;
}
QSpinBox::up-button {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 16px;
    height: 9px;
    background-color: #c0c0c0;
    border-top: 2px solid #ffffff;
    border-left: 2px solid #ffffff;
    border-bottom: 1px solid #404040;
    border-right: 2px solid #404040;
}
QSpinBox::down-button {
    subcontrol-origin: padding;
    subcontrol-position: bottom right;
    width: 16px;
    height: 9px;
    background-color: #c0c0c0;
    border-top: 1px solid #ffffff;
    border-left: 2px solid #ffffff;
    border-bottom: 2px solid #404040;
    border-right: 2px solid #404040;
}
QSpinBox::up-arrow {
    image: __ICON_UP__;
    width: 7px;
    height: 4px;
}
QSpinBox::down-arrow {
    image: __ICON_DOWN__;
    width: 7px;
    height: 4px;
}

QComboBox {
    background-color: #ffffff;
    color: #000000;
    border-top: 2px solid #404040;
    border-left: 2px solid #404040;
    border-bottom: 2px solid #ffffff;
    border-right: 2px solid #ffffff;
    padding: 2px 4px;
    min-height: 16px;
}
QComboBox::drop-down {
    background-color: #c0c0c0;
    border-top: 2px solid #ffffff;
    border-left: 2px solid #ffffff;
    border-bottom: 2px solid #404040;
    border-right: 2px solid #404040;
    width: 18px;
    subcontrol-origin: padding;
    subcontrol-position: center right;
}
QComboBox::down-arrow {
    image: __ICON_DOWN__;
    width: 7px;
    height: 4px;
}
QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: #000000;
    border: 1px solid #404040;
    selection-background-color: #000080;
    selection-color: #ffffff;
}

QListWidget {
    background-color: #ffffff;
    color: #000000;
    border-top: 2px solid #404040;
    border-left: 2px solid #404040;
    border-bottom: 2px solid #ffffff;
    border-right: 2px solid #ffffff;
    outline: none;
}
QListWidget::item {
    background-color: #ffffff;
    color: #000000;
    padding: 2px 4px;
}
QListWidget::item:selected {
    background-color: #000080;
    color: #ffffff;
}

QTextEdit {
    background-color: #ffffff;
    color: #000000;
    border-top: 2px solid #404040;
    border-left: 2px solid #404040;
    border-bottom: 2px solid #ffffff;
    border-right: 2px solid #ffffff;
    font-family: "Lucida Console", "Consolas", "Courier New", monospace;
    font-size: 9pt;
    selection-background-color: #000080;
    selection-color: #ffffff;
}

QCheckBox {
    color: #000000;
    spacing: 6px;
    background-color: transparent;
}
QCheckBox::indicator {
    width: 13px;
    height: 13px;
    background-color: #ffffff;
    border-top: 2px solid #404040;
    border-left: 2px solid #404040;
    border-bottom: 2px solid #ffffff;
    border-right: 2px solid #ffffff;
}
QCheckBox::indicator:checked {
    background-color: #000080;
    border-top: 2px solid #404040;
    border-left: 2px solid #404040;
    border-bottom: 2px solid #ffffff;
    border-right: 2px solid #ffffff;
}
QCheckBox::indicator:disabled {
    background-color: #c0c0c0;
}
QCheckBox::indicator:checked:disabled {
    background-color: #808080;
}

QProgressBar {
    background-color: #c0c0c0;
    color: #000000;
    border-top: 2px solid #404040;
    border-left: 2px solid #404040;
    border-bottom: 2px solid #ffffff;
    border-right: 2px solid #ffffff;
    text-align: center;
    min-height: 18px;
}
QProgressBar::chunk {
    background-color: #000080;
}

QScrollBar:vertical {
    background-color: #c0c0c0;
    width: 16px;
    margin: 16px 0 16px 0;
    border: none;
}
QScrollBar::handle:vertical {
    background-color: #c0c0c0;
    border-top: 2px solid #ffffff;
    border-left: 2px solid #ffffff;
    border-bottom: 2px solid #404040;
    border-right: 2px solid #404040;
    min-height: 16px;
}
QScrollBar::add-line:vertical {
    background-color: #c0c0c0;
    border-top: 2px solid #ffffff;
    border-left: 2px solid #ffffff;
    border-bottom: 2px solid #404040;
    border-right: 2px solid #404040;
    height: 16px;
    subcontrol-position: bottom;
    subcontrol-origin: margin;
}
QScrollBar::sub-line:vertical {
    background-color: #c0c0c0;
    border-top: 2px solid #ffffff;
    border-left: 2px solid #ffffff;
    border-bottom: 2px solid #404040;
    border-right: 2px solid #404040;
    height: 16px;
    subcontrol-position: top;
    subcontrol-origin: margin;
}
QScrollBar::up-arrow:vertical {
    image: __ICON_UP__;
    width: 7px;
    height: 4px;
}
QScrollBar::down-arrow:vertical {
    image: __ICON_DOWN__;
    width: 7px;
    height: 4px;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background-color: #c0c0c0;
}

QScrollBar:horizontal {
    background-color: #c0c0c0;
    height: 16px;
    margin: 0 16px 0 16px;
    border: none;
}
QScrollBar::handle:horizontal {
    background-color: #c0c0c0;
    border-top: 2px solid #ffffff;
    border-left: 2px solid #ffffff;
    border-bottom: 2px solid #404040;
    border-right: 2px solid #404040;
    min-width: 16px;
}
QScrollBar::add-line:horizontal {
    background-color: #c0c0c0;
    border-top: 2px solid #ffffff;
    border-left: 2px solid #ffffff;
    border-bottom: 2px solid #404040;
    border-right: 2px solid #404040;
    width: 16px;
    subcontrol-position: right;
    subcontrol-origin: margin;
}
QScrollBar::sub-line:horizontal {
    background-color: #c0c0c0;
    border-top: 2px solid #ffffff;
    border-left: 2px solid #ffffff;
    border-bottom: 2px solid #404040;
    border-right: 2px solid #404040;
    width: 16px;
    subcontrol-position: left;
    subcontrol-origin: margin;
}
QScrollBar::left-arrow:horizontal {
    image: __ICON_LEFT__;
    width: 4px;
    height: 7px;
}
QScrollBar::right-arrow:horizontal {
    image: __ICON_RIGHT__;
    width: 4px;
    height: 7px;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background-color: #c0c0c0;
}

QScrollArea {
    background-color: #c0c0c0;
    border: none;
}

QStatusBar {
    background-color: #c0c0c0;
    color: #000000;
    border-top: 1px solid #ffffff;
}
QStatusBar::item {
    border: none;
}
QStatusBar QLabel {
    background-color: transparent;
    border: none;
}

QMenu {
    background-color: #c0c0c0;
    color: #000000;
    border-top: 2px solid #ffffff;
    border-left: 2px solid #ffffff;
    border-bottom: 2px solid #404040;
    border-right: 2px solid #404040;
}
QMenu::item {
    background-color: transparent;
    color: #000000;
    padding: 3px 24px 3px 20px;
}
QMenu::item:selected {
    background-color: #000080;
    color: #ffffff;
}
QMenu::item:disabled {
    color: #808080;
}
QMenu::separator {
    height: 1px;
    background-color: #808080;
    margin: 3px 2px 3px 2px;
}

QToolTip {
    background-color: #ffffe1;
    color: #000000;
    border: 1px solid #000000;
    padding: 2px;
}
"""


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
#  ПАРСИНГ МЕТАДАННЫХ МОДОВ
# ============================================================
def extract_minecraft_versions(mod_data):
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
        if s[0] in "[(" and s[-1] in "])":
            inner = s[1:-1]
            parts = [p.strip() for p in inner.split(",")]
            return [v for v in (clean_version(p) for p in parts) if v]
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


def parse_version_range(range_str):
    range_str = range_str.strip()
    if range_str.startswith("[") or range_str.startswith("("):
        inner = range_str[1:-1]
        parts = [p.strip() for p in inner.split(",")]
        vers = []
        for p in parts:
            if p and p not in (")", "]"):
                v = re.sub(r'^[<>=~^]+', '', p).strip()
                v = re.sub(r'[.\-][xX*]+$', '', v).strip()
                if v:
                    vers.append(v)
        return vers
    else:
        v = re.sub(r'^[<>=~^]+', '', range_str).strip()
        v = re.sub(r'[.\-][xX*]+$', '', v).strip()
        return [v] if v else []


def parse_toml_mod_info(content, loader):
    if tomllib is None:
        return None
    try:
        data = tomllib.loads(content)
    except Exception:
        return None

    deps = data.get("dependencies", {})
    if not isinstance(deps, dict):
        return None

    for mod_id, dep_list in deps.items():
        if not isinstance(dep_list, list):
            continue
        for dep in dep_list:
            if not isinstance(dep, dict):
                continue
            if dep.get("modId") == "minecraft":
                ver_range = dep.get("versionRange", "")
                mc_vers = parse_version_range(ver_range)
                if mc_vers:
                    return {
                        "loader": loader,
                        "mc_versions": mc_vers,
                        "loader_version": None,
                    }
    return None


def read_mod_info(jar_path):
    try:
        with zipfile.ZipFile(jar_path, "r") as zf:
            namelist = zf.namelist()

            if "fabric.mod.json" in namelist:
                with zf.open("fabric.mod.json") as fm:
                    data = json.load(fm)
                mc_vers = extract_minecraft_versions(data)
                if mc_vers:
                    return {
                        "loader": "fabric",
                        "mc_versions": mc_vers,
                        "loader_version": None,
                    }

            if "META-INF/mods.toml" in namelist:
                with zf.open("META-INF/mods.toml") as fm:
                    content = fm.read().decode("utf-8", errors="replace")
                info = parse_toml_mod_info(content, "forge")
                if info:
                    return info

            if "META-INF/neoforge.mods.toml" in namelist:
                with zf.open("META-INF/neoforge.mods.toml") as fm:
                    content = fm.read().decode("utf-8", errors="replace")
                info = parse_toml_mod_info(content, "neoforge")
                if info:
                    return info

    except Exception:
        pass
    return None


def read_mod_display_name(jar_path):
    try:
        with zipfile.ZipFile(jar_path, "r") as zf:
            namelist = zf.namelist()

            if "fabric.mod.json" in namelist:
                try:
                    with zf.open("fabric.mod.json") as fm:
                        data = json.load(fm)
                    if isinstance(data, dict):
                        name = data.get("name")
                        if name:
                            return str(name).strip() or None
                except Exception:
                    pass

            if "META-INF/mods.toml" in namelist and tomllib is not None:
                try:
                    with zf.open("META-INF/mods.toml") as fm:
                        content = fm.read().decode("utf-8", errors="replace")
                    data = tomllib.loads(content)
                    mods = data.get("mods")
                    if isinstance(mods, list) and mods:
                        first = mods[0]
                        if isinstance(first, dict):
                            name = (
                                first.get("displayName")
                                or first.get("modId")
                            )
                            if name:
                                return str(name).strip() or None
                except Exception:
                    pass

            if "META-INF/neoforge.mods.toml" in namelist and tomllib is not None:
                try:
                    with zf.open("META-INF/neoforge.mods.toml") as fm:
                        content = fm.read().decode("utf-8", errors="replace")
                    data = tomllib.loads(content)
                    mods = data.get("mods")
                    if isinstance(mods, list) and mods:
                        first = mods[0]
                        if isinstance(first, dict):
                            name = (
                                first.get("displayName")
                                or first.get("modId")
                            )
                            if name:
                                return str(name).strip() or None
                except Exception:
                    pass
    except Exception:
        pass
    return None


# ============================================================
#  MODRINTH API
# ============================================================
def modrinth_session():
    s = requests.Session()
    s.headers.update({"User-Agent": MODRINTH_USER_AGENT})
    return s


def modrinth_search(query, loader, mc_version, limit=20):
    facets = [
        ["project_type:mod"],
        [f"categories:{loader}"],
        [f"versions:{mc_version}"],
    ]
    params = {
        "query": query,
        "facets": json.dumps(facets),
        "limit": limit,
    }
    s = modrinth_session()
    r = s.get(f"{MODRINTH_API}/search", params=params, timeout=20)
    r.raise_for_status()
    return r.json().get("hits", [])


def modrinth_get_versions(project_id, loader, mc_version):
    params = {
        "loaders": json.dumps([loader]),
        "game_versions": json.dumps([mc_version]),
    }
    s = modrinth_session()
    r = s.get(
        f"{MODRINTH_API}/project/{project_id}/version",
        params=params, timeout=20,
    )
    r.raise_for_status()
    return r.json()


def modrinth_get_version_by_id(version_id):
    s = modrinth_session()
    r = s.get(f"{MODRINTH_API}/version/{version_id}", timeout=20)
    r.raise_for_status()
    return r.json()


# ============================================================
#  ПОТОК ЗАПУСКА / УСТАНОВКИ
# ============================================================
class LauncherThread(QThread):
    log_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal(bool, str)
    installing_signal = pyqtSignal(bool)

    def __init__(self, instance_path, version, loader_id, loader_version,
                 username, uuid_val, token,
                 java_path="java", elyby=False, memory_mb=DEFAULT_MEMORY_MB,
                 use_managed_java=False):
        super().__init__()
        self.instance_path = instance_path
        self.version = version
        self.loader_id = loader_id
        self.loader_version = loader_version
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

    def _get_required_runtime_component(self, minecraft_dir):
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

    def _prepend_java_to_path(self, java_path=None):
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
            loader_name = MOD_LOADERS.get(self.loader_id, self.loader_id)
            self.log_signal.emit(
                f"[dotLauncher] Начинаю установку Minecraft {self.version} "
                f"с {loader_name}..."
            )
            minecraft_dir = os.path.join(self.instance_path, ".minecraft")
            os.makedirs(minecraft_dir, exist_ok=True)

            callback = self._make_callback()

            self.log_signal.emit("[dotLauncher] Установка ванильного Minecraft...")
            minecraft_launcher_lib.install.install_minecraft_version(
                self.version, minecraft_dir, callback=callback
            )

            if self._stop:
                self.finished_signal.emit(False, "Отменено пользователем")
                return

            effective_java = self.java_path
            if self.use_managed_java:
                managed = self._ensure_managed_java(minecraft_dir, callback)
                if managed:
                    effective_java = managed

            self._prepend_java_to_path(effective_java)

            self.log_signal.emit(f"[dotLauncher] Установка {loader_name}...")
            mod_loader = minecraft_launcher_lib.mod_loader.get_mod_loader(
                self.loader_id
            )

            loader_version = self.loader_version
            if not loader_version:
                try:
                    loader_version = mod_loader.get_latest_loader_version(
                        self.version
                    )
                except Exception:
                    loader_version = None

            if not loader_version:
                raise Exception(
                    f"Не удалось определить версию {loader_name} "
                    f"для Minecraft {self.version}"
                )

            self.log_signal.emit(
                f"[dotLauncher] Версия {loader_name}: {loader_version}"
            )

            mod_loader.install(
                self.version,
                minecraft_dir,
                loader_version=loader_version,
                callback=callback,
                java=effective_java,
            )

            if self._stop:
                self.finished_signal.emit(False, "Отменено пользователем")
                return

            installed_version = mod_loader.get_installed_version(
                self.version, loader_version
            )
            self.log_signal.emit(
                f"[dotLauncher] Идентификатор версии для запуска: {installed_version}"
            )

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
                installed_version, minecraft_dir, options
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
    ask_signal = pyqtSignal(list, list)
    finished_signal = pyqtSignal(bool, dict)

    def __init__(self, files, workspace, instances_dir, existing_ids):
        super().__init__()
        self.files = list(files)
        self.workspace = workspace
        self.instances_dir = instances_dir
        self.existing_ids = set(existing_ids)
        self._event = threading.Event()
        self._chosen_version = None
        self._chosen_loader = None
        self._chosen_name = None
        self._cancelled = False
        self._temp_dirs = []

    def set_user_choice(self, version, loader, name):
        self._chosen_version = version
        self._chosen_loader = loader
        self._chosen_name = name
        self._event.set()

    def cancel(self):
        self._cancelled = True
        self._event.set()

    def _extract_zip(self, zip_path):
        temp = tempfile.mkdtemp(prefix="dotlauncher_import_")
        self._temp_dirs.append(temp)
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.infolist():
                name = member.filename
                if name.startswith("/") or name.startswith("\\"):
                    continue
                parts = re.split(r"[\\/]", name)
                if ".." in parts:
                    continue
                zf.extract(member, temp)
        return temp

    def _scan_folder(self, folder, mods_info, extra_dirs):
        for root, dirs, files in os.walk(folder, followlinks=False):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

            for fn in files:
                if not fn.lower().endswith(".jar"):
                    continue
                full = os.path.join(root, fn)
                info = read_mod_info(full)
                if not info:
                    continue
                mods_info.append((full, info))
                self.log_signal.emit(
                    f"[dotLauncher] {os.path.basename(full)} → "
                    f"{MOD_LOADERS.get(info['loader'], info['loader'])} "
                    f"Minecraft {', '.join(info['mc_versions'])}"
                )

        for base in (folder, os.path.join(folder, ".minecraft")):
            if not os.path.isdir(base):
                continue
            for name in COPYABLE_DIRS:
                src = os.path.join(base, name)
                if os.path.isdir(src) and name not in extra_dirs:
                    extra_dirs[name] = src

    def _scan(self):
        mods_info = []
        extra_dirs = {}

        for path in self.files:
            if self._cancelled:
                break
            if os.path.isfile(path):
                low = path.lower()
                if low.endswith(".jar"):
                    info = read_mod_info(path)
                    if info:
                        mods_info.append((path, info))
                        self.log_signal.emit(
                            f"[dotLauncher] {os.path.basename(path)} → "
                            f"{MOD_LOADERS.get(info['loader'], info['loader'])} "
                            f"Minecraft {', '.join(info['mc_versions'])}"
                        )
                    else:
                        self.log_signal.emit(
                            f"[dotLauncher] {os.path.basename(path)} — "
                            f"не поддерживаемый мод, пропускаю."
                        )
                elif low.endswith(".zip"):
                    self.log_signal.emit(
                        f"[dotLauncher] Распаковка {os.path.basename(path)}..."
                    )
                    try:
                        temp = self._extract_zip(path)
                        self._scan_folder(temp, mods_info, extra_dirs)
                    except Exception as e:
                        self.log_signal.emit(
                            f"[Ошибка] Не удалось распаковать "
                            f"{os.path.basename(path)}: {e}"
                        )
            elif os.path.isdir(path):
                self._scan_folder(path, mods_info, extra_dirs)

        return mods_info, extra_dirs

    def _new_instance_id(self):
        while True:
            iid = str(uuid.uuid4())[:8]
            if iid in self.existing_ids:
                continue
            if os.path.exists(os.path.join(self.instances_dir, iid)):
                continue
            return iid

    def _copy_files(self, mods_info, extra_dirs, version, loader, loader_version, name):
        instance_id = self._new_instance_id()
        instance_dir = os.path.join(self.instances_dir, instance_id)
        minecraft_dir = os.path.join(instance_dir, ".minecraft")
        mods_dir = os.path.join(minecraft_dir, "mods")
        os.makedirs(mods_dir, exist_ok=True)

        filtered_mods = []
        for jar, info in mods_info:
            if info["loader"] != loader:
                self.log_signal.emit(
                    f"[dotLauncher] Пропуск {os.path.basename(jar)}: "
                    f"загрузчик {info['loader']} не совпадает с выбранным {loader}"
                )
                continue
            if version not in info["mc_versions"]:
                self.log_signal.emit(
                    f"[dotLauncher] Пропуск {os.path.basename(jar)}: "
                    f"версия Minecraft {version} не поддерживается "
                    f"(доступны: {', '.join(info['mc_versions'])})"
                )
                continue
            filtered_mods.append((jar, info))

        if not filtered_mods:
            self.log_signal.emit(
                "[Внимание] После фильтрации не осталось подходящих модов."
            )

        copied_names = set()
        for jar, _ in filtered_mods:
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
            "loader": loader,
            "loader_version": loader_version,
            "path_rel": path_rel,
        }

    def run(self):
        try:
            self.log_signal.emit(
                f"[dotLauncher] Обработка {len(self.files)} элементов..."
            )
            mods_info, extra_dirs = self._scan()

            if self._cancelled:
                self.finished_signal.emit(False, {"error": "Отменено"})
                return

            if not mods_info:
                self.finished_signal.emit(
                    False, {"error": "Не найдено подходящих модов."}
                )
                return

            loaders = Counter()
            versions_per_loader = {}
            loader_versions = {}

            for _, info in mods_info:
                lid = info["loader"]
                loaders[lid] += 1
                if lid not in versions_per_loader:
                    versions_per_loader[lid] = set()
                versions_per_loader[lid].update(info["mc_versions"])
                if info.get("loader_version"):
                    loader_versions[lid] = info["loader_version"]

            if len(loaders) == 1:
                chosen_loader = list(loaders.keys())[0]
                mc_versions = sorted(versions_per_loader[chosen_loader])
                chosen_loader_version = loader_versions.get(chosen_loader)
            else:
                self.log_signal.emit(
                    f"[dotLauncher] Обнаружены моды для разных загрузчиков: "
                    f"{', '.join(MOD_LOADERS.get(k, k) for k in loaders)}"
                )
                available_loaders = list(loaders.keys())
                all_versions = set()
                for lid in available_loaders:
                    all_versions.update(versions_per_loader[lid])
                mc_versions = sorted(all_versions)

                self.ask_signal.emit(mc_versions, available_loaders)
                self._event.wait()
                self._event.clear()
                if self._cancelled or not self._chosen_version or not self._chosen_loader or not self._chosen_name:
                    self.finished_signal.emit(False, {"error": "Отменено"})
                    return
                chosen_loader = self._chosen_loader
                chosen_version = self._chosen_version
                chosen_loader_version = loader_versions.get(chosen_loader)
                if not chosen_version:
                    chosen_version = mc_versions[0] if mc_versions else None

            if len(loaders) == 1:
                if len(mc_versions) == 1:
                    chosen_version = mc_versions[0]
                else:
                    self.ask_signal.emit(mc_versions, [chosen_loader])
                    self._event.wait()
                    self._event.clear()
                    if self._cancelled or not self._chosen_version or not self._chosen_name:
                        self.finished_signal.emit(False, {"error": "Отменено"})
                        return
                    chosen_version = self._chosen_version

                if self._chosen_name is None:
                    self.ask_signal.emit([chosen_version], [chosen_loader])
                    self._event.wait()
                    self._event.clear()
                    if self._cancelled or not self._chosen_name:
                        self.finished_signal.emit(False, {"error": "Отменено"})
                        return

            name = sanitize_instance_name(self._chosen_name)
            info = self._copy_files(
                mods_info, extra_dirs, chosen_version, chosen_loader,
                chosen_loader_version, name
            )
            self.log_signal.emit(
                f"[dotLauncher] Сборка «{name}» "
                f"({MOD_LOADERS.get(chosen_loader, chosen_loader)} {chosen_version}) создана."
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
#  ПОТОК: ЗАГРУЗКА СПИСКА ВЕРСИЙ MINECRAFT
# ============================================================
class VersionFetchThread(QThread):
    finished_signal = pyqtSignal(bool, list, str)

    def run(self):
        try:
            versions = minecraft_launcher_lib.utils.get_version_list()
            self.finished_signal.emit(True, versions, "")
        except Exception as e:
            self.finished_signal.emit(False, [], str(e))


# ============================================================
#  ПОТОК: СОЗДАНИЕ ЧИСТОЙ СБОРКИ (без модов)
# ============================================================
class InstanceInstallThread(QThread):
    log_signal = pyqtSignal(str)
    status_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal(bool, dict, str)

    def __init__(self, instances_dir, workspace, instance_id, version,
                 loader_id, name, java_path=None):
        super().__init__()
        self.instances_dir = instances_dir
        self.workspace = workspace
        self.instance_id = instance_id
        self.version = version
        self.loader_id = loader_id
        self.name = name
        self.java_path = java_path
        self._stop = False
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

    def run(self):
        try:
            loader_name = MOD_LOADERS.get(self.loader_id, self.loader_id)
            self.log_signal.emit(
                f"[dotLauncher] Создание сборки «{self.name}»: "
                f"Minecraft {self.version} + {loader_name}"
            )

            instance_dir = os.path.join(self.instances_dir, self.instance_id)
            minecraft_dir = os.path.join(instance_dir, ".minecraft")
            os.makedirs(minecraft_dir, exist_ok=True)

            callback = self._make_callback()

            self.log_signal.emit("[dotLauncher] Установка ванильного Minecraft...")
            minecraft_launcher_lib.install.install_minecraft_version(
                self.version, minecraft_dir, callback=callback
            )

            if self._stop:
                self.finished_signal.emit(
                    False, {"instance_id": self.instance_id},
                    "Отменено пользователем"
                )
                return

            self.log_signal.emit(f"[dotLauncher] Установка {loader_name}...")
            mod_loader = minecraft_launcher_lib.mod_loader.get_mod_loader(
                self.loader_id
            )

            try:
                loader_version = mod_loader.get_latest_loader_version(self.version)
            except Exception:
                loader_version = None

            if not loader_version:
                raise Exception(
                    f"Не удалось определить версию {loader_name} "
                    f"для Minecraft {self.version}"
                )

            self.log_signal.emit(
                f"[dotLauncher] Версия {loader_name}: {loader_version}"
            )

            install_kwargs = {}
            if self.java_path:
                install_kwargs["java"] = self.java_path

            mod_loader.install(
                self.version,
                minecraft_dir,
                loader_version=loader_version,
                callback=callback,
                **install_kwargs,
            )

            if self._stop:
                self.finished_signal.emit(
                    False, {"instance_id": self.instance_id},
                    "Отменено пользователем"
                )
                return

            path_rel = os.path.relpath(instance_dir, self.workspace)
            info = {
                "instance_id": self.instance_id,
                "name": self.name,
                "version": self.version,
                "loader": self.loader_id,
                "loader_version": loader_version,
                "path_rel": path_rel,
            }
            self.log_signal.emit(
                f"[dotLauncher] Сборка «{self.name}» создана."
            )
            self.finished_signal.emit(True, info, "")
        except Exception as e:
            self.log_signal.emit(f"[Ошибка] {type(e).__name__}: {e}")
            try:
                self.log_signal.emit(traceback.format_exc())
            except Exception:
                pass
            self.finished_signal.emit(
                False, {"instance_id": self.instance_id}, str(e)
            )

    def stop(self):
        self._stop = True


# ============================================================
#  ПОТОКИ MODRINTH
# ============================================================
class ModrinthSearchThread(QThread):
    finished_signal = pyqtSignal(bool, list, str)

    def __init__(self, query, loader, mc_version):
        super().__init__()
        self.query = query
        self.loader = loader
        self.mc_version = mc_version

    def run(self):
        try:
            hits = modrinth_search(self.query, self.loader, self.mc_version)
            self.finished_signal.emit(True, hits, "")
        except Exception as e:
            self.finished_signal.emit(False, [], str(e))


class ModrinthDownloadThread(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, projects, mods_dir, loader, mc_version, download_deps):
        super().__init__()
        self.projects = projects
        self.mods_dir = mods_dir
        self.loader = loader
        self.mc_version = mc_version
        self.download_deps = download_deps
        self._stop = False

    def stop(self):
        self._stop = True

    def _resolve_project(self, project_id, to_download, visited):
        if project_id in visited:
            return
        visited.add(project_id)

        try:
            versions = modrinth_get_versions(project_id, self.loader, self.mc_version)
        except Exception as e:
            self.log_signal.emit(f"[Modrinth] Ошибка получения версий {project_id}: {e}")
            return

        if not versions:
            self.log_signal.emit(
                f"[Modrinth] Нет подходящей версии для проекта {project_id} "
                f"({self.loader} {self.mc_version})"
            )
            return

        v = versions[0]
        to_download[project_id] = v

        if not self.download_deps:
            return

        for dep in v.get("dependencies", []):
            if dep.get("dependency_type") != "required":
                continue
            dep_pid = dep.get("project_id")
            if not dep_pid and dep.get("version_id"):
                try:
                    dep_ver = modrinth_get_version_by_id(dep["version_id"])
                    dep_pid = dep_ver.get("project_id")
                except Exception:
                    dep_pid = None
            if dep_pid and dep_pid not in visited:
                self.log_signal.emit(
                    f"[Modrinth] Зависимость: {dep_pid}"
                )
                self._resolve_project(dep_pid, to_download, visited)

    def _pick_primary_file(self, vdata):
        files = vdata.get("files", []) or []
        for f in files:
            if f.get("primary"):
                return f
        return files[0] if files else None

    def _download_version(self, vdata):
        primary = self._pick_primary_file(vdata)
        if not primary:
            self.log_signal.emit(
                f"[Modrinth] У версии {vdata.get('version_number')} нет файлов"
            )
            return

        url = primary.get("url")
        filename = primary.get("filename") or "mod.jar"
        if not url:
            return

        dest = os.path.join(self.mods_dir, filename)
        if os.path.isfile(dest):
            self.log_signal.emit(f"[Modrinth] Уже установлен: {filename}")
            return

        self.log_signal.emit(f"[Modrinth] Скачивание {filename}...")
        s = modrinth_session()
        r = s.get(url, stream=True, timeout=120)
        r.raise_for_status()

        tmp = dest + ".tmp"
        try:
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if self._stop:
                        raise Exception("Отменено")
                    f.write(chunk)
            os.replace(tmp, dest)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    def run(self):
        try:
            os.makedirs(self.mods_dir, exist_ok=True)

            to_download = {}
            visited = set()

            for proj in self.projects:
                if self._stop:
                    self.finished_signal.emit(False, "Отменено")
                    return
                self._resolve_project(proj["project_id"], to_download, visited)

            if not to_download:
                self.finished_signal.emit(
                    False, "Не найдено подходящих версий для выбранных модов."
                )
                return

            total = len(to_download)
            self.log_signal.emit(f"[Modrinth] К загрузке: {total} файл(ов)")
            self.progress_signal.emit(0, total)

            for i, (pid, vdata) in enumerate(to_download.items(), start=1):
                if self._stop:
                    self.finished_signal.emit(False, "Отменено")
                    return
                try:
                    self._download_version(vdata)
                except Exception as e:
                    self.log_signal.emit(f"[Modrinth] Ошибка загрузки: {e}")
                self.progress_signal.emit(i, total)

            self.finished_signal.emit(True, f"Загрузка завершена: {total} файл(ов).")
        except Exception as e:
            self.finished_signal.emit(False, str(e))


# ============================================================
#  ОКНО MODRINTH
# ============================================================
class ModrinthWindow(QDialog):
    def __init__(self, instance_name, loader_id, mc_version, mods_dir, parent=None):
        super().__init__(parent)
        self.instance_name = instance_name
        self.loader_id = loader_id
        self.mc_version = mc_version
        self.mods_dir = mods_dir

        self.chosen = {}
        self._result_cards = []
        self.search_thread = None
        self.download_thread = None

        self.setWindowTitle(f"Modrinth — {instance_name}")
        self.setMinimumSize(860, 720)
        self.init_ui()

    def loader_name(self):
        return MOD_LOADERS.get(self.loader_id, self.loader_id)

    def modrinth_loader(self):
        return LOADER_TO_MODRINTH.get(self.loader_id, self.loader_id)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        self.stack.addWidget(self._build_search_page())
        self.stack.addWidget(self._build_confirm_page())
        self.stack.setCurrentIndex(0)

    def _build_search_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)

        header = QLabel(
            f"Поиск модов для {self.loader_name()} {self.mc_version}"
        )
        header.setFont(QFont("Tahoma", 9, QFont.Weight.Bold))
        v.addWidget(header)

        row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Введите название мода...")
        self.search_input.returnPressed.connect(self.do_search)
        row.addWidget(self.search_input)

        search_btn = QPushButton("Найти")
        search_btn.setFixedWidth(90)
        search_btn.clicked.connect(self.do_search)
        row.addWidget(search_btn)
        v.addLayout(row)

        self.search_status = QLabel("")
        v.addWidget(self.search_status)

        self.results_scroll = QScrollArea()
        self.results_scroll.setWidgetResizable(True)
        self.results_scroll.setFrameShape(QFrame.Shape.StyledPanel)
        self.results_scroll.setFrameShadow(QFrame.Shadow.Sunken)
        self.results_widget = QWidget()
        self.results_widget.setStyleSheet("background-color: #ffffff;")
        self.results_layout = QVBoxLayout(self.results_widget)
        self.results_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.results_layout.setSpacing(4)
        self.results_scroll.setWidget(self.results_widget)
        v.addWidget(self.results_scroll, 1)

        bottom = QHBoxLayout()
        self.chosen_label = QLabel("Выбрано: 0")
        bottom.addWidget(self.chosen_label)
        bottom.addStretch()

        confirm_btn = QPushButton("Подтвердить")
        confirm_btn.setFixedSize(140, 26)
        confirm_btn.clicked.connect(self.go_to_confirm)
        bottom.addWidget(confirm_btn)
        v.addLayout(bottom)

        return page

    def _build_confirm_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)

        header = QLabel("Подтверждение")
        header.setFont(QFont("Tahoma", 9, QFont.Weight.Bold))
        v.addWidget(header)

        self.confirm_label = QLabel("")
        self.confirm_label.setWordWrap(True)
        v.addWidget(self.confirm_label)

        self.confirm_list = QListWidget()
        v.addWidget(self.confirm_list, 1)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        v.addWidget(self.progress)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setFixedHeight(140)
        self.log_area.setVisible(False)
        v.addWidget(self.log_area)

        self.download_btn = QPushButton("Скачать моды")
        self.download_btn.setFixedHeight(26)
        self.download_btn.clicked.connect(self.do_download)
        v.addWidget(self.download_btn)

        self.deps_check = QCheckBox("Скачать все зависимости к модам")
        self.deps_check.setChecked(True)
        v.addWidget(self.deps_check)

        back_btn = QPushButton("Назад")
        back_btn.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        v.addWidget(back_btn)

        return page

    def do_search(self):
        query = self.search_input.text().strip()
        if not query:
            return
        if self.search_thread and self.search_thread.isRunning():
            return

        self.chosen.clear()
        self._update_chosen_label()

        self.search_status.setText("Поиск...")
        self._clear_results()

        self.search_thread = ModrinthSearchThread(
            query, self.modrinth_loader(), self.mc_version
        )
        self.search_thread.finished_signal.connect(self.on_search_done)
        self.search_thread.start()

    def on_search_done(self, success, hits, error):
        if not success:
            self.search_status.setText(f"Ошибка: {error}")
            return
        if not hits:
            self.search_status.setText("Ничего не найдено")
            return
        self.search_status.setText(f"Найдено: {len(hits)}")
        for hit in hits:
            self._add_result_card(hit)

    def _clear_results(self):
        for card in self._result_cards:
            card.setParent(None)
            card.deleteLater()
        self._result_cards.clear()
        while self.results_layout.count():
            item = self.results_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _add_result_card(self, hit):
        pid = hit.get("project_id") or hit.get("slug")
        if not pid:
            return

        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setFrameShadow(QFrame.Shadow.Raised)
        card.setStyleSheet("QFrame { background-color: #c0c0c0; }")
        card.setMinimumHeight(80)
        h = QHBoxLayout(card)
        h.setContentsMargins(8, 6, 8, 6)

        info = QVBoxLayout()
        title = QLabel(hit.get("title", "Unknown"))
        title.setFont(QFont("Tahoma", 9, QFont.Weight.Bold))
        info.addWidget(title)

        author = QLabel(f"by {hit.get('author', 'Unknown')}")
        info.addWidget(author)

        desc = QLabel((hit.get("description") or "")[:220])
        desc.setWordWrap(True)
        info.addWidget(desc)

        downloads = hit.get("downloads", 0) or 0
        meta = QLabel(f"Загрузок: {downloads:,}")
        info.addWidget(meta)

        h.addLayout(info, 1)

        btn = QPushButton("Скачать")
        btn.setFixedSize(110, 26)

        def on_click(_checked=False, _pid=pid, _hit=hit, _btn=btn):
            if _pid in self.chosen:
                del self.chosen[_pid]
                _btn.setText("Скачать")
            else:
                self.chosen[_pid] = _hit
                _btn.setText("Добавлено ✓")
            self._update_chosen_label()

        btn.clicked.connect(on_click)
        h.addWidget(btn, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.results_layout.addWidget(card)
        self._result_cards.append(card)

    def _update_chosen_label(self):
        self.chosen_label.setText(f"Выбрано: {len(self.chosen)}")

    def go_to_confirm(self):
        if not self.chosen:
            QMessageBox.information(self, "Пусто", "Выберите хотя бы один мод.")
            return

        self.confirm_list.clear()
        for pid, hit in self.chosen.items():
            title = hit.get("title", pid)
            author = hit.get("author", "")
            item = QListWidgetItem(f"{title} — {author}")
            item.setData(Qt.ItemDataRole.UserRole, pid)
            self.confirm_list.addItem(item)

        self.confirm_label.setText(
            f"Будет установлено в сборку «{self.instance_name}»: "
            f"{len(self.chosen)} мод(ов)."
        )
        self.stack.setCurrentIndex(1)

    def do_download(self):
        if self.download_thread and self.download_thread.isRunning():
            return

        projects = [
            {"project_id": pid, "title": hit.get("title", pid)}
            for pid, hit in self.chosen.items()
        ]
        if not projects:
            QMessageBox.information(self, "Пусто", "Список пуст.")
            return

        download_deps = self.deps_check.isChecked()

        self.download_btn.setEnabled(False)
        self.download_btn.setText("Скачивание...")
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.log_area.setVisible(True)
        self.log_area.clear()

        self.download_thread = ModrinthDownloadThread(
            projects,
            self.mods_dir,
            self.modrinth_loader(),
            self.mc_version,
            download_deps,
        )
        self.download_thread.log_signal.connect(self.log_area.append)
        self.download_thread.progress_signal.connect(self._update_progress)
        self.download_thread.finished_signal.connect(self.on_download_done)
        self.download_thread.start()

    def _update_progress(self, current, total):
        if total > 0:
            self.progress.setMaximum(total)
            self.progress.setValue(current)
        else:
            self.progress.setMaximum(0)

    def on_download_done(self, success, message):
        self.download_btn.setEnabled(True)
        self.download_btn.setText("Скачать моды")
        if success:
            QMessageBox.information(self, "Готово", message)
            self.accept()
        else:
            QMessageBox.warning(self, "Ошибка", message)

    def closeEvent(self, event):
        if self.search_thread and self.search_thread.isRunning():
            self.search_thread.wait(2000)
        if self.download_thread and self.download_thread.isRunning():
            reply = QMessageBox.question(
                self, "Загрузка в процессе",
                "Загрузка ещё не завершена. Прервать и закрыть?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.download_thread.stop()
            self.download_thread.wait(3000)
        event.accept()


# ============================================================
#  ОКНО: СОЗДАНИЕ СБОРКИ
# ============================================================
class NewInstanceDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Создание новой сборки")
        self.setMinimumSize(680, 560)
        self.result_data = None
        self._all_versions = []
        self._fetch_thread = None
        self.init_ui()
        self.load_versions()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        header = QLabel("Создание новой сборки")
        header.setFont(QFont("Tahoma", 11, QFont.Weight.Bold))
        layout.addWidget(header)

        columns = QHBoxLayout()
        columns.setSpacing(8)

        # --- Левая колонка: версии ---
        left = QVBoxLayout()
        left.setSpacing(4)

        left.addWidget(QLabel("Версия Minecraft:"))

        self.version_list = QListWidget()
        left.addWidget(self.version_list, 1)

        self.show_snapshots_cb = QCheckBox("Показывать снапшоты")
        self.show_snapshots_cb.toggled.connect(self._refresh_versions)
        left.addWidget(self.show_snapshots_cb)

        # --- Правая колонка: настройки ---
        right = QVBoxLayout()
        right.setSpacing(4)

        right.addWidget(QLabel("Настройки"))

        right.addSpacing(6)
        right.addWidget(QLabel("Название сборки:"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Моя сборка")
        right.addWidget(self.name_input)

        right.addSpacing(8)
        right.addWidget(QLabel("Загрузчик:"))
        self.loader_combo = QComboBox()
        self.loader_combo.addItems(["Fabric", "Forge", "NeoForge"])
        right.addWidget(self.loader_combo)

        right.addStretch()

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        right.addWidget(self.status_label)

        self.create_btn = QPushButton("Создать")
        self.create_btn.setFixedHeight(28)
        self.create_btn.clicked.connect(self.on_create)
        right.addWidget(self.create_btn)

        cancel_btn = QPushButton("Отмена")
        cancel_btn.setFixedHeight(28)
        cancel_btn.clicked.connect(self.reject)
        right.addWidget(cancel_btn)

        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        layout.addLayout(columns, 1)

    def load_versions(self):
        self.version_list.clear()
        self.version_list.addItem("Загрузка списка версий...")
        self.version_list.setEnabled(False)

        self._fetch_thread = VersionFetchThread()
        self._fetch_thread.finished_signal.connect(self.on_versions_loaded)
        self._fetch_thread.start()

    def on_versions_loaded(self, success, versions, error):
        self.version_list.setEnabled(True)
        if not success:
            self.version_list.clear()
            self.version_list.addItem(f"Ошибка загрузки: {error}")
            self.status_label.setText("Не удалось получить список версий.")
            return
        self._all_versions = versions
        self._refresh_versions()

    def _refresh_versions(self):
        if not self._all_versions:
            return
        show_snaps = self.show_snapshots_cb.isChecked()
        self.version_list.clear()
        for v in self._all_versions:
            vtype = v.get("type", "")
            if not show_snaps and vtype != "release":
                continue
            if show_snaps and vtype not in ("release", "snapshot"):
                continue
            vid = v.get("id")
            if not vid:
                continue
            self.version_list.addItem(vid)

    def on_create(self):
        item = self.version_list.currentItem()
        if item is None:
            QMessageBox.warning(
                self, "Версия не выбрана",
                "Выберите версию Minecraft из списка слева."
            )
            return
        version = item.text()
        if not version or version.startswith("Загрузка") or version.startswith("Ошибка"):
            QMessageBox.warning(
                self, "Версия не выбрана",
                "Выберите версию Minecraft из списка слева."
            )
            return

        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(
                self, "Название не введено",
                "Введите название для новой сборки."
            )
            return

        loader_display = self.loader_combo.currentText()
        loader_id = None
        for lid, lname in MOD_LOADERS.items():
            if lname == loader_display:
                loader_id = lid
                break
        if not loader_id:
            QMessageBox.warning(
                self, "Ошибка",
                "Не удалось определить загрузчик."
            )
            return

        self.result_data = {
            "name": name,
            "version": version,
            "loader": loader_id,
        }
        self.accept()


# ============================================================
#  DROP ZONE
# ============================================================
class DropZone(QLabel):
    filesDropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFont(QFont("Tahoma", 9))
        self.setStyleSheet("""
            QLabel {
                background-color: #ffffff;
                color: #000000;
                border-top: 2px solid #404040;
                border-left: 2px solid #404040;
                border-bottom: 2px solid #ffffff;
                border-right: 2px solid #ffffff;
                padding: 30px;
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
#  СПИСОК МОДОВ С КЛИКОМ ЛЮБОЙ КНОПКОЙ
# ============================================================
class ModsListWidget(QListWidget):
    modRowClicked = pyqtSignal(int)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        # Только левая кнопка мыши переключает мод.
        # ПКМ используется для контекстного меню и не должна менять состояние.
        if event.button() != Qt.MouseButton.LeftButton:
            return
        index = self.indexAt(event.pos())
        if index.isValid():
            row = index.row()
            QTimer.singleShot(0, lambda r=row: self._emit_row(r))

    def _emit_row(self, row):
        if 0 <= row < self.count():
            self.modRowClicked.emit(row)


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
        self.instance_install_thread = None
        self.mods_expanded = False

        self.config_dir = get_config_dir()
        self.config_path = os.path.join(self.config_dir, "dot_config.json")

        self.init_ui()
        self.load_config()

    # ---------- ИНТЕРФЕЙС ----------
    def init_ui(self):
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1000, 720)

        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(192, 192, 192))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(0, 0, 0))
        palette.setColor(QPalette.ColorRole.Base, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(232, 232, 232))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 225))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor(0, 0, 0))
        palette.setColor(QPalette.ColorRole.Text, QColor(0, 0, 0))
        palette.setColor(QPalette.ColorRole.Button, QColor(192, 192, 192))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(0, 0, 0))
        palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
        palette.setColor(QPalette.ColorRole.Link, QColor(0, 0, 255))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(0, 0, 128))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
        self.setPalette(palette)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(3)

        # ---------- ЛЕВАЯ ПАНЕЛЬ ----------
        left = QFrame()
        left.setFrameShape(QFrame.Shape.Panel)
        left.setFrameShadow(QFrame.Shadow.Raised)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(4)

        account_label = QLabel("Аккаунт")
        account_label.setFont(QFont("Tahoma", 9, QFont.Weight.Bold))
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
        self.login_status.setWordWrap(True)
        left_layout.addWidget(self.login_status)

        left_layout.addSpacing(8)

        memory_label = QLabel("Память (MB)")
        memory_label.setFont(QFont("Tahoma", 9, QFont.Weight.Bold))
        left_layout.addWidget(memory_label)

        self.memory_spin = QSpinBox()
        self.memory_spin.setRange(MIN_MEMORY_MB, MAX_MEMORY_MB)
        self.memory_spin.setSingleStep(256)
        self.memory_spin.setValue(DEFAULT_MEMORY_MB)
        self.memory_spin.valueChanged.connect(self.save_memory)
        left_layout.addWidget(self.memory_spin)

        left_layout.addSpacing(4)

        self.java_button = QPushButton("Выбрать Java...")
        self.java_button.clicked.connect(self.choose_java)
        left_layout.addWidget(self.java_button)

        self.java_status = QLabel("Java: авто")
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

        left_layout.addSpacing(8)

        instances_label = QLabel("Сборки")
        instances_label.setFont(QFont("Tahoma", 9, QFont.Weight.Bold))
        left_layout.addWidget(instances_label)

        # ---- Кнопка "Новая сборка" (всегда сверху) ----
        self.new_instance_button = QPushButton("＋ Новая сборка")
        self.new_instance_button.clicked.connect(self.open_new_instance_dialog)
        left_layout.addWidget(self.new_instance_button)

        self.instance_list = QListWidget()
        self.instance_list.itemClicked.connect(self.on_instance_selected)
        self.instance_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.instance_list.customContextMenuRequested.connect(
            self.on_instance_context_menu
        )
        left_layout.addWidget(self.instance_list, 1)

        # ---- Список модов внутри выбранной сборки ----
        self.mods_list = ModsListWidget()
        self.mods_list.setVisible(False)
        self.mods_list.setMinimumHeight(120)
        self.mods_list.modRowClicked.connect(self.on_mod_row_clicked)
        self.mods_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.mods_list.customContextMenuRequested.connect(
            self.on_mods_context_menu
        )
        left_layout.addWidget(self.mods_list, 2)

        self.modrinth_button = QPushButton("Скачать из Modrinth")
        self.modrinth_button.clicked.connect(self.open_modrinth_window)
        left_layout.addWidget(self.modrinth_button)

        left_layout.addStretch()

        # ---------- ЦЕНТРАЛЬНАЯ ПАНЕЛЬ ----------
        center = QFrame()
        center.setFrameShape(QFrame.Shape.Panel)
        center.setFrameShadow(QFrame.Shadow.Raised)
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(12, 12, 12, 12)
        center_layout.setSpacing(6)

        self.title_label = QLabel(APP_NAME)
        self.title_label.setFont(QFont("Tahoma", 16, QFont.Weight.Bold))
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center_layout.addWidget(self.title_label)

        self.drop_zone = DropZone(self)
        self.drop_zone.setText(
            "Перетащи сюда .jar файлы модов, папку модпака\n"
            "или .zip-архив, чтобы создать сборку dotLauncher\n\n"
            "Поддерживаются Fabric, Forge и NeoForge"
        )
        self.drop_zone.filesDropped.connect(self.handle_dropped_files)
        center_layout.addWidget(self.drop_zone, 1)

        self.instance_info = QWidget()
        self.instance_info.setVisible(False)
        info_layout = QVBoxLayout(self.instance_info)
        info_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.instance_name_label = QLabel("")
        self.instance_name_label.setFont(QFont("Tahoma", 18, QFont.Weight.Bold))
        self.instance_name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_layout.addWidget(self.instance_name_label)

        self.instance_version_label = QLabel("")
        self.instance_version_label.setFont(QFont("Tahoma", 10))
        self.instance_version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info_layout.addWidget(self.instance_version_label)

        info_layout.addSpacing(20)

        self.play_button = QPushButton("ИГРАТЬ")
        self.play_button.setFont(QFont("Tahoma", 12, QFont.Weight.Bold))
        self.play_button.setFixedSize(200, 44)
        self.play_button.clicked.connect(self.play_game)
        info_layout.addWidget(self.play_button, alignment=Qt.AlignmentFlag.AlignCenter)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedWidth(300)
        info_layout.addWidget(self.progress_bar, alignment=Qt.AlignmentFlag.AlignCenter)

        center_layout.addWidget(self.instance_info, 1)

        console_label = QLabel("Консоль")
        console_label.setFont(QFont("Tahoma", 9, QFont.Weight.Bold))
        center_layout.addWidget(console_label)

        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(QFont("Lucida Console", 9))
        self.console.setFixedHeight(200)
        center_layout.addWidget(self.console)

        splitter.addWidget(left)
        splitter.addWidget(center)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        main_layout.addWidget(splitter)

        self.status_bar = self.statusBar()
        self.status_bar.showMessage("Готов")

    # ---------- КОНФИГ ----------
    def _validate_config(self, cfg):
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

        if self.config.get("email"):
            self.account_type.setCurrentIndex(1)
            self.email_input.setText(self.config["email"])
            if self.config.get("elyby_username"):
                self.username_input.setText(self.config["elyby_username"])
                self.login_status.setText(
                    f"Сохранён аккаунт: {self.config['elyby_username']}"
                )
            if self.config.get("elyby_refresh_token"):
                self._try_refresh_elyby()
        elif self.config.get("username"):
            self.username_input.setText(self.config["username"])

        if self.config.get("java_path"):
            self.java_status.setText(f"Java: {self.config['java_path']} (вручную)")
        else:
            self.java_status.setText("Java: авто")

        self.log(f"[dotLauncher] Конфиг: {self.config_dir}")
        self.log(f"[dotLauncher] Рабочая папка: {workspace}")
        self.log("[dotLauncher] Готов к работе.")

    def _migrate_instances(self, raw, workspace):
        out = {}
        for iid, inst in raw.items():
            if not isinstance(inst, dict):
                continue
            if inst.get("installing"):
                continue
            name = inst.get("name")
            version = inst.get("version")
            loader = inst.get("loader", "fabric")
            loader_version = inst.get("loader_version")
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
                "loader": loader, "loader_version": loader_version,
                "path_rel": path_rel,
            }
        return out

    def save_config(self):
        try:
            cfg = dict(self.config)
            cfg.pop("instances_dir", None)
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
        if self.instance_install_thread and self.instance_install_thread.isRunning():
            self.log("[Ошибка] Идёт создание новой сборки. Дождитесь завершения.")
            return

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

    def import_modpack_dialog(self):
        """Диалог выбора .zip/.jar для импорта модпака."""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Выберите модпак, архив или моды для импорта",
            "",
            "Модпаки и моды (*.zip *.jar);;Все файлы (*)",
        )
        if not files:
            return
        self.handle_dropped_files(files)

    def on_import_ask(self, versions, loaders):
        thread = self.import_thread
        if thread is None:
            return

        if len(loaders) > 1:
            loader_names = [MOD_LOADERS.get(l, l) for l in loaders]
            chosen_loader_name, ok = QInputDialog.getItem(
                self, "Выбор загрузчика",
                "Моды требуют разные загрузчики.\nВыберите целевой загрузчик:",
                loader_names, 0, False,
            )
            if not ok or not chosen_loader_name:
                thread.cancel()
                return
            chosen_loader = None
            for lid, lname in MOD_LOADERS.items():
                if lname == chosen_loader_name:
                    chosen_loader = lid
                    break
            if not chosen_loader:
                thread.cancel()
                return
        else:
            chosen_loader = loaders[0] if loaders else None

        if len(versions) > 1:
            chosen_version, ok = QInputDialog.getItem(
                self, "Выбор версии Minecraft",
                "Выберите целевую версию Minecraft:",
                versions, 0, False,
            )
            if not ok or not chosen_version:
                thread.cancel()
                return
        else:
            chosen_version = versions[0] if versions else None

        name, ok = QInputDialog.getText(
            self, "Создание сборки",
            f"Создание сборки {MOD_LOADERS.get(chosen_loader, chosen_loader)} "
            f"{chosen_version}.\nВведите название для этой сборки:",
        )
        if not ok or not name.strip():
            thread.cancel()
            return

        thread.set_user_choice(chosen_version, chosen_loader, name)

    def on_import_finished(self, success, info):
        self.play_button.setEnabled(True)
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
            "loader_version": info.get("loader_version"),
            "path_rel": info["path_rel"],
        }
        self.save_instances()
        self.refresh_instance_list()
        self.log(f"[dotLauncher] Сборка «{info['name']}» добавлена.")

    # ---------- НОВАЯ СБОРКА ----------
    def open_new_instance_dialog(self):
        if self.import_thread and self.import_thread.isRunning():
            QMessageBox.warning(self, "Занято", "Дождитесь завершения импорта.")
            return
        if self.launcher_thread and self.launcher_thread.isRunning():
            QMessageBox.warning(self, "Занято", "Дождитесь завершения запуска.")
            return
        if self.instance_install_thread and self.instance_install_thread.isRunning():
            QMessageBox.warning(self, "Занято", "Идёт создание новой сборки.")
            return

        dlg = NewInstanceDialog(parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        if not dlg.result_data:
            return

        data = dlg.result_data
        self._start_instance_install(
            data["name"], data["version"], data["loader"]
        )

    def _start_instance_install(self, name, version, loader_id):
        java_path = None
        if not self.managed_java_check.isChecked():
            try:
                resolved, _ = self._resolve_java()
                java_path = resolved
            except Exception:
                java_path = None

        existing = set(self.instances.keys())
        if os.path.isdir(self.config["instances_dir"]):
            try:
                existing.update(os.listdir(self.config["instances_dir"]))
            except OSError:
                pass
        instance_id = str(uuid.uuid4())[:8]
        while instance_id in existing:
            instance_id = str(uuid.uuid4())[:8]

        path_rel = os.path.join("instances", instance_id)
        self.instances[instance_id] = {
            "name": name,
            "version": version,
            "loader": loader_id,
            "loader_version": None,
            "path_rel": path_rel,
            "installing": True,
        }
        self.save_instances()
        self.refresh_instance_list()

        self.play_button.setEnabled(False)
        self.new_instance_button.setEnabled(False)
        self.status_bar.showMessage(f"Создание сборки «{name}»...")
        self.log(
            f"[dotLauncher] Создание сборки «{name}»: "
            f"Minecraft {version}, загрузчик "
            f"{MOD_LOADERS.get(loader_id, loader_id)}."
        )

        self.instance_install_thread = InstanceInstallThread(
            self.config["instances_dir"],
            self.config["workspace"],
            instance_id,
            version,
            loader_id,
            name,
            java_path=java_path,
        )
        self.instance_install_thread.log_signal.connect(self.log)
        self.instance_install_thread.status_signal.connect(
            self.status_bar.showMessage
        )
        self.instance_install_thread.finished_signal.connect(
            self.on_instance_install_finished
        )
        self.instance_install_thread.start()

    def on_instance_install_finished(self, success, info, error):
        self.play_button.setEnabled(True)
        self.new_instance_button.setEnabled(True)
        self.status_bar.showMessage("Готов")

        iid = info.get("instance_id") if isinstance(info, dict) else None

        if not success:
            if iid and iid in self.instances:
                del self.instances[iid]
                self.save_instances()
                self.refresh_instance_list()
            self.log(f"[dotLauncher] Создание сборки не завершено: {error}")
            QMessageBox.warning(
                self, "Ошибка",
                f"Не удалось создать сборку:\n{error}"
            )
            return

        self.instances[iid] = {
            "name": info["name"],
            "version": info["version"],
            "loader": info["loader"],
            "loader_version": info.get("loader_version"),
            "path_rel": info["path_rel"],
        }
        self.save_instances()
        self.refresh_instance_list()
        self.log(f"[dotLauncher] Сборка «{info['name']}» создана.")
        QMessageBox.information(
            self, "Готово",
            f"Сборка «{info['name']}» создана."
        )

    # ---------- КОНТЕКСТНОЕ МЕНЮ: СБОРКИ ----------
    def on_instance_context_menu(self, pos):
        item = self.instance_list.itemAt(pos)
        menu = QMenu(self)

        # --- Пустая область списка: только создание/импорт ---
        if item is None:
            act_new = menu.addAction("Новая сборка")
            act_import = menu.addAction("Импорт модпака")
            chosen = menu.exec(self.instance_list.mapToGlobal(pos))
            if chosen is None:
                return
            if chosen == act_new:
                self.open_new_instance_dialog()
            elif chosen == act_import:
                self.import_modpack_dialog()
            return

        instance_id = item.data(Qt.ItemDataRole.UserRole)
        if instance_id not in self.instances:
            return
        inst = self.instances[instance_id]

        # --- Сборка ещё скачивается ---
        if inst.get("installing"):
            act_info = menu.addAction("Скачивается...")
            act_info.setEnabled(False)
            menu.exec(self.instance_list.mapToGlobal(pos))
            return

        launcher_running = (
            self.launcher_thread is not None
            and self.launcher_thread.isRunning()
        )

        # 1. Играть
        act_play = menu.addAction("Играть")
        act_play.setEnabled(not launcher_running)

        # 2. Развернуть / Свернуть
        if self.current_instance == instance_id and self.mods_expanded:
            act_expand = menu.addAction("Свернуть сборку")
        else:
            act_expand = menu.addAction("Развернуть сборку")

        # 3. Открыть папку сборки
        act_folder = menu.addAction("Открыть папку сборки")
        act_screenshots = menu.addAction("Открыть скриншоты")
        
        menu.addSeparator()

        # 4. Удалить
        act_delete = menu.addAction("Удалить сборку")
        act_delete.setEnabled(not launcher_running)

        chosen = menu.exec(self.instance_list.mapToGlobal(pos))
        if chosen is None:
            return

        # Все действия, кроме удаления, требуют, чтобы эта сборка была текущей.
        if chosen in (act_play, act_expand, act_folder):
            self._select_instance_by_id(instance_id)

        if chosen in (act_play, act_expand, act_folder):
            self._select_instance_by_id(instance_id)

        if chosen == act_play:
            self.play_game()
        elif chosen == act_expand:
            self.toggle_expand()
        elif chosen == act_folder:
            self.open_instance_folder()
        elif chosen == act_screenshots:
            self.open_screenshots_folder(instance_id)
        elif chosen == act_delete:
            self._select_instance_by_id(instance_id)
            self.delete_instance()

    def _select_instance_by_id(self, instance_id):
        for i in range(self.instance_list.count()):
            item = self.instance_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == instance_id:
                if self.current_instance != instance_id:
                    self.instance_list.setCurrentItem(item)
                    self.on_instance_selected(item)
                return True
        return False

    # ---------- КОНТЕКСТНОЕ МЕНЮ: МОДЫ ----------
    def on_mods_context_menu(self, pos):
        item = self.mods_list.itemAt(pos)
        if item is None:
            return

        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return

        filename = data.get("filename")
        disabled = data.get("disabled", False)
        if not filename:
            return

        menu = QMenu(self)

        # 1. Включить / Выключить
        if disabled:
            act_toggle = menu.addAction("Включить мод")
        else:
            act_toggle = menu.addAction("Выключить мод")

        # 2. Открыть расположение файла
        act_open = menu.addAction("Открыть расположение файла")

        menu.addSeparator()

        # 3. Удалить
        act_delete = menu.addAction("Удалить мод")

        chosen = menu.exec(self.mods_list.mapToGlobal(pos))
        if chosen is None:
            return

        if chosen == act_toggle:
            row = self.mods_list.row(item)
            self.on_mod_row_clicked(row)
        elif chosen == act_open:
            self.open_mod_location(filename, disabled)
        elif chosen == act_delete:
            self.delete_mod(filename, disabled)

    def open_mod_location(self, filename, disabled):
        if not self.current_instance or self.current_instance not in self.instances:
            return
        inst = self.instances[self.current_instance]
        instance_dir = self._instance_abs_path(inst)
        minecraft_dir = os.path.join(instance_dir, ".minecraft")
        sub = "disabledMods" if disabled else "mods"
        full_path = os.path.join(minecraft_dir, sub, filename)
        if not os.path.isfile(full_path):
            QMessageBox.warning(
                self, "Файл не найден",
                f"Файл мода не найден:\n{full_path}"
            )
            return
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(
                    ["explorer", "/select,", os.path.normpath(full_path)]
                )
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", full_path])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(full_path)])
        except Exception as e:
            QMessageBox.warning(
                self, "Ошибка",
                f"Не удалось открыть папку:\n{e}"
            )

    def delete_mod(self, filename, disabled):
        if not self.current_instance or self.current_instance not in self.instances:
            return
        inst = self.instances[self.current_instance]
        instance_dir = self._instance_abs_path(inst)
        minecraft_dir = os.path.join(instance_dir, ".minecraft")
        sub = "disabledMods" if disabled else "mods"
        full_path = os.path.join(minecraft_dir, sub, filename)
        if not os.path.isfile(full_path):
            QMessageBox.warning(
                self, "Файл не найден",
                f"Файл мода не найден:\n{full_path}"
            )
            return
        reply = QMessageBox.question(
            self, "Удаление мода",
            f"Удалить мод «{filename}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            os.remove(full_path)
            self.log(f"[dotLauncher] Мод {filename} удалён.")
        except Exception as e:
            QMessageBox.warning(
                self, "Ошибка",
                f"Не удалось удалить файл:\n{e}"
            )
            return
        if self.mods_expanded:
            self._populate_mods_list()

    # ---------- СПИСОК СБОРОК ----------
    def refresh_instance_list(self):
        self.instance_list.clear()
        for iid, inst in self.instances.items():
            item = QListWidgetItem(inst["name"])
            item.setData(Qt.ItemDataRole.UserRole, iid)
            if inst.get("installing"):
                item.setText(f"{inst['name']}  [СКАЧИВАЕТСЯ]")
                item.setToolTip("Сборка создаётся, дождитесь завершения.")
                item.setForeground(QColor("#808080"))
                f = item.font()
                f.setItalic(True)
                item.setFont(f)
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
            inst = self.instances[instance_id]
            if inst.get("installing"):
                self.log(
                    f"[Внимание] Сборка «{inst['name']}» ещё создаётся. "
                    f"Подождите завершения."
                )
                self.refresh_instance_list()
                return
            self.current_instance = instance_id
            self.instance_name_label.setText(inst["name"])
            loader_name = MOD_LOADERS.get(inst["loader"], inst["loader"])
            ver_text = f"{loader_name} {inst['version']}"
            if inst.get("loader_version"):
                ver_text += f" (loader {inst['loader_version']})"
            self.instance_version_label.setText(ver_text)
            self.drop_zone.setVisible(False)
            self.instance_info.setVisible(True)
            self.title_label.setVisible(False)
            self.status_bar.showMessage(f"Выбрана сборка: {inst['name']}")

            if self.mods_expanded:
                self._populate_mods_list()

    # ---------- РАЗВОРОТ СБОРКИ / УПРАВЛЕНИЕ МОДАМИ ----------
    def toggle_expand(self):
        if not self.current_instance:
            return
        self.mods_expanded = not self.mods_expanded
        if self.mods_expanded:
            self.mods_list.setVisible(True)
            self._populate_mods_list()
        else:
            self.mods_list.setVisible(False)
            self.mods_list.clear()

    def _populate_mods_list(self):
        self.mods_list.clear()

        if not self.current_instance or self.current_instance not in self.instances:
            return

        inst = self.instances[self.current_instance]
        instance_dir = self._instance_abs_path(inst)
        minecraft_dir = os.path.join(instance_dir, ".minecraft")
        mods_dir = os.path.join(minecraft_dir, "mods")
        disabled_dir = os.path.join(minecraft_dir, "disabledMods")

        entries = []
        if os.path.isdir(mods_dir):
            try:
                for f in os.listdir(mods_dir):
                    if f.lower().endswith(".jar"):
                        entries.append((f, False))
            except OSError:
                pass
        if os.path.isdir(disabled_dir):
            try:
                for f in os.listdir(disabled_dir):
                    if f.lower().endswith(".jar"):
                        entries.append((f, True))
            except OSError:
                pass

        entries.sort(key=lambda e: (e[1], e[0].lower()))

        for fn, is_disabled in entries:
            self._add_mod_item(fn, is_disabled)

        if not entries:
            placeholder = QListWidgetItem("— нет модов —")
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.mods_list.addItem(placeholder)

    def _make_mod_item(self, filename, disabled):
        inst = self.instances[self.current_instance]
        instance_dir = self._instance_abs_path(inst)
        minecraft_dir = os.path.join(instance_dir, ".minecraft")
        sub = "disabledMods" if disabled else "mods"
        full_path = os.path.join(minecraft_dir, sub, filename)

        display_name = None
        if os.path.isfile(full_path):
            try:
                display_name = read_mod_display_name(full_path)
            except Exception:
                display_name = None

        if display_name and display_name != filename:
            text = f"{display_name}  [{filename}]"
        else:
            text = filename

        if disabled:
            text = f"[ВЫКЛ]  {text}"

        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, {
            "filename": filename,
            "disabled": disabled,
        })
        item.setToolTip(
            "Клик — " + ("включить" if disabled else "выключить") + " мод"
        )

        f = item.font()
        f.setItalic(disabled)
        item.setFont(f)
        if disabled:
            item.setForeground(QColor("#808080"))

        return item

    def _add_mod_item(self, filename, disabled):
        item = self._make_mod_item(filename, disabled)
        self.mods_list.addItem(item)

    def on_mod_row_clicked(self, row):
        if not self.current_instance or self.current_instance not in self.instances:
            return
        if row < 0 or row >= self.mods_list.count():
            return

        item = self.mods_list.item(row)
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, dict):
            return

        filename = data.get("filename")
        disabled = data.get("disabled", False)
        if not filename:
            return

        inst = self.instances[self.current_instance]
        instance_dir = self._instance_abs_path(inst)
        minecraft_dir = os.path.join(instance_dir, ".minecraft")
        mods_dir = os.path.join(minecraft_dir, "mods")
        disabled_dir = os.path.join(minecraft_dir, "disabledMods")

        src_dir = disabled_dir if disabled else mods_dir
        dst_dir = mods_dir if disabled else disabled_dir
        src = os.path.join(src_dir, filename)

        if not os.path.isfile(src):
            self.log(f"[Внимание] Файл мода не найден: {src}")
            return

        try:
            os.makedirs(dst_dir, exist_ok=True)
            target_name = filename
            target = os.path.join(dst_dir, target_name)
            if os.path.exists(target):
                base, ext = os.path.splitext(filename)
                i = 1
                while os.path.exists(os.path.join(dst_dir, f"{base}_{i}{ext}")):
                    i += 1
                target_name = f"{base}_{i}{ext}"
                target = os.path.join(dst_dir, target_name)
            shutil.move(src, target)
            state = "выключен" if not disabled else "включён"
            self.log(f"[dotLauncher] Мод {target_name} {state}.")
        except Exception as e:
            self.log(f"[Ошибка] Не удалось переключить мод {filename}: {e}")
            return

        new_disabled = not disabled
        new_item = self._make_mod_item(target_name, new_disabled)
        item.setText(new_item.text())
        item.setData(Qt.ItemDataRole.UserRole, new_item.data(Qt.ItemDataRole.UserRole))
        item.setToolTip(new_item.toolTip())
        item.setFont(new_item.font())
        if new_disabled:
            item.setForeground(QColor("#808080"))
        else:
            item.setForeground(QColor("#000000"))

        self.mods_list.update()

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
        self.mods_expanded = False
        self.mods_list.setVisible(False)
        self.mods_list.clear()
        self.log(f"[dotLauncher] Сборка «{inst['name']}» удалена.")

    def open_instance_folder(self):
        if not self.current_instance:
            QMessageBox.information(
                self, "Нет сборки",
                "Сначала выберите сборку в списке слева."
            )
            return

        inst = self.instances[self.current_instance]
        path = self._instance_abs_path(inst)

        if not os.path.isdir(path):
            QMessageBox.warning(
                self, "Папка не найдена",
                f"Папка сборки не существует:\n{path}"
            )
            return

        try:
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            QMessageBox.warning(
                self, "Ошибка",
                f"Не удалось открыть папку:\n{e}"
            )
    def open_screenshots_folder(self, instance_id=None):
        iid = instance_id or self.current_instance
        if not iid or iid not in self.instances:
            QMessageBox.information(
                self, "Нет сборки",
                "Сначала выберите сборку в списке слева."
            )
            return

        inst = self.instances[iid]
        instance_dir = self._instance_abs_path(inst)
        screenshots_dir = os.path.join(
            instance_dir, ".minecraft", "screenshots"
        )

        if not os.path.isdir(screenshots_dir):
            reply = QMessageBox.question(
                self, "Папка не найдена",
                f"Папки со скриншотами ещё нет:\n{screenshots_dir}\n\n"
                f"Создать её?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            try:
                os.makedirs(screenshots_dir, exist_ok=True)
            except Exception as e:
                QMessageBox.warning(
                    self, "Ошибка",
                    f"Не удалось создать папку:\n{e}"
                )
                return

        try:
            if sys.platform.startswith("win"):
                os.startfile(screenshots_dir)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", screenshots_dir])
            else:
                subprocess.Popen(["xdg-open", screenshots_dir])
        except Exception as e:
            QMessageBox.warning(
                self, "Ошибка",
                f"Не удалось открыть папку:\n{e}"
            )

    # ---------- MODRINTH ----------
    def open_modrinth_window(self):
        if not self.current_instance:
            QMessageBox.information(
                self, "Нет сборки",
                "Сначала выберите сборку в списке слева."
            )
            return
        if self.launcher_thread and self.launcher_thread.isRunning():
            QMessageBox.warning(self, "Занято", "Дождитесь завершения запуска.")
            return
        if self.import_thread and self.import_thread.isRunning():
            QMessageBox.warning(self, "Занято", "Дождитесь завершения импорта.")
            return

        inst = self.instances[self.current_instance]
        instance_dir = self._instance_abs_path(inst)
        mods_dir = os.path.join(instance_dir, ".minecraft", "mods")

        window = ModrinthWindow(
            inst["name"],
            inst["loader"],
            inst["version"],
            mods_dir,
            parent=self,
        )
        window.exec()
        self.log(f"[dotLauncher] Modrinth: окно закрыто для «{inst['name']}».")

        if self.mods_expanded:
            self._populate_mods_list()

    # ---------- ЗАПУСК ИГРЫ ----------
    def play_game(self):
        if not self.current_instance:
            return
        if self.launcher_thread and self.launcher_thread.isRunning():
            return

        inst = self.instances[self.current_instance]
        loader_id = inst["loader"]
        loader_version = inst.get("loader_version")

        if self.account_type.currentIndex() == 0:
            username = self.username_input.text().strip()
            if not username:
                self.log("[Ошибка] Введите никнейм.")
                return
            uuid_val = self._offline_uuid(username)
            token = "0" * 32
            elyby = False
        else:
            if self.config.get("elyby_refresh_token"):
                self.log("[dotLauncher] Обновление сессии Ely.by перед запуском...")
                self._try_refresh_elyby()
                if self.refresh_thread and self.refresh_thread.isRunning():
                    self.refresh_thread.wait(15000)

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

        self.launcher_thread = LauncherThread(
            instance_dir, inst["version"], loader_id, loader_version,
            username, uuid_val, token,
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
        if self.import_thread and self.import_thread.isRunning():
            self.import_thread.cancel()
            if not self.import_thread.wait(5000):
                self.log("[Внимание] Поток импорта не завершился, принудительное завершение.")
                self.import_thread.terminate()
                self.import_thread.wait(2000)

        if self.instance_install_thread and self.instance_install_thread.isRunning():
            self.instance_install_thread.stop()
            if not self.instance_install_thread.wait(5000):
                self.log("[Внимание] Поток создания сборки не завершился, принудительное завершение.")
                self.instance_install_thread.terminate()
                self.instance_install_thread.wait(2000)

        if self.launcher_thread and self.launcher_thread.isRunning():
            if self.launcher_thread.process is None:
                reply = QMessageBox.question(
                    self, "Установка в процессе",
                    "Идёт установка Minecraft/загрузчика/Java.\n"
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
    app.setFont(QFont("Tahoma", 8))
    app.setStyleSheet(build_win98_qss())

    app.setWindowIcon(load_app_icon())

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
