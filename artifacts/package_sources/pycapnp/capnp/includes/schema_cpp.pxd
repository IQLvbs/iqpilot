# distutils: language = c++

from capnp.helpers.non_circular cimport c_reraise_kj_exception as reraise_kj_exception
from capnp.includes.types cimport *

cdef extern from "capnp/dynamic.h" namespace " ::capnp":
    cdef cppclass DynamicStruct nogil:
        cppclass Reader nogil:
            pass
    cdef cppclass DynamicStruct_Builder " ::capnp::DynamicStruct::Builder" nogil:
        pass

cdef extern from "capnp/schema.h" namespace " ::capnp":
    cdef cppclass StructSchema nogil:
        pass

cdef extern from "capnp/blob.h" namespace " ::capnp":
    cdef cppclass Data nogil:
        cppclass Reader nogil:
            char* begin()
            size_t size()
        cppclass Builder nogil:
            char* begin()
            size_t size()
    cdef cppclass Text nogil:
        cppclass Reader nogil:
            char* cStr()

cdef extern from "capnp/schema.capnp.h" namespace " ::capnp::schema":
    cdef cppclass Node nogil:
        cppclass NestedNode nogil:
            cppclass Reader nogil:
                Text.Reader getName()
        cppclass Reader nogil:
            uint64_t getId()
            ListNestedNodeReader getNestedNodes()
            bint isStruct()
            bint isEnum()
            bint isInterface()
            bint isConst()

    cdef cppclass Field nogil:
        cppclass Reader nogil:
            Text.Reader getName()

    cdef cppclass Enumerant nogil:
        cppclass Reader nogil:
            Text.Reader getName()

    cdef cppclass ListNestedNodeReader "capnp::List<capnp::schema::Node::NestedNode>::Reader" nogil:
        uint size()
        Node.NestedNode.Reader operator[](uint)

cdef extern from "capnp/common.h" namespace " ::capnp":
    cdef cppclass word nogil:
        pass

cdef extern from "kj/common.h" namespace " ::kj":
    cdef cppclass WordArrayPtr " ::kj::ArrayPtr< ::capnp::word>" nogil:
        WordArrayPtr(word*, size_t)

cdef extern from "kj/array.h" namespace " ::kj":
    cdef cppclass WordArray " ::kj::Array< ::capnp::word>" nogil:
        word* begin()
        size_t size()

cdef extern from "capnp/message.h" namespace " ::capnp":
    cdef cppclass ReaderOptions nogil:
        uint64_t traversalLimitInWords
        uint nestingLimit

    cdef cppclass MessageBuilder nogil:
        DynamicStruct_Builder getRootDynamicStruct 'getRoot< ::capnp::DynamicStruct>'(StructSchema) except +reraise_kj_exception
        DynamicStruct_Builder initRootDynamicStruct 'initRoot< ::capnp::DynamicStruct>'(StructSchema)
        void setRootDynamicStruct 'setRoot< ::capnp::DynamicStruct::Reader>'(DynamicStruct.Reader) except +reraise_kj_exception

    cdef cppclass MessageReader nogil:
        DynamicStruct.Reader getRootDynamicStruct 'getRoot< ::capnp::DynamicStruct>'(StructSchema) except +reraise_kj_exception

    cdef cppclass MallocMessageBuilder(MessageBuilder) nogil:
        MallocMessageBuilder()

cdef extern from "capnp/serialize.h" namespace " ::capnp":
    cdef cppclass FlatArrayMessageReader(MessageReader) nogil:
        FlatArrayMessageReader(WordArrayPtr, ReaderOptions) except +reraise_kj_exception
        const word* getEnd() const

    WordArray messageToFlatArray(MessageBuilder&) nogil
