#pragma once

// One dedicated 72-byte TX buffer fits in the otherwise unused shared RAM.
// RX capacity and the normal one-element TX FIFO remain unchanged.
#define FDCAN_SPAS2_NO_OWNER 0xFFU
#define FDCAN_SPAS2_BUFFER_BYTES 72U
#define FDCAN_MESSAGE_RAM_BYTES 10240U
#define FDCAN_NORMAL_BANK_BYTES 3384U
#define FDCAN_NORMAL_RX_BYTES 3312U

_Static_assert((3U * FDCAN_NORMAL_BANK_BYTES) + FDCAN_SPAS2_BUFFER_BYTES <= FDCAN_MESSAGE_RAM_BYTES,
               "SPAS2 mailbox exceeds shared FDCAN RAM");

static inline uint32_t fdcan_layout_rx_offset(uint8_t can_number, uint8_t owner) {
  return ((uint32_t)can_number * FDCAN_NORMAL_BANK_BYTES) +
         (((owner < 3U) && (owner < can_number)) ? FDCAN_SPAS2_BUFFER_BYTES : 0U);
}

static inline uint32_t fdcan_layout_tx_offset(uint8_t can_number, uint8_t owner) {
  return fdcan_layout_rx_offset(can_number, owner) + FDCAN_NORMAL_RX_BYTES;
}

static inline uint32_t fdcan_layout_dedicated_count(uint8_t can_number, uint8_t owner) {
  return ((owner < 3U) && (owner == can_number)) ? 1U : 0U;
}
