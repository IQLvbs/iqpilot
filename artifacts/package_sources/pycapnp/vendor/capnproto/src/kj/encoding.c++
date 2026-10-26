// Copyright (c) 2017 Cloudflare, Inc.; Sandstorm Development Group, Inc.; and contributors
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

#include "encoding.h"
#include "vector.h"

namespace kj {

namespace {

const char HEX_DIGITS[] = "0123456789abcdef";
// Maps integer in the range [0,16) to a hex digit.

}  // namespace

namespace _ { // private

String encodeCEscapeImpl(ArrayPtr<const byte> bytes, bool isBinary) {
  Vector<char> escaped(bytes.size());

  for (byte b: bytes) {
    switch (b) {
      case '\a': escaped.addAll(StringPtr("\\a")); break;
      case '\b': escaped.addAll(StringPtr("\\b")); break;
      case '\f': escaped.addAll(StringPtr("\\f")); break;
      case '\n': escaped.addAll(StringPtr("\\n")); break;
      case '\r': escaped.addAll(StringPtr("\\r")); break;
      case '\t': escaped.addAll(StringPtr("\\t")); break;
      case '\v': escaped.addAll(StringPtr("\\v")); break;
      case '\'': escaped.addAll(StringPtr("\\\'")); break;
      case '\"': escaped.addAll(StringPtr("\\\"")); break;
      case '\\': escaped.addAll(StringPtr("\\\\")); break;
      default:
        if (b < 0x20 || b == 0x7f || (isBinary && b > 0x7f)) {
          // Use octal escape, not hex, because hex escapes technically have no length limit and
          // so can create ambiguity with subsequent characters.
          escaped.add('\\');
          escaped.add(HEX_DIGITS[b / 64]);
          escaped.add(HEX_DIGITS[(b / 8) % 8]);
          escaped.add(HEX_DIGITS[b % 8]);
        } else {
          escaped.add(b);
        }
        break;
    }
  }

  escaped.add(0);
  return String(escaped.releaseAsArray());
}

} // namespace

} // namespace kj
