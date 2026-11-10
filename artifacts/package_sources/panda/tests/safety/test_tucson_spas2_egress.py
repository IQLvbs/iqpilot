"""Execute the real board mailbox headers against host registers, never a car.

The safety callback is a controllable oracle here; the native safety policy has
its own CFFI tests. These tests exercise the actual egress/offset implementation.
They cannot establish STM32 peripheral timing, electrical behavior or ICU release.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

PANDA = Path(__file__).resolve().parents[2]
IQDBC = PANDA.parent / "iqdbc"

HARNESS = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// Only peripheral/context dependencies are simulated; both feature headers and
// the CAN packet/FIFO definitions below are the production source.
typedef struct {
  volatile uint32_t TXBRP, TXBCR, TXBAR, CCCR, PSR;
} FDCAN_GlobalTypeDef;
#include "board/drivers/fdcan_declarations.h"
#include "board/stm32h7/fdcan_spas2_layout.h"

#define FDCAN_CCCR_INIT 0x1U
#define FDCAN_CCCR_CCE 0x2U
#define FDCAN_CCCR_ASM 0x4U
#define FDCAN_CCCR_MON 0x20U
#define FDCAN_CCCR_TEST 0x80U
#define FDCAN_CCCR_NISO 0x8000U
#define FDCAN_PSR_EP 0x20U
#define FDCAN_PSR_BO 0x80U
#define HW_TYPE_CUATRO 9U
#define HARNESS_STATUS_NORMAL 1U
#define HARNESS_STATUS_FLIPPED 2U
#define HYUNDAI_SPAS2_PERIOD_US 20000U
#define GET_ADDR(p) ((p)->addr)

static FDCAN_GlobalTypeDef registers[PANDA_CAN_CNT];
FDCAN_GlobalTypeDef *cans[PANDA_CAN_CNT] = {&registers[0], &registers[1], &registers[2]};
static uint32_t message_ram[FDCAN_MESSAGE_RAM_BYTES / 4U];
#define FDCAN_START_ADDRESS ((uintptr_t)message_ram)
uint8_t fdcan_spas2_owner = 0U;
bool fdcan_layout_transition = false;
static uint8_t hw_type = HW_TYPE_CUATRO;
static bool can_silent, can_loopback, heartbeat_lost, relay_malfunction;
static bool ignition = true;
static struct { bool relay_driven; uint8_t status; } harness = {true, HARNESS_STATUS_NORMAL};
int power_save_status = 0;
static struct { bool canfd_enabled, brs_enabled, canfd_non_iso, canfd_auto; } bus_config[PANDA_CAN_CNT] = {
  {true, true, false, true}, {true, true, false, true}, {true, true, false, true},
};
static struct { uint32_t total_tx_cnt; } can_health[PANDA_CAN_CNT];
static uint8_t bus_to_can = 0U, can_to_bus = 0U;
#define CAN_NUM_FROM_BUS_NUM(n) ((void)(n), bus_to_can)
#define BUS_NUM_FROM_CAN_NUM(n) ((void)(n), can_to_bus)
static int critical_depth;
#define ENTER_CRITICAL() do { critical_depth++; } while (0)
#define EXIT_CRITICAL() do { assert(critical_depth > 0); critical_depth--; } while (0)
#define BYTE_ARRAY_TO_WORD(word, b) do { \
  (word) = (uint32_t)(b)[0] | ((uint32_t)(b)[1] << 8U) | ((uint32_t)(b)[2] << 16U) | ((uint32_t)(b)[3] << 24U); \
} while (0)

static bool feature_enabled = true, packet_valid = true, packet_checksum = true;
static uint32_t invalidations, clock_now = 1000U, clock_calls, final_revoke, final_revoke_kind;
static bool init_ok = true, exit_ok = true;
static uint32_t irq_disabled, irq_enabled, requested_init, requested_exit;
static bool hyundai_spas2_enabled(void) { return feature_enabled; }
static void hyundai_spas2_invalidate(void) { invalidations++; }
static void hyundai_spas2_sender_conflict(void) { invalidations++; }
static bool hyundai_spas2_packet_valid(const CANPacket_t *p, uint32_t now) {
  (void)p; (void)now;
  return packet_valid;
}
static bool can_check_checksum(const CANPacket_t *p) { (void)p; return packet_checksum; }
static bool harness_check_ignition(void) { return ignition; }
static uint32_t microsecond_timer_get(void) {
  clock_calls++;
  if ((final_revoke != 0U) && (clock_calls == final_revoke)) {
    switch (final_revoke_kind) {
      case 0U: packet_valid = false; break;
      case 1U: ignition = false; break;
      case 2U: registers[0].TXBRP = 1U; break;
      case 3U: registers[0].TXBCR = 1U; break;
      default: abort();
    }
  }
  return clock_now;
}
static uint32_t get_ts_elapsed(uint32_t now, uint32_t before) { return now - before; }
static void llcan_irq_disable(FDCAN_GlobalTypeDef *can) { (void)can; irq_disabled++; }
static void llcan_irq_enable(FDCAN_GlobalTypeDef *can) { (void)can; irq_enabled++; }
static bool fdcan_request_init(FDCAN_GlobalTypeDef *can) {
  requested_init++;
  if (init_ok) { can->CCCR |= FDCAN_CCCR_INIT; }
  return init_ok;
}
static bool fdcan_exit_init(FDCAN_GlobalTypeDef *can) {
  requested_exit++;
  if (exit_ok) { can->CCCR &= ~(FDCAN_CCCR_INIT | FDCAN_CCCR_CCE); }
  return exit_ok;
}

#include "board/drivers/fdcan_spas2.h"

#define CHECK(condition) do { if (!(condition)) { \
  fprintf(stderr, "line %d: %s\n", __LINE__, #condition); return 1; \
} } while (0)

static CANPacket_t packet(uint8_t counter) {
  CANPacket_t p = {0};
  p.addr = 0x16AU;
  p.data_len_code = 13U;
  p.data[2] = counter;
  p.data[16] = 0x80U;
  assert(GET_LEN(&p) == 32U);
  return p;
}

static canfd_fifo *feature_slot(void) {
  return (canfd_fifo *)(FDCAN_START_ADDRESS + fdcan_layout_tx_offset(fdcan_spas2_owner, fdcan_spas2_owner));
}

static bool ram_is_zero(void) {
  for (uint32_t i = 0U; i < FDCAN_MESSAGE_RAM_BYTES / 4U; i++) {
    if (message_ram[i] != 0U) { return false; }
  }
  return true;
}

static int run(const char *name, int argument) {
  CANPacket_t p = packet(1U);
  FDCAN_GlobalTypeDef *can = cans[0];
  if (strcmp(name, "flag_off") == 0) {
    feature_enabled = false;
    CHECK(!fdcan_spas2_route(&p, 0U, false));
    fdcan_spas2_poll();
    CHECK(can->TXBAR == 0U && can->TXBCR == 0U && ram_is_zero() && invalidations == 0U);
  } else if (strcmp(name, "unowned_route") == 0) {
    p.addr = 0x165U;
    CHECK(!fdcan_spas2_route(&p, 0U, false));
    p.addr = 0x16AU;
    CHECK(!fdcan_spas2_route(&p, 1U, false));
    CHECK(can->TXBAR == 0U && can->TXBCR == 0U && ram_is_zero());
  } else if (strcmp(name, "normal_auto_fd") == 0) {
    canfd_fifo *normal = feature_slot() + 1;
    normal->header[0] = 0x1234ABCDU;
    message_ram[0] = 0xCAFEBABEU;
    CHECK(p.fd == 0U && fdcan_spas2_route(&p, 0U, false));
    CHECK(normal->header[0] == 0x1234ABCDU && message_ram[0] == 0xCAFEBABEU);
    CHECK(can->TXBAR == 1U && can_health[0].total_tx_cnt == 1U);
    CHECK(feature_slot()->header[0] == (0x16AU << 18U));
    CHECK(feature_slot()->header[1] == ((13U << 16U) | (1U << 21U) | (1U << 20U)));
    CHECK(((uint8_t *)feature_slot()->data_word)[2] == 1U);
  } else if (strcmp(name, "no_effective_fd") == 0) {
    bus_config[0].canfd_auto = false;
    CHECK(fdcan_spas2_route(&p, 0U, false));
    CHECK(can->TXBAR == 0U && can_health[0].total_tx_cnt == 0U);
  } else if (strcmp(name, "bad_host_checksum") == 0) {
    packet_checksum = false;
    CHECK(fdcan_spas2_route(&p, 0U, false));
    CHECK(can->TXBAR == 0U && ram_is_zero() && !fdcan_spas2_has_pending);
  } else if (strcmp(name, "final_recheck") == 0) {
    final_revoke_kind = (uint32_t)argument;
    final_revoke = 2U;  // Revoke between copying into RAM and the final TXBAR check.
    CHECK(fdcan_spas2_route(&p, 0U, false));
    CHECK(clock_calls >= 2U);
    CHECK(can->TXBAR == 0U && can_health[0].total_tx_cnt == 0U && !fdcan_spas2_hardware_owned);
  } else if (strcmp(name, "cancel_only_owned_bit") == 0) {
    CHECK(fdcan_spas2_route(&p, 0U, false));
    can->TXBRP = 3U; // Feature bit0 and normal FIFO bit1 are both pending.
    heartbeat_lost = true;
    fdcan_spas2_poll();
    CHECK(can->TXBCR == 1U && can->TXBRP == 3U && invalidations == 1U);
    CHECK(cans[1]->TXBCR == 0U && cans[2]->TXBCR == 0U);
    CHECK(!fdcan_spas2_has_pending && fdcan_spas2_hardware_owned);
    can->TXBRP = 2U; // Hardware acknowledges cancellation of only bit0.
    fdcan_spas2_poll();
    CHECK(!fdcan_spas2_hardware_owned && can->TXBRP == 2U);
  } else if (strcmp(name, "replace_latest") == 0 || strcmp(name, "generation_wrap") == 0) {
    if (strcmp(name, "generation_wrap") == 0) { fdcan_spas2_generation = UINT32_MAX - 1U; }
    CHECK(fdcan_spas2_route(&p, 0U, false));
    uint32_t first_generation = fdcan_spas2_hardware_generation;
    can->TXBRP = 1U;
    can->TXBAR = 0U;
    clock_now += 1000U;
    p = packet(2U);
    CHECK(fdcan_spas2_route(&p, 0U, false));
    p = packet(3U);
    CHECK(fdcan_spas2_route(&p, 0U, false));
    CHECK(can->TXBCR == 1U && can->TXBAR == 0U && fdcan_spas2_pending.data[2] == 3U);
    CHECK(fdcan_spas2_hardware_generation == first_generation);
    can->TXBRP = 0U;
    can->TXBCR = 0U; // Peripheral has acknowledged cancellation.
    clock_now += 19000U;
    fdcan_spas2_poll();
    CHECK(can->TXBAR == 1U && can_health[0].total_tx_cnt == 2U);
    CHECK(((uint8_t *)feature_slot()->data_word)[2] == 3U && !fdcan_spas2_has_pending);
    CHECK(fdcan_spas2_hardware_generation == fdcan_spas2_generation);
    if (strcmp(name, "generation_wrap") == 0) { CHECK(fdcan_spas2_generation == 1U); }
  } else if (strcmp(name, "final_rate_limit") == 0) {
    CHECK(fdcan_spas2_route(&p, 0U, false));
    can->TXBAR = 0U;
    clock_now += 19999U;
    p = packet(2U);
    CHECK(fdcan_spas2_route(&p, 0U, false));
    CHECK(can->TXBAR == 0U && fdcan_spas2_has_pending && can_health[0].total_tx_cnt == 1U);
    clock_now += 1U;
    fdcan_spas2_poll();
    CHECK(can->TXBAR == 1U && can_health[0].total_tx_cnt == 2U);
  } else if (strcmp(name, "timer_wrap") == 0) {
    clock_now = UINT32_MAX - 9999U;
    CHECK(fdcan_spas2_route(&p, 0U, false));
    can->TXBAR = 0U;
    clock_now += 20000U;
    p = packet(2U);
    CHECK(fdcan_spas2_route(&p, 0U, false));
    CHECK(can->TXBAR == 1U && can_health[0].total_tx_cnt == 2U);
  } else if (strcmp(name, "expired_pending") == 0) {
    CHECK(fdcan_spas2_route(&p, 0U, false));
    can->TXBAR = 0U;
    clock_now += 1000U;
    p = packet(2U);
    CHECK(fdcan_spas2_route(&p, 0U, false));
    CHECK(fdcan_spas2_has_pending);
    packet_valid = false;
    clock_now += 20000U;
    fdcan_spas2_poll();
    CHECK(can->TXBAR == 0U && !fdcan_spas2_has_pending && can_health[0].total_tx_cnt == 1U);
  } else if (strcmp(name, "forwarded_not_owned") == 0) {
    CHECK(fdcan_spas2_route(&p, 0U, true));
    CHECK(invalidations == 1U && can->TXBAR == 0U && !fdcan_spas2_has_pending);
  } else if (strcmp(name, "invalid_context") == 0) {
    switch (argument) {
      case 0: heartbeat_lost = true; break;
      case 1: relay_malfunction = true; break;
      case 2: harness.relay_driven = false; break;
      case 3: ignition = false; break;
      case 4: harness.status = 0U; break;
      case 5: power_save_status = 1; break;
      case 6: bus_to_can = 1U; break;
      case 7: can_to_bus = 1U; break;
      case 8: bus_config[0].canfd_enabled = false; break;
      case 9: bus_config[0].brs_enabled = false; break;
      case 10: bus_config[0].canfd_non_iso = true; break;
      case 11: can->CCCR = FDCAN_CCCR_INIT; break;
      case 12: can->CCCR = FDCAN_CCCR_MON; break;
      case 13: can->CCCR = FDCAN_CCCR_ASM; break;
      case 14: can->CCCR = FDCAN_CCCR_TEST; break;
      case 15: can->CCCR = FDCAN_CCCR_NISO; break;
      case 16: can->PSR = FDCAN_PSR_BO; break;
      case 17: can->PSR = FDCAN_PSR_EP; break;
      case 18: can_silent = true; break;
      case 19: can_loopback = true; break;
      case 20: hw_type = 0U; break;
      case 21: fdcan_layout_transition = true; break;
      default: return 1;
    }
    CHECK(fdcan_spas2_route(&p, 0U, false));
    CHECK(invalidations >= 1U && can->TXBAR == 0U && ram_is_zero() && !fdcan_spas2_has_pending);
  } else if (strcmp(name, "cancellation_ack_guard") == 0) {
    CHECK(fdcan_spas2_route(&p, 0U, false));
    can->TXBRP = 1U;
    can->TXBAR = 0U;
    p = packet(2U);
    clock_now += 20000U;
    CHECK(fdcan_spas2_route(&p, 0U, false));
    CHECK(can->TXBCR == 1U && can->TXBAR == 0U);
    can->TXBRP = 0U; // Pending bit cleared, cancellation request not yet acknowledged.
    fdcan_spas2_poll();
    CHECK(can->TXBAR == 0U && fdcan_spas2_has_pending);
    can->TXBCR = 0U;
    fdcan_spas2_poll();
    CHECK(can->TXBAR == 1U && !fdcan_spas2_has_pending);
  } else if (strcmp(name, "orientation_inhibits_until_restart") == 0) {
    CHECK(fdcan_spas2_route(&p, 0U, false));
    can->TXBRP = 3U;
    can->TXBAR = 0U;
    fdcan_spas2_orientation_changing();
    CHECK(bus_to_can == 0U && fdcan_spas2_owner == 0U && can->TXBCR == 1U);
    CHECK(fdcan_spas2_harness_changed && invalidations == 1U);
    bus_to_can = 1U; // Mapping changes only after the old mailbox was cancelled.
    feature_enabled = false;
    feature_enabled = true; // A safety mode reset cannot clear the physical-change inhibit.
    bus_to_can = 0U;
    can->TXBRP = 2U;
    can->TXBCR = 0U;
    p = packet(2U);
    clock_now += 20000U;
    CHECK(fdcan_spas2_route(&p, 0U, false));
    CHECK(can->TXBAR == 0U && can->TXBRP == 2U && fdcan_spas2_harness_changed);
  } else if (strcmp(name, "layout_pending_tx_keeps_old_owner") == 0) {
    fdcan_spas2_owner = FDCAN_SPAS2_NO_OWNER;
    cans[1]->TXBRP = 2U;
    fdcan_spas2_layout_begin();
    CHECK(fdcan_spas2_owner == FDCAN_SPAS2_NO_OWNER && fdcan_spas2_layout_failed && !fdcan_layout_transition);
    CHECK(requested_init == 3U && requested_exit == 0U && irq_enabled == 0U && ram_is_zero());
  } else if (strcmp(name, "layout_partial_configuration_stays_stopped") == 0) {
    fdcan_spas2_owner = FDCAN_SPAS2_NO_OWNER;
    fdcan_spas2_layout_begin();
    fdcan_spas2_layout_configured = false;
    fdcan_spas2_layout_end();
    CHECK(fdcan_spas2_layout_failed && !fdcan_layout_transition && critical_depth == 0);
    CHECK(requested_exit == 0U && irq_enabled == 0U);
    CHECK((cans[0]->CCCR & FDCAN_CCCR_INIT) != 0U && (cans[1]->CCCR & FDCAN_CCCR_INIT) != 0U);
  } else if (strcmp(name, "layout_failed_same_owner_recovery") == 0) {
    fdcan_spas2_layout_failed = true;
    fdcan_spas2_layout_begin();
    CHECK(fdcan_layout_transition && fdcan_spas2_owner == 0U && requested_init == 3U && irq_disabled == 3U);
    fdcan_spas2_layout_end();
    CHECK(!fdcan_spas2_layout_failed && !fdcan_layout_transition && irq_enabled == 3U && requested_exit == 3U);
  } else if (strcmp(name, "layout_bounds") == 0) {
    const uint8_t owner = argument < 0 ? FDCAN_SPAS2_NO_OWNER : (uint8_t)argument;
    uint32_t previous_end = 0U;
    for (uint8_t n = 0U; n < PANDA_CAN_CNT; n++) {
      const uint32_t rx = fdcan_layout_rx_offset(n, owner);
      const uint32_t tx = fdcan_layout_tx_offset(n, owner);
      const uint32_t dedicated = fdcan_layout_dedicated_count(n, owner);
      CHECK(rx >= previous_end && rx % 4U == 0U && tx % 4U == 0U);
      CHECK(tx - rx == FDCAN_NORMAL_RX_BYTES);
      CHECK(dedicated == (uint32_t)(owner == n));
      previous_end = tx + (1U + dedicated) * FDCAN_SPAS2_BUFFER_BYTES;
      CHECK(previous_end <= FDCAN_MESSAGE_RAM_BYTES);
    }
  } else if (strcmp(name, "layout_transition") == 0) {
    fdcan_spas2_owner = FDCAN_SPAS2_NO_OWNER;
    fdcan_spas2_layout_begin();
    CHECK(critical_depth == 1 && fdcan_layout_transition && fdcan_spas2_owner == 0U);
    CHECK(requested_init == 3U && irq_disabled == 3U && irq_enabled == 0U);
    fdcan_spas2_layout_end();
    CHECK(critical_depth == 0 && !fdcan_layout_transition && !fdcan_spas2_layout_failed);
    CHECK(requested_exit == 3U && irq_enabled == 3U);
  } else if (strcmp(name, "layout_init_failure") == 0) {
    fdcan_spas2_owner = FDCAN_SPAS2_NO_OWNER;
    init_ok = false;
    fdcan_spas2_layout_begin();
    CHECK(fdcan_spas2_owner == FDCAN_SPAS2_NO_OWNER && !fdcan_layout_transition && fdcan_spas2_layout_failed);
    CHECK(invalidations == 1U && critical_depth == 0 && ram_is_zero());
  } else if (strcmp(name, "layout_exit_failure") == 0) {
    fdcan_spas2_owner = FDCAN_SPAS2_NO_OWNER;
    fdcan_spas2_layout_begin();
    exit_ok = false;
    fdcan_spas2_layout_end();
    CHECK(fdcan_spas2_layout_failed && !fdcan_layout_transition && critical_depth == 0);
    CHECK(fdcan_spas2_route(&p, 0U, false));
    CHECK(can->TXBAR == 0U);
  } else {
    return 2;
  }
  CHECK(critical_depth == 0);
  return 0;
}

int main(int argc, char **argv) {
  return argc >= 2 ? run(argv[1], argc > 2 ? atoi(argv[2]) : 0) : 2;
}
"""


@pytest.fixture(scope="module")
def egress_harness(tmp_path_factory):
  compiler = shutil.which("cc")
  if compiler is None:
    pytest.skip("host C compiler required for the real-header harness")
  directory = tmp_path_factory.mktemp("spas2-egress")
  source, executable = directory / "egress.c", directory / "egress"
  source.write_text(HARNESS)
  result = subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(PANDA), "-I", str(IQDBC),
                           str(source), "-o", str(executable)], capture_output=True, text=True)
  assert result.returncode == 0, result.stderr
  return executable


def run_case(executable, name, argument=0):
  result = subprocess.run([str(executable), name, str(argument)], capture_output=True, text=True)
  assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("case", [
  "flag_off", "unowned_route", "normal_auto_fd", "no_effective_fd", "bad_host_checksum",
  "cancel_only_owned_bit", "replace_latest", "generation_wrap", "final_rate_limit", "timer_wrap",
  "expired_pending", "forwarded_not_owned", "layout_transition", "layout_init_failure", "layout_exit_failure",
  "cancellation_ack_guard", "orientation_inhibits_until_restart", "layout_pending_tx_keeps_old_owner",
  "layout_partial_configuration_stays_stopped", "layout_failed_same_owner_recovery",
])
def test_actual_egress_header(egress_harness, case):
  run_case(egress_harness, case)


@pytest.mark.parametrize("context", range(22))
def test_actual_egress_fails_closed_for_invalid_context(egress_harness, context):
  run_case(egress_harness, "invalid_context", context)


@pytest.mark.parametrize("owner", [-1, 0, 1, 2])
def test_actual_ram_layout_stays_disjoint_and_in_bounds(egress_harness, owner):
  run_case(egress_harness, "layout_bounds", owner)


@pytest.mark.parametrize("revoke", range(4))
def test_actual_final_gate_rechecks_packet_context_and_mailbox(egress_harness, revoke):
  run_case(egress_harness, "final_recheck", revoke)
