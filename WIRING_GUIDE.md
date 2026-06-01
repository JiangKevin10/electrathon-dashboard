# Wiring Guide

This project has two microcontroller sketches:

- `esp32_dashboard/esp32_dashboard.ino`
- `arudino.ino`

They speak the same serial protocol to the dashboard, but the wiring is different.

## What The Firmware Expects

Both versions expect these external parts:

- 1 hall-effect sensor for wheel or motor pulse counting
- 1 momentary pushbutton for start/stop
- 1 `ATGM336H` GPS module or equivalent running at `9600` baud UART
- optional `GY-BNO08X` breakout with a `BNO08X`-family IMU on SPI if you want it installed now
- microSD storage
- either an onboard ESP32 microSD slot or an external SPI microSD module
- 1 USB connection to the computer or Pi running the dashboard

Important behavior from the code:

- The hall input uses `INPUT_PULLUP` and counts on a `FALLING` edge.
- The start/stop button uses `INPUT_PULLUP` and is considered pressed when the pin is pulled to `GND`.
- The dashboard serial link runs at `115200`.
- GPS serial runs at `9600`.
- The current sketches can publish `IMU:` heading and yaw-rate data over serial when built with the `SparkFun BNO08x Arduino Library` and a working SPI-wired sensor is present.
- If the IMU is absent, miswired, or the library is not installed, the sketches report `IMU:NOIMU`.

## Module Notes

This build is using:

- `ATGM336H` as the UART GPS module
- `GY-BNO08X` as the SPI IMU breakout

For the wiring tables below:

- treat the `ATGM336H` like a normal UART GPS using `TX`, `RX`, `GND`, and power
- install the `SparkFun BNO08x Arduino Library` in the Arduino IDE if you want the sketches to talk to the IMU
- on the pictured `GY-BNO08X`, the SPI labels are usually:
  `SCL` = `SCK`, `SDA` = `MISO`, `ADO` = `MOSI`
- for SPI mode, tie `PS0` high and `PS1` high at reset
- the current firmware uses the breakout's `CS`, `INT`, and `RST` pins
- power the breakout from `3V3` unless the exact board documentation explicitly says its `VCC` input is higher-voltage tolerant

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
- optional SD activity LED to `GPIO26` and `GND`
- `ATGM336H` GPS to `GPIO17` and `GPIO16`
- optional `GY-BNO08X` IMU to the shared SPI bus on `GPIO18`, `GPIO19`, and `GPIO23`, plus `GPIO14`, `GPIO33`, and `GPIO32`
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
| SD activity LED | `GPIO26` | Optional external LED, lights during SD card access |
| ATGM336H TX -> ESP32 RX | `GPIO17` | UART2 RX |
| ATGM336H RX <- ESP32 TX | `GPIO16` | UART2 TX, often optional |
| GY-BNO08X SCK (`SCL`) | `GPIO18` | Shared SPI clock |
| GY-BNO08X MISO (`SDA`) | `GPIO19` | Shared SPI MISO |
| GY-BNO08X MOSI (`ADO`) | `GPIO23` | Shared SPI MOSI |
| GY-BNO08X CS | `GPIO14` | IMU chip select |
| GY-BNO08X INT | `GPIO33` | IMU interrupt |
| GY-BNO08X RST | `GPIO32` | IMU reset |
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
| LED anode | `GPIO26` through `220 ohm` to `330 ohm` resistor |
| LED cathode | `GND` |
| ATGM336H `TX` | `GPIO17` |
| ATGM336H `RX` | `GPIO16` if used |
| ATGM336H `GND` | `GND` |
| ATGM336H `VCC` | Module-rated supply |
| GY-BNO08X `SCL` | `GPIO18` |
| GY-BNO08X `SDA` | `GPIO19` |
| GY-BNO08X `ADO` | `GPIO23` |
| GY-BNO08X `CS` | `GPIO14` |
| GY-BNO08X `INT` | `GPIO33` |
| GY-BNO08X `RST` | `GPIO32` |
| GY-BNO08X `PS0` | `3V3` |
| GY-BNO08X `PS1` | `3V3` |
| GY-BNO08X `GND` | `GND` |
| GY-BNO08X `VCC` | `3V3` unless your exact breakout documentation explicitly allows a higher input voltage |
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
GPIO26  ----resistor---> LED anode
GND     ---------------- LED cathode
GPIO17  <--------------- ATGM336H TX
GPIO16  ---------------> ATGM336H RX   (optional on some GPS boards)
GPIO18  ---------------> SD SCK
GPIO19  <--------------- SD MISO
GPIO23  ---------------> SD MOSI
GPIO5   ---------------> SD CS
GPIO18  ---------------> GY-BNO08X SCL / SCK
GPIO19  <--------------- GY-BNO08X SDA / MISO
GPIO23  ---------------> GY-BNO08X ADO / MOSI
GPIO14  ---------------> GY-BNO08X CS
GPIO33  <--------------- GY-BNO08X INT
GPIO32  ---------------> GY-BNO08X RST
3V3     ---------------- GY-BNO08X VCC / PS0 / PS1
GND     ---------------- Hall GND / GPS GND / GY-BNO08X GND / SD GND
USB     ---------------- Dashboard host
```

### ESP32 Power Notes

- Use an `ATGM336H` breakout that is safe with `3.3V` logic on its serial pins.
- Do not drive `GPIO17` with a raw `5V` GPS TX line.
- Many ESP32 dev boards can power an `ATGM336H` breakout from `3V3`.
- The BNO08X silicon is a `3.3V`-class device. On a generic `GY-BNO08X` board, do not assume `VCC` is `5V` safe unless the exact breakout documentation says so.
- The IMU and external SD adapter share the same SPI clock and data lines. They must each have their own chip-select pin.
- SD cards are `3.3V` devices. Use an SD breakout that is compatible with ESP32 logic and power.

## Arduino Wiring

Source: `arudino.ino`

This sketch looks like it was written for an Arduino with:

- standard hardware SPI
- `SoftwareSerial` on pins `8` and `9`
- interrupt-capable pin `2`
- optional `GY-BNO08X` on the board's hardware SPI pins plus dedicated `CS`, `INT`, and `RST`

That lines up well with an Uno or Nano style board.

### Pin Map

| Function | Arduino Pin | Notes |
|---|---:|---|
| Hall sensor output | `D2` | Interrupt input, active-low pulse |
| Start/stop button | `D4` | Wire button to ground |
| Status LED | `D7` | Optional external LED |
| ATGM336H RX from module TX | `D8` | `SoftwareSerial` RX |
| ATGM336H TX to module RX | `D9` | `SoftwareSerial` TX |
| GY-BNO08X SCK (`SCL`) | `D13` on Uno/Nano | Shared SPI clock |
| GY-BNO08X MISO (`SDA`) | `D12` on Uno/Nano | Shared SPI MISO |
| GY-BNO08X MOSI (`ADO`) | `D11` on Uno/Nano | Shared SPI MOSI |
| GY-BNO08X CS | `D6` | IMU chip select |
| GY-BNO08X INT | `D5` | IMU interrupt |
| GY-BNO08X RST | `A0` on Uno/Nano | IMU reset |
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
| ATGM336H `TX` | `D8` |
| ATGM336H `RX` | `D9` if used |
| ATGM336H `GND` | `GND` |
| ATGM336H `VCC` | Module-rated supply |
| GY-BNO08X `SCL` | `D13` on Uno/Nano |
| GY-BNO08X `SDA` | `D12` on Uno/Nano |
| GY-BNO08X `ADO` | `D11` on Uno/Nano |
| GY-BNO08X `CS` | `D6` |
| GY-BNO08X `INT` | `D5` |
| GY-BNO08X `RST` | `A0` on Uno/Nano |
| GY-BNO08X `PS0` | `3V3` |
| GY-BNO08X `PS1` | `3V3` |
| GY-BNO08X `GND` | `GND` |
| GY-BNO08X `VCC` | `3V3` unless your exact breakout documentation explicitly allows a higher input voltage |
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

### GY-BNO08X IMU

The `GY-BNO08X` is now configured for SPI in both sketches:

- install the `SparkFun BNO08x Arduino Library` before compiling
- on the pictured breakout, `SCL` is `SCK`, `SDA` is `MISO`, and `ADO` is `MOSI`
- for SPI mode, tie `PS0` high and `PS1` high
- `CS`, `INT`, and `RST` must be wired
- ESP32 SPI suggestion: `GPIO18` / `GPIO19` / `GPIO23` with `CS=GPIO14`, `INT=GPIO33`, `RST=GPIO32`
- Arduino SPI suggestion: `D13` / `D12` / `D11` with `CS=D6`, `INT=D5`, `RST=A0`
- the sketches publish `IMU:heading_deg,yaw_rate_dps,imu_ok` when the sensor is available, otherwise `IMU:NOIMU`

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
6. If the IMU is wired and the library is installed, confirm you start seeing `IMU:` lines. If not, expect `IMU:NOIMU`.
7. Wait for GPS output such as `GPS:...` or `GPS:NOFIX`.
8. Press the button and confirm `LOG:1` and a `RACEFILE:Rxxxxxx.CSV` message.
9. If you wired the optional ESP32 LED, confirm it lights during SD card activity such as race logging or file transfer.
10. Trigger the hall sensor and confirm `COUNT:` increases.

## Practical Notes

- The ESP32 sketch now supports an optional external SD activity LED on `GPIO26`. If that pin conflicts with your board, change `statusLedPin` near the top of `esp32_dashboard/esp32_dashboard.ino`.
- The dashboard calculates RPM using `MAGNETS_PER_REV` from `config.py`. If you use more than one magnet, set that value correctly.
- If your `ATGM336H` only needs one data wire, you can usually leave the module `RX` unconnected and still read position data.
- On a `5V` Arduino, verify whether the `ATGM336H` module `RX` pin is `5V` tolerant before connecting `D9`; if not, leave it unconnected or level-shift it.
- On a `5V` Uno or Nano, do not drive the `GY-BNO08X` SPI and control pins directly unless your breakout explicitly level-shifts them. Use a `3.3V` MCU or proper level shifting.
- When using an onboard ESP32 microSD slot, the SD wiring is internal to the board, so the external SD rows in the ESP32 tables do not apply.
