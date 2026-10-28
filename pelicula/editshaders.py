"""Shaders GLSL do modo Edição: uma camada (clipe) por passo sobre a tela da sequência.

Mesmas convenções de `shaders.py`: coordenadas de imagem com y para baixo (linha 0 = topo),
`gl_FragCoord.xy` é o pixel da tela da sequência e nada é invertido no caminho.

- `CLIP`: lê o clipe (`t_clip`, valores de vídeo Rec.709 de 0 a 1), aplica detalhe, cor e
  enquadramento e mistura com a tela anterior (`t_dst`, RGBA f4) segundo o modo de mesclagem.
  Com `u_cc_on = 0`, `u_det_on = 0`, opacidade 1 e enquadramento identidade (`u_exact = 1`), a
  saída é exatamente o pixel de entrada.
  Transparência (`u_tex_alpha = 1`): a textura é RGBA **pré-multiplicada** (`sequence.LayerImage`); a
  filtragem (bilinear e mipmaps) é feita assim, sem franja escura na borda. Depois de amostrar, a cor volta a
  ser a do clipe (dividida pelo alfa), a cor e o detalhe do clipe agem nela e o alfa entra na cobertura,
  junto com a opacidade, o corte e a transição; cada modo de mesclagem mistura com a tela por essa cobertura.
- `OUT`: converte a tela (f4) para inteiros de 8 ou 16 bits (arredondamento exato) lidos de volta; com
  `u_offset` lê só um recorte da tela (exportação num quadro de outra proporção com "cortar", `fit.py`).

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
uniform int u_tex_alpha;        // 1 = textura RGBA pré-multiplicada (fonte com transparência)
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

// Cor do clipe sem a multiplicação pelo alfa (texturas com transparência); um pixel transparente fica preto.
vec3 unpremul(vec4 s) {
    if (u_tex_alpha == 0) return s.rgb;
    return s.a > 0.0 ? s.rgb / s.a : vec3(0.0);
}

vec3 fetchClip(vec2 uv) {
    if (u_tex_alpha == 0) return texture(t_clip, uv).rgb;
    return unpremul(texture(t_clip, uv));
}

vec3 fetchLod(vec2 uv, float lod) {
    if (u_tex_alpha == 0) return textureLod(t_clip, uv, lod).rgb;
    return unpremul(textureLod(t_clip, uv, lod));
}

// Alfa da textura com as pontas firmes: menos de 1/256 de 0 ou de 1 vira 0 ou 1. As conversões de formato do
// ffmpeg deixam o "opaco" em 0,996 a 0,9998 e o "transparente" em até 0,002 (e o ProRes 4444 gravado pelo
// ffmpeg guarda o opaco como 4083/4095); sem isso o fundo vazaria ~0,3% onde o clipe é opaco.
float clipAlpha(float a) {
    const float E = 1.0 / 256.0;
    return clamp((a - E) / (1.0 - 2.0 * E), 0.0, 1.0);
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
        if (u_tex_alpha == 0) {
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
        } else {
            // Pré-multiplicado: a média ignora a cor dos pixels transparentes (sem escurecer a borda).
            vec4 acc = textureLod(t_clip, uv, lod) * 0.2;
            for (int k = 0; k < 12; k++) {
                float a = float(k) * 0.5235988 + (k >= 6 ? 0.2617994 : 0.0);
                float rr = k < 6 ? 0.45 : 0.95;
                float w = k < 6 ? 0.1 : 0.0333;
                acc += textureLod(t_clip, uv + vec2(cos(a), sin(a)) * r * rr, lod) * w;
            }
            if (acc.a > 0.0) c = acc.rgb / acc.a;
        }
    }
    if (u_sharp > 0.0) {
        vec3 b = (fetchClip(uv + vec2(tx.x, 0.0)) + fetchClip(uv - vec2(tx.x, 0.0))
                + fetchClip(uv + vec2(0.0, tx.y)) + fetchClip(uv - vec2(0.0, tx.y))) * 0.25;
        c = c + (c - b) * u_sharp * 1.6;
    }
    if (u_clarity != 0.0) {
        // Contraste local: diferença para uma versão bem desfocada (mipmap), mais forte nos tons médios.
        vec2 r = exp2(u_clarity_lod) / u_clip_px;
        vec3 base = fetchLod(uv, u_clarity_lod) * 0.4
                  + (fetchLod(uv + vec2(r.x, 0.0), u_clarity_lod)
                  + fetchLod(uv - vec2(r.x, 0.0), u_clarity_lod)
                  + fetchLod(uv + vec2(0.0, r.y), u_clarity_lod)
                  + fetchLod(uv - vec2(0.0, r.y), u_clarity_lod)) * 0.15;
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
    if (u_tex_alpha == 0) {
        if (u_exact == 1) c = texelFetch(t_clip, ip, 0).rgb;
        else c = texture(t_clip, uv).rgb;
    } else {
        vec4 s = u_exact == 1 ? texelFetch(t_clip, ip, 0) : texture(t_clip, uv);
        a *= clipAlpha(s.a);
        if (a <= 0.0) {
            f_out = dst;
            return;
        }
        c = s.rgb / max(s.a, 1e-6);
    }
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
uniform ivec2 u_offset;  // canto do recorte na tela (exportação com "cortar"; 0,0 = a tela inteira)
void main() {
    vec3 c = clamp(texelFetch(t_canvas, ivec2(gl_FragCoord.xy) + u_offset, 0).rgb, 0.0, 1.0);
    f_out = uvec4(uvec3(floor(c * u_max + 0.5)), uint(u_max));
}
"""


# ------------------------------------------------------------------ 1.5: transições de película
# `CLIP_TR`: o mesmo `CLIP` (uniforms, detalhe, cor, mesclagem e enquadramento) com as transições novas
# (`transitions.py`). As camadas sem transição nova continuam no `CLIP` de sempre, bit a bit; esta cópia só
# é usada quando `compositor.clip_uniforms` traz os uniforms `u_tr_*`. As curvas de câmera são as do look
# (`shaders.COMMON`, de `D_SLOPE` até a parte de cor), para misturar na mesma luz que o look vai ler.
from .shaders import COMMON as _COMMON  # noqa: E402

_CURVES = _COMMON[_COMMON.index("const float D_SLOPE"):
                  _COMMON.index("// ---------------------------------------------------------------- cor")]

_TR_FUNCS = """
// ---------------------------------------------------------------- transições (transitions.py)
uniform int u_tr_input;      // curva de entrada do look (look.INPUT_IDS): o código do vídeo → luz da cena
uniform int u_tr_cv;         // 1 = curva em código de 10 bits numa fonte de faixa legal (shaders.toLinear)
uniform float u_tr_scale;    // altura da tela / 1080 (px@1080 → px)
uniform int u_tr_kind[2];    // 0 = nada; transitions.KIND_IDS
uniform int u_tr_role[2];    // 0 entra, 1 sai, 2 base (cauda do clipe anterior)
uniform float u_tr_p[2];     // andamento 0 → 1
uniform int u_tr_index[2];   // quadro dentro da transição
uniform int u_tr_seed[2];    // semente do ruído (id do clipe dono)
uniform vec4 u_tr_a[2];      // parâmetros do tipo (transitions.apply)
uniform vec4 u_tr_b[2];
uniform vec4 u_tr_blur;      // desfoque de movimento: (0 nada | 1 reto: x, y px | 2 radial: centro x, y, ln da escala)

vec3 cvToLegal(vec3 v) { return (v * 1023.0 - 64.0) / 876.0; }
vec3 trDec(vec3 c) { return toLinear(c, u_tr_input, u_tr_cv == 1); }
// Inversa de toLinear (sem o gamut: as misturas e os ganhos valem igual antes ou depois dele).
vec3 trEnc(vec3 n) {
    int id = u_tr_input;
    vec3 c;
    if (id == 0) c = stopsToDisp(linToStops(n));
    else if (id == 1) c = n;
    else if (id == 2) c = vec3(nlogEnc(n.r), nlogEnc(n.g), nlogEnc(n.b));
    else if (id == 3) c = vec3(slog3Enc(n.r), slog3Enc(n.g), slog3Enc(n.b));
    else if (id == 4) c = vec3(logc3Enc(n.r), logc3Enc(n.g), logc3Enc(n.b));
    else if (id == 5) c = vec3(vlogEnc(n.r), vlogEnc(n.g), vlogEnc(n.b));
    else if (id == 7) c = vec3(diEnc(n.r), diEnc(n.g), diEnc(n.b));
    else if (id == 8) c = vec3(l3g10Enc(n.r), l3g10Enc(n.g), l3g10Enc(n.b));
    else if (id == 9) c = vec3(bmd5Enc(n.r), bmd5Enc(n.g), bmd5Enc(n.b));
    else if (id == 10) c = vec3(logc4Enc(n.r), logc4Enc(n.g), logc4Enc(n.b));
    else if (id == 11) c = vec3(appleEnc(n.r), appleEnc(n.g), appleEnc(n.b));
    else if (id == 12) c = vec3(hlgEnc(n.r), hlgEnc(n.g), hlgEnc(n.b));
    else if (id == 13) c = pqEnc(n);
    else c = vec3(cineonEnc(n.r), cineonEnc(n.g), cineonEnc(n.b));
    return u_tr_cv == 1 ? cvToLegal(c) : c;
}
// O preto da curva: sem luz nenhuma (no vídeo comum, o 0).
vec3 trBlack() { return u_tr_input == 0 ? vec3(0.0) : trEnc(vec3(0.0)); }

// Mistura na luz (as exposições somam): w = 0 dá a e w = 1 dá b, exatos; no meio, a mistura das luzes
// reescrita na curva, corrigida pelo desvio de ida e volta da curva (zero onde a curva volta exata).
// Canal a canal: o cinza continua cinza.
vec3 lightMix(vec3 a, vec3 b, float w) {
    if (w <= 0.0) return a;
    if (w >= 1.0) return b;
    vec3 la = trDec(a), lb = trDec(b);
    return mix(a, b, w) + trEnc(mix(la, lb, w)) - mix(trEnc(la), trEnc(lb), w);
}
// Ganho g na luz (abrir ou fechar a luz da copiadora): 1 devolve c, 0 o preto da curva, exatos.
vec3 lightGain(vec3 c, float g) {
    if (g >= 1.0) return c;
    vec3 B = trBlack();
    if (g <= 0.0) return B;
    vec3 lc = trDec(c);
    return mix(B, c, g) + trEnc(lc * g) - mix(trEnc(vec3(0.0)), trEnc(lc), g);
}
// Luz × m + add (clarão, brilho da queima, anel): m = 1 e add = 0 devolvem c exato.
vec3 lightAffine(vec3 c, vec3 m, vec3 add) {
    if (all(equal(m, vec3(1.0))) && all(equal(add, vec3(0.0)))) return c;
    vec3 lc = trDec(c);
    return c + trEnc(lc * m + add) - trEnc(lc);
}

// Amostra do clipe (RGBA pré-multiplicado; textura sem alfa = opaca), com o desfoque de movimento do empurrar
// (reto) e do zoom (radial) quando ele passa de meio pixel.
vec4 trTex(vec2 uv) {
    vec4 s = texture(t_clip, uv);
    return u_tex_alpha == 1 ? s : vec4(s.rgb, 1.0);
}
vec4 trSample(ivec2 ip, vec2 q, vec2 uv) {
    if (u_tr_blur.x < 0.5) {
        vec4 s = u_exact == 1 ? texelFetch(t_clip, ip, 0) : texture(t_clip, uv);
        return u_tex_alpha == 1 ? s : vec4(s.rgb, 1.0);
    }
    vec4 acc = vec4(0.0);
    for (int k = 0; k < 9; k++) {
        float t = float(k) / 8.0 - 0.5;
        vec2 qk = u_tr_blur.x < 1.5 ? q + u_tr_blur.yz * t
                                    : u_tr_blur.yz + (q - u_tr_blur.yz) * exp(-u_tr_blur.w * t);
        acc += trTex((u_xf * vec3(qk, 1.0)).xy);
    }
    return acc / 9.0;
}

// Queima: distância ao centro com o contorno irregular (fbm fixo na transição) e as borbulhas (mudam a cada
// quadro); sempre >= a distância de verdade, até 176 px@1080 a mais. O furo é onde ela fica abaixo do raio.
float burnDist(vec2 q, vec2 c, uint seed, float fr) {
    float sc = u_tr_scale;
    vec2 o = vec2(float(seed & 1023u), float((seed >> 10u) & 1023u)) * 0.731;
    float n = fbm2(q / (120.0 * sc) + o);
    float b = vnoise2(q / (26.0 * sc) + o.yx + vec2(0.0, fr * 0.45));
    return length(q - c) + (n * 150.0 + b * 26.0) * sc;
}
// Luz em volta do furo (delta = px até a borda; positivo = película ainda inteira): borda branca, halo
// laranja e, mais longe, a película chamuscada. k: força (0 nas pontas da transição).
void burnLight(float delta, float k, float flick, inout vec3 mul, inout vec3 add) {
    float G = 70.0 * u_tr_scale;
    float inside = delta < 0.0 ? exp(delta / (0.10 * G)) : 1.0;
    float rim = exp(-abs(delta) / (0.10 * G));
    float halo = exp(-max(delta, 0.0) / (0.45 * G)) * inside;
    float scorch = exp(-max(delta, 0.0) / (1.4 * G)) * inside;
    add += k * flick * (rim * vec3(5.0, 4.2, 3.0) + halo * vec3(1.6, 0.55, 0.08));
    mul *= mix(vec3(1.0), vec3(0.42, 0.26, 0.14), k * 0.8 * scorch);
}
// Íris: 1 dentro do círculo de raio que cresce com o andamento (borda suave A.w), 0 fora.
float irisMask(vec2 q, vec4 A, float p, out float R) {
    float s = max(A.w, 1.0);
    R = p * (A.z + s);
    return clamp((R - length(q - A.xy)) / s, 0.0, 1.0);
}
// Ponta (película sem imagem): luz linear com poeira, riscos e, no quadro do meio, o furo de perfuração.
vec3 leaderLight(vec2 q, vec4 A, vec4 B, uint seed, int idx) {
    float sc = u_tr_scale;
    bool clear = A.x > 0.5;
    uint fr = uint(idx);
    float flick = rnd(uvec3(seed, fr, 401u));
    vec3 lin = clear ? vec3(1.10, 1.02, 0.86) * (0.94 + 0.12 * flick) : vec3(0.0025 + 0.002 * flick);
    float cell = 40.0 * sc;
    ivec2 cc = ivec2(floor(q / cell));
    float dust = 0.0;
    for (int dy = -1; dy <= 1; dy++) {
        for (int dx = -1; dx <= 1; dx++) {
            ivec2 ce = cc + ivec2(dx, dy);
            uvec3 key = uvec3(uint(ce.x + 32768), uint(ce.y + 32768), seed ^ (fr * 7919u + 13u));
            if (rnd(key) < 0.05) {
                vec2 ctr = (vec2(ce) + vec2(rnd(key + uvec3(0u, 0u, 1u)), rnd(key + uvec3(0u, 0u, 2u)))) * cell;
                float rad = (1.2 + 4.0 * pow(rnd(key + uvec3(0u, 0u, 3u)), 2.0)) * sc;
                dust = max(dust, clamp(rad - length(q - ctr) + 0.5, 0.0, 1.0));
            }
        }
    }
    float scr = 0.0;
    int ns = 1 + int(rnd(uvec3(seed, 0u, 402u)) * 3.0);
    for (int k = 0; k < 3; k++) {
        if (k >= ns) break;
        float x = (0.1 + 0.8 * rnd(uvec3(seed, uint(k), 403u))) * u_canvas.x
                + (rnd(uvec3(seed + uint(k), fr, 404u)) - 0.5) * 4.0 * sc;
        float wd = (1.0 + 1.5 * rnd(uvec3(seed, uint(k), 405u))) * sc;
        float along = 0.6 + 0.4 * sin(q.y / (90.0 * sc) + float(k) * 2.3 + float(idx) * 0.9);
        scr = max(scr, clamp(wd * 0.5 - abs(q.x - x) + 0.5, 0.0, 1.0) * along);
    }
    if (clear) lin *= (1.0 - 0.85 * dust) * (1.0 - 0.6 * scr);
    else lin += vec3(0.9) * dust + vec3(0.35) * scr;
    float hole = B.x > 0.5 ? clamp(A.w - length(q - A.yz) + 0.5, 0.0, 1.0) : 0.0;
    return mix(lin, vec3(6.0), hole);
}
"""

_TR_MAIN = """
void main() {
    ivec2 ip = ivec2(gl_FragCoord.xy);
    vec2 q = gl_FragCoord.xy;
    vec4 dst = texelFetch(t_dst, ip, 0);
    vec2 uv = (u_xf * vec3(q, 1.0)).xy;
    vec2 lo = u_crop.xy;
    vec2 hi = 1.0 - u_crop.zw;
    vec2 dd = min(uv - lo, hi - uv) * u_px_per_uv;
    float cover = clamp(min(dd.x, dd.y) + 0.5, 0.0, 1.0);
    float a = cover * u_alpha;
    if (a <= 0.0) {
        f_out = dst;
        return;
    }
    vec4 s = trSample(ip, q, uv);
    vec3 c;
    if (u_tex_alpha == 1) {
        a *= clipAlpha(s.a);
        if (a <= 0.0) {
            f_out = dst;
            return;
        }
        c = s.rgb / max(s.a, 1e-6);
    } else {
        c = s.rgb;
    }
    if (u_det_on == 1) c = detail(uv, c);
    if (u_cc_on == 1) {
        c = colorCorrect(c);
        if (u_vig.x != 0.0) {
            vec2 pv = (uv - 0.5) * 2.0;
            pv.x *= u_clip_px.x / u_clip_px.y;
            float dn = length(pv) / length(vec2(u_clip_px.x / u_clip_px.y, 1.0));
            float v = smoothstep(u_vig.y * 0.8, u_vig.y * 0.8 + 0.6, dn);
            c *= exp2(u_vig.x * 1.6 * v);
        }
        if (u_fadeblk > 0.0) c = c * (1.0 - 0.22 * u_fadeblk) + 0.09 * u_fadeblk;
        c = max(c, vec3(0.0));
    }
    // Transições: o que muda na cor do clipe, o peso dele na mistura (w, na luz) e a luz por cima (queima, anel).
    float w = 1.0;
    vec3 mulO = vec3(1.0);
    vec3 addO = vec3(0.0);
    for (int i = 0; i < 2; i++) {
        int kind = u_tr_kind[i];
        int role = u_tr_role[i];
        if (kind == 0 || role == 2) continue;  // base: só a geometria (em u_xf) e o desfoque
        float p = u_tr_p[i];
        vec4 A = u_tr_a[i];
        vec4 B = u_tr_b[i];
        uint seed = uint(u_tr_seed[i]);
        int idx = u_tr_index[i];
        if (kind == 1) {                                   // fusão ótica
            w *= p;
        } else if (kind == 2) {                            // exposição: a luz sobe (ou desce) do preto
            c = lightGain(c, role == 0 ? p : 1.0 - p);
        } else if (kind == 3) {                            // queima
            float sw = max(A.w * 0.5, 1.0);
            float R = pow(p, 1.4) * (A.z + 400.0 * u_tr_scale + sw);
            float dn = burnDist(q, A.xy, seed, float(idx));
            float m = clamp((R - dn) / sw, 0.0, 1.0);
            w *= role == 0 ? m : 1.0 - m;
            float k = smoothstep(0.0, 0.05, p) * (1.0 - smoothstep(0.9, 1.0, p));
            float flick = 0.85 + 0.3 * rnd(uvec3(seed, uint(idx), 301u));
            if (k > 0.0) burnLight(dn - R, k, flick, mulO, addO);
        } else if (kind == 4) {                            // emenda: clarão, linha da emenda e véu da fita
            c = lightAffine(c, vec3(A.x), vec3(A.y));
            if (A.w > 0.5) {
                float sc = u_tr_scale;
                float dy = q.y - A.z;
                float line = clamp(1.25 * sc - abs(dy) + 0.5, 0.0, 1.0);
                float side = dy * B.x;
                float band = clamp(side / (1.5 * sc), 0.0, 1.0) * clamp((16.0 * sc - side) / (3.0 * sc), 0.0, 1.0);
                c = lightAffine(c, vec3((1.0 - 0.8 * line) * (1.0 - 0.25 * band)), vec3(0.05 * band));
            }
        } else if (kind == 5) {                            // ponta
            c = trEnc(leaderLight(q, A, B, seed, idx));
        } else if (kind == 6) {                            // íris (abre ao entrar, fecha ao sair)
            float pp = role == 0 ? p : 1.0 - p;
            float R;
            float m = irisMask(q, A, pp, R);
            w *= m;
            float ring = B.x * min(1.0, pp * 10.0);
            if (ring > 0.0) {
                float ra = clamp(R + ring - length(q - A.xy) + 0.5, 0.0, 1.0) * (1.0 - m);
                mulO *= 1.0 - ra;
            }
        } else if (kind == 8) {                            // cortina
            float sw = max(A.w, 1.0);
            float pos = dot(q, A.xy) + A.z;
            w *= clamp((p * (B.x + sw) - pos) / sw, 0.0, 1.0);
        } else if (kind == 9 && role == 0) {               // zoom: a troca acontece no meio, na luz
            w *= smoothstep(0.35, 0.65, p);
        }
        // 7 empurrar: só a geometria e o desfoque
    }
    if (u_fade.w > 0.0) c = mix(c, u_fade.rgb, u_fade.w);
    vec3 res = blend(dst.rgb, c);
    vec3 T = lightMix(dst.rgb, res, w);
    vec3 o = w <= 0.0 ? dst.rgb : (a >= 1.0 ? T : mix(dst.rgb, T, a));
    if (any(notEqual(mulO, vec3(1.0))) || any(notEqual(addO, vec3(0.0))))
        o = lightAffine(o, mix(vec3(1.0), mulO, a), addO * a);
    f_out = vec4(o, 1.0);
}
"""

CLIP_TR = CLIP.split("void main() {")[0] + _CURVES + _TR_FUNCS + _TR_MAIN
