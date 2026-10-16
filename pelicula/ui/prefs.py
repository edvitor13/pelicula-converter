"""Onde ficam as preferências do app (idioma, sessão, recentes, opções de exportação).

Por padrão, no lugar nativo do sistema (registro do Windows, ~/.config no Linux). Se a
variável PELICULA_SETTINGS_DIR estiver definida — modo portátil ou testes automatizados —
tudo vai para um arquivo .ini nessa pasta, sem tocar no registro.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QSettings

from .. import APP_NAME


def settings() -> QSettings:
    folder = os.environ.get("PELICULA_SETTINGS_DIR")
    if folder:
        os.makedirs(folder, exist_ok=True)
        return QSettings(os.path.join(folder, f"{APP_NAME}.ini"), QSettings.Format.IniFormat)
    return QSettings(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, APP_NAME, APP_NAME)
