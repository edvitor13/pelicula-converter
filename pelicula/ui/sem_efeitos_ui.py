"""1.7, "Desligar todos os efeitos": o botão da barra da prévia, o Shift+D e a pergunta antes de exportar.

É um estado da sessão (`MainWindow.no_effects`), lido onde a receita do quadro é montada (`frame.Recipe.no_effects`,
`export.ExportSettings.no_effects`). Nada é alterado: nem ajuste, nem chave, nem clipe; sem passo no desfazer, sem
"alterações não salvas" e fora do `.plc`, das preferências e da cópia da recuperação. Abrir outro arquivo ou projeto
religa os efeitos. O que sai da exportação é o que a prévia mostra. ARQUITETURA §40.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from .. import camera, media, sequence
from ..i18n import _


def install(win, bar) -> None:
    """O botão na barra da prévia (`bar`, o layout dela), nos dois modos."""
    b = win._flat("fx_off", _("Desligar todos os efeitos (Shift+D): o look e os ajustes de imagem dos clipes. "
                              "Cortes, enquadramento, opacidade e transições continuam. Ao religar, tudo volta "
                              "como estava. A exportação segue a prévia."), checkable=True)
    b.toggled.connect(lambda off: _toggled(win, off))
    bar.addWidget(b)
    win.btn_no_effects = b


def toggle(win) -> None:
    """O atalho: o mesmo que clicar no botão (sem nada aberto, ele fica desabilitado)."""
    if win.btn_no_effects.isEnabled():
        win.btn_no_effects.toggle()


def reset(win) -> None:
    """Religa os efeitos: outro arquivo ou projeto começa com eles ligados."""
    win.btn_no_effects.setChecked(False)


def read_entrada(win) -> str:
    """O perfil em que o arquivo da prévia é lido: o do look ou, sem efeitos, o do caminho "sem película"."""
    return "rec709" if win.no_effects else win.store.get("entrada")


def _reading(win):
    """O que muda os quadros lidos (obturador, log em float32, perfis dos clipes): diferente = ler de novo."""
    if win.info is None:
        return None
    if win.src_seq is not None:
        return win._shutter(), not win.no_effects and camera.uses_profiles(win.src_seq)
    return win._shutter(), media.float_input(win.info, read_entrada(win))


def _toggled(win, off: bool) -> None:
    before = _reading(win)
    win.no_effects = bool(off)
    win._update_label_proc()
    if win.cur_layers is not None:
        win._compose_current()
    win.render_now()
    if _reading(win) == before:
        return
    if win.playing:  # a reprodução continua de onde está, com o leitor novo
        win.stop_play()
        win.start_play()
    else:
        win.request_frame(win.frame_idx)


def thumbnail_image(win):
    """A miniatura do projeto salvo com os efeitos desligados: o quadro atual como ele sai com os efeitos ligados (o
    `.plc` é o mesmo nos dois estados). Lido de novo, com a leitura e a receita dos efeitos ligados."""
    if win.cur is None:
        return win.viewer.proc
    from .main_window import qimage_from
    win.no_effects = False  # só para montar a receita; sem sinais e sem mexer no botão
    try:
        recipe = win.frame_recipe()
        w, h = win.preview_size()
        if win.src_seq is not None:
            img = win._live_layers(sequence.grab(win.src_seq, win.cur_frame, w, h, 8, shutter=recipe.shutter))
        else:
            img = media.grab_frame(win.info, win.cur_frame, w, h, 8, profile=recipe.profile)
        win._uploaded = None
        return qimage_from(recipe.render(win.engine, img, win.cur_frame))
    except Exception:  # noqa: BLE001
        return win.viewer.proc  # melhor a miniatura do que está na tela do que nenhuma
    finally:
        win.no_effects = True


def confirm_export(win) -> bool:
    """Antes de exportar com os efeitos desligados: True = seguir (sem efeitos ou depois de religar)."""
    if not win.no_effects:
        return True
    box = QMessageBox(win)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(_("Exportar"))
    box.setText(_("Os efeitos estão desligados. O vídeo vai sair sem o look e sem os ajustes de imagem dos clipes."))
    without = box.addButton(_("Exportar sem efeitos"), QMessageBox.ButtonRole.AcceptRole)
    back_on = box.addButton(_("Religar e exportar"), QMessageBox.ButtonRole.ActionRole)
    cancel = box.addButton(_("Cancelar"), QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(without)
    box.setEscapeButton(cancel)
    box.exec()
    clicked = box.clickedButton()
    if clicked is back_on:
        reset(win)
    return clicked is without or clicked is back_on
