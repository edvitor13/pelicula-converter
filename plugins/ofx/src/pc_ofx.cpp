// Cola OpenFX do PeliculaConverter: descreve o efeito (parâmetros gerados em pc_params.h, nos grupos
// das seções do app), aplica presets e looks .json e chama o núcleo (pc_core.cpp) a cada quadro.
// Funciona no DaVinci Resolve gratuito e no Studio (páginas Color e Edit), e em outros hosts OFX.
#include <cmath>
#include <memory>
#include <string>
#include <vector>

#include "ofxsImageEffect.h"
#include "../generated/pc_params.h"
#include "pc_core.h"

namespace {

const char* const P_PRESET = "pc_preset";
const char* const P_FILE = "pc_arquivo";
const char* const P_RELOAD = "pc_recarregar";
const char* const P_QUALITY = "pc_qualidade";
const char* const G_LOOK = "pc_grupo_look";

std::string group_name(const char* key) { return std::string("pc_grupo_") + key; }

int digits_for(double step) {
    if (step >= 1.0) return 0;
    int d = (int)std::ceil(-std::log10(step) - 1e-9);
    return d < 1 ? 1 : (d > 4 ? 4 : d);
}

class PeliculaEffect : public OFX::ImageEffect {
public:
    explicit PeliculaEffect(OfxImageEffectHandle handle) : OFX::ImageEffect(handle) {
        src_ = fetchClip(kOfxImageEffectSimpleSourceClipName);
        dst_ = fetchClip(kOfxImageEffectOutputClipName);
        params_.resize(PC_PARAM_COUNT, nullptr);
        for (int i = 0; i < PC_PARAM_COUNT; ++i) {
            const pc_param_def& p = PC_PARAMS[i];
            switch (p.kind) {
                case 0: params_[i] = fetchDoubleParam(p.name); break;
                case 1: params_[i] = fetchIntParam(p.name); break;
                case 2: params_[i] = fetchBooleanParam(p.name); break;
                case 3: params_[i] = fetchChoiceParam(p.name); break;
                default: params_[i] = fetchRGBParam(p.name); break;
            }
        }
        preset_ = fetchChoiceParam(P_PRESET);
        file_ = fetchStringParam(P_FILE);
        quality_ = fetchChoiceParam(P_QUALITY);
    }

    void render(const OFX::RenderArguments& args) override {
        std::unique_ptr<OFX::Image> dst(dst_->fetchImage(args.time));
        std::unique_ptr<OFX::Image> src(src_->fetchImage(args.time));
        if (!dst || !src) OFX::throwSuiteStatusException(kOfxStatFailed);
        OFX::BitDepthEnum depth = src->getPixelDepth();
        OFX::PixelComponentEnum comps = src->getPixelComponents();
        if (depth != dst->getPixelDepth() || comps != dst->getPixelComponents() ||
            (comps != OFX::ePixelComponentRGBA && comps != OFX::ePixelComponentRGB))
            OFX::throwSuiteStatusException(kOfxStatErrImageFormat);
        const OfxRectI b = src->getBounds();
        const int w = b.x2 - b.x1, h = b.y2 - b.y1;
        if (w <= 0 || h <= 0) return;
        const int nc = comps == OFX::ePixelComponentRGBA ? 4 : 3;

        // OFX: linha y1 embaixo; o núcleo trabalha com a linha 0 no topo (como o app).
        std::vector<float> in((size_t)w * h * 3), out((size_t)w * h * 3), alpha((size_t)w * h, 1.0f);
        for (int r = 0; r < h; ++r) {
            const void* row = src->getPixelAddress(b.x1, b.y2 - 1 - r);
            if (!row) continue;
            for (int x = 0; x < w; ++x) {
                float px[4] = {0.0f, 0.0f, 0.0f, 1.0f};
                read_pixel(row, x, nc, depth, px);
                size_t i = (size_t)r * w + x;
                in[i * 3] = px[0];
                in[i * 3 + 1] = px[1];
                in[i * 3 + 2] = px[2];
                alpha[i] = px[3];
            }
        }

        std::vector<float> ui(pc::ui_size());
        values_at(args.time, ui.data());
        int quality = 0;
        quality_->getValueAtTime(args.time, quality);
        double fps = getFrameRate();
        if (!(fps > 0.0)) fps = src_->getFrameRate();
        if (!(fps > 0.0)) fps = 24.0;
        int frame = (int)std::floor(args.time + 0.5);
        renderer_.render(ui.data(), in.data(), out.data(), w, h, frame, (float)fps, quality == 1 ? 0 : 1);

        const OfxRectI& rw = args.renderWindow;
        for (int y = rw.y1; y < rw.y2; ++y) {
            void* drow = dst->getPixelAddress(rw.x1, y);
            if (!drow) continue;
            int r = b.y2 - 1 - y;
            for (int x = rw.x1; x < rw.x2; ++x) {
                float px[4] = {0.0f, 0.0f, 0.0f, 0.0f};
                if (r >= 0 && r < h && x >= b.x1 && x < b.x2) {
                    size_t i = (size_t)r * w + (x - b.x1);
                    px[0] = out[i * 3];
                    px[1] = out[i * 3 + 1];
                    px[2] = out[i * 3 + 2];
                    px[3] = alpha[i];
                }
                write_pixel(drow, x - rw.x1, nc, depth, px);
            }
        }
    }

    bool isIdentity(const OFX::IsIdentityArguments& args, OFX::Clip*& identityClip, double& identityTime) override {
        // "Força geral" em 0 e sem a curva: devolve a imagem original sem calcular nada.
        for (int i = 0; i < PC_PARAM_COUNT; ++i) {
            const std::string name = PC_PARAMS[i].name;
            if (name == "mix_geral") {
                double v = 0.0;
                static_cast<OFX::DoubleParam*>(params_[i])->getValueAtTime(args.time, v);
                if (v > 0.0) return false;
            } else if (name == "mostrar_curva") {
                bool v = false;
                static_cast<OFX::BooleanParam*>(params_[i])->getValueAtTime(args.time, v);
                if (v) return false;
            }
        }
        identityClip = src_;
        identityTime = args.time;
        return true;
    }

    void changedParam(const OFX::InstanceChangedArgs& args, const std::string& name) override {
        if (args.reason != OFX::eChangeUserEdit) return;  // abrir um projeto não pode trocar os valores salvos
        if (name == P_PRESET) {
            int idx = 0;
            preset_->getValue(idx);
            std::vector<float> ui(pc::ui_size());
            if (pc::preset_ui(idx, ui.data())) apply(ui.data(), "Preset do PeliculaConverter");
        } else if (name == P_FILE || name == P_RELOAD) {
            std::string path;
            file_->getValue(path);
            if (path.empty()) return;
            std::vector<float> ui(pc::ui_size());
            std::string err;
            if (pc::load_look_file(path, ui.data(), &err)) {
                apply(ui.data(), "Look do PeliculaConverter (.json)");
            } else {
                // o host usa o texto como formato do printf: '%' (num caminho, por exemplo) vira "%%"
                std::string msg = "PeliculaConverter: n\303\243o foi poss\303\255vel ler o look \"" + path + "\": " + err;
                std::string safe;
                for (char c : msg) {
                    safe += c;
                    if (c == '%') safe += '%';
                }
                sendMessage(OFX::Message::eMessageError, "", safe);
            }
        }
    }

private:
    OFX::Clip* src_ = nullptr;
    OFX::Clip* dst_ = nullptr;
    std::vector<OFX::Param*> params_;
    OFX::ChoiceParam* preset_ = nullptr;
    OFX::StringParam* file_ = nullptr;
    OFX::ChoiceParam* quality_ = nullptr;
    pc::Renderer renderer_;

    static void read_pixel(const void* row, int x, int nc, OFX::BitDepthEnum depth, float* px) {
        for (int k = 0; k < nc; ++k) {
            if (depth == OFX::eBitDepthFloat) px[k] = static_cast<const float*>(row)[x * nc + k];
            else if (depth == OFX::eBitDepthUShort) px[k] = static_cast<const unsigned short*>(row)[x * nc + k] / 65535.0f;
            else px[k] = static_cast<const unsigned char*>(row)[x * nc + k] / 255.0f;
        }
    }

    static void write_pixel(void* row, int x, int nc, OFX::BitDepthEnum depth, const float* px) {
        for (int k = 0; k < nc; ++k) {
            float v = px[k];
            if (depth == OFX::eBitDepthFloat) {
                static_cast<float*>(row)[x * nc + k] = v;
            } else {
                v = v < 0.0f ? 0.0f : (v > 1.0f ? 1.0f : v);
                if (depth == OFX::eBitDepthUShort)
                    static_cast<unsigned short*>(row)[x * nc + k] = (unsigned short)(v * 65535.0f + 0.5f);
                else
                    static_cast<unsigned char*>(row)[x * nc + k] = (unsigned char)(v * 255.0f + 0.5f);
            }
        }
    }

    void values_at(double t, float* ui) {
        for (int i = 0; i < PC_PARAM_COUNT; ++i) {
            const pc_param_def& p = PC_PARAMS[i];
            float* d = ui + p.offset;
            switch (p.kind) {
                case 0: {
                    double v = 0.0;
                    static_cast<OFX::DoubleParam*>(params_[i])->getValueAtTime(t, v);
                    d[0] = (float)v;
                    break;
                }
                case 1: {
                    int v = 0;
                    static_cast<OFX::IntParam*>(params_[i])->getValueAtTime(t, v);
                    d[0] = (float)v;
                    break;
                }
                case 2: {
                    bool v = false;
                    static_cast<OFX::BooleanParam*>(params_[i])->getValueAtTime(t, v);
                    d[0] = v ? 1.0f : 0.0f;
                    break;
                }
                case 3: {
                    int v = 0;
                    static_cast<OFX::ChoiceParam*>(params_[i])->getValueAtTime(t, v);
                    d[0] = (float)(v < 0 ? 0 : (v >= p.nchoices ? p.nchoices - 1 : v));
                    break;
                }
                default: {
                    double r = 0.0, g = 0.0, bb = 0.0;
                    static_cast<OFX::RGBParam*>(params_[i])->getValueAtTime(t, r, g, bb);
                    d[0] = (float)r;
                    d[1] = (float)g;
                    d[2] = (float)bb;
                    break;
                }
            }
        }
    }

    void apply(const float* ui, const std::string& what) {
        beginEditBlock(what);
        for (int i = 0; i < PC_PARAM_COUNT; ++i) {
            const pc_param_def& p = PC_PARAMS[i];
            const float* v = ui + p.offset;
            switch (p.kind) {
                case 0: static_cast<OFX::DoubleParam*>(params_[i])->setValue(v[0]); break;
                case 1: static_cast<OFX::IntParam*>(params_[i])->setValue((int)std::floor(v[0] + 0.5f)); break;
                case 2: static_cast<OFX::BooleanParam*>(params_[i])->setValue(v[0] > 0.5f); break;
                case 3: static_cast<OFX::ChoiceParam*>(params_[i])->setValue((int)std::floor(v[0] + 0.5f)); break;
                default: static_cast<OFX::RGBParam*>(params_[i])->setValue(v[0], v[1], v[2]); break;
            }
        }
        endEditBlock();
    }
};

}  // namespace

mDeclarePluginFactory(PeliculaFactory, {}, {});

void PeliculaFactory::describe(OFX::ImageEffectDescriptor& desc) {
    desc.setLabels(PC_PLUGIN_LABEL, PC_PLUGIN_LABEL, PC_PLUGIN_LABEL);
    desc.setPluginGrouping(PC_PLUGIN_LABEL);
    desc.setPluginDescription(
        "PeliculaConverter " PC_VERSION_TEXT " - look de pel\303\255cula do app: perfil da c\303\242mera, "
        "laborat\303\263rio (negativo e c\303\263pia), cor, gr\303\243o, hala\303\247\303\243o, bloom, lente, "
        "tremor, defeitos e moldura. Escolha um preset ou carregue um look .json exportado pelo app.");
    desc.addSupportedContext(OFX::eContextFilter);
    desc.addSupportedBitDepth(OFX::eBitDepthFloat);
    desc.addSupportedBitDepth(OFX::eBitDepthUShort);
    desc.addSupportedBitDepth(OFX::eBitDepthUByte);
    desc.setSingleInstance(false);
    desc.setHostFrameThreading(false);  // o núcleo divide o quadro entre os núcleos da CPU
    desc.setSupportsMultiResolution(true);
    desc.setSupportsTiles(false);       // desfoques e brilhos precisam do quadro inteiro
    desc.setTemporalClipAccess(false);
    desc.setRenderTwiceAlways(false);
    desc.setSupportsMultipleClipPARs(false);
    desc.setRenderThreadSafety(OFX::eRenderFullySafe);
}

void PeliculaFactory::describeInContext(OFX::ImageEffectDescriptor& desc, OFX::ContextEnum) {
    OFX::ClipDescriptor* src = desc.defineClip(kOfxImageEffectSimpleSourceClipName);
    src->addSupportedComponent(OFX::ePixelComponentRGBA);
    src->addSupportedComponent(OFX::ePixelComponentRGB);
    src->setTemporalClipAccess(false);
    src->setSupportsTiles(false);
    src->setIsMask(false);
    OFX::ClipDescriptor* dst = desc.defineClip(kOfxImageEffectOutputClipName);
    dst->addSupportedComponent(OFX::ePixelComponentRGBA);
    dst->addSupportedComponent(OFX::ePixelComponentRGB);
    dst->setSupportsTiles(false);

    // Look: preset, arquivo .json e qualidade da cor
    OFX::GroupParamDescriptor* look = desc.defineGroupParam(G_LOOK);
    look->setLabels("Look", "Look", "Look");
    look->setOpen(true);
    OFX::ChoiceParamDescriptor* preset = desc.defineChoiceParam(P_PRESET);
    preset->setLabels("Preset", "Preset", "Preset");
    preset->setHint("Aplica um dos presets prontos do PeliculaConverter (troca todos os ajustes abaixo).");
    for (int i = 0; i < PC_PRESET_COUNT; ++i) preset->appendOption(PC_PRESET_NAMES[i]);
    preset->setDefault(PC_DEFAULT_PRESET);
    preset->setAnimates(false);
    preset->setEvaluateOnChange(false);
    preset->setParent(*look);
    OFX::StringParamDescriptor* file = desc.defineStringParam(P_FILE);
    file->setLabels("Carregar look do PeliculaConverter (.json)", "Look .json", "Carregar look do PeliculaConverter (.json)");
    file->setHint("Escolha um preset exportado pelo app (.json) ou um projeto .plc: os ajustes viram os deste efeito.");
    file->setStringType(OFX::eStringTypeFilePath);
    file->setFilePathExists(true);
    file->setAnimates(false);
    file->setEvaluateOnChange(false);
    file->setParent(*look);
    OFX::PushButtonParamDescriptor* reload = desc.definePushButtonParam(P_RELOAD);
    reload->setLabels("Recarregar o look", "Recarregar", "Recarregar o look");
    reload->setHint("L\303\252 de novo o arquivo .json (depois de mudar o look no app).");
    reload->setParent(*look);
    OFX::ChoiceParamDescriptor* quality = desc.defineChoiceParam(P_QUALITY);
    quality->setLabels("C\303\241lculo da cor", "C\303\241lculo da cor", "C\303\241lculo da cor");
    quality->setHint("Exato: a mesma conta do app em cada pixel. R\303\241pido: a cor passa por um LUT 65\302\263 "
                     "montado com a mesma conta (diferen\303\247a de at\303\251 meio n\303\255vel de 8 bits), bom "
                     "para a pr\303\251via; o gr\303\243o, os brilhos e os defeitos n\303\243o mudam.");
    quality->appendOption("Exato (igual ao app)");
    quality->appendOption("R\303\241pido (pr\303\251via)");
    quality->setDefault(0);
    quality->setAnimates(false);
    quality->setParent(*look);

    std::vector<OFX::GroupParamDescriptor*> groups;
    for (int g = 0; g < PC_GROUP_COUNT; ++g) {
        OFX::GroupParamDescriptor* gp = desc.defineGroupParam(group_name(PC_GROUP_KEYS[g]));
        gp->setLabels(PC_GROUP_TITLES[g], PC_GROUP_TITLES[g], PC_GROUP_TITLES[g]);
        gp->setOpen(false);
        groups.push_back(gp);
    }
    for (int i = 0; i < PC_PARAM_COUNT; ++i) {
        const pc_param_def& p = PC_PARAMS[i];
        OFX::ValueParamDescriptor* d = nullptr;
        switch (p.kind) {
            case 0: {
                OFX::DoubleParamDescriptor* x = desc.defineDoubleParam(p.name);
                x->setDoubleType(OFX::eDoubleTypePlain);
                x->setDefault(p.def[0]);
                x->setRange(p.lo, p.hi);
                x->setDisplayRange(p.lo, p.hi);
                x->setIncrement(p.step);
                x->setDigits(digits_for(p.step));
                d = x;
                break;
            }
            case 1: {
                OFX::IntParamDescriptor* x = desc.defineIntParam(p.name);
                x->setDefault((int)p.def[0]);
                x->setRange((int)p.lo, (int)p.hi);
                x->setDisplayRange((int)p.lo, (int)p.hi);
                d = x;
                break;
            }
            case 2: {
                OFX::BooleanParamDescriptor* x = desc.defineBooleanParam(p.name);
                x->setDefault(p.def[0] > 0.5);
                d = x;
                break;
            }
            case 3: {
                OFX::ChoiceParamDescriptor* x = desc.defineChoiceParam(p.name);
                for (int k = 0; k < p.nchoices; ++k) x->appendOption(p.choice_labels[k]);
                x->setDefault((int)p.def[0]);
                d = x;
                break;
            }
            default: {
                OFX::RGBParamDescriptor* x = desc.defineRGBParam(p.name);
                x->setDefault(p.def[0], p.def[1], p.def[2]);
                d = x;
                break;
            }
        }
        d->setLabels(p.label, p.label, p.label);
        d->setHint(p.hint);
        for (int g = 0; g < PC_GROUP_COUNT; ++g)
            if (std::string(PC_GROUP_KEYS[g]) == p.group) d->setParent(*groups[g]);
    }
}

OFX::ImageEffect* PeliculaFactory::createInstance(OfxImageEffectHandle handle, OFX::ContextEnum) {
    return new PeliculaEffect(handle);
}

namespace OFX {
namespace Plugin {
void getPluginIDs(OFX::PluginFactoryArray& ids) {
    static PeliculaFactory p(PC_PLUGIN_ID, PC_VERSION_MAJOR, PC_VERSION_MINOR);
    ids.push_back(&p);
}
}  // namespace Plugin
}  // namespace OFX
