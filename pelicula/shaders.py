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

// ---------------------------------------------------------------- perfis de câmera da 1.6 (look.INPUT_IDS 14+)
// Fórmulas publicadas pelos fabricantes (a biblioteca colour-science, BSD-3, serviu só de conferência).
// Canon Log 2 e Canon Log 3: Canon, "Canon Log Gamma Curves – Input Transform Version 201612" (v1). A
// fórmula usa a reflexão sobre o branco 90% (luz/0,9) e é espelhada abaixo de 0, como a da Canon.
float clog2Dec(float y) {
    float r = (y < 0.035388128) ? -(pow(10.0, (0.035388128 - y) / 0.281863093) - 1.0) / 87.09937546
                                : (pow(10.0, (y - 0.035388128) / 0.281863093) - 1.0) / 87.09937546;
    return r * 0.9;
}
float clog2Enc(float x) {
    float r = x / 0.9;
    return (r < 0.0) ? -(0.281863093 * log10f(-r * 87.09937546 + 1.0) - 0.035388128)
                     : 0.281863093 * log10f(r * 87.09937546 + 1.0) + 0.035388128;
}
float clog3Dec(float y) {
    float r;
    if (y < 0.04076162) r = -(pow(10.0, (0.07623209 - y) / 0.42889912) - 1.0) / 14.98325;
    else if (y <= 0.105357102) r = (y - 0.073059361) / 2.3069815;
    else r = (pow(10.0, (y - 0.069886632) / 0.42889912) - 1.0) / 14.98325;
    return r * 0.9;
}
float clog3Enc(float x) {
    float r = x / 0.9;
    if (r < -0.014) return -0.42889912 * log10f(-r * 14.98325 + 1.0) + 0.07623209;
    if (r <= 0.014) return 2.3069815 * r + 0.073059361;
    return 0.42889912 * log10f(r * 14.98325 + 1.0) + 0.069886632;
}
// Fujifilm F-Log ("F-Log Data Sheet" Ver.1.1) e F-Log2 ("F-Log2 Data Sheet"; o F-Log2 C, id 18, usa a mesma curva):
// código de 10 bits / 1023; c·log10(a·x + b) + d acima de cut1, e·x + f abaixo.
float flogDec(float y) {
    return (y < 0.100537775223865) ? (y - 0.092864) / 8.735631
                                   : pow(10.0, (y - 0.790453) / 0.344676) / 0.555556 - 0.009468 / 0.555556;
}
float flogEnc(float x) { return (x < 0.00089) ? 8.735631 * x + 0.092864 : 0.344676 * log10f(0.555556 * x + 0.009468) + 0.790453; }
float flog2Dec(float y) {
    return (y < 0.100686685370811) ? (y - 0.092864) / 8.799461
                                   : pow(10.0, (y - 0.384316) / 0.245281) / 5.555556 - 0.064829 / 5.555556;
}
float flog2Enc(float x) { return (x < 0.000889) ? 8.799461 * x + 0.092864 : 0.245281 * log10f(5.555556 * x + 0.064829) + 0.384316; }
// DJI D-Log: "White Paper on D-Log and D-Gamut of DJI Cinema Color System" (2017), código de 10 bits / 1023.
float dlogDec(float y) { return (y <= 0.14) ? (y - 0.0929) / 6.025 : (pow(10.0, 3.89616 * y - 2.27752) - 0.0108) / 0.9892; }
float dlogEnc(float x) { return (x <= 0.0078) ? 6.025 * x + 0.0929 : log10f(x * 0.9892 + 0.0108) * 0.256663 + 0.584555; }
// Sony S-Log2: "S-Log2 Technical Paper" (2012). Sinal (antes da faixa legal) do S-Log com x·155/219 e a
// reflexão sobre o branco 90%.
float slog2Dec(float y) {
    float r = (y >= 0.030001222851889303) ? pow(10.0, (y - 0.646596) / 0.432699) - 0.037584
                                          : (y - 0.030001222851889303) / 5.0;
    return r * 0.9 * 219.0 / 155.0;
}
float slog2Enc(float x) {
    float r = x * 155.0 / 219.0 / 0.9;
    return (r >= 0.0) ? 0.432699 * log10f(r + 0.037584) + 0.646596 : r * 5.0 + 0.030001222851889303;
}
// Leica L-Log: "L-Log Reference Manual" V1.9 (2026), seção 4. O manual tem um degrau de 0,0009 em 0,006 entre
// a reta e o log; fica como está.
float llogDec(float y) { return (y <= 0.138) ? (y - 0.09) / 8.0 : (pow(10.0, (y - 0.6) / 0.27) - 0.0115) / 1.3; }
float llogEnc(float x) { return (x <= 0.006) ? 8.0 * x + 0.09 : 0.27 * log10f(1.3 * x + 0.0115) + 0.6; }
// ARRI LogC3 com outro EI (`logc3_ei` ≠ 800): id 22 + k, k = posição do EI em look.LOGC3_EI (160, 200, 250,
// 320, 400, 500, 640, 800, 1000, 1280, 1600). Corte, b, c, d, e, f de cada EI (a = 5,555556 em todos).
const float LC3[66] = float[66](
    0.005561, 0.080216, 0.269036, 0.381991, 5.842037, 0.092778,
    0.006208, 0.076621, 0.266007, 0.382478, 5.776265, 0.092782,
    0.006871, 0.072941, 0.262978, 0.382966, 5.710494, 0.092786,
    0.007622, 0.068768, 0.259627, 0.383508, 5.637732, 0.092791,
    0.008318, 0.064901, 0.256598, 0.383999, 5.571960, 0.092795,
    0.009031, 0.060939, 0.253569, 0.384493, 5.506188, 0.092800,
    0.009840, 0.056443, 0.250219, 0.385040, 5.433426, 0.092805,
    0.010591, 0.052272, 0.247190, 0.385537, 5.367655, 0.092809,
    0.011361, 0.047996, 0.244161, 0.386036, 5.301883, 0.092814,
    0.012235, 0.043137, 0.240810, 0.386590, 5.229121, 0.092819,
    0.013047, 0.038625, 0.237781, 0.387093, 5.163350, 0.092824
);
float logc3eDec(float t, int k) {
    float cut = LC3[k * 6], b = LC3[k * 6 + 1], c = LC3[k * 6 + 2], d = LC3[k * 6 + 3];
    float e = LC3[k * 6 + 4], f = LC3[k * 6 + 5];
    return (t > e * cut + f) ? (pow(10.0, (t - d) / c) - b) / 5.555556 : (t - f) / e;
}
float logc3eEnc(float x, int k) {
    float cut = LC3[k * 6], b = LC3[k * 6 + 1], c = LC3[k * 6 + 2], d = LC3[k * 6 + 3];
    float e = LC3[k * 6 + 4], f = LC3[k * 6 + 5];
    return (x > cut) ? c * log10f(5.555556 * x + b) + d : e * x + f;
}
vec3 camDec(vec3 c, int id) {
    if (id == 14) return vec3(clog2Dec(c.r), clog2Dec(c.g), clog2Dec(c.b));
    if (id == 15) return vec3(clog3Dec(c.r), clog3Dec(c.g), clog3Dec(c.b));
    if (id == 16) return vec3(flogDec(c.r), flogDec(c.g), flogDec(c.b));
    if (id == 17 || id == 18) return vec3(flog2Dec(c.r), flog2Dec(c.g), flog2Dec(c.b));  // F-Log2 (C)
    if (id == 19) return vec3(dlogDec(c.r), dlogDec(c.g), dlogDec(c.b));
    if (id == 20) return vec3(slog2Dec(c.r), slog2Dec(c.g), slog2Dec(c.b));
    if (id == 21) return vec3(llogDec(c.r), llogDec(c.g), llogDec(c.b));
    int k = id - 22;
    return vec3(logc3eDec(c.r, k), logc3eDec(c.g, k), logc3eDec(c.b, k));
}
vec3 camEnc(vec3 n, int id) {
    if (id == 14) return vec3(clog2Enc(n.r), clog2Enc(n.g), clog2Enc(n.b));
    if (id == 15) return vec3(clog3Enc(n.r), clog3Enc(n.g), clog3Enc(n.b));
    if (id == 16) return vec3(flogEnc(n.r), flogEnc(n.g), flogEnc(n.b));
    if (id == 17 || id == 18) return vec3(flog2Enc(n.r), flog2Enc(n.g), flog2Enc(n.b));  // F-Log2 (C)
    if (id == 19) return vec3(dlogEnc(n.r), dlogEnc(n.g), dlogEnc(n.b));
    if (id == 20) return vec3(slog2Enc(n.r), slog2Enc(n.g), slog2Enc(n.b));
    if (id == 21) return vec3(llogEnc(n.r), llogEnc(n.g), llogEnc(n.b));
    int k = id - 22;
    return vec3(logc3eEnc(n.r, k), logc3eEnc(n.g, k), logc3eEnc(n.b, k));
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
    if (id >= 14) return camDec(c, id);
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
    if (id >= 14) return camEnc(n, id);
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

// 1.6: grão no negativo (grao.negative_grain): densidade somada a cada camada do negativo. Só o FINAL a preenche;
// no resto (BAKE, o LUT exportado) fica zero.
vec3 g_ng = vec3(0.0);

// Um caminho completo. lin: luz linear Rec.709 (0,18 = cinza médio). Devolve o valor de exibição.
vec3 labPath(vec3 lin, mat3 sens, vec3 ng, vec3 nt, vec3 ns, float nw, mat3 ii, vec3 pg, vec3 pt, vec3 ps,
             float pw, mat3 dye, vec3 off, vec3 key, vec3 nmid, int scan) {
    vec3 e = max(sens * lin, vec3(1e-7));
    vec3 le = vec3(log10f(e.r / 0.18), log10f(e.g / 0.18), log10f(e.b / 0.18));  // log10 relativo ao cinza
    vec3 dn = ii * labCurve(le, ng, nt, ns, nw);  // densidade do negativo (com o efeito entre camadas)
    dn += g_ng;
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

// ---------------------------------------------------------------- 1.6: proteger cores saturadas
// Compressão suave do gamut logo depois da matriz da câmera (u_gamut), antes do look e do negativo. Algoritmo da
// "ACES Reference Gamut Compression" (Academy Software Foundation / AMPAS, especificação em CC BY 4.0): a
// distância de cada canal ao acromático A = máx(r, g, b) é d = (A − c)/|A|; abaixo do limiar t nada muda, acima
// a distância é comprimida por d' = t + (d − t)/(1 + ((d − t)/s)^p)^(1/p), com s tal que o limite l vá para 1.
// Aqui o espaço é o Rec.709 linear do app e o limite (u_gc_lim, look.gamut_limits) cobre a fronteira inteira do
// gamut da câmera: a cor mais saturada que ela grava cai na borda do Rec.709, sem canal negativo.
uniform float u_gc_amt;  // 0..1 (proteger_cores); 0 = a cor de sempre, bit a bit (look.SPARSE_UNIFORMS)
uniform vec3 u_gc_lim;   // limite da distância por canal (ciano, magenta, amarelo)
const vec3 GC_THR = vec3(0.815, 0.803, 0.880);
const float GC_PWR = 1.2;

float gcCompress(float d, float lim, float thr) {
    if (d < thr) return d;
    float s = (lim - thr) / pow(pow((1.0 - thr) / (lim - thr), -GC_PWR) - 1.0, 1.0 / GC_PWR);
    float nd = (d - thr) / s;
    return thr + (d - thr) / pow(1.0 + pow(nd, GC_PWR), 1.0 / GC_PWR);
}

vec3 gamutCompress(vec3 c, vec3 lim) {
    float a = max(c.r, max(c.g, c.b));
    if (a == 0.0) return c;
    float aa = abs(a);
    vec3 d = (vec3(a) - c) / aa;
    vec3 cd = vec3(gcCompress(d.r, lim.r, GC_THR.r), gcCompress(d.g, lim.g, GC_THR.g),
                   gcCompress(d.b, lim.b, GC_THR.b));
    return vec3(a) - cd * aa;
}

vec3 protectGamut(vec3 c) {
    return u_gc_amt > 0.0 ? mix(c, gamutCompress(c, u_gc_lim), u_gc_amt) : c;
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
    return max(protectGamut(u_gamut * toLinear(code, u_input, u_input_cv == 1 && u_legal == 1)), vec3(0.0))
           * exp2(u_gain);
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

// 1.6: anamórfico (`anamorfico.py`) e data impressa (`data_impressa.py`), módulos Beta. Desligados
// (look.SPARSE_UNIFORMS: u_anam = (1, 0, 0, 0), u_date_on = 0), `filmLight` é a conta de sempre, bit a bit.
vec3 imageLin(vec2 uv);
uniform vec4 u_anam;       // compressão (1 = nenhuma), barril horizontal, maciez das bordas (px@1080), ligado
uniform int u_date_on;
uniform vec4 u_date_box;   // canto de cima à esquerda do texto e altura do dígito (px@1080 do quadro da câmera), glifos
uniform vec4 u_date_g0;    // segmentos de cada glifo (bits a=1 … g=64; 128 = apóstrofo; 0 = espaço)
uniform vec4 u_date_g1;
uniform vec4 u_date_g2;
uniform vec3 u_date_col;   // cor × intensidade, luz linear somada à cena (a câmera expõe o negativo)

float dateSeg(vec2 p, vec2 a, vec2 b) {
    vec2 pa = p - a;
    vec2 ba = b - a;
    return length(pa - ba * clamp(dot(pa, ba) / max(dot(ba, ba), 1e-6), 0.0, 1.0));
}
float dateGlyph(int i) { return i < 4 ? u_date_g0[i] : (i < 8 ? u_date_g1[i - 4] : u_date_g2[i - 8]); }
float dateAdvance(float g) { return g > 127.5 ? 0.32 : (g < 0.5 ? 0.5 : 0.78); }
float dateDigit(vec2 p, int b) {
    const float W = 0.56;
    float d = 1e3;
    if ((b & 1) != 0) d = min(d, dateSeg(p, vec2(0.07, 0.0), vec2(W - 0.07, 0.0)));
    if ((b & 2) != 0) d = min(d, dateSeg(p, vec2(W, 0.07), vec2(W, 0.43)));
    if ((b & 4) != 0) d = min(d, dateSeg(p, vec2(W, 0.57), vec2(W, 0.93)));
    if ((b & 8) != 0) d = min(d, dateSeg(p, vec2(0.07, 1.0), vec2(W - 0.07, 1.0)));
    if ((b & 16) != 0) d = min(d, dateSeg(p, vec2(0.0, 0.57), vec2(0.0, 0.93)));
    if ((b & 32) != 0) d = min(d, dateSeg(p, vec2(0.0, 0.07), vec2(0.0, 0.43)));
    if ((b & 64) != 0) d = min(d, dateSeg(p, vec2(0.07, 0.5), vec2(W - 0.07, 0.5)));
    return d;
}
float dateMask(vec2 px) {
    vec2 p = (px - u_date_box.xy) / u_date_box.z;
    if (p.y < -0.25 || p.y > 1.25 || p.x < -0.25) return 0.0;
    float aa = max(1080.0 / u_res.y / u_date_box.z, 0.035);
    p.x -= (1.0 - p.y) * 0.1;  // itálico, como os mostradores de sete segmentos das câmeras
    float x = 0.0;
    float m = 0.0;
    int n = int(u_date_box.w + 0.5);
    for (int i = 0; i < 12; i++) {
        if (i >= n) break;
        float g = dateGlyph(i);
        vec2 q = vec2(p.x - x, p.y);
        float d = 1e3;
        if (g > 127.5) d = dateSeg(q, vec2(0.12, 0.0), vec2(0.08, 0.2));
        else if (g > 0.5) d = dateDigit(q, int(g + 0.5));
        m = max(m, smoothstep(0.075 + aa, 0.075 - aa, d));
        x += dateAdvance(g);
    }
    return m;
}

// A luz da imagem no quadro da câmera: desespremer (caixa de letra), barril horizontal e bordas macias da lente
// anamórfica, vinheta e a data impressa pela câmera no negativo.
vec3 filmLight(vec2 uv, vec2 vuv) {
    if (u_anam.w == 0.0 && u_date_on == 0) return imageLin(uv) * vignette(vuv);
    float S = max(u_anam.x, 1.0);
    vec2 cam = vec2(uv.x, (uv.y - 0.5) * S + 0.5);
    vec2 vcam = vec2(vuv.x, (vuv.y - 0.5) * S + 0.5);
    float cov = 1.0;
    if (S > 1.0) cov = clamp((0.5 - abs(cam.y - 0.5)) * u_res.y / S + 0.5, 0.0, 1.0);
    vec2 s = clamp(cam, 0.0, 1.0);
    vec2 q = s * 2.0 - 1.0;
    if (u_anam.y != 0.0) s.x = 0.5 + 0.5 * q.x / (1.0 + u_anam.y * (1.0 - q.y * q.y));
    int taps = (u_anam.z > 0.0) ? 2 : 0;
    float r = u_anam.z * q.x * q.x * (u_res.y / 1080.0) / u_res.x;
    vec3 c = vec3(0.0);
    float wsum = 0.0;
    for (int i = -taps; i <= taps; i++) {
        float w = 3.0 - float(abs(i));
        c += w * imageLin(s + vec2(0.5 * r * float(i), 0.0));
        wsum += w;
    }
    c /= wsum;
    c *= vignette(clamp(vcam, 0.0, 1.0));
    if (u_date_on == 1) c += u_date_col * dateMask(s * vec2(S * u_res.x / u_res.y * 1080.0, 1080.0));
    return c * cov;
}

void main() {
    if (u_scan_on == 0) {
        f_out = vec4(filmLight(weave(v_uv), v_uv), 1.0);
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
    if (u_date_on == 1)  // 1.6: a data no quadro da câmera, dentro da janela da película
        lin += inImg * inContent * u_date_col * dateMask(clamp(cuv, 0.0, 1.0) * vec2(Av * 1080.0, 1080.0));
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

# 1.6: o mesmo desfoque da maciez com um sigma por canal ("Diferença de nitidez entre camadas", grao.py).
BLUR3 = COMMON + """
uniform sampler2D t_src;
uniform vec2 u_dir;
uniform vec3 u_sigma3;
void main() {
    float sm = max(u_sigma3.r, max(u_sigma3.g, u_sigma3.b));
    float r = min(ceil(sm * 3.0), 48.0);
    vec3 s = max(u_sigma3, vec3(1e-3));
    vec3 k = -0.5 / (s * s);
    vec3 acc = vec3(0.0);
    vec3 wsum = vec3(0.0);
    for (float i = -r; i <= r; i += 1.0) {
        vec3 w = exp(i * i * k);
        acc += texture(t_src, v_uv + u_dir * i).rgb * w;
        wsum += w;
    }
    f_out = vec4(acc / wsum, 1.0);
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
uniform sampler2D t_streak;  // 1.6: risco horizontal do anamórfico (Engine._streak)
uniform int u_streak_on;     // 0 fora do plano (Engine.FINAL_NEUTRAL)
uniform float u_streak_amt;
uniform vec3 u_streak_col;
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

// 1.6: o mesmo campo do grão, sem a resposta por tom, em sigma D por camada (grão no negativo)
uniform vec3 u_ngrain;  // só com u_grain_on = 2
uniform vec3 u_breath;  // 1.6: exposição de cada camada neste quadro (Engine.FINAL_NEUTRAL sem a respiração)
vec3 negGrain(vec2 uv) {
    vec4 nf = texBicubic(t_noise, uv) * 2.08;
    vec4 nc = texBicubic(t_noise, uv * 0.4347 + vec2(0.311, 0.173)) * 2.08;
    float r = u_grain_rough;
    vec4 n = (nf * (1.0 - r) + nc * r) / sqrt((1.0 - r) * (1.0 - r) + r * r);
    float c = u_grain_chroma;
    vec3 g = (vec3(n.a) * (1.0 - c) + n.rgb * c) / sqrt((1.0 - c) * (1.0 - c) + c * c);
    return g * u_ngrain;
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

// 1.6: a fonte da halação física no ponto, igual à do EXTRACT da cadeia (limiar 0; o alfa é a máscara do scan, 1
// sem ele): e = E / (1 + E / limite), com o limite de grao.HAL_PHYS_LIMIT
const float HAL_PHYS_LIMIT = 16.0;
float halSource(vec4 s) {
    float e = s.r * s.a;
    return e / (1.0 + e / HAL_PHYS_LIMIT);
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
    if (u_streak_on == 1) lin += texture(t_streak, uv).r * u_streak_col * u_streak_amt;
    if (u_hal_on == 1) lin += texture(t_hal, uv).r * u_hal_color * u_hal_amt;
    if (u_hal_on == 2) {  // 1.6: halação física (grao.physical_halation): só o desvio local do reflexo na base
        vec3 a = u_hal_color * u_hal_amt;
        lin += a / (1.0 + a) * (texture(t_hal, uv).r - halSource(texture(t_lin, uv)));
    }
    if (u_leak_on == 1) lin += leak(uv);
    lin *= u_breath;  // 1.6: respiração por camada (grao.breathing); (1, 1, 1) sem ela
    if (u_grain_on == 2) g_ng = negGrain(uv);
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
    vec3 lin = max(protectGamut(u_gamut * toLinear(code, u_input, u_input_cv == 1 && u_legal == 1)), vec3(0.0))
               * exp2(u_gain);
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
