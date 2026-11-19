# cython: language_level = 2

from capnp.includes cimport capnp_cpp as capnp
from capnp.includes cimport schema_cpp
from capnp.includes.capnp_cpp cimport (
    Schema as C_Schema, StructSchema as C_StructSchema,
    EnumSchema as C_EnumSchema, ListSchema as C_ListSchema, DynamicStruct as C_DynamicStruct,
    DynamicValue as C_DynamicValue, DynamicList as C_DynamicList,
    SchemaParser as C_SchemaParser, ParsedSchema as C_ParsedSchema, VOID, ArrayPtr, StringPtr,
    String, StringTree, DynamicStruct_Builder
)
from capnp.includes.schema_cpp cimport Node as C_Node
from capnp.includes.types cimport *
from capnp.helpers cimport helpers

cdef void reraise_kj_exception()

cdef class _StructSchemaField:
    cdef C_StructSchema.Field thisptr
    cdef object _parent
    cdef _init(self, C_StructSchema.Field other, parent=?)

cdef class _StringArrayPtr:
    cdef StringPtr * thisptr
    cdef object parent
    cdef size_t size
    cdef ArrayPtr[StringPtr] asArrayPtr(self)

cdef class SchemaParser:
    cdef C_SchemaParser * thisptr
    cdef public dict modules_by_id
    cdef list _all_imports
    cdef _StringArrayPtr _last_import_array
    cpdef _parse_disk_file(self, displayName, diskPath, imports)

cdef class _DynamicStructReader:
    cdef C_DynamicStruct.Reader thisptr
    cdef public object _parent
    cdef public bint is_root
    cdef object _obj_to_pin
    cdef object _schema

    cdef _init(self, C_DynamicStruct.Reader other, object parent, bint isRoot=?)

    cpdef _get(self, field)
    cpdef _has(self, field)
    cpdef _DynamicEnumField _which(self)
    cpdef _get_by_field(self, _StructSchemaField field)
    cpdef as_builder(self)


cdef class _DynamicStructBuilder:
    cdef DynamicStruct_Builder thisptr
    cdef public object _parent
    cdef public bint is_root
    cdef public bint _is_written
    cdef object _schema

    cdef _init(self, DynamicStruct_Builder other, object parent, bint isRoot=?)

    cdef _check_write(self)
    cpdef to_bytes(_DynamicStructBuilder self)
    cpdef _get(self, field)
    cpdef _set(self, field, value)
    cpdef _has(self, field)
    cpdef init(self, field, size=?)
    cpdef _get_by_field(self, _StructSchemaField field)
    cpdef _set_by_field(self, _StructSchemaField field, value)
    cpdef _DynamicEnumField _which(self)
    cpdef as_reader(self)
    cpdef copy(self)

cdef class _DynamicEnumField:
    cdef object thisptr

    cdef _init(self, proto)
    cpdef _str(self)

cdef class _Schema:
    cdef C_Schema thisptr

    cdef _init(self, C_Schema other)

    cpdef as_const_value(self)
    cpdef as_struct(self)
    cpdef as_enum(self)
    cpdef get_proto(self)

cdef class _DynamicEnum:
    cdef capnp.DynamicEnum thisptr
    cdef public object _parent

    cdef _init(self, capnp.DynamicEnum other, object parent)
    cpdef _as_str(self)

cdef class _DynamicListBuilder:
    cdef C_DynamicList.Builder thisptr
    cdef public object _parent
    cdef _init(self, C_DynamicList.Builder other, object parent)

    cpdef _get(self, int64_t index)
    cpdef _set(self, index, value)

    cpdef init(self, index, size)

cdef class _MessageBuilder:
    cdef schema_cpp.MessageBuilder * thisptr
    cpdef init_root(self, schema)
    cpdef get_root(self, schema)
    cpdef set_root(self, value)
cdef to_python_reader(C_DynamicValue.Reader self, object parent)
cdef to_python_builder(C_DynamicValue.Builder self, object parent)
cdef _to_dict(msg, bint verbose)
cdef _from_list(_DynamicListBuilder msg, list d)
cdef _from_tuple(_DynamicListBuilder msg, tuple d)
cdef _setDynamicFieldWithField(DynamicStruct_Builder thisptr, _StructSchemaField field, value, parent)

cdef api object wrap_kj_exception_for_reraise(capnp.Exception & exception) with gil
