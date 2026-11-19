#pragma once

#include "main_declarations.h"

// ********************* Globals **********************
uint8_t hw_type = 0;
board *current_board;
uint32_t uptime_cnt = 0;

// ADC results, sampled in thread context (see tick_sample_poll in main.c)
uint32_t voltage_mV = 0;
uint32_t current_mA = 0;

// heartbeat state
uint32_t heartbeat_counter = 0;
bool heartbeat_lost = false;
bool heartbeat_disabled = false;            // set over USB

// siren state
bool siren_enabled = false;
