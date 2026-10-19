"""Host OpenFX mínimo em ctypes, só para os testes do plugin (tests/test_ofx.py).

Faz o que um editor (DaVinci Resolve, Natron...) faz com o binário: carrega, descreve o efeito no
contexto "filter", cria uma instância com os parâmetros declarados, troca valores, dispara
changedParam e renderiza quadros RGBA float com a origem embaixo (como o OpenFX manda). Os nomes das
propriedades vêm dos próprios cabeçalhos do OpenFX em plugins/ofx/openfx/include.
"""

from __future__ import annotations

import ctypes
import re
import struct
import sys
from ctypes import (CFUNCTYPE, POINTER, Structure, c_char_p, c_double, c_int, c_int64, c_size_t, c_uint, c_void_p)
from pathlib import Path

import numpy as np

INCLUDE = Path(__file__).resolve().parents[1] / "plugins" / "ofx" / "openfx" / "include"


def _defines() -> dict[str, str]:
    out = {}
    for h in INCLUDE.glob("*.h"):
        for m in re.finditer(r'#define\s+(kOfx\w+)\s+"([^"]*)"', h.read_text(encoding="utf-8", errors="replace")):
            out.setdefault(m.group(1), m.group(2))
    return out


K = _defines()
OK, FAILED, UNKNOWN, BADHANDLE, BADINDEX, REPLY_DEFAULT = 0, 1, 3, 9, 10, 14

OfxStatus = c_int
H = c_void_p


class OfxRectD(Structure):
    _fields_ = [("x1", c_double), ("y1", c_double), ("x2", c_double), ("y2", c_double)]


class OfxHostStruct(Structure):
    _fields_ = [("host", c_void_p), ("fetchSuite", CFUNCTYPE(c_void_p, c_void_p, c_char_p, c_int))]


ENTRY = CFUNCTYPE(OfxStatus, c_char_p, c_void_p, c_void_p, c_void_p)


class OfxPluginStruct(Structure):
    _fields_ = [("pluginApi", c_char_p), ("apiVersion", c_int), ("pluginIdentifier", c_char_p),
                ("pluginVersionMajor", c_uint), ("pluginVersionMinor", c_uint),
                ("setHost", CFUNCTYPE(None, POINTER(OfxHostStruct))), ("mainEntry", ENTRY)]


def _suite(name: str, fields: list[tuple[str, object]]):
    return type(name, (Structure,), {"_fields_": fields})


F = CFUNCTYPE
PropSuite = _suite("PropSuite", [
    ("propSetPointer", F(OfxStatus, H, c_char_p, c_int, c_void_p)),
    ("propSetString", F(OfxStatus, H, c_char_p, c_int, c_char_p)),
    ("propSetDouble", F(OfxStatus, H, c_char_p, c_int, c_double)),
    ("propSetInt", F(OfxStatus, H, c_char_p, c_int, c_int)),
    ("propSetPointerN", F(OfxStatus, H, c_char_p, c_int, POINTER(c_void_p))),
    ("propSetStringN", F(OfxStatus, H, c_char_p, c_int, POINTER(c_char_p))),
    ("propSetDoubleN", F(OfxStatus, H, c_char_p, c_int, POINTER(c_double))),
    ("propSetIntN", F(OfxStatus, H, c_char_p, c_int, POINTER(c_int))),
    ("propGetPointer", F(OfxStatus, H, c_char_p, c_int, POINTER(c_void_p))),
    ("propGetString", F(OfxStatus, H, c_char_p, c_int, POINTER(c_void_p))),
    ("propGetDouble", F(OfxStatus, H, c_char_p, c_int, POINTER(c_double))),
    ("propGetInt", F(OfxStatus, H, c_char_p, c_int, POINTER(c_int))),
    ("propGetPointerN", F(OfxStatus, H, c_char_p, c_int, POINTER(c_void_p))),
    ("propGetStringN", F(OfxStatus, H, c_char_p, c_int, POINTER(c_void_p))),
    ("propGetDoubleN", F(OfxStatus, H, c_char_p, c_int, POINTER(c_double))),
    ("propGetIntN", F(OfxStatus, H, c_char_p, c_int, POINTER(c_int))),
    ("propReset", F(OfxStatus, H, c_char_p)),
    ("propGetDimension", F(OfxStatus, H, c_char_p, POINTER(c_int))),
])
EffectSuite = _suite("EffectSuite", [
    ("getPropertySet", F(OfxStatus, H, POINTER(c_void_p))),
    ("getParamSet", F(OfxStatus, H, POINTER(c_void_p))),
    ("clipDefine", F(OfxStatus, H, c_char_p, POINTER(c_void_p))),
    ("clipGetHandle", F(OfxStatus, H, c_char_p, POINTER(c_void_p), POINTER(c_void_p))),
    ("clipGetPropertySet", F(OfxStatus, H, POINTER(c_void_p))),
    ("clipGetImage", F(OfxStatus, H, c_double, POINTER(OfxRectD), POINTER(c_void_p))),
    ("clipReleaseImage", F(OfxStatus, H)),
    ("clipGetRegionOfDefinition", F(OfxStatus, H, c_double, POINTER(OfxRectD))),
    ("abort", F(c_int, H)),
    ("imageMemoryAlloc", F(OfxStatus, H, c_size_t, POINTER(c_void_p))),
    ("imageMemoryFree", F(OfxStatus, H)),
    ("imageMemoryLock", F(OfxStatus, H, POINTER(c_void_p))),
    ("imageMemoryUnlock", F(OfxStatus, H)),
])
# Funções com argumentos variáveis: ponteiros vão nos registradores inteiros nos dois ABIs; valores
# double ficam nos inteiros no Windows x64 e nos XMM no Linux, por isso setValue recebe os dois.
ParamSuite = _suite("ParamSuite", [
    ("paramDefine", F(OfxStatus, H, c_char_p, c_char_p, POINTER(c_void_p))),
    ("paramGetHandle", F(OfxStatus, H, c_char_p, POINTER(c_void_p), POINTER(c_void_p))),
    ("paramSetGetPropertySet", F(OfxStatus, H, POINTER(c_void_p))),
    ("paramGetPropertySet", F(OfxStatus, H, POINTER(c_void_p))),
    ("paramGetValue", F(OfxStatus, H, c_void_p, c_void_p, c_void_p, c_void_p)),
    ("paramGetValueAtTime", F(OfxStatus, H, c_double, c_void_p, c_void_p, c_void_p, c_void_p)),
    ("paramGetDerivative", F(OfxStatus, H, c_double, c_void_p, c_void_p, c_void_p)),
    ("paramGetIntegral", F(OfxStatus, H, c_double, c_double, c_void_p, c_void_p, c_void_p)),
    ("paramSetValue", F(OfxStatus, H, c_int64, c_int64, c_int64, c_double, c_double, c_double)),
    ("paramSetValueAtTime", F(OfxStatus, H, c_double, c_int64, c_int64, c_int64)),
    ("paramGetNumKeys", F(OfxStatus, H, POINTER(c_uint))),
    ("paramGetKeyTime", F(OfxStatus, H, c_uint, POINTER(c_double))),
    ("paramGetKeyIndex", F(OfxStatus, H, c_double, c_int, POINTER(c_int))),
    ("paramDeleteKey", F(OfxStatus, H, c_double)),
    ("paramDeleteAllKeys", F(OfxStatus, H)),
    ("paramCopy", F(OfxStatus, H, H, c_double, c_void_p)),
    ("paramEditBegin", F(OfxStatus, H, c_char_p)),
    ("paramEditEnd", F(OfxStatus, H)),
])
MemorySuite = _suite("MemorySuite", [
    ("memoryAlloc", F(OfxStatus, c_void_p, c_size_t, POINTER(c_void_p))),
    ("memoryFree", F(OfxStatus, c_void_p)),
])
ThreadSuite = _suite("ThreadSuite", [
    ("multiThread", F(OfxStatus, CFUNCTYPE(None, c_uint, c_uint, c_void_p), c_uint, c_void_p)),
    ("multiThreadNumCPUs", F(OfxStatus, POINTER(c_uint))),
    ("multiThreadIndex", F(OfxStatus, POINTER(c_uint))),
    ("multiThreadIsSpawnedThread", F(c_int)),
    ("mutexCreate", F(OfxStatus, POINTER(c_void_p), c_int)),
    ("mutexDestroy", F(OfxStatus, c_void_p)),
    ("mutexLock", F(OfxStatus, c_void_p)),
    ("mutexUnLock", F(OfxStatus, c_void_p)),
    ("mutexTryLock", F(OfxStatus, c_void_p)),
])
MessageSuite = _suite("MessageSuite", [("message", F(OfxStatus, c_void_p, c_char_p, c_char_p, c_char_p))])
InteractSuite = _suite("InteractSuite", [
    ("interactSwapBuffers", F(OfxStatus, c_void_p)),
    ("interactRedraw", F(OfxStatus, c_void_p)),
    ("interactGetPropertySet", F(OfxStatus, c_void_p, POINTER(c_void_p))),
])


def _as_double(bits: int) -> float:
    return struct.unpack("<d", struct.pack("<q", bits))[0]


class PropSet(dict):
    """Propriedades: nome → lista de valores (str, int, float ou ponteiro)."""


class Param:
    def __init__(self, ptype: str, props: PropSet):
        self.type = ptype
        self.props = props
        self.value: list = []


class Host:
    def __init__(self, binary: str | Path, frame_rate: float = 24.0):
        self.lib = ctypes.CDLL(str(binary))
        self.lib.OfxGetPlugin.restype = POINTER(OfxPluginStruct)
        self.lib.OfxGetPlugin.argtypes = [c_int]
        self.objects: dict[int, object] = {}
        self._ids: dict[int, int] = {}
        self.strings: list = []
        self.missing: set[str] = set()
        self.messages: list[tuple[str, str]] = []
        self.edits: list[str] = []
        self.frame_rate = frame_rate
        self.images: dict[int, tuple[PropSet, np.ndarray]] = {}
        self.source: np.ndarray | None = None
        self.output: np.ndarray | None = None
        self._keep: list = []
        self._next = 1000
        self.host_props = self.new_props(**{
            "kOfxPropName": "com.peliculaconverter.testhost", "kOfxPropLabel": "Host de teste",
            "kOfxPropAPIVersion": [1, 4], "kOfxPropVersion": [1, 0, 0], "kOfxPropVersionLabel": "1.0",
            "kOfxImageEffectHostPropIsBackground": 0, "kOfxImageEffectPropSupportsOverlays": 0,
            "kOfxImageEffectPropSupportsMultiResolution": 1, "kOfxImageEffectPropSupportsTiles": 1,
            "kOfxImageEffectPropTemporalClipAccess": 0, "kOfxImageEffectPropSupportsMultipleClipDepths": 0,
            "kOfxImageEffectPropSupportsMultipleClipPARs": 0, "kOfxImageEffectPropSetableFrameRate": 0,
            "kOfxImageEffectPropSetableFielding": 0, "kOfxImageEffectInstancePropSequentialRender": 0,
            "kOfxParamHostPropSupportsStringAnimation": 0, "kOfxParamHostPropSupportsCustomInteract": 0,
            "kOfxParamHostPropSupportsChoiceAnimation": 1, "kOfxParamHostPropSupportsBooleanAnimation": 1,
            "kOfxParamHostPropSupportsCustomAnimation": 0, "kOfxParamHostPropMaxParameters": -1,
            "kOfxParamHostPropMaxPages": 0, "kOfxParamHostPropPageRowColumnCount": [0, 0],
            "kOfxImageEffectPropSupportedComponents": [K["kOfxImageComponentRGBA"], K["kOfxImageComponentRGB"]],
            "kOfxImageEffectPropSupportedContexts": [K["kOfxImageEffectContextFilter"]],
            "kOfxImageEffectPropSupportedPixelDepths": [K["kOfxBitDepthFloat"]],
            "kOfxImageEffectPropRenderQualityDraft": 0,
            "kOfxImageEffectHostPropNativeOrigin": K["kOfxHostNativeOriginBottomLeft"],
        })
        self._build_suites()
        self.host = OfxHostStruct(self.handle(self.host_props), self._fetch)
        n = self.lib.OfxGetNumberOfPlugins()
        assert n == 1, n
        self.plugin = self.lib.OfxGetPlugin(0).contents
        self.plugin.setHost(ctypes.byref(self.host))
        self.descriptor = None
        self.instance = None

    # ------------------------------------------------------------ objetos e propriedades
    def handle(self, obj) -> int:
        h = self._ids.get(id(obj))
        if h is not None and self.objects.get(h) is obj:
            return h
        self._next += 16
        self.objects[self._next] = obj
        self._ids[id(obj)] = self._next
        return self._next

    def obj(self, h):
        return self.objects.get(int(h or 0))

    def new_props(self, **named) -> PropSet:
        p = PropSet()
        for k, v in named.items():
            p[K.get(k, k)] = list(v) if isinstance(v, (list, tuple)) else [v]
        return p

    def _cstr(self, s: str) -> int:
        buf = ctypes.create_string_buffer(s.encode("utf-8"))
        self.strings.append(buf)
        return ctypes.addressof(buf)

    def _build_suites(self):
        def guard(fn, fail=FAILED):
            def wrapped(*a):
                try:
                    return fn(*a)
                except Exception as exc:  # noqa: BLE001 - erro no host de teste vira status de falha
                    print("ofxhost:", fn.__name__, exc, file=sys.stderr)
                    return fail
            wrapped.__name__ = fn.__name__
            return wrapped

        def ps(h):
            o = self.obj(h)
            if not isinstance(o, PropSet):
                raise KeyError(f"handle {h} não é um conjunto de propriedades")
            return o

        def set_one(h, name, idx, value):
            p = ps(h)
            vals = p.setdefault(name.decode(), [])
            while len(vals) <= idx:
                vals.append(None)
            vals[idx] = value
            return OK

        def get_one(h, name, idx):
            p = ps(h)
            key = name.decode()
            if key not in p:
                self.missing.add(key)
                return None, UNKNOWN
            if idx >= len(p[key]):
                return None, BADINDEX
            return p[key][idx], OK

        def propSetPointer(h, n, i, v):
            return set_one(h, n, i, int(v or 0))

        def propSetString(h, n, i, v):
            return set_one(h, n, i, (v or b"").decode("utf-8"))

        def propSetDouble(h, n, i, v):
            return set_one(h, n, i, float(v))

        def propSetInt(h, n, i, v):
            return set_one(h, n, i, int(v))

        def setN(conv):
            def f(h, n, count, arr):
                ps(h)[n.decode()] = [conv(arr[i]) for i in range(count)]
                return OK
            return f

        def getter(store):
            def f(h, n, i, out):
                v, st = get_one(h, n, i)
                if st != OK:
                    return st
                out[0] = store(v)
                return OK
            return f

        def getN(store):
            def f(h, n, count, out):
                for i in range(count):
                    v, st = get_one(h, n, i)
                    if st != OK:
                        return st
                    out[i] = store(v)
                return OK
            return f

        def as_str(v):
            return self._cstr(v if isinstance(v, str) else str(v))

        def as_int(v):
            return int(v) if not isinstance(v, str) else int(v == "true")

        def propReset(h, n):
            return OK

        def propGetDimension(h, n, out):
            # como num host de verdade, propriedades com várias entradas começam vazias (dimensão 0)
            out[0] = len(ps(h).get(n.decode(), []))
            return OK

        self.prop_suite = PropSuite(
            F(OfxStatus, H, c_char_p, c_int, c_void_p)(guard(propSetPointer)),
            F(OfxStatus, H, c_char_p, c_int, c_char_p)(guard(propSetString)),
            F(OfxStatus, H, c_char_p, c_int, c_double)(guard(propSetDouble)),
            F(OfxStatus, H, c_char_p, c_int, c_int)(guard(propSetInt)),
            F(OfxStatus, H, c_char_p, c_int, POINTER(c_void_p))(guard(setN(lambda x: int(x or 0)))),
            F(OfxStatus, H, c_char_p, c_int, POINTER(c_char_p))(guard(setN(lambda x: (x or b"").decode("utf-8")))),
            F(OfxStatus, H, c_char_p, c_int, POINTER(c_double))(guard(setN(float))),
            F(OfxStatus, H, c_char_p, c_int, POINTER(c_int))(guard(setN(int))),
            F(OfxStatus, H, c_char_p, c_int, POINTER(c_void_p))(guard(getter(lambda v: int(v or 0)))),
            F(OfxStatus, H, c_char_p, c_int, POINTER(c_void_p))(guard(getter(as_str))),
            F(OfxStatus, H, c_char_p, c_int, POINTER(c_double))(guard(getter(float))),
            F(OfxStatus, H, c_char_p, c_int, POINTER(c_int))(guard(getter(as_int))),
            F(OfxStatus, H, c_char_p, c_int, POINTER(c_void_p))(guard(getN(lambda v: int(v or 0)))),
            F(OfxStatus, H, c_char_p, c_int, POINTER(c_void_p))(guard(getN(as_str))),
            F(OfxStatus, H, c_char_p, c_int, POINTER(c_double))(guard(getN(float))),
            F(OfxStatus, H, c_char_p, c_int, POINTER(c_int))(guard(getN(as_int))),
            F(OfxStatus, H, c_char_p)(guard(propReset)),
            F(OfxStatus, H, c_char_p, POINTER(c_int))(guard(propGetDimension)),
        )

        # ---------------- efeito e clipes
        def getPropertySet(h, out):
            out[0] = self.handle(self.obj(h)["props"])
            return OK

        def getParamSet(h, out):
            out[0] = self.handle(self.obj(h)["params"])
            return OK

        def clipDefine(h, name, out):
            eff = self.obj(h)
            props = self.new_props(kOfxPropType=K["kOfxTypeClip"], kOfxPropName=name.decode())
            eff["clips"][name.decode()] = props
            out[0] = self.handle(props)
            return OK

        def clipGetHandle(h, name, clip_out, props_out):
            eff = self.obj(h)
            props = eff["clips"].get(name.decode())
            if props is None:
                return UNKNOWN
            clip_out[0] = self.handle(props)
            if props_out:
                props_out[0] = self.handle(props)
            return OK

        def clipGetPropertySet(h, out):
            out[0] = int(h)
            return OK

        def clipGetImage(h, t, region, out):
            props = self.obj(h)
            name = props[K["kOfxPropName"]][0]
            data = self.source if name == K["kOfxImageEffectSimpleSourceClipName"] else self.output
            if data is None:
                return FAILED
            hh, ww = data.shape[:2]
            img = self.new_props(**{
                "kOfxPropType": K["kOfxTypeImage"], "kOfxImagePropData": data.ctypes.data,
                "kOfxImagePropBounds": [0, 0, ww, hh], "kOfxImagePropRegionOfDefinition": [0, 0, ww, hh],
                "kOfxImagePropRowBytes": data.strides[0], "kOfxImageEffectPropPixelDepth": K["kOfxBitDepthFloat"],
                "kOfxImageEffectPropComponents": K["kOfxImageComponentRGBA"], "kOfxImagePropPixelAspectRatio": 1.0,
                "kOfxImageEffectPropRenderScale": [1.0, 1.0], "kOfxImagePropField": K["kOfxImageFieldNone"],
                "kOfxImagePropUniqueIdentifier": f"{name}-{t}",
                "kOfxImageEffectPropPreMultiplication": K["kOfxImageUnPreMultiplied"]})
            out[0] = self.handle(img)
            return OK

        def clipReleaseImage(h):
            self.objects.pop(int(h), None)
            return OK

        def clipGetRegionOfDefinition(h, t, out):
            data = self.source
            out[0] = OfxRectD(0, 0, data.shape[1], data.shape[0])
            return OK

        def abort(h):
            return 0

        def imageMemoryAlloc(h, n, out):
            buf = ctypes.create_string_buffer(int(n))
            self._keep.append(buf)
            out[0] = self.handle(buf)
            return OK

        def imageMemoryFree(h):
            return OK

        def imageMemoryLock(h, out):
            out[0] = ctypes.addressof(self.obj(h))
            return OK

        def imageMemoryUnlock(h):
            return OK

        self.effect_suite = EffectSuite(*[
            ftype(guard(fn)) for ftype, fn in zip([f[1] for f in EffectSuite._fields_], [
                getPropertySet, getParamSet, clipDefine, clipGetHandle, clipGetPropertySet, clipGetImage,
                clipReleaseImage, clipGetRegionOfDefinition, abort, imageMemoryAlloc, imageMemoryFree,
                imageMemoryLock, imageMemoryUnlock])])

        # ---------------- parâmetros
        def paramDefine(h, ptype, name, out):
            pset = self.obj(h)
            props = self.new_props(kOfxPropName=name.decode(), kOfxParamPropType=ptype.decode())
            pset["defs"][name.decode()] = Param(ptype.decode(), props)
            pset["order"].append(name.decode())
            if out:
                out[0] = self.handle(props)
            return OK

        def paramGetHandle(h, name, out, props_out):
            pset = self.obj(h)
            p = pset["defs"].get(name.decode())
            if p is None:
                return UNKNOWN
            out[0] = self.handle(p)
            if props_out:
                props_out[0] = self.handle(p.props)
            return OK

        def paramSetGetPropertySet(h, out):
            pset = self.obj(h)
            out[0] = self.handle(pset["props"])
            return OK

        def paramGetPropertySet(h, out):
            out[0] = self.handle(self.obj(h).props)
            return OK

        def write_value(p: Param, ptrs):
            t = p.type
            if t in (K["kOfxParamTypeDouble"],):
                ctypes.cast(ptrs[0], POINTER(c_double))[0] = float(p.value[0])
            elif t in (K["kOfxParamTypeInteger"], K["kOfxParamTypeChoice"], K["kOfxParamTypeBoolean"]):
                ctypes.cast(ptrs[0], POINTER(c_int))[0] = int(p.value[0])
            elif t == K["kOfxParamTypeRGB"]:
                for i in range(3):
                    ctypes.cast(ptrs[i], POINTER(c_double))[0] = float(p.value[i])
            elif t == K["kOfxParamTypeString"]:
                ctypes.cast(ptrs[0], POINTER(c_void_p))[0] = self._cstr(p.value[0])
            else:
                return FAILED
            return OK

        def paramGetValue(h, a, b, c, d):
            return write_value(self.obj(h), [a, b, c, d])

        def paramGetValueAtTime(h, t, a, b, c, d):
            return write_value(self.obj(h), [a, b, c, d])

        def paramGetDerivative(h, t, a, b, c):
            return FAILED

        def paramGetIntegral(h, t1, t2, a, b, c):
            return FAILED

        def paramSetValue(h, i1, i2, i3, d1, d2, d3):
            p: Param = self.obj(h)
            win = sys.platform == "win32"
            if p.type == K["kOfxParamTypeDouble"]:
                p.value = [_as_double(i1) if win else d1]
            elif p.type == K["kOfxParamTypeRGB"]:
                p.value = [_as_double(i1), _as_double(i2), _as_double(i3)] if win else [d1, d2, d3]
            elif p.type in (K["kOfxParamTypeInteger"], K["kOfxParamTypeChoice"], K["kOfxParamTypeBoolean"]):
                p.value = [ctypes.c_int32(i1 & 0xFFFFFFFF).value]
            elif p.type == K["kOfxParamTypeString"]:
                p.value = [ctypes.c_char_p(i1).value.decode("utf-8")]
            else:
                return FAILED
            return OK

        def paramSetValueAtTime(h, t, i1, i2, i3):
            return FAILED

        def paramGetNumKeys(h, out):
            out[0] = 0
            return OK

        def paramGetKeyTime(h, n, out):
            return BADINDEX

        def paramGetKeyIndex(h, t, d, out):
            return FAILED

        def paramDeleteKey(h, t):
            return OK

        def paramDeleteAllKeys(h):
            return OK

        def paramCopy(a, b, t, r):
            return OK

        def paramEditBegin(h, name):
            self.edits.append((name or b"").decode("utf-8"))
            return OK

        def paramEditEnd(h):
            return OK

        self.param_suite = ParamSuite(*[
            ftype(guard(fn)) for ftype, fn in zip([f[1] for f in ParamSuite._fields_], [
                paramDefine, paramGetHandle, paramSetGetPropertySet, paramGetPropertySet, paramGetValue,
                paramGetValueAtTime, paramGetDerivative, paramGetIntegral, paramSetValue, paramSetValueAtTime,
                paramGetNumKeys, paramGetKeyTime, paramGetKeyIndex, paramDeleteKey, paramDeleteAllKeys, paramCopy,
                paramEditBegin, paramEditEnd])])

        # ---------------- memória, threads, mensagens, interação
        def memoryAlloc(h, n, out):
            buf = ctypes.create_string_buffer(int(n))
            self._keep.append(buf)
            out[0] = ctypes.addressof(buf)
            return OK

        def memoryFree(p):
            return OK

        self.memory_suite = MemorySuite(F(OfxStatus, c_void_p, c_size_t, POINTER(c_void_p))(guard(memoryAlloc)),
                                        F(OfxStatus, c_void_p)(guard(memoryFree)))

        def multiThread(fn, n, arg):
            for i in range(max(1, n)):
                fn(i, max(1, n), arg)
            return OK

        def numCPUs(out):
            out[0] = 1
            return OK

        def index(out):
            out[0] = 0
            return OK

        def spawned():
            return 0

        def mutexCreate(out, count):
            out[0] = self.handle(object())
            return OK

        def mutexNop(m):
            return OK

        self.thread_suite = ThreadSuite(*[
            ftype(guard(fn)) for ftype, fn in zip([f[1] for f in ThreadSuite._fields_], [
                multiThread, numCPUs, index, spawned, mutexCreate, mutexNop, mutexNop, mutexNop, mutexNop])])

        def message(h, mtype, mid, fmt):
            self.messages.append(((mtype or b"").decode(), (fmt or b"").decode("utf-8", "replace")))
            return OK

        self.message_suite = MessageSuite(F(OfxStatus, c_void_p, c_char_p, c_char_p, c_char_p)(guard(message)))

        def interactNop(h):
            return OK

        def interactProps(h, out):
            return FAILED

        self.interact_suite = InteractSuite(F(OfxStatus, c_void_p)(interactNop), F(OfxStatus, c_void_p)(interactNop),
                                            F(OfxStatus, c_void_p, POINTER(c_void_p))(interactProps))

        suites = {
            (K["kOfxPropertySuite"], 1): self.prop_suite, (K["kOfxImageEffectSuite"], 1): self.effect_suite,
            (K["kOfxParameterSuite"], 1): self.param_suite, (K["kOfxMemorySuite"], 1): self.memory_suite,
            (K["kOfxMultiThreadSuite"], 1): self.thread_suite, (K["kOfxMessageSuite"], 1): self.message_suite,
            (K["kOfxInteractSuite"], 1): self.interact_suite,
        }

        def fetch(host, name, version):
            s = suites.get(((name or b"").decode(), version))
            return ctypes.addressof(s) if s is not None else None

        self._fetch = CFUNCTYPE(c_void_p, c_void_p, c_char_p, c_int)(fetch)

    # ------------------------------------------------------------ ações
    def action(self, name: str, handle: int | None = None, in_args: PropSet | None = None,
               out_args: PropSet | None = None) -> int:
        return self.plugin.mainEntry(K[name].encode(), handle or None, self.handle(in_args) if in_args is not None
                                     else None, self.handle(out_args) if out_args is not None else None)

    def _effect(self) -> dict:
        return {"props": PropSet(), "params": {"props": PropSet(), "defs": {}, "order": []}, "clips": {}}

    def describe(self) -> dict:
        assert self.action("kOfxActionLoad") == OK
        self.descriptor = d = self._effect()
        h = self.handle(d)
        assert self.action("kOfxActionDescribe", h) == OK
        ctx = self.new_props(kOfxImageEffectPropContext=K["kOfxImageEffectContextFilter"])
        assert self.action("kOfxImageEffectActionDescribeInContext", h, ctx) == OK
        return d

    def create_instance(self, width: int, height: int) -> dict:
        d = self.descriptor or self.describe()
        inst = self._effect()
        inst["props"].update(self.new_props(**{
            "kOfxPropType": K["kOfxTypeImageEffectInstance"],
            "kOfxImageEffectPropContext": K["kOfxImageEffectContextFilter"], "kOfxPropInstanceData": 0,
            "kOfxPropIsInteractive": 0, "kOfxImageEffectPropProjectSize": [float(width), float(height)],
            "kOfxImageEffectPropProjectOffset": [0.0, 0.0],
            "kOfxImageEffectPropProjectExtent": [float(width), float(height)],
            "kOfxImageEffectPropProjectPixelAspectRatio": 1.0, "kOfxImageEffectInstancePropEffectDuration": 100.0,
            "kOfxImageEffectInstancePropSequentialRender": 0, "kOfxImageEffectPropFrameRate": self.frame_rate,
            "kOfxImageEffectPropPluginHandle": 0}))
        for name in d["clips"]:
            inst["clips"][name] = self.new_props(**{
                "kOfxPropType": K["kOfxTypeClip"], "kOfxPropName": name,
                "kOfxImageEffectPropPixelDepth": K["kOfxBitDepthFloat"],
                "kOfxImageEffectPropComponents": K["kOfxImageComponentRGBA"],
                "kOfxImageClipPropUnmappedPixelDepth": K["kOfxBitDepthFloat"],
                "kOfxImageClipPropUnmappedComponents": K["kOfxImageComponentRGBA"],
                "kOfxImageEffectPropPreMultiplication": K["kOfxImageUnPreMultiplied"],
                "kOfxImagePropPixelAspectRatio": 1.0, "kOfxImageEffectPropFrameRate": self.frame_rate,
                "kOfxImageEffectPropFrameRange": [0.0, 99.0], "kOfxImageClipPropFieldOrder": K["kOfxImageFieldNone"],
                "kOfxImageClipPropConnected": 1, "kOfxImageEffectPropUnmappedFrameRange": [0.0, 99.0],
                "kOfxImageEffectPropUnmappedFrameRate": self.frame_rate, "kOfxImageClipPropContinuousSamples": 0,
                "kOfxImageClipPropIsMask": 0, "kOfxImageClipPropOptional": 0})
        for name in d["params"]["order"]:
            src = d["params"]["defs"][name]
            p = Param(src.type, PropSet({k: list(v) for k, v in src.props.items()}))
            p.value = list(src.props.get(K["kOfxParamPropDefault"], [0]))
            inst["params"]["defs"][name] = p
            inst["params"]["order"].append(name)
        self.instance = inst
        self.messages.clear()
        self.source = np.zeros((height, width, 4), np.float32)
        self.output = np.zeros((height, width, 4), np.float32)
        assert self.action("kOfxActionCreateInstance", self.handle(inst)) == OK
        return inst

    def param(self, name: str) -> Param:
        return self.instance["params"]["defs"][name]

    def set_param(self, name: str, *value) -> None:
        self.param(name).value = list(value)

    def change(self, name: str, reason: str = "kOfxChangeUserEdited", time: float = 0.0) -> int:
        h = self.handle(self.instance)
        args = self.new_props(kOfxPropType=K["kOfxTypeParameter"], kOfxPropName=name, kOfxPropChangeReason=K[reason],
                              kOfxPropTime=time, kOfxImageEffectPropRenderScale=[1.0, 1.0])
        breason = self.new_props(kOfxPropChangeReason=K[reason])
        self.action("kOfxActionBeginInstanceChanged", h, breason)
        st = self.action("kOfxActionInstanceChanged", h, args)
        self.action("kOfxActionEndInstanceChanged", h, breason)
        return st

    def render(self, rgb_top_down: np.ndarray, time: float = 0.0) -> np.ndarray:
        """Entrada e saída com a linha 0 no topo (como o app); no meio, o OpenFX vê a origem embaixo."""
        h, w = rgb_top_down.shape[:2]
        src = np.ones((h, w, 4), np.float32)
        src[..., :3] = rgb_top_down[::-1]
        self.source = np.ascontiguousarray(src)
        self.output = np.zeros((h, w, 4), np.float32)
        args = self.new_props(**{
            "kOfxPropTime": float(time), "kOfxImageEffectPropFieldToRender": K["kOfxImageFieldNone"],
            "kOfxImageEffectPropRenderWindow": [0, 0, w, h], "kOfxImageEffectPropRenderScale": [1.0, 1.0],
            "kOfxImageEffectPropSequentialRenderStatus": 0, "kOfxImageEffectPropInteractiveRenderStatus": 0,
            "kOfxImageEffectPropRenderQualityDraft": 0})
        st = self.action("kOfxImageEffectActionRender", self.handle(self.instance), args)
        assert st == OK, f"render devolveu {st}; propriedades que faltaram: {sorted(self.missing)}"
        return self.output[::-1, :, :3].copy()

    def is_identity(self, time: float = 0.0) -> tuple[int, str | None]:
        w, h = self.source.shape[1], self.source.shape[0]
        args = self.new_props(**{
            "kOfxPropTime": float(time), "kOfxImageEffectPropFieldToRender": K["kOfxImageFieldNone"],
            "kOfxImageEffectPropRenderWindow": [0, 0, w, h], "kOfxImageEffectPropRenderScale": [1.0, 1.0]})
        out = self.new_props(kOfxPropName="", kOfxPropTime=float(time))
        st = self.action("kOfxImageEffectActionIsIdentity", self.handle(self.instance), args, out)
        return st, out[K["kOfxPropName"]][0]
