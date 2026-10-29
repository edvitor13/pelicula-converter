// PeliculaConverter 1.5.0 - nucleo de cor e textura do plugin OpenFX.
// Gerado por pelicula/ofx.py a partir dos kernels de pelicula/resolve.py. Nao edite: rode
// "python tools/gerar_ofx.py" (ou pelicula-cli resolve --ofx-fonte DIR).
#pragma once

#include <cmath>

typedef unsigned int uint;
struct float2 { float x, y; };
struct float3 { float x, y, z; };
struct float4 { float x, y, z, w; };
struct pc_color3 { float r, g, b; };
static inline float2 make_float2(float x, float y) { float2 v = {x, y}; return v; }
static inline float3 make_float3(float x, float y, float z) { float3 v = {x, y, z}; return v; }
static inline float4 make_float4(float x, float y, float z, float w) { float4 v = {x, y, z, w}; return v; }
static inline float2 operator+(float2 a, float2 b) { return make_float2(a.x + b.x, a.y + b.y); }
static inline float2 operator-(float2 a, float2 b) { return make_float2(a.x - b.x, a.y - b.y); }
static inline float2 operator*(float2 a, float s) { return make_float2(a.x * s, a.y * s); }
static inline float3 operator+(float3 a, float3 b) { return make_float3(a.x + b.x, a.y + b.y, a.z + b.z); }
static inline float3 operator-(float3 a, float3 b) { return make_float3(a.x - b.x, a.y - b.y, a.z - b.z); }
static inline float3 operator-(float3 a) { return make_float3(-a.x, -a.y, -a.z); }
static inline float3 operator*(float3 a, float3 b) { return make_float3(a.x * b.x, a.y * b.y, a.z * b.z); }
static inline float3 operator*(float3 a, float s) { return make_float3(a.x * s, a.y * s, a.z * s); }
static inline float3 operator*(float s, float3 a) { return make_float3(a.x * s, a.y * s, a.z * s); }
static inline float3 operator/(float3 a, float s) { return make_float3(a.x / s, a.y / s, a.z / s); }
static inline float4 operator+(float4 a, float4 b) { return make_float4(a.x + b.x, a.y + b.y, a.z + b.z, a.w + b.w); }
static inline float4 operator-(float4 a, float4 b) { return make_float4(a.x - b.x, a.y - b.y, a.z - b.z, a.w - b.w); }
static inline float4 operator*(float4 a, float s) { return make_float4(a.x * s, a.y * s, a.z * s, a.w * s); }
static inline float _powf(float a, float b) { return std::pow(a, b); }
static inline float _logf(float a) { return std::log(a); }
static inline float _log2f(float a) { return std::log2(a); }
static inline float _expf(float a) { return std::exp(a); }
static inline float _exp2f(float a) { return std::exp2(a); }
static inline float _fabs(float a) { return std::fabs(a); }
static inline float _fmaxf(float a, float b) { return std::fmax(a, b); }
static inline float _fminf(float a, float b) { return std::fmin(a, b); }
static inline float _clampf(float x, float lo, float hi) { return std::fmin(std::fmax(x, lo), hi); }
static inline float _saturatef(float x) { return _clampf(x, 0.0f, 1.0f); }
static inline float _sqrtf(float a) { return std::sqrt(a); }
static inline float _floorf(float a) { return std::floor(a); }
static inline float _ceilf(float a) { return std::ceil(a); }
static inline float _sinf(float a) { return std::sin(a); }
static inline float _cosf(float a) { return std::cos(a); }
static inline float _atan2f(float y, float x) { return std::atan2(y, x); }
#define PC_F(x) ((float)(x))
#define PC_I(x) ((int)(x))
#define PC_U(x) ((uint)(x))

#define PC_DSLOPE 0.155f
#define PC_DMID 0.45f
#define PC_DP 4.0f
#define PC_CIN_BLACK 0.010797752f
#define PC_C4A 2231.82631f
#define PC_C4B 0.907135875f
#define PC_C4C 0.0928641251f
#define PC_C4S 0.113597209f
#define PC_C4T -0.0180569961f
#define PC_SKIN_LUM 0.25f
#define PC_HLG_A 0.17883277f
#define PC_HLG_B 0.28466892f
#define PC_HLG_C 0.55991073f
#define PC_HLG_K 3.73961219f
#define PC_PQ_M1 0.159301758f
#define PC_PQ_M2 78.84375f
#define PC_PQ_C1 0.8359375f
#define PC_PQ_C2 18.8515625f
#define PC_PQ_C3 18.6875f
static const int PC_IN_ID[22] = { 0, 1, 2, 3, 4, 5, 8, 7, 6, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21 };
static const int PC_IN_CV[22] = { 0, 0, 1, 1, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 0, 0 };
static const float PC_LC3[66] = { 0.005561f, 0.080216f, 0.269036f, 0.381991f, 5.842037f, 0.092778f, 0.006208f, 0.076621f, 0.266007f, 0.382478f, 5.776265f, 0.092782f, 0.006871f, 0.072941f, 0.262978f, 0.382966f, 5.710494f, 0.092786f, 0.007622f, 0.068768f, 0.259627f, 0.383508f, 5.637732f, 0.092791f, 0.008318f, 0.064901f, 0.256598f, 0.383999f, 5.57196f, 0.092795f, 0.009031f, 0.060939f, 0.253569f, 0.384493f, 5.506188f, 0.0928f, 0.00984f, 0.056443f, 0.250219f, 0.38504f, 5.433426f, 0.092805f, 0.010591f, 0.052272f, 0.24719f, 0.385537f, 5.367655f, 0.092809f, 0.011361f, 0.047996f, 0.244161f, 0.386036f, 5.301883f, 0.092814f, 0.012235f, 0.043137f, 0.24081f, 0.38659f, 5.229121f, 0.092819f, 0.013047f, 0.038625f, 0.237781f, 0.387093f, 5.16335f, 0.092824f };
#define PC_LC3_STD (7)
static const float PC_GCL[66] = { 1.147f, 1.264f, 1.312f, 1.147f, 1.264f, 1.312f, 1.59386521f, 1.264f, 1.312f, 1.54865846f, 1.31629144f, 1.312f, 1.58395633f, 1.264f, 1.312f, 1.70882131f, 1.264f, 1.312f, 1.84520049f, 1.3021352f, 1.4977769f, 1.77689157f, 1.33407676f, 1.34526449f, 1.147f, 1.264f, 1.312f, 1.52693835f, 1.264f, 1.312f, 1.76729382f, 1.264f, 1.312f, 1.59386521f, 1.264f, 1.312f, 1.59386521f, 1.264f, 1.312f, 1.59386521f, 1.264f, 1.312f, 1.79799487f, 1.3201804f, 1.34936766f, 1.79799487f, 1.3201804f, 1.34936766f, 1.59386521f, 1.264f, 1.312f, 1.59386521f, 1.264f, 1.312f, 1.93393892f, 1.264f, 1.312f, 1.62271133f, 1.264f, 1.312f, 1.76652863f, 1.264f, 1.312f, 1.59386521f, 1.264f, 1.312f };
#define PC_GC_THR_R 0.815f
#define PC_GC_THR_G 0.803f
#define PC_GC_THR_B 0.88f
#define PC_GC_PWR 1.2f
static const float PC_GAM[198] = { 1.0f, 0.0f, 0.0f, 0.0f, 1.0f, 0.0f, 0.0f, 0.0f, 1.0f, 1.0f, 0.0f, 0.0f, 0.0f, 1.0f, 0.0f, 0.0f, 0.0f, 1.0f, 1.660491f, -0.587641139f, -0.0728498633f, -0.124550475f, 1.1328999f, -0.0083494226f, -0.0181507634f, -0.100578898f, 1.11872966f, 1.62694741f, -0.540138539f, -0.0868088709f, -0.178515527f, 1.41794093f, -0.2394254f, -0.044436115f, -0.195919966f, 1.24035608f, 1.61752344f, -0.537286622f, -0.0802368141f, -0.0705727409f, 1.33461306f, -0.264040321f, -0.021101728f, -0.226953875f, 1.2480556f, 1.80657588f, -0.695697274f, -0.11087861f, -0.170090343f, 1.30595522f, -0.135864873f, -0.025205784f, -0.154468329f, 1.17967411f, 1.98197602f, -0.900431837f, -0.0815441813f, -0.178143182f, 1.50046836f, -0.322325176f, -0.101795966f, -0.535263459f, 1.63705943f, 1.8986149f, -0.792176183f, -0.106438716f, -0.168948786f, 1.48897575f, -0.320026968f, -0.121539161f, -0.315675853f, 1.43721501f, 1.0f, 0.0f, 0.0f, 0.0f, 1.0f, 0.0f, 0.0f, 0.0f, 1.0f, 1.56844516f, -0.522716456f, -0.0457287012f, -0.0863608945f, 1.34497613f, -0.258615232f, -0.0520425482f, -0.249146782f, 1.30118933f, 1.89312344f, -0.780881504f, -0.112241939f, -0.205700358f, 1.34025749f, -0.134557131f, -0.0127057429f, -0.152184876f, 1.16489062f, 1.660491f, -0.587641139f, -0.0728498633f, -0.124550475f, 1.1328999f, -0.0083494226f, -0.0181507634f, -0.100578898f, 1.11872966f, 1.660491f, -0.587641139f, -0.0728498633f, -0.124550475f, 1.1328999f, -0.0083494226f, -0.0181507634f, -0.100578898f, 1.11872966f, 1.660491f, -0.587641139f, -0.0728498633f, -0.124550475f, 1.1328999f, -0.0083494226f, -0.0181507634f, -0.100578898f, 1.11872966f, 1.9238613f, -0.798760663f, -0.125100633f, -0.204310848f, 1.49589851f, -0.291587662f, -0.023685021f, -0.420127011f, 1.44381203f, 1.9238613f, -0.798760663f, -0.125100633f, -0.204310848f, 1.49589851f, -0.291587662f, -0.023685021f, -0.420127011f, 1.44381203f, 1.660491f, -0.587641139f, -0.0728498633f, -0.124550475f, 1.1328999f, -0.0083494226f, -0.0181507634f, -0.100578898f, 1.11872966f, 1.660491f, -0.587641139f, -0.0728498633f, -0.124550475f, 1.1328999f, -0.0083494226f, -0.0181507634f, -0.100578898f, 1.11872966f, 2.11985147f, -1.07570505f, -0.0441464158f, -0.230335855f, 1.37244215f, -0.142106296f, -0.0142274334f, -0.150224987f, 1.16445242f, 1.67472308f, -0.579788957f, -0.0949341205f, -0.0980877339f, 1.33398371f, -0.235895972f, -0.0409671441f, -0.242983761f, 1.28395091f, 1.87791513f, -0.794168761f, -0.0837463671f, -0.176806981f, 1.35099962f, -0.17419264f, -0.0262011264f, -0.148422262f, 1.17462339f, 1.660491f, -0.587641139f, -0.0728498633f, -0.124550475f, 1.1328999f, -0.0083494226f, -0.0181507634f, -0.100578898f, 1.11872966f };
static const float PC_BWW[18] = { 0.25f, 0.65f, 0.1f, 0.75f, 0.22f, 0.03f, 0.55f, 0.38f, 0.07f, 0.4f, 0.52f, 0.08f, 0.18f, 0.72f, 0.1f, 0.08f, 0.37f, 0.55f };
static const float PC_TONE[30] = { 1.0f, 1.0f, 1.0f, 1.0f, 1.0f, 1.0f, 1.12f, 0.92f, 0.7f, 1.06f, 0.99f, 0.88f, 1.0f, 0.86f, 0.93f, 1.0f, 0.99f, 0.98f, 0.55f, 0.85f, 1.25f, 0.85f, 0.97f, 1.08f, 1.15f, 1.0f, 0.62f, 1.05f, 1.02f, 0.9f };
static const int PC_TONE_ON[5] = { 0, 1, 1, 1, 1 };
static const int PC_PR_ON[4] = { 0, 1, 1, 1 };
static const float PC_PR[48] = { 1.0f, 1.0f, 1.0f, 1.0f, 0.0f, 0.0f, 0.0f, 0.155f, 0.45f, 0.0f, 1.0f, 0.0f, 1.08f, 0.98f, 1.0f, 1.035f, 0.035f, 0.0f, -0.05f, 0.1705f, 0.43f, 0.012f, 0.975f, 0.0f, 1.1f, 0.985f, 1.0f, 1.03f, 0.025f, 0.0f, -0.03f, 0.186f, 0.42f, 0.004f, 0.985f, 0.0f, 1.12f, 1.0f, 1.0f, 1.0f, -0.015f, 0.01f, 0.03f, 0.1674f, 0.44f, 0.014f, 0.975f, 0.0f };
static const float PC_PR_SOFT[8] = { 0.0f, 0.0f, 0.35f, 0.15f, 0.3f, 0.05f, 0.35f, 0.15f };
#define PC_LAB_TARGET 0.901647464f
#define PC_LAB_POINT 0.025f
#define PC_LAB_VIEW 2.6f
#define PC_LAB_DENS_K 0.5f
#define PC_SPLIT_A 0.6f
#define PC_SPLIT_B 0.45f
#define PC_BYP_C 0.5f
#define PC_BYP_D 0.3f
#define PC_LAB_2383 0
static const float PC_NEG[280] = { 0.92f, 0.07f, 0.01f, 0.04f, 0.92f, 0.04f, 0.01f, 0.07f, 0.92f, 0.62f, 0.62f, 0.63f, -1.5f, -1.5f, -1.45f, 2.05f, 2.05f, 2.0f, 0.22f, 0.42f, 0.92f, 0.07f, 0.01f, 0.04f, 0.92f, 0.04f, 0.01f, 0.07f, 0.92f, 0.6f, 0.6f, 0.61f, -1.6f, -1.6f, -1.55f, 2.0f, 2.0f, 1.95f, 0.24f, 0.38f, 0.91f, 0.08f, 0.01f, 0.05f, 0.91f, 0.04f, 0.01f, 0.08f, 0.91f, 0.6f, 0.61f, 0.59f, -1.6f, -1.62f, -1.58f, 2.0f, 2.0f, 1.95f, 0.24f, 0.37f, 0.91f, 0.08f, 0.01f, 0.05f, 0.91f, 0.04f, 0.01f, 0.08f, 0.91f, 0.57f, 0.58f, 0.58f, -1.72f, -1.72f, -1.66f, 1.9f, 1.9f, 1.85f, 0.28f, 0.36f, 0.88f, 0.1f, 0.02f, 0.05f, 0.88f, 0.07f, 0.02f, 0.11f, 0.87f, 0.55f, 0.56f, 0.55f, -1.62f, -1.65f, -1.62f, 2.1f, 2.1f, 2.05f, 0.3f, 0.28f, 0.94f, 0.05f, 0.01f, 0.03f, 0.94f, 0.03f, 0.01f, 0.05f, 0.94f, 0.64f, 0.65f, 0.64f, -1.5f, -1.5f, -1.48f, 1.9f, 1.9f, 1.85f, 0.25f, 0.56f, 0.92f, 0.07f, 0.01f, 0.04f, 0.92f, 0.04f, 0.01f, 0.07f, 0.92f, 0.64f, 0.65f, 0.66f, -1.4f, -1.42f, -1.4f, 1.75f, 1.75f, 1.7f, 0.24f, 0.38f, 0.84f, 0.13f, 0.03f, 0.07f, 0.85f, 0.08f, 0.03f, 0.13f, 0.84f, 0.67f, 0.65f, 0.62f, -1.3f, -1.32f, -1.28f, 1.6f, 1.6f, 1.55f, 0.22f, 0.25f, 0.91f, 0.08f, 0.01f, 0.05f, 0.9f, 0.05f, 0.01f, 0.08f, 0.91f, 0.63f, 0.63f, 0.64f, -1.45f, -1.46f, -1.42f, 1.88f, 1.88f, 1.84f, 0.23f, 0.44f, 0.88f, 0.1f, 0.02f, 0.06f, 0.88f, 0.06f, 0.02f, 0.1f, 0.88f, 0.64f, 0.63f, 0.61f, -1.36f, -1.38f, -1.34f, 1.72f, 1.72f, 1.66f, 0.24f, 0.32f, 0.88f, 0.1f, 0.02f, 0.06f, 0.88f, 0.06f, 0.02f, 0.1f, 0.88f, 0.61f, 0.61f, 0.61f, -1.48f, -1.5f, -1.46f, 1.85f, 1.85f, 1.8f, 0.25f, 0.36f, 0.91f, 0.08f, 0.01f, 0.05f, 0.91f, 0.04f, 0.01f, 0.08f, 0.91f, 0.58f, 0.59f, 0.58f, -1.56f, -1.58f, -1.52f, 1.8f, 1.8f, 1.75f, 0.27f, 0.33f, 0.91f, 0.08f, 0.01f, 0.05f, 0.91f, 0.04f, 0.01f, 0.08f, 0.91f, 0.52f, 0.53f, 0.52f, -1.66f, -1.68f, -1.62f, 1.95f, 1.95f, 1.9f, 0.32f, 0.3f, 0.25f, 0.65f, 0.1f, 0.25f, 0.65f, 0.1f, 0.25f, 0.65f, 0.1f, 0.65f, 0.65f, 0.65f, -1.4f, -1.4f, -1.4f, 1.8f, 1.8f, 1.8f, 0.25f, 0.0f };
static const float PC_LPR[119] = { 1.0f, 3.0f, 2.95f, 2.85f, 4.0f, 4.0f, 3.95f, 0.22f, 1.0f, 0.08f, 0.02f, 0.06f, 1.0f, 0.08f, 0.02f, 0.14f, 1.0f, 1.0f, 3.2f, 3.15f, 3.05f, 4.2f, 4.2f, 4.15f, 0.2f, 1.0f, 0.07f, 0.02f, 0.05f, 1.0f, 0.07f, 0.02f, 0.12f, 1.0f, 1.0f, 2.95f, 2.95f, 2.92f, 4.0f, 4.0f, 4.0f, 0.23f, 1.0f, 0.07f, 0.03f, 0.08f, 1.0f, 0.06f, 0.03f, 0.12f, 1.0f, 1.0f, 2.9f, 2.85f, 2.74f, 3.85f, 3.85f, 3.78f, 0.24f, 1.0f, 0.1f, 0.03f, 0.07f, 1.0f, 0.1f, 0.03f, 0.16f, 1.0f, 1.0f, 2.8f, 2.74f, 2.62f, 3.65f, 3.65f, 3.55f, 0.25f, 1.0f, 0.12f, 0.04f, 0.08f, 1.0f, 0.12f, 0.04f, 0.18f, 1.0f, 1.0f, 2.7f, 2.7f, 2.7f, 3.8f, 3.8f, 3.8f, 0.22f, 1.0f, 0.0f, 0.0f, 0.0f, 1.0f, 0.0f, 0.0f, 0.0f, 1.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f };
static const float PC_PROC[160] = { 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 2.0f, 0.97f, 0.03f, 0.0f, 0.02f, 0.96f, 0.02f, 0.0f, 0.03f, 0.97f, 0.68f, 0.68f, 0.68f, -1.2f, -1.2f, -1.2f, 1.45f, 1.45f, 1.45f, 0.2f, 0.65f, 2.4f, 2.4f, 2.4f, 3.6f, 3.6f, 3.6f, 0.15f, 1.0f, 0.05f, 0.01f, 0.04f, 1.0f, 0.05f, 0.01f, 0.08f, 1.0f, 0.0f, 1.0f, 0.0f, 2.0f, 0.78f, 0.22f, 0.0f, 0.0f, 0.55f, 0.45f, 0.0f, 0.55f, 0.45f, 0.68f, 0.68f, 0.68f, -1.2f, -1.2f, -1.2f, 1.45f, 1.45f, 1.45f, 0.2f, 0.0f, 2.3f, 2.3f, 2.3f, 3.4f, 3.4f, 3.4f, 0.16f, 1.0f, 0.1f, 0.0f, 0.25f, 0.85f, 0.0f, 0.12f, 1.0f, 0.0f, 0.0f, 0.0f, 0.0f, 1.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f };
static const float PC_GAUGE[56] = { 1.0f, 1.0f, 0.0f, 1.0f, 0.0f, 1.0f, 0.0f, 3.0f, 1.55f, 2.4f, 2.8f, 0.45f, 1.6f, 1.33f, 2.6f, 1.45f, 1.9f, 2.4f, 0.38f, 1.5f, 1.36f, 1.8f, 1.25f, 1.1f, 1.6f, 0.2f, 1.25f, 1.33f, 1.6f, 1.18f, 0.9f, 1.5f, 0.16f, 1.2f, 1.66f, 1.0f, 1.0f, 0.35f, 1.0f, 0.06f, 1.0f, 1.85f, 0.6f, 0.72f, 0.0f, 0.7f, 0.03f, 0.85f, 2.2f, 0.45f, 0.55f, 0.0f, 0.55f, 0.02f, 0.75f, 1.43f };
static const float PC_ISO[10] = { 50.0f, 100.0f, 125.0f, 200.0f, 250.0f, 400.0f, 500.0f, 800.0f, 1600.0f, 3200.0f };
static const int PC_QUAL[3] = { 32, 64, 128 };
static const float PC_MTF[6] = { 0.0f, 1.6f, 1.1f, 0.7f, 1.5f, 2.3f };
static const float PC_FPS[9] = { 23.976024f, 24.0f, 25.0f, 29.97003f, 30.0f, 48.0f, 50.0f, 59.9400599f, 60.0f };
static const float PC_PROP[13] = { 0.0f, -1.0f, 1.33f, 1.37f, 1.43f, 1.66f, 1.78f, 1.85f, 1.9f, 2.0f, 2.2f, 2.39f, 2.76f };
#define PC_GRAIN_SOFT_K 0.577350269f
static const float PC_PX_MM[8] = { 77.1084337f, 393.684642f, 331.606218f, 187.134503f, 154.216867f, 77.1084337f, 36.4810944f, 27.2688539f };
static const float PC_MTF_LAYERS[6] = { 4.261f, 2.167f, 0.0f, 4.3253801f, 0.0f, 3.90045574f };
static const float PC_NG_AMP[3] = { 0.0141386093f, 0.0164063404f, 0.0292028231f };
static const float PC_HAL_PX[8] = { 1.0f, 5.1055977f, 4.30051813f, 2.42690058f, 2.0f, 1.0f, 0.473114193f, 0.353642948f };
#define PC_HAL_PHYS_K 0.18f
#define PC_HAL_PHYS_LIMIT 16.0f
#define PC_HAL_FISICA 1
#define PC_BREATH_SIGMA_D 0.015f
#define PC_BREATH_NEG_GAMMA 0.6f
#define PC_BREATH_SLOW 24.0f
#define PC_BREATH_SLOW_NORM 2.0098f
#define PC_PG_N 16
#define PC_PG_CAP 64u
static const float PC_PG_OFS[32] = { 0.188990176f, 0.0f, -0.24538444f, 0.224792257f, 0.0382217839f, -0.43551752f, 0.320640683f, 0.418219f, -0.600208461f, -0.106168419f, 0.580823123f, -0.369472116f, -0.198806569f, 0.739550531f, -0.388801187f, -0.74861306f, 0.867231369f, 0.316711515f, -0.930511117f, 0.38410145f, 0.464555442f, -0.992728055f, 0.357525259f, 1.13984692f, -1.13134563f, -0.65563792f, 1.41140139f, -0.310292631f, -0.938538969f, 1.33497512f, -0.253754199f, -1.95820367f };
#define PC_PG_REACH 2.97457662f
#define PC_PG_CELL 2.97457662f
#define PC_PG_DMAX 3.0f
#define PC_PG_AMP_MAX 0.95f
#define PC_PG_RK 0.759f
#define PC_PG_MEAN_K 6.48509191f
static const float PC_PG_KAPPA[3] = { 0.02564f, 0.02975f, 0.05393f };
#define PC_GRAO_FISICO 1
#define PC_COPIA_NENHUMA 0
#define PC_LAB_COPIA_NENHUMA 6

// ---------------------------------------------------------------- utilidades
static inline float pc_dot3(float3 a, float3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
static inline float3 pc_s3(float s) { return make_float3(s, s, s); }
static inline float pc_lerp(float a, float b, float t) { return a + (b - a) * t; }
static inline float3 pc_lerp3(float3 a, float3 b, float t) { return a + (b - a) * t; }
static inline float pc_smooth(float e0, float e1, float x) {
    float t = _saturatef((x - e0) / (e1 - e0));
    return t * t * (3.0f - 2.0f * t);
}
static inline float pc_mod(float x, float y) { return x - y * _floorf(x / y); }
static inline int pc_clampi(int i, int lo, int hi) { return i < lo ? lo : (i > hi ? hi : i); }
static inline float3 pc_mat3(float3 r0, float3 r1, float3 r2, float3 v) {
    return make_float3(pc_dot3(r0, v), pc_dot3(r1, v), pc_dot3(r2, v));
}
static inline float3 pc_max3(float3 a, float s) { return make_float3(_fmaxf(a.x, s), _fmaxf(a.y, s), _fmaxf(a.z, s)); }
static inline float3 pc_clamp3(float3 a, float lo, float hi) {
    return make_float3(_clampf(a.x, lo, hi), _clampf(a.y, lo, hi), _clampf(a.z, lo, hi));
}
static inline float pc_log10(float x) { return _logf(_fmaxf(x, 1e-10f)) * 0.4342944819f; }
static inline float pc_luma(float3 c) { return pc_dot3(c, make_float3(0.2126f, 0.7152f, 0.0722f)); }

// ---------------------------------------------------------------- curvas (mesmas do app)
static inline float pc_softclip(float u, float p) { return u / _powf(1.0f + _powf(_fabs(u), p), 1.0f / p); }
static inline float pc_softclip_inv(float v, float p) {
    float a = _fminf(_fabs(v), 0.99995f);
    float r = a / _powf(1.0f - _powf(a, p), 1.0f / p);
    return v < 0.0f ? -r : (v > 0.0f ? r : 0.0f);
}
static inline float pc_curve(float t, float slope, float mid, float black, float white, float ps, float pt) {
    if (t >= 0.0f) {
        float rw = _fmaxf(white - mid, 1e-4f);
        return mid + rw * pc_softclip(t * slope / rw, ps);
    }
    float rb = _fmaxf(mid - black, 1e-4f);
    return mid + rb * pc_softclip(t * slope / rb, pt);
}
static inline float pc_curve_inv(float y, float slope, float mid, float black, float white, float ps, float pt) {
    if (y >= mid) {
        float rw = _fmaxf(white - mid, 1e-4f);
        return pc_softclip_inv((y - mid) / rw, ps) * rw / slope;
    }
    float rb = _fmaxf(mid - black, 1e-4f);
    return pc_softclip_inv((y - mid) / rb, pt) * rb / slope;
}
static inline float3 pc_disp_to_stops(float3 y) {
    return make_float3(_clampf(pc_curve_inv(y.x, PC_DSLOPE, PC_DMID, 0.0f, 1.0f, PC_DP, PC_DP), -12.0f, 12.0f),
                       _clampf(pc_curve_inv(y.y, PC_DSLOPE, PC_DMID, 0.0f, 1.0f, PC_DP, PC_DP), -12.0f, 12.0f),
                       _clampf(pc_curve_inv(y.z, PC_DSLOPE, PC_DMID, 0.0f, 1.0f, PC_DP, PC_DP), -12.0f, 12.0f));
}
static inline float3 pc_stops_to_disp(float3 t) {
    return make_float3(pc_curve(t.x, PC_DSLOPE, PC_DMID, 0.0f, 1.0f, PC_DP, PC_DP),
                       pc_curve(t.y, PC_DSLOPE, PC_DMID, 0.0f, 1.0f, PC_DP, PC_DP),
                       pc_curve(t.z, PC_DSLOPE, PC_DMID, 0.0f, 1.0f, PC_DP, PC_DP));
}
static inline float3 pc_lin_to_stops(float3 l) {
    return make_float3(_clampf(_log2f(_fmaxf(l.x, 1e-7f) / 0.18f), -12.0f, 12.0f),
                       _clampf(_log2f(_fmaxf(l.y, 1e-7f) / 0.18f), -12.0f, 12.0f),
                       _clampf(_log2f(_fmaxf(l.z, 1e-7f) / 0.18f), -12.0f, 12.0f));
}
static inline float3 pc_stops_to_lin(float3 t) {
    return make_float3(0.18f * _exp2f(t.x), 0.18f * _exp2f(t.y), 0.18f * _exp2f(t.z));
}
static inline float3 pc_code_to_lin(float3 c) { return pc_stops_to_lin(pc_disp_to_stops(c)); }
static inline float3 pc_lin_to_code(float3 l) { return pc_stops_to_disp(pc_lin_to_stops(l)); }

// ---------------------------------------------------------------- perfis de camera
static inline float pc_nlog_dec(float y) {
    float c = y * 1023.0f;
    return (c < 452.0f) ? _powf(_fmaxf(c / 650.0f, 0.0f), 3.0f) - 0.0075f : _expf((c - 619.0f) / 150.0f);
}
static inline float pc_slog3_dec(float y) {
    float c = y * 1023.0f;
    return (c >= 171.2102946929f) ? _powf(10.0f, (c - 420.0f) / 261.5f) * 0.19f - 0.01f
                                  : (c - 95.0f) * 0.01125f / (171.2102946929f - 95.0f);
}
static inline float pc_logc3_dec(float t) {
    return (t > 0.149658f) ? (_powf(10.0f, (t - 0.385537f) / 0.247190f) - 0.052272f) / 5.555556f
                           : (t - 0.092809f) / 5.367655f;
}
static inline float pc_vlog_dec(float y) {
    return (y < 0.181f) ? (y - 0.125f) / 5.6f : _powf(10.0f, (y - 0.598206f) / 0.241514f) - 0.00873f;
}
static inline float pc_cineon_dec(float y) {
    return (_powf(10.0f, (y * 1023.0f - 685.0f) / 300.0f) - PC_CIN_BLACK) / (1.0f - PC_CIN_BLACK);
}
static inline float pc_di_dec(float y) {
    return (y <= 0.02740668f) ? y / 10.44426855f : _exp2f(y / 0.07329248f - 7.0f) - 0.0075f;
}
static inline float pc_l3g10_dec(float y) {
    return (y < 0.0f) ? y / 15.1927f - 0.01f : (_powf(10.0f, y / 0.224282f) - 1.0f) / 155.975327f - 0.01f;
}
// Blackmagic Film Gen 5: D*x + E abaixo do corte; A*ln(x + B) + C acima
static inline float pc_bmd5_dec(float y) {
    return (y < 0.13388378308667f) ? (y - 0.09246575342465753f) / 8.283605932402494f
                                   : _expf((y - 0.5300133392291939f) / 0.08692876065491224f) - 0.005494072432257808f;
}
// ARRI LogC4 (a, b, c, s, t da especificacao)
static inline float pc_logc4_dec(float e) {
    return (e >= 0.0f) ? (_exp2f(14.0f * (e - PC_C4C) / PC_C4B + 6.0f) - 64.0f) / PC_C4A : e * PC_C4S + PC_C4T;
}
// Apple Log
static inline float pc_apple_dec(float p) {
    if (p >= 0.20855531595464202f) return _exp2f((p - 0.69336945f) / 0.08550479f) - 0.00964052f;
    return (p >= 0.0f) ? _sqrtf(p / 47.28711236f) - 0.05641088f : -0.05641088f;
}
// HLG (ITU-R BT.2100): OETF inversa x HLG_K (cinza da BT.2408 em 38% -> 0,18), espelhada abaixo de 0
static inline float pc_hlg_dec(float e) {
    if (e <= 0.5f) return e * _fabs(e) / 3.0f * PC_HLG_K;
    return (_expf((e - PC_HLG_C) / PC_HLG_A) + PC_HLG_B) / 12.0f * PC_HLG_K;
}
// PQ (SMPTE ST 2084): luz da tela / 1000 cd/m2, depois a OOTF inversa do HLG (gama 1,2 pela luminancia)
static inline float pc_pq_disp(float e) {
    float p = _powf(_fmaxf(e, 0.0f), 1.0f / PC_PQ_M2);
    return 10.0f * _powf(_fmaxf(p - PC_PQ_C1, 0.0f) / _fmaxf(PC_PQ_C2 - PC_PQ_C3 * p, 1e-6f), 1.0f / PC_PQ_M1);
}
static inline float3 pc_pq_dec(float3 c) {
    float3 f = make_float3(pc_pq_disp(c.x), pc_pq_disp(c.y), pc_pq_disp(c.z));
    float y = _fmaxf(0.2627f * f.x + 0.6780f * f.y + 0.0593f * f.z, 1e-10f);
    return f * (_powf(y, -1.0f / 6.0f) * PC_HLG_K);
}
// Perfis da 1.6 (look.INPUT_IDS 14+; formulas e fontes em shaders.camDec)
static inline float pc_clog2_dec(float y) {
    float r = (y < 0.035388128f) ? -(_powf(10.0f, (0.035388128f - y) / 0.281863093f) - 1.0f) / 87.09937546f
                                 : (_powf(10.0f, (y - 0.035388128f) / 0.281863093f) - 1.0f) / 87.09937546f;
    return r * 0.9f;
}
static inline float pc_clog3_dec(float y) {
    float r = (_powf(10.0f, (y - 0.069886632f) / 0.42889912f) - 1.0f) / 14.98325f;
    if (y < 0.04076162f) r = -(_powf(10.0f, (0.07623209f - y) / 0.42889912f) - 1.0f) / 14.98325f;
    else if (y <= 0.105357102f) r = (y - 0.073059361f) / 2.3069815f;
    return r * 0.9f;
}
static inline float pc_flog_dec(float y) {
    return (y < 0.100537775223865f) ? (y - 0.092864f) / 8.735631f
                                    : _powf(10.0f, (y - 0.790453f) / 0.344676f) / 0.555556f - 0.009468f / 0.555556f;
}
static inline float pc_flog2_dec(float y) {
    return (y < 0.100686685370811f) ? (y - 0.092864f) / 8.799461f
                                    : _powf(10.0f, (y - 0.384316f) / 0.245281f) / 5.555556f - 0.064829f / 5.555556f;
}
static inline float pc_dlog_dec(float y) {
    return (y <= 0.14f) ? (y - 0.0929f) / 6.025f : (_powf(10.0f, 3.89616f * y - 2.27752f) - 0.0108f) / 0.9892f;
}
static inline float pc_slog2_dec(float y) {
    float r = (y >= 0.030001222851889303f) ? _powf(10.0f, (y - 0.646596f) / 0.432699f) - 0.037584f
                                           : (y - 0.030001222851889303f) / 5.0f;
    return r * 0.9f * 219.0f / 155.0f;
}
static inline float pc_llog_dec(float y) {
    return (y <= 0.138f) ? (y - 0.09f) / 8.0f : (_powf(10.0f, (y - 0.6f) / 0.27f) - 0.0115f) / 1.3f;
}
static inline float3 pc_cam_dec(float3 c, int id) {
    if (id == 14) return make_float3(pc_clog2_dec(c.x), pc_clog2_dec(c.y), pc_clog2_dec(c.z));
    if (id == 15) return make_float3(pc_clog3_dec(c.x), pc_clog3_dec(c.y), pc_clog3_dec(c.z));
    if (id == 16) return make_float3(pc_flog_dec(c.x), pc_flog_dec(c.y), pc_flog_dec(c.z));
    if (id == 17 || id == 18) return make_float3(pc_flog2_dec(c.x), pc_flog2_dec(c.y), pc_flog2_dec(c.z));
    if (id == 19) return make_float3(pc_dlog_dec(c.x), pc_dlog_dec(c.y), pc_dlog_dec(c.z));
    if (id == 20) return make_float3(pc_slog2_dec(c.x), pc_slog2_dec(c.y), pc_slog2_dec(c.z));
    return make_float3(pc_llog_dec(c.x), pc_llog_dec(c.y), pc_llog_dec(c.z));
}
// ARRI LogC3 com outro EI (tabela PC_LC3: corte, b, c, d, e, f por EI; a = 5,555556)
static inline float pc_logc3e_dec(float t, int ei) {
    float cut = PC_LC3[ei * 6 + 0];
    float e = PC_LC3[ei * 6 + 4];
    float f = PC_LC3[ei * 6 + 5];
    return (t > e * cut + f) ? (_powf(10.0f, (t - PC_LC3[ei * 6 + 3]) / PC_LC3[ei * 6 + 2]) - PC_LC3[ei * 6 + 1])
                               / 5.555556f
                             : (t - f) / e;
}
// cv = 1: a curva e escrita no codigo de 10 bits (codigo/1023) e o clipe chegou em faixa legal expandida
// (v = (codigo - 64)/876): volta ao codigo antes da formula (look.INPUT_DOMAIN).
static inline float3 pc_to_linear(float3 c, int id, int cv) {
    if (cv == 1) c = make_float3((c.x * 876.0f + 64.0f) / 1023.0f, (c.y * 876.0f + 64.0f) / 1023.0f,
                                 (c.z * 876.0f + 64.0f) / 1023.0f);
    if (id == 0) return pc_code_to_lin(c);
    if (id == 1) return c;
    if (id == 2) return make_float3(pc_nlog_dec(c.x), pc_nlog_dec(c.y), pc_nlog_dec(c.z));
    if (id == 3) return make_float3(pc_slog3_dec(c.x), pc_slog3_dec(c.y), pc_slog3_dec(c.z));
    if (id == 4) return make_float3(pc_logc3_dec(c.x), pc_logc3_dec(c.y), pc_logc3_dec(c.z));
    if (id == 5) return make_float3(pc_vlog_dec(c.x), pc_vlog_dec(c.y), pc_vlog_dec(c.z));
    if (id == 7) return make_float3(pc_di_dec(c.x), pc_di_dec(c.y), pc_di_dec(c.z));
    if (id == 8) return make_float3(pc_l3g10_dec(c.x), pc_l3g10_dec(c.y), pc_l3g10_dec(c.z));
    if (id == 9) return make_float3(pc_bmd5_dec(c.x), pc_bmd5_dec(c.y), pc_bmd5_dec(c.z));
    if (id == 10) return make_float3(pc_logc4_dec(c.x), pc_logc4_dec(c.y), pc_logc4_dec(c.z));
    if (id == 11) return make_float3(pc_apple_dec(c.x), pc_apple_dec(c.y), pc_apple_dec(c.z));
    if (id == 12) return make_float3(pc_hlg_dec(c.x), pc_hlg_dec(c.y), pc_hlg_dec(c.z));
    if (id == 13) return pc_pq_dec(c);
    if (id >= 14) return pc_cam_dec(c, id);
    return make_float3(pc_cineon_dec(c.x), pc_cineon_dec(c.y), pc_cineon_dec(c.z));
}
// Proteger cores saturadas (1.6; shaders.gamutCompress, ACES Reference Gamut Compression): limites em PC_GCL
static inline float pc_gc_compress(float d, float lim, float thr) {
    if (d < thr) return d;
    float s = (lim - thr) / _powf(_powf((1.0f - thr) / (lim - thr), -PC_GC_PWR) - 1.0f, 1.0f / PC_GC_PWR);
    float nd = (d - thr) / s;
    return thr + (d - thr) / _powf(1.0f + _powf(nd, PC_GC_PWR), 1.0f / PC_GC_PWR);
}
static inline float3 pc_gamut_compress(float3 c, float3 lim) {
    float a = _fmaxf(c.x, _fmaxf(c.y, c.z));
    if (a == 0.0f) return c;
    float aa = _fabs(a);
    return make_float3(a - pc_gc_compress((a - c.x) / aa, lim.x, PC_GC_THR_R) * aa,
                       a - pc_gc_compress((a - c.y) / aa, lim.y, PC_GC_THR_G) * aa,
                       a - pc_gc_compress((a - c.z) / aa, lim.z, PC_GC_THR_B) * aa);
}

// ---------------------------------------------------------------- look de pelicula
static inline float pc_hue_ang(float3 c) {
    float Y = pc_luma(c);
    return _atan2f((c.x - Y) / 1.5748f, (c.z - Y) / 1.8556f);
}
static inline float pc_hue_w(float h, float h0) {
    float d = _fabs(pc_mod(h - h0 + 3.14159265f, 6.2831853f) - 3.14159265f);
    return pc_smooth(0.8f, 0.0f, d);
}
static inline float3 pc_hue_adjust(float3 c, float rg, float rb, float skin, float skin_rot, float skin_lum) {
    if (rg == 0.0f && rb == 0.0f && skin == 0.0f && skin_rot == 0.0f && skin_lum == 0.0f) return c;
    float Y = pc_luma(c);
    float cx = (c.z - Y) / 1.8556f;
    float cy = (c.x - Y) / 1.5748f;
    if (_sqrtf(cx * cx + cy * cy) < 1e-5f) return c;
    float h = _atan2f(cy, cx);
    float wg = pc_hue_w(h, pc_hue_ang(make_float3(0.25f, 0.6f, 0.2f)));
    float wb = pc_hue_w(h, pc_hue_ang(make_float3(0.2f, 0.35f, 0.8f)));
    float ws = pc_hue_w(h, pc_hue_ang(make_float3(0.8f, 0.55f, 0.45f)));
    float rot = rg * wg + rb * wb + skin_rot * ws;
    float cs = _cosf(rot);
    float sn = _sinf(rot);
    float nx = cs * cx - sn * cy;
    float ny = sn * cx + cs * cy;
    float k = _fmaxf(0.0f, 1.0f + skin * ws);
    nx = nx * k;
    ny = ny * k;
    Y = Y * (1.0f + PC_SKIN_LUM * skin_lum * ws);
    float r = Y + 1.5748f * ny;
    float b = Y + 1.8556f * nx;
    float g = (Y - 0.2126f * r - 0.0722f * b) / 0.7152f;
    return make_float3(r, g, b);
}
static inline float3 pc_hsv_tint(float hue_deg, float amount) {
    float h = pc_mod(hue_deg, 360.0f) / 60.0f;
    float x = 1.0f - _fabs(pc_mod(h, 2.0f) - 1.0f);
    int sector = pc_clampi(PC_I(_floorf(h)), 0, 5);
    float3 c = make_float3(1.0f, x, 0.0f);
    if (sector == 1) c = make_float3(x, 1.0f, 0.0f);
    if (sector == 2) c = make_float3(0.0f, 1.0f, x);
    if (sector == 3) c = make_float3(0.0f, x, 1.0f);
    if (sector == 4) c = make_float3(x, 0.0f, 1.0f);
    if (sector == 5) c = make_float3(1.0f, 0.0f, x);
    float l = pc_luma(c);
    return (c - pc_s3(l)) * (amount * 0.09f);
}
static inline float pc_soft_p(float v) { return 4.0f + (1.15f - 4.0f) * v; }
static inline float3 pc_film_look(float3 lin, int bw, float3 bww, float sat, float3 chg, float3 cho, float slope, float mid,
                              float black, float white, float ps, float pt, float dens, float rg, float rb, float skin,
                              float skin_rot, float skin_lum, float3 sh_tint, float3 hi_tint, float bal,
                              float tone_amt, float3 tone_sh, float3 tone_hi) {
    float3 l2 = lin;
    if (bw == 1) l2 = pc_s3(pc_dot3(lin, bww));
    float3 t = pc_clamp3(pc_lin_to_stops(l2), -10.0f, 9.0f);
    float ta = pc_luma(t);
    t = pc_s3(ta) + (t - pc_s3(ta)) * sat;
    t = t * chg + cho;
    float3 y = make_float3(pc_curve(t.x, slope, mid, black, white, ps, pt),
                           pc_curve(t.y, slope, mid, black, white, ps, pt),
                           pc_curve(t.z, slope, mid, black, white, ps, pt));
    float mx = _fmaxf(y.x, _fmaxf(y.y, y.z));
    float mn = _fminf(y.x, _fminf(y.y, y.z));
    y = y * (1.0f - dens * 0.45f * (mx - mn));
    y = pc_hue_adjust(y, rg, rb, skin, skin_rot, skin_lum);
    float lum = pc_luma(y);
    float piv = _clampf(0.45f + 0.3f * bal, 0.1f, 0.9f);
    float ws = 1.0f - pc_smooth(0.0f, piv, lum);
    float wh = pc_smooth(piv, 1.0f, lum);
    y = y + sh_tint * ws + hi_tint * wh;
    if (bw == 1 && tone_amt > 0.0f) {
        float L = _clampf(pc_luma(y), 0.0f, 1.0f);
        float3 toned = pc_lerp3(tone_sh, tone_hi, pc_smooth(0.0f, 1.0f, L)) * L;
        y = pc_lerp3(y, toned, tone_amt);
    }
    return y;
}
static inline float3 pc_print_stage(float3 y, float sat, float3 gam, float3 off, float slope, float mid, float black,
                                float white, float ps, float pt) {
    float3 t = pc_disp_to_stops(y);
    float ta = pc_luma(t);
    t = pc_s3(ta) + (t - pc_s3(ta)) * sat;
    t = t * gam + off;
    return make_float3(pc_curve(t.x, slope, mid, black, white, ps, pt),
                       pc_curve(t.y, slope, mid, black, white, ps, pt),
                       pc_curve(t.z, slope, mid, black, white, ps, pt));
}
static inline float3 pc_aged(float3 y) {
    float L = pc_luma(y);
    float3 c = pc_lerp3(pc_s3(L), y, 0.6f);
    c = c * 0.82f + pc_s3(0.075f);
    return c * make_float3(1.07f, 0.93f, 0.98f);
}

// ---------------------------------------------------------------- ruido deterministico (mesmo do app)
static inline uint pc_pcg(uint v) {
    uint state = v * 747796405u + 2891336453u;
    uint word = ((state >> ((state >> 28u) + 4u)) ^ state) * 277803737u;
    return (word >> 22u) ^ word;
}
static inline float pc_rnd(uint a, uint b, uint c) {
    return PC_F(pc_pcg(a + pc_pcg(b + pc_pcg(c)))) * (1.0f / 4294967296.0f);
}
// _hash() e _vnoise() de look.py (tremor, cintilacao e eventos dos defeitos)
static inline float pc_hash(int i, int s) {
    uint x = PC_U(i) * 0x9E3779B1u + PC_U(s) * 0x85EBCA77u + 0x165667B1u;
    x = x ^ (x >> 15u);
    x = x * 0x2C1B3C6Du;
    x = x ^ (x >> 12u);
    x = x * 0x297A2D39u;
    x = x ^ (x >> 15u);
    return PC_F(x) / 4294967295.0f;
}
static inline float pc_vnoise(float x, int s) {
    float fi = _floorf(x);
    float f = x - fi;
    float u = f * f * (3.0f - 2.0f * f);
    int i = PC_I(fi);
    return (pc_hash(i, s) * (1.0f - u) + pc_hash(i + 1, s) * u) * 2.0f - 1.0f;
}
static inline float pc_vnoise2(float x, float y) {
    float ix = _floorf(x);
    float iy = _floorf(y);
    float fx = x - ix;
    float fy = y - iy;
    float ux = fx * fx * (3.0f - 2.0f * fx);
    float uy = fy * fy * (3.0f - 2.0f * fy);
    uint bx = PC_U(PC_I(ix) + 65536);
    uint by = PC_U(PC_I(iy) + 65536);
    float a = pc_rnd(bx, by, 911u);
    float c = pc_rnd(bx + 1u, by, 911u);
    float d = pc_rnd(bx, by + 1u, 911u);
    float e = pc_rnd(bx + 1u, by + 1u, 911u);
    return pc_lerp(pc_lerp(a, c, ux), pc_lerp(d, e, ux), uy);
}
static inline float pc_fbm2(float x, float y) {
    float v = 0.0f;
    float a = 0.5f;
    for (int i = 0; i < 4; i++) {
        v = v + a * pc_vnoise2(x, y);
        x = x * 2.03f + 17.0f;
        y = y * 2.03f + 17.0f;
        a = a * 0.5f;
    }
    return v / 0.9375f;
}

// ---------------------------------------------------------------- grao fisico (modelo booleano no negativo)
static inline uint pc_pg_bits(uint m) {
    m = m - ((m >> 1u) & 0x55555555u);
    m = (m & 0x33333333u) + ((m >> 2u) & 0x33333333u);
    m = (m + (m >> 4u)) & 0x0F0F0F0Fu;
    return (m * 0x01010101u) >> 24u;
}
static inline uint pc_pg_hits(float dx, float dy) {
    uint m = 0u;
    for (int k = 0; k < PC_PG_N; k++) {
        float ex = dx - PC_PG_OFS[2 * k];
        float ey = dy - PC_PG_OFS[2 * k + 1];
        if (ex * ex + ey * ey < 1.0f) m = m | (1u << PC_U(k));
    }
    return m;
}
// cobertura de cada camada vista pelo spot do pixel em (px, py) px@1080; raio r, fracao propria chroma, semente
static inline float3 pc_pg_coverage(float3 D, float px, float py, float r, float chroma, uint seed) {
    float mr_ = _clampf(D.x, 0.0f, PC_PG_DMAX) * PC_PG_MEAN_K;
    float mg_ = _clampf(D.y, 0.0f, PC_PG_DMAX) * PC_PG_MEAN_K;
    float mb_ = _clampf(D.z, 0.0f, PC_PG_DMAX) * PC_PG_MEAN_K;
    float sr = mr_ * (1.0f - chroma);
    float sg = mg_ * (1.0f - chroma);
    float sb = mb_ * (1.0f - chroma);
    float smax = _fmaxf(sr, _fmaxf(sg, sb));
    float qx = px / r;
    float qy = py / r;
    int c0x = PC_I(_floorf((qx - PC_PG_REACH) / PC_PG_CELL));
    int c0y = PC_I(_floorf((qy - PC_PG_REACH) / PC_PG_CELL));
    int c1x = PC_I(_floorf((qx + PC_PG_REACH) / PC_PG_CELL));
    int c1y = PC_I(_floorf((qy + PC_PG_REACH) / PC_PG_CELL));
    float rr = PC_PG_REACH * PC_PG_REACH;
    uint mr = 0u;
    uint mg = 0u;
    uint mb = 0u;
    for (int cy = c0y; cy <= c1y; cy++) {
        for (int cx = c0x; cx <= c1x; cx++) {
            float lox = PC_F(cx) * PC_PG_CELL;
            float loy = PC_F(cy) * PC_PG_CELL;
            float nx = _clampf(qx, lox, lox + PC_PG_CELL) - qx;
            float ny = _clampf(qy, loy, loy + PC_PG_CELL) - qy;
            if (nx * nx + ny * ny >= rr) continue;
            uint bx = PC_U(cx + 65536);
            uint by = PC_U(cy + 65536);
            for (int proc = 0; proc < 4; proc++) {
                float lim = (proc == 0) ? smax : ((proc == 1) ? mr_ * chroma : ((proc == 2) ? mg_ * chroma : mb_ * chroma));
                if (lim <= 0.0f) continue;
                uint base = pc_pcg(bx + pc_pcg(by + pc_pcg(seed * 4u + PC_U(proc))));
                float t = 0.0f;
                for (uint i = 0u; i < PC_PG_CAP; i++) {
                    uint h = pc_pcg(base + i);
                    uint h2 = pc_pcg(h ^ 0x9E3779B9u);
                    t = t - _logf((PC_F(h2 >> 8u) + 0.5f) * (1.0f / 16777216.0f));
                    if (t >= lim) break;
                    float ccx = (PC_F(cx) + (PC_F(h & 0xFFFFu) + 0.5f) * (1.0f / 65536.0f)) * PC_PG_CELL;
                    float ccy = (PC_F(cy) + (PC_F(h >> 16u) + 0.5f) * (1.0f / 65536.0f)) * PC_PG_CELL;
                    float dx = ccx - qx;
                    float dy = ccy - qy;
                    if (dx * dx + dy * dy >= rr) continue;
                    uint hm = pc_pg_hits(dx, dy);
                    if (proc == 0) {
                        if (t < sr) mr = mr | hm;
                        if (t < sg) mg = mg | hm;
                        if (t < sb) mb = mb | hm;
                    } else if (proc == 1) {
                        mr = mr | hm;
                    } else if (proc == 2) {
                        mg = mg | hm;
                    } else {
                        mb = mb | hm;
                    }
                }
            }
        }
    }
    float inv = 1.0f / PC_F(PC_PG_N);
    return make_float3(PC_F(pc_pg_bits(mr)) * inv, PC_F(pc_pg_bits(mg)) * inv, PC_F(pc_pg_bits(mb)) * inv);
}
// desvio da densidade de cada camada: T' = (1 - a) T + a T^, dD = -log10(T'/T); gq = (x, y, raio, fracao propria)
static inline float3 pc_pg_grain(float3 D, float4 gq, float3 ga, int gs) {
    float3 cov = pc_pg_coverage(D, gq.x, gq.y, gq.z, gq.w, PC_U(gs));
    float tr = _exp2f(_clampf(D.x, 0.0f, PC_PG_DMAX) * -3.321928095f);
    float tg = _exp2f(_clampf(D.y, 0.0f, PC_PG_DMAX) * -3.321928095f);
    float tb = _exp2f(_clampf(D.z, 0.0f, PC_PG_DMAX) * -3.321928095f);
    float ar = _fminf(ga.x, PC_PG_AMP_MAX);
    float ag = _fminf(ga.y, PC_PG_AMP_MAX);
    float ab = _fminf(ga.z, PC_PG_AMP_MAX);
    return make_float3(_log2f(1.0f + ar * ((1.0f - cov.x) - tr) / tr) * -0.301029996f,
                       _log2f(1.0f + ag * ((1.0f - cov.y) - tg) / tg) * -0.301029996f,
                       _log2f(1.0f + ab * ((1.0f - cov.z) - tb) / tb) * -0.301029996f);
}

// ---------------------------------------------------------------- laboratorio (look.LabPath)
static inline float pc_softplus(float z) { return _fmaxf(z, 0.0f) + _logf(1.0f + _expf(-_fabs(z))); }
static inline float3 pc_lab_curve(float3 x, float3 g, float3 xt, float3 xs, float w) {
    return make_float3(g.x * w * (pc_softplus((x.x - xt.x) / w) - pc_softplus((x.x - xs.x) / w)),
                       g.y * w * (pc_softplus((x.y - xt.y) / w) - pc_softplus((x.y - xs.y) / w)),
                       g.z * w * (pc_softplus((x.z - xt.z) / w) - pc_softplus((x.z - xs.z) / w)));
}
// os tres canais se aproximam da media deles (curvas neutras)
static inline float3 pc_neutral3(float3 v, float t) {
    float m = (v.x + v.y + v.z) / 3.0f;
    return v + (pc_s3(m) - v) * t;
}
// produto de matrizes a*I + b*J: devolve o novo b (o novo a e a1*a2)
static inline float pc_aij_b(float a1, float b1, float a2, float b2) { return a1 * b2 + b1 * a2 + 3.0f * b1 * b2; }
// densidade do negativo: dn' = A*dn + B*(soma). Efeito entre camadas k, saturacao do filme fs e prata
// retida no negativo bn: mais contraste neutro e menos cor dos corantes (look.ii_coefs)
static inline float2 pc_ii_coefs(float k, float fs, float bn) {
    float a = 1.0f + k;
    float b = -k / 3.0f;
    float nb = pc_aij_b(fs, (1.0f - fs) / 3.0f, a, b);
    a = fs * a;
    b = nb;
    float c = PC_BYP_C * bn;
    float d = PC_BYP_D * bn;
    b = pc_aij_b(1.0f - d, (c + d) / 3.0f, a, b);
    a = (1.0f - d) * a;
    return make_float2(a, b);
}
// cor pura de um matiz (setor HSV, igual a look._hue_rgb)
static inline float3 pc_hue_rgb(float hue_deg) {
    float h = pc_mod(hue_deg, 360.0f) / 60.0f;
    float x = 1.0f - _fabs(pc_mod(h, 2.0f) - 1.0f);
    int sector = pc_clampi(PC_I(_floorf(h)), 0, 5);
    float3 c = make_float3(1.0f, x, 0.0f);
    if (sector == 1) c = make_float3(x, 1.0f, 0.0f);
    if (sector == 2) c = make_float3(0.0f, 1.0f, x);
    if (sector == 3) c = make_float3(0.0f, x, 1.0f);
    if (sector == 4) c = make_float3(x, 0.0f, 1.0f);
    if (sector == 5) c = make_float3(1.0f, 0.0f, x);
    return c;
}
// uma linha da matriz da densidade: separacao de cores (Hue Split) S vezes (A*I + B*J) = A*S_i + B
static inline float3 pc_ii_row(float3 e, float ui, float vi, float3 u, float3 v, float sa, float sb, float ia, float ib,
                           int on) {
    float3 s = e;
    if (on == 1) s = pc_s3(1.0f / 3.0f) + u * ((1.0f + sa) * ui) + v * ((1.0f - sb) * vi);
    return s * ia + pc_s3(ib);
}
// inversa da curva da copia (pe 0): log da exposicao que da a densidade D
static inline float pc_lab_inv(float D, float g, float s, float w) {
    float q = _expf(D / (g * w));
    float k = _expf(-s / w);
    float a = (q - 1.0f) / _fmaxf(1.0f - q * k, 1e-12f);
    return w * _logf(_fmaxf(a, 1e-30f));
}
static inline float pc_det3(float3 a, float3 b, float3 c) {
    return a.x * (b.y * c.z - b.z * c.y) - a.y * (b.x * c.z - b.z * c.x) + a.z * (b.x * c.y - b.y * c.x);
}
static inline float3 pc_lab_path(float3 lin, float3 s0, float3 s1, float3 s2, float3 ng0, float3 nt0, float3 ns,
                             float nw, float3 i0, float3 i1, float3 i2, int has_print, float3 pg, float3 dmax,
                             float pw, float3 d0, float3 d1, float3 d2, float3 key, float push, float xtalk,
                             float3 lights, float3 gn, float3 ga, float4 gq, int gs) {
    float3 ng = ng0 * (1.0f + 0.12f * push);
    float3 nt = nt0 + pc_s3(0.08f * push);
    float3 dmid = pc_mat3(i0, i1, i2, pc_lab_curve(pc_s3(0.0f), ng, nt, ns, nw));
    float3 e = pc_max3(pc_mat3(s0, s1, s2, lin), 1e-7f);
    float3 le = make_float3(pc_log10(e.x / 0.18f), pc_log10(e.y / 0.18f), pc_log10(e.z / 0.18f));
    float3 dn = pc_mat3(i0, i1, i2, pc_lab_curve(le, ng, nt, ns, nw));
    dn = dn + gn;  // 1.6: grao no negativo (grao.negative_grain); zero sem ele
    if (ga.x + ga.y + ga.z > 0.0f) dn = dn + pc_pg_grain(dn, gq, ga, gs);  // 1.6: grao fisico
    if (has_print == 0) {
        // sem copia: inversao digital com o gama nominal do negativo
        float3 st = make_float3((dn.x - dmid.x) / (ng0.x * 0.30103f) - lights.x / 0.30103f,
                                (dn.y - dmid.y) / (ng0.y * 0.30103f) - lights.y / 0.30103f,
                                (dn.z - dmid.z) / (ng0.z * 0.30103f) - lights.z / 0.30103f);
        return pc_stops_to_disp(pc_clamp3(st, -12.0f, 12.0f));
    }
    // diafonia escolhida; colunas sem camada (Technicolor 2 cores) ficam zeradas
    float u0 = (_fabs(d0.x) + _fabs(d1.x) + _fabs(d2.x) > 0.0f) ? 1.0f : 0.0f;
    float u1 = (_fabs(d0.y) + _fabs(d1.y) + _fabs(d2.y) > 0.0f) ? 1.0f : 0.0f;
    float u2 = (_fabs(d0.z) + _fabs(d1.z) + _fabs(d2.z) > 0.0f) ? 1.0f : 0.0f;
    float3 r0 = make_float3((1.0f + xtalk * (d0.x - 1.0f)) * u0, xtalk * d0.y * u1, xtalk * d0.z * u2);
    float3 r1 = make_float3(xtalk * d1.x * u0, (1.0f + xtalk * (d1.y - 1.0f)) * u1, xtalk * d1.z * u2);
    float3 r2 = make_float3(xtalk * d2.x * u0, xtalk * d2.y * u1, (1.0f + xtalk * (d2.z - 1.0f)) * u2);
    // M = diafonia + chave (a chave soma a mesma densidade nos tres canais)
    float3 m0 = r0 + key;
    float3 m1 = r1 + key;
    float3 m2 = r2 + key;
    float T = PC_LAB_TARGET;
    float3 dl = pc_s3(T);
    float c2 = _fabs(m0.z) + _fabs(m1.z) + _fabs(m2.z);
    if (c2 > 1e-9f) {
        float det = pc_det3(m0, m1, m2);
        dl = make_float3(pc_det3(make_float3(T, m0.y, m0.z), make_float3(T, m1.y, m1.z), make_float3(T, m2.y, m2.z)),
                         pc_det3(make_float3(m0.x, T, m0.z), make_float3(m1.x, T, m1.z), make_float3(m2.x, T, m2.z)),
                         pc_det3(make_float3(m0.x, m0.y, T), make_float3(m1.x, m1.y, T), make_float3(m2.x, m2.y, T)))
             * (1.0f / det);
    } else {
        // so duas camadas: minimos quadrados nas colunas 0 e 1
        float3 ca = make_float3(m0.x, m1.x, m2.x);
        float3 cb = make_float3(m0.y, m1.y, m2.y);
        float aa = pc_dot3(ca, ca);
        float ab = pc_dot3(ca, cb);
        float bb = pc_dot3(cb, cb);
        float at = (ca.x + ca.y + ca.z) * T;
        float bt = (cb.x + cb.y + cb.z) * T;
        float det = aa * bb - ab * ab;
        dl = make_float3((at * bb - ab * bt) / det, (aa * bt - ab * at) / det, 0.0f);
    }
    float3 ps = make_float3(dmax.x / pg.x, dmax.y / pg.y, dmax.z / pg.z);
    float off_z = (c2 > 1e-9f) ? pc_lab_inv(dl.z, pg.z, ps.z, pw) + dmid.z : dmid.z + 0.35f;
    float3 off = make_float3(pc_lab_inv(dl.x, pg.x, ps.x, pw) + dmid.x, pc_lab_inv(dl.y, pg.y, ps.y, pw) + dmid.y,
                             off_z);
    off = off + lights;
    float3 dd = pc_lab_curve(off - dn, pg, pc_s3(0.0f), ps, pw);
    float3 d = pc_mat3(r0, r1, r2, dd) + pc_s3(pc_dot3(key, dd));
    float kv = 3.32192809f / PC_LAB_VIEW;
    return make_float3(_exp2f(-d.x * kv), _exp2f(-d.y * kv), _exp2f(-d.z * kv));
}
// depois da copia (look.LabPost): rolagens, saturacao final, densidade por cor e pele
static inline float3 pc_lab_post(float3 y, float hi, float lo, float sat, float3 dens, float srot, float ssat) {
    if (hi > 0.0f || lo > 0.0f) {
        float3 t = pc_disp_to_stops(y);
        float ph = pc_soft_p(hi);
        float pl = pc_soft_p(lo);
        y = make_float3(pc_curve(t.x, PC_DSLOPE, PC_DMID, 0.0f, 1.0f, ph, pl),
                        pc_curve(t.y, PC_DSLOPE, PC_DMID, 0.0f, 1.0f, ph, pl),
                        pc_curve(t.z, PC_DSLOPE, PC_DMID, 0.0f, 1.0f, ph, pl));
    }
    if (sat != 1.0f) {
        float L = pc_luma(y);
        y = pc_s3(L) + (y - pc_s3(L)) * sat;
    }
    if (dens.x != 0.0f || dens.y != 0.0f || dens.z != 0.0f) {
        float wr = _fmaxf(0.0f, y.x - _fmaxf(y.y, y.z));
        float wg = _fmaxf(0.0f, y.y - _fmaxf(y.x, y.z));
        float wb = _fmaxf(0.0f, y.z - _fmaxf(y.x, y.y));
        y = y * _clampf(1.0f - PC_LAB_DENS_K * (dens.x * wr + dens.y * wg + dens.z * wb), 0.2f, 2.0f);
    }
    if (srot != 0.0f || ssat != 0.0f) y = pc_hue_adjust(y, 0.0f, 0.0f, ssat, srot, 0.0f);
    return y;
}

// ---------------------------------------------------------------- curva sobreposta
static inline float3 pc_curve_overlay(float3 img, float3 cy, int py, int ph) {
    float H = PC_F(ph);
    float fy = (PC_F(py) + 0.5f) / H;
    float th = 1.2f * H / 1080.0f + 0.8f;
    float3 o = img;
    float dm = _fabs(fy - (1.0f - PC_DMID)) * H;
    o = pc_lerp3(o, pc_s3(0.5f), 0.35f * _clampf(1.0f - dm, 0.0f, 1.0f));
    float dr = _fabs(fy - (1.0f - cy.x)) * H;
    float dg = _fabs(fy - (1.0f - cy.y)) * H;
    float db = _fabs(fy - (1.0f - cy.z)) * H;
    o = pc_lerp3(o, make_float3(1.0f, 0.25f, 0.2f), 0.9f * _clampf(th - dr + 1.0f, 0.0f, 1.0f));
    o = pc_lerp3(o, make_float3(0.3f, 1.0f, 0.35f), 0.9f * _clampf(th - dg + 1.0f, 0.0f, 1.0f));
    o = pc_lerp3(o, make_float3(0.35f, 0.55f, 1.0f), 0.9f * _clampf(th - db + 1.0f, 0.0f, 1.0f));
    return o;
}

// ---------------------------------------------------------------- lente, vinheta, brilho e grao
static inline float2 pc_lens(float u, float v, float W, float H, float dist, float k) {
    float qx = (u - 0.5f) * W / (0.5f * H);
    float qy = (v - 0.5f) * H / (0.5f * H);
    float rc2 = (W * W) / (H * H) + 1.0f;
    float f = (1.0f + dist * (qx * qx + qy * qy)) / (1.0f + _fmaxf(dist, 0.0f) * rc2) * k;
    return make_float2(qx * f * (0.5f * H) / W + 0.5f, qy * f * (0.5f * H) / H + 0.5f);
}
static inline float pc_vignette(float u, float v, float W, float H, float amt, float rad, float soft, float rnd) {
    float px = (u - 0.5f) * 2.0f;
    float py = (v - 0.5f) * 2.0f;
    float ax = pc_lerp(1.0f, W / H, rnd);
    px = px * ax;
    float d = _sqrtf(px * px + py * py) / _sqrtf(ax * ax + 1.0f);
    float t = pc_smooth(rad - soft * 0.5f, rad + soft * 0.5f, d);
    return _exp2f(-amt * 2.0f * t);
}
// ruido de gradiente intercalado: gira a espiral de amostras de pixel a pixel sem formar manchas
static inline float pc_ign(float x, float y) {
    float a = 0.06711056f * x + 0.00583715f * y;
    float b = 52.9829189f * (a - _floorf(a));
    return b - _floorf(b);
}
static inline float3 pc_extract(float3 lin, float thr, float limit, int lum_only) {
    float l = pc_luma(lin);
    float k = (thr > 0.0f) ? pc_smooth(thr * 0.5f, thr * 1.5f, l) : 1.0f;
    float3 e = lin * k;
    e = make_float3(e.x / (1.0f + e.x / limit), e.y / (1.0f + e.y / limit), e.z / (1.0f + e.z / limit));
    if (lum_only == 1) e = pc_s3(pc_luma(e));
    return e;
}
static inline float4 pc_gauss4(uint qx, uint qy, uint s) {
    float a1 = _fmaxf(pc_rnd(qx, qy, s), 1e-7f);
    float a2 = pc_rnd(qx, qy, s + 1u);
    float b1 = _fmaxf(pc_rnd(qx, qy, s + 2u), 1e-7f);
    float b2 = pc_rnd(qx, qy, s + 3u);
    float ra = _sqrtf(-2.0f * _logf(a1));
    float rb = _sqrtf(-2.0f * _logf(b1));
    return make_float4(ra * _cosf(6.2831853f * a2), ra * _sinf(6.2831853f * a2),
                       rb * _cosf(6.2831853f * b2), rb * _sinf(6.2831853f * b2));
}
static inline float pc_cubw(float v, int k) {
    float n1 = 1.0f - v;
    float n2 = 2.0f - v;
    float n3 = 3.0f - v;
    float sx = n1 * n1 * n1;
    float sy = n2 * n2 * n2;
    float sz = n3 * n3 * n3;
    float x = sx;
    float y = sy - 4.0f * sx;
    float z = sz - 4.0f * sy + 6.0f * sx;
    float w = 6.0f - x - y - z;
    float r = (k == 0) ? x : ((k == 1) ? y : ((k == 2) ? z : w));
    return r * (1.0f / 6.0f);
}
// B-spline cubica sobre a grade do ruido (o texBicubic do app, sem a filtragem do hardware)
static inline float4 pc_noise(float u, float v, int gw, int gh, uint s) {
    float x = u * PC_F(gw) - 0.5f;
    float y = v * PC_F(gh) - 0.5f;
    float ix = _floorf(x);
    float iy = _floorf(y);
    float fx = x - ix;
    float fy = y - iy;
    float4 acc = make_float4(0.0f, 0.0f, 0.0f, 0.0f);
    for (int b = 0; b < 4; b++) {
        float wy = pc_cubw(fy, b);
        int ty = pc_clampi(PC_I(iy) - 1 + b, 0, gh - 1);
        for (int a = 0; a < 4; a++) {
            float wx = pc_cubw(fx, a);
            int tx = pc_clampi(PC_I(ix) - 1 + a, 0, gw - 1);
            acc = acc + pc_gauss4(PC_U(tx), PC_U(ty), s) * (wx * wy);
        }
    }
    return acc;
}
static inline float3 pc_apply_grain(float3 y, float4 nf, float4 nc, float rough, float chroma, float3 resp, float amt) {
    float r = rough;
    float4 n = (nf * (1.0f - r) + nc * r) * (1.0f / _sqrtf((1.0f - r) * (1.0f - r) + r * r));
    float c = chroma;
    float3 g = (pc_s3(n.w) * (1.0f - c) + make_float3(n.x, n.y, n.z) * c)
               * (1.0f / _sqrtf((1.0f - c) * (1.0f - c) + c * c));
    float L = _clampf(pc_luma(y), 0.0f, 1.0f);
    float a0 = (L - 0.10f) / 0.16f;
    float a1 = (L - 0.45f) / 0.22f;
    float a2 = (L - 0.88f) / 0.16f;
    float w = resp.x * _expf(-a0 * a0) + resp.y * _expf(-a1 * a1) + resp.z * _expf(-a2 * a2);
    return y + g * (amt * w);
}

// ---------------------------------------------------------------- defeitos e moldura (damage() e frameMask() do app)
static inline float pc_seg(float px, float py, float ax, float ay, float bx, float by) {
    float pax = px - ax;
    float pay = py - ay;
    float bax = bx - ax;
    float bay = by - ay;
    float h = _clampf((pax * bax + pay * bay) / _fmaxf(bax * bax + bay * bay, 1e-6f), 0.0f, 1.0f);
    float dx = pax - bax * h;
    float dy = pay - bay * h;
    return _sqrtf(dx * dx + dy * dy);
}
static inline float3 pc_leak(float u, float v, float a, float4 L0, float4 L1, float3 col, float amt) {
    float d0x = (u - L0.x) * a;
    float d0y = v - L0.y;
    float d1x = (u - L1.x) * a;
    float d1y = v - L1.y;
    float acc = _expf(-(d0x * d0x + d0y * d0y) / _fmaxf(L0.z * L0.z, 0.0025f) * 2.0f) * L0.w
              + _expf(-(d1x * d1x + d1y * d1y) / _fmaxf(L1.z * L1.z, 0.0025f) * 2.0f) * L1.w;
    return col * (acc * amt * 1.6f);
}
static inline float3 pc_damage(float3 y, float u, float v, float W, float H, int frame, int seed, float stain_amt,
                           float stain_seed, float hair_on, float hair_seed, float hair_size, float hair_wig,
                           float cue, float splice_on, float splice_y, float dust, float dust_size, int dust_type,
                           float scratch, float scratch_w) {
    float pxx = u * (W / H) * 1080.0f;
    float pxy = v * 1080.0f;
    float Wd = W / H * 1080.0f;
    if (stain_amt > 0.0f) {
        float qx = pxx / 1080.0f * 2.2f + stain_seed * 7.31f;
        float qy = pxy / 1080.0f * 2.2f + stain_seed * 3.17f;
        float n = pc_fbm2(qx, qy);
        float body = pc_smooth(0.6f, 0.71f, n);
        float rim = pc_smooth(0.56f, 0.6f, n) * (1.0f - pc_smooth(0.6f, 0.67f, n));
        float3 tint = (pc_mod(stain_seed * 0.37f, 1.0f) < 0.5f) ? make_float3(1.2f, 0.86f, 1.12f)
                                                              : make_float3(0.9f, 1.12f, 0.84f);
        y = pc_lerp3(y, y * tint * 1.08f + pc_s3(0.04f), body * stain_amt);
        y = y * (1.0f - 0.08f * rim * stain_amt);
    }
    if (hair_on > 0.0f) {
        uint hs = PC_U(PC_I(hair_seed));
        float side = _floorf(pc_rnd(hs, 1u, 77u) * 4.0f);
        float t0 = 0.12f + 0.76f * pc_rnd(hs, 2u, 77u);
        float ax = Wd + 4.0f;
        float ay = t0 * 1080.0f;
        float dirx = -1.0f;
        float diry = 0.0f;
        if (side < 1.0f) { ax = t0 * Wd; ay = -4.0f; dirx = 0.0f; diry = 1.0f; }
        else if (side < 2.0f) { ax = t0 * Wd; ay = 1084.0f; dirx = 0.0f; diry = -1.0f; }
        else if (side < 3.0f) { ax = -4.0f; ay = t0 * 1080.0f; dirx = 1.0f; diry = 0.0f; }
        float L = (120.0f + 200.0f * pc_rnd(hs, 3u, 77u)) * hair_size;
        float perpx = -diry;
        float perpy = dirx;
        float bend = (pc_rnd(hs, 4u, 77u) - 0.5f) * 0.9f * L;
        float curl = (0.05f + 0.1f * pc_rnd(hs, 5u, 77u)) * L;
        float ph = pc_rnd(hs, 6u, 77u) * 6.2831853f;
        float dmin = 1e9f;
        float prx = ax;
        float pry = ay;
        for (int i = 1; i <= 40; i++) {
            float t = PC_F(i) / 40.0f;
            float off = bend * t * t + curl * _sinf(t * 7.5f + ph) * t + hair_wig * t * 1.5f;
            float ext = L * t * (0.75f + 0.25f * _cosf(t * 3.0f + ph));
            float bx = ax + dirx * ext + perpx * off;
            float by = ay + diry * ext + perpy * off;
            dmin = _fminf(dmin, pc_seg(pxx, pxy, prx, pry, bx, by));
            prx = bx;
            pry = by;
        }
        float th = 1.6f * hair_size;
        float m = 1.0f - pc_smooth(th * 0.4f, th + 1.4f, dmin);
        y = y * (1.0f - 0.9f * m);
    }
    if (cue > 0.0f) {
        float ccx = Wd - 1080.0f * 0.105f;
        float ccy = 1080.0f * 0.1f;
        float r = 1080.0f * 0.021f;
        float ddx = pxx - ccx;
        float ddy = pxy - ccy;
        float d = _sqrtf(ddx * ddx + ddy * ddy) + (pc_vnoise2(pxx * 0.3f, pxy * 0.3f) - 0.5f) * 2.2f;
        float disc = pc_smooth(r, r - 1.6f, d);
        float rim = pc_smooth(r + 2.6f, r + 0.4f, d) - disc;
        y = pc_lerp3(y, pc_s3(0.025f), disc * 0.9f);
        y = pc_lerp3(y, make_float3(0.9f, 0.88f, 0.8f), _fmaxf(rim, 0.0f) * 0.55f);
    }
    if (splice_on > 0.0f) {
        float yy = splice_y * 1080.0f;
        float line = pc_smooth(2.4f, 0.4f, _fabs(pxy - yy));
        float band = pc_smooth(16.0f, 11.0f, _fabs(pxy - yy - 9.0f));
        y = pc_lerp3(y, make_float3(0.9f, 0.89f, 0.84f), line * 0.6f);
        y = y * (1.0f - 0.1f * band);
    }
    uint fr = PC_U(frame);
    uint sd = PC_U(seed);
    if (dust > 0.0f) {
        float cell = 90.0f;
        int c0x = PC_I(_floorf(pxx / cell));
        int c0y = PC_I(_floorf(pxy / cell));
        float dark = 0.0f;
        float light = 0.0f;
        for (int j = -1; j <= 1; j++) {
            for (int i = -1; i <= 1; i++) {
                int cx = c0x + i;
                int cy = c0y + j;
                uint kx = PC_U(cx + 100000);
                uint ky = PC_U(cy + 100000);
                uint kz = fr * 131u + sd;
                if (pc_rnd(kx, ky, kz) < dust * 0.045f) {
                    float ctx = (PC_F(cx) + pc_rnd(kx, ky, kz + 1u)) * cell;
                    float cty = (PC_F(cy) + pc_rnd(kx, ky, kz + 2u)) * cell;
                    float q3 = pc_rnd(kx, ky, kz + 3u);
                    float rad = dust_size * (0.8f + 3.2f * q3 * q3);
                    float ang = pc_rnd(kx, ky, kz + 4u) * 6.2831853f;
                    float q5 = pc_rnd(kx, ky, kz + 5u);
                    float el = 1.0f + 3.0f * q5 * q5 * q5;
                    float dx = pxx - ctx;
                    float dy = pxy - cty;
                    float rx = (_cosf(ang) * dx + _sinf(ang) * dy) / el;
                    float ry = -_sinf(ang) * dx + _cosf(ang) * dy;
                    float m = pc_smooth(rad, rad * 0.45f, _sqrtf(rx * rx + ry * ry));
                    int is_light = (dust_type == 1 || (dust_type == 2 && pc_rnd(kx, ky, kz + 6u) < 0.5f)) ? 1 : 0;
                    if (is_light == 1) light = _fmaxf(light, m); else dark = _fmaxf(dark, m);
                }
            }
        }
        y = y * (1.0f - 0.88f * dark);
        y = pc_lerp3(y, make_float3(0.93f, 0.92f, 0.88f), light * 0.85f);
    }
    if (scratch > 0.0f) {
        uint epoch = PC_U(frame / 14);
        for (int k = 0; k < 6; k++) {
            uint kx = PC_U(k) + 7000u;
            if (pc_rnd(kx, epoch, sd) < scratch * 0.4f) {
                float x = pc_rnd(kx, epoch, sd + 1u) * Wd + 3.0f * _sinf(PC_F(frame) * 0.37f + PC_F(k))
                        + (pc_rnd(PC_U(k), fr, sd + 5u) - 0.5f) * 2.0f;
                float w = scratch_w * (0.6f + 0.8f * pc_rnd(kx, epoch, sd + 2u));
                float a = pc_smooth(1.0f, 0.0f, _fabs(pxx - x) / w);
                float along = 0.55f + 0.45f * _sinf(pxy * (0.004f + 0.01f * pc_rnd(kx, epoch, sd + 3u))
                                                    + PC_F(k) * 2.1f + PC_F(frame) * 0.2f);
                float vis = 0.35f + 0.65f * pc_rnd(PC_U(k) + 50u, fr, sd);
                y = pc_lerp3(y, make_float3(0.92f, 0.93f, 0.88f), a * along * vis * 0.7f);
            }
        }
    }
    return y;
}
static inline float pc_vnoise1(float x) {
    float i = _floorf(x);
    float f = x - i;
    float u = f * f * (3.0f - 2.0f * f);
    float a = pc_rnd(PC_U(PC_I(i) + 100000), 3u, 9u);
    float b = pc_rnd(PC_U(PC_I(i) + 100001), 3u, 9u);
    return pc_lerp(a, b, u) * 2.0f - 1.0f;
}
static inline float3 pc_frame_mask(float3 y, float u, float v, float W, float H, float scale, float aspect_t,
                               float corner, float edge_soft, float edge_rough, float3 bar) {
    if (aspect_t <= 0.0f && corner <= 0.0f && edge_rough <= 0.0f) return y;
    float A = W / H;
    float hbx = 0.5f;
    float hby = 0.5f;
    if (aspect_t > 0.0f) {
        if (aspect_t > A) hby = 0.5f * A / aspect_t; else hbx = 0.5f * aspect_t / A;
    }
    float px = (u - 0.5f) * W;
    float py = (v - 0.5f) * H;
    float hx = hbx * W + 0.5f;
    float hy = hby * H + 0.5f;
    float rad = corner * _fminf(hx, hy) * 2.0f;
    float qx = _fabs(px) - hx + rad;
    float qy = _fabs(py) - hy + rad;
    float mx = _fmaxf(qx, 0.0f);
    float my = _fmaxf(qy, 0.0f);
    float sd = _sqrtf(mx * mx + my * my) + _fminf(_fmaxf(qx, qy), 0.0f) - rad;
    if (edge_rough > 0.0f) {
        float n = pc_vnoise1(px * 0.02f / scale + 13.0f) + pc_vnoise1(py * 0.02f / scale + 71.0f)
                + 0.5f * pc_vnoise1(px * 0.11f / scale) + 0.5f * pc_vnoise1(py * 0.11f / scale + 5.0f);
        sd = sd + (n + 1.5f) * edge_rough * 5.0f * scale;
    }
    float soft = _fmaxf(edge_soft * H, 0.7f);
    float m = 1.0f - pc_smooth(-soft, soft, sd);
    return pc_lerp3(bar, y, m);
}

static inline float3 pc_neg_grain(float4 nf, float4 nc, float rough, float chroma) {
    float r = rough;
    float4 n = (nf * (1.0f - r) + nc * r) * (1.0f / _sqrtf((1.0f - r) * (1.0f - r) + r * r));
    float c = chroma;
    return (pc_s3(n.w) * (1.0f - c) + make_float3(n.x, n.y, n.z) * c)
           * (1.0f / _sqrtf((1.0f - c) * (1.0f - c) + c * c));
}

static inline float pc_breath1(int frame, int s) {
    float fast = (pc_hash(frame, s) * 2.0f - 1.0f) * 1.7320508f;
    float slow = pc_vnoise(PC_F(frame) / PC_BREATH_SLOW, s + 101) * PC_BREATH_SLOW_NORM;
    return 0.8f * fast + 0.6f * slow;
}
static inline float3 pc_breath(int frame, int seed, float amount) {
    int s = seed * 3 + 7001;
    float a = amount * PC_BREATH_SIGMA_D;
    return make_float3(pc_breath1(frame, s) * a, pc_breath1(frame, s + 1) * a, pc_breath1(frame, s + 2) * a);
}

// ---------------------------------------------------------------- valores (formato do app)
struct pc_vals {
    int copia;
    float copia_forca;
    float mix_geral;
    int mostrar_curva;
    int bitola;
    int iso;
    int bitola_desfoque_on;
    float bitola_resolucao;
    float bitola_vinheta;
    int mtf;
    float mtf_forca;
    float mtf_camadas;
    int entrada;
    int faixa_video;
    int logc3_ei;
    float exposicao;
    float temperatura;
    float tint;
    float proteger_cores;
    int lab_on;
    int lab_negativo;
    int lab_copia;
    float lab_revelacao;
    float lab_separacao;
    float lab_separacao_eixo;
    float lab_luz_r;
    float lab_luz_g;
    float lab_luz_b;
    float lab_densidade;
    float lab_dens_r;
    float lab_dens_g;
    float lab_dens_b;
    float lab_pe;
    float lab_sombras_rolagem;
    float lab_luzes_rolagem;
    float lab_saturacao_filme;
    float lab_saturacao;
    float lab_pele_matiz;
    float lab_pele_sat;
    float lab_bypass_negativo;
    float lab_bypass_copia;
    float lab_neutro_negativo;
    float lab_neutro_copia;
    int lab_processo;
    float lab_processo_forca;
    float lab_chave;
    float lab_diafonia;
    int lab_grao;
    int lab_grao_modelo;
    int cor_on;
    float cor_forca;
    float contraste;
    float meio_tom;
    float preto;
    float branco;
    float rolagem_luzes;
    float rolagem_sombras;
    float saturacao;
    float densidade;
    float sombras_matiz;
    float sombras_forca;
    float luzes_matiz;
    float luzes_forca;
    float equilibrio;
    float contraste_r;
    float contraste_g;
    float contraste_b;
    float offset_r;
    float offset_g;
    float offset_b;
    float verdes_matiz;
    float azuis_matiz;
    float pele_sat;
    float pele_matiz;
    float pele_luz;
    int pb;
    int pb_filtro;
    int virada;
    float virada_forca;
    float envelhecimento;
    int grao_on;
    float grao_forca;
    float grao_tamanho;
    float grao_aspereza;
    float grao_cor;
    float grao_sombras;
    float grao_meios;
    float grao_luzes;
    int grao_animado;
    int grao_semente;
    float grao_maciez;
    float grao_respiracao;
    int hal_on;
    float hal_forca;
    float hal_raio;
    float hal_limiar;
    float3 hal_cor;
    int hal_modelo;
    int bloom_on;
    float bloom_forca;
    float bloom_raio;
    float bloom_limiar;
    float nevoa_forca;
    float nevoa_raio;
    int lente_on;
    float maciez;
    float raio_maciez;
    float nitidez;
    float aberracao;
    float distorcao;
    float vinheta;
    float vinheta_raio;
    float vinheta_suavidade;
    float vinheta_redondeza;
    int proj_on;
    float tremor_x;
    float tremor_y;
    float tremor_rot;
    float tremor_vel;
    float cintilacao;
    float cintilacao_vel;
    int desg_on;
    int poeira_on;
    float poeira;
    float poeira_tamanho;
    int poeira_tipo;
    int riscos_on;
    float riscos;
    float riscos_largura;
    int cabelo_on;
    float cabelo;
    float cabelo_tamanho;
    int manchas_on;
    float manchas;
    int queima_on;
    float queima;
    int marcas_on;
    float marcas_intervalo;
    int cor_instavel_on;
    float cor_instavel;
    int emenda_on;
    float emenda;
    int vazamento_on;
    float vazamento;
    float3 vazamento_cor;
    float vazamento_vel;
    int desgaste_semente;
    int mold_on;
    int proporcao;
    float cantos;
    float borda_suave;
    float borda_irregular;
    float3 cor_barras;
};
#define PC_UI_SIZE 159
static inline void pc_unpack(const float* ui, pc_vals* V) {
    float ui_copia = ui[0];
    V->copia = PC_I(ui_copia);
    float ui_copia_forca = ui[1];
    V->copia_forca = (ui_copia_forca * 0.01f);
    float ui_mix_geral = ui[2];
    V->mix_geral = (ui_mix_geral * 0.01f);
    float ui_mostrar_curva = ui[3];
    V->mostrar_curva = PC_I(ui_mostrar_curva);
    float ui_bitola = ui[4];
    V->bitola = PC_I(ui_bitola);
    float ui_iso = ui[5];
    V->iso = PC_I(ui_iso);
    float ui_bitola_desfoque_on = ui[6];
    V->bitola_desfoque_on = PC_I(ui_bitola_desfoque_on);
    float ui_bitola_resolucao = ui[7];
    V->bitola_resolucao = (ui_bitola_resolucao * 0.01f);
    float ui_bitola_vinheta = ui[8];
    V->bitola_vinheta = (ui_bitola_vinheta * 0.01f);
    float ui_mtf = ui[9];
    V->mtf = PC_I(ui_mtf);
    float ui_mtf_forca = ui[10];
    V->mtf_forca = (ui_mtf_forca * 0.01f);
    float ui_mtf_camadas = ui[11];
    V->mtf_camadas = (ui_mtf_camadas * 0.01f);
    float ui_entrada = ui[12];
    V->entrada = PC_I(ui_entrada);
    float ui_faixa_video = ui[13];
    V->faixa_video = PC_I(ui_faixa_video);
    float ui_logc3_ei = ui[14];
    V->logc3_ei = PC_I(ui_logc3_ei);
    float ui_exposicao = ui[15];
    V->exposicao = ui_exposicao;
    float ui_temperatura = ui[16];
    V->temperatura = ui_temperatura;
    float ui_tint = ui[17];
    V->tint = ui_tint;
    float ui_proteger_cores = ui[18];
    V->proteger_cores = (ui_proteger_cores * 0.01f);
    float ui_lab_on = ui[19];
    V->lab_on = PC_I(ui_lab_on);
    float ui_lab_negativo = ui[20];
    V->lab_negativo = PC_I(ui_lab_negativo);
    float ui_lab_copia = ui[21];
    V->lab_copia = PC_I(ui_lab_copia);
    float ui_lab_revelacao = ui[22];
    V->lab_revelacao = ui_lab_revelacao;
    float ui_lab_separacao = ui[23];
    V->lab_separacao = (ui_lab_separacao * 0.01f);
    float ui_lab_separacao_eixo = ui[24];
    V->lab_separacao_eixo = ui_lab_separacao_eixo;
    float ui_lab_luz_r = ui[25];
    V->lab_luz_r = ui_lab_luz_r;
    float ui_lab_luz_g = ui[26];
    V->lab_luz_g = ui_lab_luz_g;
    float ui_lab_luz_b = ui[27];
    V->lab_luz_b = ui_lab_luz_b;
    float ui_lab_densidade = ui[28];
    V->lab_densidade = ui_lab_densidade;
    float ui_lab_dens_r = ui[29];
    V->lab_dens_r = ui_lab_dens_r;
    float ui_lab_dens_g = ui[30];
    V->lab_dens_g = ui_lab_dens_g;
    float ui_lab_dens_b = ui[31];
    V->lab_dens_b = ui_lab_dens_b;
    float ui_lab_pe = ui[32];
    V->lab_pe = ui_lab_pe;
    float ui_lab_sombras_rolagem = ui[33];
    V->lab_sombras_rolagem = (ui_lab_sombras_rolagem * 0.01f);
    float ui_lab_luzes_rolagem = ui[34];
    V->lab_luzes_rolagem = (ui_lab_luzes_rolagem * 0.01f);
    float ui_lab_saturacao_filme = ui[35];
    V->lab_saturacao_filme = ui_lab_saturacao_filme;
    float ui_lab_saturacao = ui[36];
    V->lab_saturacao = ui_lab_saturacao;
    float ui_lab_pele_matiz = ui[37];
    V->lab_pele_matiz = ui_lab_pele_matiz;
    float ui_lab_pele_sat = ui[38];
    V->lab_pele_sat = ui_lab_pele_sat;
    float ui_lab_bypass_negativo = ui[39];
    V->lab_bypass_negativo = (ui_lab_bypass_negativo * 0.01f);
    float ui_lab_bypass_copia = ui[40];
    V->lab_bypass_copia = (ui_lab_bypass_copia * 0.01f);
    float ui_lab_neutro_negativo = ui[41];
    V->lab_neutro_negativo = (ui_lab_neutro_negativo * 0.01f);
    float ui_lab_neutro_copia = ui[42];
    V->lab_neutro_copia = (ui_lab_neutro_copia * 0.01f);
    float ui_lab_processo = ui[43];
    V->lab_processo = PC_I(ui_lab_processo);
    float ui_lab_processo_forca = ui[44];
    V->lab_processo_forca = (ui_lab_processo_forca * 0.01f);
    float ui_lab_chave = ui[45];
    V->lab_chave = (ui_lab_chave * 0.01f);
    float ui_lab_diafonia = ui[46];
    V->lab_diafonia = ui_lab_diafonia;
    float ui_lab_grao = ui[47];
    V->lab_grao = PC_I(ui_lab_grao);
    float ui_lab_grao_modelo = ui[48];
    V->lab_grao_modelo = PC_I(ui_lab_grao_modelo);
    float ui_cor_on = ui[49];
    V->cor_on = PC_I(ui_cor_on);
    float ui_cor_forca = ui[50];
    V->cor_forca = (ui_cor_forca * 0.01f);
    float ui_contraste = ui[51];
    V->contraste = ui_contraste;
    float ui_meio_tom = ui[52];
    V->meio_tom = ui_meio_tom;
    float ui_preto = ui[53];
    V->preto = ui_preto;
    float ui_branco = ui[54];
    V->branco = ui_branco;
    float ui_rolagem_luzes = ui[55];
    V->rolagem_luzes = (ui_rolagem_luzes * 0.01f);
    float ui_rolagem_sombras = ui[56];
    V->rolagem_sombras = (ui_rolagem_sombras * 0.01f);
    float ui_saturacao = ui[57];
    V->saturacao = ui_saturacao;
    float ui_densidade = ui[58];
    V->densidade = (ui_densidade * 0.01f);
    float ui_sombras_matiz = ui[59];
    V->sombras_matiz = ui_sombras_matiz;
    float ui_sombras_forca = ui[60];
    V->sombras_forca = (ui_sombras_forca * 0.01f);
    float ui_luzes_matiz = ui[61];
    V->luzes_matiz = ui_luzes_matiz;
    float ui_luzes_forca = ui[62];
    V->luzes_forca = (ui_luzes_forca * 0.01f);
    float ui_equilibrio = ui[63];
    V->equilibrio = ui_equilibrio;
    float ui_contraste_r = ui[64];
    V->contraste_r = ui_contraste_r;
    float ui_contraste_g = ui[65];
    V->contraste_g = ui_contraste_g;
    float ui_contraste_b = ui[66];
    V->contraste_b = ui_contraste_b;
    float ui_offset_r = ui[67];
    V->offset_r = ui_offset_r;
    float ui_offset_g = ui[68];
    V->offset_g = ui_offset_g;
    float ui_offset_b = ui[69];
    V->offset_b = ui_offset_b;
    float ui_verdes_matiz = ui[70];
    V->verdes_matiz = ui_verdes_matiz;
    float ui_azuis_matiz = ui[71];
    V->azuis_matiz = ui_azuis_matiz;
    float ui_pele_sat = ui[72];
    V->pele_sat = ui_pele_sat;
    float ui_pele_matiz = ui[73];
    V->pele_matiz = ui_pele_matiz;
    float ui_pele_luz = ui[74];
    V->pele_luz = ui_pele_luz;
    float ui_pb = ui[75];
    V->pb = PC_I(ui_pb);
    float ui_pb_filtro = ui[76];
    V->pb_filtro = PC_I(ui_pb_filtro);
    float ui_virada = ui[77];
    V->virada = PC_I(ui_virada);
    float ui_virada_forca = ui[78];
    V->virada_forca = (ui_virada_forca * 0.01f);
    float ui_envelhecimento = ui[79];
    V->envelhecimento = (ui_envelhecimento * 0.01f);
    float ui_grao_on = ui[80];
    V->grao_on = PC_I(ui_grao_on);
    float ui_grao_forca = ui[81];
    V->grao_forca = ui_grao_forca;
    float ui_grao_tamanho = ui[82];
    V->grao_tamanho = ui_grao_tamanho;
    float ui_grao_aspereza = ui[83];
    V->grao_aspereza = (ui_grao_aspereza * 0.01f);
    float ui_grao_cor = ui[84];
    V->grao_cor = (ui_grao_cor * 0.01f);
    float ui_grao_sombras = ui[85];
    V->grao_sombras = ui_grao_sombras;
    float ui_grao_meios = ui[86];
    V->grao_meios = ui_grao_meios;
    float ui_grao_luzes = ui[87];
    V->grao_luzes = ui_grao_luzes;
    float ui_grao_animado = ui[88];
    V->grao_animado = PC_I(ui_grao_animado);
    float ui_grao_semente = ui[89];
    V->grao_semente = PC_I(ui_grao_semente);
    float ui_grao_maciez = ui[90];
    V->grao_maciez = (ui_grao_maciez * 0.01f);
    float ui_grao_respiracao = ui[91];
    V->grao_respiracao = (ui_grao_respiracao * 0.01f);
    float ui_hal_on = ui[92];
    V->hal_on = PC_I(ui_hal_on);
    float ui_hal_forca = ui[93];
    V->hal_forca = ui_hal_forca;
    float ui_hal_raio = ui[94];
    V->hal_raio = ui_hal_raio;
    float ui_hal_limiar = ui[95];
    V->hal_limiar = ui_hal_limiar;
    pc_color3 ui_hal_cor = {ui[96], ui[97], ui[98]};
    V->hal_cor = make_float3(ui_hal_cor.r, ui_hal_cor.g, ui_hal_cor.b);
    float ui_hal_modelo = ui[99];
    V->hal_modelo = PC_I(ui_hal_modelo);
    float ui_bloom_on = ui[100];
    V->bloom_on = PC_I(ui_bloom_on);
    float ui_bloom_forca = ui[101];
    V->bloom_forca = ui_bloom_forca;
    float ui_bloom_raio = ui[102];
    V->bloom_raio = ui_bloom_raio;
    float ui_bloom_limiar = ui[103];
    V->bloom_limiar = ui_bloom_limiar;
    float ui_nevoa_forca = ui[104];
    V->nevoa_forca = (ui_nevoa_forca * 0.01f);
    float ui_nevoa_raio = ui[105];
    V->nevoa_raio = ui_nevoa_raio;
    float ui_lente_on = ui[106];
    V->lente_on = PC_I(ui_lente_on);
    float ui_maciez = ui[107];
    V->maciez = (ui_maciez * 0.01f);
    float ui_raio_maciez = ui[108];
    V->raio_maciez = ui_raio_maciez;
    float ui_nitidez = ui[109];
    V->nitidez = ui_nitidez;
    float ui_aberracao = ui[110];
    V->aberracao = ui_aberracao;
    float ui_distorcao = ui[111];
    V->distorcao = ui_distorcao;
    float ui_vinheta = ui[112];
    V->vinheta = (ui_vinheta * 0.01f);
    float ui_vinheta_raio = ui[113];
    V->vinheta_raio = ui_vinheta_raio;
    float ui_vinheta_suavidade = ui[114];
    V->vinheta_suavidade = ui_vinheta_suavidade;
    float ui_vinheta_redondeza = ui[115];
    V->vinheta_redondeza = (ui_vinheta_redondeza * 0.01f);
    float ui_proj_on = ui[116];
    V->proj_on = PC_I(ui_proj_on);
    float ui_tremor_x = ui[117];
    V->tremor_x = ui_tremor_x;
    float ui_tremor_y = ui[118];
    V->tremor_y = ui_tremor_y;
    float ui_tremor_rot = ui[119];
    V->tremor_rot = ui_tremor_rot;
    float ui_tremor_vel = ui[120];
    V->tremor_vel = ui_tremor_vel;
    float ui_cintilacao = ui[121];
    V->cintilacao = ui_cintilacao;
    float ui_cintilacao_vel = ui[122];
    V->cintilacao_vel = ui_cintilacao_vel;
    float ui_desg_on = ui[123];
    V->desg_on = PC_I(ui_desg_on);
    float ui_poeira_on = ui[124];
    V->poeira_on = PC_I(ui_poeira_on);
    float ui_poeira = ui[125];
    V->poeira = (ui_poeira * 0.01f);
    float ui_poeira_tamanho = ui[126];
    V->poeira_tamanho = ui_poeira_tamanho;
    float ui_poeira_tipo = ui[127];
    V->poeira_tipo = PC_I(ui_poeira_tipo);
    float ui_riscos_on = ui[128];
    V->riscos_on = PC_I(ui_riscos_on);
    float ui_riscos = ui[129];
    V->riscos = (ui_riscos * 0.01f);
    float ui_riscos_largura = ui[130];
    V->riscos_largura = ui_riscos_largura;
    float ui_cabelo_on = ui[131];
    V->cabelo_on = PC_I(ui_cabelo_on);
    float ui_cabelo = ui[132];
    V->cabelo = (ui_cabelo * 0.01f);
    float ui_cabelo_tamanho = ui[133];
    V->cabelo_tamanho = ui_cabelo_tamanho;
    float ui_manchas_on = ui[134];
    V->manchas_on = PC_I(ui_manchas_on);
    float ui_manchas = ui[135];
    V->manchas = (ui_manchas * 0.01f);
    float ui_queima_on = ui[136];
    V->queima_on = PC_I(ui_queima_on);
    float ui_queima = ui[137];
    V->queima = (ui_queima * 0.01f);
    float ui_marcas_on = ui[138];
    V->marcas_on = PC_I(ui_marcas_on);
    float ui_marcas_intervalo = ui[139];
    V->marcas_intervalo = ui_marcas_intervalo;
    float ui_cor_instavel_on = ui[140];
    V->cor_instavel_on = PC_I(ui_cor_instavel_on);
    float ui_cor_instavel = ui[141];
    V->cor_instavel = (ui_cor_instavel * 0.01f);
    float ui_emenda_on = ui[142];
    V->emenda_on = PC_I(ui_emenda_on);
    float ui_emenda = ui[143];
    V->emenda = (ui_emenda * 0.01f);
    float ui_vazamento_on = ui[144];
    V->vazamento_on = PC_I(ui_vazamento_on);
    float ui_vazamento = ui[145];
    V->vazamento = (ui_vazamento * 0.01f);
    pc_color3 ui_vazamento_cor = {ui[146], ui[147], ui[148]};
    V->vazamento_cor = make_float3(ui_vazamento_cor.r, ui_vazamento_cor.g, ui_vazamento_cor.b);
    float ui_vazamento_vel = ui[149];
    V->vazamento_vel = ui_vazamento_vel;
    float ui_desgaste_semente = ui[150];
    V->desgaste_semente = PC_I(ui_desgaste_semente);
    float ui_mold_on = ui[151];
    V->mold_on = PC_I(ui_mold_on);
    float ui_proporcao = ui[152];
    V->proporcao = PC_I(ui_proporcao);
    float ui_cantos = ui[153];
    V->cantos = ui_cantos;
    float ui_borda_suave = ui[154];
    V->borda_suave = ui_borda_suave;
    float ui_borda_irregular = ui[155];
    V->borda_irregular = (ui_borda_irregular * 0.01f);
    pc_color3 ui_cor_barras = {ui[156], ui[157], ui[158]};
    V->cor_barras = make_float3(ui_cor_barras.r, ui_cor_barras.g, ui_cor_barras.b);
}

// perfil de entrada: codigo do video -> luz linear (B_INPUT)
static inline float3 pc_input(const pc_vals& V, float3 code) {
    int v_copia = V.copia;
    float v_copia_forca = V.copia_forca;
    float v_mix_geral = V.mix_geral;
    int v_mostrar_curva = V.mostrar_curva;
    int v_bitola = V.bitola;
    int v_iso = V.iso;
    int v_bitola_desfoque_on = V.bitola_desfoque_on;
    float v_bitola_resolucao = V.bitola_resolucao;
    float v_bitola_vinheta = V.bitola_vinheta;
    int v_mtf = V.mtf;
    float v_mtf_forca = V.mtf_forca;
    float v_mtf_camadas = V.mtf_camadas;
    int v_entrada = V.entrada;
    int v_faixa_video = V.faixa_video;
    int v_logc3_ei = V.logc3_ei;
    float v_exposicao = V.exposicao;
    float v_temperatura = V.temperatura;
    float v_tint = V.tint;
    float v_proteger_cores = V.proteger_cores;
    int v_lab_on = V.lab_on;
    int v_lab_negativo = V.lab_negativo;
    int v_lab_copia = V.lab_copia;
    float v_lab_revelacao = V.lab_revelacao;
    float v_lab_separacao = V.lab_separacao;
    float v_lab_separacao_eixo = V.lab_separacao_eixo;
    float v_lab_luz_r = V.lab_luz_r;
    float v_lab_luz_g = V.lab_luz_g;
    float v_lab_luz_b = V.lab_luz_b;
    float v_lab_densidade = V.lab_densidade;
    float v_lab_dens_r = V.lab_dens_r;
    float v_lab_dens_g = V.lab_dens_g;
    float v_lab_dens_b = V.lab_dens_b;
    float v_lab_pe = V.lab_pe;
    float v_lab_sombras_rolagem = V.lab_sombras_rolagem;
    float v_lab_luzes_rolagem = V.lab_luzes_rolagem;
    float v_lab_saturacao_filme = V.lab_saturacao_filme;
    float v_lab_saturacao = V.lab_saturacao;
    float v_lab_pele_matiz = V.lab_pele_matiz;
    float v_lab_pele_sat = V.lab_pele_sat;
    float v_lab_bypass_negativo = V.lab_bypass_negativo;
    float v_lab_bypass_copia = V.lab_bypass_copia;
    float v_lab_neutro_negativo = V.lab_neutro_negativo;
    float v_lab_neutro_copia = V.lab_neutro_copia;
    int v_lab_processo = V.lab_processo;
    float v_lab_processo_forca = V.lab_processo_forca;
    float v_lab_chave = V.lab_chave;
    float v_lab_diafonia = V.lab_diafonia;
    int v_lab_grao = V.lab_grao;
    int v_lab_grao_modelo = V.lab_grao_modelo;
    int v_cor_on = V.cor_on;
    float v_cor_forca = V.cor_forca;
    float v_contraste = V.contraste;
    float v_meio_tom = V.meio_tom;
    float v_preto = V.preto;
    float v_branco = V.branco;
    float v_rolagem_luzes = V.rolagem_luzes;
    float v_rolagem_sombras = V.rolagem_sombras;
    float v_saturacao = V.saturacao;
    float v_densidade = V.densidade;
    float v_sombras_matiz = V.sombras_matiz;
    float v_sombras_forca = V.sombras_forca;
    float v_luzes_matiz = V.luzes_matiz;
    float v_luzes_forca = V.luzes_forca;
    float v_equilibrio = V.equilibrio;
    float v_contraste_r = V.contraste_r;
    float v_contraste_g = V.contraste_g;
    float v_contraste_b = V.contraste_b;
    float v_offset_r = V.offset_r;
    float v_offset_g = V.offset_g;
    float v_offset_b = V.offset_b;
    float v_verdes_matiz = V.verdes_matiz;
    float v_azuis_matiz = V.azuis_matiz;
    float v_pele_sat = V.pele_sat;
    float v_pele_matiz = V.pele_matiz;
    float v_pele_luz = V.pele_luz;
    int v_pb = V.pb;
    int v_pb_filtro = V.pb_filtro;
    int v_virada = V.virada;
    float v_virada_forca = V.virada_forca;
    float v_envelhecimento = V.envelhecimento;
    int v_grao_on = V.grao_on;
    float v_grao_forca = V.grao_forca;
    float v_grao_tamanho = V.grao_tamanho;
    float v_grao_aspereza = V.grao_aspereza;
    float v_grao_cor = V.grao_cor;
    float v_grao_sombras = V.grao_sombras;
    float v_grao_meios = V.grao_meios;
    float v_grao_luzes = V.grao_luzes;
    int v_grao_animado = V.grao_animado;
    int v_grao_semente = V.grao_semente;
    float v_grao_maciez = V.grao_maciez;
    float v_grao_respiracao = V.grao_respiracao;
    int v_hal_on = V.hal_on;
    float v_hal_forca = V.hal_forca;
    float v_hal_raio = V.hal_raio;
    float v_hal_limiar = V.hal_limiar;
    float3 v_hal_cor = V.hal_cor;
    int v_hal_modelo = V.hal_modelo;
    int v_bloom_on = V.bloom_on;
    float v_bloom_forca = V.bloom_forca;
    float v_bloom_raio = V.bloom_raio;
    float v_bloom_limiar = V.bloom_limiar;
    float v_nevoa_forca = V.nevoa_forca;
    float v_nevoa_raio = V.nevoa_raio;
    int v_lente_on = V.lente_on;
    float v_maciez = V.maciez;
    float v_raio_maciez = V.raio_maciez;
    float v_nitidez = V.nitidez;
    float v_aberracao = V.aberracao;
    float v_distorcao = V.distorcao;
    float v_vinheta = V.vinheta;
    float v_vinheta_raio = V.vinheta_raio;
    float v_vinheta_suavidade = V.vinheta_suavidade;
    float v_vinheta_redondeza = V.vinheta_redondeza;
    int v_proj_on = V.proj_on;
    float v_tremor_x = V.tremor_x;
    float v_tremor_y = V.tremor_y;
    float v_tremor_rot = V.tremor_rot;
    float v_tremor_vel = V.tremor_vel;
    float v_cintilacao = V.cintilacao;
    float v_cintilacao_vel = V.cintilacao_vel;
    int v_desg_on = V.desg_on;
    int v_poeira_on = V.poeira_on;
    float v_poeira = V.poeira;
    float v_poeira_tamanho = V.poeira_tamanho;
    int v_poeira_tipo = V.poeira_tipo;
    int v_riscos_on = V.riscos_on;
    float v_riscos = V.riscos;
    float v_riscos_largura = V.riscos_largura;
    int v_cabelo_on = V.cabelo_on;
    float v_cabelo = V.cabelo;
    float v_cabelo_tamanho = V.cabelo_tamanho;
    int v_manchas_on = V.manchas_on;
    float v_manchas = V.manchas;
    int v_queima_on = V.queima_on;
    float v_queima = V.queima;
    int v_marcas_on = V.marcas_on;
    float v_marcas_intervalo = V.marcas_intervalo;
    int v_cor_instavel_on = V.cor_instavel_on;
    float v_cor_instavel = V.cor_instavel;
    int v_emenda_on = V.emenda_on;
    float v_emenda = V.emenda;
    int v_vazamento_on = V.vazamento_on;
    float v_vazamento = V.vazamento;
    float3 v_vazamento_cor = V.vazamento_cor;
    float v_vazamento_vel = V.vazamento_vel;
    int v_desgaste_semente = V.desgaste_semente;
    int v_mold_on = V.mold_on;
    int v_proporcao = V.proporcao;
    float v_cantos = V.cantos;
    float v_borda_suave = V.borda_suave;
    float v_borda_irregular = V.borda_irregular;
    float3 v_cor_barras = V.cor_barras;
    (void)v_copia;
    (void)v_copia_forca;
    (void)v_mix_geral;
    (void)v_mostrar_curva;
    (void)v_bitola;
    (void)v_iso;
    (void)v_bitola_desfoque_on;
    (void)v_bitola_resolucao;
    (void)v_bitola_vinheta;
    (void)v_mtf;
    (void)v_mtf_forca;
    (void)v_mtf_camadas;
    (void)v_entrada;
    (void)v_faixa_video;
    (void)v_logc3_ei;
    (void)v_exposicao;
    (void)v_temperatura;
    (void)v_tint;
    (void)v_proteger_cores;
    (void)v_lab_on;
    (void)v_lab_negativo;
    (void)v_lab_copia;
    (void)v_lab_revelacao;
    (void)v_lab_separacao;
    (void)v_lab_separacao_eixo;
    (void)v_lab_luz_r;
    (void)v_lab_luz_g;
    (void)v_lab_luz_b;
    (void)v_lab_densidade;
    (void)v_lab_dens_r;
    (void)v_lab_dens_g;
    (void)v_lab_dens_b;
    (void)v_lab_pe;
    (void)v_lab_sombras_rolagem;
    (void)v_lab_luzes_rolagem;
    (void)v_lab_saturacao_filme;
    (void)v_lab_saturacao;
    (void)v_lab_pele_matiz;
    (void)v_lab_pele_sat;
    (void)v_lab_bypass_negativo;
    (void)v_lab_bypass_copia;
    (void)v_lab_neutro_negativo;
    (void)v_lab_neutro_copia;
    (void)v_lab_processo;
    (void)v_lab_processo_forca;
    (void)v_lab_chave;
    (void)v_lab_diafonia;
    (void)v_lab_grao;
    (void)v_lab_grao_modelo;
    (void)v_cor_on;
    (void)v_cor_forca;
    (void)v_contraste;
    (void)v_meio_tom;
    (void)v_preto;
    (void)v_branco;
    (void)v_rolagem_luzes;
    (void)v_rolagem_sombras;
    (void)v_saturacao;
    (void)v_densidade;
    (void)v_sombras_matiz;
    (void)v_sombras_forca;
    (void)v_luzes_matiz;
    (void)v_luzes_forca;
    (void)v_equilibrio;
    (void)v_contraste_r;
    (void)v_contraste_g;
    (void)v_contraste_b;
    (void)v_offset_r;
    (void)v_offset_g;
    (void)v_offset_b;
    (void)v_verdes_matiz;
    (void)v_azuis_matiz;
    (void)v_pele_sat;
    (void)v_pele_matiz;
    (void)v_pele_luz;
    (void)v_pb;
    (void)v_pb_filtro;
    (void)v_virada;
    (void)v_virada_forca;
    (void)v_envelhecimento;
    (void)v_grao_on;
    (void)v_grao_forca;
    (void)v_grao_tamanho;
    (void)v_grao_aspereza;
    (void)v_grao_cor;
    (void)v_grao_sombras;
    (void)v_grao_meios;
    (void)v_grao_luzes;
    (void)v_grao_animado;
    (void)v_grao_semente;
    (void)v_grao_maciez;
    (void)v_grao_respiracao;
    (void)v_hal_on;
    (void)v_hal_forca;
    (void)v_hal_raio;
    (void)v_hal_limiar;
    (void)v_hal_cor;
    (void)v_hal_modelo;
    (void)v_bloom_on;
    (void)v_bloom_forca;
    (void)v_bloom_raio;
    (void)v_bloom_limiar;
    (void)v_nevoa_forca;
    (void)v_nevoa_raio;
    (void)v_lente_on;
    (void)v_maciez;
    (void)v_raio_maciez;
    (void)v_nitidez;
    (void)v_aberracao;
    (void)v_distorcao;
    (void)v_vinheta;
    (void)v_vinheta_raio;
    (void)v_vinheta_suavidade;
    (void)v_vinheta_redondeza;
    (void)v_proj_on;
    (void)v_tremor_x;
    (void)v_tremor_y;
    (void)v_tremor_rot;
    (void)v_tremor_vel;
    (void)v_cintilacao;
    (void)v_cintilacao_vel;
    (void)v_desg_on;
    (void)v_poeira_on;
    (void)v_poeira;
    (void)v_poeira_tamanho;
    (void)v_poeira_tipo;
    (void)v_riscos_on;
    (void)v_riscos;
    (void)v_riscos_largura;
    (void)v_cabelo_on;
    (void)v_cabelo;
    (void)v_cabelo_tamanho;
    (void)v_manchas_on;
    (void)v_manchas;
    (void)v_queima_on;
    (void)v_queima;
    (void)v_marcas_on;
    (void)v_marcas_intervalo;
    (void)v_cor_instavel_on;
    (void)v_cor_instavel;
    (void)v_emenda_on;
    (void)v_emenda;
    (void)v_vazamento_on;
    (void)v_vazamento;
    (void)v_vazamento_cor;
    (void)v_vazamento_vel;
    (void)v_desgaste_semente;
    (void)v_mold_on;
    (void)v_proporcao;
    (void)v_cantos;
    (void)v_borda_suave;
    (void)v_borda_irregular;
    (void)v_cor_barras;

    int ent = v_entrada;
    int in_cv = (PC_IN_CV[ent] == 1 && v_faixa_video == 0) ? 1 : 0;
    float3 lin_in = pc_to_linear(code, PC_IN_ID[ent], in_cv);
    if (PC_IN_ID[ent] == 4 && v_logc3_ei != PC_LC3_STD)
        lin_in = make_float3(pc_logc3e_dec(code.x, v_logc3_ei), pc_logc3e_dec(code.y, v_logc3_ei),
                             pc_logc3e_dec(code.z, v_logc3_ei));
    lin_in = pc_mat3(make_float3(PC_GAM[ent * 9 + 0], PC_GAM[ent * 9 + 1], PC_GAM[ent * 9 + 2]),
                     make_float3(PC_GAM[ent * 9 + 3], PC_GAM[ent * 9 + 4], PC_GAM[ent * 9 + 5]),
                     make_float3(PC_GAM[ent * 9 + 6], PC_GAM[ent * 9 + 7], PC_GAM[ent * 9 + 8]), lin_in);
    if (v_proteger_cores > 0.0f)
        lin_in = pc_lerp3(lin_in, pc_gamut_compress(lin_in, make_float3(PC_GCL[ent * 3 + 0], PC_GCL[ent * 3 + 1],
                                                                        PC_GCL[ent * 3 + 2])), v_proteger_cores);
    return lin_in;
}
// exposicao e balanco + ganhos extras por canal (B_GAIN)
static inline float3 pc_gain(const pc_vals& V, float3 lin, float3 gx) {
    int v_copia = V.copia;
    float v_copia_forca = V.copia_forca;
    float v_mix_geral = V.mix_geral;
    int v_mostrar_curva = V.mostrar_curva;
    int v_bitola = V.bitola;
    int v_iso = V.iso;
    int v_bitola_desfoque_on = V.bitola_desfoque_on;
    float v_bitola_resolucao = V.bitola_resolucao;
    float v_bitola_vinheta = V.bitola_vinheta;
    int v_mtf = V.mtf;
    float v_mtf_forca = V.mtf_forca;
    float v_mtf_camadas = V.mtf_camadas;
    int v_entrada = V.entrada;
    int v_faixa_video = V.faixa_video;
    int v_logc3_ei = V.logc3_ei;
    float v_exposicao = V.exposicao;
    float v_temperatura = V.temperatura;
    float v_tint = V.tint;
    float v_proteger_cores = V.proteger_cores;
    int v_lab_on = V.lab_on;
    int v_lab_negativo = V.lab_negativo;
    int v_lab_copia = V.lab_copia;
    float v_lab_revelacao = V.lab_revelacao;
    float v_lab_separacao = V.lab_separacao;
    float v_lab_separacao_eixo = V.lab_separacao_eixo;
    float v_lab_luz_r = V.lab_luz_r;
    float v_lab_luz_g = V.lab_luz_g;
    float v_lab_luz_b = V.lab_luz_b;
    float v_lab_densidade = V.lab_densidade;
    float v_lab_dens_r = V.lab_dens_r;
    float v_lab_dens_g = V.lab_dens_g;
    float v_lab_dens_b = V.lab_dens_b;
    float v_lab_pe = V.lab_pe;
    float v_lab_sombras_rolagem = V.lab_sombras_rolagem;
    float v_lab_luzes_rolagem = V.lab_luzes_rolagem;
    float v_lab_saturacao_filme = V.lab_saturacao_filme;
    float v_lab_saturacao = V.lab_saturacao;
    float v_lab_pele_matiz = V.lab_pele_matiz;
    float v_lab_pele_sat = V.lab_pele_sat;
    float v_lab_bypass_negativo = V.lab_bypass_negativo;
    float v_lab_bypass_copia = V.lab_bypass_copia;
    float v_lab_neutro_negativo = V.lab_neutro_negativo;
    float v_lab_neutro_copia = V.lab_neutro_copia;
    int v_lab_processo = V.lab_processo;
    float v_lab_processo_forca = V.lab_processo_forca;
    float v_lab_chave = V.lab_chave;
    float v_lab_diafonia = V.lab_diafonia;
    int v_lab_grao = V.lab_grao;
    int v_lab_grao_modelo = V.lab_grao_modelo;
    int v_cor_on = V.cor_on;
    float v_cor_forca = V.cor_forca;
    float v_contraste = V.contraste;
    float v_meio_tom = V.meio_tom;
    float v_preto = V.preto;
    float v_branco = V.branco;
    float v_rolagem_luzes = V.rolagem_luzes;
    float v_rolagem_sombras = V.rolagem_sombras;
    float v_saturacao = V.saturacao;
    float v_densidade = V.densidade;
    float v_sombras_matiz = V.sombras_matiz;
    float v_sombras_forca = V.sombras_forca;
    float v_luzes_matiz = V.luzes_matiz;
    float v_luzes_forca = V.luzes_forca;
    float v_equilibrio = V.equilibrio;
    float v_contraste_r = V.contraste_r;
    float v_contraste_g = V.contraste_g;
    float v_contraste_b = V.contraste_b;
    float v_offset_r = V.offset_r;
    float v_offset_g = V.offset_g;
    float v_offset_b = V.offset_b;
    float v_verdes_matiz = V.verdes_matiz;
    float v_azuis_matiz = V.azuis_matiz;
    float v_pele_sat = V.pele_sat;
    float v_pele_matiz = V.pele_matiz;
    float v_pele_luz = V.pele_luz;
    int v_pb = V.pb;
    int v_pb_filtro = V.pb_filtro;
    int v_virada = V.virada;
    float v_virada_forca = V.virada_forca;
    float v_envelhecimento = V.envelhecimento;
    int v_grao_on = V.grao_on;
    float v_grao_forca = V.grao_forca;
    float v_grao_tamanho = V.grao_tamanho;
    float v_grao_aspereza = V.grao_aspereza;
    float v_grao_cor = V.grao_cor;
    float v_grao_sombras = V.grao_sombras;
    float v_grao_meios = V.grao_meios;
    float v_grao_luzes = V.grao_luzes;
    int v_grao_animado = V.grao_animado;
    int v_grao_semente = V.grao_semente;
    float v_grao_maciez = V.grao_maciez;
    float v_grao_respiracao = V.grao_respiracao;
    int v_hal_on = V.hal_on;
    float v_hal_forca = V.hal_forca;
    float v_hal_raio = V.hal_raio;
    float v_hal_limiar = V.hal_limiar;
    float3 v_hal_cor = V.hal_cor;
    int v_hal_modelo = V.hal_modelo;
    int v_bloom_on = V.bloom_on;
    float v_bloom_forca = V.bloom_forca;
    float v_bloom_raio = V.bloom_raio;
    float v_bloom_limiar = V.bloom_limiar;
    float v_nevoa_forca = V.nevoa_forca;
    float v_nevoa_raio = V.nevoa_raio;
    int v_lente_on = V.lente_on;
    float v_maciez = V.maciez;
    float v_raio_maciez = V.raio_maciez;
    float v_nitidez = V.nitidez;
    float v_aberracao = V.aberracao;
    float v_distorcao = V.distorcao;
    float v_vinheta = V.vinheta;
    float v_vinheta_raio = V.vinheta_raio;
    float v_vinheta_suavidade = V.vinheta_suavidade;
    float v_vinheta_redondeza = V.vinheta_redondeza;
    int v_proj_on = V.proj_on;
    float v_tremor_x = V.tremor_x;
    float v_tremor_y = V.tremor_y;
    float v_tremor_rot = V.tremor_rot;
    float v_tremor_vel = V.tremor_vel;
    float v_cintilacao = V.cintilacao;
    float v_cintilacao_vel = V.cintilacao_vel;
    int v_desg_on = V.desg_on;
    int v_poeira_on = V.poeira_on;
    float v_poeira = V.poeira;
    float v_poeira_tamanho = V.poeira_tamanho;
    int v_poeira_tipo = V.poeira_tipo;
    int v_riscos_on = V.riscos_on;
    float v_riscos = V.riscos;
    float v_riscos_largura = V.riscos_largura;
    int v_cabelo_on = V.cabelo_on;
    float v_cabelo = V.cabelo;
    float v_cabelo_tamanho = V.cabelo_tamanho;
    int v_manchas_on = V.manchas_on;
    float v_manchas = V.manchas;
    int v_queima_on = V.queima_on;
    float v_queima = V.queima;
    int v_marcas_on = V.marcas_on;
    float v_marcas_intervalo = V.marcas_intervalo;
    int v_cor_instavel_on = V.cor_instavel_on;
    float v_cor_instavel = V.cor_instavel;
    int v_emenda_on = V.emenda_on;
    float v_emenda = V.emenda;
    int v_vazamento_on = V.vazamento_on;
    float v_vazamento = V.vazamento;
    float3 v_vazamento_cor = V.vazamento_cor;
    float v_vazamento_vel = V.vazamento_vel;
    int v_desgaste_semente = V.desgaste_semente;
    int v_mold_on = V.mold_on;
    int v_proporcao = V.proporcao;
    float v_cantos = V.cantos;
    float v_borda_suave = V.borda_suave;
    float v_borda_irregular = V.borda_irregular;
    float3 v_cor_barras = V.cor_barras;
    (void)v_copia;
    (void)v_copia_forca;
    (void)v_mix_geral;
    (void)v_mostrar_curva;
    (void)v_bitola;
    (void)v_iso;
    (void)v_bitola_desfoque_on;
    (void)v_bitola_resolucao;
    (void)v_bitola_vinheta;
    (void)v_mtf;
    (void)v_mtf_forca;
    (void)v_mtf_camadas;
    (void)v_entrada;
    (void)v_faixa_video;
    (void)v_logc3_ei;
    (void)v_exposicao;
    (void)v_temperatura;
    (void)v_tint;
    (void)v_proteger_cores;
    (void)v_lab_on;
    (void)v_lab_negativo;
    (void)v_lab_copia;
    (void)v_lab_revelacao;
    (void)v_lab_separacao;
    (void)v_lab_separacao_eixo;
    (void)v_lab_luz_r;
    (void)v_lab_luz_g;
    (void)v_lab_luz_b;
    (void)v_lab_densidade;
    (void)v_lab_dens_r;
    (void)v_lab_dens_g;
    (void)v_lab_dens_b;
    (void)v_lab_pe;
    (void)v_lab_sombras_rolagem;
    (void)v_lab_luzes_rolagem;
    (void)v_lab_saturacao_filme;
    (void)v_lab_saturacao;
    (void)v_lab_pele_matiz;
    (void)v_lab_pele_sat;
    (void)v_lab_bypass_negativo;
    (void)v_lab_bypass_copia;
    (void)v_lab_neutro_negativo;
    (void)v_lab_neutro_copia;
    (void)v_lab_processo;
    (void)v_lab_processo_forca;
    (void)v_lab_chave;
    (void)v_lab_diafonia;
    (void)v_lab_grao;
    (void)v_lab_grao_modelo;
    (void)v_cor_on;
    (void)v_cor_forca;
    (void)v_contraste;
    (void)v_meio_tom;
    (void)v_preto;
    (void)v_branco;
    (void)v_rolagem_luzes;
    (void)v_rolagem_sombras;
    (void)v_saturacao;
    (void)v_densidade;
    (void)v_sombras_matiz;
    (void)v_sombras_forca;
    (void)v_luzes_matiz;
    (void)v_luzes_forca;
    (void)v_equilibrio;
    (void)v_contraste_r;
    (void)v_contraste_g;
    (void)v_contraste_b;
    (void)v_offset_r;
    (void)v_offset_g;
    (void)v_offset_b;
    (void)v_verdes_matiz;
    (void)v_azuis_matiz;
    (void)v_pele_sat;
    (void)v_pele_matiz;
    (void)v_pele_luz;
    (void)v_pb;
    (void)v_pb_filtro;
    (void)v_virada;
    (void)v_virada_forca;
    (void)v_envelhecimento;
    (void)v_grao_on;
    (void)v_grao_forca;
    (void)v_grao_tamanho;
    (void)v_grao_aspereza;
    (void)v_grao_cor;
    (void)v_grao_sombras;
    (void)v_grao_meios;
    (void)v_grao_luzes;
    (void)v_grao_animado;
    (void)v_grao_semente;
    (void)v_grao_maciez;
    (void)v_grao_respiracao;
    (void)v_hal_on;
    (void)v_hal_forca;
    (void)v_hal_raio;
    (void)v_hal_limiar;
    (void)v_hal_cor;
    (void)v_hal_modelo;
    (void)v_bloom_on;
    (void)v_bloom_forca;
    (void)v_bloom_raio;
    (void)v_bloom_limiar;
    (void)v_nevoa_forca;
    (void)v_nevoa_raio;
    (void)v_lente_on;
    (void)v_maciez;
    (void)v_raio_maciez;
    (void)v_nitidez;
    (void)v_aberracao;
    (void)v_distorcao;
    (void)v_vinheta;
    (void)v_vinheta_raio;
    (void)v_vinheta_suavidade;
    (void)v_vinheta_redondeza;
    (void)v_proj_on;
    (void)v_tremor_x;
    (void)v_tremor_y;
    (void)v_tremor_rot;
    (void)v_tremor_vel;
    (void)v_cintilacao;
    (void)v_cintilacao_vel;
    (void)v_desg_on;
    (void)v_poeira_on;
    (void)v_poeira;
    (void)v_poeira_tamanho;
    (void)v_poeira_tipo;
    (void)v_riscos_on;
    (void)v_riscos;
    (void)v_riscos_largura;
    (void)v_cabelo_on;
    (void)v_cabelo;
    (void)v_cabelo_tamanho;
    (void)v_manchas_on;
    (void)v_manchas;
    (void)v_queima_on;
    (void)v_queima;
    (void)v_marcas_on;
    (void)v_marcas_intervalo;
    (void)v_cor_instavel_on;
    (void)v_cor_instavel;
    (void)v_emenda_on;
    (void)v_emenda;
    (void)v_vazamento_on;
    (void)v_vazamento;
    (void)v_vazamento_cor;
    (void)v_vazamento_vel;
    (void)v_desgaste_semente;
    (void)v_mold_on;
    (void)v_proporcao;
    (void)v_cantos;
    (void)v_borda_suave;
    (void)v_borda_irregular;
    (void)v_cor_barras;

    float tmp = v_temperatura / 100.0f;
    float tnt = v_tint / 100.0f;
    lin = make_float3(_fmaxf(lin.x, 0.0f) * _exp2f(v_exposicao + 0.28f * tmp + 0.08f * tnt + gx.x),
                      _fmaxf(lin.y, 0.0f) * _exp2f(v_exposicao - 0.22f * tnt + gx.y),
                      _fmaxf(lin.z, 0.0f) * _exp2f(v_exposicao - 0.38f * tmp + 0.08f * tnt + gx.z));
    return lin;
}
// colorPipe do app: laboratorio + look + copia + envelhecimento (B_LAB + B_LOOK)
static inline float3 pc_colorpipe(const pc_vals& V, float3 lin) {
    int v_copia = V.copia;
    float v_copia_forca = V.copia_forca;
    float v_mix_geral = V.mix_geral;
    int v_mostrar_curva = V.mostrar_curva;
    int v_bitola = V.bitola;
    int v_iso = V.iso;
    int v_bitola_desfoque_on = V.bitola_desfoque_on;
    float v_bitola_resolucao = V.bitola_resolucao;
    float v_bitola_vinheta = V.bitola_vinheta;
    int v_mtf = V.mtf;
    float v_mtf_forca = V.mtf_forca;
    float v_mtf_camadas = V.mtf_camadas;
    int v_entrada = V.entrada;
    int v_faixa_video = V.faixa_video;
    int v_logc3_ei = V.logc3_ei;
    float v_exposicao = V.exposicao;
    float v_temperatura = V.temperatura;
    float v_tint = V.tint;
    float v_proteger_cores = V.proteger_cores;
    int v_lab_on = V.lab_on;
    int v_lab_negativo = V.lab_negativo;
    int v_lab_copia = V.lab_copia;
    float v_lab_revelacao = V.lab_revelacao;
    float v_lab_separacao = V.lab_separacao;
    float v_lab_separacao_eixo = V.lab_separacao_eixo;
    float v_lab_luz_r = V.lab_luz_r;
    float v_lab_luz_g = V.lab_luz_g;
    float v_lab_luz_b = V.lab_luz_b;
    float v_lab_densidade = V.lab_densidade;
    float v_lab_dens_r = V.lab_dens_r;
    float v_lab_dens_g = V.lab_dens_g;
    float v_lab_dens_b = V.lab_dens_b;
    float v_lab_pe = V.lab_pe;
    float v_lab_sombras_rolagem = V.lab_sombras_rolagem;
    float v_lab_luzes_rolagem = V.lab_luzes_rolagem;
    float v_lab_saturacao_filme = V.lab_saturacao_filme;
    float v_lab_saturacao = V.lab_saturacao;
    float v_lab_pele_matiz = V.lab_pele_matiz;
    float v_lab_pele_sat = V.lab_pele_sat;
    float v_lab_bypass_negativo = V.lab_bypass_negativo;
    float v_lab_bypass_copia = V.lab_bypass_copia;
    float v_lab_neutro_negativo = V.lab_neutro_negativo;
    float v_lab_neutro_copia = V.lab_neutro_copia;
    int v_lab_processo = V.lab_processo;
    float v_lab_processo_forca = V.lab_processo_forca;
    float v_lab_chave = V.lab_chave;
    float v_lab_diafonia = V.lab_diafonia;
    int v_lab_grao = V.lab_grao;
    int v_lab_grao_modelo = V.lab_grao_modelo;
    int v_cor_on = V.cor_on;
    float v_cor_forca = V.cor_forca;
    float v_contraste = V.contraste;
    float v_meio_tom = V.meio_tom;
    float v_preto = V.preto;
    float v_branco = V.branco;
    float v_rolagem_luzes = V.rolagem_luzes;
    float v_rolagem_sombras = V.rolagem_sombras;
    float v_saturacao = V.saturacao;
    float v_densidade = V.densidade;
    float v_sombras_matiz = V.sombras_matiz;
    float v_sombras_forca = V.sombras_forca;
    float v_luzes_matiz = V.luzes_matiz;
    float v_luzes_forca = V.luzes_forca;
    float v_equilibrio = V.equilibrio;
    float v_contraste_r = V.contraste_r;
    float v_contraste_g = V.contraste_g;
    float v_contraste_b = V.contraste_b;
    float v_offset_r = V.offset_r;
    float v_offset_g = V.offset_g;
    float v_offset_b = V.offset_b;
    float v_verdes_matiz = V.verdes_matiz;
    float v_azuis_matiz = V.azuis_matiz;
    float v_pele_sat = V.pele_sat;
    float v_pele_matiz = V.pele_matiz;
    float v_pele_luz = V.pele_luz;
    int v_pb = V.pb;
    int v_pb_filtro = V.pb_filtro;
    int v_virada = V.virada;
    float v_virada_forca = V.virada_forca;
    float v_envelhecimento = V.envelhecimento;
    int v_grao_on = V.grao_on;
    float v_grao_forca = V.grao_forca;
    float v_grao_tamanho = V.grao_tamanho;
    float v_grao_aspereza = V.grao_aspereza;
    float v_grao_cor = V.grao_cor;
    float v_grao_sombras = V.grao_sombras;
    float v_grao_meios = V.grao_meios;
    float v_grao_luzes = V.grao_luzes;
    int v_grao_animado = V.grao_animado;
    int v_grao_semente = V.grao_semente;
    float v_grao_maciez = V.grao_maciez;
    float v_grao_respiracao = V.grao_respiracao;
    int v_hal_on = V.hal_on;
    float v_hal_forca = V.hal_forca;
    float v_hal_raio = V.hal_raio;
    float v_hal_limiar = V.hal_limiar;
    float3 v_hal_cor = V.hal_cor;
    int v_hal_modelo = V.hal_modelo;
    int v_bloom_on = V.bloom_on;
    float v_bloom_forca = V.bloom_forca;
    float v_bloom_raio = V.bloom_raio;
    float v_bloom_limiar = V.bloom_limiar;
    float v_nevoa_forca = V.nevoa_forca;
    float v_nevoa_raio = V.nevoa_raio;
    int v_lente_on = V.lente_on;
    float v_maciez = V.maciez;
    float v_raio_maciez = V.raio_maciez;
    float v_nitidez = V.nitidez;
    float v_aberracao = V.aberracao;
    float v_distorcao = V.distorcao;
    float v_vinheta = V.vinheta;
    float v_vinheta_raio = V.vinheta_raio;
    float v_vinheta_suavidade = V.vinheta_suavidade;
    float v_vinheta_redondeza = V.vinheta_redondeza;
    int v_proj_on = V.proj_on;
    float v_tremor_x = V.tremor_x;
    float v_tremor_y = V.tremor_y;
    float v_tremor_rot = V.tremor_rot;
    float v_tremor_vel = V.tremor_vel;
    float v_cintilacao = V.cintilacao;
    float v_cintilacao_vel = V.cintilacao_vel;
    int v_desg_on = V.desg_on;
    int v_poeira_on = V.poeira_on;
    float v_poeira = V.poeira;
    float v_poeira_tamanho = V.poeira_tamanho;
    int v_poeira_tipo = V.poeira_tipo;
    int v_riscos_on = V.riscos_on;
    float v_riscos = V.riscos;
    float v_riscos_largura = V.riscos_largura;
    int v_cabelo_on = V.cabelo_on;
    float v_cabelo = V.cabelo;
    float v_cabelo_tamanho = V.cabelo_tamanho;
    int v_manchas_on = V.manchas_on;
    float v_manchas = V.manchas;
    int v_queima_on = V.queima_on;
    float v_queima = V.queima;
    int v_marcas_on = V.marcas_on;
    float v_marcas_intervalo = V.marcas_intervalo;
    int v_cor_instavel_on = V.cor_instavel_on;
    float v_cor_instavel = V.cor_instavel;
    int v_emenda_on = V.emenda_on;
    float v_emenda = V.emenda;
    int v_vazamento_on = V.vazamento_on;
    float v_vazamento = V.vazamento;
    float3 v_vazamento_cor = V.vazamento_cor;
    float v_vazamento_vel = V.vazamento_vel;
    int v_desgaste_semente = V.desgaste_semente;
    int v_mold_on = V.mold_on;
    int v_proporcao = V.proporcao;
    float v_cantos = V.cantos;
    float v_borda_suave = V.borda_suave;
    float v_borda_irregular = V.borda_irregular;
    float3 v_cor_barras = V.cor_barras;
    (void)v_copia;
    (void)v_copia_forca;
    (void)v_mix_geral;
    (void)v_mostrar_curva;
    (void)v_bitola;
    (void)v_iso;
    (void)v_bitola_desfoque_on;
    (void)v_bitola_resolucao;
    (void)v_bitola_vinheta;
    (void)v_mtf;
    (void)v_mtf_forca;
    (void)v_mtf_camadas;
    (void)v_entrada;
    (void)v_faixa_video;
    (void)v_logc3_ei;
    (void)v_exposicao;
    (void)v_temperatura;
    (void)v_tint;
    (void)v_proteger_cores;
    (void)v_lab_on;
    (void)v_lab_negativo;
    (void)v_lab_copia;
    (void)v_lab_revelacao;
    (void)v_lab_separacao;
    (void)v_lab_separacao_eixo;
    (void)v_lab_luz_r;
    (void)v_lab_luz_g;
    (void)v_lab_luz_b;
    (void)v_lab_densidade;
    (void)v_lab_dens_r;
    (void)v_lab_dens_g;
    (void)v_lab_dens_b;
    (void)v_lab_pe;
    (void)v_lab_sombras_rolagem;
    (void)v_lab_luzes_rolagem;
    (void)v_lab_saturacao_filme;
    (void)v_lab_saturacao;
    (void)v_lab_pele_matiz;
    (void)v_lab_pele_sat;
    (void)v_lab_bypass_negativo;
    (void)v_lab_bypass_copia;
    (void)v_lab_neutro_negativo;
    (void)v_lab_neutro_copia;
    (void)v_lab_processo;
    (void)v_lab_processo_forca;
    (void)v_lab_chave;
    (void)v_lab_diafonia;
    (void)v_lab_grao;
    (void)v_lab_grao_modelo;
    (void)v_cor_on;
    (void)v_cor_forca;
    (void)v_contraste;
    (void)v_meio_tom;
    (void)v_preto;
    (void)v_branco;
    (void)v_rolagem_luzes;
    (void)v_rolagem_sombras;
    (void)v_saturacao;
    (void)v_densidade;
    (void)v_sombras_matiz;
    (void)v_sombras_forca;
    (void)v_luzes_matiz;
    (void)v_luzes_forca;
    (void)v_equilibrio;
    (void)v_contraste_r;
    (void)v_contraste_g;
    (void)v_contraste_b;
    (void)v_offset_r;
    (void)v_offset_g;
    (void)v_offset_b;
    (void)v_verdes_matiz;
    (void)v_azuis_matiz;
    (void)v_pele_sat;
    (void)v_pele_matiz;
    (void)v_pele_luz;
    (void)v_pb;
    (void)v_pb_filtro;
    (void)v_virada;
    (void)v_virada_forca;
    (void)v_envelhecimento;
    (void)v_grao_on;
    (void)v_grao_forca;
    (void)v_grao_tamanho;
    (void)v_grao_aspereza;
    (void)v_grao_cor;
    (void)v_grao_sombras;
    (void)v_grao_meios;
    (void)v_grao_luzes;
    (void)v_grao_animado;
    (void)v_grao_semente;
    (void)v_grao_maciez;
    (void)v_grao_respiracao;
    (void)v_hal_on;
    (void)v_hal_forca;
    (void)v_hal_raio;
    (void)v_hal_limiar;
    (void)v_hal_cor;
    (void)v_hal_modelo;
    (void)v_bloom_on;
    (void)v_bloom_forca;
    (void)v_bloom_raio;
    (void)v_bloom_limiar;
    (void)v_nevoa_forca;
    (void)v_nevoa_raio;
    (void)v_lente_on;
    (void)v_maciez;
    (void)v_raio_maciez;
    (void)v_nitidez;
    (void)v_aberracao;
    (void)v_distorcao;
    (void)v_vinheta;
    (void)v_vinheta_raio;
    (void)v_vinheta_suavidade;
    (void)v_vinheta_redondeza;
    (void)v_proj_on;
    (void)v_tremor_x;
    (void)v_tremor_y;
    (void)v_tremor_rot;
    (void)v_tremor_vel;
    (void)v_cintilacao;
    (void)v_cintilacao_vel;
    (void)v_desg_on;
    (void)v_poeira_on;
    (void)v_poeira;
    (void)v_poeira_tamanho;
    (void)v_poeira_tipo;
    (void)v_riscos_on;
    (void)v_riscos;
    (void)v_riscos_largura;
    (void)v_cabelo_on;
    (void)v_cabelo;
    (void)v_cabelo_tamanho;
    (void)v_manchas_on;
    (void)v_manchas;
    (void)v_queima_on;
    (void)v_queima;
    (void)v_marcas_on;
    (void)v_marcas_intervalo;
    (void)v_cor_instavel_on;
    (void)v_cor_instavel;
    (void)v_emenda_on;
    (void)v_emenda;
    (void)v_vazamento_on;
    (void)v_vazamento;
    (void)v_vazamento_cor;
    (void)v_vazamento_vel;
    (void)v_desgaste_semente;
    (void)v_mold_on;
    (void)v_proporcao;
    (void)v_cantos;
    (void)v_borda_suave;
    (void)v_borda_irregular;
    (void)v_cor_barras;

    if (v_lab_on == 1) {
        float3 gn = pc_s3(0.0f);
        float3 ga = pc_s3(0.0f);  // 1.6: grao fisico (fracao por camada; zero = desligado), posicao e semente
        float4 gq = make_float4(0.0f, 0.0f, 1.0f, 0.0f);
        int gs = 0;
        int ni = v_lab_negativo * 20;
        int lp = v_lab_copia;
        int pk = v_lab_processo * 40;
        float kind = PC_PROC[pk];
        float forca = v_lab_processo_forca;
        float3 lights = make_float3(PC_LAB_POINT * (v_lab_luz_r + v_lab_densidade),
                                    PC_LAB_POINT * (v_lab_luz_g + v_lab_densidade),
                                    PC_LAB_POINT * (v_lab_luz_b + v_lab_densidade));
        float3 key = pc_s3(0.0f);
        if (kind == 1.0f) {
            key = pc_s3(0.8f * forca / 3.0f);
            if (PC_LPR[lp * 17] == 0.0f) lp = PC_LAB_2383;
        }
        if (v_lab_bypass_copia > 0.0f && PC_LPR[lp * 17] > 0.5f) key = key + pc_s3(0.8f * v_lab_bypass_copia / 3.0f);
        // separacao de cores (Hue Split) na densidade: eixos u (polo quente) e v (perpendicular)
        int split_on = (v_lab_separacao > 0.0f) ? 1 : 0;
        float3 hu = pc_hue_rgb(v_lab_separacao_eixo);
        hu = hu - pc_s3((hu.x + hu.y + hu.z) / 3.0f);
        hu = hu * (1.0f / _sqrtf(pc_dot3(hu, hu)));
        float3 hv = make_float3(hu.z - hu.y, hu.x - hu.z, hu.y - hu.x) * 0.57735027f;
        hv = hv * (1.0f / _sqrtf(pc_dot3(hv, hv)));
        float sa = PC_SPLIT_A * v_lab_separacao;
        float sb = PC_SPLIT_B * v_lab_separacao;
        float toe = _exp2f(-0.6f * v_lab_pe);
        float nn = v_lab_neutro_negativo;
        float np = v_lab_neutro_copia;
        int lq = lp * 17;
        float2 ab = pc_ii_coefs(PC_NEG[ni + 19], v_lab_saturacao_filme, v_lab_bypass_negativo);
        float3 la = pc_lab_path(lin,
            make_float3(PC_NEG[ni + 0], PC_NEG[ni + 1], PC_NEG[ni + 2]),
            make_float3(PC_NEG[ni + 3], PC_NEG[ni + 4], PC_NEG[ni + 5]),
            make_float3(PC_NEG[ni + 6], PC_NEG[ni + 7], PC_NEG[ni + 8]),
            pc_neutral3(make_float3(PC_NEG[ni + 9], PC_NEG[ni + 10], PC_NEG[ni + 11]), nn),
            pc_neutral3(make_float3(PC_NEG[ni + 12], PC_NEG[ni + 13], PC_NEG[ni + 14]), nn),
            pc_neutral3(make_float3(PC_NEG[ni + 15], PC_NEG[ni + 16], PC_NEG[ni + 17]), nn), PC_NEG[ni + 18],
            pc_ii_row(make_float3(1.0f, 0.0f, 0.0f), hu.x, hv.x, hu, hv, sa, sb, ab.x, ab.y, split_on),
            pc_ii_row(make_float3(0.0f, 1.0f, 0.0f), hu.y, hv.y, hu, hv, sa, sb, ab.x, ab.y, split_on),
            pc_ii_row(make_float3(0.0f, 0.0f, 1.0f), hu.z, hv.z, hu, hv, sa, sb, ab.x, ab.y, split_on),
            (PC_LPR[lq] > 0.5f) ? 1 : 0,
            pc_neutral3(make_float3(PC_LPR[lq + 1], PC_LPR[lq + 2], PC_LPR[lq + 3]), np),
            pc_neutral3(make_float3(PC_LPR[lq + 4], PC_LPR[lq + 5], PC_LPR[lq + 6]), np) * toe, PC_LPR[lq + 7],
            make_float3(PC_LPR[lq + 8], PC_LPR[lq + 9], PC_LPR[lq + 10]),
            make_float3(PC_LPR[lq + 11], PC_LPR[lq + 12], PC_LPR[lq + 13]),
            make_float3(PC_LPR[lq + 14], PC_LPR[lq + 15], PC_LPR[lq + 16]),
            key, v_lab_revelacao, v_lab_diafonia, lights, gn, ga, gq, gs);
        if (kind == 2.0f) {
            int b = pk + 1;
            float2 bb = pc_ii_coefs(PC_PROC[b + 19], v_lab_saturacao_filme, v_lab_bypass_negativo);
            float3 lb = pc_lab_path(lin,
                make_float3(PC_PROC[b + 0], PC_PROC[b + 1], PC_PROC[b + 2]),
                make_float3(PC_PROC[b + 3], PC_PROC[b + 4], PC_PROC[b + 5]),
                make_float3(PC_PROC[b + 6], PC_PROC[b + 7], PC_PROC[b + 8]),
                pc_neutral3(make_float3(PC_PROC[b + 9], PC_PROC[b + 10], PC_PROC[b + 11]), nn),
                pc_neutral3(make_float3(PC_PROC[b + 12], PC_PROC[b + 13], PC_PROC[b + 14]), nn),
                pc_neutral3(make_float3(PC_PROC[b + 15], PC_PROC[b + 16], PC_PROC[b + 17]), nn), PC_PROC[b + 18],
                pc_ii_row(make_float3(1.0f, 0.0f, 0.0f), hu.x, hv.x, hu, hv, sa, sb, bb.x, bb.y, split_on),
                pc_ii_row(make_float3(0.0f, 1.0f, 0.0f), hu.y, hv.y, hu, hv, sa, sb, bb.x, bb.y, split_on),
                pc_ii_row(make_float3(0.0f, 0.0f, 1.0f), hu.z, hv.z, hu, hv, sa, sb, bb.x, bb.y, split_on),
                1,
                pc_neutral3(make_float3(PC_PROC[b + 20], PC_PROC[b + 21], PC_PROC[b + 22]), np),
                pc_neutral3(make_float3(PC_PROC[b + 23], PC_PROC[b + 24], PC_PROC[b + 25]), np) * toe,
                PC_PROC[b + 26],
                make_float3(PC_PROC[b + 27], PC_PROC[b + 28], PC_PROC[b + 29]),
                make_float3(PC_PROC[b + 30], PC_PROC[b + 31], PC_PROC[b + 32]),
                make_float3(PC_PROC[b + 33], PC_PROC[b + 34], PC_PROC[b + 35]),
                make_float3(PC_PROC[b + 36], PC_PROC[b + 37], PC_PROC[b + 38]) * v_lab_chave,
                v_lab_revelacao, v_lab_diafonia, lights, gn, ga, gq, gs);
            la = pc_lerp3(la, lb, forca);
        }
        la = pc_lab_post(la, v_lab_luzes_rolagem, v_lab_sombras_rolagem, v_lab_saturacao,
                         make_float3(v_lab_dens_r - 1.0f, v_lab_dens_g - 1.0f, v_lab_dens_b - 1.0f),
                         v_lab_pele_matiz * 0.0174532925f, v_lab_pele_sat);
        lin = pc_code_to_lin(la);
    }

    float3 neutral = pc_lin_to_code(lin);
    float3 y = neutral;
    if (v_cor_on == 1) {
        int fi = v_pb_filtro;
        int vi = v_virada;
        float tone_amt = (PC_TONE_ON[vi] == 1 && v_pb == 1) ? v_virada_forca : 0.0f;
        float3 film = pc_film_look(lin, v_pb, make_float3(PC_BWW[fi * 3], PC_BWW[fi * 3 + 1], PC_BWW[fi * 3 + 2]),
            v_saturacao, make_float3(v_contraste_r, v_contraste_g, v_contraste_b),
            make_float3(v_offset_r, v_offset_g, v_offset_b), PC_DSLOPE * v_contraste, v_meio_tom, v_preto,
            _fmaxf(v_branco, v_meio_tom + 0.05f), pc_soft_p(v_rolagem_luzes), pc_soft_p(v_rolagem_sombras),
            v_densidade, v_verdes_matiz * 0.0174532925f, v_azuis_matiz * 0.0174532925f, v_pele_sat,
            v_pele_matiz * 0.0174532925f, v_pele_luz,
            pc_hsv_tint(v_sombras_matiz, v_sombras_forca), pc_hsv_tint(v_luzes_matiz, v_luzes_forca), v_equilibrio,
            tone_amt, make_float3(PC_TONE[vi * 6], PC_TONE[vi * 6 + 1], PC_TONE[vi * 6 + 2]),
            make_float3(PC_TONE[vi * 6 + 3], PC_TONE[vi * 6 + 4], PC_TONE[vi * 6 + 5]));
        y = pc_lerp3(neutral, film, v_cor_forca);
    }
    int pi = v_copia;
    if (PC_PR_ON[pi] == 1) {
        float3 pr = pc_print_stage(y, PC_PR[pi * 12 + 0],
            make_float3(PC_PR[pi * 12 + 1], PC_PR[pi * 12 + 2], PC_PR[pi * 12 + 3]),
            make_float3(PC_PR[pi * 12 + 4], PC_PR[pi * 12 + 5], PC_PR[pi * 12 + 6]),
            PC_PR[pi * 12 + 7], PC_PR[pi * 12 + 8], PC_PR[pi * 12 + 9], PC_PR[pi * 12 + 10],
            pc_soft_p(PC_PR_SOFT[pi * 2]), pc_soft_p(PC_PR_SOFT[pi * 2 + 1]));
        y = pc_lerp3(y, pr, v_copia_forca);
    }
    float age = (v_cor_on == 1) ? v_envelhecimento : 0.0f;
    if (age > 0.0f) y = pc_lerp3(y, pc_aged(y), age);
    return y;
}
// colorPipe com o grao no negativo (grao.negative_grain)
static inline float3 pc_colorpipe_ng(const pc_vals& V, float3 lin, float3 gn_in) {
    int v_copia = V.copia;
    float v_copia_forca = V.copia_forca;
    float v_mix_geral = V.mix_geral;
    int v_mostrar_curva = V.mostrar_curva;
    int v_bitola = V.bitola;
    int v_iso = V.iso;
    int v_bitola_desfoque_on = V.bitola_desfoque_on;
    float v_bitola_resolucao = V.bitola_resolucao;
    float v_bitola_vinheta = V.bitola_vinheta;
    int v_mtf = V.mtf;
    float v_mtf_forca = V.mtf_forca;
    float v_mtf_camadas = V.mtf_camadas;
    int v_entrada = V.entrada;
    int v_faixa_video = V.faixa_video;
    int v_logc3_ei = V.logc3_ei;
    float v_exposicao = V.exposicao;
    float v_temperatura = V.temperatura;
    float v_tint = V.tint;
    float v_proteger_cores = V.proteger_cores;
    int v_lab_on = V.lab_on;
    int v_lab_negativo = V.lab_negativo;
    int v_lab_copia = V.lab_copia;
    float v_lab_revelacao = V.lab_revelacao;
    float v_lab_separacao = V.lab_separacao;
    float v_lab_separacao_eixo = V.lab_separacao_eixo;
    float v_lab_luz_r = V.lab_luz_r;
    float v_lab_luz_g = V.lab_luz_g;
    float v_lab_luz_b = V.lab_luz_b;
    float v_lab_densidade = V.lab_densidade;
    float v_lab_dens_r = V.lab_dens_r;
    float v_lab_dens_g = V.lab_dens_g;
    float v_lab_dens_b = V.lab_dens_b;
    float v_lab_pe = V.lab_pe;
    float v_lab_sombras_rolagem = V.lab_sombras_rolagem;
    float v_lab_luzes_rolagem = V.lab_luzes_rolagem;
    float v_lab_saturacao_filme = V.lab_saturacao_filme;
    float v_lab_saturacao = V.lab_saturacao;
    float v_lab_pele_matiz = V.lab_pele_matiz;
    float v_lab_pele_sat = V.lab_pele_sat;
    float v_lab_bypass_negativo = V.lab_bypass_negativo;
    float v_lab_bypass_copia = V.lab_bypass_copia;
    float v_lab_neutro_negativo = V.lab_neutro_negativo;
    float v_lab_neutro_copia = V.lab_neutro_copia;
    int v_lab_processo = V.lab_processo;
    float v_lab_processo_forca = V.lab_processo_forca;
    float v_lab_chave = V.lab_chave;
    float v_lab_diafonia = V.lab_diafonia;
    int v_lab_grao = V.lab_grao;
    int v_lab_grao_modelo = V.lab_grao_modelo;
    int v_cor_on = V.cor_on;
    float v_cor_forca = V.cor_forca;
    float v_contraste = V.contraste;
    float v_meio_tom = V.meio_tom;
    float v_preto = V.preto;
    float v_branco = V.branco;
    float v_rolagem_luzes = V.rolagem_luzes;
    float v_rolagem_sombras = V.rolagem_sombras;
    float v_saturacao = V.saturacao;
    float v_densidade = V.densidade;
    float v_sombras_matiz = V.sombras_matiz;
    float v_sombras_forca = V.sombras_forca;
    float v_luzes_matiz = V.luzes_matiz;
    float v_luzes_forca = V.luzes_forca;
    float v_equilibrio = V.equilibrio;
    float v_contraste_r = V.contraste_r;
    float v_contraste_g = V.contraste_g;
    float v_contraste_b = V.contraste_b;
    float v_offset_r = V.offset_r;
    float v_offset_g = V.offset_g;
    float v_offset_b = V.offset_b;
    float v_verdes_matiz = V.verdes_matiz;
    float v_azuis_matiz = V.azuis_matiz;
    float v_pele_sat = V.pele_sat;
    float v_pele_matiz = V.pele_matiz;
    float v_pele_luz = V.pele_luz;
    int v_pb = V.pb;
    int v_pb_filtro = V.pb_filtro;
    int v_virada = V.virada;
    float v_virada_forca = V.virada_forca;
    float v_envelhecimento = V.envelhecimento;
    int v_grao_on = V.grao_on;
    float v_grao_forca = V.grao_forca;
    float v_grao_tamanho = V.grao_tamanho;
    float v_grao_aspereza = V.grao_aspereza;
    float v_grao_cor = V.grao_cor;
    float v_grao_sombras = V.grao_sombras;
    float v_grao_meios = V.grao_meios;
    float v_grao_luzes = V.grao_luzes;
    int v_grao_animado = V.grao_animado;
    int v_grao_semente = V.grao_semente;
    float v_grao_maciez = V.grao_maciez;
    float v_grao_respiracao = V.grao_respiracao;
    int v_hal_on = V.hal_on;
    float v_hal_forca = V.hal_forca;
    float v_hal_raio = V.hal_raio;
    float v_hal_limiar = V.hal_limiar;
    float3 v_hal_cor = V.hal_cor;
    int v_hal_modelo = V.hal_modelo;
    int v_bloom_on = V.bloom_on;
    float v_bloom_forca = V.bloom_forca;
    float v_bloom_raio = V.bloom_raio;
    float v_bloom_limiar = V.bloom_limiar;
    float v_nevoa_forca = V.nevoa_forca;
    float v_nevoa_raio = V.nevoa_raio;
    int v_lente_on = V.lente_on;
    float v_maciez = V.maciez;
    float v_raio_maciez = V.raio_maciez;
    float v_nitidez = V.nitidez;
    float v_aberracao = V.aberracao;
    float v_distorcao = V.distorcao;
    float v_vinheta = V.vinheta;
    float v_vinheta_raio = V.vinheta_raio;
    float v_vinheta_suavidade = V.vinheta_suavidade;
    float v_vinheta_redondeza = V.vinheta_redondeza;
    int v_proj_on = V.proj_on;
    float v_tremor_x = V.tremor_x;
    float v_tremor_y = V.tremor_y;
    float v_tremor_rot = V.tremor_rot;
    float v_tremor_vel = V.tremor_vel;
    float v_cintilacao = V.cintilacao;
    float v_cintilacao_vel = V.cintilacao_vel;
    int v_desg_on = V.desg_on;
    int v_poeira_on = V.poeira_on;
    float v_poeira = V.poeira;
    float v_poeira_tamanho = V.poeira_tamanho;
    int v_poeira_tipo = V.poeira_tipo;
    int v_riscos_on = V.riscos_on;
    float v_riscos = V.riscos;
    float v_riscos_largura = V.riscos_largura;
    int v_cabelo_on = V.cabelo_on;
    float v_cabelo = V.cabelo;
    float v_cabelo_tamanho = V.cabelo_tamanho;
    int v_manchas_on = V.manchas_on;
    float v_manchas = V.manchas;
    int v_queima_on = V.queima_on;
    float v_queima = V.queima;
    int v_marcas_on = V.marcas_on;
    float v_marcas_intervalo = V.marcas_intervalo;
    int v_cor_instavel_on = V.cor_instavel_on;
    float v_cor_instavel = V.cor_instavel;
    int v_emenda_on = V.emenda_on;
    float v_emenda = V.emenda;
    int v_vazamento_on = V.vazamento_on;
    float v_vazamento = V.vazamento;
    float3 v_vazamento_cor = V.vazamento_cor;
    float v_vazamento_vel = V.vazamento_vel;
    int v_desgaste_semente = V.desgaste_semente;
    int v_mold_on = V.mold_on;
    int v_proporcao = V.proporcao;
    float v_cantos = V.cantos;
    float v_borda_suave = V.borda_suave;
    float v_borda_irregular = V.borda_irregular;
    float3 v_cor_barras = V.cor_barras;
    (void)v_copia;
    (void)v_copia_forca;
    (void)v_mix_geral;
    (void)v_mostrar_curva;
    (void)v_bitola;
    (void)v_iso;
    (void)v_bitola_desfoque_on;
    (void)v_bitola_resolucao;
    (void)v_bitola_vinheta;
    (void)v_mtf;
    (void)v_mtf_forca;
    (void)v_mtf_camadas;
    (void)v_entrada;
    (void)v_faixa_video;
    (void)v_logc3_ei;
    (void)v_exposicao;
    (void)v_temperatura;
    (void)v_tint;
    (void)v_proteger_cores;
    (void)v_lab_on;
    (void)v_lab_negativo;
    (void)v_lab_copia;
    (void)v_lab_revelacao;
    (void)v_lab_separacao;
    (void)v_lab_separacao_eixo;
    (void)v_lab_luz_r;
    (void)v_lab_luz_g;
    (void)v_lab_luz_b;
    (void)v_lab_densidade;
    (void)v_lab_dens_r;
    (void)v_lab_dens_g;
    (void)v_lab_dens_b;
    (void)v_lab_pe;
    (void)v_lab_sombras_rolagem;
    (void)v_lab_luzes_rolagem;
    (void)v_lab_saturacao_filme;
    (void)v_lab_saturacao;
    (void)v_lab_pele_matiz;
    (void)v_lab_pele_sat;
    (void)v_lab_bypass_negativo;
    (void)v_lab_bypass_copia;
    (void)v_lab_neutro_negativo;
    (void)v_lab_neutro_copia;
    (void)v_lab_processo;
    (void)v_lab_processo_forca;
    (void)v_lab_chave;
    (void)v_lab_diafonia;
    (void)v_lab_grao;
    (void)v_lab_grao_modelo;
    (void)v_cor_on;
    (void)v_cor_forca;
    (void)v_contraste;
    (void)v_meio_tom;
    (void)v_preto;
    (void)v_branco;
    (void)v_rolagem_luzes;
    (void)v_rolagem_sombras;
    (void)v_saturacao;
    (void)v_densidade;
    (void)v_sombras_matiz;
    (void)v_sombras_forca;
    (void)v_luzes_matiz;
    (void)v_luzes_forca;
    (void)v_equilibrio;
    (void)v_contraste_r;
    (void)v_contraste_g;
    (void)v_contraste_b;
    (void)v_offset_r;
    (void)v_offset_g;
    (void)v_offset_b;
    (void)v_verdes_matiz;
    (void)v_azuis_matiz;
    (void)v_pele_sat;
    (void)v_pele_matiz;
    (void)v_pele_luz;
    (void)v_pb;
    (void)v_pb_filtro;
    (void)v_virada;
    (void)v_virada_forca;
    (void)v_envelhecimento;
    (void)v_grao_on;
    (void)v_grao_forca;
    (void)v_grao_tamanho;
    (void)v_grao_aspereza;
    (void)v_grao_cor;
    (void)v_grao_sombras;
    (void)v_grao_meios;
    (void)v_grao_luzes;
    (void)v_grao_animado;
    (void)v_grao_semente;
    (void)v_grao_maciez;
    (void)v_grao_respiracao;
    (void)v_hal_on;
    (void)v_hal_forca;
    (void)v_hal_raio;
    (void)v_hal_limiar;
    (void)v_hal_cor;
    (void)v_hal_modelo;
    (void)v_bloom_on;
    (void)v_bloom_forca;
    (void)v_bloom_raio;
    (void)v_bloom_limiar;
    (void)v_nevoa_forca;
    (void)v_nevoa_raio;
    (void)v_lente_on;
    (void)v_maciez;
    (void)v_raio_maciez;
    (void)v_nitidez;
    (void)v_aberracao;
    (void)v_distorcao;
    (void)v_vinheta;
    (void)v_vinheta_raio;
    (void)v_vinheta_suavidade;
    (void)v_vinheta_redondeza;
    (void)v_proj_on;
    (void)v_tremor_x;
    (void)v_tremor_y;
    (void)v_tremor_rot;
    (void)v_tremor_vel;
    (void)v_cintilacao;
    (void)v_cintilacao_vel;
    (void)v_desg_on;
    (void)v_poeira_on;
    (void)v_poeira;
    (void)v_poeira_tamanho;
    (void)v_poeira_tipo;
    (void)v_riscos_on;
    (void)v_riscos;
    (void)v_riscos_largura;
    (void)v_cabelo_on;
    (void)v_cabelo;
    (void)v_cabelo_tamanho;
    (void)v_manchas_on;
    (void)v_manchas;
    (void)v_queima_on;
    (void)v_queima;
    (void)v_marcas_on;
    (void)v_marcas_intervalo;
    (void)v_cor_instavel_on;
    (void)v_cor_instavel;
    (void)v_emenda_on;
    (void)v_emenda;
    (void)v_vazamento_on;
    (void)v_vazamento;
    (void)v_vazamento_cor;
    (void)v_vazamento_vel;
    (void)v_desgaste_semente;
    (void)v_mold_on;
    (void)v_proporcao;
    (void)v_cantos;
    (void)v_borda_suave;
    (void)v_borda_irregular;
    (void)v_cor_barras;

    if (v_lab_on == 1) {
        float3 gn = pc_s3(0.0f);
        float3 ga = pc_s3(0.0f);  // 1.6: grao fisico (fracao por camada; zero = desligado), posicao e semente
        float4 gq = make_float4(0.0f, 0.0f, 1.0f, 0.0f);
        int gs = 0;
        gn = gn_in;
        int ni = v_lab_negativo * 20;
        int lp = v_lab_copia;
        int pk = v_lab_processo * 40;
        float kind = PC_PROC[pk];
        float forca = v_lab_processo_forca;
        float3 lights = make_float3(PC_LAB_POINT * (v_lab_luz_r + v_lab_densidade),
                                    PC_LAB_POINT * (v_lab_luz_g + v_lab_densidade),
                                    PC_LAB_POINT * (v_lab_luz_b + v_lab_densidade));
        float3 key = pc_s3(0.0f);
        if (kind == 1.0f) {
            key = pc_s3(0.8f * forca / 3.0f);
            if (PC_LPR[lp * 17] == 0.0f) lp = PC_LAB_2383;
        }
        if (v_lab_bypass_copia > 0.0f && PC_LPR[lp * 17] > 0.5f) key = key + pc_s3(0.8f * v_lab_bypass_copia / 3.0f);
        // separacao de cores (Hue Split) na densidade: eixos u (polo quente) e v (perpendicular)
        int split_on = (v_lab_separacao > 0.0f) ? 1 : 0;
        float3 hu = pc_hue_rgb(v_lab_separacao_eixo);
        hu = hu - pc_s3((hu.x + hu.y + hu.z) / 3.0f);
        hu = hu * (1.0f / _sqrtf(pc_dot3(hu, hu)));
        float3 hv = make_float3(hu.z - hu.y, hu.x - hu.z, hu.y - hu.x) * 0.57735027f;
        hv = hv * (1.0f / _sqrtf(pc_dot3(hv, hv)));
        float sa = PC_SPLIT_A * v_lab_separacao;
        float sb = PC_SPLIT_B * v_lab_separacao;
        float toe = _exp2f(-0.6f * v_lab_pe);
        float nn = v_lab_neutro_negativo;
        float np = v_lab_neutro_copia;
        int lq = lp * 17;
        float2 ab = pc_ii_coefs(PC_NEG[ni + 19], v_lab_saturacao_filme, v_lab_bypass_negativo);
        float3 la = pc_lab_path(lin,
            make_float3(PC_NEG[ni + 0], PC_NEG[ni + 1], PC_NEG[ni + 2]),
            make_float3(PC_NEG[ni + 3], PC_NEG[ni + 4], PC_NEG[ni + 5]),
            make_float3(PC_NEG[ni + 6], PC_NEG[ni + 7], PC_NEG[ni + 8]),
            pc_neutral3(make_float3(PC_NEG[ni + 9], PC_NEG[ni + 10], PC_NEG[ni + 11]), nn),
            pc_neutral3(make_float3(PC_NEG[ni + 12], PC_NEG[ni + 13], PC_NEG[ni + 14]), nn),
            pc_neutral3(make_float3(PC_NEG[ni + 15], PC_NEG[ni + 16], PC_NEG[ni + 17]), nn), PC_NEG[ni + 18],
            pc_ii_row(make_float3(1.0f, 0.0f, 0.0f), hu.x, hv.x, hu, hv, sa, sb, ab.x, ab.y, split_on),
            pc_ii_row(make_float3(0.0f, 1.0f, 0.0f), hu.y, hv.y, hu, hv, sa, sb, ab.x, ab.y, split_on),
            pc_ii_row(make_float3(0.0f, 0.0f, 1.0f), hu.z, hv.z, hu, hv, sa, sb, ab.x, ab.y, split_on),
            (PC_LPR[lq] > 0.5f) ? 1 : 0,
            pc_neutral3(make_float3(PC_LPR[lq + 1], PC_LPR[lq + 2], PC_LPR[lq + 3]), np),
            pc_neutral3(make_float3(PC_LPR[lq + 4], PC_LPR[lq + 5], PC_LPR[lq + 6]), np) * toe, PC_LPR[lq + 7],
            make_float3(PC_LPR[lq + 8], PC_LPR[lq + 9], PC_LPR[lq + 10]),
            make_float3(PC_LPR[lq + 11], PC_LPR[lq + 12], PC_LPR[lq + 13]),
            make_float3(PC_LPR[lq + 14], PC_LPR[lq + 15], PC_LPR[lq + 16]),
            key, v_lab_revelacao, v_lab_diafonia, lights, gn, ga, gq, gs);
        if (kind == 2.0f) {
            int b = pk + 1;
            float2 bb = pc_ii_coefs(PC_PROC[b + 19], v_lab_saturacao_filme, v_lab_bypass_negativo);
            float3 lb = pc_lab_path(lin,
                make_float3(PC_PROC[b + 0], PC_PROC[b + 1], PC_PROC[b + 2]),
                make_float3(PC_PROC[b + 3], PC_PROC[b + 4], PC_PROC[b + 5]),
                make_float3(PC_PROC[b + 6], PC_PROC[b + 7], PC_PROC[b + 8]),
                pc_neutral3(make_float3(PC_PROC[b + 9], PC_PROC[b + 10], PC_PROC[b + 11]), nn),
                pc_neutral3(make_float3(PC_PROC[b + 12], PC_PROC[b + 13], PC_PROC[b + 14]), nn),
                pc_neutral3(make_float3(PC_PROC[b + 15], PC_PROC[b + 16], PC_PROC[b + 17]), nn), PC_PROC[b + 18],
                pc_ii_row(make_float3(1.0f, 0.0f, 0.0f), hu.x, hv.x, hu, hv, sa, sb, bb.x, bb.y, split_on),
                pc_ii_row(make_float3(0.0f, 1.0f, 0.0f), hu.y, hv.y, hu, hv, sa, sb, bb.x, bb.y, split_on),
                pc_ii_row(make_float3(0.0f, 0.0f, 1.0f), hu.z, hv.z, hu, hv, sa, sb, bb.x, bb.y, split_on),
                1,
                pc_neutral3(make_float3(PC_PROC[b + 20], PC_PROC[b + 21], PC_PROC[b + 22]), np),
                pc_neutral3(make_float3(PC_PROC[b + 23], PC_PROC[b + 24], PC_PROC[b + 25]), np) * toe,
                PC_PROC[b + 26],
                make_float3(PC_PROC[b + 27], PC_PROC[b + 28], PC_PROC[b + 29]),
                make_float3(PC_PROC[b + 30], PC_PROC[b + 31], PC_PROC[b + 32]),
                make_float3(PC_PROC[b + 33], PC_PROC[b + 34], PC_PROC[b + 35]),
                make_float3(PC_PROC[b + 36], PC_PROC[b + 37], PC_PROC[b + 38]) * v_lab_chave,
                v_lab_revelacao, v_lab_diafonia, lights, gn, ga, gq, gs);
            la = pc_lerp3(la, lb, forca);
        }
        la = pc_lab_post(la, v_lab_luzes_rolagem, v_lab_sombras_rolagem, v_lab_saturacao,
                         make_float3(v_lab_dens_r - 1.0f, v_lab_dens_g - 1.0f, v_lab_dens_b - 1.0f),
                         v_lab_pele_matiz * 0.0174532925f, v_lab_pele_sat);
        lin = pc_code_to_lin(la);
    }

    float3 neutral = pc_lin_to_code(lin);
    float3 y = neutral;
    if (v_cor_on == 1) {
        int fi = v_pb_filtro;
        int vi = v_virada;
        float tone_amt = (PC_TONE_ON[vi] == 1 && v_pb == 1) ? v_virada_forca : 0.0f;
        float3 film = pc_film_look(lin, v_pb, make_float3(PC_BWW[fi * 3], PC_BWW[fi * 3 + 1], PC_BWW[fi * 3 + 2]),
            v_saturacao, make_float3(v_contraste_r, v_contraste_g, v_contraste_b),
            make_float3(v_offset_r, v_offset_g, v_offset_b), PC_DSLOPE * v_contraste, v_meio_tom, v_preto,
            _fmaxf(v_branco, v_meio_tom + 0.05f), pc_soft_p(v_rolagem_luzes), pc_soft_p(v_rolagem_sombras),
            v_densidade, v_verdes_matiz * 0.0174532925f, v_azuis_matiz * 0.0174532925f, v_pele_sat,
            v_pele_matiz * 0.0174532925f, v_pele_luz,
            pc_hsv_tint(v_sombras_matiz, v_sombras_forca), pc_hsv_tint(v_luzes_matiz, v_luzes_forca), v_equilibrio,
            tone_amt, make_float3(PC_TONE[vi * 6], PC_TONE[vi * 6 + 1], PC_TONE[vi * 6 + 2]),
            make_float3(PC_TONE[vi * 6 + 3], PC_TONE[vi * 6 + 4], PC_TONE[vi * 6 + 5]));
        y = pc_lerp3(neutral, film, v_cor_forca);
    }
    int pi = v_copia;
    if (PC_PR_ON[pi] == 1) {
        float3 pr = pc_print_stage(y, PC_PR[pi * 12 + 0],
            make_float3(PC_PR[pi * 12 + 1], PC_PR[pi * 12 + 2], PC_PR[pi * 12 + 3]),
            make_float3(PC_PR[pi * 12 + 4], PC_PR[pi * 12 + 5], PC_PR[pi * 12 + 6]),
            PC_PR[pi * 12 + 7], PC_PR[pi * 12 + 8], PC_PR[pi * 12 + 9], PC_PR[pi * 12 + 10],
            pc_soft_p(PC_PR_SOFT[pi * 2]), pc_soft_p(PC_PR_SOFT[pi * 2 + 1]));
        y = pc_lerp3(y, pr, v_copia_forca);
    }
    float age = (v_cor_on == 1) ? v_envelhecimento : 0.0f;
    if (age > 0.0f) y = pc_lerp3(y, pc_aged(y), age);
    return y;
}
// colorPipe com o grao fisico no negativo (grao_fisico.negative_grain)
static inline float3 pc_colorpipe_pg(const pc_vals& V, float3 lin, float3 ga_in, float4 gq_in, int gs_in) {
    int v_copia = V.copia;
    float v_copia_forca = V.copia_forca;
    float v_mix_geral = V.mix_geral;
    int v_mostrar_curva = V.mostrar_curva;
    int v_bitola = V.bitola;
    int v_iso = V.iso;
    int v_bitola_desfoque_on = V.bitola_desfoque_on;
    float v_bitola_resolucao = V.bitola_resolucao;
    float v_bitola_vinheta = V.bitola_vinheta;
    int v_mtf = V.mtf;
    float v_mtf_forca = V.mtf_forca;
    float v_mtf_camadas = V.mtf_camadas;
    int v_entrada = V.entrada;
    int v_faixa_video = V.faixa_video;
    int v_logc3_ei = V.logc3_ei;
    float v_exposicao = V.exposicao;
    float v_temperatura = V.temperatura;
    float v_tint = V.tint;
    float v_proteger_cores = V.proteger_cores;
    int v_lab_on = V.lab_on;
    int v_lab_negativo = V.lab_negativo;
    int v_lab_copia = V.lab_copia;
    float v_lab_revelacao = V.lab_revelacao;
    float v_lab_separacao = V.lab_separacao;
    float v_lab_separacao_eixo = V.lab_separacao_eixo;
    float v_lab_luz_r = V.lab_luz_r;
    float v_lab_luz_g = V.lab_luz_g;
    float v_lab_luz_b = V.lab_luz_b;
    float v_lab_densidade = V.lab_densidade;
    float v_lab_dens_r = V.lab_dens_r;
    float v_lab_dens_g = V.lab_dens_g;
    float v_lab_dens_b = V.lab_dens_b;
    float v_lab_pe = V.lab_pe;
    float v_lab_sombras_rolagem = V.lab_sombras_rolagem;
    float v_lab_luzes_rolagem = V.lab_luzes_rolagem;
    float v_lab_saturacao_filme = V.lab_saturacao_filme;
    float v_lab_saturacao = V.lab_saturacao;
    float v_lab_pele_matiz = V.lab_pele_matiz;
    float v_lab_pele_sat = V.lab_pele_sat;
    float v_lab_bypass_negativo = V.lab_bypass_negativo;
    float v_lab_bypass_copia = V.lab_bypass_copia;
    float v_lab_neutro_negativo = V.lab_neutro_negativo;
    float v_lab_neutro_copia = V.lab_neutro_copia;
    int v_lab_processo = V.lab_processo;
    float v_lab_processo_forca = V.lab_processo_forca;
    float v_lab_chave = V.lab_chave;
    float v_lab_diafonia = V.lab_diafonia;
    int v_lab_grao = V.lab_grao;
    int v_lab_grao_modelo = V.lab_grao_modelo;
    int v_cor_on = V.cor_on;
    float v_cor_forca = V.cor_forca;
    float v_contraste = V.contraste;
    float v_meio_tom = V.meio_tom;
    float v_preto = V.preto;
    float v_branco = V.branco;
    float v_rolagem_luzes = V.rolagem_luzes;
    float v_rolagem_sombras = V.rolagem_sombras;
    float v_saturacao = V.saturacao;
    float v_densidade = V.densidade;
    float v_sombras_matiz = V.sombras_matiz;
    float v_sombras_forca = V.sombras_forca;
    float v_luzes_matiz = V.luzes_matiz;
    float v_luzes_forca = V.luzes_forca;
    float v_equilibrio = V.equilibrio;
    float v_contraste_r = V.contraste_r;
    float v_contraste_g = V.contraste_g;
    float v_contraste_b = V.contraste_b;
    float v_offset_r = V.offset_r;
    float v_offset_g = V.offset_g;
    float v_offset_b = V.offset_b;
    float v_verdes_matiz = V.verdes_matiz;
    float v_azuis_matiz = V.azuis_matiz;
    float v_pele_sat = V.pele_sat;
    float v_pele_matiz = V.pele_matiz;
    float v_pele_luz = V.pele_luz;
    int v_pb = V.pb;
    int v_pb_filtro = V.pb_filtro;
    int v_virada = V.virada;
    float v_virada_forca = V.virada_forca;
    float v_envelhecimento = V.envelhecimento;
    int v_grao_on = V.grao_on;
    float v_grao_forca = V.grao_forca;
    float v_grao_tamanho = V.grao_tamanho;
    float v_grao_aspereza = V.grao_aspereza;
    float v_grao_cor = V.grao_cor;
    float v_grao_sombras = V.grao_sombras;
    float v_grao_meios = V.grao_meios;
    float v_grao_luzes = V.grao_luzes;
    int v_grao_animado = V.grao_animado;
    int v_grao_semente = V.grao_semente;
    float v_grao_maciez = V.grao_maciez;
    float v_grao_respiracao = V.grao_respiracao;
    int v_hal_on = V.hal_on;
    float v_hal_forca = V.hal_forca;
    float v_hal_raio = V.hal_raio;
    float v_hal_limiar = V.hal_limiar;
    float3 v_hal_cor = V.hal_cor;
    int v_hal_modelo = V.hal_modelo;
    int v_bloom_on = V.bloom_on;
    float v_bloom_forca = V.bloom_forca;
    float v_bloom_raio = V.bloom_raio;
    float v_bloom_limiar = V.bloom_limiar;
    float v_nevoa_forca = V.nevoa_forca;
    float v_nevoa_raio = V.nevoa_raio;
    int v_lente_on = V.lente_on;
    float v_maciez = V.maciez;
    float v_raio_maciez = V.raio_maciez;
    float v_nitidez = V.nitidez;
    float v_aberracao = V.aberracao;
    float v_distorcao = V.distorcao;
    float v_vinheta = V.vinheta;
    float v_vinheta_raio = V.vinheta_raio;
    float v_vinheta_suavidade = V.vinheta_suavidade;
    float v_vinheta_redondeza = V.vinheta_redondeza;
    int v_proj_on = V.proj_on;
    float v_tremor_x = V.tremor_x;
    float v_tremor_y = V.tremor_y;
    float v_tremor_rot = V.tremor_rot;
    float v_tremor_vel = V.tremor_vel;
    float v_cintilacao = V.cintilacao;
    float v_cintilacao_vel = V.cintilacao_vel;
    int v_desg_on = V.desg_on;
    int v_poeira_on = V.poeira_on;
    float v_poeira = V.poeira;
    float v_poeira_tamanho = V.poeira_tamanho;
    int v_poeira_tipo = V.poeira_tipo;
    int v_riscos_on = V.riscos_on;
    float v_riscos = V.riscos;
    float v_riscos_largura = V.riscos_largura;
    int v_cabelo_on = V.cabelo_on;
    float v_cabelo = V.cabelo;
    float v_cabelo_tamanho = V.cabelo_tamanho;
    int v_manchas_on = V.manchas_on;
    float v_manchas = V.manchas;
    int v_queima_on = V.queima_on;
    float v_queima = V.queima;
    int v_marcas_on = V.marcas_on;
    float v_marcas_intervalo = V.marcas_intervalo;
    int v_cor_instavel_on = V.cor_instavel_on;
    float v_cor_instavel = V.cor_instavel;
    int v_emenda_on = V.emenda_on;
    float v_emenda = V.emenda;
    int v_vazamento_on = V.vazamento_on;
    float v_vazamento = V.vazamento;
    float3 v_vazamento_cor = V.vazamento_cor;
    float v_vazamento_vel = V.vazamento_vel;
    int v_desgaste_semente = V.desgaste_semente;
    int v_mold_on = V.mold_on;
    int v_proporcao = V.proporcao;
    float v_cantos = V.cantos;
    float v_borda_suave = V.borda_suave;
    float v_borda_irregular = V.borda_irregular;
    float3 v_cor_barras = V.cor_barras;
    (void)v_copia;
    (void)v_copia_forca;
    (void)v_mix_geral;
    (void)v_mostrar_curva;
    (void)v_bitola;
    (void)v_iso;
    (void)v_bitola_desfoque_on;
    (void)v_bitola_resolucao;
    (void)v_bitola_vinheta;
    (void)v_mtf;
    (void)v_mtf_forca;
    (void)v_mtf_camadas;
    (void)v_entrada;
    (void)v_faixa_video;
    (void)v_logc3_ei;
    (void)v_exposicao;
    (void)v_temperatura;
    (void)v_tint;
    (void)v_proteger_cores;
    (void)v_lab_on;
    (void)v_lab_negativo;
    (void)v_lab_copia;
    (void)v_lab_revelacao;
    (void)v_lab_separacao;
    (void)v_lab_separacao_eixo;
    (void)v_lab_luz_r;
    (void)v_lab_luz_g;
    (void)v_lab_luz_b;
    (void)v_lab_densidade;
    (void)v_lab_dens_r;
    (void)v_lab_dens_g;
    (void)v_lab_dens_b;
    (void)v_lab_pe;
    (void)v_lab_sombras_rolagem;
    (void)v_lab_luzes_rolagem;
    (void)v_lab_saturacao_filme;
    (void)v_lab_saturacao;
    (void)v_lab_pele_matiz;
    (void)v_lab_pele_sat;
    (void)v_lab_bypass_negativo;
    (void)v_lab_bypass_copia;
    (void)v_lab_neutro_negativo;
    (void)v_lab_neutro_copia;
    (void)v_lab_processo;
    (void)v_lab_processo_forca;
    (void)v_lab_chave;
    (void)v_lab_diafonia;
    (void)v_lab_grao;
    (void)v_lab_grao_modelo;
    (void)v_cor_on;
    (void)v_cor_forca;
    (void)v_contraste;
    (void)v_meio_tom;
    (void)v_preto;
    (void)v_branco;
    (void)v_rolagem_luzes;
    (void)v_rolagem_sombras;
    (void)v_saturacao;
    (void)v_densidade;
    (void)v_sombras_matiz;
    (void)v_sombras_forca;
    (void)v_luzes_matiz;
    (void)v_luzes_forca;
    (void)v_equilibrio;
    (void)v_contraste_r;
    (void)v_contraste_g;
    (void)v_contraste_b;
    (void)v_offset_r;
    (void)v_offset_g;
    (void)v_offset_b;
    (void)v_verdes_matiz;
    (void)v_azuis_matiz;
    (void)v_pele_sat;
    (void)v_pele_matiz;
    (void)v_pele_luz;
    (void)v_pb;
    (void)v_pb_filtro;
    (void)v_virada;
    (void)v_virada_forca;
    (void)v_envelhecimento;
    (void)v_grao_on;
    (void)v_grao_forca;
    (void)v_grao_tamanho;
    (void)v_grao_aspereza;
    (void)v_grao_cor;
    (void)v_grao_sombras;
    (void)v_grao_meios;
    (void)v_grao_luzes;
    (void)v_grao_animado;
    (void)v_grao_semente;
    (void)v_grao_maciez;
    (void)v_grao_respiracao;
    (void)v_hal_on;
    (void)v_hal_forca;
    (void)v_hal_raio;
    (void)v_hal_limiar;
    (void)v_hal_cor;
    (void)v_hal_modelo;
    (void)v_bloom_on;
    (void)v_bloom_forca;
    (void)v_bloom_raio;
    (void)v_bloom_limiar;
    (void)v_nevoa_forca;
    (void)v_nevoa_raio;
    (void)v_lente_on;
    (void)v_maciez;
    (void)v_raio_maciez;
    (void)v_nitidez;
    (void)v_aberracao;
    (void)v_distorcao;
    (void)v_vinheta;
    (void)v_vinheta_raio;
    (void)v_vinheta_suavidade;
    (void)v_vinheta_redondeza;
    (void)v_proj_on;
    (void)v_tremor_x;
    (void)v_tremor_y;
    (void)v_tremor_rot;
    (void)v_tremor_vel;
    (void)v_cintilacao;
    (void)v_cintilacao_vel;
    (void)v_desg_on;
    (void)v_poeira_on;
    (void)v_poeira;
    (void)v_poeira_tamanho;
    (void)v_poeira_tipo;
    (void)v_riscos_on;
    (void)v_riscos;
    (void)v_riscos_largura;
    (void)v_cabelo_on;
    (void)v_cabelo;
    (void)v_cabelo_tamanho;
    (void)v_manchas_on;
    (void)v_manchas;
    (void)v_queima_on;
    (void)v_queima;
    (void)v_marcas_on;
    (void)v_marcas_intervalo;
    (void)v_cor_instavel_on;
    (void)v_cor_instavel;
    (void)v_emenda_on;
    (void)v_emenda;
    (void)v_vazamento_on;
    (void)v_vazamento;
    (void)v_vazamento_cor;
    (void)v_vazamento_vel;
    (void)v_desgaste_semente;
    (void)v_mold_on;
    (void)v_proporcao;
    (void)v_cantos;
    (void)v_borda_suave;
    (void)v_borda_irregular;
    (void)v_cor_barras;

    if (v_lab_on == 1) {
        float3 gn = pc_s3(0.0f);
        float3 ga = pc_s3(0.0f);  // 1.6: grao fisico (fracao por camada; zero = desligado), posicao e semente
        float4 gq = make_float4(0.0f, 0.0f, 1.0f, 0.0f);
        int gs = 0;
        ga = ga_in;
        gq = gq_in;
        gs = gs_in;
        int ni = v_lab_negativo * 20;
        int lp = v_lab_copia;
        int pk = v_lab_processo * 40;
        float kind = PC_PROC[pk];
        float forca = v_lab_processo_forca;
        float3 lights = make_float3(PC_LAB_POINT * (v_lab_luz_r + v_lab_densidade),
                                    PC_LAB_POINT * (v_lab_luz_g + v_lab_densidade),
                                    PC_LAB_POINT * (v_lab_luz_b + v_lab_densidade));
        float3 key = pc_s3(0.0f);
        if (kind == 1.0f) {
            key = pc_s3(0.8f * forca / 3.0f);
            if (PC_LPR[lp * 17] == 0.0f) lp = PC_LAB_2383;
        }
        if (v_lab_bypass_copia > 0.0f && PC_LPR[lp * 17] > 0.5f) key = key + pc_s3(0.8f * v_lab_bypass_copia / 3.0f);
        // separacao de cores (Hue Split) na densidade: eixos u (polo quente) e v (perpendicular)
        int split_on = (v_lab_separacao > 0.0f) ? 1 : 0;
        float3 hu = pc_hue_rgb(v_lab_separacao_eixo);
        hu = hu - pc_s3((hu.x + hu.y + hu.z) / 3.0f);
        hu = hu * (1.0f / _sqrtf(pc_dot3(hu, hu)));
        float3 hv = make_float3(hu.z - hu.y, hu.x - hu.z, hu.y - hu.x) * 0.57735027f;
        hv = hv * (1.0f / _sqrtf(pc_dot3(hv, hv)));
        float sa = PC_SPLIT_A * v_lab_separacao;
        float sb = PC_SPLIT_B * v_lab_separacao;
        float toe = _exp2f(-0.6f * v_lab_pe);
        float nn = v_lab_neutro_negativo;
        float np = v_lab_neutro_copia;
        int lq = lp * 17;
        float2 ab = pc_ii_coefs(PC_NEG[ni + 19], v_lab_saturacao_filme, v_lab_bypass_negativo);
        float3 la = pc_lab_path(lin,
            make_float3(PC_NEG[ni + 0], PC_NEG[ni + 1], PC_NEG[ni + 2]),
            make_float3(PC_NEG[ni + 3], PC_NEG[ni + 4], PC_NEG[ni + 5]),
            make_float3(PC_NEG[ni + 6], PC_NEG[ni + 7], PC_NEG[ni + 8]),
            pc_neutral3(make_float3(PC_NEG[ni + 9], PC_NEG[ni + 10], PC_NEG[ni + 11]), nn),
            pc_neutral3(make_float3(PC_NEG[ni + 12], PC_NEG[ni + 13], PC_NEG[ni + 14]), nn),
            pc_neutral3(make_float3(PC_NEG[ni + 15], PC_NEG[ni + 16], PC_NEG[ni + 17]), nn), PC_NEG[ni + 18],
            pc_ii_row(make_float3(1.0f, 0.0f, 0.0f), hu.x, hv.x, hu, hv, sa, sb, ab.x, ab.y, split_on),
            pc_ii_row(make_float3(0.0f, 1.0f, 0.0f), hu.y, hv.y, hu, hv, sa, sb, ab.x, ab.y, split_on),
            pc_ii_row(make_float3(0.0f, 0.0f, 1.0f), hu.z, hv.z, hu, hv, sa, sb, ab.x, ab.y, split_on),
            (PC_LPR[lq] > 0.5f) ? 1 : 0,
            pc_neutral3(make_float3(PC_LPR[lq + 1], PC_LPR[lq + 2], PC_LPR[lq + 3]), np),
            pc_neutral3(make_float3(PC_LPR[lq + 4], PC_LPR[lq + 5], PC_LPR[lq + 6]), np) * toe, PC_LPR[lq + 7],
            make_float3(PC_LPR[lq + 8], PC_LPR[lq + 9], PC_LPR[lq + 10]),
            make_float3(PC_LPR[lq + 11], PC_LPR[lq + 12], PC_LPR[lq + 13]),
            make_float3(PC_LPR[lq + 14], PC_LPR[lq + 15], PC_LPR[lq + 16]),
            key, v_lab_revelacao, v_lab_diafonia, lights, gn, ga, gq, gs);
        if (kind == 2.0f) {
            int b = pk + 1;
            float2 bb = pc_ii_coefs(PC_PROC[b + 19], v_lab_saturacao_filme, v_lab_bypass_negativo);
            float3 lb = pc_lab_path(lin,
                make_float3(PC_PROC[b + 0], PC_PROC[b + 1], PC_PROC[b + 2]),
                make_float3(PC_PROC[b + 3], PC_PROC[b + 4], PC_PROC[b + 5]),
                make_float3(PC_PROC[b + 6], PC_PROC[b + 7], PC_PROC[b + 8]),
                pc_neutral3(make_float3(PC_PROC[b + 9], PC_PROC[b + 10], PC_PROC[b + 11]), nn),
                pc_neutral3(make_float3(PC_PROC[b + 12], PC_PROC[b + 13], PC_PROC[b + 14]), nn),
                pc_neutral3(make_float3(PC_PROC[b + 15], PC_PROC[b + 16], PC_PROC[b + 17]), nn), PC_PROC[b + 18],
                pc_ii_row(make_float3(1.0f, 0.0f, 0.0f), hu.x, hv.x, hu, hv, sa, sb, bb.x, bb.y, split_on),
                pc_ii_row(make_float3(0.0f, 1.0f, 0.0f), hu.y, hv.y, hu, hv, sa, sb, bb.x, bb.y, split_on),
                pc_ii_row(make_float3(0.0f, 0.0f, 1.0f), hu.z, hv.z, hu, hv, sa, sb, bb.x, bb.y, split_on),
                1,
                pc_neutral3(make_float3(PC_PROC[b + 20], PC_PROC[b + 21], PC_PROC[b + 22]), np),
                pc_neutral3(make_float3(PC_PROC[b + 23], PC_PROC[b + 24], PC_PROC[b + 25]), np) * toe,
                PC_PROC[b + 26],
                make_float3(PC_PROC[b + 27], PC_PROC[b + 28], PC_PROC[b + 29]),
                make_float3(PC_PROC[b + 30], PC_PROC[b + 31], PC_PROC[b + 32]),
                make_float3(PC_PROC[b + 33], PC_PROC[b + 34], PC_PROC[b + 35]),
                make_float3(PC_PROC[b + 36], PC_PROC[b + 37], PC_PROC[b + 38]) * v_lab_chave,
                v_lab_revelacao, v_lab_diafonia, lights, gn, ga, gq, gs);
            la = pc_lerp3(la, lb, forca);
        }
        la = pc_lab_post(la, v_lab_luzes_rolagem, v_lab_sombras_rolagem, v_lab_saturacao,
                         make_float3(v_lab_dens_r - 1.0f, v_lab_dens_g - 1.0f, v_lab_dens_b - 1.0f),
                         v_lab_pele_matiz * 0.0174532925f, v_lab_pele_sat);
        lin = pc_code_to_lin(la);
    }

    float3 neutral = pc_lin_to_code(lin);
    float3 y = neutral;
    if (v_cor_on == 1) {
        int fi = v_pb_filtro;
        int vi = v_virada;
        float tone_amt = (PC_TONE_ON[vi] == 1 && v_pb == 1) ? v_virada_forca : 0.0f;
        float3 film = pc_film_look(lin, v_pb, make_float3(PC_BWW[fi * 3], PC_BWW[fi * 3 + 1], PC_BWW[fi * 3 + 2]),
            v_saturacao, make_float3(v_contraste_r, v_contraste_g, v_contraste_b),
            make_float3(v_offset_r, v_offset_g, v_offset_b), PC_DSLOPE * v_contraste, v_meio_tom, v_preto,
            _fmaxf(v_branco, v_meio_tom + 0.05f), pc_soft_p(v_rolagem_luzes), pc_soft_p(v_rolagem_sombras),
            v_densidade, v_verdes_matiz * 0.0174532925f, v_azuis_matiz * 0.0174532925f, v_pele_sat,
            v_pele_matiz * 0.0174532925f, v_pele_luz,
            pc_hsv_tint(v_sombras_matiz, v_sombras_forca), pc_hsv_tint(v_luzes_matiz, v_luzes_forca), v_equilibrio,
            tone_amt, make_float3(PC_TONE[vi * 6], PC_TONE[vi * 6 + 1], PC_TONE[vi * 6 + 2]),
            make_float3(PC_TONE[vi * 6 + 3], PC_TONE[vi * 6 + 4], PC_TONE[vi * 6 + 5]));
        y = pc_lerp3(neutral, film, v_cor_forca);
    }
    int pi = v_copia;
    if (PC_PR_ON[pi] == 1) {
        float3 pr = pc_print_stage(y, PC_PR[pi * 12 + 0],
            make_float3(PC_PR[pi * 12 + 1], PC_PR[pi * 12 + 2], PC_PR[pi * 12 + 3]),
            make_float3(PC_PR[pi * 12 + 4], PC_PR[pi * 12 + 5], PC_PR[pi * 12 + 6]),
            PC_PR[pi * 12 + 7], PC_PR[pi * 12 + 8], PC_PR[pi * 12 + 9], PC_PR[pi * 12 + 10],
            pc_soft_p(PC_PR_SOFT[pi * 2]), pc_soft_p(PC_PR_SOFT[pi * 2 + 1]));
        y = pc_lerp3(y, pr, v_copia_forca);
    }
    float age = (v_cor_on == 1) ? v_envelhecimento : 0.0f;
    if (age > 0.0f) y = pc_lerp3(y, pc_aged(y), age);
    return y;
}

// tremor, cintilacao e eventos dos defeitos de um quadro (B_FRAME = look.build_plan)
struct pc_frame {
    float scale;
    float sh_x;
    float sh_y;
    float rot;
    float zoom;
    float g0;
    float g1;
    float g2;
    float splice_on;
    float splice_y;
    float hair_on;
    float hair_seed;
    float hair_wig;
    float stain_amt;
    float stain_seed;
    float cue;
    float leak_on;
    int sd;
    int dg;
    float4 L0;
    float4 L1;
};
static inline void pc_frame_params(const pc_vals& V, int p_Width, int p_Height, int p_frame, float p_fps, pc_frame* o) {
    int v_copia = V.copia;
    float v_copia_forca = V.copia_forca;
    float v_mix_geral = V.mix_geral;
    int v_mostrar_curva = V.mostrar_curva;
    int v_bitola = V.bitola;
    int v_iso = V.iso;
    int v_bitola_desfoque_on = V.bitola_desfoque_on;
    float v_bitola_resolucao = V.bitola_resolucao;
    float v_bitola_vinheta = V.bitola_vinheta;
    int v_mtf = V.mtf;
    float v_mtf_forca = V.mtf_forca;
    float v_mtf_camadas = V.mtf_camadas;
    int v_entrada = V.entrada;
    int v_faixa_video = V.faixa_video;
    int v_logc3_ei = V.logc3_ei;
    float v_exposicao = V.exposicao;
    float v_temperatura = V.temperatura;
    float v_tint = V.tint;
    float v_proteger_cores = V.proteger_cores;
    int v_lab_on = V.lab_on;
    int v_lab_negativo = V.lab_negativo;
    int v_lab_copia = V.lab_copia;
    float v_lab_revelacao = V.lab_revelacao;
    float v_lab_separacao = V.lab_separacao;
    float v_lab_separacao_eixo = V.lab_separacao_eixo;
    float v_lab_luz_r = V.lab_luz_r;
    float v_lab_luz_g = V.lab_luz_g;
    float v_lab_luz_b = V.lab_luz_b;
    float v_lab_densidade = V.lab_densidade;
    float v_lab_dens_r = V.lab_dens_r;
    float v_lab_dens_g = V.lab_dens_g;
    float v_lab_dens_b = V.lab_dens_b;
    float v_lab_pe = V.lab_pe;
    float v_lab_sombras_rolagem = V.lab_sombras_rolagem;
    float v_lab_luzes_rolagem = V.lab_luzes_rolagem;
    float v_lab_saturacao_filme = V.lab_saturacao_filme;
    float v_lab_saturacao = V.lab_saturacao;
    float v_lab_pele_matiz = V.lab_pele_matiz;
    float v_lab_pele_sat = V.lab_pele_sat;
    float v_lab_bypass_negativo = V.lab_bypass_negativo;
    float v_lab_bypass_copia = V.lab_bypass_copia;
    float v_lab_neutro_negativo = V.lab_neutro_negativo;
    float v_lab_neutro_copia = V.lab_neutro_copia;
    int v_lab_processo = V.lab_processo;
    float v_lab_processo_forca = V.lab_processo_forca;
    float v_lab_chave = V.lab_chave;
    float v_lab_diafonia = V.lab_diafonia;
    int v_lab_grao = V.lab_grao;
    int v_lab_grao_modelo = V.lab_grao_modelo;
    int v_cor_on = V.cor_on;
    float v_cor_forca = V.cor_forca;
    float v_contraste = V.contraste;
    float v_meio_tom = V.meio_tom;
    float v_preto = V.preto;
    float v_branco = V.branco;
    float v_rolagem_luzes = V.rolagem_luzes;
    float v_rolagem_sombras = V.rolagem_sombras;
    float v_saturacao = V.saturacao;
    float v_densidade = V.densidade;
    float v_sombras_matiz = V.sombras_matiz;
    float v_sombras_forca = V.sombras_forca;
    float v_luzes_matiz = V.luzes_matiz;
    float v_luzes_forca = V.luzes_forca;
    float v_equilibrio = V.equilibrio;
    float v_contraste_r = V.contraste_r;
    float v_contraste_g = V.contraste_g;
    float v_contraste_b = V.contraste_b;
    float v_offset_r = V.offset_r;
    float v_offset_g = V.offset_g;
    float v_offset_b = V.offset_b;
    float v_verdes_matiz = V.verdes_matiz;
    float v_azuis_matiz = V.azuis_matiz;
    float v_pele_sat = V.pele_sat;
    float v_pele_matiz = V.pele_matiz;
    float v_pele_luz = V.pele_luz;
    int v_pb = V.pb;
    int v_pb_filtro = V.pb_filtro;
    int v_virada = V.virada;
    float v_virada_forca = V.virada_forca;
    float v_envelhecimento = V.envelhecimento;
    int v_grao_on = V.grao_on;
    float v_grao_forca = V.grao_forca;
    float v_grao_tamanho = V.grao_tamanho;
    float v_grao_aspereza = V.grao_aspereza;
    float v_grao_cor = V.grao_cor;
    float v_grao_sombras = V.grao_sombras;
    float v_grao_meios = V.grao_meios;
    float v_grao_luzes = V.grao_luzes;
    int v_grao_animado = V.grao_animado;
    int v_grao_semente = V.grao_semente;
    float v_grao_maciez = V.grao_maciez;
    float v_grao_respiracao = V.grao_respiracao;
    int v_hal_on = V.hal_on;
    float v_hal_forca = V.hal_forca;
    float v_hal_raio = V.hal_raio;
    float v_hal_limiar = V.hal_limiar;
    float3 v_hal_cor = V.hal_cor;
    int v_hal_modelo = V.hal_modelo;
    int v_bloom_on = V.bloom_on;
    float v_bloom_forca = V.bloom_forca;
    float v_bloom_raio = V.bloom_raio;
    float v_bloom_limiar = V.bloom_limiar;
    float v_nevoa_forca = V.nevoa_forca;
    float v_nevoa_raio = V.nevoa_raio;
    int v_lente_on = V.lente_on;
    float v_maciez = V.maciez;
    float v_raio_maciez = V.raio_maciez;
    float v_nitidez = V.nitidez;
    float v_aberracao = V.aberracao;
    float v_distorcao = V.distorcao;
    float v_vinheta = V.vinheta;
    float v_vinheta_raio = V.vinheta_raio;
    float v_vinheta_suavidade = V.vinheta_suavidade;
    float v_vinheta_redondeza = V.vinheta_redondeza;
    int v_proj_on = V.proj_on;
    float v_tremor_x = V.tremor_x;
    float v_tremor_y = V.tremor_y;
    float v_tremor_rot = V.tremor_rot;
    float v_tremor_vel = V.tremor_vel;
    float v_cintilacao = V.cintilacao;
    float v_cintilacao_vel = V.cintilacao_vel;
    int v_desg_on = V.desg_on;
    int v_poeira_on = V.poeira_on;
    float v_poeira = V.poeira;
    float v_poeira_tamanho = V.poeira_tamanho;
    int v_poeira_tipo = V.poeira_tipo;
    int v_riscos_on = V.riscos_on;
    float v_riscos = V.riscos;
    float v_riscos_largura = V.riscos_largura;
    int v_cabelo_on = V.cabelo_on;
    float v_cabelo = V.cabelo;
    float v_cabelo_tamanho = V.cabelo_tamanho;
    int v_manchas_on = V.manchas_on;
    float v_manchas = V.manchas;
    int v_queima_on = V.queima_on;
    float v_queima = V.queima;
    int v_marcas_on = V.marcas_on;
    float v_marcas_intervalo = V.marcas_intervalo;
    int v_cor_instavel_on = V.cor_instavel_on;
    float v_cor_instavel = V.cor_instavel;
    int v_emenda_on = V.emenda_on;
    float v_emenda = V.emenda;
    int v_vazamento_on = V.vazamento_on;
    float v_vazamento = V.vazamento;
    float3 v_vazamento_cor = V.vazamento_cor;
    float v_vazamento_vel = V.vazamento_vel;
    int v_desgaste_semente = V.desgaste_semente;
    int v_mold_on = V.mold_on;
    int v_proporcao = V.proporcao;
    float v_cantos = V.cantos;
    float v_borda_suave = V.borda_suave;
    float v_borda_irregular = V.borda_irregular;
    float3 v_cor_barras = V.cor_barras;
    (void)v_copia;
    (void)v_copia_forca;
    (void)v_mix_geral;
    (void)v_mostrar_curva;
    (void)v_bitola;
    (void)v_iso;
    (void)v_bitola_desfoque_on;
    (void)v_bitola_resolucao;
    (void)v_bitola_vinheta;
    (void)v_mtf;
    (void)v_mtf_forca;
    (void)v_mtf_camadas;
    (void)v_entrada;
    (void)v_faixa_video;
    (void)v_logc3_ei;
    (void)v_exposicao;
    (void)v_temperatura;
    (void)v_tint;
    (void)v_proteger_cores;
    (void)v_lab_on;
    (void)v_lab_negativo;
    (void)v_lab_copia;
    (void)v_lab_revelacao;
    (void)v_lab_separacao;
    (void)v_lab_separacao_eixo;
    (void)v_lab_luz_r;
    (void)v_lab_luz_g;
    (void)v_lab_luz_b;
    (void)v_lab_densidade;
    (void)v_lab_dens_r;
    (void)v_lab_dens_g;
    (void)v_lab_dens_b;
    (void)v_lab_pe;
    (void)v_lab_sombras_rolagem;
    (void)v_lab_luzes_rolagem;
    (void)v_lab_saturacao_filme;
    (void)v_lab_saturacao;
    (void)v_lab_pele_matiz;
    (void)v_lab_pele_sat;
    (void)v_lab_bypass_negativo;
    (void)v_lab_bypass_copia;
    (void)v_lab_neutro_negativo;
    (void)v_lab_neutro_copia;
    (void)v_lab_processo;
    (void)v_lab_processo_forca;
    (void)v_lab_chave;
    (void)v_lab_diafonia;
    (void)v_lab_grao;
    (void)v_lab_grao_modelo;
    (void)v_cor_on;
    (void)v_cor_forca;
    (void)v_contraste;
    (void)v_meio_tom;
    (void)v_preto;
    (void)v_branco;
    (void)v_rolagem_luzes;
    (void)v_rolagem_sombras;
    (void)v_saturacao;
    (void)v_densidade;
    (void)v_sombras_matiz;
    (void)v_sombras_forca;
    (void)v_luzes_matiz;
    (void)v_luzes_forca;
    (void)v_equilibrio;
    (void)v_contraste_r;
    (void)v_contraste_g;
    (void)v_contraste_b;
    (void)v_offset_r;
    (void)v_offset_g;
    (void)v_offset_b;
    (void)v_verdes_matiz;
    (void)v_azuis_matiz;
    (void)v_pele_sat;
    (void)v_pele_matiz;
    (void)v_pele_luz;
    (void)v_pb;
    (void)v_pb_filtro;
    (void)v_virada;
    (void)v_virada_forca;
    (void)v_envelhecimento;
    (void)v_grao_on;
    (void)v_grao_forca;
    (void)v_grao_tamanho;
    (void)v_grao_aspereza;
    (void)v_grao_cor;
    (void)v_grao_sombras;
    (void)v_grao_meios;
    (void)v_grao_luzes;
    (void)v_grao_animado;
    (void)v_grao_semente;
    (void)v_grao_maciez;
    (void)v_grao_respiracao;
    (void)v_hal_on;
    (void)v_hal_forca;
    (void)v_hal_raio;
    (void)v_hal_limiar;
    (void)v_hal_cor;
    (void)v_hal_modelo;
    (void)v_bloom_on;
    (void)v_bloom_forca;
    (void)v_bloom_raio;
    (void)v_bloom_limiar;
    (void)v_nevoa_forca;
    (void)v_nevoa_raio;
    (void)v_lente_on;
    (void)v_maciez;
    (void)v_raio_maciez;
    (void)v_nitidez;
    (void)v_aberracao;
    (void)v_distorcao;
    (void)v_vinheta;
    (void)v_vinheta_raio;
    (void)v_vinheta_suavidade;
    (void)v_vinheta_redondeza;
    (void)v_proj_on;
    (void)v_tremor_x;
    (void)v_tremor_y;
    (void)v_tremor_rot;
    (void)v_tremor_vel;
    (void)v_cintilacao;
    (void)v_cintilacao_vel;
    (void)v_desg_on;
    (void)v_poeira_on;
    (void)v_poeira;
    (void)v_poeira_tamanho;
    (void)v_poeira_tipo;
    (void)v_riscos_on;
    (void)v_riscos;
    (void)v_riscos_largura;
    (void)v_cabelo_on;
    (void)v_cabelo;
    (void)v_cabelo_tamanho;
    (void)v_manchas_on;
    (void)v_manchas;
    (void)v_queima_on;
    (void)v_queima;
    (void)v_marcas_on;
    (void)v_marcas_intervalo;
    (void)v_cor_instavel_on;
    (void)v_cor_instavel;
    (void)v_emenda_on;
    (void)v_emenda;
    (void)v_vazamento_on;
    (void)v_vazamento;
    (void)v_vazamento_cor;
    (void)v_vazamento_vel;
    (void)v_desgaste_semente;
    (void)v_mold_on;
    (void)v_proporcao;
    (void)v_cantos;
    (void)v_borda_suave;
    (void)v_borda_irregular;
    (void)v_cor_barras;

    float W = PC_F(p_Width);
    float H = PC_F(p_Height);
    float scale = H / 1080.0f;
    int frame = p_frame;
    float fps = p_fps;
    float t = PC_F(frame) / fps;
    int gi = v_bitola;
    float weave = PC_GAUGE[gi * 7 + 3];
    float sh_x = 0.0f;
    float sh_y = 0.0f;
    float rot = 0.0f;
    float zoom = 1.0f;
    float g0 = 0.0f;
    float g1 = 0.0f;
    float g2 = 0.0f;
    if (v_proj_on == 1) {
        float ww = weave * scale;
        float vel = v_tremor_vel;
        sh_x = v_tremor_x * ww * (0.7f * pc_vnoise(t * 2.2f * vel, 101) + 0.3f * (pc_hash(frame, 102) * 2.0f - 1.0f));
        sh_y = v_tremor_y * ww * (0.7f * pc_vnoise(t * 1.9f * vel, 103) + 0.3f * (pc_hash(frame, 104) * 2.0f - 1.0f));
        rot = (v_tremor_rot * weave * 0.0174532925f)
            * (0.7f * pc_vnoise(t * 1.6f * vel, 105) + 0.3f * (pc_hash(frame, 106) * 2.0f - 1.0f));
        float margin = _fmaxf(v_tremor_x, v_tremor_y) * ww * 1.1f + _fabs(rot) * W * 0.5f;
        zoom = 1.0f + 2.0f * margin / _fmaxf(1.0f, _fminf(W, H));
        float fl = v_cintilacao * (0.6f * pc_vnoise(t * 7.0f * v_cintilacao_vel, 107)
                                   + 0.4f * (pc_hash(frame, 108) * 2.0f - 1.0f));
        g0 = g0 + fl;
        g1 = g1 + fl;
        g2 = g2 + fl;
    }
    int sd = v_desgaste_semente;
    int dg = v_desg_on;
    float splice_on = 0.0f;
    float splice_y = 0.5f;
    if (dg == 1) {
        if (v_queima_on == 1 && v_queima > 0.0f) {
            int ep = PC_I(_floorf(t / 6.0f));
            if (pc_hash(ep, sd + 401) < v_queima * 0.55f) {
                float st = PC_F(ep) * 6.0f + pc_hash(ep, sd + 402) * 5.0f;
                if (t >= st) {
                    float f = _expf(-(t - st) / 0.13f);
                    g0 = g0 + 2.6f * f;
                    g1 = g1 + 2.0f * f;
                    g2 = g2 + 1.1f * f;
                }
            }
        }
        if (v_cor_instavel_on == 1 && v_cor_instavel > 0.0f) {
            float a = v_cor_instavel * 0.12f;
            g0 = g0 + a * (0.6f * pc_vnoise(t * 5.0f, sd + 410) + 0.4f * (pc_hash(frame, sd + 420) * 2.0f - 1.0f));
            g1 = g1 + a * (0.6f * pc_vnoise(t * 5.0f, sd + 411) + 0.4f * (pc_hash(frame, sd + 421) * 2.0f - 1.0f));
            g2 = g2 + a * (0.6f * pc_vnoise(t * 5.0f, sd + 412) + 0.4f * (pc_hash(frame, sd + 422) * 2.0f - 1.0f));
        }
        if (v_emenda_on == 1 && v_emenda > 0.0f) {
            int ep = PC_I(_floorf(t / 2.5f));
            if (pc_hash(ep, sd + 501) < v_emenda * 0.4f) {
                int sf = PC_I(_floorf((PC_F(ep) * 2.5f + pc_hash(ep, sd + 502) * 2.0f) * fps + 0.5f));
                if (frame == sf) {
                    sh_y = sh_y + 14.0f * scale;
                    splice_on = 1.0f;
                    splice_y = 0.15f + 0.7f * pc_hash(ep, sd + 503);
                } else if (frame == sf + 1) {
                    sh_y = sh_y + 6.0f * scale;
                }
            }
        }
    }
    float hair_on = 0.0f;
    float hair_seed = 0.0f;
    float hair_wig = 0.0f;
    if (dg == 1 && v_cabelo_on == 1 && v_cabelo > 0.0f) {
        int ep = PC_I(_floorf(t / 3.0f));
        if (pc_hash(ep, sd + 201) < v_cabelo * 0.7f) {
            hair_wig = 3.0f * pc_vnoise(t * 9.0f, sd + 202) + 1.2f * (pc_hash(frame, sd + 203) * 2.0f - 1.0f);
            hair_on = 1.0f;
            hair_seed = PC_F(ep - (ep / 100000) * 100000 + sd * 7);
        }
    }
    float stain_amt = 0.0f;
    float stain_seed = 0.0f;
    if (dg == 1 && v_manchas_on == 1 && v_manchas > 0.0f) {
        int ep = frame / 3;
        if (pc_hash(ep, sd + 301) < v_manchas * 0.18f) {
            stain_amt = _fminf(1.0f, 0.5f + v_manchas);
            stain_seed = PC_F(ep - (ep / 9973) * 9973);
        }
    }
    float cue = 0.0f;
    if (dg == 1 && v_marcas_on == 1) {
        int per = PC_I(_floorf(v_marcas_intervalo * fps + 0.5f));
        per = per < 8 ? 8 : per;
        if (frame - (frame / per) * per < 4 && frame >= 4) cue = 1.0f;
    }
    float leak_on = 0.0f;
    float4 L0 = make_float4(0.0f, 0.0f, 1.0f, 0.0f);
    float4 L1 = make_float4(0.0f, 0.0f, 1.0f, 0.0f);
    if (dg == 1 && v_vazamento_on == 1 && v_vazamento > 0.0f) {
        leak_on = 1.0f;
        float tl = t * 0.35f * v_vazamento_vel;
        for (int k = 0; k < 2; k++) {
            float side = (pc_hash(k, sd + 3) < 0.5f) ? 0.0f : 1.0f;
            float bx = side + ((side == 0.0f) ? 0.12f : -0.12f) * pc_vnoise(tl + PC_F(k) * 7.3f, sd + 10 + k);
            float by = 0.5f + 0.55f * pc_vnoise(tl * 0.8f + PC_F(k) * 3.1f, sd + 20 + k);
            float br = 0.35f + 0.2f * pc_vnoise(tl * 1.3f + PC_F(k), sd + 30 + k);
            float ba = _fmaxf(0.0f, 0.55f + 0.6f * pc_vnoise(tl * 1.7f + PC_F(k) * 5.0f, sd + 40 + k));
            if (k == 0) L0 = make_float4(bx, by, br, ba); else L1 = make_float4(bx, by, br, ba);
        }
    }
    o->scale = scale;
    o->sh_x = sh_x;
    o->sh_y = sh_y;
    o->rot = rot;
    o->zoom = zoom;
    o->g0 = g0;
    o->g1 = g1;
    o->g2 = g2;
    o->splice_on = splice_on;
    o->splice_y = splice_y;
    o->hair_on = hair_on;
    o->hair_seed = hair_seed;
    o->hair_wig = hair_wig;
    o->stain_amt = stain_amt;
    o->stain_seed = stain_seed;
    o->cue = cue;
    o->leak_on = leak_on;
    o->sd = sd;
    o->dg = dg;
    o->L0 = L0;
    o->L1 = L1;
}
