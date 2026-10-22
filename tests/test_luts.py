"""LUTs .cube: leitura, escrita, palpite do espaço de entrada e busca de LUTs instalados."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pelicula import luts


def identity(n: int) -> np.ndarray:
    """Ordem .cube: R varia mais rápido, depois G, depois B."""
    ax = np.linspace(0.0, 1.0, n, dtype=np.float32)
    b, g, r = np.meshgrid(ax, ax, ax, indexing="ij")
    return np.stack([r.ravel(), g.ravel(), b.ravel()], axis=1)


def write_text(path: Path, text: str, encoding: str = "utf-8") -> str:
    path.write_text(text, encoding=encoding, newline="\n")
    return str(path)


def cube_text(n: int = 2, header: str = "", rows: np.ndarray | None = None) -> str:
    rows = identity(n) if rows is None else rows
    body = "\n".join(f"{r:.6f} {g:.6f} {b:.6f}" for r, g, b in rows)
    return f"{header}LUT_3D_SIZE {n}\n{body}\n"


# ------------------------------------------------------------------ leitura e escrita
@pytest.mark.parametrize("n", [2, 5, 17])
def test_save_and_load_identity_roundtrip(tmp_path, n):
    p = str(tmp_path / f"id{n}.cube")
    luts.save_cube(p, identity(n), n, "Identidade")
    lut = luts.load_cube(p)
    assert lut.size == n
    assert lut.title == "Identidade"
    assert lut.path == p
    assert lut.data.shape == (n ** 3, 3) and lut.data.dtype == np.float32
    np.testing.assert_allclose(lut.data, identity(n), atol=1e-6)
    assert lut.dmin == (0.0, 0.0, 0.0) and lut.dmax == (1.0, 1.0, 1.0)


def test_save_cube_clips_to_unit_range(tmp_path):
    data = identity(2) * 3.0 - 1.0
    p = str(tmp_path / "clip.cube")
    luts.save_cube(p, data, 2, "x")
    lut = luts.load_cube(p)
    assert lut.data.min() >= 0.0 and lut.data.max() <= 1.0


def test_save_cube_writes_lf_and_header(tmp_path):
    p = tmp_path / "h.cube"
    luts.save_cube(str(p), identity(2), 2, "Meu LUT")
    raw = p.read_bytes()
    assert b"\r\n" not in raw
    text = raw.decode("utf-8")
    assert text.startswith('TITLE "Meu LUT"\n')
    assert "LUT_3D_SIZE 2\n" in text and "DOMAIN_MIN 0.0 0.0 0.0" in text and "DOMAIN_MAX 1.0 1.0 1.0" in text


def test_save_cube_replaces_an_old_lut_without_leaving_partials(tmp_path):
    p = tmp_path / "look.cube"
    p.write_text("LUT antigo", encoding="utf-8")
    luts.save_cube(str(p), identity(3), 3, "novo")
    assert luts.load_cube(str(p)).size == 3
    assert sorted(f.name for f in tmp_path.iterdir()) == ["look.cube"]


def test_save_cube_failure_keeps_the_old_lut(tmp_path):
    """Uma falha no meio da gravação não deixa o LUT pela metade nem apaga o antigo."""
    p = tmp_path / "look.cube"
    p.write_text("LUT antigo", encoding="utf-8")
    bad = np.array([[0.1, 0.2]], dtype=np.float32)  # linha com 2 valores: a gravação quebra no meio
    with pytest.raises(ValueError):
        luts.save_cube(str(p), bad, 2, "x")
    assert p.read_text(encoding="utf-8") == "LUT antigo"
    assert sorted(f.name for f in tmp_path.iterdir()) == ["look.cube"]


def test_load_cube_domain_min_max(tmp_path):
    p = write_text(tmp_path / "dom.cube",
                   cube_text(2, header='TITLE "Dom"\n# comentário\n\nDOMAIN_MIN -0.1 -0.2 -0.3\nDOMAIN_MAX 1.5 2 4\n'))
    lut = luts.load_cube(p)
    assert lut.dmin == pytest.approx((-0.1, -0.2, -0.3))
    assert lut.dmax == pytest.approx((1.5, 2.0, 4.0))
    assert lut.title == "Dom"


def test_load_cube_input_range_keyword(tmp_path):
    p = write_text(tmp_path / "rng.cube", cube_text(2, header="LUT_3D_INPUT_RANGE 0.0 4.0\n"))
    lut = luts.load_cube(p)
    assert lut.dmin == (0.0, 0.0, 0.0) and lut.dmax == (4.0, 4.0, 4.0)


def test_load_cube_lowercase_keywords_and_signs(tmp_path):
    rows = identity(2) - 0.5
    body = "\n".join(f"{r:+.4f}\t{g:.4e}  {b:.4f}" for r, g, b in rows)
    p = write_text(tmp_path / "lc.cube", f"title \"min\"\nlut_3d_size 2\n{body}\n")
    lut = luts.load_cube(p)
    np.testing.assert_allclose(lut.data, rows, atol=1e-4)


def test_load_cube_ignores_extra_values(tmp_path):
    p = write_text(tmp_path / "extra.cube", cube_text(2) + "0.5 0.5 0.5\n")
    assert luts.load_cube(p).data.shape == (8, 3)


def test_load_cube_rejects_1d_lut(tmp_path):
    p = write_text(tmp_path / "1d.cube", "LUT_1D_SIZE 4\n0 0 0\n0.3 0.3 0.3\n0.6 0.6 0.6\n1 1 1\n")
    with pytest.raises(ValueError, match="1D"):
        luts.load_cube(p)


def test_load_cube_requires_size(tmp_path):
    p = write_text(tmp_path / "nosize.cube", "TITLE \"x\"\n0 0 0\n1 1 1\n")
    with pytest.raises(ValueError, match="LUT_3D_SIZE"):
        luts.load_cube(p)


def test_load_cube_rejects_incomplete(tmp_path):
    rows = identity(3)[:20]
    p = write_text(tmp_path / "inc.cube", cube_text(3, rows=rows))
    with pytest.raises(ValueError, match="incompleto"):
        luts.load_cube(p)


def test_load_cube_missing_file(tmp_path):
    with pytest.raises(OSError):
        luts.load_cube(str(tmp_path / "nao_existe.cube"))


def test_load_cube_with_utf8_bom(tmp_path):
    p = write_text(tmp_path / "bom.cube", cube_text(2), encoding="utf-8-sig")
    lut = luts.load_cube(p)
    assert lut.size == 2


def test_load_cube_with_utf8_bom_before_title(tmp_path):
    """Com TITLE na primeira linha o BOM só faz perder o título."""
    p = write_text(tmp_path / "bomt.cube", cube_text(2, header='TITLE "x"\n'), encoding="utf-8-sig")
    assert luts.load_cube(p).size == 2


# ------------------------------------------------------------------ palpite do espaço de entrada
@pytest.mark.parametrize("path, expected", [
    (r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\LUT\Film Looks\Rec709 Kodak 2383 D65.cube", "cineon"),
    ("/opt/resolve/LUT/Film Looks/DCI-P3 Fujifilm 3513DI D60.cube", "cineon"),
    (r"D:\luts\Kodak_Cineon_to_2383.cube", "cineon"),
    (r"D:\luts\ARRI_LogC3_to_Rec709.cube", "logc3"),
    (r"D:\luts\Alexa LogC Look.cube", "logc3"),
    (r"D:\luts\SLog3SGamut3.Cine_to_709.cube", "slog3"),
    (r"D:\luts\Sony S-Log3 Look.cube", "slog3"),
    (r"D:\luts\Nikon N-Log 3D LUT.cube", "nlog"),
    (r"D:\luts\nlog_to_rec709.cube", "nlog"),
    (r"D:\luts\Panasonic V-Log to V-709.cube", "vlog"),
    (r"D:\luts\VLOG_film.cube", "vlog"),
    (r"D:\luts\ARRI_LogC4_to_Rec709.cube", "logc4"),
    (r"D:\luts\AWG4 Look.cube", "logc4"),
    (r"D:\luts\Apple Log to Rec709.cube", "applelog"),
    (r"D:\luts\AppleLog_film.cube", "applelog"),
    (r"D:\luts\BMD Film Gen5 to Video.cube", "bmd_gen5"),
    (r"D:\luts\Blackmagic_Film_Gen_5_look.cube", "bmd_gen5"),
    (r"D:\luts\iPhone HLG to Rec709.cube", "hlg"),
    (r"D:\luts\HLG_film_look.cube", "hlg"),
    (r"D:\luts\HDR10 to SDR.cube", "pq"),
    (r"D:\luts\PQ_1000nits_look.cube", "pq"),
    (r"D:\luts\ST2084 to 709.cube", "pq"),
    (r"D:\luts\Teal Orange.cube", "rec709"),
    (r"D:\luts\Equipe Highlight Glow.cube", "rec709"),
    (r"C:\Program Files\Adobe\Adobe Premiere Pro 2025\Lumetri\LUTs\Creative\Fuji F125 Kodak 2393.cube", "rec709"),
])
def test_guess_input(path, expected):
    assert luts.guess_input(path) == expected


def test_guess_input_only_uses_folder_for_film_looks():
    # "logc" numa pasta não deve influenciar: só o nome do arquivo conta.
    assert luts.guess_input(r"D:\logc_projetos\Teal Orange.cube") == "rec709"


@pytest.mark.parametrize("name", ["Warrior Teal.cube", "Carrie Look.cube", "Harris Shutter.cube"])
def test_guess_input_no_false_arri(name):
    assert luts.guess_input("D:/luts/" + name) == "rec709"


# ------------------------------------------------------------------ instalação e busca
def test_user_dir_is_redirected(tmp_appdata):
    assert luts.user_dir() == tmp_appdata / "PeliculaConverter" / "luts"
    assert luts.user_dir().is_dir()


def test_install_copies_validates_and_renames(tmp_appdata, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    good = src / "Meu Filme.cube"
    luts.save_cube(str(good), identity(3), 3, "bom")
    bad = src / "Quebrado.cube"
    bad.write_text("isto não é um LUT", encoding="utf-8")

    done, errors = luts.install([str(good), str(bad)])
    dest = luts.user_dir() / "Meu Filme.cube"
    assert done == [str(dest)] and dest.is_file()
    assert len(errors) == 1 and errors[0].startswith("Quebrado.cube:")
    assert not (luts.user_dir() / "Quebrado.cube").exists()

    # o mesmo nome de novo ganha "(2)"
    done2, errors2 = luts.install([str(good)])
    assert errors2 == []
    assert Path(done2[0]).name == "Meu Filme (2).cube"

    # instalar um arquivo que já está na pasta não duplica
    done3, _ = luts.install([str(dest)])
    assert done3 == [str(dest)]
    assert sorted(p.name for p in luts.user_dir().glob("*.cube")) == ["Meu Filme (2).cube", "Meu Filme.cube"]


def test_find_system_luts_with_fake_install_dirs(tmp_appdata, tmp_path, monkeypatch):
    pf = tmp_path / "pf"
    pd = tmp_path / "pd"
    creative = pf / "Adobe" / "Adobe Premiere Pro 2025" / "Lumetri" / "LUTs" / "Creative"
    emul = pf / "Adobe" / "Adobe Premiere Pro 2025" / "Resources" / "LUTs" / "FilmEmulation"
    old = pf / "Adobe" / "Adobe Premiere Pro 2024" / "Lumetri" / "LUTs" / "Creative"
    resolve = pd / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "LUT" / "Film Looks"
    for d in (creative, emul, old, resolve):
        d.mkdir(parents=True)
    for d, name in ((creative, "Fuji Eterna"), (emul, "Kodak 5205"), (old, "Antigo"), (resolve, "Rec709 Kodak 2383 D65")):
        luts.save_cube(str(d / f"{name}.cube"), identity(2), 2, name)
    (creative / "leia-me.txt").write_text("x", encoding="utf-8")
    luts.save_cube(str(luts.user_dir() / "Pessoal.cube"), identity(2), 2, "p")
    monkeypatch.setenv("ProgramFiles", str(pf))
    monkeypatch.setenv("ProgramData", str(pd))

    found = luts.find_system_luts()
    labels = [lab for lab, _ in found]
    assert labels[0] == "Meus LUTs — Pessoal"
    assert "Premiere Pro 2025 — Fuji Eterna" in labels
    assert "Premiere Pro 2025 (emulação) — Kodak 5205" in labels
    assert "DaVinci Resolve — Rec709 Kodak 2383 D65" in labels
    # só a versão mais nova do Premiere
    assert not any("Antigo" in lab for lab in labels)
    assert len(found) == 4
    for _, path in found:
        assert Path(path).is_file() and path.endswith(".cube")
        luts.load_cube(path)


def test_find_system_luts_without_any_install(tmp_appdata, tmp_path, monkeypatch):
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "vazio_pf"))
    monkeypatch.setenv("ProgramData", str(tmp_path / "vazio_pd"))
    assert luts.find_system_luts() == []
