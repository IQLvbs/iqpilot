from capnp.includes.capnp_cpp cimport Maybe, EnumSchema, StructSchema
from non_circular cimport c_reraise_kj_exception as reraise_kj_exception

cdef extern from "capnp/helpers/fixMaybe.h":
    EnumSchema.Enumerant fixMaybe(Maybe[EnumSchema.Enumerant]) except +reraise_kj_exception
    StructSchema.Field fixMaybe(Maybe[StructSchema.Field]) except +reraise_kj_exception

cdef extern from "capnp/helpers/exception.h":
    void init_capnp_api()
