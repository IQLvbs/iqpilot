#include <math.h>
#include <stddef.h>
#include <stdint.h>

typedef struct {
  int32_t msb;
  int32_t lsb;
  int32_t size;
  int32_t is_signed;
  int32_t is_little_endian;
  int32_t pad;
  double factor;
  double offset;
} can_signal;

void can_signals_decode(const can_signal *signals, int count, const uint8_t *dat, int length, double *out) {
  for (int k = 0; k < count; k++) {
    const can_signal *sig = &signals[k];
    uint64_t ret = 0;
    int i = sig->msb / 8;
    int bits = sig->size;
    while (i >= 0 && i < length && bits > 0) {
      int lsb = (sig->lsb / 8) == i ? sig->lsb : i * 8;
      int msb = (sig->msb / 8) == i ? sig->msb : (i + 1) * 8 - 1;
      int size = msb - lsb + 1;
      uint64_t d = ((uint64_t)dat[i] >> (lsb - i * 8)) & ((1ULL << size) - 1);
      ret |= d << (bits - size);
      bits -= size;
      i = sig->is_little_endian ? i - 1 : i + 1;
    }
    double value;
    if (sig->is_signed) {
      int64_t signed_ret = (int64_t)ret;
      if (sig->size < 64) {
        signed_ret = (int64_t)ret - (int64_t)(((ret >> (sig->size - 1)) & 1ULL) << sig->size);
      }
      value = (double)signed_ret;
    } else {
      value = (double)ret;
    }
    out[k] = value * sig->factor + sig->offset;
  }
}

static uint8_t crc8_h2f_table[256];

__attribute__((constructor)) static void init_crc8_h2f_table(void) {
  for (int i = 0; i < 256; i++) {
    uint8_t crc = (uint8_t)i;
    for (int bit = 0; bit < 8; bit++) {
      crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x2F) : (uint8_t)(crc << 1);
    }
    crc8_h2f_table[i] = crc;
  }
}

int can_vw_mqb_meb_crc(const uint8_t *d, int n, const uint8_t *constants) {
  uint8_t crc = 0xFF;
  for (int i = 1; i < n; i++) {
    crc = crc8_h2f_table[crc ^ d[i]];
  }
  if (constants != NULL) {
    crc = crc8_h2f_table[crc ^ constants[d[1] & 0x0F]];
  }
  return crc ^ 0xFF;
}

int can_signals_pack(const can_signal *signals, int count, const int32_t *idx, const double *vals, int n, uint8_t *dat,
                     int length) {
  for (int k = 0; k < n; k++) {
    if (idx[k] < 0 || idx[k] >= count) {
      return 2;
    }
    const can_signal *sig = &signals[idx[k]];
    double x = (vals[k] - sig->offset) / sig->factor + 0.5;
    if (!isfinite(x) || fabs(x) >= 4.0e18) {
      return 1;
    }
    uint64_t ival = (uint64_t)(int64_t)floor(x);
    if (sig->size < 64) {
      ival &= (1ULL << sig->size) - 1;
    }
    int i = sig->lsb / 8;
    int bits = sig->size;
    while (i >= 0 && i < length && bits > 0) {
      int shift = (sig->lsb / 8) == i ? sig->lsb % 8 : 0;
      int size = bits < 8 - shift ? bits : 8 - shift;
      uint8_t field = (uint8_t)((1u << size) - 1);
      uint8_t mask = (uint8_t)(field << shift);
      dat[i] = (uint8_t)((dat[i] & ~mask) | (uint8_t)((ival & field) << shift));
      bits -= size;
      ival >>= size;
      i = sig->is_little_endian ? i + 1 : i - 1;
    }
  }
  return 0;
}

typedef struct {
  int32_t union_byte_offset;
  int32_t can_tag;
  int32_t can_pointer_index;
  int32_t mono_byte_offset;
  int32_t address_byte_offset;
  int32_t src_byte_offset;
  int32_t dat_pointer_index;
  int32_t pad;
} can_event_layout;

static uint64_t load_u64(const uint8_t *p) {
  uint64_t v;
  __builtin_memcpy(&v, p, 8);
  return v;
}

static uint32_t load_u32(const uint8_t *p) {
  uint32_t v;
  __builtin_memcpy(&v, p, 4);
  return v;
}

static uint16_t load_u16(const uint8_t *p) {
  uint16_t v;
  __builtin_memcpy(&v, p, 2);
  return v;
}

int can_event_parse(const uint8_t *buf, int64_t length, const can_event_layout *layout, uint64_t *mono, int32_t capacity,
                    uint32_t *addr, uint32_t *off, uint32_t *len, uint32_t *src) {
  if (length < 16) {
    return -1;
  }
  if (load_u32(buf) != 0) {
    return -1;
  }
  uint64_t seg_words = load_u32(buf + 4);
  if ((uint64_t)length < 8 + seg_words * 8) {
    return -1;
  }
  const uint8_t *seg = buf + 8;

  uint64_t root = load_u64(seg);
  if ((root & 3) != 0) {
    return -1;
  }
  int64_t event_start = 1 + ((int64_t)((int32_t)(uint32_t)root >> 2));
  uint64_t event_data_words = (root >> 32) & 0xffff;
  uint64_t event_pointer_words = root >> 48;
  if (event_start < 0 || (uint64_t)event_start + event_data_words + event_pointer_words > seg_words) {
    return -1;
  }
  const uint8_t *event_data = seg + (uint64_t)event_start * 8;
  if (layout->union_byte_offset < 0 || (uint64_t)layout->union_byte_offset + 2 > event_data_words * 8 ||
      layout->mono_byte_offset < 0 || (uint64_t)layout->mono_byte_offset + 8 > event_data_words * 8) {
    return -1;
  }
  if (load_u16(event_data + layout->union_byte_offset) != (uint16_t)layout->can_tag) {
    return -1;
  }
  *mono = load_u64(event_data + layout->mono_byte_offset);

  if (layout->can_pointer_index < 0 || (uint64_t)layout->can_pointer_index >= event_pointer_words) {
    return -1;
  }
  uint64_t list_pointer_word = (uint64_t)event_start + event_data_words + (uint64_t)layout->can_pointer_index;
  uint64_t list_pointer = load_u64(seg + list_pointer_word * 8);
  if (list_pointer == 0) {
    return 0;
  }
  if ((list_pointer & 3) != 1 || ((list_pointer >> 32) & 7) != 7) {
    return -1;
  }
  int64_t list_start = (int64_t)list_pointer_word + 1 + ((int64_t)((int32_t)(uint32_t)list_pointer >> 2));
  uint64_t list_words = list_pointer >> 35;
  if (list_start < 0 || (uint64_t)list_start + 1 + list_words > seg_words) {
    return -1;
  }
  uint64_t tag = load_u64(seg + (uint64_t)list_start * 8);
  if ((tag & 3) != 0) {
    return -1;
  }
  uint64_t count = (uint32_t)tag >> 2;
  uint64_t element_data_words = (tag >> 32) & 0xffff;
  uint64_t element_pointer_words = tag >> 48;
  uint64_t element_words = element_data_words + element_pointer_words;
  if (count * element_words > list_words) {
    return -1;
  }
  if (count > (uint64_t)capacity) {
    return -2;
  }
  if (layout->address_byte_offset < 0 || (uint64_t)layout->address_byte_offset + 4 > element_data_words * 8 ||
      layout->src_byte_offset < 0 || (uint64_t)layout->src_byte_offset + 1 > element_data_words * 8 ||
      layout->dat_pointer_index < 0 || (uint64_t)layout->dat_pointer_index >= element_pointer_words) {
    return count == 0 ? 0 : -1;
  }

  for (uint64_t i = 0; i < count; i++) {
    uint64_t element_word = (uint64_t)list_start + 1 + i * element_words;
    const uint8_t *element_data = seg + element_word * 8;
    addr[i] = load_u32(element_data + layout->address_byte_offset);
    src[i] = element_data[layout->src_byte_offset];
    uint64_t dat_pointer_word = element_word + element_data_words + (uint64_t)layout->dat_pointer_index;
    uint64_t dat_pointer = load_u64(seg + dat_pointer_word * 8);
    if (dat_pointer == 0) {
      off[i] = 0;
      len[i] = 0;
      continue;
    }
    if ((dat_pointer & 3) != 1 || ((dat_pointer >> 32) & 7) != 2) {
      return -1;
    }
    int64_t dat_start = (int64_t)dat_pointer_word + 1 + ((int64_t)((int32_t)(uint32_t)dat_pointer >> 2));
    uint64_t dat_len = dat_pointer >> 35;
    if (dat_start < 0 || (uint64_t)dat_start * 8 + dat_len > seg_words * 8) {
      return -1;
    }
    off[i] = (uint32_t)(8 + (uint64_t)dat_start * 8);
    len[i] = (uint32_t)dat_len;
  }
  return (int)count;
}
