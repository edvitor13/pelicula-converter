"""Pastas do painel de mídia do modo Edição (sem Qt, sem GPU e sem `timeline`).

Só organização: uma pasta tem nome, cor e (opcionalmente) uma pasta-mãe, e guarda itens da Mídia por chave (o
caminho da fonte, que é o id em `Sequence.sources`; outro tipo de item, como uma sequência, pode entrar depois
com a sua chave). Nada aqui toca arquivos do disco nem a imagem ou o som: o render não consulta este módulo.

- `Folders`: as pastas e a pasta de cada item. Ids `p1`, `p2`… vêm de um contador do próprio objeto
  (determinístico; nunca aleatório nem do relógio). Item que não está em nenhuma pasta está na raiz.
- Cor: `""` (a cor padrão do app), o id de uma cor da paleta `PALETTE` (as mesmas dos marcadores,
  `timeline.MARKER_COLORS`; a conferência está em `tests/test_pastas.py`) ou um hexadecimal `#rrggbb`.
- JSON (`to_json`/`from_json`, o bloco `"pastas"` do bloco `"edicao"`): `{"lista": [{id, nome, cor, pai}],
  "midia": {chave: id da pasta}}`. `from_json` tolera dados quebrados: mãe desconhecida vai para a raiz, ciclos
  são desfeitos, chaves desconhecidas somem.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

PALETTE = ("laranja", "vermelho", "amarelo", "verde", "ciano", "azul", "roxo", "rosa")  # = timeline.MARKER_COLORS
NAME_MAX = 120
DEFAULT_NAME = "Pasta"
ROOT = ""   # id da "pasta" raiz
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def clean_color(color: Any) -> str:
    """A cor normalizada: id da paleta, `#rrggbb` em minúsculas ou "" (padrão) se não vale."""
    c = str(color or "").strip()
    if c in PALETTE:
        return c
    if _HEX.match(c):
        return c.lower()
    return ""


def clean_name(name: Any) -> str:
    return " ".join(str(name or "").split())[:NAME_MAX]


@dataclass
class Folder:
    id: str
    name: str
    color: str = ""
    parent: str = ROOT

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "nome": self.name, "cor": self.color, "pai": self.parent}


class Folders:
    """As pastas do painel de mídia e o que há em cada uma."""

    def __init__(self) -> None:
        self.folders: dict[str, Folder] = {}   # na ordem de criação
        self.items: dict[str, str] = {}        # chave do item → id da pasta (fora daqui = raiz)
        self._next = 1

    # ------------------------------------------------------------ consulta
    def __bool__(self) -> bool:
        return bool(self.folders)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Folders) and self.to_json() == other.to_json()

    __hash__ = None  # type: ignore[assignment]

    def has_folders(self) -> bool:
        return bool(self.folders)

    def get(self, fid: str) -> Folder | None:
        return self.folders.get(fid)

    def children(self, parent: str = ROOT) -> list[Folder]:
        """As subpastas diretas, na ordem de criação."""
        return [f for f in self.folders.values() if f.parent == parent]

    def items_in(self, fid: str = ROOT) -> list[str]:
        """Os itens que estão direto nesta pasta (ou na raiz, se `fid` é ""), na ordem em que entraram."""
        return [k for k, f in self.items.items() if f == fid]

    def folder_of(self, key: str) -> str:
        return self.items.get(key, ROOT)

    def ancestors(self, fid: str) -> list[str]:
        """Do pai até a pasta de cima (sem a raiz)."""
        out: list[str] = []
        f = self.folders.get(fid)
        while f is not None and f.parent and f.parent not in out and len(out) <= len(self.folders):
            out.append(f.parent)
            f = self.folders.get(f.parent)
        return out

    def descendants(self, fid: str) -> list[str]:
        """Todas as subpastas, de qualquer nível (sem a própria)."""
        out: list[str] = []
        todo = [fid]
        while todo:
            cur = todo.pop(0)
            for ch in self.children(cur):
                if ch.id not in out:
                    out.append(ch.id)
                    todo.append(ch.id)
        return out

    def path_of(self, fid: str) -> list[str]:
        """Os nomes da raiz até a pasta (o "caminho" dela)."""
        chain = [*reversed(self.ancestors(fid)), fid]
        return [self.folders[i].name for i in chain if i in self.folders]

    def items_under(self, fid: str) -> list[str]:
        """Os itens da pasta e de todas as subpastas dela."""
        ids = {fid, *self.descendants(fid)}
        return [k for k, f in self.items.items() if f in ids]

    # ------------------------------------------------------------ edição (cada uma devolve se mudou algo)
    def _new_id(self) -> str:
        while f"p{self._next}" in self.folders:
            self._next += 1
        fid = f"p{self._next}"
        self._next += 1
        return fid

    def create(self, name: str = DEFAULT_NAME, parent: str = ROOT, color: str = "") -> Folder:
        """Pasta nova (dentro de `parent`, que se não existe vira a raiz)."""
        f = Folder(self._new_id(), clean_name(name) or DEFAULT_NAME, clean_color(color),
                   parent if parent in self.folders else ROOT)
        self.folders[f.id] = f
        return f

    def rename(self, fid: str, name: str) -> bool:
        f, new = self.folders.get(fid), clean_name(name)
        if f is None or not new or new == f.name:
            return False
        f.name = new
        return True

    def set_color(self, fid: str, color: str) -> bool:
        f, new = self.folders.get(fid), clean_color(color)
        if f is None or new == f.color:
            return False
        f.color = new
        return True

    def move(self, fid: str, parent: str) -> bool:
        """Muda a pasta de mãe. Recusa (False) uma pasta dentro dela mesma ou de uma subpasta (ciclo), uma mãe
        que não existe e não mudar nada."""
        f = self.folders.get(fid)
        if f is None or parent == f.parent or (parent and parent not in self.folders):
            return False
        if parent == fid or parent in self.descendants(fid):
            return False
        f.parent = parent
        return True

    def delete(self, fid: str, to_root: bool = False) -> bool:
        """Apaga a pasta. As subpastas e os itens dela sobem para a pasta-mãe (ou, com `to_root`, vão para a
        raiz). Não apaga nenhum item da Mídia."""
        f = self.folders.pop(fid, None)
        if f is None:
            return False
        up = ROOT if to_root else f.parent
        for ch in self.folders.values():
            if ch.parent == fid:
                ch.parent = up
        for k, where in list(self.items.items()):
            if where == fid:
                self._put(k, up)
        return True

    def _put(self, key: str, fid: str) -> None:
        if fid:
            self.items[key] = fid
        else:
            self.items.pop(key, None)

    def assign(self, keys: Iterable[str], fid: str) -> bool:
        """Põe os itens na pasta (`fid` "" = raiz). Pasta que não existe: nada muda."""
        if fid and fid not in self.folders:
            return False
        changed = False
        for k in keys:
            k = str(k)
            if k and self.items.get(k, ROOT) != fid:
                if fid:
                    self.items.pop(k, None)  # volta ao fim da ordem de entrada na pasta nova
                self._put(k, fid)
                changed = True
        return changed

    def unassign(self, key: str) -> bool:
        """Tira o item de qualquer pasta (ele volta para a raiz)."""
        return self.items.pop(key, None) is not None

    def rename_item(self, old: str, new: str) -> None:
        """O item mudou de chave (arquivo reencontrado em outro caminho): a pasta continua a mesma."""
        if old != new and old in self.items:
            where = self.items.pop(old)
            self.items.setdefault(new, where)

    def keep_items(self, valid: Iterable[str]) -> None:
        """Esquece os itens que não existem mais (chave fora de `valid`)."""
        ok = set(valid)
        for k in [k for k in self.items if k not in ok]:
            del self.items[k]

    # ------------------------------------------------------------ JSON
    def to_json(self) -> dict[str, Any]:
        return {"lista": [f.to_json() for f in self.folders.values()], "midia": dict(self.items)}

    @classmethod
    def from_json(cls, d: Any) -> "Folders":
        out = cls()
        if not isinstance(d, dict):
            return out
        for fd in d.get("lista") if isinstance(d.get("lista"), list) else []:
            if not isinstance(fd, dict):
                continue
            fid = fd.get("id")
            if not isinstance(fid, str) or not fid or fid in out.folders:
                continue
            pai = fd.get("pai")
            out.folders[fid] = Folder(fid, clean_name(fd.get("nome")) or DEFAULT_NAME, clean_color(fd.get("cor")),
                                      pai if isinstance(pai, str) else ROOT)
        for f in out.folders.values():   # mãe desconhecida: raiz
            if f.parent and (f.parent not in out.folders or f.parent == f.id):
                f.parent = ROOT
        for f in out.folders.values():   # ciclos: quem fecha o ciclo vai para a raiz
            seen = {f.id}
            cur = f
            while cur.parent:
                if cur.parent in seen:
                    cur.parent = ROOT
                    break
                seen.add(cur.parent)
                cur = out.folders[cur.parent]
        mid = d.get("midia")
        for k, fid in (mid.items() if isinstance(mid, dict) else []):
            if isinstance(k, str) and k and isinstance(fid, str) and fid in out.folders:
                out.items[k] = fid
        nums = [int(i[1:]) for i in out.folders if re.fullmatch(r"p\d+", i)]
        out._next = max(nums, default=0) + 1
        return out

    def copy(self) -> "Folders":
        return Folders.from_json(self.to_json())
