#!/usr/bin/env python3
"""Name the GPU the emulator should render on, inside WSL (PAD-258).

Mesa's d3d12 driver renders on adapter 0 of DXCore's list unless
MESA_D3D12_DEFAULT_ADAPTER_NAME names another (a case-insensitive substring of
the adapter's driver description). Adapter 0 is Windows' default adapter, and
on a machine with an integrated GPU as well as a discrete one that is very
often the integrated one: on David's 9800X3D + RTX 5090 it was the Radeon iGPU,
1.096 ms/frame against the 5090's 0.026, taking its bandwidth out of system RAM
and paying a cross-adapter copy every frame to reach the display.

This asks DXCore the same question Mesa does, through the same library
(/usr/lib/wsl/lib/libdxcore.so, which Windows injects into every WSL2 VM), and
prints the description of the adapter to render on:

  * only when there are TWO OR MORE hardware adapters that can do D3D12
    graphics - with one there is nothing to choose, and printing nothing leaves
    Mesa exactly as it was;
  * DXCore's own HighPerformance ordering when the list supports it (that is
    Windows' notion of the fast GPU), otherwise: discrete before integrated,
    then the most dedicated video memory.

Prints nothing and exits 0 when there is nothing to choose or anything at all
goes wrong: the caller then leaves Mesa's own choice alone, which is how every
run behaved before this existed.

  gpupick.py          the description to export, or nothing
  gpupick.py --list   every adapter and which one would be picked (for logs)
"""
import ctypes
import os
import sys

LIB = "/usr/lib/wsl/lib/libdxcore.so"


class GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_uint32), ("d2", ctypes.c_uint16),
                ("d3", ctypes.c_uint16), ("d4", ctypes.c_uint8 * 8)]


def guid(s):
    h = s.replace("-", "")
    g = GUID(int(h[0:8], 16), int(h[8:12], 16), int(h[12:16], 16))
    for i in range(8):
        g.d4[i] = int(h[16 + 2 * i:18 + 2 * i], 16)
    return g


# dxcore_interface.h (DirectX-Headers).
IID_FACTORY = guid("78ee5945-c36e-4b13-a669-005dd11c0f06")
IID_LIST = guid("526c7776-40e9-459b-b711-f32ad76dfc28")
IID_ADAPTER = guid("f0db4c7f-fe5a-42a2-bd62-f2a6cf6fc83e")
ATTR_D3D12_GRAPHICS = guid("0c9ece4d-2f6e-4f01-8c96-e89e331b47b1")

# DXCoreAdapterProperty
P_DRIVER_DESCRIPTION = 2
P_DEDICATED_ADAPTER_MEMORY = 7
P_IS_HARDWARE = 11
P_IS_INTEGRATED = 12
# DXCoreAdapterPreference
PREF_HARDWARE = 0
PREF_HIGH_PERFORMANCE = 2

HRESULT = ctypes.c_int32
PV = ctypes.c_void_p


def method(obj, index, restype, *argtypes):
    """Slot `index` of a COM object's vtable, bound to `obj`. IUnknown is
    slots 0-2 (QueryInterface, AddRef, Release) on Linux too: DirectX-Headers'
    wsl/winadapter.h declares no virtual destructor, so nothing shifts."""
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(PV))).contents
    proto = ctypes.CFUNCTYPE(restype, PV, *argtypes)
    fn = proto(vtbl[index])
    return lambda *a: fn(obj, *a)


def release(obj):
    if obj:
        method(obj, 2, ctypes.c_uint32)()


def adapters():
    """[(description, hardware, integrated, dedicated_bytes)] in HighPerformance
    order when DXCore can sort, else in its own order; plus whether it sorted."""
    dx = ctypes.CDLL(LIB)
    create = dx.DXCoreCreateAdapterFactory
    create.restype = HRESULT
    create.argtypes = [ctypes.POINTER(GUID), ctypes.POINTER(PV)]
    factory = PV()
    if create(ctypes.byref(IID_FACTORY), ctypes.byref(factory)) < 0:
        return [], False
    lst = PV()
    try:
        # IDXCoreAdapterFactory: 3 CreateAdapterList
        if method(factory, 3, HRESULT, ctypes.c_uint32, ctypes.POINTER(GUID),
                  ctypes.POINTER(GUID), ctypes.POINTER(PV))(
                1, ctypes.byref(ATTR_D3D12_GRAPHICS), ctypes.byref(IID_LIST),
                ctypes.byref(lst)) < 0:
            return [], False
        # IDXCoreAdapterList: 3 GetAdapter, 4 GetAdapterCount, 5 IsStale,
        # 6 GetFactory, 7 Sort, 8 IsAdapterPreferenceSupported
        sorted_ = False
        try:
            supported = method(lst, 8, ctypes.c_bool, ctypes.c_uint32)
            if supported(PREF_HIGH_PERFORMANCE) and supported(PREF_HARDWARE):
                prefs = (ctypes.c_uint32 * 2)(PREF_HARDWARE, PREF_HIGH_PERFORMANCE)
                sorted_ = method(lst, 7, HRESULT, ctypes.c_uint32,
                                 ctypes.POINTER(ctypes.c_uint32))(2, prefs) >= 0
        except Exception:
            sorted_ = False
        out = []
        for i in range(method(lst, 4, ctypes.c_uint32)()):
            ad = PV()
            if method(lst, 3, HRESULT, ctypes.c_uint32, ctypes.POINTER(GUID),
                      ctypes.POINTER(PV))(i, ctypes.byref(IID_ADAPTER),
                                          ctypes.byref(ad)) < 0:
                continue
            try:
                out.append(describe(ad))
            finally:
                release(ad)
        return out, sorted_
    finally:
        release(lst)
        release(factory)


def describe(ad):
    # IDXCoreAdapter: 3 IsValid, 4 IsAttributeSupported, 5 IsPropertySupported,
    # 6 GetProperty, 7 GetPropertySize
    has = method(ad, 5, ctypes.c_bool, ctypes.c_uint32)
    get = method(ad, 6, HRESULT, ctypes.c_uint32, ctypes.c_size_t, PV)
    size = method(ad, 7, HRESULT, ctypes.c_uint32, ctypes.POINTER(ctypes.c_size_t))

    def prop(p, ctype):
        if not has(p):
            return None
        v = ctype()
        return v.value if get(p, ctypes.sizeof(v), ctypes.byref(v)) >= 0 else None

    desc = ""
    n = ctypes.c_size_t()
    if has(P_DRIVER_DESCRIPTION) and size(P_DRIVER_DESCRIPTION, ctypes.byref(n)) >= 0:
        buf = ctypes.create_string_buffer(n.value)
        if get(P_DRIVER_DESCRIPTION, n.value, buf) >= 0:
            desc = buf.value.decode("utf-8", "replace").strip()
    return (desc, bool(prop(P_IS_HARDWARE, ctypes.c_bool)),
            bool(prop(P_IS_INTEGRATED, ctypes.c_bool)),
            prop(P_DEDICATED_ADAPTER_MEMORY, ctypes.c_uint64) or 0)


def pick(ads, sorted_):
    hw = [a for a in ads if a[1] and a[0]]
    if len(hw) < 2:
        return None
    if sorted_:
        return hw[0][0]
    # No DXCore ordering: discrete first, then the most dedicated memory.
    # sorted() is stable, so ties keep DXCore's (i.e. Mesa's) order.
    return sorted(hw, key=lambda a: (a[2], -a[3]))[0][0]


def main():
    listing = "--list" in sys.argv[1:]
    if not os.path.exists(LIB):
        if listing:
            print("no %s (not WSL2): nothing to choose" % LIB)
        return 0
    try:
        ads, sorted_ = adapters()
    except Exception as e:  # a missing symbol, an old DXCore - never fatal
        if listing:
            print("DXCore query failed: %r" % (e,))
        return 0
    choice = pick(ads, sorted_)
    if listing:
        print("order: %s" % ("DXCore HighPerformance" if sorted_
                             else "DXCore default (fallback heuristic)"))
        for d, hard, integ, mem in ads:
            print("%s %-50s %s %s %6d MB" % (
                "*" if d == choice else " ", d,
                "hw " if hard else "sw ", "integrated" if integ else "discrete  ",
                mem // (1 << 20)))
        if choice is None:
            print("fewer than two hardware adapters: Mesa's own choice stands")
    elif choice:
        print(choice)
    return 0


if __name__ == "__main__":
    sys.exit(main())
