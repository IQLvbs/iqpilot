#pragma once

// The SPI slave must re-arm its RX DMA at every protocol turnaround before the
// master clocks the next phase. Without preemption that re-arm waits behind any
// in-flight handler (CAN RX under bus load), the master clocks into an unarmed
// peripheral, and the transfer fails its checksum -> NACK retry storms.
#define IRQ_PRIORITY_COMMS 0U
#define IRQ_PRIORITY_DEFAULT 2U

typedef struct interrupt {
  void (*handler)(void);
  uint32_t call_counter;
  uint32_t call_rate;
  uint32_t max_call_rate;   // Call rate is defined as the amount of calls each second
  uint32_t call_rate_fault;
} interrupt;

void interrupt_timer_init(void);
uint32_t microsecond_timer_get(void);
void unused_interrupt_handler(void);

extern interrupt interrupts[NUM_INTERRUPTS];

#define REGISTER_INTERRUPT(irq_num, func_ptr, call_rate_max, rate_fault) \
  interrupts[irq_num].handler = (func_ptr);  \
  interrupts[irq_num].call_counter = 0U;   \
  interrupts[irq_num].call_rate = 0U;   \
  interrupts[irq_num].max_call_rate = (call_rate_max); \
  interrupts[irq_num].call_rate_fault = (rate_fault);

extern float interrupt_load;

void handle_interrupt(IRQn_Type irq_type);
// Every second
void interrupt_timer_handler(void);
void init_interrupts(bool check_rate_limit);
