// Núcleo do plugin OpenFX: segue Engine.render() (pelicula/engine.py) e os shaders BASE/BLUR/EXTRACT/
// NOISE/FINAL (pelicula/shaders.py) passo a passo. Toda a matemática por pixel vem dos kernels gerados
// (pc_kernels.h, os mesmos dos DCTLs); aqui ficam só as passadas e as amostragens.
//
// Diferenças conhecidas em relação ao app (documentadas em docs/DAVINCI.md):
//  - os alvos intermediários são float32 (no app, half float) — o resultado fica um pouco mais limpo;
//  - os mipmaps das cadeias de brilho são médias 2x2 (o driver do OpenGL pode filtrar diferente);
//  - sem scan da película (furos e texto da borda) e sem LUT externo; sem pontilhado (a saída é float).
#include "pc_core.h"

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <locale>
#include <sstream>
#include <thread>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#endif

#include "../generated/pc_kernels.h"
#include "../generated/pc_params.h"
#include "pc_json.h"

#ifdef PC_PROFILE
#include <chrono>
#endif

namespace pc {

namespace {

#ifdef PC_PROFILE  // compile com /DPC_PROFILE para ver o tempo de cada passada
struct ProfileMark {
    std::chrono::steady_clock::time_point t = std::chrono::steady_clock::now();
    void mark(const char* name) {
        auto n = std::chrono::steady_clock::now();
        std::fprintf(stderr, "[pc] %-6s %8.2f ms\n", name, std::chrono::duration<double, std::milli>(n - t).count());
        t = n;
    }
};
#define PC_MARK(name) prof.mark(name)
#define PC_PROFILE_START ProfileMark prof
#else
#define PC_MARK(name) ((void)0)
#define PC_PROFILE_START ((void)0)
#endif

const int LUT_N = 65;

#ifdef _WIN32
// As threads do plugin pedem desempenho: sem isso o Windows 11 pode marcá-las como de eficiência
// (EcoQoS, núcleos E em clock baixo) quando o processo fica em segundo plano, e o quadro demora 4x mais.
// Só mexe nas threads criadas aqui, nunca nas do host.
void worker_qos() {
    typedef BOOL(WINAPI * SetInfo)(HANDLE, int, LPVOID, DWORD);
    static const SetInfo fn =
        (SetInfo)(void*)GetProcAddress(GetModuleHandleW(L"kernel32.dll"), "SetThreadInformation");
    if (!fn) return;
    struct { ULONG version, control, state; } st = {1, 0x1, 0};  // THREAD_POWER_THROTTLING_EXECUTION_SPEED: não
    fn(GetCurrentThread(), 3 /* ThreadPowerThrottling */, &st, (DWORD)sizeof(st));
}
#else
void worker_qos() {}
#endif

// Divide as linhas entre os núcleos em blocos pequenos tirados de um contador: núcleos rápidos (P) pegam
// mais blocos que os lentos (E), e ninguém fica esperando o mais lento.
template <class F>
void parallel_rows(int rows, F fn) {
    unsigned hc = std::thread::hardware_concurrency();
    int nt = (int)std::max(1u, std::min(hc ? hc : 4u, 64u));
    if (rows < 64 || nt == 1) {
        fn(0, rows);
        return;
    }
    const int chunk = std::max(1, std::min(16, rows / (nt * 4)));
    nt = std::min(nt, (rows + chunk - 1) / chunk);
    std::atomic<int> next(0);
    auto work = [&]() {
        for (;;) {
            int a = next.fetch_add(chunk);
            if (a >= rows) break;
            fn(a, std::min(rows, a + chunk));
        }
    };
    std::vector<std::thread> th;
    th.reserve(nt - 1);
    for (int t = 1; t < nt; ++t)
        th.emplace_back([&work]() {
            worker_qos();
            work();
        });
    work();
    for (auto& x : th) x.join();
}

struct Img {
    int w = 0, h = 0;
    std::vector<float3> px;
    void resize(int w_, int h_) {
        w = w_;
        h = h_;
        px.assign((size_t)w * h, make_float3(0.0f, 0.0f, 0.0f));
    }
    float3& at(int x, int y) { return px[(size_t)y * w + x]; }
    const float3& at(int x, int y) const { return px[(size_t)y * w + x]; }
};

inline int clampi(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }

// texture() com filtro LINEAR e CLAMP_TO_EDGE (como os alvos do app), em coordenadas uv 0..1.
inline float3 sample(const Img& im, float u, float v) {
    float gx = u * im.w - 0.5f;
    float gy = v * im.h - 0.5f;
    float fx0 = std::floor(gx);
    float fy0 = std::floor(gy);
    float ax = gx - fx0;
    float ay = gy - fy0;
    int x0 = clampi((int)fx0, 0, im.w - 1), x1 = clampi((int)fx0 + 1, 0, im.w - 1);
    int y0 = clampi((int)fy0, 0, im.h - 1), y1 = clampi((int)fy0 + 1, 0, im.h - 1);
    float3 a = im.at(x0, y0) + (im.at(x1, y0) - im.at(x0, y0)) * ax;
    float3 b = im.at(x0, y1) + (im.at(x1, y1) - im.at(x0, y1)) * ax;
    return a + (b - a) * ay;
}

inline float3 sample_rgb(const float* in, int w, int h, float u, float v) {
    float gx = u * w - 0.5f;
    float gy = v * h - 0.5f;
    float fx0 = std::floor(gx);
    float fy0 = std::floor(gy);
    float ax = gx - fx0;
    float ay = gy - fy0;
    int x0 = clampi((int)fx0, 0, w - 1), x1 = clampi((int)fx0 + 1, 0, w - 1);
    int y0 = clampi((int)fy0, 0, h - 1), y1 = clampi((int)fy0 + 1, 0, h - 1);
    auto P = [&](int x, int y) {
        const float* p = in + ((size_t)y * w + x) * 3;
        return make_float3(p[0], p[1], p[2]);
    };
    float3 a = P(x0, y0) + (P(x1, y0) - P(x0, y0)) * ax;
    float3 b = P(x0, y1) + (P(x1, y1) - P(x0, y1)) * ax;
    return a + (b - a) * ay;
}

// BLUR do app: gaussiana separável, raio min(ceil(3 sigma), 48), deslocamentos em texels inteiros.
void blur_pass(const Img& src, Img& dst, int dx, int dy, float sigma) {
    dst.resize(src.w, src.h);
    int r = (int)std::min(std::ceil(sigma * 3.0f), 48.0f);
    std::vector<float> wts(2 * r + 1);
    float k = -0.5f / (sigma * sigma);
    float wsum = 0.0f;
    for (int i = -r; i <= r; ++i) {
        wts[i + r] = std::exp((float)(i * i) * k);
        wsum += wts[i + r];
    }
    for (auto& w : wts) w /= wsum;
    parallel_rows(src.h, [&](int y0, int y1) {
        for (int y = y0; y < y1; ++y) {
            for (int x = 0; x < src.w; ++x) {
                float3 acc = make_float3(0.0f, 0.0f, 0.0f);
                for (int i = -r; i <= r; ++i) {
                    int sx = clampi(x + i * dx, 0, src.w - 1);
                    int sy = clampi(y + i * dy, 0, src.h - 1);
                    acc = acc + src.at(sx, sy) * wts[i + r];
                }
                dst.at(x, y) = acc;
            }
        }
    });
}

// BLUR3 do app (1.6, nitidez por camada): a mesma gaussiana separável com um sigma por canal.
void blur_pass3(const Img& src, Img& dst, int dx, int dy, float3 sigma) {
    dst.resize(src.w, src.h);
    float sm = std::max(sigma.x, std::max(sigma.y, sigma.z));
    int r = (int)std::min(std::ceil(sm * 3.0f), 48.0f);
    std::vector<float3> wts(2 * r + 1);
    float sx = std::max(sigma.x, 1e-3f), sy = std::max(sigma.y, 1e-3f), sz = std::max(sigma.z, 1e-3f);
    float3 k = make_float3(-0.5f / (sx * sx), -0.5f / (sy * sy), -0.5f / (sz * sz));
    float3 wsum = make_float3(0.0f, 0.0f, 0.0f);
    for (int i = -r; i <= r; ++i) {
        float d2 = (float)(i * i);
        wts[i + r] = make_float3(std::exp(d2 * k.x), std::exp(d2 * k.y), std::exp(d2 * k.z));
        wsum = wsum + wts[i + r];
    }
    for (auto& w : wts) w = make_float3(w.x / wsum.x, w.y / wsum.y, w.z / wsum.z);
    parallel_rows(src.h, [&](int y0, int y1) {
        for (int y = y0; y < y1; ++y) {
            for (int x = 0; x < src.w; ++x) {
                float3 acc = make_float3(0.0f, 0.0f, 0.0f);
                for (int i = -r; i <= r; ++i) {
                    int px = clampi(x + i * dx, 0, src.w - 1);
                    int py = clampi(y + i * dy, 0, src.h - 1);
                    acc = acc + src.at(px, py) * wts[i + r];
                }
                dst.at(x, y) = acc;
            }
        }
    });
}

// Um nível de mipmap a partir do anterior (média 2x2).
void downsample(const Img& src, Img& dst) {
    int w = std::max(1, src.w / 2), h = std::max(1, src.h / 2);
    dst.resize(w, h);
    parallel_rows(h, [&](int y0, int y1) {
        for (int y = y0; y < y1; ++y) {
            for (int x = 0; x < w; ++x) {
                int xa = std::min(2 * x, src.w - 1), xb = std::min(2 * x + 1, src.w - 1);
                int ya = std::min(2 * y, src.h - 1), yb = std::min(2 * y + 1, src.h - 1);
                dst.at(x, y) = (src.at(xa, ya) + src.at(xb, ya) + src.at(xa, yb) + src.at(xb, yb)) * 0.25f;
            }
        }
    });
}

struct Chain {
    bool on = false;
    float thr = 0.0f, sigma = 0.0f, limit = 1.0f;
    int lum_only = 0;
};

// Cadeia de brilho do Engine: EXTRACT → mipmaps → desfoque horizontal no nível escolhido → vertical.
void glow(const Img& lin, const Chain& c, Img& out) {
    Img hi;
    hi.resize(lin.w, lin.h);
    parallel_rows(lin.h, [&](int y0, int y1) {
        for (int y = y0; y < y1; ++y)
            for (int x = 0; x < lin.w; ++x) hi.at(x, y) = pc_extract(lin.at(x, y), c.thr, c.limit, c.lum_only);
    });
    int lvl = 0;
    while (c.sigma / (float)(1 << lvl) > 6.0f && lvl < 8 && (lin.w >> (lvl + 1)) >= 4 && (lin.h >> (lvl + 1)) >= 4)
        ++lvl;
    Img level = hi, tmp;
    for (int i = 0; i < lvl; ++i) {
        downsample(level, tmp);
        level.px.swap(tmp.px);
        level.w = tmp.w;
        level.h = tmp.h;
    }
    float sig = std::max(c.sigma / (float)(1 << lvl), 0.5f);
    Img a;
    blur_pass(level, a, 1, 0, sig);
    blur_pass(a, out, 0, 1, sig);
}

// Grade do ruído do grão (NOISE do app) e a B-spline cúbica que a amostra (texBicubic).
struct NoiseGrid {
    int gw = 0, gh = 0;
    std::vector<float4> g;
    void build(int gw_, int gh_, uint seed8) {
        gw = gw_;
        gh = gh_;
        g.resize((size_t)gw * gh);
        parallel_rows(gh, [&](int y0, int y1) {
            for (int y = y0; y < y1; ++y)
                for (int x = 0; x < gw; ++x) g[(size_t)y * gw + x] = pc_gauss4((uint)x, (uint)y, seed8);
        });
    }
    float4 sample(float u, float v) const {
        float x = u * (float)gw - 0.5f;
        float y = v * (float)gh - 0.5f;
        float ix = std::floor(x), iy = std::floor(y);
        float fx = x - ix, fy = y - iy;
        float4 acc = make_float4(0.0f, 0.0f, 0.0f, 0.0f);
        for (int b = 0; b < 4; ++b) {
            float wy = pc_cubw(fy, b);
            int ty = clampi((int)iy - 1 + b, 0, gh - 1);
            for (int a = 0; a < 4; ++a) {
                float wx = pc_cubw(fx, a);
                int tx = clampi((int)ix - 1 + a, 0, gw - 1);
                acc = acc + g[(size_t)ty * gw + tx] * (wx * wy);
            }
        }
        return acc;
    }
};

inline float gauge(int gi, int field) { return PC_GAUGE[gi * 7 + field]; }

// Domínio do LUT da cor: log2 da luz linear de -14 a +8 stops em volta do cinza (0 = preto exato).
const float LUT_LO = -14.0f, LUT_SPAN = 22.0f;
inline float lut_axis_to_lin(float x) { return 0.18f * (std::exp2(x * LUT_SPAN + LUT_LO) - std::exp2(LUT_LO)); }
inline float lin_to_lut_axis(float l) {
    return (std::log2(std::max(l, 0.0f) / 0.18f + std::exp2(LUT_LO)) - LUT_LO) / LUT_SPAN;
}
inline float3 lut_to_lin(float3 c) {
    return make_float3(lut_axis_to_lin(c.x), lut_axis_to_lin(c.y), lut_axis_to_lin(c.z));
}
inline float3 lin_to_lut(float3 l) {
    return make_float3(lin_to_lut_axis(l.x), lin_to_lut_axis(l.y), lin_to_lut_axis(l.z));
}

inline size_t lut_cell(int x, int y, int z) { return ((size_t)z * (LUT_N - 1) + y) * (LUT_N - 1) + x; }

// Cor pelo LUT, com "células exatas": onde a conta curva demais dentro de uma célula (cores muito
// saturadas perto do limite do gamut, luzes acima de +8 stops), o pixel volta para a conta exata.
inline float3 lut_color(const std::vector<float>& lut, const std::vector<unsigned char>& exact, const pc_vals& V,
                        float3 lin) {
    const int N = LUT_N;
    float3 c = lin_to_lut(lin);
    if (c.x > 1.0f || c.y > 1.0f || c.z > 1.0f) return pc_colorpipe(V, lin);
    float fx = _clampf(c.x, 0.0f, 1.0f) * (N - 1);
    float fy = _clampf(c.y, 0.0f, 1.0f) * (N - 1);
    float fz = _clampf(c.z, 0.0f, 1.0f) * (N - 1);
    int x0 = std::min((int)fx, N - 2), y0 = std::min((int)fy, N - 2), z0 = std::min((int)fz, N - 2);
    if (exact[lut_cell(x0, y0, z0)]) return pc_colorpipe(V, lin);
    float ax = fx - x0, ay = fy - y0, az = fz - z0;
    auto L = [&](int x, int y, int z) {
        const float* p = &lut[(((size_t)z * N + y) * N + x) * 3];
        return make_float3(p[0], p[1], p[2]);
    };
    float3 c00 = L(x0, y0, z0) + (L(x0 + 1, y0, z0) - L(x0, y0, z0)) * ax;
    float3 c10 = L(x0, y0 + 1, z0) + (L(x0 + 1, y0 + 1, z0) - L(x0, y0 + 1, z0)) * ax;
    float3 c01 = L(x0, y0, z0 + 1) + (L(x0 + 1, y0, z0 + 1) - L(x0, y0, z0 + 1)) * ax;
    float3 c11 = L(x0, y0 + 1, z0 + 1) + (L(x0 + 1, y0 + 1, z0 + 1) - L(x0, y0 + 1, z0 + 1)) * ax;
    float3 c0 = c00 + (c10 - c00) * ay;
    float3 c1 = c01 + (c11 - c01) * ay;
    return c0 + (c1 - c0) * az;
}

}  // namespace

int ui_size() { return PC_UI_SIZE; }

void app_default_ui(float* ui) { std::memcpy(ui, PC_APP_DEFAULTS, sizeof(float) * PC_UI_SIZE); }

void start_ui(float* ui) {
    for (int i = 0; i < PC_PARAM_COUNT; ++i) {
        const pc_param_def& p = PC_PARAMS[i];
        int n = p.kind == 4 ? 3 : 1;
        for (int k = 0; k < n; ++k) ui[p.offset + k] = (float)p.def[k];
    }
}

bool preset_ui(int index, float* ui) {
    if (index < 0 || index >= PC_PRESET_COUNT) return false;
    std::memcpy(ui, PC_PRESET_VALUES[index], sizeof(float) * PC_UI_SIZE);
    return true;
}

// ---------------------------------------------------------------- looks .json / .plc
bool load_look_json(const std::string& text, float* ui, std::string* error) {
    json::Value root;
    std::string err;
    if (!json::Parser(text).parse(&root, &err)) {
        if (error) *error = err;
        return false;
    }
    const json::Value* vals = root.get("valores");
    if (!vals || vals->type != json::Value::Object) {
        if (error) *error = "o arquivo nao tem a chave \"valores\" (look do PeliculaConverter)";
        return false;
    }
    app_default_ui(ui);
    for (int i = 0; i < PC_PARAM_COUNT; ++i) {
        const pc_param_def& p = PC_PARAMS[i];
        if (!p.key[0]) continue;
        const json::Value* v = vals->get(p.key);
        if (!v) continue;
        float* dst = ui + p.offset;
        switch (p.kind) {
            case 0:  // float (percentuais: o app guarda 0..1, a interface 0..100)
                if (v->type == json::Value::Number)
                    *dst = (float)std::min(std::max(v->num / p.scale, p.lo), p.hi);
                break;
            case 1:
                if (v->type == json::Value::Number) *dst = (float)std::min(std::max(std::floor(v->num + 0.5), p.lo), p.hi);
                break;
            case 2:
                if (v->type == json::Value::Bool) *dst = v->b ? 1.0f : 0.0f;
                else if (v->type == json::Value::Number) *dst = v->num != 0.0 ? 1.0f : 0.0f;
                break;
            case 3: {
                std::string s = v->type == json::Value::String ? v->str : std::string();
                if (v->type == json::Value::Number) {  // ISO e afins podem vir como número
                    std::ostringstream os;
                    os.imbue(std::locale::classic());
                    os << v->num;
                    s = os.str();
                }
                for (int k = 0; k < p.nchoices; ++k)
                    if (s == p.choice_values[k]) *dst = (float)k;
                break;
            }
            case 4:
                if (v->type == json::Value::Array && v->arr.size() >= 3)
                    for (int k = 0; k < 3; ++k)
                        if (v->arr[k].type == json::Value::Number)
                            dst[k] = (float)std::min(std::max(v->arr[k].num, 0.0), 1.0);
                break;
        }
    }
    return true;
}

bool load_look_file(const std::string& utf8_path, float* ui, std::string* error) {
    FILE* f = nullptr;
#ifdef _WIN32
    int n = MultiByteToWideChar(CP_UTF8, 0, utf8_path.c_str(), -1, nullptr, 0);
    std::wstring wp(n > 0 ? n : 1, L'\0');
    if (n > 0) MultiByteToWideChar(CP_UTF8, 0, utf8_path.c_str(), -1, &wp[0], n);
    f = _wfopen(wp.c_str(), L"rb");
#else
    f = std::fopen(utf8_path.c_str(), "rb");
#endif
    if (!f) {
        if (error) *error = "nao foi possivel abrir o arquivo";
        return false;
    }
    std::string text;
    char buf[65536];
    size_t got;
    while ((got = std::fread(buf, 1, sizeof(buf), f)) > 0) {
        text.append(buf, got);
        if (text.size() > (64u << 20)) break;  // um look tem poucos KB; projeto .plc grande ainda cabe
    }
    std::fclose(f);
    return load_look_json(text, ui, error);
}

// ---------------------------------------------------------------- cor
std::shared_ptr<const Renderer::Lut> Renderer::lut_for(const float* ui) {
    std::lock_guard<std::mutex> lock(lut_mutex_);
    if (lut_ && std::memcmp(lut_->key.data(), ui, sizeof(float) * PC_UI_SIZE) == 0) return lut_;
    pc_vals V;
    pc_unpack(ui, &V);
    const int N = LUT_N;
    auto lut = std::make_shared<Lut>();
    lut->key.assign(ui, ui + PC_UI_SIZE);
    lut->data.resize((size_t)N * N * N * 3);
    float* data = lut->data.data();
    const float step = 1.0f / (N - 1);
    auto eval = [&](float x, float y, float z) { return pc_colorpipe(V, lut_to_lin(make_float3(x, y, z))); };
    const float tol = lut_tol_;
    auto differs = [tol](float3 a, float3 b) {
        return std::max(std::fabs(a.x - b.x), std::max(std::fabs(a.y - b.y), std::fabs(a.z - b.z))) > tol;
    };
    parallel_rows(N * N, [&](int r0, int r1) {
        for (int r = r0; r < r1; ++r) {
            int z = r / N, y = r % N;
            for (int x = 0; x < N; ++x) {
                float3 o = eval(x * step, y * step, z * step);
                float* p = &data[(((size_t)z * N + y) * N + x) * 3];
                p[0] = o.x;
                p[1] = o.y;
                p[2] = o.z;
            }
        }
    });
    auto node = [&](int x, int y, int z) {
        const float* p = &data[(((size_t)z * N + y) * N + x) * 3];
        return make_float3(p[0], p[1], p[2]);
    };
    // Teste de cada célula: o centro e o meio das arestas, na conta exata x interpolação.
    const int M = N - 1;
    std::vector<unsigned char> center((size_t)M * M * M), ex((size_t)N * N * M), ey((size_t)N * N * M),
        ez((size_t)N * N * M);
    parallel_rows(N * N, [&](int r0, int r1) {
        for (int r = r0; r < r1; ++r) {
            int z = r / N, y = r % N;
            for (int x = 0; x < M; ++x) {
                // ex: aresta em R que sai do nó (R=x, G=y, B=z), índice (B*N + G)*M + R;
                // ey: aresta em G que sai de (R=y, G=x, B=z), índice (B*N + R)*M + G;
                // ez: aresta em B que sai de (R=y, G=z, B=x), índice (G*N + R)*M + B.
                size_t e = ((size_t)z * N + y) * M + x;
                ex[e] = differs(eval((x + 0.5f) * step, y * step, z * step), (node(x, y, z) + node(x + 1, y, z)) * 0.5f);
                ey[e] = differs(eval(y * step, (x + 0.5f) * step, z * step), (node(y, x, z) + node(y, x + 1, z)) * 0.5f);
                ez[e] = differs(eval(y * step, z * step, (x + 0.5f) * step), (node(y, z, x) + node(y, z, x + 1)) * 0.5f);
                if (z < M && y < M) {
                    float3 avg = (node(x, y, z) + node(x + 1, y, z) + node(x, y + 1, z) + node(x + 1, y + 1, z) +
                                  node(x, y, z + 1) + node(x + 1, y, z + 1) + node(x, y + 1, z + 1) +
                                  node(x + 1, y + 1, z + 1)) * 0.125f;
                    center[lut_cell(x, y, z)] = differs(eval((x + 0.5f) * step, (y + 0.5f) * step, (z + 0.5f) * step), avg);
                }
            }
        }
    });
    lut->exact.assign((size_t)M * M * M, 0);
    unsigned char* flag = lut->exact.data();
    parallel_rows(M, [&](int z0, int z1) {
        for (int z = z0; z < z1; ++z)
            for (int y = 0; y < M; ++y)
                for (int x = 0; x < M; ++x) {
                    // a célula usa as 12 arestas em volta dela (4 em cada eixo) e o centro
                    bool bad = center[lut_cell(x, y, z)] != 0;
                    for (int j = 0; j < 2 && !bad; ++j)
                        for (int k = 0; k < 2 && !bad; ++k) {
                            bad = ex[((size_t)(z + k) * N + (y + j)) * M + x] ||
                                  ey[((size_t)(z + k) * N + (x + j)) * M + y] ||
                                  ez[((size_t)(y + k) * N + (x + j)) * M + z];
                        }
                    flag[lut_cell(x, y, z)] = bad ? 1 : 0;
                }
    });
    lut_ = lut;  // quem ainda renderiza com o LUT anterior continua com a sua cópia
    return lut_;
}

void Renderer::set_lut_tolerance(float tol) {
    std::lock_guard<std::mutex> lock(lut_mutex_);
    lut_tol_ = tol;
    lut_.reset();
}

float Renderer::lut_exact_fraction(const float* ui) {
    std::shared_ptr<const Lut> lut = lut_for(ui);
    size_t n = 0;
    for (unsigned char f : lut->exact) n += f;
    return lut->exact.empty() ? 0.0f : (float)n / (float)lut->exact.size();
}

void Renderer::color(const float* ui, const float* in, float* out, int n, int exact_color) {
    pc_vals V;
    pc_unpack(ui, &V);
    std::shared_ptr<const Lut> lut = exact_color ? nullptr : lut_for(ui);
    parallel_rows(n, [&](int a, int b) {
        for (int i = a; i < b; ++i) {
            float3 code = make_float3(in[i * 3], in[i * 3 + 1], in[i * 3 + 2]);
            float3 lin = pc_gain(V, pc_input(V, code), make_float3(0.0f, 0.0f, 0.0f));
            float3 y = lut ? lut_color(lut->data, lut->exact, V, lin) : pc_colorpipe(V, lin);
            out[i * 3] = y.x;
            out[i * 3 + 1] = y.y;
            out[i * 3 + 2] = y.z;
        }
    });
}

void Renderer::render(const float* ui, const float* in, float* out, int w, int h, int frame, float fps,
                      int exact_color) {
    PC_PROFILE_START;
    pc_vals V;
    pc_unpack(ui, &V);
    std::shared_ptr<const Lut> lut = exact_color ? nullptr : lut_for(ui);
    PC_MARK("lut");
    const float W = (float)w, H = (float)h;
    const float scale = H / 1080.0f;
    if (fps <= 0.0f) fps = 24.0f;
    pc_frame F;
    pc_frame_params(V, w, h, frame, fps, &F);
    const int gi = V.bitola;

    PC_MARK("start");
    // ---------------------------------------------------------------- BASE: tremor, lente, entrada, ganho, vinheta
    const float dist = V.lente_on == 1 ? V.distorcao : 0.0f;
    const float ca = V.lente_on == 1 ? (V.aberracao * scale / (0.5f * H)) : 0.0f;
    const float vig_amt = std::min((V.lente_on == 1 ? V.vinheta : 0.0f) + gauge(gi, 4) * V.bitola_vinheta, 1.5f);
    const float3 gx = make_float3(F.g0, F.g1, F.g2);
    const float cr = std::cos(F.rot), sr = std::sin(F.rot);
    Img lin;
    lin.resize(w, h);
    parallel_rows(h, [&](int y0, int y1) {
        for (int y = y0; y < y1; ++y) {
            for (int x = 0; x < w; ++x) {
                float u = ((float)x + 0.5f) / W, v = ((float)y + 0.5f) / H;
                float px = (u - 0.5f) * W / F.zoom, py = (v - 0.5f) * H / F.zoom;
                float su = (cr * px - sr * py - F.sh_x) / W + 0.5f;
                float sv = (sr * px + cr * py - F.sh_y) / H + 0.5f;
                float3 code;
                float2 pg = pc_lens(su, sv, W, H, dist, 1.0f);
                if (ca != 0.0f) {
                    float2 pr = pc_lens(su, sv, W, H, dist, 1.0f + ca);
                    float2 pb = pc_lens(su, sv, W, H, dist, 1.0f - ca);
                    code = make_float3(sample_rgb(in, w, h, pr.x, pr.y).x, sample_rgb(in, w, h, pg.x, pg.y).y,
                                       sample_rgb(in, w, h, pb.x, pb.y).z);
                } else {
                    code = sample_rgb(in, w, h, pg.x, pg.y);
                }
                float3 l = pc_gain(V, pc_input(V, code), gx);
                float vg = pc_vignette(u, v, W, H, vig_amt, V.vinheta_raio, V.vinheta_suavidade, V.vinheta_redondeza);
                lin.at(x, y) = l * vg;
            }
        }
    });

    PC_MARK("base");
    // ---------------------------------------------------------------- maciez / nitidez (BLUR x 2)
    float sig_g = V.bitola_desfoque_on == 1 ? gauge(gi, 2) * V.bitola_resolucao : 0.0f;
    float sig_u = V.lente_on == 1 ? V.raio_maciez * V.maciez * 2.0f : 0.0f;
    float sig_m = PC_MTF[V.mtf] * 2.0f * V.mtf_forca;
    float sig_r = 0.0f;  // 1.6: maciez pelo grão (grao.soft_sigma)
    if (V.grao_maciez > 0.0f && V.grao_on == 1 && V.grao_forca > 0.0f)
        sig_r = PC_GRAIN_SOFT_K * 0.8f * V.grao_tamanho * gauge(gi, 0) * std::pow(PC_ISO[V.iso] / 250.0f, 0.18f) *
                V.grao_maciez;
    float soft = std::sqrt(sig_g * sig_g + sig_u * sig_u + sig_m * sig_m + sig_r * sig_r) * scale;
    float sharp = V.lente_on == 1 ? V.nitidez : 0.0f;
    float soft_sigma = 0.0f, soft_mix = 0.0f;
    if (soft > 0.05f) {
        soft_sigma = soft;
        soft_mix = 1.0f;
    } else if (sharp > 0.0f) {
        soft_sigma = std::max(V.raio_maciez * scale, 0.6f);
    }
    // 1.6: diferença de nitidez entre camadas (grao.layer_softness): um sigma por canal
    bool layers = false;
    float3 s3 = make_float3(0.0f, 0.0f, 0.0f);
    if (V.mtf_camadas > 0.0f) {
        bool with_print = (V.copia != PC_COPIA_NENHUMA && V.copia_forca > 0.0f) ||
                          (V.lab_on == 1 && V.lab_copia != PC_LAB_COPIA_NENHUMA);
        int lo = with_print ? 3 : 0;
        float kl = 2.0f * V.mtf_camadas * PC_PX_MM[gi] * 0.001f * scale;
        float dr = PC_MTF_LAYERS[lo] * kl, dg = PC_MTF_LAYERS[lo + 1] * kl, db = PC_MTF_LAYERS[lo + 2] * kl;
        float3 t3 = make_float3(std::sqrt(soft * soft + dr * dr), std::sqrt(soft * soft + dg * dg),
                                std::sqrt(soft * soft + db * db));
        float tm = std::max(t3.x, std::max(t3.y, t3.z));
        if (tm > 0.05f) {
            layers = true;
            s3 = t3;
            soft_sigma = tm;
            soft_mix = 1.0f;
        }
    }
    Img softimg;
    if (soft_sigma > 0.0f) {
        Img t;
        if (layers) {
            blur_pass3(lin, t, 1, 0, s3);
            blur_pass3(t, softimg, 0, 1, s3);
        } else {
            blur_pass(lin, t, 1, 0, soft_sigma);
            blur_pass(t, softimg, 0, 1, soft_sigma);
        }
    }

    PC_MARK("soft");
    // ---------------------------------------------------------------- halação, bloom e névoa
    Chain hal, bloom, mist;
    if (V.hal_on == 1 && V.hal_forca > 0.0f) {
        hal.on = true;
        hal.thr = 0.18f * std::exp2(V.hal_limiar);
        hal.sigma = V.hal_raio * gauge(gi, 5) * scale;
        hal.limit = 8.0f;
        hal.lum_only = 1;
    }
    if (V.bloom_on == 1 && V.bloom_forca > 0.0f) {
        bloom.on = true;
        bloom.thr = 0.18f * std::exp2(V.bloom_limiar);
        bloom.sigma = V.bloom_raio * scale;
        bloom.limit = 6.0f;
    }
    if (V.bloom_on == 1 && V.nevoa_forca > 0.0f) {
        mist.on = true;
        mist.thr = 0.0f;
        mist.sigma = V.nevoa_raio * scale;
        mist.limit = 3.0f;
    }
    Img hal_b, bloom_b, mist_b;
    if (hal.on) glow(lin, hal, hal_b);
    if (bloom.on) glow(lin, bloom, bloom_b);
    if (mist.on) glow(lin, mist, mist_b);

    PC_MARK("glow");
    // ---------------------------------------------------------------- grão (grade de ruído)
    NoiseGrid noise;
    float grain_amt = 0.0f;
    float ng_k = 0.0f;  // 1.6: multiplicador do grão no negativo (o de grain_amt sem o 0,011)
    const bool grain = V.grao_on == 1 && V.grao_forca > 0.0f;
    if (grain) {
        float iso = PC_ISO[V.iso];
        float iso_amt = std::pow(iso / 250.0f, 0.35f);
        float iso_size = std::pow(iso / 250.0f, 0.18f);
        float size = 0.8f * V.grao_tamanho * gauge(gi, 0) * iso_size * scale;
        float gsz = std::max(size, 1.0f);
        long long seed = (long long)V.grao_semente * 7919LL + (V.grao_animado == 1 ? frame : 0);
        seed %= 2147483647LL;
        int gw = std::max(2, (int)std::ceil(W / gsz));
        int gh = std::max(2, (int)std::ceil(H / gsz));
        float push = V.lab_on == 1 ? std::pow(1.15f, V.lab_revelacao) : 1.0f;
        grain_amt = 0.011f * V.grao_forca * gauge(gi, 1) * iso_amt * std::sqrt(std::min(1.0f, size)) * push;
        ng_k = V.grao_forca * gauge(gi, 1) * iso_amt * std::sqrt(std::min(1.0f, size)) * push;
        noise.build(gw, gh, (uint)seed * 8u);
    }
    // 1.6: grão no negativo (grao.negative_grain): o mesmo campo na densidade das camadas, dentro da cor
    const bool ngrain = grain && V.lab_on == 1 && V.lab_grao == 1;
    float3 ng_amp = make_float3(0.0f, 0.0f, 0.0f);
    if (ngrain) ng_amp = make_float3(PC_NG_AMP[0], PC_NG_AMP[1], PC_NG_AMP[2]) * ng_k;

    PC_MARK("noise");
    // ---------------------------------------------------------------- curva sobreposta ("Mostrar curva")
    std::vector<float3> curve;
    if (V.mostrar_curva == 1) {
        curve.resize(w);
        for (int x = 0; x < w; ++x) {
            float t = -8.0f + 16.0f * ((float)x + 0.5f) / W;
            float3 g = pc_gain(V, make_float3(0.18f * std::exp2(t), 0.18f * std::exp2(t), 0.18f * std::exp2(t)),
                               make_float3(0.0f, 0.0f, 0.0f));
            curve[x] = pc_colorpipe(V, g);
        }
    }

    PC_MARK("curve");
    // ---------------------------------------------------------------- FINAL
    const int dg = F.dg;
    const float dust = (dg == 1 && V.poeira_on == 1) ? V.poeira : 0.0f;
    const float scr = (dg == 1 && V.riscos_on == 1) ? V.riscos : 0.0f;
    const bool damage = dust > 0.0f || scr > 0.0f || F.hair_on > 0.0f || F.stain_amt > 0.0f || F.cue > 0.0f ||
                        F.splice_on > 0.0f;
    float aspect = PC_PROP[V.proporcao];
    if (aspect < 0.0f) aspect = gauge(gi, 6);
    parallel_rows(h, [&](int y0, int y1) {
        for (int y = y0; y < y1; ++y) {
            for (int x = 0; x < w; ++x) {
                float u = ((float)x + 0.5f) / W, v = ((float)y + 0.5f) / H;
                const float* ip = in + ((size_t)y * w + x) * 3;
                float3 code0 = make_float3(ip[0], ip[1], ip[2]);
                float3 l = lin.at(x, y);
                if (soft_sigma > 0.0f) {
                    float3 b = softimg.at(x, y);
                    float3 base = l + (b - l) * soft_mix;
                    l = pc_max3(base + (l - b) * sharp, 0.0f);
                }
                if (mist.on) {
                    float3 m = sample(mist_b, u, v);
                    l = l + (m - l) * (0.3f * V.nevoa_forca) + m * (0.35f * V.nevoa_forca);
                }
                if (bloom.on) l = l + sample(bloom_b, u, v) * (V.bloom_forca * 0.22f);
                if (hal.on) l = l + V.hal_cor * (sample(hal_b, u, v).x * V.hal_forca * 0.32f);
                if (F.leak_on > 0.0f) l = l + pc_leak(u, v, W / H, F.L0, F.L1, V.vazamento_cor, V.vazamento);
                float3 yv;
                if (ngrain) {
                    float4 nf = noise.sample(u, v) * 2.08f;
                    float4 nc = noise.sample(u * 0.4347f + 0.311f, v * 0.4347f + 0.173f) * 2.08f;
                    yv = pc_colorpipe_ng(V, l, pc_neg_grain(nf, nc, V.grao_aspereza, V.grao_cor) * ng_amp);
                } else {
                    yv = lut ? lut_color(lut->data, lut->exact, V, l) : pc_colorpipe(V, l);
                }
                if (grain && !ngrain) {
                    float4 nf = noise.sample(u, v) * 2.08f;
                    float4 nc = noise.sample(u * 0.4347f + 0.311f, v * 0.4347f + 0.173f) * 2.08f;
                    yv = pc_apply_grain(yv, nf, nc, V.grao_aspereza, V.grao_cor,
                                        make_float3(V.grao_sombras, V.grao_meios, V.grao_luzes), grain_amt);
                }
                if (damage) {
                    yv = pc_damage(yv, u, v, W, H, frame, F.sd, F.stain_amt, F.stain_seed, F.hair_on, F.hair_seed,
                                   V.cabelo_tamanho, F.hair_wig, F.cue, F.splice_on, F.splice_y, dust,
                                   V.poeira_tamanho, V.poeira_tipo, scr, V.riscos_largura);
                }
                yv = code0 + (yv - code0) * V.mix_geral;
                if (V.mold_on == 1)
                    yv = pc_frame_mask(yv, u, v, W, H, scale, aspect, V.cantos, V.borda_suave, V.borda_irregular,
                                       V.cor_barras);
                yv = pc_clamp3(yv, 0.0f, 1.0f);
                if (!curve.empty()) yv = pc_curve_overlay(yv, curve[x], y, h);
                float* op = out + ((size_t)y * w + x) * 3;
                op[0] = yv.x;
                op[1] = yv.y;
                op[2] = yv.z;
            }
        }
    });
    PC_MARK("final");
}

}  // namespace pc
