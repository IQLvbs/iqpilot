// Copyright (c) 2013-2014 Sandstorm Development Group, Inc. and contributors
// Licensed under the MIT License:
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in
// all copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
// THE SOFTWARE.

#pragma once

#include "layout.h"

CAPNP_BEGIN_HEADER

namespace capnp {

class StructSchema;
class ListSchema;
struct DynamicStruct;
struct DynamicList;

template <typename T>
class Orphan {
  // Represents an object which is allocated within some message builder but has no pointers
  // pointing at it.  An Orphan can later be "adopted" by some other object as one of that object's
  // fields, without having to copy the orphan.  For a field `foo` of pointer type, the generated
  // code will define builder methods `void adoptFoo(Orphan<T>)` and `Orphan<T> disownFoo()`.
  // Orphans can also be created independently of any parent using an Orphanage.
  //
  // `Orphan<T>` can be moved but not copied, like `Own<T>`, so that it is impossible for one
  // orphan to be adopted multiple times.  If an orphan is destroyed without being adopted, its
  // contents are zero'd out (and possibly reused, if we ever implement the ability to reuse space
  // in a message arena).

public:
  Orphan() = default;
  KJ_DISALLOW_COPY(Orphan);
  Orphan(Orphan&&) = default;
  Orphan& operator=(Orphan&&) = default;
  inline Orphan(_::OrphanBuilder&& builder): builder(kj::mv(builder)) {}

  inline BuilderFor<T> get();
  // Get the underlying builder.  If the orphan is null, this will allocate and return a default
  // object rather than crash.  This is done for security -- otherwise, you might enable a DoS
  // attack any time you disown a field and fail to check if it is null.  In the case of structs,
  // this means that the orphan is no longer null after get() returns.  In the case of lists,
  // no actual object is allocated since a simple empty ListBuilder can be returned.

  inline ReaderFor<T> getReader() const;

  inline bool operator==(decltype(nullptr)) const { return builder == nullptr; }
  inline bool operator!=(decltype(nullptr)) const { return builder != nullptr; }

private:
  _::OrphanBuilder builder;

  template <typename, Kind>
  friend struct _::PointerHelpers;
  template <typename, Kind>
  friend struct List;
  template <typename U>
  friend class Orphan;
  friend class Orphanage;
  friend class MessageBuilder;
};

class Orphanage: private kj::DisallowConstCopy {
  // Use to directly allocate Orphan objects, without having a parent object allocate and then
  // disown the object.

public:
  inline Orphanage(): arena(nullptr) {}

  template <typename BuilderType>
  static Orphanage getForMessageContaining(BuilderType builder);
  // Construct an Orphanage that allocates within the message containing the given Builder.  This
  // allows the constructed Orphans to be adopted by objects within said message.
  //
  // This constructor takes the builder rather than having the builder have a getOrphanage() method
  // because this is an advanced feature and we don't want to pollute the builder APIs with it.
  //
  // Note that if you have a direct pointer to the `MessageBuilder`, you can simply call its
  // `getOrphanage()` method.

  template <typename RootType>
  Orphan<RootType> newOrphan() const;
  // Allocate a new orphaned struct.

  template <typename RootType>
  Orphan<RootType> newOrphan(uint size) const;
  // Allocate a new orphaned list or blob.

  Orphan<DynamicStruct> newOrphan(StructSchema schema) const;
  // Dynamically create an orphan struct with the given schema.  You must
  // #include <capnp/dynamic.h> to use this.

  Orphan<DynamicList> newOrphan(ListSchema schema, uint size) const;
  // Dynamically create an orphan list with the given schema.  You must #include <capnp/dynamic.h>
  // to use this.

  template <typename Reader>
  Orphan<FromReader<Reader>> newOrphanCopy(Reader copyFrom) const;
  // Allocate a new orphaned object (struct, list, or blob) and initialize it as a copy of the
  // given object.

private:
  _::BuilderArena* arena;

  inline explicit Orphanage(_::BuilderArena* arena)
      : arena(arena) {}

  template <typename T, Kind = CAPNP_KIND(T)>
  struct GetInnerBuilder;
  template <typename T, Kind = CAPNP_KIND(T)>
  struct GetInnerReader;
  template <typename T>
  struct NewOrphanListImpl;

  friend class MessageBuilder;
};

// =======================================================================================
// Inline implementation details.

namespace _ {  // private

template <typename T, Kind = CAPNP_KIND(T)>
struct OrphanGetImpl;

template <typename T>
struct OrphanGetImpl<T, Kind::PRIMITIVE> {

};

template <typename T>
struct OrphanGetImpl<T, Kind::STRUCT> {
  static inline typename T::Builder apply(_::OrphanBuilder& builder) {
    return typename T::Builder(builder.asStruct(_::structSize<T>()));
  }
  static inline typename T::Reader applyReader(const _::OrphanBuilder& builder) {
    return typename T::Reader(builder.asStructReader(_::structSize<T>()));
  }

};

template <typename T, Kind k>
struct OrphanGetImpl<List<T, k>, Kind::LIST> {
  static inline typename List<T>::Builder apply(_::OrphanBuilder& builder) {
    return typename List<T>::Builder(builder.asList(_::ElementSizeForType<T>::value));
  }
  static inline typename List<T>::Reader applyReader(const _::OrphanBuilder& builder) {
    return typename List<T>::Reader(builder.asListReader(_::ElementSizeForType<T>::value));
  }

};

template <typename T>
struct OrphanGetImpl<List<T, Kind::STRUCT>, Kind::LIST> {
  static inline typename List<T>::Builder apply(_::OrphanBuilder& builder) {
    return typename List<T>::Builder(builder.asStructList(_::structSize<T>()));
  }
  static inline typename List<T>::Reader applyReader(const _::OrphanBuilder& builder) {
    return typename List<T>::Reader(builder.asListReader(_::ElementSizeForType<T>::value));
  }

};

template <>
struct OrphanGetImpl<Text, Kind::BLOB> {
  static inline Text::Builder apply(_::OrphanBuilder& builder) {
    return Text::Builder(builder.asText());
  }
  static inline Text::Reader applyReader(const _::OrphanBuilder& builder) {
    return Text::Reader(builder.asTextReader());
  }

};

template <>
struct OrphanGetImpl<Data, Kind::BLOB> {
  static inline Data::Builder apply(_::OrphanBuilder& builder) {
    return Data::Builder(builder.asData());
  }
  static inline Data::Reader applyReader(const _::OrphanBuilder& builder) {
    return Data::Reader(builder.asDataReader());
  }

};

}  // namespace _ (private)

template <typename T>
inline BuilderFor<T> Orphan<T>::get() {
  return _::OrphanGetImpl<T>::apply(builder);
}

template <typename T>
inline ReaderFor<T> Orphan<T>::getReader() const {
  return _::OrphanGetImpl<T>::applyReader(builder);
}

template <typename T>
struct Orphanage::GetInnerBuilder<T, Kind::STRUCT> {
  static inline _::StructBuilder apply(typename T::Builder& t) {
    return t._builder;
  }
};

template <typename T>
struct Orphanage::GetInnerBuilder<T, Kind::LIST> {
  static inline _::ListBuilder apply(typename T::Builder& t) {
    return t.builder;
  }
};

template <typename BuilderType>
Orphanage Orphanage::getForMessageContaining(BuilderType builder) {
  auto inner = GetInnerBuilder<FromBuilder<BuilderType>>::apply(builder);
  return Orphanage(inner.getArena());
}

template <typename RootType>
Orphan<RootType> Orphanage::newOrphan() const {
  return Orphan<RootType>(_::OrphanBuilder::initStruct(arena, _::structSize<RootType>()));
}

template <typename T, Kind k>
struct Orphanage::NewOrphanListImpl<List<T, k>> {
  static inline _::OrphanBuilder apply(
      _::BuilderArena* arena, uint size) {
    return _::OrphanBuilder::initList(
        arena, bounded(size) * ELEMENTS, _::ElementSizeForType<T>::value);
  }
};

template <typename T>
struct Orphanage::NewOrphanListImpl<List<T, Kind::STRUCT>> {
  static inline _::OrphanBuilder apply(
      _::BuilderArena* arena, uint size) {
    return _::OrphanBuilder::initStructList(
        arena, bounded(size) * ELEMENTS, _::structSize<T>());
  }
};

template <>
struct Orphanage::NewOrphanListImpl<Text> {
  static inline _::OrphanBuilder apply(
      _::BuilderArena* arena, uint size) {
    return _::OrphanBuilder::initText(arena, bounded(size) * BYTES);
  }
};

template <>
struct Orphanage::NewOrphanListImpl<Data> {
  static inline _::OrphanBuilder apply(
      _::BuilderArena* arena, uint size) {
    return _::OrphanBuilder::initData(arena, bounded(size) * BYTES);
  }
};

template <typename RootType>
Orphan<RootType> Orphanage::newOrphan(uint size) const {
  return Orphan<RootType>(NewOrphanListImpl<RootType>::apply(arena, size));
}

template <typename T>
struct Orphanage::GetInnerReader<T, Kind::STRUCT> {
  static inline _::StructReader apply(const typename T::Reader& t) {
    return t._reader;
  }
};

template <typename T>
struct Orphanage::GetInnerReader<T, Kind::LIST> {
  static inline _::ListReader apply(const typename T::Reader& t) {
    return t.reader;
  }
};

template <typename T>
struct Orphanage::GetInnerReader<T, Kind::BLOB> {
  static inline const typename T::Reader& apply(const typename T::Reader& t) {
    return t;
  }
};

template <typename Reader>
inline Orphan<FromReader<Reader>> Orphanage::newOrphanCopy(Reader copyFrom) const {
  return Orphan<FromReader<Reader>>(_::OrphanBuilder::copy(
      arena, GetInnerReader<FromReader<Reader>>::apply(copyFrom)));
}

}  // namespace capnp

CAPNP_END_HEADER
