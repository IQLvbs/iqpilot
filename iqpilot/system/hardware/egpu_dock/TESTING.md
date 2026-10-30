# eGPU dock bring-up runbook

Our flasher is a port of comma's known-working one, byte-identical firmware
bundle, but it has never touched real hardware. Order matters: everything
read-only first, evidence at every step.

Run everything as root from the repo root on the device, dock on the USB-C
port, car ignition off.

## 1. Read-only probe (safe, run first, share the output)

    sudo python3 iqpilot/system/hardware/egpu_dock/dock_probe.py

Expected on a dock previously flashed by stock openpilot: product matches the
bundled `custom ed4e39b7-CLEAN`, USB3 speed, PCIe link L0, stable config read.
Any other result: stop and send the output before proceeding.

## 2. Flash-path validation (writes, but writes the same bytes)

A stock-flashed dock already runs our exact bundled firmware, so the
no-op path proves version detection:

    sudo python3 iqpilot/system/hardware/egpu_dock/flash.py

Expected: "firmware matches" and no write. Then exercise the full write path
by reflashing the identical image:

    sudo python3 iqpilot/system/hardware/egpu_dock/flash.py --force

This backs up the per-unit config page to /data/egpu_dock_config/ first and
verifies every sector; identical bytes make it the lowest-risk possible
full-path test. Re-run step 1 after; product string and config sha must be
unchanged.

## 3. Runtime

Set `IQEgpuEnabled`, go onroad (bench is fine), and confirm iqegpumodeld
downloads/compiles and the selector reports UsbGpu* status. The runtime gate
requires the exact bundled firmware product string, so a dock that failed
step 2 will be treated as absent by design.

## If anything goes wrong

The dock falling back to the ROM bootloader (product "USB 3.2 PCIe
TinyEnclosure" or AS2462*) is recoverable: flash.py handles ROM recovery, and
the config backup from step 2 is on disk. Do not improvise register writes;
capture output and stop.
