#pragma once

#include "board/crc.h"

#define SPI_TIMEOUT_US 10000U

// got max rate from hitting a non-existent endpoint
// in a tight loop, plus some buffer
#define SPI_IRQ_RATE  16000U

#define SPI_BUF_SIZE 4096U
extern uint8_t spi_buf_rx[SPI_BUF_SIZE];
extern uint8_t spi_buf_tx[SPI_BUF_SIZE];

extern uint16_t spi_error_count;

void llspi_init(void);
void llspi_queue(const uint8_t *tx, uint16_t tx_len);
uint16_t llspi_rx_count(void);
void can_tx_comms_resume_spi(void);
void spi_init(void);
void spi_cs_rising(void);
