# Wiring Guide

This project has two microcontroller sketches:

- `esp32_dashboard/esp32_dashboard.ino`
- `arudino.ino`

They speak the same serial protocol to the dashboard, but the wiring is different.

## What The Firmware Expects

Both versions expect these external parts:

- 1 hall-effect sensor for wheel or motor pulse counting
- 1 momentary pushbutton for start/stop
- 1 GPS module running at `9600` baud UART
- microSD storage
- either an onboard ESP32 microSD slot or an external SPI microSD module
- 1 USB connection to the computer or Pi running the dashboard

Important behavior from the code:

- The hall input uses `INPUT_PULLUP` and counts on a `FALLING` edge.
- The start/stop button uses `INPUT_PULLUP` and is considered pressed when the pin is pulled to `GND`.
- The dashboard serial link runs at `115200`.
- GPS serial runs at `9600`.

## ESP32 Wiring

Source: `esp32_dashboard/esp32_dashboard.ino`

The ESP32 sketch now supports two storage backends:

- `STORAGE_BACKEND_SD_SPI` for an external SPI microSD adapter
- `STORAGE_BACKEND_SD_MMC` for an onboard microSD slot

To use the onboard slot, change this line near the top of `esp32_dashboard/esp32_dashboard.ino`:

```cpp
#define STORAGE_BACKEND STORAGE_BACKEND_SD_MMC
```

### ESP32 With Onboard microSD Slot

If your ESP32 board already has a built-in microSD slot, you do not wire a separate SD adapter.

Use:

- the board's built-in card slot
- the board's built-in SD wiring
- the `STORAGE_BACKEND_SD_MMC` setting in the sketch

What still needs to be wired externally:

- hall sensor to `GPIO25`
- start/stop button to `GPIO27` and `GND`
- GPS to `GPIO16` and `GPIO17`
- USB to the dashboard host

Important limitation:

- the exact onboard microSD wiring depends on the specific ESP32 board
- `SD_MMC` only works if the board's slot is actually connected to the ESP32 in a way supported by that board definition
- if your board does not expose a working onboard SD slot through `SD_MMC`, you must either adapt the sketch to that board's pinout or keep using SPI mode

### ESP32 With External SPI microSD Adapter

### Pin Map

| Function | ESP32 Pin | Notes |
|---|---:|---|
| Hall sensor output | `GPIO25` | Input with pull-up, active-low pulse |
| Start/stop button | `GPIO27` | Wire button to ground |
| GPS TX -> ESP32 RX | `GPIO16` | UART2 RX |
| GPS RX <- ESP32 TX | `GPIO17` | UART2 TX, often optional |
| SD SCK | `GPIO18` | SPI clock |
| SD MISO | `GPIO19` | SPI MISO |
| SD MOSI | `GPIO23` | SPI MOSI |
| SD CS | `GPIO5` | SPI chip select |
| USB to dashboard host | USB port | Serial at `115200` |
| Ground | `GND` | All modules must share ground |
| Power | `3V3` or `5V` depending on module | See notes below |

### ESP32 Connection Table

| Module pin | Connect to |
|---|---|
| Hall sensor `OUT` | `GPIO25` |
| Hall sensor `GND` | `GND` |
| Hall sensor `VCC` | Module-rated supply |
| Button leg 1 | `GPIO27` |
| Button leg 2 | `GND` |
| GPS `TX` | `GPIO16` |
| GPS `RX` | `GPIO17` if used |
| GPS `GND` | `GND` |
| GPS `VCC` | Module-rated supply |
| SD `SCK` | `GPIO18` |
| SD `MISO` | `GPIO19` |
| SD `MOSI` | `GPIO23` |
| SD `CS` | `GPIO5` |
| SD `GND` | `GND` |
| SD `VCC` | Module-rated supply |

### ESP32 ASCII Layout

```text
ESP32                    Module
-----                    -------------------------
GPIO25  ---------------> Hall sensor OUT
GPIO27  ----button-----> GND
GPIO16  <--------------- GPS TX
GPIO17  ---------------> GPS RX   (optional on some GPS boards)
GPIO18  ---------------> SD SCK
GPIO19  <--------------- SD MISO
GPIO23  ---------------> SD MOSI
GPIO5   ---------------> SD CS
GND     ---------------- Hall GND / GPS GND / SD GND
USB     ---------------- Dashboard host
```

### ESP32 Power Notes

- Use a GPS module that is safe with `3.3V` logic on its serial pins.
- Do not drive `GPIO16` with a raw `5V` GPS TX line.
- Many ESP32 dev boards can power a GPS breakout from `3V3`.
- SD cards are `3.3V` devices. Use an SD breakout that is compatible with ESP32 logic and power.

## Arduino Wiring

Source: `arudino.ino`

This sketch looks like it was written for an Arduino with:

- standard hardware SPI
- `SoftwareSerial` on pins `8` and `9`
- interrupt-capable pin `2`

That lines up well with an Uno or Nano style board.

### Pin Map

| Function | Arduino Pin | Notes |
|---|---:|---|
| Hall sensor output | `D2` | Interrupt input, active-low pulse |
| Start/stop button | `D4` | Wire button to ground |
| Status LED | `D7` | Optional external LED |
| GPS RX from module TX | `D8` | `SoftwareSerial` RX |
| GPS TX to module RX | `D9` | `SoftwareSerial` TX |
| SD CS | `D10` | SPI chip select |
| SD MOSI | `D11` on Uno/Nano | Hardware SPI |
| SD MISO | `D12` on Uno/Nano | Hardware SPI |
| SD SCK | `D13` on Uno/Nano | Hardware SPI |
| USB to dashboard host | USB port | Serial at `115200` |
| Ground | `GND` | All modules must share ground |

### Arduino Connection Table

| Module pin | Connect to |
|---|---|
| Hall sensor `OUT` | `D2` |
| Hall sensor `GND` | `GND` |
| Hall sensor `VCC` | Module-rated supply |
| Button leg 1 | `D4` |
| Button leg 2 | `GND` |
| LED anode | `D7` through resistor |
| LED cathode | `GND` |
| GPS `TX` | `D8` |
| GPS `RX` | `D9` if used |
| GPS `GND` | `GND` |
| GPS `VCC` | Module-rated supply |
| SD `CS` | `D10` |
| SD `MOSI` | `D11` on Uno/Nano |
| SD `MISO` | `D12` on Uno/Nano |
| SD `SCK` | `D13` on Uno/Nano |
| SD `GND` | `GND` |
| SD `VCC` | Module-rated supply |

## Sensor And Switch Details

### Hall Sensor

The code expects the input to idle high and pulse low:

- Good fit: open-collector or open-drain hall output that sinks to ground
- Also works: digital hall modules that pull output low on trigger

If your sensor outputs the opposite polarity, the count behavior will be wrong unless you change the sketch.

### Start/Stop Button

Wire a simple normally-open pushbutton:

- one side to the input pin
- one side to `GND`

Do not add an external pull-up unless you have a reason. The sketch already enables the internal pull-up.

## Host Connection

The dashboard app talks to the microcontroller over USB serial:

- baud: `115200`
- default host port in the Python app: `/dev/ttyACM0`

If you run the dashboard on Windows, you will likely need to set `ELECTRATHON_PORT` to a `COM` port.

## Bring-Up Checklist

1. Wire all module grounds together.
2. Connect the board to the host over USB.
3. Insert a formatted SD card.
4. Open the serial monitor at `115200`.
5. Confirm you see `SD:READY`.
6. Wait for GPS output such as `GPS:...` or `GPS:NOFIX`.
7. Press the button and confirm `LOG:1` and a `RACEFILE:Rxxxxxx.CSV` message.
8. Trigger the hall sensor and confirm `COUNT:` increases.

## Practical Notes

- The ESP32 sketch does not use the separate external LED that the Arduino sketch uses on `D7`.
- The dashboard calculates RPM using `MAGNETS_PER_REV` from `config.py`. If you use more than one magnet, set that value correctly.
- If your GPS module only needs one data wire, you can usually leave the module `RX` unconnected and still read position data.
- When using an onboard ESP32 microSD slot, the SD wiring is internal to the board, so the external SD rows in the ESP32 tables do not apply.
