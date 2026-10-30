#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdint.h>
#include <string.h>

#define MAX_SIGNALS 256
#define MAX_BAD_COUNTER 5
#define SLOT_ITEMS 15

enum {
  SLOT_STATE, SLOT_VL, SLOT_TS, SLOT_NAMES, SLOT_NAME, SLOT_PLAN, SLOT_NSIG, SLOT_SPECIALS, SLOT_NSPECIAL, SLOT_CHECK,
  SLOT_ADDRESS, SLOT_SIGS, SLOT_CALLBACKS, SLOT_LOG_FAILURE, SLOT_LEARN_FREQUENCY
};

enum { KIND_PYTHON = 0, KIND_MQB_MEB = 1, KIND_GEN2 = 2, KIND_XOR = 3 };

typedef struct {
  int32_t msb;
  int32_t lsb;
  int32_t size;
  int32_t is_signed;
  int32_t is_little_endian;
  int32_t pad;
  double factor;
  double offset;
} signal_t;

typedef struct {
  int32_t index;
  int32_t size;
  int32_t is_counter;
  int32_t has_checksum;
  int32_t kind;
  int32_t start_byte;
  int32_t pad0;
  int32_t pad1;
} special_t;

typedef struct {
  int32_t has_default;
  int32_t has_gen2;
  int32_t gen2_length;
  int32_t pad;
  uint8_t default_constants[16];
  uint8_t gen2_magic[16];
} check_t;

static uint8_t crc8_table[256];

static PyObject *s_first_seen_nanos, *s_ignore_checksum, *s_ignore_counter, *s_counter, *s_counter_fail, *s_vals, *s_frame_vals,
    *s_timestamps, *s_frequency, *s_append;

static uint64_t raw_value(const signal_t *sig, const uint8_t *dat, int length) {
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
  return ret;
}

static double scaled_value(const signal_t *sig, const uint8_t *dat, int length) {
  uint64_t ret = raw_value(sig, dat, length);
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
  return value * sig->factor + sig->offset;
}

static int crc_mqb_meb(const uint8_t *d, int n, const uint8_t *constants) {
  uint8_t crc = 0xFF;
  for (int i = 1; i < n; i++) {
    crc = crc8_table[crc ^ d[i]];
  }
  if (constants != NULL) {
    crc = crc8_table[crc ^ constants[d[1] & 0x0F]];
  }
  return crc ^ 0xFF;
}

static int expected_checksum(const special_t *special, const check_t *check, const uint8_t *d, int n, uint64_t *out) {
  if (special->kind == KIND_XOR) {
    uint8_t x = 0;
    for (int i = 0; i < n; i++) {
      if (i != special->start_byte) {
        x ^= d[i];
      }
    }
    *out = x;
    return 1;
  }
  if (n < 2) {
    return 0;
  }
  if (special->kind == KIND_GEN2 && check->has_gen2) {
    int length = check->gen2_length < n ? check->gen2_length : n;
    if (length >= 2) {
      int dynamic = crc_mqb_meb(d, length, check->gen2_magic);
      if (dynamic == d[0]) {
        *out = (uint64_t)dynamic;
        return 1;
      }
    } else {
      return 0;
    }
  }
  *out = (uint64_t)crc_mqb_meb(d, n, check->has_default ? check->default_constants : NULL);
  return 1;
}

static int get_long(PyObject *object, long *out) {
  long value = PyLong_AsLong(object);
  if (value == -1 && PyErr_Occurred()) {
    return -1;
  }
  *out = value;
  return 0;
}

static int update_counter(PyObject *state, uint64_t current, int size, int *ok) {
  PyObject *counter_obj = PyObject_GetAttr(state, s_counter);
  PyObject *fail_obj = counter_obj ? PyObject_GetAttr(state, s_counter_fail) : NULL;
  long counter, fail;
  int rc = -1;
  if (fail_obj == NULL || get_long(counter_obj, &counter) < 0 || get_long(fail_obj, &fail) < 0) {
    goto done;
  }
  uint64_t mask = size >= 64 ? ~0ULL : ((1ULL << size) - 1);
  if ((((uint64_t)counter + 1) & mask) != current) {
    fail = fail + 1 < MAX_BAD_COUNTER ? fail + 1 : MAX_BAD_COUNTER;
  } else if (fail > 0) {
    fail -= 1;
  }
  PyObject *new_counter = PyLong_FromUnsignedLongLong(current);
  PyObject *new_fail = PyLong_FromLong(fail);
  if (new_counter == NULL || new_fail == NULL || PyObject_SetAttr(state, s_counter, new_counter) < 0 ||
      PyObject_SetAttr(state, s_counter_fail, new_fail) < 0) {
    Py_XDECREF(new_counter);
    Py_XDECREF(new_fail);
    goto done;
  }
  Py_DECREF(new_counter);
  Py_DECREF(new_fail);
  *ok = fail < MAX_BAD_COUNTER;
  rc = 0;
done:
  Py_XDECREF(counter_obj);
  Py_XDECREF(fail_obj);
  return rc;
}

static int flag_set(PyObject *state, PyObject *name, int *out) {
  PyObject *value = PyObject_GetAttr(state, name);
  if (value == NULL) {
    return -1;
  }
  int truth = PyObject_IsTrue(value);
  Py_DECREF(value);
  if (truth < 0) {
    return -1;
  }
  *out = truth;
  return 0;
}

static int parse_native(PyObject *slot, PyObject *t, PyObject *address, PyObject *dat_obj, const uint8_t *dat, int length,
                        PyObject *dirty, PyObject *dat_store, PyObject *updated, int *parsed) {
  PyObject *state = PyTuple_GET_ITEM(slot, SLOT_STATE);
  const signal_t *plan = (const signal_t *)PyBytes_AS_STRING(PyTuple_GET_ITEM(slot, SLOT_PLAN));
  long nsig = PyLong_AsLong(PyTuple_GET_ITEM(slot, SLOT_NSIG));
  const special_t *specials = (const special_t *)PyBytes_AS_STRING(PyTuple_GET_ITEM(slot, SLOT_SPECIALS));
  long nspecial = PyLong_AsLong(PyTuple_GET_ITEM(slot, SLOT_NSPECIAL));
  const check_t *check = (const check_t *)PyBytes_AS_STRING(PyTuple_GET_ITEM(slot, SLOT_CHECK));
  PyObject *names = PyTuple_GET_ITEM(slot, SLOT_NAMES);
  PyObject *vl = PyTuple_GET_ITEM(slot, SLOT_VL);
  PyObject *ts = PyTuple_GET_ITEM(slot, SLOT_TS);
  PyObject *state_address = PyTuple_GET_ITEM(slot, SLOT_ADDRESS);
  PyObject *sigs = PyTuple_GET_ITEM(slot, SLOT_SIGS);
  PyObject *callbacks = PyTuple_GET_ITEM(slot, SLOT_CALLBACKS);
  double values[MAX_SIGNALS];
  PyObject *first_seen = NULL, *vals = NULL, *frame_vals = NULL, *timestamps = NULL, *new_values = NULL, *frequency_obj = NULL;
  PyObject *result = NULL;
  int rc = -1;
  int ignore_checksum, ignore_counter;
  int checksum_failed = 0, counter_failed = 0;

  *parsed = 0;
  if (nsig > MAX_SIGNALS) {
    PyErr_SetString(PyExc_ValueError, "too many signals for the native parser");
    return -1;
  }

  first_seen = PyObject_GetAttr(state, s_first_seen_nanos);
  if (first_seen == NULL) {
    goto done;
  }
  long first_seen_value;
  if (get_long(first_seen, &first_seen_value) < 0) {
    goto done;
  }
  if (first_seen_value == 0 && PyObject_SetAttr(state, s_first_seen_nanos, t) < 0) {
    goto done;
  }

  for (long i = 0; i < nsig; i++) {
    values[i] = scaled_value(&plan[i], dat, length);
  }

  if (flag_set(state, s_ignore_checksum, &ignore_checksum) < 0 || flag_set(state, s_ignore_counter, &ignore_counter) < 0) {
    goto done;
  }

  for (long k = 0; k < nspecial; k++) {
    const special_t *special = &specials[k];
    if (ignore_checksum && (ignore_counter || !special->is_counter)) {
      continue;
    }
    uint64_t received = raw_value(&plan[special->index], dat, length);

    if (!ignore_checksum && special->has_checksum) {
      uint64_t expected;
      int equal;
      PyObject *expected_obj = NULL;
      if (special->kind != KIND_PYTHON && expected_checksum(special, check, dat, length, &expected)) {
        equal = received == expected;
        if (!equal) {
          expected_obj = PyLong_FromUnsignedLongLong(expected);
        }
      } else {
        PyObject *callback = PyTuple_GET_ITEM(callbacks, k);
        PyObject *copy = PyByteArray_FromStringAndSize((const char *)dat, length);
        if (copy == NULL) {
          goto done;
        }
        expected_obj = PyObject_CallFunctionObjArgs(callback, state_address, PyTuple_GET_ITEM(sigs, k), copy, NULL);
        Py_DECREF(copy);
        if (expected_obj == NULL) {
          goto done;
        }
        PyObject *received_obj = PyLong_FromUnsignedLongLong(received);
        if (received_obj == NULL) {
          Py_DECREF(expected_obj);
          goto done;
        }
        equal = PyObject_RichCompareBool(received_obj, expected_obj, Py_EQ);
        Py_DECREF(received_obj);
        if (equal < 0) {
          Py_DECREF(expected_obj);
          goto done;
        }
        if (equal) {
          Py_DECREF(expected_obj);
          expected_obj = NULL;
        }
      }
      if (!equal) {
        checksum_failed = 1;
        if (expected_obj == NULL) {
          goto done;
        }
        PyObject *received_obj = PyLong_FromUnsignedLongLong(received);
        PyObject *logged = received_obj ? PyObject_CallFunctionObjArgs(PyTuple_GET_ITEM(slot, SLOT_LOG_FAILURE), t, received_obj, expected_obj, NULL) : NULL;
        Py_XDECREF(received_obj);
        Py_DECREF(expected_obj);
        if (logged == NULL) {
          goto done;
        }
        Py_DECREF(logged);
      }
    }

    if (!ignore_counter && special->is_counter) {
      int ok;
      if (update_counter(state, received, special->size, &ok) < 0) {
        goto done;
      }
      if (!ok) {
        counter_failed = 1;
      }
    }
  }

  if (checksum_failed || counter_failed) {
    rc = 0;
    goto done;
  }

  vals = PyObject_GetAttr(state, s_vals);
  if (vals == NULL) {
    goto done;
  }
  if (PyList_GET_SIZE(vals) == 0) {
    Py_DECREF(vals);
    vals = PyList_New(nsig);
    if (vals == NULL) {
      goto done;
    }
    for (long i = 0; i < nsig; i++) {
      PyObject *zero = PyFloat_FromDouble(0.0);
      if (zero == NULL) {
        goto done;
      }
      PyList_SET_ITEM(vals, i, zero);
    }
    if (PyObject_SetAttr(state, s_vals, vals) < 0) {
      goto done;
    }
  }

  new_values = PyList_New(nsig);
  if (new_values == NULL) {
    goto done;
  }
  for (long i = 0; i < nsig; i++) {
    PyObject *number = PyFloat_FromDouble(values[i]);
    if (number == NULL) {
      goto done;
    }
    PyList_SET_ITEM(new_values, i, number);
  }
  if (PyList_SetSlice(vals, 0, PyList_GET_SIZE(vals), new_values) < 0) {
    goto done;
  }
  frame_vals = PyObject_GetAttr(state, s_frame_vals);
  if (frame_vals == NULL || PyList_Append(frame_vals, new_values) < 0) {
    goto done;
  }
  timestamps = PyObject_GetAttr(state, s_timestamps);
  if (timestamps == NULL) {
    goto done;
  }
  result = PyObject_CallMethodOneArg(timestamps, s_append, t);
  if (result == NULL) {
    goto done;
  }
  Py_CLEAR(result);

  frequency_obj = PyObject_GetAttr(state, s_frequency);
  if (frequency_obj == NULL) {
    goto done;
  }
  double frequency = PyFloat_AsDouble(frequency_obj);
  if (frequency == -1.0 && PyErr_Occurred()) {
    goto done;
  }
  if (frequency < 1e-5) {
    result = PyObject_CallNoArgs(PyTuple_GET_ITEM(slot, SLOT_LEARN_FREQUENCY));
    if (result == NULL) {
      goto done;
    }
    Py_CLEAR(result);
  }

  if (PySet_Add(updated, address) < 0 || PyDict_SetItem(dirty, address, state) < 0) {
    goto done;
  }
  for (long i = 0; i < nsig; i++) {
    PyObject *name = PyTuple_GET_ITEM(names, i);
    if (PyDict_SetItem(vl, name, PyList_GET_ITEM(new_values, i)) < 0 || PyDict_SetItem(ts, name, t) < 0) {
      goto done;
    }
  }
  PyObject *raw_dat;
  if (PyBytes_CheckExact(dat_obj)) {
    raw_dat = dat_obj;
    Py_INCREF(raw_dat);
  } else {
    raw_dat = PyBytes_FromStringAndSize((const char *)dat, length);
    if (raw_dat == NULL) {
      goto done;
    }
  }
  if (PyDict_SetItem(dat_store, address, raw_dat) < 0 || PyDict_SetItem(dat_store, PyTuple_GET_ITEM(slot, SLOT_NAME), raw_dat) < 0) {
    Py_DECREF(raw_dat);
    goto done;
  }
  Py_DECREF(raw_dat);
  *parsed = 1;
  rc = 0;

done:
  Py_XDECREF(first_seen);
  Py_XDECREF(vals);
  Py_XDECREF(frame_vals);
  Py_XDECREF(timestamps);
  Py_XDECREF(new_values);
  Py_XDECREF(frequency_obj);
  Py_XDECREF(result);
  return rc;
}

static int buffer_of(PyObject *dat, const uint8_t **data, Py_ssize_t *length) {
  if (PyBytes_Check(dat)) {
    *data = (const uint8_t *)PyBytes_AS_STRING(dat);
    *length = PyBytes_GET_SIZE(dat);
    return 1;
  }
  if (PyByteArray_Check(dat)) {
    *data = (const uint8_t *)PyByteArray_AS_STRING(dat);
    *length = PyByteArray_GET_SIZE(dat);
    return 1;
  }
  return 0;
}

static PyObject *native_update(PyObject *self, PyObject *args) {
  PyObject *slots, *strings, *bus, *capture_obj, *seen, *dirty, *dat_store, *updated, *times, *fallback;
  (void)self;
  if (!PyArg_ParseTuple(args, "O!OOOO!O!O!O!O!O", &PyDict_Type, &slots, &strings, &bus, &capture_obj, &PySet_Type, &seen,
                        &PyDict_Type, &dirty, &PyDict_Type, &dat_store, &PySet_Type, &updated, &PyList_Type, &times, &fallback)) {
    return NULL;
  }
  int capture = PyObject_IsTrue(capture_obj);
  if (capture < 0) {
    return NULL;
  }
  PyObject *entries = PySequence_Fast(strings, "strings must be a sequence");
  if (entries == NULL) {
    return NULL;
  }
  int failed = 1;
  for (Py_ssize_t e = 0; e < PySequence_Fast_GET_SIZE(entries); e++) {
    PyObject *entry = PySequence_Fast(PySequence_Fast_GET_ITEM(entries, e), "entry must be a sequence");
    if (entry == NULL || PySequence_Fast_GET_SIZE(entry) < 2) {
      Py_XDECREF(entry);
      if (!PyErr_Occurred()) {
        PyErr_SetString(PyExc_ValueError, "entry needs a time and frames");
      }
      goto cleanup;
    }
    PyObject *t = PySequence_Fast_GET_ITEM(entry, 0);
    PyObject *frames = PySequence_Fast(PySequence_Fast_GET_ITEM(entry, 1), "frames must be a sequence");
    if (frames == NULL) {
      Py_DECREF(entry);
      goto cleanup;
    }
    int bus_empty = 1;
    for (Py_ssize_t f = 0; f < PySequence_Fast_GET_SIZE(frames); f++) {
      PyObject *frame = PySequence_Fast(PySequence_Fast_GET_ITEM(frames, f), "frame must be a sequence");
      if (frame == NULL || PySequence_Fast_GET_SIZE(frame) != 3) {
        Py_XDECREF(frame);
        if (!PyErr_Occurred()) {
          PyErr_SetString(PyExc_ValueError, "frame must be (address, data, bus)");
        }
        Py_DECREF(frames);
        Py_DECREF(entry);
        goto cleanup;
      }
      PyObject *address = PySequence_Fast_GET_ITEM(frame, 0);
      PyObject *dat = PySequence_Fast_GET_ITEM(frame, 1);
      PyObject *src = PySequence_Fast_GET_ITEM(frame, 2);
      int different = PyObject_RichCompareBool(src, bus, Py_NE);
      if (different < 0) {
        Py_DECREF(frame);
        Py_DECREF(frames);
        Py_DECREF(entry);
        goto cleanup;
      }
      if (different) {
        Py_DECREF(frame);
        continue;
      }
      bus_empty = 0;
      if (capture && PySet_Add(seen, address) < 0) {
        Py_DECREF(frame);
        Py_DECREF(frames);
        Py_DECREF(entry);
        goto cleanup;
      }
      PyObject *slot = PyDict_GetItemWithError(slots, address);
      if (slot == NULL) {
        Py_DECREF(frame);
        if (PyErr_Occurred()) {
          Py_DECREF(frames);
          Py_DECREF(entry);
          goto cleanup;
        }
        continue;
      }
      const uint8_t *data = NULL;
      Py_ssize_t length = 0;
      int native = slot != Py_None && PyTuple_CheckExact(slot) && PyTuple_GET_SIZE(slot) == SLOT_ITEMS && buffer_of(dat, &data, &length);
      int rc = 0;
      if (native) {
        if (length <= 64) {
          int parsed;
          rc = parse_native(slot, t, address, dat, data, (int)length, dirty, dat_store, updated, &parsed);
        }
      } else {
        PyObject *outcome = PyObject_CallFunctionObjArgs(fallback, t, address, dat, updated, NULL);
        if (outcome == NULL) {
          rc = -1;
        } else {
          Py_DECREF(outcome);
        }
      }
      Py_DECREF(frame);
      if (rc < 0) {
        Py_DECREF(frames);
        Py_DECREF(entry);
        goto cleanup;
      }
    }
    Py_DECREF(frames);
    if (!bus_empty) {
      Py_INCREF(t);
      if (PyList_SetItem(times, 0, t) < 0) {
        Py_DECREF(entry);
        goto cleanup;
      }
    }
    Py_INCREF(t);
    if (PyList_SetItem(times, 1, t) < 0) {
      Py_DECREF(entry);
      goto cleanup;
    }
    Py_DECREF(entry);
  }
  failed = 0;
cleanup:
  Py_DECREF(entries);
  if (failed) {
    return NULL;
  }
  Py_INCREF(updated);
  return updated;
}

static PyMethodDef methods[] = {
    {"update", native_update, METH_VARARGS, NULL},
    {NULL, NULL, 0, NULL},
};

static struct PyModuleDef module = {PyModuleDef_HEAD_INIT, "_can_parser_native", NULL, -1, methods, NULL, NULL, NULL, NULL};

PyMODINIT_FUNC PyInit__can_parser_native(void) {
  for (int i = 0; i < 256; i++) {
    uint8_t crc = (uint8_t)i;
    for (int bit = 0; bit < 8; bit++) {
      crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x2F) : (uint8_t)(crc << 1);
    }
    crc8_table[i] = crc;
  }
  s_first_seen_nanos = PyUnicode_InternFromString("first_seen_nanos");
  s_ignore_checksum = PyUnicode_InternFromString("ignore_checksum");
  s_ignore_counter = PyUnicode_InternFromString("ignore_counter");
  s_counter = PyUnicode_InternFromString("counter");
  s_counter_fail = PyUnicode_InternFromString("counter_fail");
  s_vals = PyUnicode_InternFromString("vals");
  s_frame_vals = PyUnicode_InternFromString("frame_vals");
  s_timestamps = PyUnicode_InternFromString("timestamps");
  s_frequency = PyUnicode_InternFromString("frequency");
  s_append = PyUnicode_InternFromString("append");
  if (!s_first_seen_nanos || !s_ignore_checksum || !s_ignore_counter || !s_counter || !s_counter_fail || !s_vals || !s_frame_vals ||
      !s_timestamps || !s_frequency || !s_append) {
    return NULL;
  }
  return PyModule_Create(&module);
}
