#!/usr/bin/env python3
"""py3port.py <dir> - make upstream pypinproc (Python 2 C API) build for
Python 3, in place.  Only API spelling changes: no behaviour is touched, so a
real-stack run on 3.x checks the same C code a 2.7 run does.

pypinproc.cpp strings are text (machine types, decode() numbers): str.
dmdutil.cpp strings are frame data (DMDBuffer.set_data/get_data): bytes.
"""
import os
import re
import sys


def sub(text, old, new, count=0, required=True):
    if required and old not in text:
        raise SystemExit("py3port.py: pattern not found: %r" % old)
    return text.replace(old, new) if not count else text.replace(old, new, count)


def common(text):
    text = text.replace("self->ob_type->tp_free", "Py_TYPE(self)->tp_free")
    text = re.sub(r"PyObject_HEAD_INIT\(NULL\)\s*\n\s*0,\s*/\*ob_size\*/",
                  "PyVarObject_HEAD_INIT(NULL, 0)", text)
    text = text.replace("PyInt_Check", "PyLong_Check")
    text = text.replace("PyInt_AsLong", "PyLong_AsLong")
    text = text.replace("PyInt_FromString(", "PyLong_FromString((char *)")
    return text


def port_pypinproc(text):
    text = common(text)
    text = text.replace("PyString_Check", "PyUnicode_Check")
    text = text.replace("PyString_AsString", "(char *)PyUnicode_AsUTF8")
    text = sub(text, "PyMODINIT_FUNC initpinproc()",
               "static struct PyModuleDef pinproc_moduledef = {\n"
               "    PyModuleDef_HEAD_INIT, \"pinproc\", NULL, -1, methods};\n\n"
               "PyMODINIT_FUNC PyInit_pinproc(void)")
    head, _, tail = text.partition("PyInit_pinproc(void)")
    body_end = tail.index('"DriverCount", kPRDriverCount);') + len('"DriverCount", kPRDriverCount);')
    body, rest = tail[:body_end], tail[body_end:]
    body = body.replace("return;", "return NULL;")
    body = sub(body, 'Py_InitModule("pinproc", methods)', "PyModule_Create(&pinproc_moduledef)")
    return head + "PyInit_pinproc(void)" + body + "\n    return m;" + rest


def port_dmdutil(text):
    text = common(text)
    return text.replace("PyString_", "PyBytes_")


def main(d):
    for name, fn in (("pypinproc.cpp", port_pypinproc), ("dmdutil.cpp", port_dmdutil)):
        path = os.path.join(d, name)
        with open(path) as f:
            text = f.read()
        with open(path, "w") as f:
            f.write(fn(text))


if __name__ == "__main__":
    main(sys.argv[1])
