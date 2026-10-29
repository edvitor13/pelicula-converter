"""Shaders da saída com transparência (fundo transparente da montagem e o alfa do look).

A montagem com "Fundo transparente" guarda na tela RGBA de 32 bits a cor *direta* (não pré-multiplicada) e a
cobertura de cada pixel (`editshaders.CLIP`). Para sair com alfa:

- `PREMUL` + `CANVAS_OUT`: a tela vira RGBA direto (8/16 bits). Os pixels totalmente transparentes recebem a cor
  dos vizinhos visíveis (um mipmap da tela pré-multiplicada), para que os desfoques do look (difusão, halação,
  bloom) não puxem a cor do fundo para dentro da borda (sem franja escura).
- `ALPHA`: o alfa do quadro com o look. O próprio `shaders.BASE` desenha a *transparência* da entrada (1 − alfa)
  com a geometria do look (tremor, zoom, rotação, distorção da lente e a tira do scan) usando uniforms neutros de
  cor (`ALPHA_GEOMETRY`: tudo o que o scan desenha — base do filme, furos, bordas, lado de fora — vale 0, ou seja,
  opaco); aqui ele se junta à cor já pronta (lida com `texelFetch`, então a cor sai bit a bit igual à de
  `Engine.render`), com a "Intensidade do look" e a Moldura (fora da janela da moldura: transparente).

As funções da moldura são copiadas do texto de `shaders.FINAL` (`_function`), para nunca ficarem diferentes.
"""

from __future__ import annotations

from . import shaders


def _function(src: str, signature: str) -> str:
    """O texto de uma função GLSL de `src`, da assinatura até a chave que a fecha."""
    i = src.index(signature)
    j = src.index("{", i)
    depth = 0
    for k in range(j, len(src)):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return src[i:k + 1]
    raise ValueError(signature)


PREMUL = """
#version 330
in vec2 v_uv;
out vec4 f_out;
uniform sampler2D t_canvas;
void main() {
    vec4 c = texelFetch(t_canvas, ivec2(gl_FragCoord.xy), 0);
    float a = clamp(c.a, 0.0, 1.0);
    f_out = vec4(clamp(c.rgb, 0.0, 1.0) * a, a);
}
"""

CANVAS_OUT = """
#version 330
in vec2 v_uv;
out uvec4 f_out;
uniform sampler2D t_canvas;
uniform sampler2D t_pm;      // a tela pré-multiplicada, com mipmaps
uniform float u_max;         // 255 ou 65535
uniform ivec2 u_offset;      // canto do recorte na tela ("cortar" da exportação)
uniform vec2 u_size;         // tamanho da tela (px)
uniform float u_levels;      // níveis do mipmap
void main() {
    ivec2 ip = ivec2(gl_FragCoord.xy) + u_offset;
    vec4 t = texelFetch(t_canvas, ip, 0);
    vec3 c = clamp(t.rgb, 0.0, 1.0);
    float a = clamp(t.a, 0.0, 1.0);
    if (a <= 0.0) {
        vec2 uv = (vec2(ip) + 0.5) / u_size;
        for (float l = 1.0; l <= u_levels; l += 1.0) {
            vec4 m = textureLod(t_pm, uv, l);
            if (m.a > 1e-4) {
                c = clamp(m.rgb / m.a, 0.0, 1.0);
                break;
            }
        }
    }
    f_out = uvec4(uvec3(floor(c * u_max + 0.5)), uint(floor(a * u_max + 0.5)));
}
"""

ALPHA = shaders.COMMON + """
uniform sampler2D t_rgb;     // o quadro com o look (alvo out8/out16)
uniform sampler2D t_geo;     // transparência (1 − alfa) desenhada pelo BASE com a geometria do look
uniform sampler2D t_ain;     // transparência da entrada, sem geometria (para a "Intensidade do look")
uniform float u_mix;
uniform vec2 u_res;
uniform float u_scale;
uniform int u_frame_on;
uniform float u_aspect_t;
uniform float u_corner;
uniform float u_edge_soft;
uniform float u_edge_rough;
uniform vec3 u_bar_color;
""" + _function(shaders.FINAL, "float vnoise1(") + "\n\n" + _function(shaders.FINAL, "vec3 frameMask(") + """

void main() {
    ivec2 ip = ivec2(gl_FragCoord.xy);
    vec3 c = texelFetch(t_rgb, ip, 0).rgb;
    float a = 1.0 - mix(texture(t_ain, v_uv).r, texelFetch(t_geo, ip, 0).r, u_mix);
    if (u_frame_on == 1) {
        // frameMask(y) = mix(barra, y, m): a diferença entre y = 1 e y = 0 é a cobertura m da janela.
        float m = clamp(frameMask(vec3(1.0), v_uv).r - frameMask(vec3(0.0), v_uv).r, 0.0, 1.0);
        if (m > 0.0 && m < 1.0) c = clamp((c - u_bar_color * (1.0 - m)) / m, 0.0, 1.0);
        a *= m;
    }
    f_out = vec4(c, clamp(a, 0.0, 1.0));
}
"""

# Uniforms do BASE que desenham só a transparência: entrada linear sem conversão de cor (perfil 1), sem
# aberração cromática nem vinheta; a base do filme, os furos, o lado de fora e o texto da borda valem 0 (opacos).
ALPHA_GEOMETRY = {
    "u_input": 1, "u_input_cv": 0, "u_gamut": (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
    "u_gain": (0.0, 0.0, 0.0), "u_ca": 0.0, "u_vig": (0.0, 0.5, 0.5, 0.0), "u_scan_base": (0.0, 0.0, 0.0),
    "u_scan_light": (0.0, 0.0, 0.0), "u_scan_outside": (0.0, 0.0, 0.0), "u_scan_textcol": (0.0, 0.0, 0.0),
    "u_date_on": 0,  # 1.6: a data impressa é luz, não muda a transparência
}
