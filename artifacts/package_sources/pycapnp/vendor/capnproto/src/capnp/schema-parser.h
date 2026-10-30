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

#include "schema-loader.h"
#include <kj/string.h>
#include <kj/filesystem.h>

CAPNP_BEGIN_HEADER

namespace capnp {

class ParsedSchema;
class SchemaFile;

class SchemaParser {
  // Parses `.capnp` files to produce `Schema` objects.
  //
  // This class is thread-safe, hence all its methods are const.

public:
  SchemaParser();
  ~SchemaParser() noexcept(false);

  ParsedSchema parseDiskFile(kj::StringPtr displayName, kj::StringPtr diskPath,
                             kj::ArrayPtr<const kj::StringPtr> importPath) const;
  // Parse a file from disk. Relative imports and embeds can access paths outside its directory.
  // Absolute schema imports are searched in importPath.

  ParsedSchema parseFile(kj::Own<SchemaFile>&& file) const;
  // Advanced interface for parsing a file that may or may not be located in any global namespace.
  //
  // If the file has already been parsed (that is, a SchemaFile that compares equal to this one
  // was parsed previously), the existing schema will be returned again.
  //
  // This method reports errors by calling SchemaFile::reportError() on the file where the error
  // is located.  If that call does not throw an exception, `parseFile()` may in fact return
  // normally.  In this case, the result is a best-effort attempt to compile the schema, but it
  // may be invalid or corrupt, and using it for anything may cause exceptions to be thrown.

private:
  struct Impl;
  struct DiskFileCompat;
  class ModuleImpl;
  kj::Own<Impl> impl;
  mutable bool hadErrors = false;

  ModuleImpl& getModuleImpl(kj::Own<SchemaFile>&& file) const;

  friend class ParsedSchema;
};

class ParsedSchema: public Schema {
  // ParsedSchema is an extension of Schema which also has the ability to look up nested nodes
  // by name.  See `SchemaParser`.

public:
  inline ParsedSchema(): parser(nullptr) {}

  kj::Maybe<ParsedSchema> findNested(kj::StringPtr name) const;
  // Gets the nested node with the given name, or returns null if there is no such nested
  // declaration.

  ParsedSchema getNested(kj::StringPtr name) const;
  // Gets the nested node with the given name, or throws an exception if there is no such nested
  // declaration.

private:
  inline ParsedSchema(Schema inner, const SchemaParser& parser): Schema(inner), parser(&parser) {}

  const SchemaParser* parser;
  friend class SchemaParser;
};

class SchemaFile {
  // Abstract interface representing a schema file.  You can implement this yourself in order to
  // gain more control over how the compiler resolves imports and reads files.  For the
  // common case of files on disk or other global filesystem-like namespaces, use
  // `SchemaFile::newDiskFile()`.

public:
  // Note: Cap'n Proto 0.6.x and below had classes FileReader and DiskFileReader and a method
  //   newDiskFile() defined here. These were removed when SchemaParser was transitioned to use the
  //   KJ filesystem API. You should be able to get the same effect by subclassing
  //   kj::ReadableDirectory, or using kj::newInMemoryDirectory().

  static kj::Own<SchemaFile> newFromDirectory(
      const kj::ReadableDirectory& baseDir, kj::Path path,
      kj::ArrayPtr<const kj::ReadableDirectory* const> importPath,
      kj::Maybe<kj::String> displayNameOverride = nullptr);
  // Construct a SchemaFile representing a file in a kj::ReadableDirectory. This is used to
  // resolve imports relative to a filesystem directory.
  //
  // The SchemaFile compares equal to any other SchemaFile that has exactly the same `baseDir`
  // object (by identity) and `path` (by value).

  // -----------------------------------------------------------------
  // For more control, you can implement this interface.

  virtual kj::StringPtr getDisplayName() const = 0;
  // Get the file's name, as it should appear in the schema.

  virtual kj::Array<const char> readContent() const = 0;
  // Read the file's entire content and return it as a byte array.

  virtual kj::Maybe<kj::Own<SchemaFile>> import(kj::StringPtr path) const = 0;
  // Resolve an import, relative to this file.
  //
  // `path` is exactly what appears between quotes after the `import` keyword in the source code.
  // It is entirely up to the `SchemaFile` to decide how to map this to another file.  Typically,
  // a leading '/' means that the file is an "absolute" path and is searched for in some list of
  // schema file repositories.  On the other hand, a path that doesn't start with '/' is relative
  // to the importing file.

  virtual bool operator==(const SchemaFile& other) const = 0;
  virtual size_t hashCode() const = 0;
  // Compare two SchemaFiles to see if they refer to the same underlying file.  This is an
  // optimization used to avoid the need to re-parse a file to check its ID.

  struct SourcePos {
    uint byte;
    uint line;
    uint column;
  };
  virtual void reportError(SourcePos start, SourcePos end, kj::StringPtr message) const = 0;
  // Report that the file contains an error at the given interval.

private:
  class DiskSchemaFile;
};

}  // namespace capnp

CAPNP_END_HEADER
