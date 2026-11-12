# -*- mode: python ; coding: utf-8 -*-
# onefile 模式：所有文件打包进单个 exe
#   upx=False — UPX 运行时解压会显著拖慢启动
#   排除所有未使用的 Qt 模块 — 减小体积

from PyInstaller.building.datastruct import Tree
from PyInstaller.depend.bindepend import resolve_library_path
from pathlib import Path
import os
import sys

if sys.platform == 'win32':
    usb_library = str(Path(SPECPATH) / 'libusb-1.0.dll')
elif sys.platform.startswith('linux'):
    usb_library = resolve_library_path('libusb-1.0.so.0')
else:
    raise SystemExit('Packaging is supported on Windows and Linux only.')
if not usb_library or not Path(usb_library).is_file():
    raise SystemExit('libusb not found: Windows needs libusb-1.0.dll in the project root; '
                     'Linux needs the libusb-1.0-0 system package.')

liangzhi_assets = Path('docs/良质关节驱动协议手册/图片和附件')

a = Analysis(
    ['cangui.py'],
    pathex=[],
    binaries=[
        (usb_library, '.'),
    ],
    datas=[
        ('cangui/logo.svg', 'cangui'),
        ('cangui/check.svg', 'cangui'),
        ('cangui/close.svg', 'cangui'),
        ('cangui/close_hover.svg', 'cangui'),
        ('cangui/arrow_down.svg', 'cangui'),
        ('cangui/arrow_down_dark.svg', 'cangui'),
        ('cangui/logo.ico', 'cangui'),
        *((str(path), liangzhi_assets.as_posix())
          for pattern in ('endpoint*.json', 'ds402.eds')
          for path in (Path(SPECPATH) / liangzhi_assets).glob(pattern)),
    ],
    hiddenimports=[
        'usb.backend.libusb1',
        'PySide6.QtXml',
        # boot_upgrade 插件 (动态导入，PyInstaller 无法自动检测)
        'plugins',
        'plugins.boot_upgrade',
        'plugins.boot_upgrade.plugin',
        'plugins.boot_upgrade.protocol',
        'plugins.boot_upgrade.upgrader',
        'plugins.boot_upgrade.widget',
        # power_monitor 插件
        'plugins.power_monitor',
        'plugins.power_monitor.plugin',
        'plugins.power_monitor.protocol',
        'plugins.power_monitor.widget',
        # juxie_motor 插件
        'plugins.juxie_motor',
        'plugins.juxie_motor.plugin',
        'plugins.juxie_motor.protocol',
        'plugins.juxie_motor.widget',
        'plugins.liangzhi_motor',
        'plugins.liangzhi_motor.plugin',
        'plugins.liangzhi_motor.faults',
        'plugins.liangzhi_motor.protocol',
        'plugins.liangzhi_motor.widget',
        # torque_sensor 插件
        'plugins.torque_sensor',
        'plugins.torque_sensor.plugin',
        'plugins.torque_sensor.protocol',
        'plugins.torque_sensor.scope',
        'plugins.torque_sensor.setid',
        'plugins.torque_sensor.widget',
        # battery_monitor 插件
        'plugins.battery_monitor',
        'plugins.battery_monitor.plugin',
        'plugins.battery_monitor.protocol',
        'plugins.battery_monitor.widget',
        # keli_torque 插件
        'plugins.keli_torque',
        'plugins.keli_torque.plugin',
        'plugins.keli_torque.protocol',
        'plugins.keli_torque.scope',
        'plugins.keli_torque.widget',
        # fill_light 插件
        'plugins.fill_light',
        'plugins.fill_light.plugin',
        'plugins.fill_light.protocol',
        'plugins.fill_light.widget',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PySide6.Qt3DAnimation',
        'PySide6.Qt3DCore',
        'PySide6.Qt3DExtras',
        'PySide6.Qt3DInput',
        'PySide6.Qt3DLogic',
        'PySide6.Qt3DRender',
        'PySide6.QtBluetooth',
        'PySide6.QtCharts',
        'PySide6.QtConcurrent',
        'PySide6.QtDBus',
        'PySide6.QtDataVisualization',
        'PySide6.QtDesigner',
        'PySide6.QtGraphs',
        'PySide6.QtGraphsWidgets',
        'PySide6.QtHelp',
        'PySide6.QtHttpServer',
        'PySide6.QtLocation',
        'PySide6.QtMultimedia',
        'PySide6.QtMultimediaWidgets',
        'PySide6.QtNetwork',
        'PySide6.QtNetworkAuth',
        'PySide6.QtNfc',
        'PySide6.QtOpenGL',
        'PySide6.QtOpenGLWidgets',
        'PySide6.QtPdf',
        'PySide6.QtPdfWidgets',
        'PySide6.QtPositioning',
        'PySide6.QtQml',
        'PySide6.QtQuick',
        'PySide6.QtQuick3D',
        'PySide6.QtQuickControls2',
        'PySide6.QtQuickTest',
        'PySide6.QtQuickWidgets',
        'PySide6.QtRemoteObjects',
        'PySide6.QtScxml',
        'PySide6.QtSensors',
        'PySide6.QtSerialBus',
        'PySide6.QtSerialPort',
        'PySide6.QtSpatialAudio',
        'PySide6.QtSql',
        'PySide6.QtStateMachine',
        'PySide6.QtTest',
        'PySide6.QtTextToSpeech',
        'PySide6.QtUiTools',
        'PySide6.QtWebChannel',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineQuick',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebSockets',
        'PySide6.QtWebView',
        'tkinter',
        'unittest',
        'pydoc',
        'doctest',
        'pdb',
        'lib2to3',
        'distutils',
    ],
    noarchive=False,
    optimize=0,
)
if sys.platform == 'win32':
    # Qt uses Windows' unversioned ICU API. An unrelated ICU on PATH (e.g.
    # Poppler's versioned ICU) can be picked up by dependency analysis and
    # break QtWidgets at startup. Keep these OS libraries out of the bundle.
    system32 = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32'
    system_icu = {'icu.dll', 'icuuc.dll', 'icuin.dll'}
    a.binaries = [entry for entry in a.binaries
                  if not (Path(entry[0]).name.lower() in system_icu
                          and (system32 / Path(entry[0]).name).is_file())]

# 插件目录：Tree 递归收集所有文件，排除 __pycache__
a.datas += Tree('plugins', prefix='plugins', excludes=['__pycache__'])
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    exclude_binaries=False,       # onefile：打包所有二进制文件
    name='CANable2.5',
    debug=False,
    bootloader_ignore_signals=False,
    strip=sys.platform != 'win32',
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['cangui/logo.ico'] if sys.platform == 'win32' else None,
)
