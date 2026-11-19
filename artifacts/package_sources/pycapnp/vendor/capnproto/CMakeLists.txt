cmake_minimum_required(VERSION 3.16)
project(pycapnp_vendor LANGUAGES CXX)

add_library(capnp-vendored STATIC
  src/capnp/blob.c++
  src/capnp/arena.c++
  src/capnp/layout.c++
  src/capnp/message.c++
  src/capnp/schema.capnp.c++
  src/capnp/serialize.c++
  src/capnp/schema.c++
  src/capnp/schema-loader.c++
  src/capnp/dynamic.c++
  src/capnp/stringify.c++
  src/capnp/compiler/type-id.c++
  src/capnp/compiler/lexer.c++
  src/capnp/compiler/grammar.capnp.c++
  src/capnp/compiler/parser.c++
  src/capnp/compiler/generics.c++
  src/capnp/compiler/node-translator.c++
  src/capnp/compiler/compiler.c++
  src/capnp/schema-parser.c++
  src/kj/array.c++
  src/kj/common.c++
  src/kj/debug.c++
  src/kj/exception.c++
  src/kj/io.c++
  src/kj/mutex.c++
  src/kj/string.c++
  src/kj/source-location.c++
  src/kj/hash.c++
  src/kj/table.c++
  src/kj/arena.c++
  src/kj/units.c++
  src/kj/encoding.c++
  src/kj/refcount.c++
  src/kj/string-tree.c++
  src/kj/time.c++
  src/kj/filesystem.c++
  src/kj/filesystem-disk-unix.c++
  src/kj/parse/char.c++
)
target_compile_features(capnp-vendored PUBLIC cxx_std_17)
target_include_directories(capnp-vendored PUBLIC src)
set_target_properties(capnp-vendored PROPERTIES POSITION_INDEPENDENT_CODE ON)
find_package(Threads REQUIRED)
target_link_libraries(capnp-vendored PUBLIC Threads::Threads)
