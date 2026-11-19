#pragma once

#define SPI_CS_PIN 11U

void spi_cs_rising(void);

void llspi_queue(const uint8_t *tx, uint16_t tx_len) {
  register_clear_bits(&(SPI4->CR1), SPI_CR1_SPE);
  DMA2_Stream2->CR &= ~DMA_SxCR_EN;
  DMA2_Stream3->CR &= ~DMA_SxCR_EN;
  register_clear_bits(&(SPI4->CFG1), SPI_CFG1_RXDMAEN | SPI_CFG1_TXDMAEN);
  for (uint16_t i = 0U; (i < 1000U) && (((DMA2_Stream2->CR & DMA_SxCR_EN) != 0U) || ((DMA2_Stream3->CR & DMA_SxCR_EN) != 0U)); i++) {}

  while ((SPI4->SR & SPI_SR_RXP) != 0U) {
    volatile uint8_t dat = SPI4->RXDR;
    (void)dat;
  }
  SPI4->IFCR = (0x1FFU << 3U);
  DMA2->LIFCR = (0x3DUL << 16U) | (0x3DUL << 22U);

  register_set(&(DMA2_Stream2->M0AR), (uint32_t)spi_buf_rx, 0xFFFFFFFFU);
  DMA2_Stream2->NDTR = SPI_BUF_SIZE;
  register_set(&(DMA2_Stream3->M0AR), (uint32_t)tx, 0xFFFFFFFFU);
  DMA2_Stream3->NDTR = tx_len;

  register_set_bits(&(SPI4->CFG1), SPI_CFG1_RXDMAEN);
  DMA2_Stream2->CR |= DMA_SxCR_EN;
  DMA2_Stream3->CR |= DMA_SxCR_EN;
  register_set_bits(&(SPI4->CFG1), SPI_CFG1_TXDMAEN);
  register_set_bits(&(SPI4->CR1), SPI_CR1_SPE);
}

uint16_t llspi_rx_count(void) {
  for (uint16_t i = 0U; (i < 1000U) && ((SPI4->SR & SPI_SR_RXP) != 0U) && (DMA2_Stream2->NDTR != 0U); i++) {}
  return SPI_BUF_SIZE - DMA2_Stream2->NDTR;
}

static void EXTI15_10_IRQ_Handler(void) {
  if ((EXTI->PR1 & (1UL << SPI_CS_PIN)) != 0U) {
    EXTI->PR1 = (1UL << SPI_CS_PIN);
    if ((GPIOE->IDR & (1UL << SPI_CS_PIN)) != 0U) {
      spi_cs_rising();
    }
  }
}

void llspi_init(void) {
  REGISTER_INTERRUPT(EXTI15_10_IRQn, EXTI15_10_IRQ_Handler, (SPI_IRQ_RATE * 2U), FAULT_INTERRUPT_RATE_SPI)

  register_set(&(DMAMUX1_Channel10->CCR), 83U, 0xFFFFFFFFU);
  register_set(&(DMA2_Stream2->CR), DMA_SxCR_MINC, 0x1E077EFEU);
  register_set(&(DMA2_Stream2->PAR), (uint32_t)&(SPI4->RXDR), 0xFFFFFFFFU);

  register_set(&(DMAMUX1_Channel11->CCR), 84U, 0xFFFFFFFFU);
  register_set(&(DMA2_Stream3->CR), (DMA_SxCR_MINC | DMA_SxCR_DIR_0), 0x1E077EFEU);
  register_set(&(DMA2_Stream3->PAR), (uint32_t)&(SPI4->TXDR), 0xFFFFFFFFU);

  register_set(&(SPI4->IER), 0, 0x3FFU);
  register_set(&(SPI4->CFG1), (7U << SPI_CFG1_DSIZE_Pos), SPI_CFG1_DSIZE_Msk);
  register_set(&(SPI4->UDRDR), SPI_IDLE, 0xFFFFU);
  register_set(&(SPI4->CR2), 0, 0xFFFFU);

  register_set(&(SYSCFG->EXTICR[2]), SYSCFG_EXTICR3_EXTI11_PE, SYSCFG_EXTICR3_EXTI11);
  register_set_bits(&(EXTI->RTSR1), (1UL << SPI_CS_PIN));
  register_set_bits(&(EXTI->IMR1), (1UL << SPI_CS_PIN));
  EXTI->PR1 = (1UL << SPI_CS_PIN);
  NVIC_EnableIRQ(EXTI15_10_IRQn);
}
