#pragma once

#include <Python.h>
#include <kj/exception.h>
#include <stdexcept>

class GILAcquire {
public:
  GILAcquire() : gstate(PyGILState_Ensure()) {}
  ~GILAcquire() {
    PyGILState_Release(gstate);
  }

  PyGILState_STATE gstate;
};

void c_reraise_kj_exception();
void init_capnp_api();
