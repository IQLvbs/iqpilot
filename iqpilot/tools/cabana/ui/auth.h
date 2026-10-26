// Copyright (c) 2026 IQ.Lvbs LLC. All Rights Reserved.
#pragma once

#include <atomic>
#include <string>

std::string authenticateKonn3kt(const std::string &provider, std::atomic<bool> *abort);
