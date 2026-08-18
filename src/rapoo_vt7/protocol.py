VID = 0x24AE
PID = 0x1413          # 2.4G wireless receiver
PID_USB = 0x4613      # mouse connected directly via USB cable

# Report IDs of the configuration interface (hidraw interface 1):
#   rid 6  -> command output report (input 32B + output 32B, usage 0xFF00:0x0E)
#   rid 7  -> passive report (battery, connection, DPI, rate) sent by the mouse
#   rid 8  -> feature report (reply in WebHID; on hidraw the reply comes on input 6)
REPORT_CMD = 6
REPORT_PASSIVE = 7
REPORT_FEATURE_RESP = 8

# VT_nrf54L protocol prefix.
# The A Hub recognizes PID 0x1413 as a wireless receiver (map "Je" -> mouse
# 0x4613/VT7), so commands use prefix 0xA5. A direct USB connection of the mouse
# (PID 0x46xx) uses 0xFF.
PREFIX_USB = 0xFF
PREFIX_WIRELESS = 0xA5

# VT_nrf54L protocol command IDs (do NOT receive +32 from Telink)
GET_WORK_MODE = 0xA2            # 162
GET_FIRMWARE = 0xA3             # 163
READ_EEPROM = 0xA4              # 164
WRITE_EEPROM = 0xA5             # 165
FACTORY_UPDATE = 0xA8           # 168
GET_BATTERY_LEVEL = 0xAA        # 170
RETURN_FACTORY_SETTINGS = 0xAD  # 173

# Receiver pairing (A Hub `deviceMatcher`, story 5-3; free 0xA0-0xAF slots).
# Sent to the RECEIVER (prefix 0xA5). 0xA0/0xA1 are DESTRUCTIVE (they alter the
# receiver's pairing state) — no app write path, probe-only behind an Ask First
# gate. 0xA7 is read-only but its reply semantics are unvalidated (🔶).
PAIR_START_MATCH = 0xA0         # enter pairing mode (sub-arg 0x81)
PAIR_WRITE_RF = 0xA1            # write the 4-byte RF address (sub-arg 0x8F)
PAIR_GET_RESULT = 0xA7          # read the match result (0 = failed; other 🔶)
PAIR_MATCH_SUB = 0x81           # sendStartMatch payload byte
PAIR_WRITE_RF_SUB = 0x8F        # sendWriteRF payload byte (followed by 4 RF bytes)

# Reply via input report 6: data[0] == 0x01 indicates a valid response/ACK.
# Reports with data[0] == 0x00 are "empty" (mouse asleep / heartbeat).
RESP_ACK = 0x01
RESP_EMPTY = 0x00

# get_battery_level (0xAA) -> raw reply "06 01 <status> <battery%> ...":
#   data[0] = report id (0x06)
#   data[1] = ACK (0x01)
#   data[2] = battery status (0 invalid, 1 ok, 2 charging)
#   data[3] = level 0-100
BATTERY_STATUS_INVALID = 0
BATTERY_STATUS_OK = 1
BATTERY_STATUS_CHARGING = 2
BATTERY_OFFSET_STATUS = 2
BATTERY_OFFSET_LEVEL = 3

# Passive report (rid 7): indexes of the RAW report (byte 0 = rid 0x07):
#   data[1] low nibble = mode (0 2.4G, 1 BT, 2 USB), high nibble = sensorType;
#   data[2]=DPI gear; data[3..4]/[5..6]=dpiX/dpiY LE; data[7]=battery status;
#   data[8]=battery%; data[9]=blMode, data[10]=rpt_24g, data[11]=rpt_usb, data[12]=config.
MODE_WIRELESS = 0
MODE_BT = 1
MODE_USB = 2
MODE_NAMES = {MODE_WIRELESS: "2.4G", MODE_BT: "Bluetooth", MODE_USB: "USB"}

# Passive report (rid 7) field offsets of the RAW report (byte 0 = rid 0x07).
R7_MODE = 1                # low nibble = connect type (0 2.4G, 1 BT, 2 USB)
R7_DPI_GEAR = 2            # DPI gear/index
R7_DPI_X = 3               # dpiX, 2 bytes LE
R7_DPI_Y = 5               # dpiY, 2 bytes LE
R7_BATTERY_STATUS = 7      # 0/1/2
R7_BATTERY_LEVEL = 8       # %
R7_BL_MODE = 9
# NOTE: R7_RPT_USB is the trusted source for the active polling-rate slot:
# it mirrors the rateCode of MOUSE_REPORT (0x0880) and maps to a slot 0..6 via
# performance.rate_index_from_code(). R7_RPT_24G is NOT a rate code on this
# device (observed constant) — it must never be used for active-slot selection.
R7_RPT_24G = 10            # 2.4G rate byte — not a rate code; do not use for slot detection
R7_RPT_USB = 11            # USB polling rate code mirror (rateCode from 0x0880)
R7_CONFIG = 12

# read_eeprom (0xA4) -> raw reply "06 01 <overhead> <data>":
#   the data read starts at data[5] (in WebHID, without report id, it would be data[4])
EEPROM_DATA_OFFSET = 5

# get_work_mode (0xA2): mode in data[2] (raw)
WORK_MODE_OFFSET = 2

# get_firmware (0xA3): version = data[2].minor, data[3].major (raw)
FIRMWARE_OFFSET_MINOR = 2
FIRMWARE_OFFSET_MAJOR = 3

# VT_nrf54L EEPROM addresses (A Hub table "yh"), 2 bytes little-endian.
# _3(offset) generates 8 addresses (one per bank 0x0600/0x0A00/.../0x2200); most
# fields use bank 0. Useful for Phase 2 (DPI).
EEPROM_BANKS = (0x0600, 0x0A00, 0x0E00, 0x1200, 0x1600, 0x1A00, 0x1E00, 0x2200)
EEPROM_BANK0_BASE = 0x0600
EEPROM_BANK0_END = 0x0A00
EEPROM_READ_MAX = 24           # firmware limit per read_eeprom/write_eeprom call

EEPROM_CURRENT_CONNECT_PROTOCOL = (0x04, 0x01)
EEPROM_CONFIG_CURRENT = (0x0C, 0x01)
EEPROM_RF_PROTOCOL_SETTING = (0x60, 0x00)

# Receiver-pairing connected-mouse poll (A Hub BaseSetting
# `getConnectedMouseVid`/`getConnectedMousePid`, 2026-08-16): read_eeprom 2 B
# LE at these raw addresses reports the mouse the receiver is paired to
# (0x24AE VID / 0x4613 PID when attached; 0 = none). These are absolute
# addresses passed straight to read_eeprom, NOT bank-0 offsets.
CONNECTED_MOUSE_VID_ADDR = (0x00, 0x00)
CONNECTED_MOUSE_PID_ADDR = (0x04, 0x00)

# "Double-byte" (2-byte LE) addresses of the main fields in bank 0.
# 0 = MOUSE_LEFT ... (see docs/rapoo_hub_app.js -> table "yh")
MOUSE_DPI_CUR = 0x0298          # current DPI index (bank 0 = 0x0600+0x0298)
MOUSE_DPI_X_LIST = 0x0288       # DPI X table
MOUSE_DPI_Y_LIST = 0x02C8       # DPI Y table
MOUSE_DPI_ENABLE_GEAR = 0x0296  # enable/disable the DPI gear system
MOUSE_DPI_GEAR_LENGTH = 7       # bundle constant: max number of gears

# Buttons (docs/FEATURES.md D): absolute 0x0600-0x0638
MOUSE_LEFT = 0x0000             # 0x0600
MOUSE_MID = 0x0004              # 0x0604 middle
MOUSE_RIGHT = 0x0008            # 0x0608
MOUSE_CPIADD = 0x000C           # 0x060C DPI+
MOUSE_CPIREDUCE = 0x0010        # 0x0610 DPI-
MOUSE_FORWARD = 0x0014          # 0x0614
MOUSE_BACK = 0x0018             # 0x0618
MOUSE_ROLLFORWARD = 0x0024      # 0x0624 scroll forward
MOUSE_ROLLBACK = 0x0028         # 0x0628 scroll back
MOUSE_ROLLRIGHT = 0x002C        # 0x062C scroll right
MOUSE_ROLLLEFT = 0x0030         # 0x0630 scroll left
MOUSE_BOTTOM = 0x0034           # 0x0634 bottom button
MOUSE_BLE = 0x0038              # 0x0638 BLE switch

# Performance / sensor (docs/FEATURES.md B)
MOUSE_REPORT = 0x0280           # 0x0880
MOUSE_SCAN = 0x0281             # 0x0881
MOUSE_SLIGHT = 0x0284           # 0x0884 (lift-off height?)
MOUSE_MOTION = 0x0285           # 0x0885 motion sync (on/off)
SENSOR_MODE = 0x02DC            # 0x08DC performance mode (0..5)

# RF strategy 0x08D8 shares its byte with the low-power warning switch.
# The byte is a bit mask: bit 0 = RF strengthen (0 adaptive/smart, 1 maximum
# RF) and bit 1 = low-battery light warning (0 off, 1 on). Per-field writes
# must use a masked write and preserve the unrelated bits.
RF_STRENGTHEN_SWITCH = 0x02D8   # 0x08D8 smart/full RF (bit mask, bit 0)
LOW_POWE_WARN_SWITCH = 0x02D8   # 0x08D8 low battery warning (same byte, bit 1)
RF_STRENGTHEN_MASK = 0x01
LOW_POWE_WARN_MASK = 0x02

# Mouse parameters (docs/FEATURES.md C)
MOUSE_DOWNDELAY = 0x02C0        # 0x08C0 press debounce
MOUSE_LIFTDELAY = 0x02C1        # 0x08C1 release debounce
MOUSE_SLEEPTIME = 0x02C2        # 0x08C2 sleep time
MOUSE_LINEAR_RIPPLE = 0x02C3    # 0x08C3 linear correction
MOUSE_SENSORANGLE = 0x02C4      # 0x08C4 sensor angle
MOUSE_GLASS = 0x02C5            # 0x08C5 glass tracking
MOUSE_LOWPOWER = 0x02C6         # 0x08C6 low power
MOUSE_POWERSAVE = 0x02AC        # 0x08AC power save
MOUSE_DCSWITCH = 0x02DA         # 0x08DA DC switch

# System (docs/FEATURES.md E)
CONFIG_NAME = 0x03EC            # 0x09EC device name (16 bytes)

# RGB/lighting (docs/FEATURES.md F — documented, not applicable to the VT7:
# the product has no lightModes). Registered so the registry covers §2 fully.
MOUSE_LIGHTMOD = 0x0299         # 0x0899 RGB lighting mode
MOUSE_LIGHTRGB = 0x02B8         # 0x08B8 RGB color


def eeprom_bank0(offset):
    if not (0 <= offset < EEPROM_BANK0_END - EEPROM_BANK0_BASE):
        raise ValueError("offset outside bank0")
    return [
        (EEPROM_BANK0_BASE + offset) & 0xFF,
        (EEPROM_BANK0_BASE + offset) >> 8,
    ]
