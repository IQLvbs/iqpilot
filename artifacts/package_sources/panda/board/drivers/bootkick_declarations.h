#pragma once

extern bool bootkick_reset_triggered;
extern bool bootkick_reset_requested;

void bootkick_tick(bool ignition, bool recent_heartbeat);
void bootkick_request_reset(void);
