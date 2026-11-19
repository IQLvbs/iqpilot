cdef extern from "capnp/helpers/exception.h":
    void c_reraise_kj_exception()
