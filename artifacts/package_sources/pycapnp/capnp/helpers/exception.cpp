#include "capnp/helpers/exception.h"
#include "capnp/lib/capnp_api.h"

void c_reraise_kj_exception() {
  GILAcquire gil;
  try {
    if (PyErr_Occurred())
      ; // let the latest Python exn pass through and ignore the current one
    else
      throw;
  }
  catch (kj::Exception& exn) {
    auto obj = wrap_kj_exception_for_reraise(exn);
    if (obj == nullptr) {
      return;
    }
    PyErr_SetObject((PyObject*)obj->ob_type, obj);
    Py_DECREF(obj);
  }
  catch (const std::exception& exn) {
    PyErr_SetString(PyExc_RuntimeError, exn.what());
  }
  catch (...)
  {
    PyErr_SetString(PyExc_RuntimeError, "Unknown exception");
  }
}

void init_capnp_api() {
    import_capnp__lib__capnp();
}
