"""Shaders GLSL do modo Edição: uma camada (clipe) por passo sobre a tela da sequência.

Mesmas convenções de `shaders.py`: coordenadas de imagem com y para baixo (linha 0 = topo),
`gl_FragCoord.xy` é o pixel da tela da sequência e nada é invertido no caminho.

- `CLIP`: lê o clipe (`t_clip`, valores de vídeo Rec.709 de 0 a 1), aplica detalhe, cor e
  enquadramento e mistura com a tela anterior (`t_dst`, RGBA f4) segundo o modo de mesclagem.
  Com `u_cc_on = 0`, `u_det_on = 0`, opacidade 1 e enquadramento identidade (`u_exact = 1`), a
  saída é exatamente o pixel de entrada.
- `OUT`: converte a tela (f4) para inteiros de 8 ou 16 bits (arredondamento exato) lidos de volta.

Os valores vêm de `compositor.clip_uniforms()`; a interpretação de cada ajuste está lá.
"""

from .shaders import VERT  # noqa: F401  (mesmo vértice de tela cheia)

CLIP = """
#version 330
in vec2 v_uv;
out vec4 f_out;

const vec3 W709 = vec3(0.2126, 0.7152, 0.0722);

uniform sampler2D t_clip;
uniform sampler2D t_dst;
uniform vec2 u_canvas;          // largura e altura da tela (px)
uniform vec2 u_clip_px;         // tamanho da textura do clipe (texels)
uniform mat3 u_xf;              // pixel da tela -> uv do clipe
uniform vec2 u_px_per_uv;       // px da tela por unidade de uv (antisserrilhado das bordas)
uniform int u_exact;            // 1 = mapeamento identidade (texelFetch, saída bit a bit)
uniform vec4 u_crop;            // esquerda, topo, direita, base (fração do clipe)
uniform float u_alpha;          // opacidade final (clipe x transição)
uniform int u_blend;            // 0 normal, 1 tela, 2 multiplicar, 3 sobrepor, 4 adicionar, 5 clarear, 6 escurecer
uniform vec4 u_fade;            // cor e força do fade (surgir/sumir no preto ou branco)

uniform int u_det_on;
uniform float u_texel;          // passo dos filtros finos em texels (1 em 1080p, proporcional acima)
uniform float u_sharp;
uniform float u_clarity;
uniform float u_clarity_lod;
uniform float u_blur;           // raio do desfoque em texels
uniform float u_denoise;

uniform int u_cc_on;
uniform float u_exp;            // EV
uniform vec3 u_wb;              // ganhos do balanço de branco (luz linear)
uniform vec2 u_levels;          // ponto preto, ponto branco
uniform vec2 u_hs;              // realces, sombras
uniform vec4 u_curve;           // sombras, escuros, claros, realces
uniform float u_bright;         // expoente dos tons médios
uniform float u_contrast;       // força da curva em S
uniform vec3 u_lift;
uniform vec3 u_gamma;
uniform vec3 u_cgain;
uniform float u_sat;            // 1 = neutro
uniform float u_vib;
uniform float u_hue_rot;        // radianos
uniform int u_hsl_on;
uniform float u_hsl_h[8];
uniform float u_hsl_s[8];
uniform float u_hsl_l[8];
uniform vec2 u_vig;             // força (negativo escurece), tamanho
uniform float u_fadeblk;        // desbotar

const float HUES[8] = float[8](0.0, 30.0, 60.0, 120.0, 180.0, 225.0, 270.0, 315.0);

vec3 fetchClip(vec2 uv) {
    return texture(t_clip, uv).rgb;
}

vec3 rgb2hsv(vec3 c) {
    float mx = max(c.r, max(c.g, c.b));
    float mn = min(c.r, min(c.g, c.b));
    float d = mx - mn;
    float h = 0.0;
    if (d > 1e-6) {
        if (mx == c.r) h = mod((c.g - c.b) / d, 6.0);
        else if (mx == c.g) h = (c.b - c.r) / d + 2.0;
        else h = (c.r - c.g) / d + 4.0;
    }
    float s = mx > 1e-6 ? d / mx : 0.0;
    return vec3(h * 60.0, s, mx);
}
vec3 hsv2rgb(vec3 c) {
    float h = mod(c.x, 360.0) / 60.0;
    float C = c.z * c.y;
    float X = C * (1.0 - abs(mod(h, 2.0) - 1.0));
    float m = c.z - C;
    vec3 rgb;
    if (h < 1.0) rgb = vec3(C, X, 0.0);
    else if (h < 2.0) rgb = vec3(X, C, 0.0);
    else if (h < 3.0) rgb = vec3(0.0, C, X);
    else if (h < 4.0) rgb = vec3(0.0, X, C);
    else if (h < 5.0) rgb = vec3(X, 0.0, C);
    else rgb = vec3(C, 0.0, X);
    return rgb + m;
}

// ---------------------------------------------------------------- detalhe
vec3 detail(vec2 uv, vec3 c) {
    vec2 tx = u_texel / u_clip_px;
    if (u_denoise > 0.0) {
        // Bilateral 5x5: média dos vizinhos parecidos (preserva bordas).
        float rs = mix(0.02, 0.12, u_denoise);
        vec3 acc = vec3(0.0);
        float ws = 0.0;
        for (int j = -2; j <= 2; j++) {
            for (int i = -2; i <= 2; i++) {
                vec3 s = fetchClip(uv + vec2(float(i), float(j)) * tx);
                vec3 d = s - c;
                float w = exp(-float(i * i + j * j) / 4.5 - dot(d, d) / (2.0 * rs * rs));
                acc += s * w;
                ws += w;
            }
        }
        c = mix(c, acc / ws, min(1.0, u_denoise * 1.5));
    }
    if (u_blur > 0.0) {
        // Desfoque gaussiano aproximado: anéis de amostras no nível de mipmap do raio.
        float lod = max(0.0, log2(u_blur / 3.0));
        vec2 r = u_blur / u_clip_px;
        vec3 acc = textureLod(t_clip, uv, lod).rgb * 0.2;
        float ws = 0.2;
        for (int k = 0; k < 12; k++) {
            float a = float(k) * 0.5235988 + (k >= 6 ? 0.2617994 : 0.0);
            float rr = k < 6 ? 0.45 : 0.95;
            float w = k < 6 ? 0.1 : 0.0333;
            acc += textureLod(t_clip, uv + vec2(cos(a), sin(a)) * r * rr, lod).rgb * w;
            ws += w;
        }
        c = acc / ws;
    }
    if (u_sharp > 0.0) {
        vec3 b = (fetchClip(uv + vec2(tx.x, 0.0)) + fetchClip(uv - vec2(tx.x, 0.0))
                + fetchClip(uv + vec2(0.0, tx.y)) + fetchClip(uv - vec2(0.0, tx.y))) * 0.25;
        c = c + (c - b) * u_sharp * 1.6;
    }
    if (u_clarity != 0.0) {
        // Contraste local: diferença para uma versão bem desfocada (mipmap), mais forte nos tons médios.
        vec2 r = exp2(u_clarity_lod) / u_clip_px;
        vec3 base = textureLod(t_clip, uv, u_clarity_lod).rgb * 0.4
                  + (textureLod(t_clip, uv + vec2(r.x, 0.0), u_clarity_lod).rgb
                  + textureLod(t_clip, uv - vec2(r.x, 0.0), u_clarity_lod).rgb
                  + textureLod(t_clip, uv + vec2(0.0, r.y), u_clarity_lod).rgb
                  + textureLod(t_clip, uv - vec2(0.0, r.y), u_clarity_lod).rgb) * 0.15;
        float L = dot(c, W709);
        float mid = 1.0 - pow(abs(clamp(L, 0.0, 1.0) * 2.0 - 1.0), 2.0);
        c = c + (dot(c, W709) - dot(base, W709)) * u_clarity * 0.9 * mid;
    }
    return max(c, vec3(0.0));
}

// ---------------------------------------------------------------- tons e cor
float bumpS(float x) { x = clamp(x, 0.0, 1.0); return x * (1.0 - x) * (1.0 - x) * 6.75; }
float bumpH(float x) { x = clamp(x, 0.0, 1.0); return x * x * (1.0 - x) * 6.75; }
float region(float x, float c) {
    float d = (x - c) / 0.3;
    float w = max(0.0, 1.0 - d * d);
    return w * w * x * (1.0 - x) * 4.0;
}
float tone(float x) {
    x = (x - u_levels.x) / max(u_levels.y - u_levels.x, 1e-4);
    x += u_hs.x * 0.15 * bumpH(x) + u_hs.y * 0.15 * bumpS(x);
    if (u_curve != vec4(0.0)) {
        float xc = clamp(x, 0.0, 1.0);
        x += 0.1 * (u_curve.x * region(xc, 0.125) + u_curve.y * region(xc, 0.375)
                  + u_curve.z * region(xc, 0.625) + u_curve.w * region(xc, 0.875));
    }
    if (u_bright != 1.0) x = pow(max(x, 0.0), u_bright);
    if (u_contrast != 0.0 && x > 0.0 && x < 1.0) x = x - u_contrast * sin(6.2831853 * x) / 6.2831853;
    return x;
}

vec3 colorCorrect(vec3 c) {
    // Exposição e balanço de branco em luz (gama 2,2).
    if (u_exp != 0.0 || u_wb != vec3(1.0)) {
        vec3 lin = pow(max(c, vec3(0.0)), vec3(2.2)) * exp2(u_exp) * u_wb;
        c = pow(lin, vec3(1.0 / 2.2));
    }
    if (u_levels != vec2(0.0, 1.0) || u_hs != vec2(0.0) || u_curve != vec4(0.0) || u_bright != 1.0
        || u_contrast != 0.0)
        c = vec3(tone(c.r), tone(c.g), tone(c.b));
    // Rodas: levantar (sombras), gama (tons médios) e ganho (altas luzes).
    c = c + u_lift * (1.0 - c);
    if (u_gamma != vec3(1.0)) c = pow(max(c, vec3(0.0)), u_gamma);
    c *= u_cgain;
    // Saturação e vibração em torno da luminância.
    float L = dot(c, W709);
    float amt = u_sat;
    if (u_vib != 0.0) {
        float mx = max(c.r, max(c.g, c.b));
        float mn = min(c.r, min(c.g, c.b));
        float s = (mx - mn) / max(mx, 1e-4);
        float skin = (c.r > c.g && c.g > c.b) ? 0.5 : 1.0;
        amt *= 1.0 + u_vib * (1.0 - smoothstep(0.0, 0.7, s)) * (u_vib > 0.0 ? skin : 1.0);
    }
    if (amt != 1.0) c = L + (c - L) * amt;
    if (u_hue_rot != 0.0) {
        float Y = dot(c, W709);
        vec2 cc = vec2((c.b - Y) / 1.8556, (c.r - Y) / 1.5748);
        float cs = cos(u_hue_rot), sn = sin(u_hue_rot);
        cc = vec2(cs * cc.x - sn * cc.y, sn * cc.x + cs * cc.y);
        float r = Y + 1.5748 * cc.y;
        float b = Y + 1.8556 * cc.x;
        c = vec3(r, (Y - 0.2126 * r - 0.0722 * b) / 0.7152, b);
    }
    if (u_hsl_on == 1) {
        vec3 hsv = rgb2hsv(max(c, vec3(0.0)));
        float h = hsv.x;
        float dh = 0.0, ds = 0.0, dl = 0.0;
        for (int i = 0; i < 8; i++) {
            float h0 = HUES[i];
            float hp = HUES[(i + 7) % 8] - (i == 0 ? 360.0 : 0.0);
            float hn = HUES[(i + 1) % 8] + (i == 7 ? 360.0 : 0.0);
            float d = mod(h - h0 + 540.0, 360.0) - 180.0;
            float w = d >= 0.0 ? 1.0 - d / (hn - h0) : 1.0 + d / (h0 - hp);
            w = clamp(w, 0.0, 1.0);
            w = w * w * (3.0 - 2.0 * w);
            dh += w * u_hsl_h[i];
            ds += w * u_hsl_s[i];
            dl += w * u_hsl_l[i];
        }
        float sw = smoothstep(0.02, 0.2, hsv.y);
        hsv.x += dh * 30.0 * sw;
        hsv.y = clamp(hsv.y * (1.0 + ds * sw), 0.0, 1.0);
        hsv.z *= 1.0 + dl * 0.5 * sw;
        c = hsv2rgb(hsv);
    }
    return c;
}

vec3 blend(vec3 b, vec3 s) {
    if (u_blend == 1) return 1.0 - (1.0 - clamp(b, 0.0, 1.0)) * (1.0 - clamp(s, 0.0, 1.0));
    if (u_blend == 2) return b * s;
    if (u_blend == 3) {
        vec3 bb = clamp(b, 0.0, 1.0);
        vec3 ss = clamp(s, 0.0, 1.0);
        return mix(2.0 * bb * ss, 1.0 - 2.0 * (1.0 - bb) * (1.0 - ss), step(0.5, bb));
    }
    if (u_blend == 4) return b + s;
    if (u_blend == 5) return max(b, s);
    if (u_blend == 6) return min(b, s);
    return s;
}

void main() {
    ivec2 ip = ivec2(gl_FragCoord.xy);
    vec4 dst = texelFetch(t_dst, ip, 0);
    vec2 uv = (u_xf * vec3(gl_FragCoord.xy, 1.0)).xy;
    // Cobertura do pixel: distância (em px da tela) até a borda do recorte do clipe.
    vec2 lo = u_crop.xy;
    vec2 hi = 1.0 - u_crop.zw;
    vec2 dd = min(uv - lo, hi - uv) * u_px_per_uv;
    float cover = clamp(min(dd.x, dd.y) + 0.5, 0.0, 1.0);
    float a = cover * u_alpha;
    if (a <= 0.0) {
        f_out = dst;
        return;
    }
    vec3 c;
    if (u_exact == 1) c = texelFetch(t_clip, ip, 0).rgb;
    else c = texture(t_clip, uv).rgb;
    if (u_det_on == 1) c = detail(uv, c);
    if (u_cc_on == 1) {
        c = colorCorrect(c);
        if (u_vig.x != 0.0) {
            vec2 p = (uv - 0.5) * 2.0;
            p.x *= u_clip_px.x / u_clip_px.y;
            float dn = length(p) / length(vec2(u_clip_px.x / u_clip_px.y, 1.0));
            float v = smoothstep(u_vig.y * 0.8, u_vig.y * 0.8 + 0.6, dn);
            c *= exp2(u_vig.x * 1.6 * v);
        }
        if (u_fadeblk > 0.0) c = c * (1.0 - 0.22 * u_fadeblk) + 0.09 * u_fadeblk;
        c = max(c, vec3(0.0));
    }
    if (u_fade.w > 0.0) c = mix(c, u_fade.rgb, u_fade.w);
    vec3 res = blend(dst.rgb, c);
    if (a >= 1.0) f_out = vec4(res, 1.0);
    else f_out = vec4(mix(dst.rgb, res, a), 1.0);
}
"""

OUT = """
#version 330
in vec2 v_uv;
out uvec4 f_out;
uniform sampler2D t_canvas;
uniform float u_max;  // 255 ou 65535: arredonda aqui, sem depender da conversão do driver
void main() {
    vec3 c = clamp(texelFetch(t_canvas, ivec2(gl_FragCoord.xy), 0).rgb, 0.0, 1.0);
    f_out = uvec4(uvec3(floor(c * u_max + 0.5)), uint(u_max));
}
"""
