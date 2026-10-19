// Interface C do núcleo (exportada pelo próprio PeliculaConverter.ofx): os testes carregam o binário com
// ctypes e comparam com o app (tests/test_ofx.py). O Resolve só usa OfxGetPlugin/OfxGetNumberOfPlugins.
#include <cstring>
#include <string>

#include "pc_core.h"

#if defined(_WIN32)
#define PC_API extern "C" __declspec(dllexport)
#else
#define PC_API extern "C" __attribute__((visibility("default")))
#endif

namespace {
pc::Renderer& renderer() {
    static pc::Renderer r;
    return r;
}
}  // namespace

PC_API int pc_ui_size(void) { return pc::ui_size(); }

PC_API void pc_app_default_ui(float* ui) { pc::app_default_ui(ui); }

PC_API void pc_start_ui(float* ui) { pc::start_ui(ui); }

PC_API int pc_preset_ui(int index, float* ui) { return pc::preset_ui(index, ui) ? 1 : 0; }

// Devolve 1 se leu; senão 0 e a mensagem (UTF-8) em `err` (até err_size bytes com o zero final).
PC_API int pc_load_look(const char* utf8_json, float* ui, char* err, int err_size) {
    std::string e;
    bool ok = pc::load_look_json(utf8_json ? utf8_json : "", ui, &e);
    if (!ok && err && err_size > 0) {
        std::strncpy(err, e.c_str(), (size_t)err_size - 1);
        err[err_size - 1] = '\0';
    }
    return ok ? 1 : 0;
}

// Imagens RGB float32 contíguas, linha 0 no topo.
PC_API void pc_render(const float* ui, const float* in, float* out, int w, int h, int frame, float fps,
                      int exact_color) {
    renderer().render(ui, in, out, w, h, frame, fps, exact_color);
}

PC_API void pc_color(const float* ui, const float* in, float* out, int n, int exact_color) {
    renderer().color(ui, in, out, n, exact_color);
}

PC_API float pc_lut_exact_fraction(const float* ui) { return renderer().lut_exact_fraction(ui); }

PC_API void pc_set_lut_tolerance(float tol) { renderer().set_lut_tolerance(tol); }
