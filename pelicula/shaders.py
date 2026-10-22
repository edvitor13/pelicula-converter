"""Shaders GLSL do motor. Coordenadas de imagem com y para baixo (linha 0 = topo)."""

VERT = """
#version 330
in vec2 in_pos;
out vec2 v_uv;
void main() {
    v_uv = in_pos * 0.5 + 0.5;
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
"""

COMMON = """
#version 330
in vec2 v_uv;
out vec4 f_out;

const vec3 W709 = vec3(0.2126, 0.7152, 0.0722);
const float D_SLOPE = 0.155;
const float D_MID = 0.45;
const float D_P = 4.0;
const float CIN_BLACK = 0.010797752;

float log10f(float x) { return log(max(x, 1e-10)) * 0.4342944819; }

uint pcg(uint v) {
    uint state = v * 747796405u + 2891336453u;
    uint word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
    return (word >> 22u) ^ word;
}
float rnd(uvec3 p) { return float(pcg(p.x + pcg(p.y + pcg(p.z)))) * (1.0 / 4294967296.0); }

float vnoise2(vec2 x) {
    vec2 i = floor(x);
    vec2 f = fract(x);
    vec2 u = f * f * (3.0 - 2.0 * f);
    uvec2 b = uvec2(ivec2(i) + 65536);
    float a = rnd(uvec3(b, 911u));
    float c = rnd(uvec3(b + uvec2(1u, 0u), 911u));
    float d = rnd(uvec3(b + uvec2(0u, 1u), 911u));
    float e = rnd(uvec3(b + uvec2(1u, 1u), 911u));
    return mix(mix(a, c, u.x), mix(d, e, u.x), u.y);
}
float fbm2(vec2 x) {
    float v = 0.0;
    float a = 0.5;
    for (int i = 0; i < 4; i++) {
        v += a * vnoise2(x);
        x = x * 2.03 + 17.0;
        a *= 0.5;
    }
    return v / 0.9375;
}
float sdRound(vec2 p, vec2 hb, float r) {
    vec2 q = abs(p) - hb + r;
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}

float softclip(float u, float p) { return u / pow(1.0 + pow(abs(u), p), 1.0 / p); }
float softclipInv(float v, float p) {
    float a = min(abs(v), 0.99995);
    return sign(v) * a / pow(1.0 - pow(a, p), 1.0 / p);
}
float curve(float t, float slope, float mid, float black, float white, float ps, float pt) {
    if (t >= 0.0) { float r = max(white - mid, 1e-4); return mid + r * softclip(t * slope / r, ps); }
    float r = max(mid - black, 1e-4);
    return mid + r * softclip(t * slope / r, pt);
}
float curveInv(float y, float slope, float mid, float black, float white, float ps, float pt) {
    if (y >= mid) { float r = max(white - mid, 1e-4); return softclipInv((y - mid) / r, ps) * r / slope; }
    float r = max(mid - black, 1e-4);
    return softclipInv((y - mid) / r, pt) * r / slope;
}
vec3 dispToStops(vec3 y) {
    vec3 t = vec3(curveInv(y.r, D_SLOPE, D_MID, 0.0, 1.0, D_P, D_P),
                  curveInv(y.g, D_SLOPE, D_MID, 0.0, 1.0, D_P, D_P),
                  curveInv(y.b, D_SLOPE, D_MID, 0.0, 1.0, D_P, D_P));
    return clamp(t, -12.0, 12.0);
}
vec3 stopsToDisp(vec3 t) {
    return vec3(curve(t.r, D_SLOPE, D_MID, 0.0, 1.0, D_P, D_P),
                curve(t.g, D_SLOPE, D_MID, 0.0, 1.0, D_P, D_P),
                curve(t.b, D_SLOPE, D_MID, 0.0, 1.0, D_P, D_P));
}
vec3 linToStops(vec3 lin) { return clamp(log2(max(lin, vec3(1e-7)) / 0.18), -12.0, 12.0); }
vec3 stopsToLin(vec3 t) { return 0.18 * exp2(t); }

float nlogDec(float y) { float c = y * 1023.0; return (c < 452.0) ? pow(max(c / 650.0, 0.0), 3.0) - 0.0075 : exp((c - 619.0) / 150.0); }
float nlogEnc(float x) { return (x < 0.328) ? 650.0 * pow(max(x + 0.0075, 0.0), 1.0 / 3.0) / 1023.0 : (150.0 * log(x) + 619.0) / 1023.0; }
float slog3Dec(float y) {
    float c = y * 1023.0;
    return (c >= 171.2102946929) ? pow(10.0, (c - 420.0) / 261.5) * 0.19 - 0.01 : (c - 95.0) * 0.01125 / (171.2102946929 - 95.0);
}
float slog3Enc(float x) {
    return (x >= 0.01125) ? (420.0 + log10f((x + 0.01) / 0.19) * 261.5) / 1023.0 : (x * (171.2102946929 - 95.0) / 0.01125 + 95.0) / 1023.0;
}
float logc3Dec(float t) { return (t > 0.149658) ? (pow(10.0, (t - 0.385537) / 0.247190) - 0.052272) / 5.555556 : (t - 0.092809) / 5.367655; }
float logc3Enc(float x) { return (x > 0.010591) ? 0.247190 * log10f(5.555556 * x + 0.052272) + 0.385537 : 5.367655 * x + 0.092809; }
float vlogDec(float y) { return (y < 0.181) ? (y - 0.125) / 5.6 : pow(10.0, (y - 0.598206) / 0.241514) - 0.00873; }
float vlogEnc(float x) { return (x < 0.01) ? 5.6 * x + 0.125 : 0.241514 * log10f(x + 0.00873) + 0.598206; }
float cineonDec(float y) { return (pow(10.0, (y * 1023.0 - 685.0) / 300.0) - CIN_BLACK) / (1.0 - CIN_BLACK); }
float cineonEnc(float x) { return (685.0 + 300.0 * log10f(max(x * (1.0 - CIN_BLACK) + CIN_BLACK, 1e-6))) / 1023.0; }
float diDec(float y) { return (y <= 0.02740668) ? y / 10.44426855 : exp2(y / 0.07329248 - 7.0) - 0.0075; }
float diEnc(float x) { return (x <= 0.00262409) ? x * 10.44426855 : (log2(max(x + 0.0075, 1e-10)) + 7.0) * 0.07329248; }
float l3g10Dec(float y) { return (y < 0.0) ? y / 15.1927 - 0.01 : (pow(10.0, y / 0.224282) - 1.0) / 155.975327 - 0.01; }
float l3g10Enc(float x) { float v = x + 0.01; return (v < 0.0) ? v * 15.1927 : 0.224282 * log10f(v * 155.975327 + 1.0); }
// Blackmagic Film Gen 5: y = D·x + E abaixo de 0,005; acima, A·ln(x + B) + C (corte em 0,13388378 no código).
float bmd5Dec(float y) {
    return (y < 0.13388378308667) ? (y - 0.09246575342465753) / 8.283605932402494
                                  : exp((y - 0.5300133392291939) / 0.08692876065491224) - 0.005494072432257808;
}
float bmd5Enc(float x) {
    return (x < 0.005) ? 8.283605932402494 * x + 0.09246575342465753
                       : 0.08692876065491224 * log(x + 0.005494072432257808) + 0.5300133392291939;
}
// ARRI LogC4: a = (2^18 − 16)/117,45, b = 928/1023, c = 95/1023, s e t derivados (especificação da ARRI).
const float C4A = 2231.8263090676883;
const float C4B = 0.9071358748778103;
const float C4C = 0.09286412512218964;
const float C4S = 0.1135972086105891;
const float C4T = -0.01805699611991131;
float logc4Dec(float e) { return (e >= 0.0) ? (exp2(14.0 * (e - C4C) / C4B + 6.0) - 64.0) / C4A : e * C4S + C4T; }
float logc4Enc(float x) { return (x >= C4T) ? (log2(C4A * x + 64.0) - 6.0) / 14.0 * C4B + C4C : (x - C4T) / C4S; }
// Apple Log: γ·log2(R + β) + δ acima de Rt = 0,01; σ·(R − R0)² entre R0 e Rt; 0 abaixo de R0.
float appleDec(float p) {
    if (p >= 0.20855531595464202) return exp2((p - 0.69336945) / 0.08550479) - 0.00964052;
    return (p >= 0.0) ? sqrt(p / 47.28711236) - 0.05641088 : -0.05641088;
}
float appleEnc(float r) {
    if (r >= 0.01) return 0.08550479 * log2(r + 0.00964052) + 0.69336945;
    return (r >= -0.05641088) ? 47.28711236 * (r + 0.05641088) * (r + 0.05641088) : 0.0;
}
// HLG (ITU-R BT.2100): inverso da OETF, E′ → luz de cena E (0..1), × HLG_K: o cinza de referência da
// BT.2408 (38% do sinal) vira 0,18 e o branco de referência (75%) ≈ 0,99 (look.HLG_SCALE).
// Abaixo de 0 (pé da faixa legal) a curva é espelhada: monotônica e sem NaN.
const float HLG_A = 0.17883277;
const float HLG_B = 0.28466892;
const float HLG_C = 0.55991073;
const float HLG_K = 3.739612188365651;
float hlgDec(float e) {
    if (e <= 0.5) return e * abs(e) / 3.0 * HLG_K;
    return (exp((e - HLG_C) / HLG_A) + HLG_B) / 12.0 * HLG_K;
}
float hlgEnc(float x) {
    float e = x / HLG_K;
    if (e <= 1.0 / 12.0) return sign(e) * sqrt(3.0 * abs(e));
    return HLG_A * log(12.0 * e - HLG_B) + HLG_C;
}
// PQ (SMPTE ST 2084 / BT.2100): E′ → luz da tela em cd/m² (aqui ÷ 1000) → OOTF inversa do HLG com pico
// nominal de 1000 cd/m² (γ = 1,2 pela luminância BT.2100, como na conversão PQ → HLG da BT.2408) → luz
// de cena → × HLG_K. 26 cd/m² (cinza da BT.2408) ≈ 0,18; 203 cd/m² ≈ 0,99. Acima de 1000 cd/m² a luz
// continua subindo, sem corte (4000 cd/m² ≈ 11,9; 10000 ≈ 25,5) e a curva do filme comprime.
const float PQ_M1 = 0.1593017578125;
const float PQ_M2 = 78.84375;
const float PQ_C1 = 0.8359375;
const float PQ_C2 = 18.8515625;
const float PQ_C3 = 18.6875;
const vec3 W2020 = vec3(0.2627, 0.6780, 0.0593);
vec3 pqDec(vec3 e) {
    vec3 p = pow(max(e, vec3(0.0)), vec3(1.0 / PQ_M2));
    vec3 f = 10.0 * pow(max(p - PQ_C1, vec3(0.0)) / max(PQ_C2 - PQ_C3 * p, vec3(1e-6)), vec3(1.0 / PQ_M1));
    return f * pow(max(dot(f, W2020), 1e-10), -1.0 / 6.0) * HLG_K;  // E = F·Y^((1 − γ)/γ)
}
vec3 pqEnc(vec3 x) {
    vec3 s = max(x / HLG_K, vec3(0.0));
    vec3 t = pow(s * pow(max(dot(s, W2020), 1e-10), 0.2) * 0.1, vec3(PQ_M1));  // F = E·Y^(γ − 1), ÷ 10000
    return pow((PQ_C1 + PQ_C2 * t) / (1.0 + PQ_C3 * t), vec3(PQ_M2));
}

// Curvas em código de 10 bits (look.INPUT_DOMAIN == "cv"): o decodificador expande a faixa legal
// (v = (código − 64)/876) e a fórmula do fabricante espera CV = código/1023.
vec3 legalToCv(vec3 v) { return (v * 876.0 + 64.0) / 1023.0; }

// Valor do vídeo → luz linear da cena. cv: a curva é em código de 10 bits e a fonte veio em faixa
// legal expandida (u_input_cv e u_legal): volta ao código da câmera antes da fórmula.
vec3 toLinear(vec3 c, int id, bool cv) {
    if (cv) c = legalToCv(c);
    if (id == 0) return stopsToLin(dispToStops(c));
    if (id == 1) return c;
    if (id == 2) return vec3(nlogDec(c.r), nlogDec(c.g), nlogDec(c.b));
    if (id == 3) return vec3(slog3Dec(c.r), slog3Dec(c.g), slog3Dec(c.b));
    if (id == 4) return vec3(logc3Dec(c.r), logc3Dec(c.g), logc3Dec(c.b));
    if (id == 5) return vec3(vlogDec(c.r), vlogDec(c.g), vlogDec(c.b));
    if (id == 7) return vec3(diDec(c.r), diDec(c.g), diDec(c.b));
    if (id == 8) return vec3(l3g10Dec(c.r), l3g10Dec(c.g), l3g10Dec(c.b));
    if (id == 9) return vec3(bmd5Dec(c.r), bmd5Dec(c.g), bmd5Dec(c.b));
    if (id == 10) return vec3(logc4Dec(c.r), logc4Dec(c.g), logc4Dec(c.b));
    if (id == 11) return vec3(appleDec(c.r), appleDec(c.g), appleDec(c.b));
    if (id == 12) return vec3(hlgDec(c.r), hlgDec(c.g), hlgDec(c.b));
    if (id == 13) return pqDec(c);
    return vec3(cineonDec(c.r), cineonDec(c.g), cineonDec(c.b));
}

// ---------------------------------------------------------------- cor
uniform int u_film_on;
uniform float u_film_mix;
uniform float u_slope;
uniform float u_mid;
uniform float u_black;
uniform float u_white;
uniform float u_ps;
uniform float u_pt;
uniform float u_sat;
uniform float u_density;
uniform vec3 u_ch_gamma;
uniform vec3 u_ch_offset;
uniform vec3 u_shadow_tint;
uniform vec3 u_high_tint;
uniform float u_balance;
uniform vec3 u_hue;
uniform vec2 u_skin;  // pele: giro de matiz (rad), luz (-1..1)
uniform int u_bw;
uniform vec3 u_bw_w;
uniform float u_tone_amt;
uniform vec3 u_tone_sh;
uniform vec3 u_tone_hi;
uniform float u_age;
uniform int u_print_on;
uniform float u_print_amt;
uniform float u_pr_slope;
uniform float u_pr_mid;
uniform float u_pr_black;
uniform float u_pr_white;
uniform float u_pr_ps;
uniform float u_pr_pt;
uniform float u_pr_sat;
uniform vec3 u_pr_gamma;
uniform vec3 u_pr_offset;
uniform int u_lut_on;
uniform float u_lut_amt;
uniform int u_lut_pos;
uniform int u_lut_in;
uniform float u_lut_size;
uniform vec3 u_lut_dmin;
uniform vec3 u_lut_dmax;
uniform mat3 u_lut_gamut;
uniform sampler3D t_lut;

float hueAng(vec3 c) { float Y = dot(c, W709); return atan((c.r - Y) / 1.5748, (c.b - Y) / 1.8556); }
float hueWeight(float h, float h0) {
    float d = abs(mod(h - h0 + 3.14159265, 6.2831853) - 3.14159265);
    return smoothstep(0.8, 0.0, d);
}
vec3 hueAdjust(vec3 c) {
    if (u_hue == vec3(0.0) && u_skin == vec2(0.0)) return c;
    float Y = dot(c, W709);
    vec2 cc = vec2((c.b - Y) / 1.8556, (c.r - Y) / 1.5748);
    if (length(cc) < 1e-5) return c;
    float h = atan(cc.y, cc.x);
    float wg = hueWeight(h, hueAng(vec3(0.25, 0.6, 0.2)));
    float wb = hueWeight(h, hueAng(vec3(0.2, 0.35, 0.8)));
    float ws = hueWeight(h, hueAng(vec3(0.8, 0.55, 0.45)));
    float rot = u_hue.x * wg + u_hue.y * wb + u_skin.x * ws;
    float cs = cos(rot), sn = sin(rot);
    cc = vec2(cs * cc.x - sn * cc.y, sn * cc.x + cs * cc.y);
    cc *= max(0.0, 1.0 + u_hue.z * ws);
    Y *= 1.0 + 0.25 * u_skin.y * ws;  // luz da pele: até ±25% na luminância dos tons de pele
    float r = Y + 1.5748 * cc.y;
    float b = Y + 1.8556 * cc.x;
    float g = (Y - 0.2126 * r - 0.0722 * b) / 0.7152;
    return vec3(r, g, b);
}

vec3 filmLook(vec3 lin) {
    vec3 l2 = lin;
    if (u_bw == 1) l2 = vec3(dot(lin, u_bw_w));
    vec3 t = clamp(linToStops(l2), -10.0, 9.0);
    float ta = dot(t, W709);
    t = ta + (t - ta) * u_sat;
    t = t * u_ch_gamma + u_ch_offset;
    vec3 y = vec3(curve(t.r, u_slope, u_mid, u_black, u_white, u_ps, u_pt),
                  curve(t.g, u_slope, u_mid, u_black, u_white, u_ps, u_pt),
                  curve(t.b, u_slope, u_mid, u_black, u_white, u_ps, u_pt));
    float mx = max(y.r, max(y.g, y.b));
    float mn = min(y.r, min(y.g, y.b));
    y *= 1.0 - u_density * 0.45 * (mx - mn);
    y = hueAdjust(y);
    float lum = dot(y, W709);
    float piv = clamp(0.45 + 0.3 * u_balance, 0.1, 0.9);
    float ws = 1.0 - smoothstep(0.0, piv, lum);
    float wh = smoothstep(piv, 1.0, lum);
    y += u_shadow_tint * ws + u_high_tint * wh;
    if (u_bw == 1 && u_tone_amt > 0.0) {
        float L = clamp(dot(y, W709), 0.0, 1.0);
        vec3 toned = L * mix(u_tone_sh, u_tone_hi, smoothstep(0.0, 1.0, L));
        y = mix(y, toned, u_tone_amt);
    }
    return y;
}

vec3 printStage(vec3 y) {
    vec3 t = dispToStops(y);
    float ta = dot(t, W709);
    t = ta + (t - ta) * u_pr_sat;
    t = t * u_pr_gamma + u_pr_offset;
    return vec3(curve(t.r, u_pr_slope, u_pr_mid, u_pr_black, u_pr_white, u_pr_ps, u_pr_pt),
                curve(t.g, u_pr_slope, u_pr_mid, u_pr_black, u_pr_white, u_pr_ps, u_pr_pt),
                curve(t.b, u_pr_slope, u_pr_mid, u_pr_black, u_pr_white, u_pr_ps, u_pr_pt));
}

vec3 aged(vec3 y) {
    float L = dot(y, W709);
    vec3 c = mix(vec3(L), y, 0.6);
    c = c * 0.82 + 0.075;
    return c * vec3(1.07, 0.93, 0.98);
}

// Luz linear → valor que o LUT externo espera, no domínio da própria curva (look.INPUT_DOMAIN): o código
// de 10 bits (código/1023) no S-Log3, V-Log e N-Log — a convenção dos LUTs dos fabricantes ("Full") e das
// IDTs do ACES —, o sinal nas outras. Não depende da faixa do arquivo de origem.
vec3 lutEncode(vec3 lin, int id) {
    if (id == 0) return stopsToDisp(linToStops(lin));
    vec3 n = u_lut_gamut * lin;
    if (id == 1) return n;
    if (id == 2) return vec3(nlogEnc(n.r), nlogEnc(n.g), nlogEnc(n.b));
    if (id == 3) return vec3(slog3Enc(n.r), slog3Enc(n.g), slog3Enc(n.b));
    if (id == 4) return vec3(logc3Enc(n.r), logc3Enc(n.g), logc3Enc(n.b));
    if (id == 5) return vec3(vlogEnc(n.r), vlogEnc(n.g), vlogEnc(n.b));
    if (id == 7) return vec3(diEnc(n.r), diEnc(n.g), diEnc(n.b));
    if (id == 8) return vec3(l3g10Enc(n.r), l3g10Enc(n.g), l3g10Enc(n.b));
    if (id == 9) return vec3(bmd5Enc(n.r), bmd5Enc(n.g), bmd5Enc(n.b));
    if (id == 10) return vec3(logc4Enc(n.r), logc4Enc(n.g), logc4Enc(n.b));
    if (id == 11) return vec3(appleEnc(n.r), appleEnc(n.g), appleEnc(n.b));
    if (id == 12) return vec3(hlgEnc(n.r), hlgEnc(n.g), hlgEnc(n.b));
    if (id == 13) return pqEnc(n);
    return vec3(cineonEnc(n.r), cineonEnc(n.g), cineonEnc(n.b));
}
vec3 sampleLut(vec3 c) {
    vec3 x = clamp((c - u_lut_dmin) / max(u_lut_dmax - u_lut_dmin, vec3(1e-6)), 0.0, 1.0);
    x = x * (u_lut_size - 1.0) / u_lut_size + 0.5 / u_lut_size;
    return texture(t_lut, x).rgb;
}

// ---------------------------------------------------------------- laboratório (negativo → cópia)
// Modelo de densidade (veja look.py): matriz de sensibilidade → curva do negativo → luz da
// copiadora − densidade → curva da cópia → diafonia dos corantes (+ chave/prata) → 10^(−D/2,6).
// Caminho A = negativo + cópia escolhidos; caminho B = processo Technicolor (misturado por u_lab_mix).
uniform int u_lab_on;
uniform int u_lab_b_on;
uniform float u_lab_mix;
uniform mat3 u_la_sens;
uniform vec3 u_la_ng;
uniform vec3 u_la_nt;
uniform vec3 u_la_ns;
uniform float u_la_nw;
uniform mat3 u_la_ii;
uniform vec3 u_la_pg;
uniform vec3 u_la_pt;
uniform vec3 u_la_ps;
uniform float u_la_pw;
uniform mat3 u_la_dye;
uniform vec3 u_la_off;
uniform vec3 u_la_key;
uniform vec3 u_la_mid;
uniform int u_la_scan;
uniform mat3 u_lb_sens;
uniform vec3 u_lb_ng;
uniform vec3 u_lb_nt;
uniform vec3 u_lb_ns;
uniform float u_lb_nw;
uniform mat3 u_lb_ii;
uniform vec3 u_lb_pg;
uniform vec3 u_lb_pt;
uniform vec3 u_lb_ps;
uniform float u_lb_pw;
uniform mat3 u_lb_dye;
uniform vec3 u_lb_off;
uniform vec3 u_lb_key;
uniform vec3 u_lb_mid;
uniform int u_lb_scan;
// Depois dos caminhos (look.LabPost). u_lab_ops: 2 rolagem das sombras/altas luzes, 4 saturação
// final, 8 densidade por cor, 16 pele. A separação de cores (Hue Split) já está em u_la_ii/u_lb_ii.
uniform int u_lab_ops;
uniform vec2 u_lab_tone;   // expoentes da curva de rolagem (altas luzes, sombras); 4 = sem mudança
uniform float u_lab_sat;
uniform vec3 u_lab_dens;   // densidade − 1 dos vermelhos, verdes e azuis
uniform vec2 u_lab_skin;   // pele: giro de matiz (rad), saturação (−1..1)

// softplus(z) = ln(1 + e^z), estável para |z| grande.
float labSoftplus(float z) { return max(z, 0.0) + log(1.0 + exp(-abs(z))); }

// Curva característica: densidade acima da base em função do log10 da exposição.
// D(x) = gama · w · [softplus((x − pé)/w) − softplus((x − ombro)/w)] (sempre crescente; satura em gama·(ombro − pé)).
vec3 labCurve(vec3 x, vec3 g, vec3 xt, vec3 xs, float w) {
    vec3 a = vec3(labSoftplus((x.r - xt.r) / w), labSoftplus((x.g - xt.g) / w), labSoftplus((x.b - xt.b) / w));
    vec3 b = vec3(labSoftplus((x.r - xs.r) / w), labSoftplus((x.g - xs.g) / w), labSoftplus((x.b - xs.b) / w));
    return g * w * (a - b);
}

// Um caminho completo. lin: luz linear Rec.709 (0,18 = cinza médio). Devolve o valor de exibição.
vec3 labPath(vec3 lin, mat3 sens, vec3 ng, vec3 nt, vec3 ns, float nw, mat3 ii, vec3 pg, vec3 pt, vec3 ps,
             float pw, mat3 dye, vec3 off, vec3 key, vec3 nmid, int scan) {
    vec3 e = max(sens * lin, vec3(1e-7));
    vec3 le = vec3(log10f(e.r / 0.18), log10f(e.g / 0.18), log10f(e.b / 0.18));  // log10 relativo ao cinza
    vec3 dn = ii * labCurve(le, ng, nt, ns, nw);  // densidade do negativo (com o efeito entre camadas)
    if (scan == 1) {
        // Sem cópia: inverte o negativo com o gama nominal (guardado em pg; 0,30103 = log10(2), um stop)
        // e mostra com a curva neutra.
        vec3 st = (dn - nmid) / (pg * 0.30103) - off / 0.30103;
        return stopsToDisp(clamp(st, -12.0, 12.0));
    }
    vec3 dl = labCurve(off - dn, pg, pt, ps, pw);  // densidade de cada camada de corante da cópia
    vec3 d = dye * dl + vec3(dot(key, dl));         // diafonia + chave preta / prata retida
    return exp2(-d * (3.32192809 / 2.6));           // 10^(−d/2,6): projeção com gama 2,6
}

// Pele: giro de matiz e saturação só nos tons de pele (mesmos pesos do hueAdjust do look).
vec3 labSkin(vec3 c, float rot, float sat) {
    float Y = dot(c, W709);
    vec2 cc = vec2((c.b - Y) / 1.8556, (c.r - Y) / 1.5748);
    if (length(cc) < 1e-5) return c;
    float ws = hueWeight(atan(cc.y, cc.x), hueAng(vec3(0.8, 0.55, 0.45)));
    float a = rot * ws;
    float cs = cos(a), sn = sin(a);
    cc = vec2(cs * cc.x - sn * cc.y, sn * cc.x + cs * cc.y) * max(0.0, 1.0 + sat * ws);
    float r = Y + 1.5748 * cc.y;
    float b = Y + 1.8556 * cc.x;
    float g = (Y - 0.2126 * r - 0.0722 * b) / 0.7152;
    return vec3(r, g, b);
}

// Depois da cópia, no valor de exibição: nada disso muda o cinza.
vec3 labPost(vec3 y) {
    if ((u_lab_ops & 2) != 0) {
        // rolagem: a curva neutra com outros expoentes nas pontas (cinza médio fica em 0,45)
        vec3 t = dispToStops(y);
        y = vec3(curve(t.r, D_SLOPE, D_MID, 0.0, 1.0, u_lab_tone.x, u_lab_tone.y),
                 curve(t.g, D_SLOPE, D_MID, 0.0, 1.0, u_lab_tone.x, u_lab_tone.y),
                 curve(t.b, D_SLOPE, D_MID, 0.0, 1.0, u_lab_tone.x, u_lab_tone.y));
    }
    if ((u_lab_ops & 4) != 0) {
        float L = dot(y, W709);
        y = vec3(L) + (y - vec3(L)) * u_lab_sat;
    }
    if ((u_lab_ops & 8) != 0) {
        // densidade por cor: quanto mais um canal domina, mais a cor escurece (ou clareia, abaixo de 1)
        vec3 w = vec3(max(0.0, y.r - max(y.g, y.b)), max(0.0, y.g - max(y.r, y.b)), max(0.0, y.b - max(y.r, y.g)));
        y *= clamp(1.0 - 0.5 * dot(u_lab_dens, w), 0.2, 2.0);
    }
    if ((u_lab_ops & 16) != 0) y = labSkin(y, u_lab_skin.x, u_lab_skin.y);
    return y;
}

vec3 labPipe(vec3 lin) {
    vec3 a = labPath(lin, u_la_sens, u_la_ng, u_la_nt, u_la_ns, u_la_nw, u_la_ii, u_la_pg, u_la_pt, u_la_ps,
                     u_la_pw, u_la_dye, u_la_off, u_la_key, u_la_mid, u_la_scan);
    if (u_lab_b_on == 0) return labPost(a);
    vec3 b = labPath(lin, u_lb_sens, u_lb_ng, u_lb_nt, u_lb_ns, u_lb_nw, u_lb_ii, u_lb_pg, u_lb_pt, u_lb_ps,
                     u_lb_pw, u_lb_dye, u_lb_off, u_lb_key, u_lb_mid, u_lb_scan);
    return labPost(mix(a, b, u_lab_mix));
}

vec3 colorPipe(vec3 lin) {
    // Laboratório primeiro: o resultado volta para luz linear e o resto (look, cópia, LUT) vem por cima.
    if (u_lab_on == 1) lin = stopsToLin(dispToStops(labPipe(lin)));
    vec3 neutral = stopsToDisp(linToStops(lin));
    vec3 y = neutral;
    if (u_lut_on == 1 && u_lut_pos == 1) {
        y = mix(neutral, sampleLut(lutEncode(lin, u_lut_in)), u_lut_amt);
        if (u_age > 0.0) y = mix(y, aged(y), u_age);
        return y;
    }
    if (u_film_on == 1) y = mix(neutral, filmLook(lin), u_film_mix);
    if (u_print_on == 1) y = mix(y, printStage(y), u_print_amt);
    if (u_age > 0.0) y = mix(y, aged(y), u_age);
    if (u_lut_on == 1) {
        vec3 inp = (u_lut_in == 0) ? y : lutEncode(stopsToLin(dispToStops(y)), u_lut_in);
        y = mix(y, sampleLut(inp), u_lut_amt);
    }
    return y;
}
"""

BASE = COMMON + """
uniform sampler2D t_in;
uniform vec2 u_res;
uniform vec2 u_shift;
uniform float u_rot;
uniform float u_zoom;
uniform float u_dist;
uniform float u_ca;
uniform int u_input;
uniform int u_input_cv;  // 1 = curva em código de 10 bits (look.INPUT_DOMAIN), arquivo sem log_reescalado
uniform int u_legal;     // 1 = a fonte veio em faixa legal expandida pelo decodificador (media.legal_range)
uniform mat3 u_gamut;
uniform vec3 u_gain;
uniform vec4 u_vig;

uniform int u_scan_on;
uniform vec4 u_scan_view;
uniform vec4 u_scan_img;
uniform vec4 u_scan_perf;
uniform vec3 u_scan_perf2;
uniform vec4 u_scan_text;
uniform int u_scan_fill;
uniform int u_scan_neighbors;
uniform vec3 u_scan_base;
uniform vec3 u_scan_light;
uniform vec3 u_scan_textcol;
uniform vec3 u_scan_outside;
uniform float u_scan_rough;
uniform sampler2D t_text;
uniform float u_text_aspect;

vec2 lens(vec2 uv, float k) {
    vec2 q = (uv - 0.5) * u_res / (0.5 * u_res.y);
    float rc2 = (u_res.x * u_res.x) / (u_res.y * u_res.y) + 1.0;
    q *= (1.0 + u_dist * dot(q, q)) / (1.0 + max(u_dist, 0.0) * rc2) * k;
    return q * (0.5 * u_res.y) / u_res + 0.5;
}

vec2 weave(vec2 uv) {
    vec2 p = (uv - 0.5) * u_res;
    p /= u_zoom;
    float c = cos(u_rot), s = sin(u_rot);
    p = vec2(c * p.x - s * p.y, s * p.x + c * p.y);
    p -= u_shift;
    return p / u_res + 0.5;
}

vec3 imageLin(vec2 uv) {
    vec3 code;
    if (u_ca != 0.0) {
        code = vec3(texture(t_in, lens(uv, 1.0 + u_ca)).r,
                    texture(t_in, lens(uv, 1.0)).g,
                    texture(t_in, lens(uv, 1.0 - u_ca)).b);
    } else {
        code = texture(t_in, lens(uv, 1.0)).rgb;
    }
    return max(u_gamut * toLinear(code, u_input, u_input_cv == 1 && u_legal == 1), vec3(0.0)) * exp2(u_gain);
}

float vignette(vec2 uv) {
    vec2 p = (uv - 0.5) * 2.0;
    float ax = mix(1.0, u_res.x / u_res.y, u_vig.w);
    p.x *= ax;
    float d = length(p) / length(vec2(ax, 1.0));
    float v = smoothstep(u_vig.y - u_vig.z * 0.5, u_vig.y + u_vig.z * 0.5, d);
    return exp2(-u_vig.x * 2.0 * v);
}

float edgeText(vec2 mm) {
    float m = 0.0;
    for (int side = 0; side < 2; side++) {
        float x0 = (side == 0) ? u_scan_text.x : u_scan_text.z;
        float x1 = (side == 0) ? u_scan_text.y : u_scan_text.w;
        if (x1 <= x0 || mm.x < x0 || mm.x > x1) continue;
        float bw = x1 - x0;
        float len = bw * u_text_aspect;
        float period = len * 1.45;
        float u = fract(mm.y / period + 0.37 * float(side)) * 1.45;
        if (u > 1.0) continue;
        float v = (mm.x - x0) / bw;
        if (side == 0) v = 1.0 - v; else u = 1.0 - u;
        m = max(m, texture(t_text, vec2(u, v)).r);
    }
    return m;
}

void main() {
    if (u_scan_on == 0) {
        f_out = vec4(imageLin(weave(v_uv)) * vignette(v_uv), 1.0);
        return;
    }
    // Scan da película: a tira inteira (furos, bordas e quadros) treme junto.
    vec2 suv = weave(v_uv);
    float mmpp = u_scan_view.z / u_res.x;
    vec2 mm = vec2(u_scan_view.w, 0.0) + (suv - 0.5) * u_res * mmpp;
    float aa = mmpp * 0.85;
    float pitch = u_scan_view.y;
    float k = floor(mm.y / pitch + 0.5);
    float yl = mm.y - k * pitch;
    vec2 c = vec2(0.5 * (u_scan_img.x + u_scan_img.y), 0.0);
    vec2 hb = vec2(0.5 * (u_scan_img.y - u_scan_img.x), 0.5 * u_scan_img.z);
    vec2 pl = vec2(mm.x, yl) - c;
    float sd = sdRound(pl, hb, u_scan_img.w);
    sd += u_scan_rough * (fbm2(vec2(mm.x, yl) * 6.0 + k * 3.7) - 0.5);
    float inImg = 1.0 - smoothstep(-aa, aa, sd);
    if (u_scan_neighbors == 0 && k != 0.0) inImg = 0.0;

    vec2 wuv = (pl + hb) / (2.0 * hb);
    float Aw = hb.x / hb.y;
    float Av = u_res.x / u_res.y;
    vec2 cuv = wuv;
    float inContent = 1.0;
    if (u_scan_fill == 0) {
        if (Av > Aw) {
            cuv.y = (wuv.y - 0.5) * (Av / Aw) + 0.5;
            float ey = (0.5 - abs(cuv.y - 0.5)) * 2.0 * hb.x / Av;
            inContent = smoothstep(-aa, aa, ey);
        } else {
            cuv.x = (wuv.x - 0.5) * (Aw / Av) + 0.5;
            float ex = (0.5 - abs(cuv.x - 0.5)) * 2.0 * hb.y * Av;
            inContent = smoothstep(-aa, aa, ex);
        }
    } else {
        if (Av > Aw) cuv.x = (wuv.x - 0.5) * (Aw / Av) + 0.5; else cuv.y = (wuv.y - 0.5) * (Av / Aw) + 0.5;
    }
    vec3 img = imageLin(clamp(cuv, 0.0, 1.0)) * vignette(clamp(cuv, 0.0, 1.0));
    img = mix(u_scan_base * 0.6, img, inContent);

    float density = 1.0 + 0.08 * (fbm2(mm * 0.35) - 0.5);
    vec3 lin = u_scan_base * density;
    if (u_text_aspect > 0.0) lin += u_scan_textcol * edgeText(mm);
    float period = u_scan_perf2.z;
    float yp = mm.y - (u_scan_perf2.y + period * floor((mm.y - u_scan_perf2.y) / period + 0.5));
    vec2 ph = vec2(0.5 * u_scan_perf.z, 0.5 * u_scan_perf.w);
    float hole = 1.0 - smoothstep(-aa, aa, sdRound(vec2(mm.x - u_scan_perf.x, yp), ph, u_scan_perf2.x));
    if (u_scan_perf.y > 0.0)
        hole = max(hole, 1.0 - smoothstep(-aa, aa, sdRound(vec2(mm.x - u_scan_perf.y, yp), ph, u_scan_perf2.x)));
    lin = mix(lin, u_scan_light, hole);
    lin = mix(lin, img, inImg);
    float edge = max(smoothstep(aa, -aa, mm.x), smoothstep(-aa, aa, mm.x - u_scan_view.x));
    lin = mix(lin, u_scan_outside, edge);
    f_out = vec4(lin, inImg);
}
"""

EXTRACT = COMMON + """
uniform sampler2D t_src;
uniform float u_thr;
uniform float u_limit;
uniform int u_lum_only;
uniform int u_use_alpha;
void main() {
    vec4 src = texture(t_src, v_uv);
    vec3 lin = src.rgb;
    float l = dot(lin, W709);
    float k = (u_thr > 0.0) ? smoothstep(u_thr * 0.5, u_thr * 1.5, l) : 1.0;
    if (u_use_alpha == 1) k *= src.a;
    vec3 e = lin * k;
    e = e / (1.0 + e / u_limit);
    if (u_lum_only == 1) e = vec3(dot(e, W709));
    f_out = vec4(e, 1.0);
}
"""

BLUR = COMMON + """
uniform sampler2D t_src;
uniform vec2 u_dir;
uniform float u_sigma;
uniform float u_lod;
void main() {
    float r = min(ceil(u_sigma * 3.0), 48.0);
    vec4 acc = vec4(0.0);
    float wsum = 0.0;
    float k = -0.5 / (u_sigma * u_sigma);
    for (float i = -r; i <= r; i += 1.0) {
        float w = exp(i * i * k);
        acc += textureLod(t_src, v_uv + u_dir * i, u_lod) * w;
        wsum += w;
    }
    f_out = acc / wsum;
}
"""

NOISE = COMMON + """
uniform int u_seed;
void main() {
    uvec2 q = uvec2(gl_FragCoord.xy);
    uint s = uint(u_seed) * 8u;
    float a1 = max(rnd(uvec3(q, s)), 1e-7);
    float a2 = rnd(uvec3(q, s + 1u));
    float b1 = max(rnd(uvec3(q, s + 2u)), 1e-7);
    float b2 = rnd(uvec3(q, s + 3u));
    float ra = sqrt(-2.0 * log(a1));
    float rb = sqrt(-2.0 * log(b1));
    f_out = vec4(ra * cos(6.2831853 * a2), ra * sin(6.2831853 * a2), rb * cos(6.2831853 * b2), rb * sin(6.2831853 * b2));
}
"""

FINAL = COMMON + """
uniform sampler2D t_in;
uniform sampler2D t_lin;
uniform sampler2D t_soft;
uniform sampler2D t_hal;
uniform sampler2D t_bloom;
uniform sampler2D t_mist;
uniform sampler2D t_noise;
uniform vec2 u_res;
uniform float u_scale;
uniform int u_frame;
uniform int u_seed_d;
uniform int u_soft_on;
uniform float u_soft_mix;
uniform float u_sharp;
uniform int u_mist_on;
uniform float u_mist_amt;
uniform int u_bloom_on;
uniform float u_bloom_amt;
uniform int u_hal_on;
uniform float u_hal_amt;
uniform vec3 u_hal_color;
uniform int u_leak_on;
uniform float u_leak_amt;
uniform vec3 u_leak_color;
uniform vec4 u_leak0;
uniform vec4 u_leak1;
uniform int u_grain_on;
uniform float u_grain_amt;
uniform float u_grain_rough;
uniform float u_grain_chroma;
uniform vec3 u_grain_resp;
uniform int u_dmg_on;
uniform float u_dust;
uniform float u_dust_size;
uniform int u_dust_type;
uniform float u_scratch;
uniform float u_scratch_w;
uniform vec4 u_hair;
uniform vec2 u_stain;
uniform float u_cue;
uniform vec2 u_splice;
uniform int u_frame_on;
uniform float u_aspect_t;
uniform float u_corner;
uniform float u_edge_soft;
uniform float u_edge_rough;
uniform vec3 u_bar_color;
uniform float u_mix;
uniform int u_dither;

vec4 cubicW(float v) {
    vec4 n = vec4(1.0, 2.0, 3.0, 4.0) - v;
    vec4 s = n * n * n;
    float x = s.x;
    float y = s.y - 4.0 * s.x;
    float z = s.z - 4.0 * s.y + 6.0 * s.x;
    float w = 6.0 - x - y - z;
    return vec4(x, y, z, w) * (1.0 / 6.0);
}
vec4 texBicubic(sampler2D s, vec2 uv) {
    vec2 ts = vec2(textureSize(s, 0));
    vec2 inv = 1.0 / ts;
    uv = uv * ts - 0.5;
    vec2 fxy = fract(uv);
    uv -= fxy;
    vec4 xc = cubicW(fxy.x);
    vec4 yc = cubicW(fxy.y);
    vec4 c = uv.xxyy + vec2(-0.5, 1.5).xyxy;
    vec4 s4 = vec4(xc.xz + xc.yw, yc.xz + yc.yw);
    vec4 off = (c + vec4(xc.yw, yc.yw) / s4) * inv.xxyy;
    vec4 s0 = texture(s, off.xz);
    vec4 s1 = texture(s, off.yz);
    vec4 s2 = texture(s, off.xw);
    vec4 s3 = texture(s, off.yw);
    float sx = s4.x / (s4.x + s4.y);
    float sy = s4.z / (s4.z + s4.w);
    return mix(mix(s3, s2, sx), mix(s1, s0, sx), sy);
}

vec3 applyGrain(vec3 y, vec2 uv) {
    vec4 nf = texBicubic(t_noise, uv) * 2.08;
    vec4 nc = texBicubic(t_noise, uv * 0.4347 + vec2(0.311, 0.173)) * 2.08;
    float r = u_grain_rough;
    vec4 n = (nf * (1.0 - r) + nc * r) / sqrt((1.0 - r) * (1.0 - r) + r * r);
    float c = u_grain_chroma;
    vec3 g = (vec3(n.a) * (1.0 - c) + n.rgb * c) / sqrt((1.0 - c) * (1.0 - c) + c * c);
    float L = clamp(dot(y, W709), 0.0, 1.0);
    float w = u_grain_resp.x * exp(-pow((L - 0.10) / 0.16, 2.0))
            + u_grain_resp.y * exp(-pow((L - 0.45) / 0.22, 2.0))
            + u_grain_resp.z * exp(-pow((L - 0.88) / 0.16, 2.0));
    return y + g * u_grain_amt * w;
}

vec3 leak(vec2 uv) {
    float a = u_res.x / u_res.y;
    vec3 acc = vec3(0.0);
    vec4 L0 = u_leak0;
    vec4 L1 = u_leak1;
    vec2 d0 = (uv - L0.xy) * vec2(a, 1.0);
    vec2 d1 = (uv - L1.xy) * vec2(a, 1.0);
    acc += exp(-dot(d0, d0) / max(L0.z * L0.z, 0.0025) * 2.0) * L0.w;
    acc += exp(-dot(d1, d1) / max(L1.z * L1.z, 0.0025) * 2.0) * L1.w;
    return u_leak_color * acc * u_leak_amt * 1.6;
}

float sdSeg(vec2 p, vec2 a, vec2 b) {
    vec2 pa = p - a;
    vec2 ba = b - a;
    return length(pa - ba * clamp(dot(pa, ba) / max(dot(ba, ba), 1e-6), 0.0, 1.0));
}

vec3 damage(vec3 y, vec2 uv) {
    vec2 px = uv * vec2(u_res.x / u_res.y, 1.0) * 1080.0;
    float Wd = u_res.x / u_res.y * 1080.0;
    if (u_stain.x > 0.0) {
        vec2 q = px / 1080.0 * 2.2 + vec2(u_stain.y * 7.31, u_stain.y * 3.17);
        float n = fbm2(q);
        float body = smoothstep(0.6, 0.71, n);
        float rim = smoothstep(0.56, 0.6, n) * (1.0 - smoothstep(0.6, 0.67, n));
        vec3 tint = (fract(u_stain.y * 0.37) < 0.5) ? vec3(1.2, 0.86, 1.12) : vec3(0.9, 1.12, 0.84);
        y = mix(y, y * tint * 1.08 + 0.04, body * u_stain.x);
        y *= 1.0 - 0.08 * rim * u_stain.x;
    }
    if (u_hair.x > 0.0) {
        uint hs = uint(u_hair.y);
        float side = floor(rnd(uvec3(hs, 1u, 77u)) * 4.0);
        float t0 = 0.12 + 0.76 * rnd(uvec3(hs, 2u, 77u));
        vec2 a;
        vec2 dir;
        if (side < 1.0) { a = vec2(t0 * Wd, -4.0); dir = vec2(0.0, 1.0); }
        else if (side < 2.0) { a = vec2(t0 * Wd, 1084.0); dir = vec2(0.0, -1.0); }
        else if (side < 3.0) { a = vec2(-4.0, t0 * 1080.0); dir = vec2(1.0, 0.0); }
        else { a = vec2(Wd + 4.0, t0 * 1080.0); dir = vec2(-1.0, 0.0); }
        float L = (120.0 + 200.0 * rnd(uvec3(hs, 3u, 77u))) * u_hair.z;
        vec2 perp = vec2(-dir.y, dir.x);
        float bend = (rnd(uvec3(hs, 4u, 77u)) - 0.5) * 0.9 * L;
        float curl = (0.05 + 0.1 * rnd(uvec3(hs, 5u, 77u))) * L;
        float ph = rnd(uvec3(hs, 6u, 77u)) * 6.2831853;
        float dmin = 1e9;
        vec2 prev = a;
        for (int i = 1; i <= 40; i++) {
            float t = float(i) / 40.0;
            float off = bend * t * t + curl * sin(t * 7.5 + ph) * t + u_hair.w * t * 1.5;
            vec2 b = a + dir * L * t * (0.75 + 0.25 * cos(t * 3.0 + ph)) + perp * off;
            dmin = min(dmin, sdSeg(px, prev, b));
            prev = b;
        }
        float th = 1.6 * u_hair.z;
        float m = 1.0 - smoothstep(th * 0.4, th + 1.4, dmin);
        y *= 1.0 - 0.9 * m;
    }
    if (u_cue > 0.0) {
        vec2 cc = vec2(Wd - 1080.0 * 0.105, 1080.0 * 0.1);
        float r = 1080.0 * 0.021;
        float d = length(px - cc) + (vnoise2(px * 0.3) - 0.5) * 2.2;
        float disc = smoothstep(r, r - 1.6, d);
        float rim = smoothstep(r + 2.6, r + 0.4, d) - disc;
        y = mix(y, vec3(0.025), disc * 0.9);
        y = mix(y, vec3(0.9, 0.88, 0.8), max(rim, 0.0) * 0.55);
    }
    if (u_splice.x > 0.0) {
        float yy = u_splice.y * 1080.0;
        float line = smoothstep(2.4, 0.4, abs(px.y - yy));
        float band = smoothstep(16.0, 11.0, abs(px.y - yy - 9.0));
        y = mix(y, vec3(0.9, 0.89, 0.84), line * 0.6);
        y *= 1.0 - 0.1 * band;
    }
    uint fr = uint(u_frame);
    uint sd = uint(u_seed_d);
    if (u_dust > 0.0) {
        float cell = 90.0;
        ivec2 c0 = ivec2(floor(px / cell));
        float dark = 0.0;
        float light = 0.0;
        for (int j = -1; j <= 1; j++) {
            for (int i = -1; i <= 1; i++) {
                ivec2 c = c0 + ivec2(i, j);
                uvec3 key = uvec3(uint(c.x + 100000), uint(c.y + 100000), fr * 131u + sd);
                if (rnd(key) < u_dust * 0.045) {
                    vec2 ctr = (vec2(c) + vec2(rnd(key + uvec3(0u, 0u, 1u)), rnd(key + uvec3(0u, 0u, 2u)))) * cell;
                    float rad = u_dust_size * (0.8 + 3.2 * pow(rnd(key + uvec3(0u, 0u, 3u)), 2.0));
                    float ang = rnd(key + uvec3(0u, 0u, 4u)) * 6.2831853;
                    float el = 1.0 + 3.0 * pow(rnd(key + uvec3(0u, 0u, 5u)), 3.0);
                    vec2 d = px - ctr;
                    d = vec2(cos(ang) * d.x + sin(ang) * d.y, -sin(ang) * d.x + cos(ang) * d.y);
                    d.x /= el;
                    float m = smoothstep(rad, rad * 0.45, length(d));
                    bool isLight = (u_dust_type == 1) || (u_dust_type == 2 && rnd(key + uvec3(0u, 0u, 6u)) < 0.5);
                    if (isLight) light = max(light, m); else dark = max(dark, m);
                }
            }
        }
        y = y * (1.0 - 0.88 * dark);
        y = mix(y, vec3(0.93, 0.92, 0.88), light * 0.85);
    }
    if (u_scratch > 0.0) {
        float W = u_res.x / u_res.y * 1080.0;
        uint epoch = uint(u_frame / 14);
        for (int k = 0; k < 6; k++) {
            uvec3 key = uvec3(uint(k) + 7000u, epoch, sd);
            if (rnd(key) < u_scratch * 0.4) {
                float x = rnd(key + uvec3(0u, 0u, 1u)) * W + 3.0 * sin(float(u_frame) * 0.37 + float(k))
                        + (rnd(uvec3(uint(k), fr, sd + 5u)) - 0.5) * 2.0;
                float w = u_scratch_w * (0.6 + 0.8 * rnd(key + uvec3(0u, 0u, 2u)));
                float a = smoothstep(1.0, 0.0, abs(px.x - x) / w);
                float along = 0.55 + 0.45 * sin(px.y * (0.004 + 0.01 * rnd(key + uvec3(0u, 0u, 3u))) + float(k) * 2.1 + float(u_frame) * 0.2);
                float vis = 0.35 + 0.65 * rnd(uvec3(uint(k) + 50u, fr, sd));
                y = mix(y, vec3(0.92, 0.93, 0.88), a * along * vis * 0.7);
            }
        }
    }
    return y;
}

float vnoise1(float x) {
    float i = floor(x);
    float fr = fract(x);
    float u = fr * fr * (3.0 - 2.0 * fr);
    float a = rnd(uvec3(uint(int(i) + 100000), 3u, 9u));
    float b = rnd(uvec3(uint(int(i) + 100001), 3u, 9u));
    return mix(a, b, u) * 2.0 - 1.0;
}

vec3 frameMask(vec3 y, vec2 uv) {
    if (u_aspect_t <= 0.0 && u_corner <= 0.0 && u_edge_rough <= 0.0) return y;
    float A = u_res.x / u_res.y;
    vec2 hb = vec2(0.5);
    if (u_aspect_t > 0.0) {
        if (u_aspect_t > A) hb.y = 0.5 * A / u_aspect_t; else hb.x = 0.5 * u_aspect_t / A;
    }
    vec2 p = (uv - 0.5) * u_res;
    vec2 h = hb * u_res + 0.5;
    float rad = u_corner * min(h.x, h.y) * 2.0;
    vec2 q = abs(p) - h + rad;
    float sd = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - rad;
    if (u_edge_rough > 0.0) {
        float n = vnoise1(p.x * 0.02 / u_scale + 13.0) + vnoise1(p.y * 0.02 / u_scale + 71.0)
                + 0.5 * vnoise1(p.x * 0.11 / u_scale) + 0.5 * vnoise1(p.y * 0.11 / u_scale + 5.0);
        sd += (n + 1.5) * u_edge_rough * 5.0 * u_scale;
    }
    float soft = max(u_edge_soft * u_res.y, 0.7);
    float m = 1.0 - smoothstep(-soft, soft, sd);
    return mix(u_bar_color, y, m);
}

void main() {
    vec2 uv = v_uv;
    vec3 code0 = texture(t_in, uv).rgb;
    vec3 lin = texture(t_lin, uv).rgb;
    if (u_soft_on == 1) {
        vec3 b = texture(t_soft, uv).rgb;
        vec3 base = mix(lin, b, u_soft_mix);
        lin = max(base + (lin - b) * u_sharp, vec3(0.0));
    }
    if (u_mist_on == 1) {
        vec3 m = texture(t_mist, uv).rgb;
        lin = mix(lin, m, 0.3 * u_mist_amt) + m * (0.35 * u_mist_amt);
    }
    if (u_bloom_on == 1) lin += texture(t_bloom, uv).rgb * u_bloom_amt;
    if (u_hal_on == 1) lin += texture(t_hal, uv).r * u_hal_color * u_hal_amt;
    if (u_leak_on == 1) lin += leak(uv);
    vec3 y = colorPipe(lin);
    if (u_grain_on == 1) y = applyGrain(y, uv);
    if (u_dmg_on == 1) y = damage(y, uv);
    y = mix(code0, y, u_mix);
    if (u_frame_on == 1) y = frameMask(y, uv);
    if (u_dither == 1) {
        uvec2 q = uvec2(gl_FragCoord.xy);
        float n1 = rnd(uvec3(q, uint(u_frame) * 3u + 1u));
        float n2 = rnd(uvec3(q, uint(u_frame) * 3u + 2u));
        y += (n1 - n2) / 255.0;
    }
    f_out = vec4(clamp(y, 0.0, 1.0), 1.0);
}
"""

BAKE = COMMON + """
uniform sampler2D t_grid;
uniform int u_input;
uniform int u_input_cv;
uniform int u_legal;
uniform mat3 u_gamut;
uniform vec3 u_gain;
void main() {
    vec3 code = texelFetch(t_grid, ivec2(gl_FragCoord.xy), 0).rgb;
    vec3 lin = max(u_gamut * toLinear(code, u_input, u_input_cv == 1 && u_legal == 1), vec3(0.0)) * exp2(u_gain);
    f_out = vec4(colorPipe(lin), 1.0);
}
"""

# ------------------------------------------------------------------ encaixe da exportação (fit.py)
# `Engine.render_fit`: o quadro com o look (`t_img`, já em valores de exibição de 8 ou 16 bits) vai para um
# quadro maior, sobre bordas pretas ou sobre o fundo desfocado (`t_bg`: a própria imagem desfocada, no espaço
# dela). A imagem é copiada pixel a pixel (`texelFetch`) e a saída é inteira, arredondada aqui: dentro da
# caixa o resultado é exatamente o quadro do look. Nada aleatório: o pontilhado do fundo usa o hash do pixel
# e o número do quadro, como o do passo final.
COPY = COMMON + """
uniform sampler2D t_src;
void main() {
    f_out = texelFetch(t_src, ivec2(gl_FragCoord.xy), 0);
}
"""

FIT = """
#version 330
in vec2 v_uv;
out uvec4 f_out;
uniform sampler2D t_img;
uniform sampler2D t_bg;
uniform ivec4 u_box;      // x, y, largura, altura da imagem no quadro (px, y para baixo)
uniform int u_bg_mode;    // 0 = preto, 1 = fundo desfocado
uniform vec4 u_cover;     // uv do fundo = (pixel - u_cover.xy) * u_cover.zw
uniform float u_dim;
uniform float u_max;      // 255 ou 65535
uniform int u_dither;
uniform int u_frame;

uint pcg(uint v) {
    uint state = v * 747796405u + 2891336453u;
    uint word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
    return (word >> 22u) ^ word;
}
float rnd(uvec3 p) { return float(pcg(p.x + pcg(p.y + pcg(p.z)))) * (1.0 / 4294967296.0); }

void main() {
    ivec2 p = ivec2(gl_FragCoord.xy);
    ivec2 q = p - u_box.xy;
    vec3 c = vec3(0.0);
    if (q.x >= 0 && q.y >= 0 && q.x < u_box.z && q.y < u_box.w) {
        c = texelFetch(t_img, q, 0).rgb;
    } else if (u_bg_mode == 1) {
        vec2 uv = (gl_FragCoord.xy - u_cover.xy) * u_cover.zw;
        c = texture(t_bg, uv).rgb * u_dim;
        if (u_dither == 1) {
            uvec2 s = uvec2(p);
            c += (rnd(uvec3(s, uint(u_frame) * 3u + 7u)) - rnd(uvec3(s, uint(u_frame) * 3u + 8u))) / u_max;
        }
    }
    f_out = uvec4(uvec3(floor(clamp(c, 0.0, 1.0) * u_max + 0.5)), uint(u_max));
}
"""
