#pragma once

#include "board/drivers/spi_declarations.h"

#ifdef STM32H7
__attribute__((section(".sram12"))) uint8_t spi_buf_rx[SPI_BUF_SIZE];
__attribute__((section(".sram12"))) uint8_t spi_buf_tx[SPI_BUF_SIZE];
__attribute__((section(".sram12"))) static uint8_t spi_buf_ready[1];
#else
uint8_t spi_buf_rx[SPI_BUF_SIZE];
uint8_t spi_buf_tx[SPI_BUF_SIZE];
static uint8_t spi_buf_ready[1];
#endif

#define SPI_SLAVE_READY 0x3CU
#define SPI_ACK 0xC3U
#define SPI_NACK 0x5AU
#define SPI_IDLE 0x00U

typedef struct {
  uint8_t endpoint;
  uint32_t id;
  uint16_t tx_len;
  uint16_t rx_len;
} __attribute__((packed)) spi_req_header_t;

typedef struct {
  uint8_t status;
  uint32_t id;
  uint16_t len;
} __attribute__((packed)) spi_resp_header_t;

#define SPI_CRC_SIZE 4U
#define SPI_RESP_OVERHEAD (sizeof(spi_resp_header_t) + SPI_CRC_SIZE)

#define SPI_ENDPOINT_INFO 0xF0U

uint16_t spi_error_count = 0;

void llspi_init(void);
void llspi_queue(const uint8_t *tx, uint16_t tx_len);
uint16_t llspi_rx_count(void);

static bool spi_can_tx_ready = false;

static bool spi_handle_endpoint(uint8_t endpoint, const uint8_t *data, uint16_t data_len, uint16_t max_resp_len,
                                uint8_t *resp, uint16_t *resp_len) {
  bool ack = false;
  *resp_len = 0U;

  if (endpoint == 0U) {
    if (data_len >= sizeof(ControlPacket_t)) {
      ControlPacket_t ctrl = {0};
      (void)memcpy((uint8_t*)&ctrl, data, sizeof(ControlPacket_t));
      *resp_len = (uint16_t)comms_control_handler(&ctrl, resp);
      ack = true;
    }
  } else if ((endpoint == 1U) || (endpoint == 0x81U)) {
    *resp_len = (uint16_t)comms_can_read(resp, max_resp_len);
    ack = true;
  } else if (endpoint == 2U) {
    comms_endpoint2_write(data, data_len);
    ack = true;
  } else if (endpoint == 3U) {
    if (spi_can_tx_ready) {
      spi_can_tx_ready = false;
      comms_can_write(data, data_len);
      ack = true;
    }
  } else if (endpoint == SPI_ENDPOINT_INFO) {
    (void)memcpy(resp, ((uint8_t *)UID_BASE), 12);
    resp[12] = hw_type;
    resp[13] = USB_PID & 0xFFU;
    *resp_len = 14U;
    ack = true;
  } else if (endpoint == 0xABU) {
    // test endpoint: mimics panda -> device transfer
    *resp_len = max_resp_len;
    ack = true;
  } else {
  }

  return ack;
}

static uint16_t spi_process_request(uint16_t n) {
  static bool handled = false;
  static uint32_t handled_id = 0U;
  static uint32_t handled_crc = 0U;

  spi_req_header_t req;
  (void)memcpy((uint8_t *)&req, spi_buf_rx, sizeof(req));
  uint32_t req_len = sizeof(req) + (uint32_t)req.tx_len + SPI_CRC_SIZE;
  uint32_t crc = 0U;
  if (req_len <= n) {
    (void)memcpy((uint8_t *)&crc, &spi_buf_rx[req_len - SPI_CRC_SIZE], SPI_CRC_SIZE);
  }
  bool valid = (req_len <= n) && (crc32(spi_buf_rx, req_len - SPI_CRC_SIZE) == crc) &&
               (req.rx_len >= SPI_RESP_OVERHEAD) && (req.rx_len <= SPI_BUF_SIZE);

  if (valid && !(handled && (req.id == handled_id) && (crc == handled_crc))) {
    uint16_t max_data_len = req.rx_len - SPI_RESP_OVERHEAD;
    uint16_t data_len = 0U;
    bool ack = spi_handle_endpoint(req.endpoint, &spi_buf_rx[sizeof(req)], req.tx_len, max_data_len,
                                   &spi_buf_tx[sizeof(spi_resp_header_t)], &data_len);
    data_len = ack ? MIN(data_len, max_data_len) : 0U;
    spi_resp_header_t resp = {
      .status = ack ? SPI_ACK : SPI_NACK,
      .id = req.id,
      .len = data_len,
    };
    (void)memcpy(spi_buf_tx, (uint8_t *)&resp, sizeof(resp));
    uint32_t len = sizeof(resp) + resp.len;
    uint32_t resp_crc = crc32(spi_buf_tx, len);
    (void)memcpy(&spi_buf_tx[len], (uint8_t *)&resp_crc, SPI_CRC_SIZE);
    handled = true;
    handled_id = req.id;
    handled_crc = crc;
  } else if (!valid && (req_len <= n)) {
    spi_error_count += 1U;
  } else {
  }
  return valid ? req.rx_len : 0U;
}

void spi_cs_rising(void) {
  static bool response_queued = false;
  static uint16_t resp_len = 0U;

  bool send_response = response_queued;
  uint16_t n = llspi_rx_count();
  if (n > 0U) {
    if (response_queued) {
      send_response = false;
    } else {
      resp_len = spi_process_request(n);
      send_response = resp_len > 0U;
    }
  }

  if (send_response) {
    llspi_queue(spi_buf_tx, resp_len);
    response_queued = true;
  } else {
    llspi_queue(spi_buf_ready, 1U);
    response_queued = false;
  }
}

void spi_init(void) {
  crc32_init();
  llspi_init();

  spi_buf_ready[0] = SPI_SLAVE_READY;
  llspi_queue(spi_buf_ready, 1U);
}

void can_tx_comms_resume_spi(void) {
  spi_can_tx_ready = true;
}
