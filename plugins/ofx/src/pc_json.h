// Leitor de JSON mínimo para os looks do PeliculaConverter (.json de preset e projeto .plc).
// Só o necessário: objetos, listas, textos (com \uXXXX), números, true/false/null.
#pragma once

#include <locale>
#include <map>
#include <sstream>
#include <string>
#include <vector>

namespace pc {
namespace json {

struct Value {
    enum Type { Null, Bool, Number, String, Array, Object } type = Null;
    bool b = false;
    double num = 0.0;
    std::string str;
    std::vector<Value> arr;
    std::map<std::string, Value> obj;

    const Value* get(const std::string& k) const {
        if (type != Object) return nullptr;
        auto it = obj.find(k);
        return it == obj.end() ? nullptr : &it->second;
    }
};

class Parser {
public:
    explicit Parser(const std::string& text) : s_(text), i_(0) {}

    bool parse(Value* out, std::string* err) {
        skip_bom();
        if (!value(out, 0)) {
            if (err) *err = err_.empty() ? "JSON invalido" : err_;
            return false;
        }
        ws();
        if (i_ != s_.size()) {
            if (err) *err = "texto sobrando depois do JSON";
            return false;
        }
        return true;
    }

private:
    const std::string& s_;
    size_t i_;
    std::string err_;

    void skip_bom() {
        if (s_.size() >= 3 && (unsigned char)s_[0] == 0xEF && (unsigned char)s_[1] == 0xBB &&
            (unsigned char)s_[2] == 0xBF)
            i_ = 3;
    }
    void ws() {
        while (i_ < s_.size() && (s_[i_] == ' ' || s_[i_] == '\t' || s_[i_] == '\n' || s_[i_] == '\r')) ++i_;
    }
    bool fail(const char* m) {
        if (err_.empty()) err_ = std::string(m) + " (posicao " + std::to_string(i_) + ")";
        return false;
    }
    bool lit(const char* w) {
        size_t n = std::string(w).size();
        if (s_.compare(i_, n, w) != 0) return false;
        i_ += n;
        return true;
    }
    static void put_utf8(std::string& o, unsigned cp) {
        if (cp < 0x80) {
            o += (char)cp;
        } else if (cp < 0x800) {
            o += (char)(0xC0 | (cp >> 6));
            o += (char)(0x80 | (cp & 0x3F));
        } else if (cp < 0x10000) {
            o += (char)(0xE0 | (cp >> 12));
            o += (char)(0x80 | ((cp >> 6) & 0x3F));
            o += (char)(0x80 | (cp & 0x3F));
        } else {
            o += (char)(0xF0 | (cp >> 18));
            o += (char)(0x80 | ((cp >> 12) & 0x3F));
            o += (char)(0x80 | ((cp >> 6) & 0x3F));
            o += (char)(0x80 | (cp & 0x3F));
        }
    }
    bool hex4(unsigned* v) {
        if (i_ + 4 > s_.size()) return false;
        unsigned r = 0;
        for (int k = 0; k < 4; ++k) {
            char c = s_[i_++];
            r <<= 4;
            if (c >= '0' && c <= '9') r |= (unsigned)(c - '0');
            else if (c >= 'a' && c <= 'f') r |= (unsigned)(c - 'a' + 10);
            else if (c >= 'A' && c <= 'F') r |= (unsigned)(c - 'A' + 10);
            else return false;
        }
        *v = r;
        return true;
    }
    bool string(std::string* o) {
        ++i_;  // "
        while (i_ < s_.size()) {
            char c = s_[i_++];
            if (c == '"') return true;
            if (c != '\\') {
                *o += c;
                continue;
            }
            if (i_ >= s_.size()) break;
            char e = s_[i_++];
            switch (e) {
                case '"': *o += '"'; break;
                case '\\': *o += '\\'; break;
                case '/': *o += '/'; break;
                case 'b': *o += '\b'; break;
                case 'f': *o += '\f'; break;
                case 'n': *o += '\n'; break;
                case 'r': *o += '\r'; break;
                case 't': *o += '\t'; break;
                case 'u': {
                    unsigned cp;
                    if (!hex4(&cp)) return fail("escape \\u invalido");
                    if (cp >= 0xD800 && cp < 0xDC00 && i_ + 6 <= s_.size() && s_[i_] == '\\' && s_[i_ + 1] == 'u') {
                        i_ += 2;
                        unsigned lo;
                        if (!hex4(&lo)) return fail("escape \\u invalido");
                        cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
                    }
                    put_utf8(*o, cp);
                    break;
                }
                default: return fail("escape invalido");
            }
        }
        return fail("texto sem fim");
    }
    bool value(Value* v, int depth) {
        if (depth > 64) return fail("JSON fundo demais");
        ws();
        if (i_ >= s_.size()) return fail("fim inesperado");
        char c = s_[i_];
        if (c == '{') {
            v->type = Value::Object;
            ++i_;
            ws();
            if (i_ < s_.size() && s_[i_] == '}') {
                ++i_;
                return true;
            }
            for (;;) {
                ws();
                if (i_ >= s_.size() || s_[i_] != '"') return fail("esperava uma chave");
                std::string k;
                if (!string(&k)) return false;
                ws();
                if (i_ >= s_.size() || s_[i_] != ':') return fail("esperava ':'");
                ++i_;
                Value item;
                if (!value(&item, depth + 1)) return false;
                v->obj[k] = std::move(item);
                ws();
                if (i_ < s_.size() && s_[i_] == ',') {
                    ++i_;
                    continue;
                }
                if (i_ < s_.size() && s_[i_] == '}') {
                    ++i_;
                    return true;
                }
                return fail("esperava ',' ou '}'");
            }
        }
        if (c == '[') {
            v->type = Value::Array;
            ++i_;
            ws();
            if (i_ < s_.size() && s_[i_] == ']') {
                ++i_;
                return true;
            }
            for (;;) {
                Value item;
                if (!value(&item, depth + 1)) return false;
                v->arr.push_back(std::move(item));
                ws();
                if (i_ < s_.size() && s_[i_] == ',') {
                    ++i_;
                    continue;
                }
                if (i_ < s_.size() && s_[i_] == ']') {
                    ++i_;
                    return true;
                }
                return fail("esperava ',' ou ']'");
            }
        }
        if (c == '"') {
            v->type = Value::String;
            return string(&v->str);
        }
        if (lit("true")) {
            v->type = Value::Bool;
            v->b = true;
            return true;
        }
        if (lit("false")) {
            v->type = Value::Bool;
            v->b = false;
            return true;
        }
        if (lit("null")) {
            v->type = Value::Null;
            return true;
        }
        if (c == '-' || (c >= '0' && c <= '9')) {
            size_t j = i_;
            while (j < s_.size() && (s_[j] == '-' || s_[j] == '+' || s_[j] == '.' || s_[j] == 'e' || s_[j] == 'E' ||
                                     (s_[j] >= '0' && s_[j] <= '9')))
                ++j;
            // istringstream na localidade "C": o host pode ter trocado o separador decimal
            std::istringstream is(s_.substr(i_, j - i_));
            is.imbue(std::locale::classic());
            v->type = Value::Number;
            is >> v->num;
            if (is.fail() || is.peek() != std::char_traits<char>::eof()) return fail("numero invalido");
            i_ = j;
            return true;
        }
        return fail("valor invalido");
    }
};

}  // namespace json
}  // namespace pc
