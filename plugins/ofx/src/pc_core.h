// Núcleo do plugin OpenFX do PeliculaConverter: o mesmo caminho do Engine.render() do app, na CPU.
//
// Imagens RGB float com a linha 0 no topo (como o app; o OFX entrega de baixo para cima e a cola
// em pc_ofx.cpp inverte). Valores de entrada e saída são códigos do vídeo (0..1).
// `ui` é o vetor de valores da interface (PC_UI_SIZE floats, na ordem de PC_PARAMS).
#pragma once

#include <memory>
#include <mutex>
#include <string>
#include <vector>

namespace pc {

int ui_size();
void app_default_ui(float* ui);   // params.defaults() do app
void start_ui(float* ui);         // o efeito novo: o preset padrão do app
bool preset_ui(int index, float* ui);

// Lê um look exportado pelo app (.json de preset ou projeto .plc, chave "valores") e preenche `ui`
// a partir dos padrões do app, como params.sanitize(). Devolve false e a mensagem em `error`.
bool load_look_json(const std::string& text, float* ui, std::string* error);
bool load_look_file(const std::string& utf8_path, float* ui, std::string* error);

class Renderer {
public:
    // Look inteiro: tremor, lente, entrada, ganho, vinheta, maciez, halação/bloom/névoa, vazamento,
    // cor (laboratório + look + cópia), grão, defeitos, força geral, moldura e "Mostrar curva".
    // `exact_color` = 1 calcula a cor em cada pixel (igual ao app); 0 usa um LUT 65^3 adaptativo (prévia).
    void render(const float* ui, const float* in, float* out, int w, int h, int frame, float fps,
                int exact_color);

    // Só a cor (o que o app grava num LUT): entrada → ganho → colorPipe, pixel a pixel.
    void color(const float* ui, const float* in, float* out, int n, int exact_color);

    // Fração das células do LUT da cor que usam a conta exata (diagnóstico e testes).
    float lut_exact_fraction(const float* ui);

    // Erro de interpolação aceito no meio de uma célula do LUT; acima dele a célula usa a conta exata.
    void set_lut_tolerance(float tol);

private:
    struct Lut {
        std::vector<float> key;   // valores da interface usados para montar
        std::vector<float> data;  // N^3 x 3, R mais rápido
        std::vector<unsigned char> exact;  // (N-1)^3 células: 1 = interpolar erra demais, usar a conta exata
    };
    std::mutex lut_mutex_;
    std::shared_ptr<const Lut> lut_;
    float lut_tol_ = 2e-3f;  // ~1/2 nível de 8 bits
    std::shared_ptr<const Lut> lut_for(const float* ui);
};

}  // namespace pc
