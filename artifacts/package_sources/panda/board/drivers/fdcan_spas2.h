#pragma once

// This path owns only one dedicated mailbox and one replace-latest packet.
// It never generates CAN packets or clears normal steering/SCC queues.
#if !defined(PANDA_JUNGLE) && !defined(PANDA_BODY)
#include "board/power_saving_declarations.h"

static CANPacket_t fdcan_spas2_pending;
static CANPacket_t fdcan_spas2_hardware_packet;
static bool fdcan_spas2_has_pending = false;
static bool fdcan_spas2_hardware_owned = false;
static bool fdcan_spas2_layout_failed = false;
static bool fdcan_spas2_sent = false;
static uint32_t fdcan_spas2_sent_at = 0U;
static uint32_t fdcan_spas2_generation = 0U;
static uint32_t fdcan_spas2_hardware_generation = 0U;
static bool fdcan_spas2_layout_configured = true;
static bool fdcan_spas2_harness_changed = false;

static bool fdcan_spas2_context_valid(void) {
  const uint8_t n = fdcan_spas2_owner;
  bool valid = hyundai_spas2_enabled() && !fdcan_spas2_layout_failed && !fdcan_spas2_harness_changed && !fdcan_layout_transition &&
    (hw_type == HW_TYPE_CUATRO) && (n < PANDA_CAN_CNT) && (CAN_NUM_FROM_BUS_NUM(0U) == n) &&
    (BUS_NUM_FROM_CAN_NUM(n) == 0U) && !can_silent && !can_loopback && !heartbeat_lost &&
    !relay_malfunction && harness.relay_driven && harness_check_ignition() &&
    ((harness.status == HARNESS_STATUS_NORMAL) || (harness.status == HARNESS_STATUS_FLIPPED)) &&
    (power_save_status == POWER_SAVE_STATUS_DISABLED);
  if (valid) {
    const FDCAN_GlobalTypeDef *can = cans[n];
    valid = bus_config[n].canfd_enabled && bus_config[n].brs_enabled && !bus_config[n].canfd_non_iso &&
      ((can->CCCR & (FDCAN_CCCR_INIT | FDCAN_CCCR_MON | FDCAN_CCCR_ASM | FDCAN_CCCR_TEST | FDCAN_CCCR_NISO)) == 0U) &&
      ((can->PSR & (FDCAN_PSR_BO | FDCAN_PSR_EP)) == 0U);
  }
  return valid;
}

static void fdcan_spas2_cancel_owned(void) {
  if (fdcan_spas2_hardware_owned && (fdcan_spas2_owner < PANDA_CAN_CNT)) {
    FDCAN_GlobalTypeDef *can = cans[fdcan_spas2_owner];
    if ((can->TXBRP & 1U) != 0U) {
      // Bit zero is dedicated to SPAS2. Never cancel the normal FIFO.
      can->TXBCR = 1U;
    } else {
      fdcan_spas2_hardware_owned = false;
    }
  }
}

void fdcan_spas2_poll(void) {
  if ((fdcan_spas2_owner < PANDA_CAN_CNT) &&
      (hyundai_spas2_enabled() || fdcan_spas2_hardware_owned || fdcan_spas2_has_pending)) {
    ENTER_CRITICAL();
    FDCAN_GlobalTypeDef *can = cans[fdcan_spas2_owner];
    uint32_t now = microsecond_timer_get();
    bool context = fdcan_spas2_context_valid();
    if (!context) {
      hyundai_spas2_invalidate();
      fdcan_spas2_has_pending = false;
      fdcan_spas2_cancel_owned();
    } else {
      if (fdcan_spas2_hardware_owned) {
        if ((can->TXBRP & 1U) == 0U) {
          fdcan_spas2_hardware_owned = false;
        } else if ((fdcan_spas2_hardware_generation != fdcan_spas2_generation) ||
                   !hyundai_spas2_packet_valid(&fdcan_spas2_hardware_packet, now)) {
          fdcan_spas2_cancel_owned();
        } else {
        }
      }
      if (fdcan_spas2_has_pending && !hyundai_spas2_packet_valid(&fdcan_spas2_pending, now)) {
        fdcan_spas2_has_pending = false;
      }
      if (fdcan_spas2_has_pending && !fdcan_spas2_hardware_owned && ((can->TXBCR & 1U) == 0U) &&
          (!fdcan_spas2_sent || (get_ts_elapsed(now, fdcan_spas2_sent_at) >= HYUNDAI_SPAS2_PERIOD_US))) {
        const CANPacket_t *p = &fdcan_spas2_pending;
        // Normal pandad uses fd=0 with auto-FD enabled. Check the effective mode.
        bool fd = bus_config[fdcan_spas2_owner].canfd_auto ? bus_config[fdcan_spas2_owner].canfd_enabled : (p->fd != 0U);
        canfd_fifo *slot = (canfd_fifo *)(FDCAN_START_ADDRESS + fdcan_layout_tx_offset(fdcan_spas2_owner, fdcan_spas2_owner));
        if (fd && can_check_checksum(&fdcan_spas2_pending)) {
          slot->header[0] = p->addr << 18U;
          slot->header[1] = (p->data_len_code << 16U) | (1UL << 21U) | (1UL << 20U);
          for (uint32_t i = 0U; i < 8U; i++) {
            BYTE_ARRAY_TO_WORD(slot->data_word[i], &p->data[i * 4U]);
          }
          // Final checks immediately precede the only feature TXBAR write.
          now = microsecond_timer_get();
          if (fdcan_spas2_context_valid() && hyundai_spas2_packet_valid(p, now) &&
              ((can->TXBRP & 1U) == 0U) && ((can->TXBCR & 1U) == 0U)) {
            fdcan_spas2_hardware_packet = *p;
            fdcan_spas2_hardware_generation = fdcan_spas2_generation;
            fdcan_spas2_hardware_owned = true;
            fdcan_spas2_sent = true;
            fdcan_spas2_sent_at = now;
            can->TXBAR = 1U;
            can_health[fdcan_spas2_owner].total_tx_cnt += 1U;
          }
        }
        fdcan_spas2_has_pending = false;
      }
    }
    EXIT_CRITICAL();
  }
}

bool fdcan_spas2_route(const CANPacket_t *packet, uint8_t bus_number, bool forwarded) {
  const bool owned = hyundai_spas2_enabled() && (GET_ADDR(packet) == 0x16A) && (bus_number == 0U);
  if (owned) {
    ENTER_CRITICAL();
    if (!forwarded && fdcan_spas2_context_valid()) {
      fdcan_spas2_generation += 1U;
      fdcan_spas2_pending = *packet;
      fdcan_spas2_has_pending = true;
    } else {
      if (forwarded) {
        hyundai_spas2_sender_conflict();
      } else {
        hyundai_spas2_invalidate();
      }
      fdcan_spas2_has_pending = false;
      fdcan_spas2_cancel_owned();
    }
    EXIT_CRITICAL();
    fdcan_spas2_poll();
  }
  return owned;
}

void fdcan_spas2_orientation_changing(void) {
  if (hyundai_spas2_enabled() || (fdcan_spas2_owner < PANDA_CAN_CNT)) {
    ENTER_CRITICAL();
    // Inhibit until MCU restart; mode resets cannot silently requalify a changed
    // physical harness. Cancellation happens before logical mapping changes.
    fdcan_spas2_harness_changed = true;
    hyundai_spas2_invalidate();
    fdcan_spas2_has_pending = false;
    fdcan_spas2_cancel_owned();
    EXIT_CRITICAL();
  }
}

void fdcan_spas2_layout_begin(void) {
  ENTER_CRITICAL();
  fdcan_spas2_has_pending = false;
  fdcan_spas2_cancel_owned();
  uint8_t requested = (hyundai_spas2_enabled() && !fdcan_spas2_harness_changed && (hw_type == HW_TYPE_CUATRO)) ?
                      CAN_NUM_FROM_BUS_NUM(0U) : FDCAN_SPAS2_NO_OWNER;
  if ((requested != fdcan_spas2_owner) || fdcan_spas2_layout_failed) {
    bool quiescent = true;
    for (uint8_t i = 0U; i < PANDA_CAN_CNT; i++) {
      llcan_irq_disable(cans[i]);
      quiescent = fdcan_request_init(cans[i]) && quiescent;
    }
    if (quiescent) {
      // M_CAN resets pending TX/FIFO state on entering configuration change
      // enable, not merely INIT. Establish CCE on every core before relayout.
      for (uint8_t i = 0U; i < PANDA_CAN_CNT; i++) {
        cans[i]->CCCR |= FDCAN_CCCR_CCE;
        quiescent = ((cans[i]->CCCR & FDCAN_CCCR_CCE) != 0U) && (cans[i]->TXBRP == 0U) && quiescent;
      }
    }
    if (quiescent) {
      // All cores are stopped BEFORE shared addresses change. Keep the critical
      // section and defer every exit/IRQ until all new RAM ranges are configured.
      fdcan_layout_transition = true;
      fdcan_spas2_layout_configured = true;
      fdcan_spas2_owner = requested;
      fdcan_spas2_hardware_owned = false;
      fdcan_spas2_layout_failed = false;
      fdcan_spas2_sent = false;
    } else {
      // No offsets changed. The ordinary reinit below retains the old layout;
      // feature output remains closed if any core could not be quiesced.
      fdcan_spas2_layout_failed = true;
      hyundai_spas2_invalidate();
    }
  }
  if (!fdcan_layout_transition) {
    EXIT_CRITICAL();
  }
}

void fdcan_spas2_layout_end(void) {
  if (fdcan_layout_transition) {
    bool ready = fdcan_spas2_layout_configured;
    if (ready) {
      for (uint8_t i = 0U; i < PANDA_CAN_CNT; i++) {
        ready = fdcan_exit_init(cans[i]) && ready;
      }
    }
    fdcan_spas2_layout_failed = !ready;
    fdcan_layout_transition = false;
    if (fdcan_spas2_layout_configured) {
      for (uint8_t i = 0U; i < PANDA_CAN_CNT; i++) {
        llcan_irq_enable(cans[i]);
      }
    }
    // A partially programmed shared layout must stay in INIT. Do not activate
    // a core with an old address range overlapping another core's new range.
    EXIT_CRITICAL();
  }
}
#else
void fdcan_spas2_layout_begin(void) { }
void fdcan_spas2_layout_end(void) { }
void fdcan_spas2_poll(void) { }
void fdcan_spas2_orientation_changing(void) { }
bool fdcan_spas2_route(const CANPacket_t *packet, uint8_t bus_number, bool forwarded) {
  UNUSED(forwarded);
  return hyundai_spas2_enabled() && (GET_ADDR(packet) == 0x16A) && (bus_number == 0U);
}
#endif
