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

// This file defines classes that can be used to manipulate messages based on schemas that are not
// known until runtime.  This is also useful for writing generic code that uses schemas to handle
// arbitrary types in a generic way.
//
// Each of the classes defined here has a to() template method which converts an instance back to a
// native type.  This method will throw an exception if the requested type does not match the
// schema.  To convert native types to dynamic, use DynamicFactory.
//
// As always, underlying data is validated lazily, so you have to actually traverse the whole
// message if you want to validate all content.

#pragma once

#include "schema.h"
#include "layout.h"
#include "message.h"
#include "any.h"

CAPNP_BEGIN_HEADER

namespace capnp {

class MessageReader;
class MessageBuilder;

struct DynamicValue {
  DynamicValue() = delete;

  enum Type {
    UNKNOWN,
    // Means that the value has unknown type and content because it comes from a newer version of
    // the schema, or from a newer version of Cap'n Proto that has new features that this version
    // doesn't understand.

    VOID,
    BOOL,
    INT,
    UINT,
    FLOAT,
    TEXT,
    DATA,
    LIST,
    ENUM,
    STRUCT,
    ANY_POINTER
  };

  class Reader;
  class Builder;
};
class DynamicEnum;
struct DynamicStruct {
  DynamicStruct() = delete;
  class Reader;
  class Builder;
};
struct DynamicList {
  DynamicList() = delete;
  class Reader;
  class Builder;
};
template <> class Orphan<DynamicValue>;

template <Kind k> struct DynamicTypeFor_;
template <> struct DynamicTypeFor_<Kind::ENUM> { typedef DynamicEnum Type; };
template <> struct DynamicTypeFor_<Kind::STRUCT> { typedef DynamicStruct Type; };
template <> struct DynamicTypeFor_<Kind::LIST> { typedef DynamicList Type; };

template <typename T>
using DynamicTypeFor = typename DynamicTypeFor_<kind<T>()>::Type;

template <typename T>
ReaderFor<DynamicTypeFor<FromReader<T>>> toDynamic(T&& value);
template <typename T>
BuilderFor<DynamicTypeFor<FromBuilder<T>>> toDynamic(T&& value);
template <typename T>
DynamicTypeFor<TypeIfEnum<T>> toDynamic(T&& value);

namespace _ {  // private

template <> struct Kind_<DynamicValue     > { static constexpr Kind kind = Kind::OTHER; };
template <> struct Kind_<DynamicEnum      > { static constexpr Kind kind = Kind::OTHER; };
template <> struct Kind_<DynamicStruct    > { static constexpr Kind kind = Kind::OTHER; };
template <> struct Kind_<DynamicList      > { static constexpr Kind kind = Kind::OTHER; };

}  // namespace _ (private)

template <> inline constexpr Style style<DynamicValue     >() { return Style::POINTER;    }
template <> inline constexpr Style style<DynamicEnum      >() { return Style::PRIMITIVE;  }
template <> inline constexpr Style style<DynamicStruct    >() { return Style::STRUCT;     }
template <> inline constexpr Style style<DynamicList      >() { return Style::POINTER;    }

// -------------------------------------------------------------------

class DynamicEnum {
public:
  DynamicEnum() = default;
  inline DynamicEnum(EnumSchema::Enumerant enumerant)
      : schema(enumerant.getContainingEnum()), value(enumerant.getOrdinal()) {}
  inline DynamicEnum(EnumSchema schema, uint16_t value)
      : schema(schema), value(value) {}

  template <typename T, typename = kj::EnableIf<kind<T>() == Kind::ENUM>>
  inline DynamicEnum(T&& value): DynamicEnum(toDynamic(value)) {}

  template <typename T>
  inline T as() const { return static_cast<T>(asImpl(typeId<T>())); }
  // Cast to a native enum type.

  inline EnumSchema getSchema() const { return schema; }

  kj::Maybe<EnumSchema::Enumerant> getEnumerant() const;
  // Get which enumerant this enum value represents.  Returns nullptr if the numeric value does not
  // correspond to any enumerant in the schema -- this can happen if the data was built using a
  // newer schema that has more values defined.

  inline uint16_t getRaw() const { return value; }
  // Returns the raw underlying enum value.

private:
  EnumSchema schema;
  uint16_t value;

  uint16_t asImpl(uint64_t requestedTypeId) const;

  friend struct DynamicStruct;
  friend struct DynamicList;
  friend struct DynamicValue;
  template <typename T>
  friend DynamicTypeFor<TypeIfEnum<T>> toDynamic(T&& value);
};

// -------------------------------------------------------------------

enum class HasMode: uint8_t {
  // Specifies the meaning of "has(field)".

  NON_NULL,
  // "has(field)" only returns false if the field is a pointer and the pointer is null. This is the
  // default behavior.

  NON_DEFAULT
  // "has(field)" returns false if the field is set to its default value. This differs from
  // NON_NULL only in the handling of primitive values.
  //
  // "Equal to default value" is technically defined as the field value being encoded as all-zero
  // on the wire (since primitive values are XORed by their defined default value when encoded).
};

class DynamicStruct::Reader {
public:
  typedef DynamicStruct Reads;

  Reader() = default;

  template <typename T, typename = kj::EnableIf<kind<FromReader<T>>() == Kind::STRUCT>>
  inline Reader(T&& value): Reader(toDynamic(value)) {}

  inline operator AnyStruct::Reader() const { return AnyStruct::Reader(reader); }

  inline MessageSize totalSize() const { return reader.totalSize().asPublic(); }

  template <typename T>
  typename T::Reader as() const;
  // Convert the dynamic struct to its compiled-in type.

  inline StructSchema getSchema() const { return schema; }

  DynamicValue::Reader get(StructSchema::Field field) const;
  // Read the given field value.

  bool has(StructSchema::Field field, HasMode mode = HasMode::NON_NULL) const;
  // Tests whether the given field is "present". If the field is a union member and is not the
  // active member, this always returns false. Otherwise, the field's value is interpreted
  // according to `mode`.

  kj::Maybe<StructSchema::Field> which() const;
  // If the struct contains an (unnamed) union, and the currently-active field within that union
  // is known, this returns that field.  Otherwise, it returns null.  In other words, this returns
  // null if there is no union present _or_ if the union's discriminant is set to an unrecognized
  // value.  This could happen in particular when receiving a message from a sender who has a
  // newer version of the protocol and is using a field of the union that you don't know about yet.

  DynamicValue::Reader get(kj::StringPtr name) const;
  bool has(kj::StringPtr name, HasMode mode = HasMode::NON_NULL) const;
  // Shortcuts to access fields by name.  These throw exceptions if no such field exists.

private:
  StructSchema schema;
  _::StructReader reader;

  inline Reader(StructSchema schema, _::StructReader reader)
      : schema(schema), reader(reader) {}
  Reader(StructSchema schema, const _::OrphanBuilder& orphan);

  bool isSetInUnion(StructSchema::Field field) const;
  void verifySetInUnion(StructSchema::Field field) const;
  static DynamicValue::Reader getImpl(_::StructReader reader, StructSchema::Field field);

  template <typename T, Kind K>
  friend struct _::PointerHelpers;
  friend class DynamicStruct::Builder;
  friend struct DynamicList;
  friend class MessageReader;
  friend class MessageBuilder;
  template <typename T, ::capnp::Kind k>
  friend struct ::capnp::ToDynamic_;
  friend kj::StringTree _::structString(
      _::StructReader reader, const _::RawBrandedSchema& schema);
  friend class Orphanage;
  friend class Orphan<DynamicStruct>;
  friend class Orphan<DynamicValue>;
  friend class Orphan<AnyPointer>;
  friend class AnyStruct::Reader;
};

class DynamicStruct::Builder {
public:
  typedef DynamicStruct Builds;

  Builder() = default;
  inline Builder(decltype(nullptr)) {}

  template <typename T, typename = kj::EnableIf<kind<FromBuilder<T>>() == Kind::STRUCT>>
  inline Builder(T&& value): Builder(toDynamic(value)) {}

  inline operator AnyStruct::Builder() { return AnyStruct::Builder(builder); }

  inline MessageSize totalSize() const { return asReader().totalSize(); }

  template <typename T>
  typename T::Builder as();
  // Cast to a particular struct type.

  inline StructSchema getSchema() const { return schema; }

  DynamicValue::Builder get(StructSchema::Field field);
  // Read the given field value.

  inline bool has(StructSchema::Field field, HasMode mode = HasMode::NON_NULL)
      { return asReader().has(field, mode); }
  // Tests whether the given field is "present". If the field is a union member and is not the
  // active member, this always returns false. Otherwise, the field's value is interpreted
  // according to `mode`.

  kj::Maybe<StructSchema::Field> which();
  // If the struct contains an (unnamed) union, and the currently-active field within that union
  // is known, this returns that field.  Otherwise, it returns null.  In other words, this returns
  // null if there is no union present _or_ if the union's discriminant is set to an unrecognized
  // value.  This could happen in particular when receiving a message from a sender who has a
  // newer version of the protocol and is using a field of the union that you don't know about yet.

  void set(StructSchema::Field field, const DynamicValue::Reader& value);
  // Set the given field value.

  DynamicValue::Builder init(StructSchema::Field field);
  DynamicValue::Builder init(StructSchema::Field field, uint size);
  // Init a struct, list, or blob field.

  void adopt(StructSchema::Field field, Orphan<DynamicValue>&& orphan);
  Orphan<DynamicValue> disown(StructSchema::Field field);
  // Adopt/disown.  This works even for non-pointer fields: adopt() becomes equivalent to set()
  // and disown() becomes like get() followed by clear().

  void clear(StructSchema::Field field);
  // Clear a field, setting it to its default value.  For pointer fields, this actually makes the
  // field null.

  DynamicValue::Builder get(kj::StringPtr name);
  bool has(kj::StringPtr name, HasMode mode = HasMode::NON_NULL);
  void set(kj::StringPtr name, const DynamicValue::Reader& value);
  void set(kj::StringPtr name, std::initializer_list<DynamicValue::Reader> value);
  DynamicValue::Builder init(kj::StringPtr name);
  DynamicValue::Builder init(kj::StringPtr name, uint size);
  void adopt(kj::StringPtr name, Orphan<DynamicValue>&& orphan);
  Orphan<DynamicValue> disown(kj::StringPtr name);
  void clear(kj::StringPtr name);
  // Shortcuts to access fields by name.  These throw exceptions if no such field exists.

  Reader asReader() const;

private:
  StructSchema schema;
  _::StructBuilder builder;

  inline Builder(StructSchema schema, _::StructBuilder builder)
      : schema(schema), builder(builder) {}
  Builder(StructSchema schema, _::OrphanBuilder& orphan);

  bool isSetInUnion(StructSchema::Field field);
  void verifySetInUnion(StructSchema::Field field);
  void setInUnion(StructSchema::Field field);

  template <typename T, Kind k>
  friend struct _::PointerHelpers;
  friend struct DynamicList;
  friend class MessageReader;
  friend class MessageBuilder;
  template <typename T, ::capnp::Kind k>
  friend struct ::capnp::ToDynamic_;
  friend class Orphanage;
  friend class Orphan<DynamicStruct>;
  friend class Orphan<DynamicValue>;
  friend class Orphan<AnyPointer>;
  friend class AnyStruct::Builder;
};

// -------------------------------------------------------------------

class DynamicList::Reader {
public:
  typedef DynamicList Reads;

  inline Reader(): reader(ElementSize::VOID) {}

  template <typename T, typename = kj::EnableIf<kind<FromReader<T>>() == Kind::LIST>>
  inline Reader(T&& value): Reader(toDynamic(value)) {}

  inline operator AnyList::Reader() const { return AnyList::Reader(reader); }

  template <typename T>
  typename T::Reader as() const;
  // Try to convert to any List<T>, Data, or Text.  Throws an exception if the underlying data
  // can't possibly represent the requested type.

  inline ListSchema getSchema() const { return schema; }

  inline uint size() const { return unbound(reader.size() / ELEMENTS); }
  DynamicValue::Reader operator[](uint index) const;

  typedef _::IndexingIterator<const Reader, DynamicValue::Reader> Iterator;
  inline Iterator begin() const { return Iterator(this, 0); }
  inline Iterator end() const { return Iterator(this, size()); }

private:
  ListSchema schema;
  _::ListReader reader;

  Reader(ListSchema schema, _::ListReader reader): schema(schema), reader(reader) {}
  Reader(ListSchema schema, const _::OrphanBuilder& orphan);

  template <typename T, Kind k>
  friend struct _::PointerHelpers;
  friend struct DynamicStruct;
  friend class DynamicList::Builder;
  template <typename T, ::capnp::Kind k>
  friend struct ::capnp::ToDynamic_;
  friend class Orphanage;
  friend class Orphan<DynamicList>;
  friend class Orphan<DynamicValue>;
  friend class Orphan<AnyPointer>;
};

class DynamicList::Builder {
public:
  typedef DynamicList Builds;

  inline Builder(): builder(ElementSize::VOID) {}
  inline Builder(decltype(nullptr)): builder(ElementSize::VOID) {}

  template <typename T, typename = kj::EnableIf<kind<FromBuilder<T>>() == Kind::LIST>>
  inline Builder(T&& value): Builder(toDynamic(value)) {}

  inline operator AnyList::Builder() { return AnyList::Builder(builder); }

  template <typename T>
  typename T::Builder as();
  // Try to convert to any List<T>, Data, or Text.  Throws an exception if the underlying data
  // can't possibly represent the requested type.

  inline ListSchema getSchema() const { return schema; }

  inline uint size() const { return unbound(builder.size() / ELEMENTS); }
  DynamicValue::Builder operator[](uint index);
  void set(uint index, const DynamicValue::Reader& value);
  DynamicValue::Builder init(uint index, uint size);
  void adopt(uint index, Orphan<DynamicValue>&& orphan);
  Orphan<DynamicValue> disown(uint index);

  typedef _::IndexingIterator<Builder, DynamicStruct::Builder> Iterator;
  inline Iterator begin() { return Iterator(this, 0); }
  inline Iterator end() { return Iterator(this, size()); }

  void copyFrom(std::initializer_list<DynamicValue::Reader> value);

  Reader asReader() const;

private:
  ListSchema schema;
  _::ListBuilder builder;

  Builder(ListSchema schema, _::ListBuilder builder): schema(schema), builder(builder) {}
  Builder(ListSchema schema, _::OrphanBuilder& orphan);

  template <typename T, Kind k>
  friend struct _::PointerHelpers;
  friend struct DynamicStruct;
  template <typename T, ::capnp::Kind k>
  friend struct ::capnp::ToDynamic_;
  friend class Orphanage;
  template <typename T, Kind k>
  friend struct _::OrphanGetImpl;
  friend class Orphan<DynamicList>;
  friend class Orphan<DynamicValue>;
  friend class Orphan<AnyPointer>;
};

// -------------------------------------------------------------------

// Make sure ReaderFor<T> and BuilderFor<T> work for DynamicEnum, DynamicStruct, and
// DynamicList, so that we can define DynamicValue::as().

template <> struct ReaderFor_ <DynamicEnum, Kind::OTHER> { typedef DynamicEnum Type; };
template <> struct BuilderFor_<DynamicEnum, Kind::OTHER> { typedef DynamicEnum Type; };
template <> struct ReaderFor_ <DynamicStruct, Kind::OTHER> { typedef DynamicStruct::Reader Type; };
template <> struct BuilderFor_<DynamicStruct, Kind::OTHER> { typedef DynamicStruct::Builder Type; };
template <> struct ReaderFor_ <DynamicList, Kind::OTHER> { typedef DynamicList::Reader Type; };
template <> struct BuilderFor_<DynamicList, Kind::OTHER> { typedef DynamicList::Builder Type; };

class DynamicValue::Reader {
public:
  typedef DynamicValue Reads;

  inline Reader(decltype(nullptr) n = nullptr);  // UNKNOWN
  inline Reader(Void value);
  inline Reader(bool value);
  inline Reader(char value);
  inline Reader(signed char value);
  inline Reader(short value);
  inline Reader(int value);
  inline Reader(long value);
  inline Reader(long long value);
  inline Reader(unsigned char value);
  inline Reader(unsigned short value);
  inline Reader(unsigned int value);
  inline Reader(unsigned long value);
  inline Reader(unsigned long long value);
  inline Reader(float value);
  inline Reader(double value);
  inline Reader(const char* value);  // Text
  inline Reader(const Text::Reader& value);
  inline Reader(const Data::Reader& value);
  inline Reader(const DynamicList::Reader& value);
  inline Reader(DynamicEnum value);
  inline Reader(const DynamicStruct::Reader& value);
  inline Reader(const AnyPointer::Reader& value);
  Reader(ConstSchema constant);

  template <typename T, typename = decltype(toDynamic(kj::instance<T>()))>
  inline Reader(T&& value): Reader(toDynamic(kj::mv(value))) {}

  Reader(const Reader& other) = default;
  Reader(Reader&& other) noexcept = default;
  ~Reader() noexcept(false) = default;
  Reader& operator=(const Reader& other) = default;
  Reader& operator=(Reader&& other) = default;

  template <typename T>
  inline ReaderFor<T> as() const { return AsImpl<T>::apply(*this); }
  // Use to interpret the value as some Cap'n Proto type.  Allowed types are:
  // - Void, bool, [u]int{8,16,32,64}_t, float, double, any enum:  Returns the raw value.
  // - Text, Data, AnyPointer, any struct type:  Returns the corresponding Reader.
  // - List<T> for any T listed above:  Returns List<T>::Reader.
  // - DynamicEnum:  Returns the corresponding type.
  // - DynamicStruct, DynamicList:  Returns the corresponding Reader.
  // - DynamicValue:  Returns an identical Reader. Useful to avoid special-casing in generic code.
  //
  // DynamicValue allows various implicit conversions, mostly just to make the interface friendlier.
  // - Any integer can be converted to any other integer type so long as the actual value is within
  //   the new type's range.
  // - Floating-point types can be converted to integers as long as no information would be lost
  //   in the conversion.
  // - Integers can be converted to floating points.  This may lose information, but won't throw.
  // - Float32/Float64 can be converted between each other.  Converting Float64 -> Float32 may lose
  //   information, but won't throw.
  // - Text can be converted to an enum, if the Text matches one of the enumerant names (but not
  //   vice-versa).
  //
  // Any other conversion attempt will throw an exception.

  inline Type getType() const { return type; }
  // Get the type of this value.

private:
  Type type;

  union {
    Void voidValue;
    bool boolValue;
    int64_t intValue;
    uint64_t uintValue;
    double floatValue;
    Text::Reader textValue;
    Data::Reader dataValue;
    DynamicList::Reader listValue;
    DynamicEnum enumValue;
    DynamicStruct::Reader structValue;
    AnyPointer::Reader anyPointerValue;
  };

  template <typename T, Kind kind = kind<T>()> struct AsImpl;
  // Implementation backing the as() method.  Needs to be a struct to allow partial
  // specialization.  Has a method apply() which does the work.

  friend class Orphanage;  // to speed up newOrphanCopy(DynamicValue::Reader)
};

class DynamicValue::Builder {
public:
  typedef DynamicValue Builds;

  inline Builder(decltype(nullptr) n = nullptr);  // UNKNOWN
  inline Builder(Void value);
  inline Builder(bool value);
  inline Builder(char value);
  inline Builder(signed char value);
  inline Builder(short value);
  inline Builder(int value);
  inline Builder(long value);
  inline Builder(long long value);
  inline Builder(unsigned char value);
  inline Builder(unsigned short value);
  inline Builder(unsigned int value);
  inline Builder(unsigned long value);
  inline Builder(unsigned long long value);
  inline Builder(float value);
  inline Builder(double value);
  inline Builder(Text::Builder value);
  inline Builder(Data::Builder value);
  inline Builder(DynamicList::Builder value);
  inline Builder(DynamicEnum value);
  inline Builder(DynamicStruct::Builder value);
  inline Builder(AnyPointer::Builder value);

  template <typename T, typename = decltype(toDynamic(kj::instance<T>()))>
  inline Builder(T value): Builder(toDynamic(value)) {}

  Builder(Builder& other) = default;
  Builder(Builder&& other) noexcept = default;
  ~Builder() noexcept(false) = default;
  Builder& operator=(Builder& other) = default;
  Builder& operator=(Builder&& other) = default;

  template <typename T>
  inline BuilderFor<T> as() { return AsImpl<T>::apply(*this); }
  // See DynamicValue::Reader::as().

  inline Type getType() { return type; }
  // Get the type of this value.

  Reader asReader() const;

private:
  Type type;

  union {
    Void voidValue;
    bool boolValue;
    int64_t intValue;
    uint64_t uintValue;
    double floatValue;
    Text::Builder textValue;
    Data::Builder dataValue;
    DynamicList::Builder listValue;
    DynamicEnum enumValue;
    DynamicStruct::Builder structValue;
    AnyPointer::Builder anyPointerValue;
  };

  template <typename T, Kind kind = kind<T>()> struct AsImpl;
  // Implementation backing the as() method.  Needs to be a struct to allow partial
  // specialization.  Has a method apply() which does the work.

  friend class Orphan<DynamicValue>;
};

kj::StringTree KJ_STRINGIFY(const DynamicValue::Reader& value);
kj::StringTree KJ_STRINGIFY(const DynamicValue::Builder& value);
kj::StringTree KJ_STRINGIFY(DynamicEnum value);
kj::StringTree KJ_STRINGIFY(const DynamicStruct::Reader& value);
kj::StringTree KJ_STRINGIFY(const DynamicStruct::Builder& value);
kj::StringTree KJ_STRINGIFY(const DynamicList::Reader& value);
kj::StringTree KJ_STRINGIFY(const DynamicList::Builder& value);

// -------------------------------------------------------------------
// Orphan <-> Dynamic glue

template <>
class Orphan<DynamicStruct> {
public:
  Orphan() = default;
  KJ_DISALLOW_COPY(Orphan);
  Orphan(Orphan&&) = default;
  Orphan& operator=(Orphan&&) = default;

  template <typename T, typename = kj::EnableIf<kind<T>() == Kind::STRUCT>>
  inline Orphan(Orphan<T>&& other): schema(Schema::from<T>()), builder(kj::mv(other.builder)) {}

  DynamicStruct::Builder get();
  DynamicStruct::Reader getReader() const;

  template <typename T>
  Orphan<T> releaseAs();
  // Like DynamicStruct::Builder::as(), but coerces the Orphan type.  Since Orphans are move-only,
  // the original Orphan<DynamicStruct> is no longer valid after this call; ownership is
  // transferred to the returned Orphan<T>.

  inline bool operator==(decltype(nullptr)) const { return builder == nullptr; }
  inline bool operator!=(decltype(nullptr)) const { return builder != nullptr; }

private:
  StructSchema schema;
  _::OrphanBuilder builder;

  inline Orphan(StructSchema schema, _::OrphanBuilder&& builder)
      : schema(schema), builder(kj::mv(builder)) {}

  template <typename, Kind>
  friend struct _::PointerHelpers;
  friend struct DynamicList;
  friend class Orphanage;
  friend class Orphan<DynamicValue>;
  friend class Orphan<AnyPointer>;
  friend class MessageBuilder;
};

template <>
class Orphan<DynamicList> {
public:
  Orphan() = default;
  KJ_DISALLOW_COPY(Orphan);
  Orphan(Orphan&&) = default;
  Orphan& operator=(Orphan&&) = default;

  template <typename T, typename = kj::EnableIf<kind<T>() == Kind::LIST>>
  inline Orphan(Orphan<T>&& other): schema(Schema::from<T>()), builder(kj::mv(other.builder)) {}

  DynamicList::Builder get();
  DynamicList::Reader getReader() const;

  template <typename T>
  Orphan<T> releaseAs();
  // Like DynamicList::Builder::as(), but coerces the Orphan type.  Since Orphans are move-only,
  // the original Orphan<DynamicStruct> is no longer valid after this call; ownership is
  // transferred to the returned Orphan<T>.

  // TODO(someday): Support truncate().

  inline bool operator==(decltype(nullptr)) const { return builder == nullptr; }
  inline bool operator!=(decltype(nullptr)) const { return builder != nullptr; }

private:
  ListSchema schema;
  _::OrphanBuilder builder;

  inline Orphan(ListSchema schema, _::OrphanBuilder&& builder)
      : schema(schema), builder(kj::mv(builder)) {}

  template <typename, Kind>
  friend struct _::PointerHelpers;
  friend struct DynamicList;
  friend class Orphanage;
  friend class Orphan<DynamicValue>;
  friend class Orphan<AnyPointer>;
};

template <>
class Orphan<DynamicValue> {
public:
  inline Orphan(decltype(nullptr) n = nullptr): type(DynamicValue::UNKNOWN) {}
  inline Orphan(Void value);
  inline Orphan(bool value);
  inline Orphan(char value);
  inline Orphan(signed char value);
  inline Orphan(short value);
  inline Orphan(int value);
  inline Orphan(long value);
  inline Orphan(long long value);
  inline Orphan(unsigned char value);
  inline Orphan(unsigned short value);
  inline Orphan(unsigned int value);
  inline Orphan(unsigned long value);
  inline Orphan(unsigned long long value);
  inline Orphan(float value);
  inline Orphan(double value);
  inline Orphan(DynamicEnum value);
  Orphan(Orphan&&) = default;
  template <typename T>
  Orphan(Orphan<T>&&);
  Orphan(Orphan<AnyPointer>&&);
  Orphan(void*) = delete;  // So Orphan(bool) doesn't accept pointers.
  KJ_DISALLOW_COPY(Orphan);

  Orphan& operator=(Orphan&&) = default;

  inline DynamicValue::Type getType() { return type; }

  DynamicValue::Builder get();
  DynamicValue::Reader getReader() const;

  template <typename T>
  Orphan<T> releaseAs();
  // Like DynamicValue::Builder::as(), but coerces the Orphan type.  Since Orphans are move-only,
  // the original Orphan<DynamicStruct> is no longer valid after this call; ownership is
  // transferred to the returned Orphan<T>.

private:
  DynamicValue::Type type;
  union {
    Void voidValue;
    bool boolValue;
    int64_t intValue;
    uint64_t uintValue;
    double floatValue;
    DynamicEnum enumValue;
    StructSchema structSchema;
    ListSchema listSchema;
  };

  _::OrphanBuilder builder;
  // Only used if `type` is a pointer type.

  Orphan(DynamicValue::Builder value, _::OrphanBuilder&& builder);
  Orphan(DynamicValue::Type type, _::OrphanBuilder&& builder)
      : type(type), builder(kj::mv(builder)) {}
  Orphan(StructSchema structSchema, _::OrphanBuilder&& builder)
      : type(DynamicValue::STRUCT), structSchema(structSchema), builder(kj::mv(builder)) {}
  Orphan(ListSchema listSchema, _::OrphanBuilder&& builder)
      : type(DynamicValue::LIST), listSchema(listSchema), builder(kj::mv(builder)) {}

  template <typename, Kind>
  friend struct _::PointerHelpers;
  friend struct DynamicStruct;
  friend struct DynamicList;
  friend struct AnyPointer;
  friend class Orphanage;
};

template <typename T>
inline Orphan<DynamicValue>::Orphan(Orphan<T>&& other)
    : Orphan(other.get(), kj::mv(other.builder)) {}

inline Orphan<DynamicValue>::Orphan(Orphan<AnyPointer>&& other)
    : type(DynamicValue::ANY_POINTER), builder(kj::mv(other.builder)) {}

template <typename T>
Orphan<T> Orphan<DynamicStruct>::releaseAs() {
  get().as<T>();  // type check
  return Orphan<T>(kj::mv(builder));
}

template <typename T>
Orphan<T> Orphan<DynamicList>::releaseAs() {
  get().as<T>();  // type check
  return Orphan<T>(kj::mv(builder));
}

template <typename T>
Orphan<T> Orphan<DynamicValue>::releaseAs() {
  get().as<T>();  // type check
  type = DynamicValue::UNKNOWN;
  return Orphan<T>(kj::mv(builder));
}

template <>
Orphan<AnyPointer> Orphan<DynamicValue>::releaseAs<AnyPointer>();
template <>
Orphan<DynamicStruct> Orphan<DynamicValue>::releaseAs<DynamicStruct>();
template <>
Orphan<DynamicList> Orphan<DynamicValue>::releaseAs<DynamicList>();

template <>
struct Orphanage::GetInnerBuilder<DynamicStruct, Kind::OTHER> {
  static inline _::StructBuilder apply(DynamicStruct::Builder& t) {
    return t.builder;
  }
};

template <>
struct Orphanage::GetInnerBuilder<DynamicList, Kind::OTHER> {
  static inline _::ListBuilder apply(DynamicList::Builder& t) {
    return t.builder;
  }
};

template <>
inline Orphan<DynamicStruct> Orphanage::newOrphanCopy<DynamicStruct::Reader>(
    DynamicStruct::Reader copyFrom) const {
  return Orphan<DynamicStruct>(
      copyFrom.getSchema(), _::OrphanBuilder::copy(arena, copyFrom.reader));
}

template <>
inline Orphan<DynamicList> Orphanage::newOrphanCopy<DynamicList::Reader>(
    DynamicList::Reader copyFrom) const {
  return Orphan<DynamicList>(copyFrom.getSchema(),
      _::OrphanBuilder::copy(arena, copyFrom.reader));
}

template <>
Orphan<DynamicValue> Orphanage::newOrphanCopy<DynamicValue::Reader>(
    DynamicValue::Reader copyFrom) const;

namespace _ {  // private

template <>
struct PointerHelpers<DynamicStruct, Kind::OTHER> {
  // getDynamic() is used when an AnyPointer's get() accessor is passed arguments, because for
  // non-dynamic types PointerHelpers::get() takes a default value as the third argument, and we
  // don't want people to accidentally be able to provide their own default value.
  static DynamicStruct::Reader getDynamic(PointerReader reader, StructSchema schema);
  static DynamicStruct::Builder getDynamic(PointerBuilder builder, StructSchema schema);
  static void set(PointerBuilder builder, const DynamicStruct::Reader& value);
  static DynamicStruct::Builder init(PointerBuilder builder, StructSchema schema);
  static inline void adopt(PointerBuilder builder, Orphan<DynamicStruct>&& value) {
    builder.adopt(kj::mv(value.builder));
  }
  static inline Orphan<DynamicStruct> disown(PointerBuilder builder, StructSchema schema) {
    return Orphan<DynamicStruct>(schema, builder.disown());
  }
};

template <>
struct PointerHelpers<DynamicList, Kind::OTHER> {
  // getDynamic() is used when an AnyPointer's get() accessor is passed arguments, because for
  // non-dynamic types PointerHelpers::get() takes a default value as the third argument, and we
  // don't want people to accidentally be able to provide their own default value.
  static DynamicList::Reader getDynamic(PointerReader reader, ListSchema schema);
  static DynamicList::Builder getDynamic(PointerBuilder builder, ListSchema schema);
  static void set(PointerBuilder builder, const DynamicList::Reader& value);
  static DynamicList::Builder init(PointerBuilder builder, ListSchema schema, uint size);
  static inline void adopt(PointerBuilder builder, Orphan<DynamicList>&& value) {
    builder.adopt(kj::mv(value.builder));
  }
  static inline Orphan<DynamicList> disown(PointerBuilder builder, ListSchema schema) {
    return Orphan<DynamicList>(schema, builder.disown());
  }
};

}  // namespace _ (private)

template <typename T>
inline ReaderFor<T> AnyPointer::Reader::getAs(StructSchema schema) const {
  return _::PointerHelpers<T>::getDynamic(reader, schema);
}
template <typename T>
inline ReaderFor<T> AnyPointer::Reader::getAs(ListSchema schema) const {
  return _::PointerHelpers<T>::getDynamic(reader, schema);
}
template <typename T>
inline BuilderFor<T> AnyPointer::Builder::getAs(StructSchema schema) {
  return _::PointerHelpers<T>::getDynamic(builder, schema);
}
template <typename T>
inline BuilderFor<T> AnyPointer::Builder::getAs(ListSchema schema) {
  return _::PointerHelpers<T>::getDynamic(builder, schema);
}
template <typename T>
inline BuilderFor<T> AnyPointer::Builder::initAs(StructSchema schema) {
  return _::PointerHelpers<T>::init(builder, schema);
}
template <typename T>
inline BuilderFor<T> AnyPointer::Builder::initAs(ListSchema schema, uint elementCount) {
  return _::PointerHelpers<T>::init(builder, schema, elementCount);
}
template <>
inline void AnyPointer::Builder::setAs<DynamicStruct>(DynamicStruct::Reader value) {
  return _::PointerHelpers<DynamicStruct>::set(builder, value);
}
template <>
inline void AnyPointer::Builder::setAs<DynamicList>(DynamicList::Reader value) {
  return _::PointerHelpers<DynamicList>::set(builder, value);
}
template <>
void AnyPointer::Builder::adopt<DynamicValue>(Orphan<DynamicValue>&& orphan);
template <typename T>
inline Orphan<T> AnyPointer::Builder::disownAs(StructSchema schema) {
  return _::PointerHelpers<T>::disown(builder, schema);
}
template <typename T>
inline Orphan<T> AnyPointer::Builder::disownAs(ListSchema schema) {
  return _::PointerHelpers<T>::disown(builder, schema);
}

// We have to declare the methods below inline because Clang and GCC disagree about how to mangle
// their symbol names.
template <>
inline DynamicStruct::Builder Orphan<AnyPointer>::getAs<DynamicStruct>(StructSchema schema) {
  return DynamicStruct::Builder(schema, builder);
}
template <>
inline DynamicStruct::Reader Orphan<AnyPointer>::getAsReader<DynamicStruct>(
    StructSchema schema) const {
  return DynamicStruct::Reader(schema, builder);
}
template <>
inline Orphan<DynamicStruct> Orphan<AnyPointer>::releaseAs<DynamicStruct>(StructSchema schema) {
  return Orphan<DynamicStruct>(schema, kj::mv(builder));
}
template <>
inline DynamicList::Builder Orphan<AnyPointer>::getAs<DynamicList>(ListSchema schema) {
  return DynamicList::Builder(schema, builder);
}
template <>
inline DynamicList::Reader Orphan<AnyPointer>::getAsReader<DynamicList>(ListSchema schema) const {
  return DynamicList::Reader(schema, builder);
}
template <>
inline Orphan<DynamicList> Orphan<AnyPointer>::releaseAs<DynamicList>(ListSchema schema) {
  return Orphan<DynamicList>(schema, kj::mv(builder));
}
// =======================================================================================
// Inline implementation details.

template <typename T>
struct ToDynamic_<T, Kind::STRUCT> {
  static inline DynamicStruct::Reader apply(const typename T::Reader& value) {
    return DynamicStruct::Reader(Schema::from<T>(), value._reader);
  }
  static inline DynamicStruct::Builder apply(typename T::Builder& value) {
    return DynamicStruct::Builder(Schema::from<T>(), value._builder);
  }
};

template <typename T>
struct ToDynamic_<T, Kind::LIST> {
  static inline DynamicList::Reader apply(const typename T::Reader& value) {
    return DynamicList::Reader(Schema::from<T>(), value.reader);
  }
  static inline DynamicList::Builder apply(typename T::Builder& value) {
    return DynamicList::Builder(Schema::from<T>(), value.builder);
  }
};

template <typename T>
ReaderFor<DynamicTypeFor<FromReader<T>>> toDynamic(T&& value) {
  return ToDynamic_<FromReader<T>>::apply(value);
}
template <typename T>
BuilderFor<DynamicTypeFor<FromBuilder<T>>> toDynamic(T&& value) {
  return ToDynamic_<FromBuilder<T>>::apply(value);
}
template <typename T>
DynamicTypeFor<TypeIfEnum<T>> toDynamic(T&& value) {
  return DynamicEnum(Schema::from<kj::Decay<T>>(), static_cast<uint16_t>(value));
}

inline DynamicValue::Reader::Reader(std::nullptr_t n): type(UNKNOWN) {}
inline DynamicValue::Builder::Builder(std::nullptr_t n): type(UNKNOWN) {}

#define CAPNP_DECLARE_DYNAMIC_VALUE_CONSTRUCTOR(cppType, typeTag, fieldName) \
inline DynamicValue::Reader::Reader(cppType value) \
    : type(typeTag), fieldName##Value(value) {} \
inline DynamicValue::Builder::Builder(cppType value) \
    : type(typeTag), fieldName##Value(value) {} \
inline Orphan<DynamicValue>::Orphan(cppType value) \
    : type(DynamicValue::typeTag), fieldName##Value(value) {}

CAPNP_DECLARE_DYNAMIC_VALUE_CONSTRUCTOR(Void, VOID, void);
CAPNP_DECLARE_DYNAMIC_VALUE_CONSTRUCTOR(bool, BOOL, bool);
CAPNP_DECLARE_DYNAMIC_VALUE_CONSTRUCTOR(char, INT, int);
CAPNP_DECLARE_DYNAMIC_VALUE_CONSTRUCTOR(signed char, INT, int);
CAPNP_DECLARE_DYNAMIC_VALUE_CONSTRUCTOR(short, INT, int);
CAPNP_DECLARE_DYNAMIC_VALUE_CONSTRUCTOR(int, INT, int);
CAPNP_DECLARE_DYNAMIC_VALUE_CONSTRUCTOR(long, INT, int);
CAPNP_DECLARE_DYNAMIC_VALUE_CONSTRUCTOR(long long, INT, int);
CAPNP_DECLARE_DYNAMIC_VALUE_CONSTRUCTOR(unsigned char, UINT, uint);
CAPNP_DECLARE_DYNAMIC_VALUE_CONSTRUCTOR(unsigned short, UINT, uint);
CAPNP_DECLARE_DYNAMIC_VALUE_CONSTRUCTOR(unsigned int, UINT, uint);
CAPNP_DECLARE_DYNAMIC_VALUE_CONSTRUCTOR(unsigned long, UINT, uint);
CAPNP_DECLARE_DYNAMIC_VALUE_CONSTRUCTOR(unsigned long long, UINT, uint);
CAPNP_DECLARE_DYNAMIC_VALUE_CONSTRUCTOR(float, FLOAT, float);
CAPNP_DECLARE_DYNAMIC_VALUE_CONSTRUCTOR(double, FLOAT, float);
CAPNP_DECLARE_DYNAMIC_VALUE_CONSTRUCTOR(DynamicEnum, ENUM, enum);
#undef CAPNP_DECLARE_DYNAMIC_VALUE_CONSTRUCTOR

#define CAPNP_DECLARE_DYNAMIC_VALUE_CONSTRUCTOR(cppType, typeTag, fieldName) \
inline DynamicValue::Reader::Reader(const cppType::Reader& value) \
    : type(typeTag), fieldName##Value(value) {} \
inline DynamicValue::Builder::Builder(cppType::Builder value) \
    : type(typeTag), fieldName##Value(value) {}

CAPNP_DECLARE_DYNAMIC_VALUE_CONSTRUCTOR(Text, TEXT, text);
CAPNP_DECLARE_DYNAMIC_VALUE_CONSTRUCTOR(Data, DATA, data);
CAPNP_DECLARE_DYNAMIC_VALUE_CONSTRUCTOR(DynamicList, LIST, list);
CAPNP_DECLARE_DYNAMIC_VALUE_CONSTRUCTOR(DynamicStruct, STRUCT, struct);
CAPNP_DECLARE_DYNAMIC_VALUE_CONSTRUCTOR(AnyPointer, ANY_POINTER, anyPointer);

#undef CAPNP_DECLARE_DYNAMIC_VALUE_CONSTRUCTOR

inline DynamicValue::Reader::Reader(const char* value): Reader(Text::Reader(value)) {}

#define CAPNP_DECLARE_TYPE(discrim, typeName) \
template <> \
struct DynamicValue::Reader::AsImpl<typeName> { \
  static ReaderFor<typeName> apply(const Reader& reader); \
}; \
template <> \
struct DynamicValue::Builder::AsImpl<typeName> { \
  static BuilderFor<typeName> apply(Builder& builder); \
};

//CAPNP_DECLARE_TYPE(VOID, Void)
CAPNP_DECLARE_TYPE(BOOL, bool)
CAPNP_DECLARE_TYPE(INT8, int8_t)
CAPNP_DECLARE_TYPE(INT16, int16_t)
CAPNP_DECLARE_TYPE(INT32, int32_t)
CAPNP_DECLARE_TYPE(INT64, int64_t)
CAPNP_DECLARE_TYPE(UINT8, uint8_t)
CAPNP_DECLARE_TYPE(UINT16, uint16_t)
CAPNP_DECLARE_TYPE(UINT32, uint32_t)
CAPNP_DECLARE_TYPE(UINT64, uint64_t)
CAPNP_DECLARE_TYPE(FLOAT32, float)
CAPNP_DECLARE_TYPE(FLOAT64, double)

CAPNP_DECLARE_TYPE(TEXT, Text)
CAPNP_DECLARE_TYPE(DATA, Data)
CAPNP_DECLARE_TYPE(LIST, DynamicList)
CAPNP_DECLARE_TYPE(STRUCT, DynamicStruct)
CAPNP_DECLARE_TYPE(ENUM, DynamicEnum)
CAPNP_DECLARE_TYPE(ANY_POINTER, AnyPointer)
#undef CAPNP_DECLARE_TYPE

// CAPNP_DECLARE_TYPE(Void) causes gcc 4.7 to segfault.  If I do it manually and remove the
// ReaderFor<> and BuilderFor<> wrappers, it works.
template <>
struct DynamicValue::Reader::AsImpl<Void> {
  static Void apply(const Reader& reader);
};
template <>
struct DynamicValue::Builder::AsImpl<Void> {
  static Void apply(Builder& builder);
};

template <typename T>
struct DynamicValue::Reader::AsImpl<T, Kind::ENUM> {
  static T apply(const Reader& reader) {
    return reader.as<DynamicEnum>().as<T>();
  }
};
template <typename T>
struct DynamicValue::Builder::AsImpl<T, Kind::ENUM> {
  static T apply(Builder& builder) {
    return builder.as<DynamicEnum>().as<T>();
  }
};

template <typename T>
struct DynamicValue::Reader::AsImpl<T, Kind::STRUCT> {
  static typename T::Reader apply(const Reader& reader) {
    return reader.as<DynamicStruct>().as<T>();
  }
};
template <typename T>
struct DynamicValue::Builder::AsImpl<T, Kind::STRUCT> {
  static typename T::Builder apply(Builder& builder) {
    return builder.as<DynamicStruct>().as<T>();
  }
};

template <typename T>
struct DynamicValue::Reader::AsImpl<T, Kind::LIST> {
  static typename T::Reader apply(const Reader& reader) {
    return reader.as<DynamicList>().as<T>();
  }
};
template <typename T>
struct DynamicValue::Builder::AsImpl<T, Kind::LIST> {
  static typename T::Builder apply(Builder& builder) {
    return builder.as<DynamicList>().as<T>();
  }
};

template <>
struct DynamicValue::Reader::AsImpl<DynamicValue> {
  static DynamicValue::Reader apply(const Reader& reader) {
    return reader;
  }
};
template <>
struct DynamicValue::Builder::AsImpl<DynamicValue> {
  static DynamicValue::Builder apply(Builder& builder) {
    return builder;
  }
};

// -------------------------------------------------------------------

template <typename T>
typename T::Reader DynamicStruct::Reader::as() const {
  static_assert(kind<T>() == Kind::STRUCT,
                "DynamicStruct::Reader::as<T>() can only convert to struct types.");
  schema.requireUsableAs<T>();
  return typename T::Reader(reader);
}

template <typename T>
typename T::Builder DynamicStruct::Builder::as() {
  static_assert(kind<T>() == Kind::STRUCT,
                "DynamicStruct::Builder::as<T>() can only convert to struct types.");
  schema.requireUsableAs<T>();
  return typename T::Builder(builder);
}

template <>
inline DynamicStruct::Reader DynamicStruct::Reader::as<DynamicStruct>() const {
  return *this;
}
template <>
inline DynamicStruct::Builder DynamicStruct::Builder::as<DynamicStruct>() {
  return *this;
}

inline DynamicStruct::Reader DynamicStruct::Builder::asReader() const {
  return DynamicStruct::Reader(schema, builder.asReader());
}

template <>
inline AnyStruct::Reader DynamicStruct::Reader::as<AnyStruct>() const {
  return AnyStruct::Reader(reader);
}

template <>
inline AnyStruct::Builder DynamicStruct::Builder::as<AnyStruct>() {
  return AnyStruct::Builder(builder);
}

template <>
inline DynamicStruct::Reader AnyStruct::Reader::as<DynamicStruct>(StructSchema schema) const {
  return DynamicStruct::Reader(schema, _reader);
}

template <>
inline DynamicStruct::Builder AnyStruct::Builder::as<DynamicStruct>(StructSchema schema) {
  return DynamicStruct::Builder(schema, _builder);
}

template <typename T>
typename T::Reader DynamicList::Reader::as() const {
  static_assert(kind<T>() == Kind::LIST,
                "DynamicStruct::Reader::as<T>() can only convert to list types.");
  schema.requireUsableAs<T>();
  return typename T::Reader(reader);
}
template <typename T>
typename T::Builder DynamicList::Builder::as() {
  static_assert(kind<T>() == Kind::LIST,
                "DynamicStruct::Builder::as<T>() can only convert to list types.");
  schema.requireUsableAs<T>();
  return typename T::Builder(builder);
}

template <>
inline DynamicList::Reader DynamicList::Reader::as<DynamicList>() const {
  return *this;
}
template <>
inline DynamicList::Builder DynamicList::Builder::as<DynamicList>() {
  return *this;
}

template <>
inline AnyList::Reader DynamicList::Reader::as<AnyList>() const {
  return AnyList::Reader(reader);
}

template <>
inline AnyList::Builder DynamicList::Builder::as<AnyList>() {
  return AnyList::Builder(builder);
}

// -------------------------------------------------------------------

template <typename T>
ReaderFor<T> ConstSchema::as() const {
  return DynamicValue::Reader(*this).as<T>();
}

}  // namespace capnp

CAPNP_END_HEADER
