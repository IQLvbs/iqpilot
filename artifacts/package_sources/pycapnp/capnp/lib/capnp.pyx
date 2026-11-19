# capnp.pyx
# distutils: language = c++
# distutils: include_dirs = .
# cython: c_string_type = str
# cython: c_string_encoding = default
# cython: embedsignature = True
# cython: language_level = 2

cimport cython  # noqa: E402

from capnp.helpers.helpers cimport init_capnp_api

from builtins import memoryview as BuiltinsMemoryview
from cpython cimport Py_buffer, PyObject_CheckBuffer
from cpython.buffer cimport PyBUF_SIMPLE, PyBUF_CONTIG_RO
from cpython.bytes cimport PyBytes_FromStringAndSize, PyBytes_AS_STRING
from cpython.exc cimport PyErr_Clear
from cython.operator cimport dereference as deref
from libc.stdlib cimport malloc, free
from libc.string cimport memcpy
from libcpp.utility cimport move


import contextlib
import base64
import enum as _enum
import os as _os
import warnings as _warnings

from types import ModuleType as _ModuleType

cdef object _numpy = None

cdef extern from "capnp/helpers/serialize.h":
    object messageToPythonBytes(schema_cpp.MessageBuilder&) except +reraise_kj_exception

_CAPNP_VERSION_MAJOR = capnp.CAPNP_VERSION_MAJOR
_CAPNP_VERSION_MINOR = capnp.CAPNP_VERSION_MINOR
_CAPNP_VERSION_MICRO = capnp.CAPNP_VERSION_MICRO
_CAPNP_VERSION = capnp.CAPNP_VERSION

cdef extern from "<kj/string.h>" namespace " ::kj":
    String strStructReader" ::kj::str"(C_DynamicStruct.Reader)
    String strStructBuilder" ::kj::str"(DynamicStruct_Builder)
    String strListReader" ::kj::str"(C_DynamicList.Reader)
    String strListBuilder" ::kj::str"(C_DynamicList.Builder)
    String strException" ::kj::str"(capnp.Exception)


def _make_enum(enum_name, *sequential, **named):
    enums = dict(zip(sequential, range(len(sequential))), **named)
    reverse = dict((value, key) for key, value in enums.iteritems())
    enums['reverse_mapping'] = reverse
    return type(enum_name, (), enums)


_Type = _make_enum(
    "_Type",
    FAILED=0,
    OVERLOADED=1,
    DISCONNECTED=2,
    UNIMPLEMENTED=3,
    OTHER=4,
)


cdef class _KjExceptionWrapper:
    cdef capnp.Exception * thisptr

    cdef _init(self, capnp.Exception & other):
        self.thisptr = new capnp.Exception(move(other))
        return self

    def __dealloc__(self):
        del self.thisptr

    property file:
        def __get__(self):
            return <char*>self.thisptr.getFile()
    property line:
        def __get__(self):
            return self.thisptr.getLine()
    property type:
        def __get__(self):
            cdef int temp = <int>self.thisptr.getType()
            return _Type.reverse_mapping[temp]
    property description:
        def __get__(self):
            return <char*>self.thisptr.getDescription().cStr()

    def __str__(self):
        return <char*>strException(deref(self.thisptr)).cStr()


# Extension classes can't inherit from Exception, so we're going to proxy wrap kj::Exception,
# and forward all calls to it from this Python class
class KjException(Exception):

    """KjException is a wrapper of the internal C++ exception type.

    There is an enum named `Type` listed below, and a bunch of fields."""

    Type = _make_enum("Type", **{x: x for x in _Type.reverse_mapping.values()})

    def __init__(self, message=None, wrapper=None, type=None):
        if wrapper is not None:
            self.wrapper = wrapper
            self.message = str(wrapper)
        else:
            self.wrapper = None
            self.message = message
            self._type = type

    @property
    def file(self):
        return self.wrapper.file

    @property
    def line(self):
        return self.wrapper.line

    @property
    def type(self):
        if self.wrapper is not None:
            return self.wrapper.type
        else:
            return self._type

    @property
    def description(self):
        if self.wrapper is not None:
            return self.wrapper.description
        else:
            return self.message

    def __str__(self):
        return self.message

    def _to_python(self):
        message = self.message
        if self.wrapper is not None and self.wrapper.type == 'FAILED':
            if 'has no such' in self.message:
                return AttributeError(message).with_traceback(self.__traceback__)
        return self


cdef api object wrap_kj_exception_for_reraise(capnp.Exception & exception) with gil:
    PyErr_Clear()
    wrapper = _KjExceptionWrapper()._init(exception)
    ret = KjException(wrapper=wrapper)
    return ret


cdef void reraise_kj_exception():
    helpers.reraise_kj_exception()


cdef schema_cpp.ReaderOptions make_reader_opts(traversal_limit_in_words, nesting_limit):
    cdef schema_cpp.ReaderOptions opts
    if traversal_limit_in_words is not None:
        opts.traversalLimitInWords = traversal_limit_in_words
    if nesting_limit is not None:
        opts.nestingLimit = nesting_limit
    return opts


ctypedef fused _DynamicSetterClasses:
    C_DynamicList.Builder
    DynamicStruct_Builder


cdef extern from "Python.h":
    cdef int PyObject_GetBuffer(object, Py_buffer *view, int flags)
    cdef void PyBuffer_Release(Py_buffer *view)

cdef extern from "<capnp/pretty-print.h>" namespace " ::capnp":
    StringTree printStructReader" ::capnp::prettyPrint"(C_DynamicStruct.Reader) except +reraise_kj_exception
    StringTree printStructBuilder" ::capnp::prettyPrint"(DynamicStruct_Builder) except +reraise_kj_exception
    StringTree printListReader" ::capnp::prettyPrint"(C_DynamicList.Reader) except +reraise_kj_exception
    StringTree printListBuilder" ::capnp::prettyPrint"(C_DynamicList.Builder) except +reraise_kj_exception


cdef class _NodeReader:
    cdef C_Node.Reader thisptr
    cdef init(self, C_Node.Reader other):
        self.thisptr = other
        return self

    property id:
        def __get__(self):
            return self.thisptr.getId()

    property nestedNodes:
        def __get__(self):
            return _List_NestedNode_Reader()._init(self.thisptr.getNestedNodes())

    property isStruct:
        def __get__(self):
            return self.thisptr.isStruct()

    property isConst:
        def __get__(self):
            return self.thisptr.isConst()

    property isInterface:
        def __get__(self):
            return self.thisptr.isInterface()

    property isEnum:
        def __get__(self):
            return self.thisptr.isEnum()

cdef class _NestedNodeReader:
    cdef C_Node.NestedNode.Reader thisptr
    cdef init(self, C_Node.NestedNode.Reader other):
        self.thisptr = other
        return self

    property name:
        def __get__(self):
            return <char*>self.thisptr.getName().cStr()


cdef class _DynamicListReader:
    """Class for reading Cap'n Proto Lists

    This class thinly wraps the C++ Cap'n Proto DynamicList::Reader class. __getitem__ and __len__
    have been defined properly, so you can treat this class mostly like any other iterable class::

        ...
        person = addressbook.Person.new_message()

        phones = person.phones # This returns a _DynamicListReader

        phone = phones[0]
        print phone.number

        for phone in phones:
            print phone.number
    """
    cdef C_DynamicList.Reader thisptr
    cdef public object _parent
    cdef _init(self, C_DynamicList.Reader other, object parent):
        self.thisptr = other
        self._parent = parent
        return self

    cpdef _get(self, int64_t index):
        ptr = self.thisptr[index]
        return to_python_reader(ptr, self._parent)

    def to_float64_bytes(self):
        cdef Py_ssize_t size = self.thisptr.size()
        cdef bytes result = PyBytes_FromStringAndSize(NULL, size * sizeof(double))
        cdef char* target = PyBytes_AS_STRING(result)
        cdef Py_ssize_t index
        cdef double value
        cdef C_DynamicValue.Reader item
        cdef int kind
        if size:
            item = self.thisptr[0]
            kind = item.getType()
            if kind != capnp.TYPE_FLOAT and kind != capnp.TYPE_INT and kind != capnp.TYPE_UINT:
                raise TypeError("to_float64_bytes requires a numeric list")
        for index in range(size):
            item = self.thisptr[index]
            value = item.asDouble()
            memcpy(target + index * sizeof(double), &value, sizeof(double))
        return result

    def __array__(self, dtype=None, copy=None):
        global _numpy
        if _numpy is None:
            _numpy = __import__("numpy")
        np = _numpy
        if copy is False:
            raise ValueError("Cap'n Proto lists require a copy for NumPy conversion")
        cdef Py_ssize_t size = self.thisptr.size()
        cdef Py_ssize_t index
        cdef C_DynamicValue.Reader item
        cdef int kind
        cdef double[::1] values64
        if size:
            item = self.thisptr[0]
            kind = item.getType()
            if kind != capnp.TYPE_FLOAT:
                return np.array(list(self), dtype=dtype)
        result = np.empty(size, dtype=np.float64)
        values64 = result
        for index in range(size):
            item = self.thisptr[index]
            values64[index] = item.asDouble()
        return result if dtype is None else result.astype(dtype, copy=False)

    def __getitem__(self, int64_t index):
        cdef uint size = self.thisptr.size()
        if index >= size:
            raise IndexError('Out of bounds')
        index = index % size
        return self._get(index)

    def __len__(self):
        return self.thisptr.size()

    def __str__(self):
        return <char*>printListReader(self.thisptr).flatten().cStr()

    def __repr__(self):
        # TODO:  Print the list type.
        return '<capnp list reader %s>' % <char*>strListReader(self.thisptr).cStr()


cdef class _DynamicListBuilder:
    """Class for building Cap'n Proto Lists

    This class thinly wraps the C++ Cap'n Proto DynamicList::Bulder class. __getitem__, __setitem__, and __len__
    have been defined properly, so you can treat this class mostly like any other iterable class::

        ...
        person = addressbook.Person.new_message()

        phones = person.init('phones', 2) # This returns a _DynamicListBuilder

        phone = phones[0]
        phone.number = 'foo'
        phone = phones[1]
        phone.number = 'bar'

        for phone in phones:
            print phone.number
    """
    cdef _init(self, C_DynamicList.Builder other, object parent):
        self.thisptr = other
        self._parent = parent
        return self

    cpdef _get(self, int64_t index):
        ptr = self.thisptr[index]
        return to_python_builder(ptr, self._parent)

    def __array__(self, dtype=None, copy=None):
        return _DynamicListReader()._init(self.thisptr.asReader(), self._parent).__array__(dtype=dtype, copy=copy)

    def __getitem__(self, int64_t index):
        cdef uint size = self.thisptr.size()
        if index >= size:
            raise IndexError('Out of bounds')
        index = index % size
        return self._get(index)

    cpdef _set(self, index, value):
        _setDynamicField(self.thisptr, index, value, self._parent)

    def __setitem__(self, index, value):
        size = self.thisptr.size()
        if index >= size:
            raise IndexError('Out of bounds')
        index = index % size
        _setDynamicField(self.thisptr, index, value, self._parent)

    def __len__(self):
        return self.thisptr.size()

    cpdef init(self, index, size):
        """A method for initializing an element in a list

        :type index: int
        :param index: The index of the element in the list

        :type size: int
        :param size: Size of the element to be initialized.
        """
        ptr = self.thisptr.init(index, size)
        return to_python_builder(ptr, self._parent)

    def __str__(self):
        return <char*>printListBuilder(self.thisptr).flatten().cStr()

    def __repr__(self):
        # TODO:  Print the list type.
        return '<capnp list builder %s>' % <char*>strListBuilder(self.thisptr).cStr()


cdef class _List_NestedNode_Reader:
    cdef schema_cpp.ListNestedNodeReader thisptr
    cdef _init(self, schema_cpp.ListNestedNodeReader other):
        self.thisptr = <schema_cpp.ListNestedNodeReader>other
        return self

    def __getitem__(self, index):
        size = self.thisptr.size()
        if index >= size:
            raise IndexError('Out of bounds')
        index = index % size
        return _NestedNodeReader().init(<C_Node.NestedNode.Reader>self.thisptr[index])

    def __len__(self):
        return self.thisptr.size()

cdef to_python_reader(C_DynamicValue.Reader self, object parent):
    cdef int type = self.getType()
    if type == capnp.TYPE_BOOL:
        return self.asBool()
    elif type == capnp.TYPE_INT:
        return self.asInt()
    elif type == capnp.TYPE_UINT:
        return self.asUint()
    elif type == capnp.TYPE_FLOAT:
        return self.asDouble()
    elif type == capnp.TYPE_TEXT:
        temp_text = self.asText()
        return (<char*>temp_text.begin())[:temp_text.size()]
    elif type == capnp.TYPE_DATA:
        temp_data = self.asData()
        return <bytes>((<char*>temp_data.begin())[:temp_data.size()])
    elif type == capnp.TYPE_LIST:
        return _DynamicListReader()._init(self.asList(), parent)
    elif type == capnp.TYPE_STRUCT:
        return _DynamicStructReader()._init(self.asStruct(), parent)
    elif type == capnp.TYPE_ENUM:
        return _DynamicEnum()._init(self.asEnum(), parent)
    elif type == capnp.TYPE_VOID:
        return None
    elif type == capnp.TYPE_UNKNOWN:
        raise KjException("Cannot convert type to Python. Type is unknown by capnproto library")
    else:
        raise KjException("Cannot convert type to Python. Type is unhandled by capnproto library")


cdef to_python_builder(C_DynamicValue.Builder self, object parent):
    cdef int type = self.getType()
    if type == capnp.TYPE_BOOL:
        return self.asBool()
    elif type == capnp.TYPE_INT:
        return self.asInt()
    elif type == capnp.TYPE_UINT:
        return self.asUint()
    elif type == capnp.TYPE_FLOAT:
        return self.asDouble()
    elif type == capnp.TYPE_TEXT:
        temp_text = self.asText()
        return (<char*>temp_text.begin())[:temp_text.size()]
    elif type == capnp.TYPE_DATA:
        temp_data = self.asData()
        return <bytes>((<char*>temp_data.begin())[:temp_data.size()])
    elif type == capnp.TYPE_LIST:
        return _DynamicListBuilder()._init(self.asList(), parent)
    elif type == capnp.TYPE_STRUCT:
        return _DynamicStructBuilder()._init(self.asStruct(), parent)
    elif type == capnp.TYPE_ENUM:
        return _DynamicEnum()._init(self.asEnum(), parent)
    elif type == capnp.TYPE_VOID:
        return None
    elif type == capnp.TYPE_UNKNOWN:
        raise KjException("Cannot convert type to Python. Type is unknown by capnproto library")
    else:
        raise KjException("Cannot convert type to Python. Type is unhandled by capnproto library")


cdef C_DynamicValue.Reader _extract_dynamic_struct_builder(_DynamicStructBuilder value):
    return C_DynamicValue.Reader(value.thisptr.asReader())


cdef C_DynamicValue.Reader _extract_dynamic_struct_reader(_DynamicStructReader value):
    return C_DynamicValue.Reader(value.thisptr)


cdef C_DynamicValue.Reader _extract_dynamic_list_builder(_DynamicListBuilder value):
    return C_DynamicValue.Reader(value.thisptr.asReader())


cdef C_DynamicValue.Reader _extract_dynamic_list_reader(_DynamicListReader value):
    return C_DynamicValue.Reader(value.thisptr)


cdef C_DynamicValue.Reader _extract_dynamic_enum(_DynamicEnum value):
    return C_DynamicValue.Reader(value.thisptr)


cdef _setBytes(_DynamicSetterClasses thisptr, field, value):
    cdef capnp.StringPtr temp_string = capnp.StringPtr(<char*>value, len(value))
    cdef C_DynamicValue.Reader temp = C_DynamicValue.Reader(temp_string)
    thisptr.set(field, temp)

cdef _setMemoryview(_DynamicSetterClasses thisptr, field, value):
    cdef Py_buffer buf
    cdef capnp.StringPtr temp_string
    cdef C_DynamicValue.Reader temp
    if PyObject_GetBuffer(value, &buf, PyBUF_CONTIG_RO) != 0:
        raise KjException(
            "cannot get buffer from memory view, for field '{}'".format(field)
        )
    try:
        temp_string = capnp.StringPtr(<char *> buf.buf, buf.len)
        temp = C_DynamicValue.Reader(temp_string)
        thisptr.set(field, temp)
    finally:
        PyBuffer_Release(&buf)

cdef _setBaseString(_DynamicSetterClasses thisptr, field, value):
    encoded_value = value.encode('utf-8')
    cdef capnp.StringPtr temp_string = capnp.StringPtr(<char*>encoded_value, len(encoded_value))
    cdef C_DynamicValue.Reader temp = C_DynamicValue.Reader(temp_string)
    thisptr.set(field, temp)


cdef _setBytesField(DynamicStruct_Builder thisptr, _StructSchemaField field, value):
    cdef capnp.StringPtr temp_string = capnp.StringPtr(<char*>value, len(value))
    cdef C_DynamicValue.Reader temp = C_DynamicValue.Reader(temp_string)
    thisptr.setByField(field.thisptr, temp)

cdef _setMemoryviewField(DynamicStruct_Builder thisptr, _StructSchemaField field, value):
    cdef Py_buffer buf
    cdef capnp.StringPtr temp_string
    cdef C_DynamicValue.Reader temp
    if PyObject_GetBuffer(value, &buf, PyBUF_CONTIG_RO) != 0:
        raise KjException(
            "cannot get buffer from memory view, for field '{}'".format(field)
        )
    try:
        temp_string = capnp.StringPtr(<char *>buf.buf, buf.len)
        temp = C_DynamicValue.Reader(temp_string)
        thisptr.setByField(field.thisptr, temp)
    finally:
        PyBuffer_Release(&buf)

cdef _setBaseStringField(DynamicStruct_Builder thisptr, _StructSchemaField field, value):
    encoded_value = value.encode('utf-8')
    cdef capnp.StringPtr temp_string = capnp.StringPtr(<char*>encoded_value, len(encoded_value))
    cdef C_DynamicValue.Reader temp = C_DynamicValue.Reader(temp_string)
    thisptr.setByField(field.thisptr, temp)


cdef _setDynamicField(_DynamicSetterClasses thisptr, field, value, parent):
    cdef C_DynamicValue.Reader temp
    value_type = type(value)

    if value_type is int or value_type is long:
        if value < 0:
            temp = C_DynamicValue.Reader(<long long>value)
        else:
            temp = C_DynamicValue.Reader(<unsigned long long>value)
        thisptr.set(field, temp)
    elif value_type is float:
        temp = C_DynamicValue.Reader(<double>value)
        thisptr.set(field, temp)
    elif value_type is bool:
        temp = C_DynamicValue.Reader(<cbool>value)
        thisptr.set(field, temp)
    elif value_type is bytes:
        _setBytes(thisptr, field, value)
    elif isinstance(value, BuiltinsMemoryview):
        _setMemoryview(thisptr, field, value)
    elif isinstance(value, basestring):
        _setBaseString(thisptr, field, value)
    elif value_type is list:
        ptr = thisptr.init(field, len(value))
        builder = to_python_builder(ptr, parent)
        _from_list(builder, value)
    elif value_type is tuple:
        ptr = thisptr.init(field, len(value))
        builder = to_python_builder(ptr, parent)
        _from_tuple(builder, value)
    elif value_type is dict:
        if _DynamicSetterClasses is DynamicStruct_Builder:
            ptr = thisptr.get(field)
            builder = to_python_builder(ptr, parent)
            builder.from_dict(value)
        else:
            ptr = thisptr[field]
            builder = to_python_builder(ptr, parent)
            builder.from_dict(value)
    elif value is None:
        temp = C_DynamicValue.Reader(VOID)
        thisptr.set(field, temp)
    elif value_type is _DynamicStructBuilder:
        thisptr.set(field, _extract_dynamic_struct_builder(value))
    elif value_type is _DynamicStructReader:
        thisptr.set(field, _extract_dynamic_struct_reader(value))
    elif value_type is _DynamicListBuilder:
        thisptr.set(field, _extract_dynamic_list_builder(value))
    elif value_type is _DynamicListReader:
        thisptr.set(field, _extract_dynamic_list_reader(value))
    elif value_type is _DynamicEnum:
        thisptr.set(field, _extract_dynamic_enum(value))
    else:
        raise KjException(
            "Tried to set field: '{}' with a value of: '{}' which is an unsupported type: '{}'"
            .format(field, str(value), str(type(value))))


cdef _setDynamicFieldWithField(DynamicStruct_Builder thisptr, _StructSchemaField field, value, parent):
    cdef C_DynamicValue.Reader temp
    value_type = type(value)

    if value_type is int or value_type is long:
        if value < 0:
            temp = C_DynamicValue.Reader(<long long>value)
        else:
            temp = C_DynamicValue.Reader(<unsigned long long>value)
        thisptr.setByField(field.thisptr, temp)
    elif value_type is float:
        temp = C_DynamicValue.Reader(<double>value)
        thisptr.setByField(field.thisptr, temp)
    elif value_type is bool:
        temp = C_DynamicValue.Reader(<cbool>value)
        thisptr.setByField(field.thisptr, temp)
    elif value_type is bytes:
        _setBytesField(thisptr, field, value)
    elif isinstance(value, BuiltinsMemoryview):
        _setMemoryviewField(thisptr, field, value)
    elif isinstance(value, basestring):
        _setBaseStringField(thisptr, field, value)
    elif value_type is list:
        ptr = thisptr.init(field.proto.name, len(value))
        builder = to_python_builder(ptr, parent)
        _from_list(builder, value)
    elif value_type is dict:
        ptr = thisptr.getByField(field.thisptr)
        builder = to_python_builder(ptr, parent)
        builder.from_dict(value)
    elif value is None:
        temp = C_DynamicValue.Reader(VOID)
        thisptr.setByField(field.thisptr, temp)
    elif value_type is _DynamicStructBuilder:
        thisptr.setByField(field.thisptr, _extract_dynamic_struct_builder(value))
    elif value_type is _DynamicStructReader:
        thisptr.setByField(field.thisptr, _extract_dynamic_struct_reader(value))
    elif value_type is _DynamicListBuilder:
        thisptr.setByField(field.thisptr, _extract_dynamic_list_builder(value))
    elif value_type is _DynamicListReader:
        thisptr.setByField(field.thisptr, _extract_dynamic_list_reader(value))
    elif value_type is _DynamicEnum:
        thisptr.setByField(field.thisptr, _extract_dynamic_enum(value))
    else:
        raise KjException(
            "Tried to set field: '{}' with a value of: '{}' which is an unsupported type: '{}'"
            .format(field, str(value), str(type(value))))


cdef _to_dict(msg, bint verbose):
    msg_type = type(msg)
    if msg_type is _DynamicListBuilder:
        temp_list_b = msg
        return [_to_dict(temp_list_b._get(i), verbose) for i in range(len(msg))]
    elif msg_type is _DynamicListReader:
        temp_list_r = msg
        return [_to_dict(temp_list_r._get(i), verbose) for i in range(len(msg))]

    if msg_type is _DynamicStructBuilder:
        temp_msg_b = msg
        ret = {}
        try:
            which = temp_msg_b.which()
            ret[which] = _to_dict(temp_msg_b._get(which), verbose)
        except KjException:
            pass

        for field in temp_msg_b.schema.non_union_fields:
            if verbose or temp_msg_b._has(field):
                ret[field] = _to_dict(temp_msg_b._get(field), verbose)

        return ret
    elif msg_type is _DynamicStructReader:
        temp_msg_r = msg
        ret = {}
        try:
            which = temp_msg_r.which()
            ret[which] = _to_dict(temp_msg_r._get(which), verbose)
        except KjException:
            pass

        for field in temp_msg_r.schema.non_union_fields:
            if verbose or temp_msg_r._has(field):
                ret[field] = _to_dict(temp_msg_r._get(field), verbose)

        return ret

    if isinstance(msg, (_DynamicStructBuilder, _DynamicStructReader)):
        return msg.to_dict(verbose)

    if msg_type is _DynamicEnum:
        return str(msg)

    return msg


cdef _from_list(_DynamicListBuilder msg, list d):
    for i, x in enumerate(d):
        msg._set(i, x)


cdef _from_tuple(_DynamicListBuilder msg, tuple d):
    for i, x in enumerate(d):
        msg._set(i, x)


cdef class _DynamicEnum:
    cdef _init(self, capnp.DynamicEnum other, object parent):
        self.thisptr = other
        self._parent = parent
        return self

    cpdef _as_str(self):
        return <char*>helpers.fixMaybe(self.thisptr.getEnumerant()).getProto().getName().cStr()

    property raw:
        """A property that returns the raw int of the enum"""
        def __get__(self):
            return self.thisptr.getRaw()

    def __str__(self):
        return self._as_str()

    def __repr__(self):
        return '<%s enum>' % str(self)

    def __richcmp__(_DynamicEnum self, right, int op):
        if isinstance(right, basestring):
            left = self._as_str()
        else:
            left = self.thisptr.getRaw()

        if op == 2: # ==
            return left == right
        elif op == 3: # !=
            return left != right
        elif op == 0: # <
            return left < right
        elif op == 1: # <=
            return left <= right
        elif op == 4: # >
            return left > right
        elif op == 5: # >=
            return left >= right

    def __hash__(_DynamicEnum self):
        return hash(self._as_str())


cdef class _DynamicEnumField:
    cdef _init(self, proto):
        self.thisptr = proto
        return self

    property raw:
        """A property that returns the raw int of the enum"""
        def __get__(self):
            return self.thisptr.discriminantValue

    cpdef _str(self):
        return self.thisptr.name

    def __str__(self):
        return self._str()

    def __repr__(self):
        return '<%s which-enum>' % str(self)

    def __richcmp__(_DynamicEnumField self, right, int op):
        if isinstance(right, basestring):
            left = self.thisptr.name
        else:
            left = self.thisptr.discriminantValue

        if op == 2: # ==
            return left == right
        elif op == 3: # !=
            return left != right
        elif op == 0: # <
            return left < right
        elif op == 1: # <=
            return left <= right
        elif op == 4: # >
            return left > right
        elif op == 5: # >=
            return left >= right

    def __call__(self):
        return str(self)


cdef class _MessageSize:
    cdef public uint64_t word_count
    cdef public uint cap_count

    def __init__(self, uint64_t word_count, uint cap_count):
        self.word_count = word_count
        self.cap_count = cap_count


def _struct_reducer(schema_id, data):
    with _global_schema_parser.modules_by_id[schema_id].from_bytes(data) as msg:
        return msg


cdef class _DynamicStructReader:
    """Reads Cap'n Proto structs

    This class is almost a 1 for 1 wrapping of the Cap'n Proto C++ DynamicStruct::Reader.
    The only difference is that instead of a `get` method, __getattr__ is overloaded and the field name
    is passed onto the C++ equivalent `get`. This means you just use . syntax to access any field.
    For field names that don't follow valid python naming convention for fields, use the global function
    :py:func:`getattr`::

        person = addressbook.Person.new_message() # This returns a _DynamicStructReader
        print person.name # using . syntax
        print getattr(person, 'field-with-hyphens') # for names that are invalid for python, use getattr
    """
    cdef _init(self, C_DynamicStruct.Reader other, object parent, bint isRoot=False):
        self.thisptr = other
        self._parent = parent
        self.is_root = isRoot
        self._schema = None

        return self

    cpdef _get(self, field):
        ptr = self.thisptr.get(field)
        return to_python_reader(ptr, self)

    def __getattr__(self, field):
        try:
            return self._get(field)
        except KjException as e:
            raise e._to_python() from None

    cpdef _get_by_field(self, _StructSchemaField field):
        ptr = self.thisptr.getByField(field.thisptr)
        return to_python_reader(ptr, self)

    cpdef _has(self, field):
        return self.thisptr.has(field)

    cpdef _DynamicEnumField _which(self):
        """Returns the enum corresponding to the union in this struct

        :rtype: :class:`_DynamicEnumField`
        :return: A string/enum corresponding to what field is set in the union

        :Raises: :exc:`KjException` if this struct doesn't contain a union
        """
        try:
            which = _DynamicEnumField()._init(
                _StructSchemaField()._init(helpers.fixMaybe(self.thisptr.which()), self).proto)
        except RuntimeError as e:
            if str(e) == "Member was null.":
                raise KjException("Attempted to call which on a non-union type")
            raise

        return which

    property which:
        """Returns the enum corresponding to the union in this struct

        :rtype: :class:`_DynamicEnumField`
        :return: A string/enum corresponding to what field is set in the union

        :Raises: :exc:`KjException` if this struct doesn't contain a union
        """
        def __get__(_DynamicStructReader self):
            return self._which()

    property schema:
        """A property that returns the _StructSchema object matching this reader"""
        def __get__(self):
            if self._schema is None:
                self._schema = _StructSchema()._init_child(self.thisptr.getSchema())
            return self._schema

    def __dir__(self):
        return list(set(self.schema.fieldnames + tuple(dir(self.__class__))))

    def __str__(self):
        return <char*>printStructReader(self.thisptr).flatten().cStr()

    def __repr__(self):
        return '<%s reader %s>' % (self.schema.node.displayName, <char*>strStructReader(self.thisptr).cStr())

    def to_dict(self, verbose=False):
        return _to_dict(self, verbose)

    cpdef as_builder(self):
        """A method for casting this Reader to a Builder

        This is a copying operation with respect to the message's buffer.
        Changes in the new builder will not reflect in the original reader.

        :rtype: :class:`_DynamicStructBuilder`
        """
        builder = _MallocMessageBuilder()
        return builder.set_root(self)

    property total_size:
        def __get__(self):
            size = self.thisptr.totalSize()
            return _MessageSize(size.wordCount, size.capCount)

    def __reduce_ex__(self, proto):
        return _struct_reducer, (self.schema.node.id, self.as_builder().to_bytes())


cdef class _DynamicStructBuilder:
    """Builds Cap'n Proto structs

    This class is almost a 1 for 1 wrapping of the Cap'n Proto C++ DynamicStruct::Builder.
    The only difference is that instead of a `get`/`set` method, __getattr__/__setattr__ is overloaded
    and the field name is passed onto the C++ equivalent function.

    This means you just use . syntax to access or set any field. For field names that don't follow valid
    python naming convention for fields, use the global functions :py:func:`getattr`/:py:func:`setattr`::

        person = addressbook.Person.new_message() # This returns a _DynamicStructBuilder

        person.name = 'foo' # using . syntax
        print person.name # using . syntax

        setattr(person, 'field-with-hyphens', 'foo') # for names that are invalid for python, use setattr
        print getattr(person, 'field-with-hyphens') # for names that are invalid for python, use getattr
    """
    cdef _init(self, DynamicStruct_Builder other, object parent, bint isRoot=False):
        self.thisptr = other
        self._parent = parent
        self.is_root = isRoot
        self._is_written = False
        self._schema = None

        return self

    cdef _check_write(self):
        if not self.is_root:
            raise KjException("You can only serialize the message's root struct.")
        if self._is_written:
            _warnings.warn(
                "This message has already been written once. Be very careful that you're not setting "
                "Text/Struct/List fields more than once, since that will cause memory leaks "
                "(both in memory and in the serialized data). You can disable this warning by "
                "calling the `clear_write_flag` method of this object after every write.")

    cpdef to_bytes(_DynamicStructBuilder self):
        """Returns the struct's containing message as a Python bytes object in the unpacked binary format.

        :rtype: bytes

        :Raises: :exc:`KjException` if this isn't the message's root struct.
        """
        self._check_write()
        cdef _MessageBuilder builder = self._parent
        cdef bytes ret = messageToPythonBytes(deref(builder.thisptr))
        self._is_written = True
        return ret

    cpdef _get(self, field):
        ptr = self.thisptr.get(field)
        return to_python_builder(ptr, self._parent)

    cpdef _get_by_field(self, _StructSchemaField field):
        ptr = self.thisptr.getByField(field.thisptr)
        return to_python_builder(ptr, self._parent)

    def __getattr__(self, field):
        try:
            return self._get(field)
        except KjException as e:
            raise e._to_python() from None

    cpdef _set(self, field, value):
        _setDynamicField(self.thisptr, field, value, self._parent)

    cpdef _set_by_field(self, _StructSchemaField field, value):
        _setDynamicFieldWithField(self.thisptr, field, value, self._parent)

    def __setattr__(self, field, value):
        try:
            self._set(field, value)
        except KjException as e:
            raise e._to_python() from None

    cpdef _has(self, field):
        return self.thisptr.has(field)

    cpdef init(self, field, size=None):
        """Method for initializing fields that are of type union/struct/list

        Typically, you don't have to worry about initializing structs/unions, so this method is mainly for lists.

        :type field: str
        :param field: The field name to initialize

        :type size: int
        :param size: The size of the list to initiialize. This should be None for struct/union initialization.

        :rtype: :class:`_DynamicStructBuilder` or :class:`_DynamicListBuilder`

        :Raises: :exc:`KjException` if the field isn't in this struct
        """
        if isinstance(field, _StructModuleWhich):
            field = field.name[0].lower() + field.name[1:]
        if size is None:
            ptr = self.thisptr.init(field)
            return to_python_builder(ptr, self._parent)
        else:
            ptr = self.thisptr.init(field, size)
            return to_python_builder(ptr, self._parent)

    cpdef _DynamicEnumField _which(self):
        """Returns the enum corresponding to the union in this struct

        :rtype: :class:`_DynamicEnumField`
        :return: A string/enum corresponding to what field is set in the union

        :Raises: :exc:`KjException` if this struct doesn't contain a union
        """
        try:
            which = _DynamicEnumField()._init(
                _StructSchemaField()._init(helpers.fixMaybe(self.thisptr.which()), self).proto)
        except RuntimeError as e:
            if str(e) == "Member was null.":
                raise KjException("Attempted to call which on a non-union type")
            raise

        return which

    property which:
        """Returns the enum corresponding to the union in this struct

        :rtype: :class:`_DynamicEnumField`
        :return: A string/enum corresponding to what field is set in the union

        :Raises: :exc:`KjException` if this struct doesn't contain a union
        """
        def __get__(_DynamicStructBuilder self):
            return self._which()

    cpdef as_reader(self):
        """A method for casting this Builder to a Reader

        This is a non-copying operation with respect to the message's buffer.
        This means changes to the fields in the original struct will carry over to the new reader.

        :rtype: :class:`_DynamicStructReader`
        """
        cdef _DynamicStructReader reader
        reader = _DynamicStructReader()._init(
            self.thisptr.asReader(), self._parent, self.is_root)
        reader._obj_to_pin = self
        return reader

    cpdef copy(self):
        """A method for copying this Builder

        This is a copying operation with respect to the message's buffer.
        Changes in the new builder will not reflect in the original reader.

        :rtype: :class:`_DynamicStructBuilder`
        """
        builder = _MallocMessageBuilder()
        return builder.set_root(self)

    property schema:
        """A property that returns the _StructSchema object matching this writer"""
        def __get__(self):
            if self._schema is None:
                self._schema = _StructSchema()._init_child(self.thisptr.getSchema())
            return self._schema

    def __dir__(self):
        return list(set(self.schema.fieldnames + tuple(dir(self.__class__))))

    def __str__(self):
        return <char*>printStructBuilder(self.thisptr).flatten().cStr()

    def __repr__(self):
        return '<%s builder %s>' % (self.schema.node.displayName, <char*>strStructBuilder(self.thisptr).cStr())

    def to_dict(self, verbose=False):
        return _to_dict(self, verbose)

    def from_dict(self, dict d):
        for key, val in d.iteritems():
            if key != 'which':
                if isinstance(val, str):
                    key_bytes = key.encode()
                    if self.thisptr.getSchema().getFieldByName(key_bytes).getType().isData():
                        # decode bytes from utf-8 base64 encoding
                        val = base64.b64decode(val)
                try:
                    self._set(key, val)
                except Exception as e:
                    if 'expected isSetInUnion(field)' in str(e):
                        self.init(key)
                        self._set(key, val)
                    else:
                        raise

    property total_size:
        def __get__(self):
            size = self.thisptr.totalSize()
            return _MessageSize(size.wordCount, size.capCount)

    def clear_write_flag(self):
        """A method used to clear the _is_written flag.

        This allows you to write the struct more than once without seeing any warnings.
        """
        self._is_written = False

    def __reduce_ex__(self, proto):
        return _struct_reducer, (self.schema.node.id, self.to_bytes())


cdef class _Schema:
    cdef _init(self, C_Schema other):
        self.thisptr = other
        return self

    cpdef as_const_value(self):
        ptr = <C_DynamicValue.Reader>self.thisptr.asConst()
        return to_python_reader(ptr, self)

    cpdef as_struct(self):
        return _StructSchema()._init_child(self.thisptr.asStruct())

    cpdef as_enum(self):
        return _EnumSchema()._init(self.thisptr.asEnum())

    cpdef get_proto(self):
        return _NodeReader().init(self.thisptr.getProto())

    property node:
        """The raw schema node"""
        def __get__(self):
            return _DynamicStructReader()._init(self.thisptr.getProto(), self)


cdef class _StructSchema(_Schema):
    cdef C_StructSchema thisptr_child
    cdef object __fieldnames, __union_fields, __non_union_fields, __fields
    cdef _init_child(self, C_StructSchema other):
        self.thisptr_child = other
        self._init(other)
        self.__fieldnames = None
        self.__union_fields = None
        self.__non_union_fields = None
        self.__fields = None
        return self

    cdef C_StructSchema _thisptr(self):
        return self.thisptr_child

    property fieldnames:
        """A tuple of the field names in the struct."""
        def __get__(self):
            if self.__fieldnames is not None:
                return self.__fieldnames
            fieldlist = self._thisptr().getFields()
            nfields = fieldlist.size()
            self.__fieldnames = tuple(<char*>fieldlist[i].getProto().getName().cStr() for i in xrange(nfields))
            return self.__fieldnames

    property union_fields:
        """A tuple of the field names in the struct."""
        def __get__(self):
            if self.__union_fields is not None:
                return self.__union_fields
            fieldlist = self._thisptr().getUnionFields()
            nfields = fieldlist.size()
            self.__union_fields = tuple(
                <char*>fieldlist[i].getProto().getName().cStr() for i in xrange(nfields))
            return self.__union_fields

    property non_union_fields:
        """A tuple of the field names in the struct."""
        def __get__(self):
            if self.__non_union_fields is not None:
                return self.__non_union_fields
            fieldlist = self._thisptr().getNonUnionFields()
            nfields = fieldlist.size()
            self.__non_union_fields = tuple(
                <char*>fieldlist[i].getProto().getName().cStr() for i in xrange(nfields))
            return self.__non_union_fields

    property fields:
        """All of the _StructSchemaField in this schema as a dict"""
        def __get__(self):
            if self.__fields is not None:
                return self.__fields
            fieldlist = self._thisptr().getFields()
            nfields = fieldlist.size()
            self.__fields = {
                <char*>fieldlist[i].getProto().getName().cStr(): _StructSchemaField()._init(fieldlist[i], self)
                for i in xrange(nfields)
            }
            return self.__fields

    property node:
        """The raw schema node"""
        def __get__(self):
            return _DynamicStructReader()._init(self._thisptr().getProto(), self)

    def __repr__(self):
        return '<schema for %s>' % self.node.displayName


cdef typeAsSchema(capnp.SchemaType fieldType):
    # TODO(soon): make sure this is memory safe
    if fieldType.isStruct():
        return _StructSchema()._init_child(fieldType.asStruct())
    elif fieldType.isEnum():
        return _EnumSchema()._init(fieldType.asEnum())
    elif fieldType.isList():
        return _ListSchema()._init(fieldType.asList())
    else:
        raise KjException("Schema type is unknown")


cdef class _StructSchemaField:
    cdef _init(self, C_StructSchema.Field other, parent=None):
        self.thisptr = other
        self._parent = parent
        return self

    property proto:
        """The raw schema proto"""
        def __get__(self):
            return _DynamicStructReader()._init(self.thisptr.getProto(), self)

    property schema:
        """The schema of this field, or None if it's a type without a schema"""
        def __get__(self):
            return typeAsSchema(self.thisptr.getType())

    def __repr__(self):
        return '<field schema for %s>' % self.proto.name


cdef class _EnumSchema:
    cdef C_EnumSchema thisptr

    cdef _init(self, C_EnumSchema other):
        self.thisptr = other
        return self

    property enumerants:
        """The list of enumerants as a dictionary"""
        def __get__(self):
            ret = {}
            enumerants = self.thisptr.getEnumerants()
            for i in range(enumerants.size()):
                enumerant = enumerants[i]
                ret[<char *>enumerant.getProto().getName().cStr()] = enumerant.getOrdinal()

            return ret

    property node:
        """The raw schema node"""
        def __get__(self):
            return _DynamicStructReader()._init(self.thisptr.getProto(), self)


cdef class _ListSchema:
    cdef C_ListSchema thisptr

    cdef _init(self, C_ListSchema other):
        self.thisptr = other
        return self

    property elementType:
        """The schema of the element type of this list"""
        def __get__(self):
            return typeAsSchema(self.thisptr.getElementType())


cdef class _ParsedSchema(_Schema):
    cdef C_ParsedSchema thisptr_child
    cdef _init_child(self, C_ParsedSchema other):
        self.thisptr_child = other
        self._init(other)
        return self

    cpdef get_nested(self, name):
        return _ParsedSchema()._init_child(self.thisptr_child.getNested(name))


cdef _new_message(self, kwargs):
    cdef _MessageBuilder builder
    builder = _MallocMessageBuilder()
    msg = builder.init_root(self.schema)
    if kwargs is not None:
        msg.from_dict(kwargs)
    return msg


class _StructModuleWhich(_enum.Enum):
    def __eq__(self, other):
        if isinstance(other, int):
            return self.value == other
        else:
            return self.name == other


class _StructModule(object):
    def __init__(self, schema):
        self.schema = schema

        # Add enums for union fields
        for field, raw_field in zip(schema.node.struct.fields, schema.fields.values()):
            if field.which() == 'group':
                name = field.name[0].upper() + field.name[1:]
                raw_schema = raw_field.schema
                field_schema = raw_schema.node.struct

                if field_schema.discriminantCount == 0:
                    sub_module = _StructModule(raw_schema)
                else:
                    mapping = []
                    for union_field in field_schema.fields:
                        mapping.append((union_field.name, union_field.discriminantValue))
                    sub_module = _StructModuleWhich("StructModuleWhich", mapping)
                    setattr(sub_module, 'schema', raw_schema)
                setattr(self, name, sub_module)

    def read_multiple_bytes(self, buf, traversal_limit_in_words=None, nesting_limit=None):
        """Returns an iterable, that when traversed will return Readers for messages.

        :type buf: buffer
        :param buf: Any Python object that supports the buffer interface.

        :type traversal_limit_in_words: int
        :param traversal_limit_in_words: Limits how many total words of data are allowed to be traversed.
                                         Is actually a uint64_t, and values can be up to 2^64-1. Default is 8*1024*1024.

        :type nesting_limit: int
        :param nesting_limit: Limits how many total words of data are allowed to be traversed. Default is 64.

        :rtype: Iterable with elements of :class:`_DynamicStructReader`"""
        reader = _MultipleBytesMessageReader(buf, self.schema, traversal_limit_in_words, nesting_limit)
        return reader

    @contextlib.contextmanager
    def from_bytes(self, buf, traversal_limit_in_words=None, nesting_limit=None):
        """Returns a Reader for the unpacked object in buf.

        :type buf: buffer
        :param buf: Any Python object that supports the buffer interface.

        :type traversal_limit_in_words: int
        :param traversal_limit_in_words: Limits how many total words of data are allowed to be traversed.
                                         Is actually a uint64_t, and values can be up to 2^64-1. Default is 8*1024*1024.

        :type nesting_limit: int
        :param nesting_limit: Limits how many total words of data are allowed to be traversed. Default is 64.

        :rtype: :class:`_DynamicStructReader`
        """
        message = None
        try:
            message = _FlatArrayMessageReader(buf, traversal_limit_in_words, nesting_limit)
            yield message.get_root(self.schema)
        finally:
            if message:
                message.close()

    def __call__(self, **kwargs):
        return self.new_message(**kwargs)

    def new_message(self, **kwargs):
        """Returns a newly allocated builder message.

        :type kwargs: dict
        :param kwargs: A list of fields and their values to initialize in the struct.

        Note, kwargs is not an actual argument, but refers to Python's ability to pass keyword arguments.
        ie. new_message(my_field=100)

        :rtype: :class:`_DynamicStructBuilder`
        """
        return _new_message(self, kwargs)


class _EnumModule(object):
    def __init__(self, schema):
        self.schema = schema
        for name, val in schema.enumerants.items():
            setattr(self, name, val)


cdef class _StringArrayPtr:
    def __cinit__(self, size_t size, parent):
        self.size = size
        self.thisptr = <StringPtr *>malloc(sizeof(StringPtr) * size)
        self.parent = parent

    def __dealloc__(self):
        free(self.thisptr)

    cdef ArrayPtr[StringPtr] asArrayPtr(self):
        return ArrayPtr[StringPtr](self.thisptr, self.size)


cdef class SchemaParser:
    """A class for loading Cap'n Proto schema files.

    Do not use this class unless you're sure you know what you're doing.
    Use the convenience method :func:`load` instead.
    """

    def __cinit__(self):
        self.thisptr = new C_SchemaParser()
        self.modules_by_id = {}
        self._all_imports = []

    def __dealloc__(self):
        del self.thisptr

    cpdef _parse_disk_file(self, displayName, diskPath, imports):
        cdef _StringArrayPtr importArray

        if self._last_import_array and self._last_import_array.parent == imports:
            importArray = self._last_import_array
        else:
            importArray = _StringArrayPtr(len(imports), imports)

            for i in range(len(imports)):
                curr_import = imports[i]
                importArray.thisptr[i] = StringPtr(curr_import, <size_t>len(curr_import))

            self._all_imports.append(importArray)
            self._last_import_array = importArray

        ret = _ParsedSchema()
        ret._init_child(self.thisptr.parseDiskFile(displayName, diskPath, importArray.asArrayPtr()))

        return ret

    def load(self, file_name, display_name=None, imports=[]):
        """Load a Cap'n Proto schema from a file

        You will have to load a schema before you can begin doing anything
        meaningful with this library. Loading a schema is much like loading
        a Python module (and load even returns a `ModuleType`). Once it's been
        loaded, you use it much like any other Module::

            parser = capnp.SchemaParser()
            addressbook = parser.load('addressbook.capnp')
            print addressbook.qux # qux is a top level constant
            # 123
            person = addressbook.Person.new_message()

        :type file_name: str
        :param file_name: A relative or absolute path to a Cap'n Proto schema

        :type display_name: str
        :param display_name: The name internally used by the Cap'n Proto library
            for the loaded schema. By default, it's just os.path.basename(file_name)

        :type imports: list
        :param imports: A list of str directories to add to the import path.

        :rtype: ModuleType
        :return: A module corresponding to the loaded schema. You can access
            parsed schemas and constants with . syntax

        :Raises:
            - :exc:`exceptions.IOError` if `file_name` doesn't exist
            - :exc:`KjException` if the Cap'n Proto C++ library has any problems loading the schema

        """
        def _load(nodeSchema, module):
            module._nodeSchema = nodeSchema
            nodeProto = nodeSchema.get_proto()
            module._nodeProto = nodeProto

            self.modules_by_id[nodeProto.id] = module

            for node in nodeProto.nestedNodes:
                local_module = _ModuleType(node.name)

                schema = nodeSchema.get_nested(node.name)
                proto = schema.get_proto()
                if proto.isStruct:
                    local_module = _StructModule(schema.as_struct())

                    module.__dict__[node.name] = local_module
                elif proto.isConst:
                    module.__dict__[node.name] = schema.as_const_value()
                elif proto.isInterface:
                    continue
                elif proto.isEnum:
                    local_module = _EnumModule(schema.as_enum())

                    module.__dict__[node.name] = local_module

                _load(schema, local_module)
        if not _os.path.isfile(file_name):
            raise IOError("File not found: " + file_name)

        if not file_name.endswith('.capnp'):
            raise ValueError("File does not end with .capnp, {}".format(file_name))

        if display_name is None:
            display_name = _os.path.basename(file_name)

        module = _ModuleType(display_name)
        parser = self

        module._parser = parser

        # Only pass directories to the schema parser.
        filtered_imports = []
        for imp in imports:
            if _os.path.isdir(imp):
                filtered_imports.append(imp)
        fileSchema = parser._parse_disk_file(display_name, file_name, filtered_imports)
        _load(fileSchema, module)

        abs_path = _os.path.abspath(file_name)
        module.__path__ = [_os.path.dirname(abs_path)]
        module.__file__ = abs_path
        module.schema = fileSchema

        return module


cdef class _MessageBuilder:
    """An abstract base class for building Cap'n Proto messages

    .. warning:: Don't ever instantiate this class directly. It is only used for inheritance.
    """
    def __dealloc__(self):
        del self.thisptr

    def __init__(self):
        raise NotImplementedError("This is an abstract base class. You should use MallocMessageBuilder instead")

    cpdef init_root(self, schema):
        """A method for instantiating Cap'n Proto structs

        You will need to pass in a schema to specify which struct to
        instantiate. Schemas are available in a loaded Cap'n Proto module::

            addressbook = capnp.load('addressbook.capnp')
            ...
            person = message.init_root(addressbook.Person)

        :type schema: Schema
        :param schema: A Cap'n proto schema specifying which struct to instantiate

        :rtype: :class:`_DynamicStructBuilder`
        :return: An object where you will set all the members
        """
        cdef _StructSchema s
        if hasattr(schema, 'schema'):
            s = schema.schema
        else:
            s = schema
        ptr = s._thisptr()
        return _DynamicStructBuilder()._init(self.thisptr.initRootDynamicStruct(ptr), self, True)

    cpdef get_root(self, schema):
        """A method for instantiating Cap'n Proto structs, from an already pre-written buffer

        Don't use this method unless you know what you're doing. You probably
        want to use init_root instead::

            addressbook = capnp.load('addressbook.capnp')
            ...
            person = message.init_root(addressbook.Person)
            ...
            person = message.get_root(addressbook.Person)

        :type schema: Schema
        :param schema: A Cap'n proto schema specifying which struct to instantiate

        :rtype: :class:`_DynamicStructBuilder`
        :return: An object where you will set all the members
        """
        cdef _StructSchema s
        if hasattr(schema, 'schema'):
            s = schema.schema
        else:
            s = schema
        ptr = s._thisptr()
        return _DynamicStructBuilder()._init(self.thisptr.getRootDynamicStruct(ptr), self, True)

    cpdef set_root(self, value):
        """A method for instantiating Cap'n Proto structs by copying from an existing struct

        :type value: :class:`_DynamicStructReader`
        :param value: A Cap'n Proto struct value to copy

        :rtype: void
        """
        value_type = type(value)
        if value_type is _DynamicStructBuilder:
            self.thisptr.setRootDynamicStruct((<_DynamicStructReader>value.as_reader()).thisptr)
            return self.get_root(value.schema)
        elif value_type is _DynamicStructReader:
            self.thisptr.setRootDynamicStruct((<_DynamicStructReader>value).thisptr)
            return self.get_root(value.schema)

cdef class _MallocMessageBuilder(_MessageBuilder):
    """The main class for building Cap'n Proto messages

    You will use this class to handle arena allocation of the Cap'n Proto
    messages. You also use this object when you're done assigning to Cap'n
    Proto objects, and wish to serialize them::

        addressbook = capnp.load('addressbook.capnp')
        message = capnp._MallocMessageBuilder()
        person = message.init_root(addressbook.Person)
        person.name = 'alice'
        ...
        data = person.to_bytes()
    """
    def __init__(self):
        self.thisptr = new schema_cpp.MallocMessageBuilder()


cdef class _MessageReader:
    """An abstract base class for reading Cap'n Proto messages

    .. warning:: Don't ever instantiate this class. It is only used for inheritance.
    """
    cdef public object _parent
    cdef schema_cpp.MessageReader * thisptr

    def __init__(self):
        raise NotImplementedError("This is an abstract base class")

    cpdef get_root(self, schema):
        """A method for instantiating Cap'n Proto structs

        You will need to pass in a schema to specify which struct to
        instantiate. Schemas are available in a loaded Cap'n Proto module::

            addressbook = capnp.load('addressbook.capnp')
            ...
            person = message.get_root(addressbook.Person)

        :type schema: Schema
        :param schema: A Cap'n proto schema specifying which struct to instantiate

        :rtype: :class:`_DynamicStructReader`
        :return: An object with all the data of the read Cap'n Proto message.
            Access members with . syntax.
        """
        cdef _StructSchema s
        if hasattr(schema, 'schema'):
            s = schema.schema
        else:
            s = schema
        ptr = s._thisptr()
        return _DynamicStructReader()._init(self.thisptr.getRootDynamicStruct(ptr), self)

cdef class _MultipleBytesMessageReader:
    cdef Py_ssize_t offset, sz
    cdef const char *ptr
    cdef object _object_to_pin
    cdef public object traversal_limit_in_words, nesting_limit, schema

    def __init__(self, buf, schema, traversal_limit_in_words=None, nesting_limit=None):
        self.offset = 0
        self.schema = schema
        self.traversal_limit_in_words = traversal_limit_in_words
        self.nesting_limit = nesting_limit

        self.sz = len(buf)
        if isinstance(buf, bytes):
            self.ptr = buf
            if (<uintptr_t>self.ptr) % 8 != 0:
                aligned = _AlignedBuffer(buf)
                self.ptr = aligned.buf
                self._object_to_pin = aligned
            else:
                self._object_to_pin = buf
                self.ptr = buf
        elif PyObject_CheckBuffer(buf):
            view = _BufferView(buf)
            self.ptr = view.buf
            self._object_to_pin = view
        else:
            raise TypeError('expected buffer-like object in FlatArrayMessageReader')

    def __next__(self):
        cdef _FlatArrayMessageReaderAligned reader
        if self.offset == self.sz:
            raise StopIteration
        try:
            reader = _FlatArrayMessageReaderAligned()
            reader._init(self._object_to_pin, self.ptr + self.offset, self.sz - self.offset,
                         self.traversal_limit_in_words, self.nesting_limit)
            self.offset += reader.msg_size
            return reader.get_root(self.schema)
        except KjException as e:
            if 'EOF' in str(e):
                raise StopIteration
            else:
                raise

    def __iter__(self):
        return self


cdef class _AlignedBuffer:
    cdef char * buf
    cdef bint allocated
    cdef Py_buffer view

    # other should also have a length that's a multiple of 8
    def __init__(self, other):
        if PyObject_GetBuffer(other, &self.view, PyBUF_SIMPLE) != 0:
            raise KjException("could not get read buffer")
        other_len = len(other)

        # malloc is defined as being word aligned
        # we don't care about adding NULL terminating character
        self.buf = <char *>malloc(other_len)
        memcpy(self.buf, self.view.buf, other_len)
        self.allocated = True

    def __dealloc__(self):
        if self.allocated:
            free(self.buf)
        PyBuffer_Release(&self.view)


@cython.internal
cdef class _BufferView:
    cdef Py_buffer view
    cdef char * buf
    cdef int closed

    def __init__(self, other):
        cdef int ret = PyObject_GetBuffer(other, &self.view, PyBUF_SIMPLE)
        if ret < 0:
            raise ValueError("Invalid buffer passed to BufferView")
        self.buf = <char*>self.view.buf
        self.closed = False

    def close(self):
        if not self.closed:
            PyBuffer_Release(&self.view)
            self.closed = True

    def __dealloc__(self):
        self.close()


@cython.internal
cdef class _FlatArrayMessageReaderAligned(_MessageReader):
    """
    Creates a reader based on a contiguous block of memory

    For performance consideration it's assumed that the provided buffer is already aligned. This
    allows us to align a set of adjacent messages with a single align operation.
    """
    cdef object _object_to_pin
    cdef Py_ssize_t msg_size

    def __init__(self):
        self.msg_size = 0

    cdef _init(self, buf, const char *ptr, Py_ssize_t sz, traversal_limit_in_words=None, nesting_limit=None):
        cdef schema_cpp.ReaderOptions opts = make_reader_opts(traversal_limit_in_words, nesting_limit)
        cdef schema_cpp.FlatArrayMessageReader * flat_reader

        self._object_to_pin = buf

        flat_reader = new schema_cpp.FlatArrayMessageReader(
            schema_cpp.WordArrayPtr(<schema_cpp.word*>ptr, sz//8),
            opts)
        self.thisptr = flat_reader
        self.msg_size = <char *>flat_reader.getEnd() - ptr
        return self

    def __dealloc__(self):
        del self.thisptr


@cython.internal
cdef class _FlatArrayMessageReader(_MessageReader):
    cdef object _object_to_pin
    cdef _BufferView _buffer_view

    def __init__(self, buf, traversal_limit_in_words=None, nesting_limit=None):
        cdef schema_cpp.ReaderOptions opts = make_reader_opts(traversal_limit_in_words, nesting_limit)
        cdef _AlignedBuffer aligned

        sz = len(buf)
        if sz % 8 != 0:
            raise ValueError("input length must be a multiple of eight bytes")

        cdef char * ptr
        if isinstance(buf, bytes):
            ptr = buf
            if (<uintptr_t>ptr) % 8 != 0:
                aligned = _AlignedBuffer(buf)
                ptr = aligned.buf
                self._object_to_pin = aligned
            else:
                self._object_to_pin = buf
            self._buffer_view = None
        elif PyObject_CheckBuffer(buf):
            view = _BufferView(buf)
            ptr = view.buf
            self._object_to_pin = view
            self._buffer_view = view
        else:
            raise TypeError('expected buffer-like object in FlatArrayMessageReader')

        self.thisptr = new schema_cpp.FlatArrayMessageReader(
            schema_cpp.WordArrayPtr(<schema_cpp.word*>ptr, sz//8),
            opts)

    def close(self):
        if self._buffer_view:
            self._buffer_view.close()

    def __dealloc__(self):
        self.close()
        del self.thisptr


_global_schema_parser = None


def load(file_name, display_name=None, imports=[]):
    """Load a Cap'n Proto schema from a file

    You will have to load a schema before you can begin doing anything
    meaningful with this library. Loading a schema is much like loading
    a Python module (and load even returns a `ModuleType`). Once it's been
    loaded, you use it much like any other Module::

        addressbook = capnp.load('addressbook.capnp')
        print addressbook.qux # qux is a top level constant in the addressbook.capnp schema
        # 123
        person = addressbook.Person.new_message()

    :type file_name: str
    :param file_name: A relative or absolute path to a Cap'n Proto schema

    :type display_name: str
    :param display_name: The name internally used by the Cap'n Proto library
        for the loaded schema. By default, it's just os.path.basename(file_name)

    :type imports: list
    :param imports: A list of str directories to add to the import path.

    :rtype: ModuleType
    :return: A module corresponding to the loaded schema. You can access
        parsed schemas and constants with . syntax

    :Raises: :exc:`KjException` if `file_name` doesn't exist

    """
    global _global_schema_parser
    if _global_schema_parser is None:
        _global_schema_parser = SchemaParser()

    return _global_schema_parser.load(file_name, display_name, imports)

def remove_import_hook():
    """Compatibility with cereal: this build never installs an import hook."""
    pass


def _init_capnp_api():
    """ Initialize static function pointers for cdef api functions. """
    init_capnp_api()
