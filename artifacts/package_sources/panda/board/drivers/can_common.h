#pragma once

#include "can_common_declarations.h"

uint32_t safety_tx_blocked = 0;
uint32_t safety_rx_invalid = 0;
uint32_t tx_buffer_overflow = 0;
uint32_t rx_buffer_overflow = 0;

can_health_t can_health[PANDA_CAN_CNT] = {{0}, {0}, {0}};

// Ignition detected from CAN meessages
bool ignition_can = false;
uint32_t ignition_can_cnt = 0U;

// set only once a Toyota SecOC hybrid gear source is positively identified: those cars keep
// the harness ignition line live in Park, so the reported line has to follow the gear instead
bool ignition_can_gates_line = false;

bool can_silent = true;
bool can_loopback = false;

// ********************* instantiate queues *********************
#define can_buffer(x, size) \
  static CANPacket_t elems_##x[size]; \
  extern can_ring can_##x; \
  can_ring can_##x = { .w_ptr = 0, .r_ptr = 0, .fifo_size = (size), .elems = (CANPacket_t *)&(elems_##x) };

#ifdef STM32H7
  #define CAN_RX_BUFFER_SIZE 4096U
  #define CAN_TX_BUFFER_SIZE 416U
// ITCM RAM and DTCM RAM are the fastest for Cortex-M7 core access
__attribute__((section(".axisram"))) can_buffer(rx_q, CAN_RX_BUFFER_SIZE)
__attribute__((section(".itcmram"))) can_buffer(tx1_q, CAN_TX_BUFFER_SIZE)
__attribute__((section(".itcmram"))) can_buffer(tx2_q, CAN_TX_BUFFER_SIZE)
#else
  #define CAN_RX_BUFFER_SIZE 512U
  #define CAN_TX_BUFFER_SIZE 52U
can_buffer(rx_q, CAN_RX_BUFFER_SIZE)
can_buffer(tx1_q, CAN_TX_BUFFER_SIZE)
can_buffer(tx2_q, CAN_TX_BUFFER_SIZE)
#endif
can_buffer(tx3_q, CAN_TX_BUFFER_SIZE)

// FIXME:
// cppcheck-suppress misra-c2012-9.3
can_ring *can_queues[PANDA_CAN_CNT] = {&can_tx1_q, &can_tx2_q, &can_tx3_q};

// ********************* interrupt safe queue *********************
bool can_pop(can_ring *q, CANPacket_t *elem) {
  bool ret = 0;

  ENTER_CRITICAL();
  if (q->w_ptr != q->r_ptr) {
    *elem = q->elems[q->r_ptr];
    if ((q->r_ptr + 1U) == q->fifo_size) {
      q->r_ptr = 0;
    } else {
      q->r_ptr += 1U;
    }
    ret = 1;
  }
  EXIT_CRITICAL();

  return ret;
}

bool can_push(can_ring *q, const CANPacket_t *elem) {
  bool ret = false;
  uint32_t next_w_ptr;

  ENTER_CRITICAL();
  if ((q->w_ptr + 1U) == q->fifo_size) {
    next_w_ptr = 0;
  } else {
    next_w_ptr = q->w_ptr + 1U;
  }
  if (next_w_ptr != q->r_ptr) {
    q->elems[q->w_ptr] = *elem;
    q->w_ptr = next_w_ptr;
    ret = true;
  }
  EXIT_CRITICAL();
  if (!ret) {
    #ifdef DEBUG
      print("can_push to ");
      if (q == &can_rx_q) {
        print("can_rx_q");
      } else if (q == &can_tx1_q) {
        print("can_tx1_q");
      } else if (q == &can_tx2_q) {
        print("can_tx2_q");
      } else if (q == &can_tx3_q) {
        print("can_tx3_q");
      } else {
        print("unknown");
      }
      print(" failed!\n");
    #endif
  }
  return ret;
}

uint32_t can_slots_empty(const can_ring *q) {
  uint32_t ret = 0;

  ENTER_CRITICAL();
  if (q->w_ptr >= q->r_ptr) {
    ret = q->fifo_size - 1U - q->w_ptr + q->r_ptr;
  } else {
    ret = q->r_ptr - q->w_ptr - 1U;
  }
  EXIT_CRITICAL();

  return ret;
}

void can_clear(can_ring *q) {
  ENTER_CRITICAL();
  q->w_ptr = 0;
  q->r_ptr = 0;
  EXIT_CRITICAL();
  // handle TX buffer full with zero ECUs awake on the bus
  refresh_can_tx_slots_available();
}

// assign CAN numbering
// bus num: CAN Bus numbers in panda, sent to/from USB
//    Min: 0; Max: 127; Bit 7 marks message as receipt (bus 129 is receipt for but 1)
// cans: Look up MCU can interface from bus number
// can number: numeric lookup for MCU CAN interfaces (0 = CAN1, 1 = CAN2, etc);
// bus_lookup: Translates from 'can number' to 'bus number'.
// can_num_lookup: Translates from 'bus number' to 'can number'.
// forwarding bus: If >= 0, forward all messages from this bus to the specified bus.

// Helpers
// Panda:       Bus 0=CAN1   Bus 1=CAN2   Bus 2=CAN3
bus_config_t bus_config[PANDA_CAN_CNT] = {
  { .bus_lookup = 0U, .can_num_lookup = 0U, .forwarding_bus = -1, .can_speed = 5000U, .can_data_speed = 20000U, .canfd_auto = false, .canfd_enabled = false, .brs_enabled = false, .canfd_non_iso = false },
  { .bus_lookup = 1U, .can_num_lookup = 1U, .forwarding_bus = -1, .can_speed = 5000U, .can_data_speed = 20000U, .canfd_auto = false, .canfd_enabled = false, .brs_enabled = false, .canfd_non_iso = false },
  { .bus_lookup = 2U, .can_num_lookup = 2U, .forwarding_bus = -1, .can_speed = 5000U, .can_data_speed = 20000U, .canfd_auto = false, .canfd_enabled = false, .brs_enabled = false, .canfd_non_iso = false },
};

void can_init_all(void) {
  for (uint8_t i=0U; i < PANDA_CAN_CNT; i++) {
    bus_config[i].canfd_enabled = false;
    // NOTE: do NOT reset can_data_speed here. Matching stock panda, can_init_all() only clears
    // canfd_enabled (re-discovered on RX via canfd_auto). The old "#ifndef CANFD: can_data_speed = 0U"
    // fired on every board because CANFD is never defined, zeroing the FD data-phase bitrate on every
    // set_safety_model() -> CAN-FD frames then failed with form/stuff errors and never re-enabled,
    // breaking all CAN-FD cars (e.g. Kia EV6) after fingerprinting. can_data_speed is only used by fdcan.
    can_clear(can_queues[i]);
    (void)can_init(i);
  }
}

void can_set_orientation(bool flipped) {
  bus_config[0].bus_lookup = flipped ? 2U : 0U;
  bus_config[0].can_num_lookup = flipped ? 2U : 0U;
  bus_config[2].bus_lookup = flipped ? 0U : 2U;
  bus_config[2].can_num_lookup = flipped ? 0U : 2U;
}

#ifdef PANDA_JUNGLE
void can_set_forwarding(uint8_t from, uint8_t to) {
  bus_config[from].forwarding_bus = to;
}
#endif

// same checksum Toyota's safety mode validates: folds in the address and the length, so a
// same-addressed frame from another brand does not satisfy it
static bool toyota_hybrid_gear_checksum_valid(const CANPacket_t *msg, int len) {
  uint8_t checksum = (uint8_t)(msg->addr) + (uint8_t)((unsigned int)(msg->addr) >> 8U) + (uint8_t)(len);
  for (int i = 0; i < (len - 1); i++) {
    checksum += (uint8_t)msg->data[i];
  }
  return checksum == (uint8_t)msg->data[len - 1];
}

void ignition_can_hook(CANPacket_t *msg) {
  if (msg->bus == 0U) {
    int len = GET_LEN(msg);
    const int TESLA_DI_GEAR_P = 1;
    const int TOYOTA_GEAR_P = 32;
    const int TOYOTA_HYBRID_GEAR_P = 0;
    const uint32_t TOYOTA_HYBRID_GEAR_LOCK = 20U;
    static uint32_t toyota_hybrid_gear_lock_cnt = 0U;
    static uint8_t toyota_hybrid_gear_last_ck = 0U;
    static bool toyota_hybrid_gear_ck_varied = false;
    static bool toyota_secoc_seen = false;
    static bool tesla_gear_seen = false;
    static int tesla_gear = TESLA_DI_GEAR_P;
    static int toyota_gear = TOYOTA_GEAR_P;
    static int toyota_hybrid_gear = TOYOTA_HYBRID_GEAR_P;
    static bool toyota_hybrid_gear_seen = false;
    static bool vw_meb_seen = false;
    static bool vw_meb_getriebe_out_of_p = false;
    static bool vw_meb_gateway_out_of_p = false;
    static int prev_counter_vw_meb = -1;

    // GM exception
    if ((msg->addr == 0x1F1U) && (len == 8)) {
      // SystemPowerMode (2=Run, 3=Crank Request)
      ignition_can = (msg->data[0] & 0x2U) != 0U;
      ignition_can_cnt = 0U;
    }

    // Rivian R1S/T GEN1 exception
    if ((msg->addr == 0x152U) && (len == 8)) {
      // 0x152 overlaps with Subaru pre-global which has this bit as the high beam
      int counter = msg->data[1] & 0xFU;  // max is only 14

      static int prev_counter_rivian = -1;
      if ((counter == ((prev_counter_rivian + 1) % 15)) && (prev_counter_rivian != -1)) {
        // VDM_OutputSignals->VDM_EpasPowerMode
        ignition_can = ((msg->data[7] >> 4U) & 0x3U) == 1U;  // VDM_EpasPowerMode_Drive_On=1
        ignition_can_cnt = 0U;
      }
      prev_counter_rivian = counter;
    }

    // Tesla Model 3/Y exception
    if ((msg->addr == 0x221U) && (len == 8)) {
      // 0x221 overlaps with Rivian which has random data on byte 0
      int counter = msg->data[6] >> 4;

      static int prev_counter_tesla = -1;
      if ((counter == ((prev_counter_tesla + 1) % 16)) && (prev_counter_tesla != -1)) {
        // VCFRONT_LVPowerState->VCFRONT_vehiclePowerState
        int power_state = (msg->data[0] >> 5U) & 0x3U;
        bool tesla_in_park = !tesla_gear_seen || (tesla_gear == TESLA_DI_GEAR_P);
        ignition_can = (power_state == 0x3) && !tesla_in_park;  // VEHICLE_POWER_STATE_DRIVE=3
        ignition_can_cnt = 0U;
      }
      prev_counter_tesla = counter;
    }

    if ((msg->addr == 0x118U) && (len == 8)) {
      tesla_gear = (msg->data[2] >> 5) & 0x7;
      tesla_gear_seen = true;
    }

    // Mazda exception
    if ((msg->addr == 0x9EU) && (len == 8)) {
      ignition_can = (msg->data[0] >> 5) == 0x6U;
      ignition_can_cnt = 0U;
    }

    // Toyota/Lexus exception. SecOC hybrids (e.g. Sienna 4th gen) report gear on
    // GEAR_PACKET_HYBRID (0x127); their GEAR_PACKET (0x3BC) does not read Park, so once
    // the hybrid gear packet is seen, don't let 0x3BC override it (Park -> ignition off).
    if ((msg->addr == 0x3BCU) && (len == 8) && !toyota_hybrid_gear_seen) {
      int gear = msg->data[1] & 0x3FU;
      if ((gear == 0) || (gear == 1) || (gear == 8) || (gear == 16) || (gear == 32)) {
        toyota_gear = gear;
        ignition_can = toyota_gear != TOYOTA_GEAR_P;
        ignition_can_cnt = 0U;
      }
    }

    // GEAR_PACKET_HYBRID is in four Toyota DBCs, so 0x127 alone would gate every Toyota hybrid.
    // SECOC_SYNCHRONIZATION is broadcast only by the SecOC cars, which are the only ones whose
    // gear is read off 0x127 at all. This narrows the gate, it can never widen it.
    if ((msg->addr == 0xFU) && (len == 8)) {
      toyota_secoc_seen = true;
    }

    // 0x127 is not Toyota exclusive on bus 0: Subaru global hybrid Transmission and Ford CADS
    // MRR_Detection_008 are both 8 byte 0x127, and Subaru carries its gear in the same nibble.
    // Only trust the gear on frames that validate against Toyota's checksum, and only let it
    // gate the harness ignition line after it has held for TOYOTA_HYBRID_GEAR_LOCK frames.
    if ((msg->addr == 0x127U) && (len == 8)) {
      if (toyota_hybrid_gear_checksum_valid(msg, len)) {
        int gear = (msg->data[5] >> 4U) & 0xFU;
        if (gear <= 4) {
          toyota_hybrid_gear_seen = true;
          toyota_hybrid_gear = gear;
          ignition_can = toyota_hybrid_gear != TOYOTA_HYBRID_GEAR_P;
          ignition_can_cnt = 0U;

          // a frame whose payload never moves could satisfy the checksum by coincidence, a live
          // gear source cannot: require the checksum byte to change before trusting the gate
          if ((toyota_hybrid_gear_lock_cnt > 0U) && (msg->data[len - 1] != toyota_hybrid_gear_last_ck)) {
            toyota_hybrid_gear_ck_varied = true;
          }
          toyota_hybrid_gear_last_ck = msg->data[len - 1];

          if (toyota_hybrid_gear_lock_cnt < TOYOTA_HYBRID_GEAR_LOCK) {
            toyota_hybrid_gear_lock_cnt += 1U;
          } else if (toyota_hybrid_gear_ck_varied && toyota_secoc_seen) {
            ignition_can_gates_line = true;
          } else {
            // hold until the payload moves
          }
        }
      } else {
        toyota_hybrid_gear_lock_cnt = 0U;
        toyota_hybrid_gear_ck_varied = false;
      }
    }

    if ((msg->addr == 0xADU) && (len == 8)) {
      int fahrstufe = (msg->data[5] >> 2) & 0xFU;
      vw_meb_getriebe_out_of_p = (fahrstufe >= 6) && (fahrstufe <= 14);
    }

    if ((msg->addr == 0x3DCU) && (len == 8)) {
      int fahrstufe = msg->data[5] & 0xFU;
      vw_meb_gateway_out_of_p = (fahrstufe >= 6) && (fahrstufe <= 14);
    }

    if (((msg->addr == 0xC0U) && (len == 32)) || ((msg->addr == 0x20AU) && (len == 64))) {
      vw_meb_seen = true;
    }

    if ((msg->addr == 0x3C0U) && (len == 4) && vw_meb_seen) {
      int counter = msg->data[1] & 0xFU;
      if ((counter == ((prev_counter_vw_meb + 1) % 16)) && (prev_counter_vw_meb != -1)) {
        bool vw_meb_out_of_park = vw_meb_getriebe_out_of_p || vw_meb_gateway_out_of_p;
        ignition_can = (((msg->data[2] >> 1) & 1U) != 0U) && vw_meb_out_of_park;
        ignition_can_cnt = 0U;
        ignition_can_gates_line = true;
      }
      prev_counter_vw_meb = counter;
    }

    if ((msg->addr == 0x116U) && (len == 6)) {
      const int TESLA_LEGACY_DI_GEAR_LOCK = 3;
      const uint8_t TESLA_LEGACY_DI_GEAR_R = 2U;
      const uint8_t TESLA_LEGACY_DI_GEAR_D = 4U;
      static int prev_counter_tesla_legacy_gear = -1;
      static int tesla_legacy_gear_streak = 0;

      uint8_t checksum = (uint8_t)(0x16U + 0x01U);
      for (int i = 0; i < 5; i++) {
        checksum += (uint8_t)msg->data[i];
      }

      if (checksum == (uint8_t)msg->data[5]) {
        int counter = msg->data[4] & 0xFU;
        if ((prev_counter_tesla_legacy_gear != -1) && (counter == ((prev_counter_tesla_legacy_gear + 1) % 16))) {
          if (tesla_legacy_gear_streak < TESLA_LEGACY_DI_GEAR_LOCK) {
            tesla_legacy_gear_streak += 1;
          }
        } else {
          tesla_legacy_gear_streak = 0;
        }
        prev_counter_tesla_legacy_gear = counter;

        if (tesla_legacy_gear_streak >= TESLA_LEGACY_DI_GEAR_LOCK) {
          const uint8_t gear = (msg->data[1] >> 4) & 0x7U;
          ignition_can = (gear >= TESLA_LEGACY_DI_GEAR_R) && (gear <= TESLA_LEGACY_DI_GEAR_D);
          ignition_can_cnt = 0U;
        }
      } else {
        tesla_legacy_gear_streak = 0;
        prev_counter_tesla_legacy_gear = -1;
      }
    }

  }

  if (((msg->bus == 0U) || (msg->bus == 1U)) && (msg->addr == 0x348U) && (GET_LEN(msg) == 8)) {
    int counter = msg->data[6] & 0xFU;

    static int prev_counter_tesla_legacy = -1;
    if ((counter == ((prev_counter_tesla_legacy + 1) % 16)) && (prev_counter_tesla_legacy != -1)) {
      ignition_can = (msg->data[0] & 0x1U) != 0U;
      ignition_can_cnt = 0U;
    }
    prev_counter_tesla_legacy = counter;
  }
}

bool can_tx_check_min_slots_free(uint32_t min) {
  return
    (can_slots_empty(&can_tx1_q) >= min) &&
    (can_slots_empty(&can_tx2_q) >= min) &&
    (can_slots_empty(&can_tx3_q) >= min);
}

uint8_t calculate_checksum(const uint8_t *dat, uint32_t len) {
  uint8_t checksum = 0U;
  for (uint32_t i = 0U; i < len; i++) {
    checksum ^= dat[i];
  }
  return checksum;
}

void can_set_checksum(CANPacket_t *packet) {
  packet->checksum = 0U;
  packet->checksum = calculate_checksum((uint8_t *) packet, CANPACKET_HEAD_SIZE + GET_LEN(packet));
}

bool can_check_checksum(CANPacket_t *packet) {
  return (calculate_checksum((uint8_t *) packet, CANPACKET_HEAD_SIZE + GET_LEN(packet)) == 0U);
}

void can_send(CANPacket_t *to_push, uint8_t bus_number, bool skip_tx_hook) {
  if (skip_tx_hook || safety_tx_hook(to_push) != 0) {
    if (bus_number < PANDA_CAN_CNT) {
      // add CAN packet to send queue
      tx_buffer_overflow += can_push(can_queues[bus_number], to_push) ? 0U : 1U;
      process_can(CAN_NUM_FROM_BUS_NUM(bus_number));
    }
  } else {
    safety_tx_blocked += 1U;
    to_push->returned = 0U;
    to_push->rejected = 1U;

    // data changed
    can_set_checksum(to_push);
    rx_buffer_overflow += can_push(&can_rx_q, to_push) ? 0U : 1U;
  }
}

bool is_speed_valid(uint32_t speed, const uint32_t *all_speeds, uint8_t len) {
  bool ret = false;
  for (uint8_t i = 0U; i < len; i++) {
    if (all_speeds[i] == speed) {
      ret = true;
    }
  }
  return ret;
}
