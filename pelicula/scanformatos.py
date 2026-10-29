"""Formatos de foto no scan da película (1.6): 135 (36 × 24 mm, 8 furos), meio quadro (18 × 24 mm, 4 furos) e 120
(6 × 6 e 6 × 4,5, sem furos).

As medidas ficam em `look.SCAN_FORMATS` (x atravessa a película, y corre ao longo dela, como nas bitolas de cinema)
e as bitolas em `look.GAUGES`. O 135 e o meio quadro são fotografados com a película correndo na horizontal: o scan
mostra a tira deitada (`rotated`: o passo BASE gira o sistema de coordenadas da película em 90°, e a imagem volta
na orientação dela). O 120 6 × 6 também (o quadro quadrado inteiro cabe na altura da tela, com os vizinhos dos
lados); o 6 × 4,5 fica de pé (o quadro já sai deitado, 56 mm na largura).

O BASE de sempre não muda: a tira deitada é outra variante do programa (`Engine._base_program`, compilada no
primeiro uso), montada aqui por substituição de texto do BASE (ou do BASE da Cor por planos), como `planes.BASE_CP`;
o plano marca a variante com `u_scan_rot` = 1 (não é um uniform do programa). Sem o scan deitado, o look usa o BASE
letra por letra.
"""

from __future__ import annotations

ROTATED = ("135", "meio_quadro", "120_66")   # formatos com a tira deitada

# Texto da borda de cada formato (o "auto"); os números dos quadros, como nos negativos de foto
EDGE_TEXTS = {
    "135": "KODAK  PORTRA  400      12      12A      13      13A",
    "meio_quadro": "KODAK  GOLD  200      24      24A      25      25A",
    "120_66": "KODAK  PORTRA  160            6",
    "120_645": "KODAK  PORTRA  160            8",
}

_SUBS = (
    ("    vec2 suv = weave(v_uv);\n    float mmpp = u_scan_view.z / u_res.x;\n"
     "    vec2 mm = vec2(u_scan_view.w, 0.0) + (suv - 0.5) * u_res * mmpp;\n",
     "    vec2 suv = weave(v_uv);\n    suv = vec2(suv.y, 1.0 - suv.x);\n    vec2 R = u_res.yx;\n"
     "    float mmpp = u_scan_view.z / R.x;\n    vec2 mm = vec2(u_scan_view.w, 0.0) + (suv - 0.5) * R * mmpp;\n"),
    ("    float Av = u_res.x / u_res.y;\n", "    float Av = R.x / R.y;\n"),
    ("    vec3 img = imageLin(clamp(cuv, 0.0, 1.0)) * vignette(clamp(cuv, 0.0, 1.0));\n",
     "    vec2 iuv = clamp(cuv, 0.0, 1.0);\n    iuv = vec2(1.0 - iuv.y, iuv.x);\n"
     "    vec3 img = imageLin(iuv) * vignette(iuv);\n"),
    ("dateMask(clamp(cuv, 0.0, 1.0) * vec2(Av * 1080.0, 1080.0))",
     "dateMask(iuv * vec2(u_res.x / u_res.y * 1080.0, 1080.0))"),
)


def rotated(src: str) -> str:
    """O BASE (ou o BASE da Cor por planos) com a tira da película deitada no scan."""
    for old, new in _SUBS:
        assert src.count(old) == 1, old
        src = src.replace(old, new, 1)
    return src


def is_rotated(v: dict) -> bool:
    from .look import scan_format
    return bool(v.get("scan_on")) and scan_format(v) in ROTATED
