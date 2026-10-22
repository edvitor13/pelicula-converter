"""Notificações do sistema na tela (Qt, só na thread principal).

`pelicula/notify.py` decide *se* e *como* avisar (sem Qt); aqui o aviso aparece, por um backend:

| Sistema | Backend | Se não houver |
|---|---|---|
| Windows | `TrayBackend`: `QSystemTrayIcon.showMessage` (toast do Windows 10/11); clicar dispara `messageClicked` | nada (sem bandeja) |
| Linux | `DBusBackend`: `org.freedesktop.Notifications` pelo `PySide6.QtDBus`, com a ação "default" (sinal `ActionInvoked`) e o ícone do app | `TrayBackend` (bandeja do sistema); sem nenhum dos dois, nada |

Nenhum backend derruba o app: qualquer falha vira "não mostrou" e a janela segue (o ícone ainda pisca
na barra de tarefas com `QApplication.alert`, se ligado). Som: `QApplication.beep()` — no Windows o
"Aviso padrão" do esquema de sons do sistema (MessageBeep), no X11 o sinal sonoro do servidor —, sem
arquivo de som nem biblioteca nova; no Linux com D-Bus, o próprio servidor toca o som do tema
(`sound-name` = `message-new-instant`, da especificação de nomes de sons do freedesktop).

O ícone da bandeja só aparece enquanto um aviso está na tela (some depois de `TrayBackend.HIDE_AFTER_MS`).

A `MainWindow` cria um `Notifier` com o `NullBackend` (não mostra nada): testes e automações nunca
mostram notificações de verdade. Só o `app.main()` liga o backend do sistema (`system_backend`).
"""

from __future__ import annotations

import os
import sys
from typing import Callable

from PySide6.QtCore import QObject, Qt, QTimer, Slot
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from .. import APP_NAME, modules, notify, system
from ..i18n import _

MODULE = "notificacoes"


# ------------------------------------------------------------------ backends
class Backend:
    """Mostra uma notificação. `show` devolve (mostrou, tocou_som); um clique chama `on_click(token)`."""

    name = "nenhum"

    def __init__(self):
        self.on_click: Callable[[int | None], None] | None = None

    def show(self, token: int, title: str, body: str, sound: bool) -> tuple[bool, bool]:
        return False, False

    def close(self) -> None:
        pass

    def _clicked(self, token: int | None) -> None:
        if self.on_click is not None:
            self.on_click(token)


class NullBackend(Backend):
    """Não mostra nada (padrão da janela; testes e automações)."""


class TrayBackend(Backend):
    """Ícone na bandeja do sistema + `showMessage` (toast no Windows 10/11, balão nos outros)."""

    name = "bandeja"
    HIDE_AFTER_MS = 20000
    SHOW_MS = 8000

    def __init__(self, icon: QIcon | None = None, parent: QObject | None = None):
        super().__init__()
        self._icon = icon
        self._parent = parent
        self._tray: QSystemTrayIcon | None = None
        self._last: int | None = None
        self._hide = QTimer(parent)
        self._hide.setSingleShot(True)
        self._hide.setInterval(self.HIDE_AFTER_MS)
        self._hide.timeout.connect(self._hide_icon)

    @staticmethod
    def available() -> bool:
        try:
            return QSystemTrayIcon.isSystemTrayAvailable() and QSystemTrayIcon.supportsMessages()
        except Exception:  # noqa: BLE001
            return False

    def _make(self) -> QSystemTrayIcon:
        if self._tray is None:
            from . import icons
            icon = self._icon if self._icon is not None else icons.app_icon()
            self._tray = QSystemTrayIcon(icon, self._parent)
            self._tray.setToolTip(APP_NAME)
            self._tray.messageClicked.connect(lambda: self._clicked(self._last))
            self._tray.activated.connect(self._activated)
        return self._tray

    def _activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._clicked(self._last)

    def show(self, token: int, title: str, body: str, sound: bool) -> tuple[bool, bool]:
        if not self.available():
            return False, False
        try:
            tray = self._make()
            tray.show()
            tray.showMessage(title, body, tray.icon(), self.SHOW_MS)
        except Exception:  # noqa: BLE001
            return False, False
        self._last = token
        self._hide.start()
        return True, False

    def _hide_icon(self) -> None:
        if self._tray is not None:
            self._tray.hide()

    def close(self) -> None:
        self._hide.stop()
        if self._tray is not None:
            self._tray.hide()
            self._tray.deleteLater()
            self._tray = None


class DBusBackend(QObject, Backend):
    """`org.freedesktop.Notifications` (Linux) pelo QtDBus.

    O `Notify` precisa de `replaces_id` como `uint32` (servidores como o do GNOME conferem a assinatura
    `susssasa{sv}i`). O PySide6 converte `int` do Python para `int32`, então a chamada passa pelo
    meta-objeto do `QDBusInterface` (montado pela introspecção do serviço) com `QMetaObject.invokeMethod`
    e argumentos tipados (`Q_ARG("uint", 0)`): o QtDBus monta a mensagem com os tipos certos.
    """

    name = "dbus"
    SERVICE = "org.freedesktop.Notifications"
    PATH = "/org/freedesktop/Notifications"
    TIMEOUT_MS = 2000

    def __init__(self, icon: str = "", parent: QObject | None = None, iface: QObject | None = None):
        """`iface`: um objeto com o método `Notify` já pronto (testes: um servidor falso, sem D-Bus)."""
        QObject.__init__(self, parent)
        Backend.__init__(self)
        self.icon = icon
        self._iface = iface
        self._failed = False
        self._ids: dict[int, int] = {}  # id da notificação no servidor → token

    def _interface(self):
        if self._iface is not None or self._failed:
            return self._iface
        try:
            from PySide6.QtCore import SLOT
            from PySide6.QtDBus import QDBusConnection, QDBusInterface
            bus = QDBusConnection.sessionBus()
            if not bus.isConnected():
                raise RuntimeError("sem barramento de sessão")
            names = bus.interface()
            known = names.isServiceRegistered(self.SERVICE)
            if not (known.isValid() and known.value()):
                act = names.activatableServiceNames()
                if not (act.isValid() and self.SERVICE in (act.value() or [])):
                    raise RuntimeError("sem serviço de notificações")
            iface = QDBusInterface(self.SERVICE, self.PATH, self.SERVICE, bus)
            if not iface.isValid():
                raise RuntimeError(iface.lastError().message())
            iface.setTimeout(self.TIMEOUT_MS)
            bus.connect(self.SERVICE, self.PATH, self.SERVICE, "ActionInvoked", self,
                        SLOT("_action_invoked(uint,QString)"))
            bus.connect(self.SERVICE, self.PATH, self.SERVICE, "NotificationClosed", self,
                        SLOT("_notification_closed(uint,uint)"))
            self._iface = iface
        except Exception:  # noqa: BLE001 — sem D-Bus: quem chamou cai no próximo backend
            self._failed = True
            self._iface = None
        return self._iface

    def available(self) -> bool:
        return self._interface() is not None

    def show(self, token: int, title: str, body: str, sound: bool) -> tuple[bool, bool]:
        iface = self._interface()
        if iface is None:
            return False, False
        try:
            from PySide6.QtCore import Q_ARG, Q_RETURN_ARG, QMetaObject
            hints = {"desktop-entry": "pelicula-converter"}
            if sound:
                hints["sound-name"] = "message-new-instant"
            else:
                hints["suppress-sound"] = True
            nid = QMetaObject.invokeMethod(
                iface, "Notify", Qt.ConnectionType.DirectConnection, Q_RETURN_ARG("uint"),
                Q_ARG("QString", APP_NAME), Q_ARG("uint", 0), Q_ARG("QString", self.icon),
                Q_ARG("QString", title), Q_ARG("QString", body),
                Q_ARG("QStringList", ["default", _("Abrir")]), Q_ARG("QVariantMap", hints), Q_ARG("int", -1))
        except Exception:  # noqa: BLE001
            return False, False
        if not nid:
            return False, False
        self._ids[int(nid)] = token
        if len(self._ids) > 200:
            for old in list(self._ids)[:100]:
                self._ids.pop(old, None)
        return True, sound

    @Slot("uint", str)
    def _action_invoked(self, nid, _key) -> None:
        token = self._ids.get(int(nid))
        if token is not None:
            self._clicked(token)

    @Slot("uint", "uint")
    def _notification_closed(self, nid, _reason) -> None:
        self._ids.pop(int(nid), None)


class ChainBackend(Backend):
    """Tenta cada backend em ordem até um mostrar a notificação."""

    def __init__(self, backends: list[Backend]):
        super().__init__()
        self.backends = list(backends)
        for b in self.backends:
            b.on_click = self._clicked
        self.name = "+".join(b.name for b in self.backends)

    def show(self, token: int, title: str, body: str, sound: bool) -> tuple[bool, bool]:
        for b in self.backends:
            shown, played = b.show(token, title, body, sound)
            if shown:
                return shown, played
        return False, False

    def close(self) -> None:
        for b in self.backends:
            b.close()


def _icon_path() -> str:
    from . import icons
    for name in ("logo-256.png", "logo-512.png"):
        p = icons.assets_dir() / name
        if p.is_file():
            return str(p)
    return "pelicula-converter"  # nome do ícone instalado pelo .deb


def system_backend(parent: QObject | None = None) -> Backend:
    """O backend deste sistema (veja a tabela no topo do arquivo)."""
    if sys.platform.startswith("linux"):
        return ChainBackend([DBusBackend(_icon_path(), parent), TrayBackend(parent=parent)])
    return TrayBackend(parent=parent)


# ------------------------------------------------------------------ notificador
class Notifier(QObject):
    """Avisa eventos da janela (`notify(Notice)`) conforme o módulo e as preferências.

    `actions`: destinos de clique que não são arquivos (`notify.ACTION_*` → função da janela).
    `open_file`/`open_folder` são substituíveis nos testes (por padrão `system.reveal`/`system.open_path`).
    """

    HISTORY = 50

    def __init__(self, window=None, settings=None, backend: Backend | None = None):
        super().__init__(window)
        self.window = window
        self.settings = settings if settings is not None else getattr(window, "settings", None)
        self.backend: Backend = NullBackend()
        self.actions: dict[str, Callable[[], None]] = {}
        self.open_file: Callable[[str], None] = system.reveal
        self.open_folder: Callable[[str], None] = system.open_path
        self.beep: Callable[[], None] = QApplication.beep        # testes: substituídos (nada toca nem pisca)
        self.alert: Callable[[object], None] = QApplication.alert
        self.focus_override: bool | None = None  # testes: força "janela em foco" ou não
        self.history: list[tuple[notify.Notice, notify.Decision, bool]] = []
        self._notices: dict[int, notify.Notice] = {}
        self._token = 0
        self._batch: list[notify.Finished] = []
        self.set_backend(backend or NullBackend())

    # ------------------------------------------------------------ backend
    def set_backend(self, backend: Backend) -> None:
        old = self.backend
        if old is not backend:
            old.on_click = None
            old.close()
        self.backend = backend
        backend.on_click = self.activate

    def close(self) -> None:
        self.backend.close()

    # ------------------------------------------------------------ estado
    def module_on(self) -> bool:
        return modules.is_enabled(self.settings, MODULE)

    def is_focused(self) -> bool:
        if self.focus_override is not None:
            return self.focus_override
        if QGuiApplication.applicationState() != Qt.ApplicationState.ApplicationActive:
            return False
        w = self.window
        return not (w is not None and w.isMinimized())

    # ------------------------------------------------------------ avisar
    def notify(self, notice: notify.Notice, test: bool = False) -> notify.Decision:
        """Mostra (ou não) um aviso. Devolve a decisão tomada."""
        d = notify.decide(notice.kind, self.module_on(), self.is_focused(), notify.load(self.settings), test=test)
        shown = played = False
        if d.show:
            self._token += 1
            self._notices[self._token] = notice
            if len(self._notices) > self.HISTORY:
                self._notices.pop(next(iter(self._notices)))
            try:
                shown, played = self.backend.show(self._token, notice.title, notice.body, d.sound)
            except Exception:  # noqa: BLE001 — um backend com defeito nunca derruba a janela
                shown = played = False
        try:
            if d.sound and not played:
                self.beep()
            if d.flash and self.window is not None:
                self.alert(self.window)
        except Exception:  # noqa: BLE001
            pass
        self.history.append((notice, d, shown))
        del self.history[:-self.HISTORY]
        return d

    def test(self) -> bool:
        """Botão "Testar notificação": mostra um aviso agora (ignora o foco e os tipos). True se apareceu."""
        self.notify(notify.sample_notice(), test=True)
        return bool(self.history and self.history[-1][2])

    # ------------------------------------------------------------ clique
    def activate(self, token: int | None) -> None:
        """Clique na notificação: mostra o arquivo na pasta, abre a pasta ou a janela certa."""
        notice = self._notices.get(token) if token is not None else None
        self.raise_window()
        if notice is None:
            return
        target = notice.target
        if target:
            try:
                if os.path.isdir(target):
                    self.open_folder(target)
                elif os.path.exists(target):
                    self.open_file(target)
                elif os.path.isdir(os.path.dirname(target)):
                    self.open_folder(os.path.dirname(target))
            except Exception:  # noqa: BLE001
                pass
            return
        fn = self.actions.get(notice.action)
        if fn is not None:
            fn()

    def raise_window(self) -> None:
        w = self.window
        if w is None:
            return
        if w.isMinimized():
            w.showNormal()
        w.raise_()
        w.activateWindow()

    # ------------------------------------------------------------ eventos
    def export_progress(self, new: list[notify.Finished], idle: bool) -> list[notify.Notice]:
        """Fila de exportação: `new` terminou agora; `idle` = nada mais esperando ou exportando."""
        self._batch += list(new)
        notices = notify.queue_notices(new, list(self._batch), idle)
        if idle:
            self._batch = []
        for n in notices:
            self.notify(n)
        return notices

    def watch_jobs(self, bridge) -> None:
        """Downloads de componentes pela fila de tarefas (`ui/job_bridge.bridge()`)."""
        bridge.finished.connect(self._job_finished)

    def _job_finished(self, job) -> None:
        from .. import jobs, tools
        data = job.data or {}
        if not str(getattr(job, "key", "")).startswith("componente:") or data.get("acao") != "baixar":
            return
        try:
            name = _(tools.get(str(data.get("tool"))).name)
        except KeyError:
            name = str(data.get("tool") or "")
        if job.state == jobs.CONCLUIDO:
            self.notify(notify.component_done(name))
        elif job.state == jobs.ERRO:
            self.notify(notify.component_failed(name, job.error or ""))


def for_window(window) -> Notifier:
    """O notificador da janela principal, com os destinos de clique ligados aos métodos dela."""
    n = Notifier(window, window.settings)
    n.actions.update({
        notify.ACTION_QUEUE: window.show_queue,
        notify.ACTION_COMPONENTS: lambda: window.show_settings("componentes"),
        notify.ACTION_UPDATE: lambda: window.show_update(getattr(window, "_release", None)),
    })
    try:
        from .job_bridge import bridge
        n.watch_jobs(bridge())
    except Exception:  # noqa: BLE001
        pass
    return n
