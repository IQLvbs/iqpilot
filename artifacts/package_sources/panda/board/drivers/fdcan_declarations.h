#pragma once

#include "board/can.h"

typedef struct {
  volatile uint32_t header[2];
  volatile uint32_t data_word[CANPACKET_DATA_SIZE_MAX/4U];
} canfd_fifo;

extern FDCAN_GlobalTypeDef *cans[PANDA_CAN_CNT];

#define CAN_ACK_ERROR 3U

void can_clear_send(FDCAN_GlobalTypeDef *FDCANx, uint8_t can_number);
void update_can_health_pkt(uint8_t can_number, uint32_t ir_reg);

void process_can(uint8_t can_number);
void can_rx(uint8_t can_number);
bool can_init(uint8_t can_number);

void fdcan_spas2_layout_begin(void);
void fdcan_spas2_layout_end(void);
bool fdcan_spas2_route(const CANPacket_t *packet, uint8_t bus_number, bool forwarded);
void fdcan_spas2_poll(void);
void fdcan_spas2_orientation_changing(void);
