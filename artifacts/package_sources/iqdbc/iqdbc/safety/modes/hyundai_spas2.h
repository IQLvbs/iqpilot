#pragma once

// Experimental normal-mode capability. No messages are generated here. The lease
// measures Panda admission age; the wire payload contains no host-origin timestamp.
// Receiver self-timeout and manual/hazard priority must be qualified separately.
#define HYUNDAI_PARAM_CANFD_SPAS2_BLINKERS 1024U
#define HYUNDAI_SPAS2_LEASE_US 100000U
#define HYUNDAI_SPAS2_PERIOD_US 20000U
#define HYUNDAI_SPAS2_DIRECTION_US 10000000U
#define HYUNDAI_SPAS2_NEUTRAL_US 3000000U

static bool hyundai_spas2_capability = false;
static bool hyundai_spas2_conflict = false;
static bool hyundai_spas2_counter_seen = false;
static uint8_t hyundai_spas2_counter = 0U;
static uint32_t hyundai_spas2_received_at = 0U;
static bool hyundai_spas2_admitted = false;
static bool hyundai_spas2_rate_seen = false;
static uint8_t hyundai_spas2_admitted_counter = 0U;
static uint8_t hyundai_spas2_admitted_control = 0U;
static uint32_t hyundai_spas2_admitted_at = 0U;
static bool hyundai_spas2_neutral_seen = false;
static uint32_t hyundai_spas2_neutral_since = 0U;
static uint32_t hyundai_spas2_neutral_last = 0U;
static bool hyundai_spas2_primed = false;
static bool hyundai_spas2_epoch = false;
static uint8_t hyundai_spas2_direction = 0U;
static uint32_t hyundai_spas2_epoch_at = 0U;
static bool hyundai_spas2_gear_seen = false;
static uint8_t hyundai_spas2_gear_counter = 0U;
static uint32_t hyundai_spas2_gear_at = 0U;
static bool hyundai_spas2_gear_valid = false;
static bool hyundai_spas2_gear_drive = false;

static inline bool hyundai_spas2_enabled(void) {
  return hyundai_spas2_capability && (current_safety_mode == SAFETY_HYUNDAI_CANFD);
}

static inline void hyundai_spas2_invalidate(void) {
  hyundai_spas2_primed = false;
  hyundai_spas2_neutral_seen = false;
  hyundai_spas2_epoch = false;
  // Invalidate already admitted directions. A later neutral is still admissible.
  if (hyundai_spas2_admitted_control != 0U) {
    hyundai_spas2_admitted = false;
  }
}

static inline void hyundai_spas2_sender_conflict(void) {
  hyundai_spas2_conflict = true;
  hyundai_spas2_invalidate();
  hyundai_spas2_admitted = false;
}

static void hyundai_spas2_init(bool enabled) {
  hyundai_spas2_capability = enabled;
  hyundai_spas2_conflict = false;
  hyundai_spas2_counter_seen = false;
  hyundai_spas2_admitted = false;
  hyundai_spas2_rate_seen = false;
  hyundai_spas2_admitted_control = 0U;
  hyundai_spas2_gear_seen = false;
  hyundai_spas2_gear_counter = 0U;
  hyundai_spas2_gear_valid = false;
  hyundai_spas2_gear_drive = false;
  hyundai_spas2_invalidate();
}

static bool hyundai_spas2_rx_fresh(uint32_t now) {
  bool valid = current_safety_config.rx_checks_len > 0;
  for (int i = 0; i < current_safety_config.rx_checks_len; i++) {
    const RxStatus *s = &current_safety_config.rx_checks[i].status;
    valid = valid && s->msg_seen && s->valid_checksum && s->valid_quality_flag &&
            (s->wrong_counters == 0) && (safety_get_ts_elapsed(now, s->last_timestamp) <= HYUNDAI_SPAS2_LEASE_US);
  }
  return valid && hyundai_spas2_gear_seen && hyundai_spas2_gear_valid &&
         (safety_get_ts_elapsed(now, hyundai_spas2_gear_at) <= HYUNDAI_SPAS2_LEASE_US);
}

// Optional feature observers do not change the mandatory vehicle RX list or
// controls_allowed. Stock SPAS on car-side bus0 is a latched sender conflict.
static void hyundai_spas2_rx_observe(const CANPacket_t *msg) {
  if (hyundai_spas2_enabled() && (GET_BUS(msg) == 0U)) {
    if ((GET_ADDR(msg) == 0x165) || (GET_ADDR(msg) == 0x16A)) {
      hyundai_spas2_sender_conflict();
    } else if (GET_ADDR(msg) == 0x40) {
      const uint8_t counter = GET_BYTE(msg, 2);
      const bool shape = (GET_LEN(msg) == 32) && (msg->extended == 0U) && (msg->returned == 0U) && (msg->rejected == 0U);
      const bool crc = shape && (hyundai_common_canfd_compute_checksum(msg) == (uint32_t)(GET_BYTE(msg, 0) | (GET_BYTE(msg, 1) << 8U)));
      const bool sequence = !hyundai_spas2_gear_seen || (counter == (uint8_t)(hyundai_spas2_gear_counter + 1U));
      hyundai_spas2_gear_valid = crc && sequence;
      // GEAR_ALT 0x40: byte4 bits0..2, D=5 on this qualified profile.
      hyundai_spas2_gear_drive = hyundai_spas2_gear_valid && ((GET_BYTE(msg, 4) & 7U) == 5U);
      hyundai_spas2_gear_seen = true;
      hyundai_spas2_gear_counter = counter;
      hyundai_spas2_gear_at = microsecond_timer_get();
      if (!hyundai_spas2_gear_valid || (hyundai_spas2_epoch && !hyundai_spas2_gear_drive)) {
        hyundai_spas2_invalidate();
      }
    } else {
    }
  }
  // Observe each RX result, rather than allowing a later good frame in the
  // same hardware batch to hide a lost directional prerequisite.
  if (hyundai_spas2_enabled() && hyundai_spas2_epoch &&
      (!controls_allowed || !hyundai_spas2_rx_fresh(microsecond_timer_get()))) {
    hyundai_spas2_invalidate();
  }
}

static bool hyundai_spas2_shape(const CANPacket_t *msg) {
  bool valid = (GET_ADDR(msg) == 0x16A) && (GET_BUS(msg) == 0U) && (GET_LEN(msg) == 32) &&
               (msg->extended == 0U) && (msg->returned == 0U) && (msg->rejected == 0U);
  for (int i = 3; i < 32; i++) {
    valid = valid && ((i == 16) || (GET_BYTE(msg, i) == 0U));
  }
  const uint8_t v = GET_BYTE(msg, 16);
  valid = valid && ((v == 0U) || (v == 0x60U) || (v == 0x80U));
  return valid && (hyundai_common_canfd_compute_checksum(msg) == (uint32_t)(GET_BYTE(msg, 0) | (GET_BYTE(msg, 1) << 8U)));
}

static inline bool hyundai_spas2_packet_valid(const CANPacket_t *msg, uint32_t now) {
  const uint8_t control = GET_BYTE(msg, 16) >> 5U;
  // Superseded hardware tickets are rejected without invalidating the NEW
  // admitted epoch. The board cancels only the old feature mailbox.
  if (!hyundai_spas2_admitted || (GET_BYTE(msg, 2) != hyundai_spas2_admitted_counter) ||
      (control != hyundai_spas2_admitted_control)) {
    return false;
  }
  bool valid = hyundai_spas2_enabled() && !hyundai_spas2_conflict && !relay_malfunction &&
    hyundai_spas2_admitted && hyundai_spas2_shape(msg) &&
    (GET_BYTE(msg, 2) == hyundai_spas2_admitted_counter) && (control == hyundai_spas2_admitted_control) &&
    (safety_get_ts_elapsed(now, hyundai_spas2_admitted_at) <= HYUNDAI_SPAS2_LEASE_US);
  if (control != 0U) {
    valid = valid && controls_allowed && hyundai_spas2_rx_fresh(now) && hyundai_spas2_gear_drive && hyundai_spas2_epoch &&
      (control == hyundai_spas2_direction) && (safety_get_ts_elapsed(now, hyundai_spas2_epoch_at) < HYUNDAI_SPAS2_DIRECTION_US);
    if (!valid) {
      hyundai_spas2_invalidate();
    }
  }
  return valid;
}

static bool hyundai_spas2_tx_hook(const CANPacket_t *msg) {
  const uint32_t now = microsecond_timer_get();
  const uint8_t control = GET_BYTE(msg, 16) >> 5U;
  if (!hyundai_spas2_enabled() || hyundai_spas2_conflict || relay_malfunction || !hyundai_spas2_shape(msg)) {
    hyundai_spas2_invalidate();
    return false;
  }
  const bool gap = hyundai_spas2_counter_seen && (safety_get_ts_elapsed(now, hyundai_spas2_received_at) > HYUNDAI_SPAS2_LEASE_US);
  const bool sequence = !hyundai_spas2_counter_seen || (GET_BYTE(msg, 2) == (uint8_t)(hyundai_spas2_counter + 1U));
  // Receipt sequence advances even on a rate rejection, never the TX lease.
  hyundai_spas2_counter = GET_BYTE(msg, 2);
  hyundai_spas2_received_at = now;
  hyundai_spas2_counter_seen = true;
  if (gap || !sequence) {
    hyundai_spas2_invalidate();
  }
  if (!sequence) {
    return false;
  }
  if (hyundai_spas2_epoch && (safety_get_ts_elapsed(now, hyundai_spas2_epoch_at) >= HYUNDAI_SPAS2_DIRECTION_US)) {
    hyundai_spas2_invalidate();
  }
  if (control == 0U) {
    if (hyundai_spas2_epoch) {
      hyundai_spas2_epoch = false;
      hyundai_spas2_primed = false;
      hyundai_spas2_neutral_seen = false;
    }
    // Neutral immediately invalidates an older directional ticket, including
    // a rate-rejected neutral. Only accepted neutral counts toward priming.
    if (hyundai_spas2_admitted_control != 0U) {
      hyundai_spas2_admitted = false;
    }
  } else if (!controls_allowed || !hyundai_spas2_rx_fresh(now) || !hyundai_spas2_gear_drive) {
    hyundai_spas2_invalidate();
    return false;
  }
  if (hyundai_spas2_rate_seen && (safety_get_ts_elapsed(now, hyundai_spas2_admitted_at) < HYUNDAI_SPAS2_PERIOD_US)) {
    return false;
  }
  if (control == 0U) {
    if (!hyundai_spas2_rx_fresh(now)) {
      hyundai_spas2_neutral_seen = false;
      hyundai_spas2_primed = false;
    } else if (!hyundai_spas2_neutral_seen ||
               (safety_get_ts_elapsed(now, hyundai_spas2_neutral_last) > HYUNDAI_SPAS2_LEASE_US)) {
      hyundai_spas2_neutral_seen = true;
      hyundai_spas2_neutral_since = now;
      hyundai_spas2_primed = false;
    } else if (safety_get_ts_elapsed(now, hyundai_spas2_neutral_since) >= HYUNDAI_SPAS2_NEUTRAL_US) {
      hyundai_spas2_primed = true;
      hyundai_spas2_epoch = false;
    } else {
    }
    hyundai_spas2_neutral_last = now;
  } else {
    if (!hyundai_spas2_epoch) {
      if (!hyundai_spas2_primed) {
        return false;
      }
      hyundai_spas2_epoch = true;
      hyundai_spas2_epoch_at = now;
      hyundai_spas2_direction = control;
      hyundai_spas2_primed = false;
    } else if (control != hyundai_spas2_direction) {
      hyundai_spas2_invalidate();
      return false;
    } else {
    }
    hyundai_spas2_neutral_seen = false;
  }
  hyundai_spas2_admitted = true;
  hyundai_spas2_rate_seen = true;
  hyundai_spas2_admitted_counter = GET_BYTE(msg, 2);
  hyundai_spas2_admitted_control = control;
  hyundai_spas2_admitted_at = now;
  return true;
}
