"""1.9, atmosfera do clipe (#68, módulo Beta "atmosfera"; ARQUITETURA §52): partículas e névoa. Sem Qt nem GPU.

Dois efeitos da pilha de `vfx.py` (o passo GLSL roda no espaço da textura do clipe, entre a leitura e o `CLIP`):

- **Névoa** (`nevoa_*`, ordem 600): a luz do clipe vai para a cor da névoa (`lin·(1 − f) + névoa·f`, na luz da curva do
  look, `fxDec`), com `f` = densidade × degradê (`masks.gradMask`, o mesmo do "Degradê" da cor simples: linha pelo
  centro deslocada pela altura, lado marcado pela direção) × nuvens. As nuvens são um ruído de valor periódico em
  px@1080 que anda na horizontal (`nevoa_movimento` px/s): o deslocamento sai do tempo do clipe em float64, reduzido ao
  período do ruído (`NOISE_PERIOD` células), então um clipe longo não perde precisão. A cor é dada como num vídeo comum
  (Rec.709: `stopsToLin(dispToStops(cor))`), qualquer que seja a curva do clipe.
- **Partículas** (`part_*`, ordem 700): chuva, neve, poeira no ar ou brasas, desenhadas por célula num quadriculado
  alinhado à direção do movimento, em três camadas de profundidade (paralaxe: as do fundo menores, mais lentas, mais
  apagadas e mais macias). Cada célula tem até `CANDIDATES` partículas; presença, posição, tamanho, brilho e fase saem
  de um hash de inteiros (célula reduzida ao período, camada, candidata, `part_semente`). O mundo de cada camada anda
  `velocidade × tempo do clipe` ao longo da direção (float64 aqui, reduzido ao período do quadriculado): o quadro N é
  sempre o mesmo, e dividir o clipe no meio não muda nada (o tempo do clipe das chaves não muda ao cortar). O rastro de
  movimento é o caminho percorrido durante a exposição (`part_desfoque` = fração do quadro, 50% = 180°). Chuva e neve
  cobrem (mistura "por cima" na luz); poeira e brasas somam luz; as brasas cintilam (ruído no tempo, ~6 Hz).

Os dois só mexem no que mudam: a saída é `c + fxEnc(luz nova) − fxEnc(luz)`, então um pixel sem névoa nem partícula sai
bit a bit como entrou. Valem numa camada de ajuste (sobre tudo o que está embaixo). Tudo em px@1080 do clipe
(`u_fx_scale`), y para baixo.
"""

from __future__ import annotations

import math

from . import masks, vfx

MODULE = "atmosfera"
NOISE_PERIOD = 64          # células do ruído da névoa até ele se repetir (o deslocamento é reduzido a este período)
GRID_PERIOD = 1024         # células do quadriculado das partículas até ele se repetir
CANDIDATES = 4             # partículas possíveis por célula (o GLSL usa o mesmo número)
LAYERS = 3                 # camadas de profundidade
DEPTH_SCALE = 0.65         # com profundidade 100%, a camada do fundo tem 35% do tamanho e da velocidade
DEPTH_FADE = 0.45          # … e 55% da opacidade
DEPTH_SOFT = 0.8           # … e fica mais macia (fora de foco)
CELL_MARGIN = 8.0          # folga da célula (px@1080) para a borda suavizada de um texel numa prévia pequena

# Cada tipo de partícula: id no GLSL, velocidade natural (px@1080/s), direção (y para baixo), quanto o vento inclina,
# luz (linear; × a cor do ajuste), se soma luz, célula (px@1080) e partículas por célula com 100%, fração do
# "Tamanho" que vira diâmetro, maciez da borda (fração do raio) e balanço (amplitude px@1080, rad/s).
TYPES = {
    "chuva": dict(id=1, speed=1600.0, dir=(0.0, 1.0), wind=0.6, light=(0.55, 0.6, 0.7), add=False, cell=55.0,
                  count=1.6, size=0.35, soft=0.25, sway=0.0, sway_w=0.0),
    "neve": dict(id=2, speed=90.0, dir=(0.0, 1.0), wind=1.5, light=(0.85, 0.87, 0.9), add=False, cell=70.0,
                 count=1.2, size=1.0, soft=0.7, sway=18.0, sway_w=1.3),
    "poeira": dict(id=3, speed=10.0, dir=(0.0, 1.0), wind=4.0, light=(0.3, 0.27, 0.22), add=True, cell=60.0,
                   count=1.0, size=0.5, soft=1.0, sway=25.0, sway_w=0.5),
    "brasas": dict(id=4, speed=140.0, dir=(0.0, -1.0), wind=1.2, light=(2.6, 0.95, 0.25), add=True, cell=90.0,
                   count=0.7, size=0.6, soft=0.5, sway=30.0, sway_w=0.9),
}

PARTICLE_KEYS = ("part_tipo", "part_quantidade", "part_tamanho", "part_velocidade", "part_vento", "part_profundidade",
                 "part_opacidade", "part_cor", "part_desfoque", "part_semente")
FOG_KEYS = ("nevoa_densidade", "nevoa_cor", "nevoa_forma", "nevoa_angulo", "nevoa_posicao", "nevoa_suavidade",
            "nevoa_textura", "nevoa_escala", "nevoa_movimento", "nevoa_semente")

# ------------------------------------------------------------------ GLSL
PARTICLES = """
uniform int u_kind;          // atmosfera.TYPES[...]["id"]
uniform int u_add;           // 1 = soma luz (poeira, brasas); 0 = cobre (chuva, neve)
uniform int u_seed;
uniform vec2 u_dir;          // direção do movimento na tela (unitária, y para baixo)
uniform vec3 u_off;          // quanto o mundo de cada camada andou ao longo da direção (px@1080, já no período)
uniform vec3 u_ca;           // célula de cada camada: largura (de lado) …
uniform vec3 u_cb;           // … e comprimento (ao longo da direção), px@1080
uniform vec3 u_prob;         // chance de cada candidata existir, por camada
uniform vec3 u_rad;          // raio de cada camada (px@1080)
uniform vec3 u_len;          // rastro de cada camada (px@1080)
uniform vec3 u_alpha;        // opacidade de cada camada (com o rastro)
uniform vec3 u_soft;         // maciez da borda (fração do raio) de cada camada
uniform vec3 u_lscale;       // escala de cada camada (1 = a da frente)
uniform vec2 u_sway;         // balanço: amplitude (px@1080 na frente), rad/s
uniform vec3 u_light;        // luz das partículas (linear)

const float PERIOD = %(period).1f;
const int CANDS = %(cands)d;

uint cellHash(vec2 cell, int layer, int k) {
    uvec2 c = uvec2(mod(cell, PERIOD));
    return pcg(c.x + pcg(c.y + pcg(uint(u_seed) * 64u + uint(layer) * 8u + uint(k))));
}
float next01(inout uint h) {
    h = pcg(h);
    return float(h) * (1.0 / 4294967296.0);
}
// Cintilação das brasas: ruído de valor no tempo (~6 Hz), de 0,35 a 1.
float flicker(uint h, float t) {
    float i = floor(t);
    float f = fract(t);
    float a = float(pcg(h + uint(i))) * (1.0 / 4294967296.0);
    float b = float(pcg(h + uint(i) + 1u)) * (1.0 / 4294967296.0);
    return mix(0.35, 1.0, mix(a, b, f * f * (3.0 - 2.0 * f)));
}

void main() {
    vec4 c = texture(t_prev, v_uv);
    vec2 P = framePoint(v_uv, u_fx_clip_px.x / u_fx_clip_px.y);
    vec2 side = vec2(-u_dir.y, u_dir.x);
    float aa = 0.75 / u_fx_scale;  // ~ três quartos de texel, em px@1080
    float cover = 0.0;
    vec3 light = vec3(0.0);
    for (int l = 0; l < 3; l++) {
        vec2 cell = vec2(u_ca[l], u_cb[l]);
        vec2 q = vec2(dot(P, side), dot(P, u_dir) - u_off[l]);
        vec2 base = floor(q / cell);
        float half_len = 0.5 * u_len[l];
        for (int dy = -1; dy <= 1; dy++) {
            for (int dx = -1; dx <= 1; dx++) {
                vec2 id = base + vec2(float(dx), float(dy));
                for (int k = 0; k < CANDS; k++) {
                    uint h = cellHash(id, l, k);
                    if (float(h) * (1.0 / 4294967296.0) >= u_prob[l]) continue;
                    vec2 j = vec2(next01(h), next01(h));
                    float r = u_rad[l] * mix(0.6, 1.4, next01(h));
                    float bright = mix(0.55, 1.0, next01(h));
                    float ph = 6.2831853 * next01(h);
                    float w = u_sway.y * mix(0.6, 1.4, next01(h));
                    vec2 ctr = (id + j) * cell;
                    ctr.x += u_sway.x * u_lscale[l] * sin(u_fx_time * w + ph);
                    ctr.y += 0.6 * u_sway.x * u_lscale[l] * cos(u_fx_time * w * 0.7 + 2.0 * ph);
                    vec2 rel = q - ctr;
                    float re = max(r, aa);
                    float d = length(vec2(rel.x, rel.y - clamp(rel.y, -half_len, half_len)));
                    // Borda em px@1080 (a mesma em qualquer resolução); só fica mais larga que um texel quando ele
                    // é maior que ela.
                    float mid = re * (1.0 - 0.5 * u_soft[l]);
                    float hw = max(0.5 * re * u_soft[l], 0.5 * aa);
                    float a = 1.0 - smoothstep(mid - hw, mid + hw, d);
                    if (a <= 0.0) continue;
                    a *= u_len[l] > re ? r / re : (r / re) * (r / re);  // menor que um texel: a mesma luz, espalhada
                    a = clamp(a * u_alpha[l] * bright, 0.0, 1.0);
                    vec3 col = u_light;
                    if (u_kind == 4) col *= flicker(h, u_fx_time * 6.0 + ph);
                    if (u_add == 1) {
                        light += a * col;
                    } else {
                        light += a * (1.0 - cover) * col;
                        cover += a * (1.0 - cover);
                    }
                }
            }
        }
    }
    if (cover <= 0.0 && dot(light, light) <= 0.0) {
        f_out = c;
        return;
    }
    vec3 lin = fxDec(c.rgb);
    vec3 lin2 = lin * (1.0 - cover) + light;
    f_out = vec4(c.rgb + fxEnc(lin2) - fxEnc(lin), c.a);
}
""" % {"period": GRID_PERIOD, "cands": CANDIDATES}

FOG = """
uniform float u_density;
uniform vec3 u_fog;          // cor da névoa como num vídeo Rec.709 (0 a 1)
uniform int u_uniform;       // 1 = o quadro todo; 0 = degradê
uniform vec4 u_g;            // degradê (masks.gradient_uniform)
uniform vec4 u_k;
uniform float u_texture;     // 0 = lisa; 1 = nuvens marcadas
uniform float u_scale;       // tamanho das nuvens (px@1080)
uniform vec2 u_off1;         // deslocamento das nuvens (células, já no período)
uniform vec2 u_off2;
uniform int u_seed;

const float NP = %(period).1f;

float cellRnd(vec2 i, uint salt) {
    uvec2 c = uvec2(i);
    return float(pcg(c.x + pcg(c.y + pcg(uint(u_seed) * 16u + salt)))) * (1.0 / 4294967296.0);
}
// Ruído de valor que se repete a cada `per` células (a rede de inteiros é reduzida ao período).
float pnoise(vec2 x, float per, uint salt) {
    vec2 i = floor(x);
    vec2 f = fract(x);
    vec2 u = f * f * (3.0 - 2.0 * f);
    vec2 i0 = mod(i, per);
    vec2 i1 = mod(i + 1.0, per);
    float a = cellRnd(i0, salt);
    float b = cellRnd(vec2(i1.x, i0.y), salt);
    float c = cellRnd(vec2(i0.x, i1.y), salt);
    float d = cellRnd(i1, salt);
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
// Quatro oitavas; cada uma dobra a escala e o período, então a soma se repete a cada NP células.
float pfbm(vec2 x, uint salt) {
    float v = 0.0;
    float a = 0.5;
    float per = NP;
    for (int o = 0; o < 4; o++) {
        v += a * pnoise(x, per, salt + uint(o));
        x = x * 2.0 + 17.0;
        per *= 2.0;
        a *= 0.5;
    }
    return v / 0.9375;
}

void main() {
    vec4 c = texture(t_prev, v_uv);
    vec2 P = framePoint(v_uv, u_fx_clip_px.x / u_fx_clip_px.y);
    float m = u_uniform == 1 ? 1.0 : gradMask(P, u_g, u_k);
    float f = u_density * m;
    if (u_texture > 0.0 && f > 0.0) {
        vec2 x = P / u_scale;
        float n = 0.5 * (pfbm(x + u_off1, 1u) + pfbm(x + u_off2 + 31.0, 9u));
        n = clamp((n - 0.5) * 1.8, -0.5, 0.5) * 2.0;  // −1 … 1
        f *= 1.0 + u_texture * n;
    }
    f = clamp(f, 0.0, 1.0);
    if (f <= 0.0) {
        f_out = c;
        return;
    }
    vec3 lin = fxDec(c.rgb);
    vec3 fog = stopsToLin(dispToStops(u_fog));
    f_out = vec4(c.rgb + fxEnc(mix(lin, fog, f)) - fxEnc(lin), c.a);
}
""" % {"period": NOISE_PERIOD}

PARTICLES_GLSL = masks.GLSL + PARTICLES
FOG_GLSL = masks.GLSL + FOG


# ------------------------------------------------------------------ partículas
def particles_active(v: dict) -> bool:
    return (str(v.get("part_tipo", "nenhuma")) in TYPES and float(v.get("part_quantidade", 0.0)) > 0.0
            and float(v.get("part_opacidade", 0.0)) > 0.0)


def particle_layers(v: dict, seconds: float, fps: float) -> dict:
    """As grandezas das três camadas (sem GPU; os testes e a GPU leem daqui): direção, velocidade, células, chance de
    cada candidata, raio, rastro, opacidade, maciez e o deslocamento no tempo `seconds` (float64, já reduzido ao período
    do quadriculado). Nada depende da resolução: a prévia reduzida e a exportação têm as mesmas partículas."""
    t = TYPES[str(v["part_tipo"])]
    vx = t["dir"][0] + float(v.get("part_vento", 0.0)) * t["wind"]
    vy = t["dir"][1]
    norm = math.hypot(vx, vy)
    speed = t["speed"] * float(v.get("part_velocidade", 1.0)) * norm
    direction = (vx / norm, vy / norm) if norm > 1e-9 else tuple(t["dir"])
    depth = float(v.get("part_profundidade", 0.0))
    size = max(0.1, float(v.get("part_tamanho", 6.0))) * t["size"]
    blur = max(0.0, float(v.get("part_desfoque", 0.0)))
    amount = max(0.0, min(1.0, float(v.get("part_quantidade", 0.0))))
    out = {"dir": direction, "speed": speed, "scale": [], "ca": [], "cb": [], "prob": [], "rad": [], "len": [],
           "alpha": [], "soft": [], "off": []}
    for i in range(LAYERS):
        z = i / (LAYERS - 1)
        s = 1.0 - DEPTH_SCALE * depth * z
        r = 0.5 * size * s
        length = blur * speed * s / max(fps, 1e-6)
        sway = t["sway"] * s
        margin = CELL_MARGIN
        ca = max(t["cell"] * s, 2.2 * (1.4 * r + sway) + margin)
        cb = max(t["cell"] * s, 2.2 * (0.5 * length + 1.4 * r + 0.6 * sway) + margin)
        count = amount * t["count"] * ca * cb / (t["cell"] * s) ** 2
        # O rastro espalha a luz da partícula: menos opaca, mas visível (meio caminho entre cobrir e conservar a luz).
        motion = 1.0 / math.sqrt(1.0 + length / max(2.0 * r, 1e-6))
        out["scale"].append(s)
        out["ca"].append(ca)
        out["cb"].append(cb)
        out["prob"].append(min(1.0, count / CANDIDATES))
        out["rad"].append(r)
        out["len"].append(length)
        out["alpha"].append(float(v.get("part_opacidade", 0.0)) * (1.0 - DEPTH_FADE * depth * z) * motion)
        out["soft"].append(min(0.95, t["soft"] + DEPTH_SOFT * depth * z))
        out["off"].append(math.fmod(speed * s * float(seconds), GRID_PERIOD * cb))
    return out


def particle_passes(ctx: vfx.Ctx) -> list[vfx.Pass]:
    v = ctx.values
    t = TYPES[str(v["part_tipo"])]
    L = particle_layers(v, ctx.seconds, float(ctx.seq.fps))
    tint = [float(x) for x in (v.get("part_cor") or (1.0, 1.0, 1.0))]
    U = {"u_kind": int(t["id"]), "u_add": int(bool(t["add"])), "u_seed": int(v.get("part_semente", 1)),
         "u_dir": tuple(float(x) for x in L["dir"]), "u_sway": (float(t["sway"]), float(t["sway_w"])),
         "u_light": tuple(float(a) * float(b) for a, b in zip(t["light"], tint))}
    for name, key in (("u_off", "off"), ("u_ca", "ca"), ("u_cb", "cb"), ("u_prob", "prob"), ("u_rad", "rad"),
                      ("u_len", "len"), ("u_alpha", "alpha"), ("u_soft", "soft"), ("u_lscale", "scale")):
        U[name] = tuple(float(x) for x in L[key])
    return [vfx.Pass("particulas", PARTICLES_GLSL, uniforms=U)]


# ------------------------------------------------------------------ névoa
def fog_active(v: dict) -> bool:
    return float(v.get("nevoa_densidade", 0.0)) > 0.0


def fog_offsets(v: dict, seconds: float) -> tuple[tuple[float, float], tuple[float, float]]:
    """Deslocamento das duas camadas de nuvens (em células do ruído, float64 reduzido ao período): a segunda anda a
    55% e sobe devagar, para as nuvens mudarem de forma enquanto andam."""
    scale = max(1.0, float(v.get("nevoa_escala", 300.0)))
    move = float(v.get("nevoa_movimento", 0.0)) * float(seconds) / scale
    return ((math.fmod(move, NOISE_PERIOD), 0.0),
            (math.fmod(0.55 * move, NOISE_PERIOD), math.fmod(-0.15 * abs(move), NOISE_PERIOD)))


def fog_passes(ctx: vfx.Ctx) -> list[vfx.Pass]:
    v = ctx.values
    g, k = masks.gradient_uniform("linear", 0.0, float(v.get("nevoa_posicao", 0.0)), float(v.get("nevoa_angulo", 180.0)),
                                  0.0, float(v.get("nevoa_suavidade", 600.0)), False)
    off1, off2 = fog_offsets(v, ctx.seconds)
    U = {"u_density": float(v["nevoa_densidade"]), "u_fog": tuple(float(x) for x in v.get("nevoa_cor") or (1, 1, 1)),
         "u_uniform": int(str(v.get("nevoa_forma", "degrade")) == "uniforme"), "u_g": g, "u_k": k,
         "u_texture": float(v.get("nevoa_textura", 0.0)), "u_scale": max(1.0, float(v.get("nevoa_escala", 300.0))),
         "u_off1": off1, "u_off2": off2, "u_seed": int(v.get("nevoa_semente", 1))}
    return [vfx.Pass("nevoa", FOG_GLSL, uniforms=U)]


FOG_EFFECT = vfx.register(vfx.Effect("nevoa", MODULE, vfx.ORDER["nevoa"], active=fog_active, passes=fog_passes,
                                     keys=FOG_KEYS))
PARTICLES_EFFECT = vfx.register(vfx.Effect("particulas", MODULE, vfx.ORDER["particulas"], active=particles_active,
                                           passes=particle_passes, keys=PARTICLE_KEYS))
