# Vendored Cap'n Proto

Based on Cap'n Proto 1.4.0, the version previously downloaded by this fork.

Source: https://capnproto.org/capnproto-c++-1.4.0.tar.gz

Archive SHA-256: `fa02378ad522b318916b9ad928d1372fc9abd43dd1f4f0392e50450f5c87828f`

See LICENSE.txt and individual files for upstream licenses.

This is an internal serialization/schema-parser subset for pycapnp, not a full
Cap'n Proto distribution. Generated schema sources are checked in; no compiler
executables or network downloads are required to build it.

Removed: RPC/capabilities, promises/async I/O, networking/TLS/HTTP, JSON,
compression, packed/text/stream/fd message serialization, command-line tools and
code generators, upstream build systems/examples/tests, compiler export helpers,
unused KJ encodings/stream classes/clocks, and opt-in crash handlers. Also removed
are canonicalization, borrowed-memory builders, orphan resizing/concatenation,
schema doc-comment storage, interface-schema support, Windows code, and the
optional lite build. Interface declarations are rejected with a parser error.

The retained core includes message validation, flat serialization, dynamic
struct/list/enum values, runtime schema compilation (including generics), and
its filesystem, allocation, synchronization, and diagnostic dependencies.
Generated schema reader/builder metadata is retained; pipeline classes are not.
This source tree is for the Python binding, not a drop-in C++ SDK or schema
compiler for openpilot's separate C++ build.

The retained `src/capnp/schema.capnp` omits compiler-request and documentation
metadata. Its generated C++ was rebuilt with upstream 1.4.0's `capnp` and
`capnpc-c++`, then unused generated pipeline APIs were removed. Regeneration:

```sh
capnp compile -I<upstream>/src --src-prefix=vendor/capnproto/src/capnp \
  -o<capnpc-c++>:<output> vendor/capnproto/src/capnp/schema.capnp
```

Regeneration must also apply the vendor's removal of Pipeline declarations,
classes and accessors, and Windows-only includes. The unused `LexedTokens` type
was removed from the shipped generated lexer files; the runtime parser uses
`LexedStatements`. Lexer reflection metadata is also omitted; its generated
static reader/builder layouts remain. Generated wire type tags and active field
ordinals are kept.
