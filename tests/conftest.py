"""Shared pytest fixtures.

Stubs the ``qgis`` package so the plugin's modules can be imported without a
running QGIS instance. The stub reproduces the real ``qgis.PyQt`` shim
behavior on Qt6: it re-exports ``QAction``, ``QActionGroup`` and ``QShortcut``
from ``PyQt6.QtGui`` under ``qgis.PyQt.QtWidgets`` (they moved out of
``QtWidgets`` in Qt6).
"""

import sys
import types
from unittest.mock import MagicMock

import PyQt6.QtCore
import PyQt6.QtGui
import PyQt6.QtNetwork
import PyQt6.QtWidgets


def _install_qgis_stub() -> None:
    qgis = types.ModuleType("qgis")
    qgis.__path__ = []
    sys.modules["qgis"] = qgis

    qgis_pyqt = types.ModuleType("qgis.PyQt")
    qgis_pyqt.__path__ = []
    sys.modules["qgis.PyQt"] = qgis_pyqt
    qgis.PyQt = qgis_pyqt

    pyqt_submodules = {
        "QtCore": PyQt6.QtCore,
        "QtGui": PyQt6.QtGui,
        "QtNetwork": PyQt6.QtNetwork,
        "QtWidgets": PyQt6.QtWidgets,
    }
    for name, real in pyqt_submodules.items():
        alias = types.ModuleType(f"qgis.PyQt.{name}")
        for attr in dir(real):
            if not attr.startswith("_"):
                setattr(alias, attr, getattr(real, attr))
        sys.modules[f"qgis.PyQt.{name}"] = alias
        setattr(qgis_pyqt, name, alias)

    # Qt6: QAction, QActionGroup, and QShortcut live in QtGui. The real
    # qgis.PyQt.QtWidgets shim re-exports them, so mirror that here.
    qtwidgets_alias = sys.modules["qgis.PyQt.QtWidgets"]
    for attr in ("QAction", "QActionGroup", "QShortcut"):
        setattr(qtwidgets_alias, attr, getattr(PyQt6.QtGui, attr))

    for submodule in ("QtSvg", "QtWebEngineWidgets"):
        alias = MagicMock()
        sys.modules[f"qgis.PyQt.{submodule}"] = alias
        setattr(qgis_pyqt, submodule, alias)

    class _AutoTypeMeta(type):
        """Metaclass that auto-creates nested classes on attribute access.

        Lets ``Qgis.MessageLevel.Info`` resolve at import time without needing
        a real QGIS install: each access materializes a real ``type``.
        """

        def __getattr__(cls, name):
            if name.startswith("__"):
                raise AttributeError(name)
            cache = cls.__dict__.get("_auto_cache")
            if cache is None:
                cache = {}
                type.__setattr__(cls, "_auto_cache", cache)
            sub = cache.get(name)
            if sub is None:
                sub = _AutoTypeMeta(name, (), {})
                cache[name] = sub
            return sub

    class _AutoTypeModule(types.ModuleType):
        """qgis.core/gui/utils stub that auto-creates real classes on attribute access.

        ``pyqtSignal(QgsRectangle)`` and ``class X(QgsMapToolEmitPoint)`` both
        need real type objects (not MagicMock) at import time, so every access
        materializes a brand-new ``type`` and caches it.
        """

        def __init__(self, fullname: str) -> None:
            super().__init__(fullname)
            self.__spec__ = None
            self._cache: dict = {}

        def __getattr__(self, name: str):
            if name.startswith("__"):
                raise AttributeError(name)
            cached = self._cache.get(name)
            if cached is None:
                cached = _AutoTypeMeta(name, (), {})
                self._cache[name] = cached
            return cached

    for name in ("core", "gui", "utils"):
        stub = _AutoTypeModule(f"qgis.{name}")
        sys.modules[f"qgis.{name}"] = stub
        setattr(qgis, name, stub)


_install_qgis_stub()
