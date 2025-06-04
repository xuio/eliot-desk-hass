"""Low-level BLE communication with an Eliot smart desk."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, List, Optional

from bleak import BleakClient, BleakError
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .const import (
    SERVICE_UUID,
    WRITE_CHAR_UUID,
    NOTIFY_CHAR_UUID,
)

_LOGGER = logging.getLogger(__name__)

START_BYTES = (0xF1, 0xF1)
END_BYTE = 0x7E


def _checksum(cmd: int, payload: List[int]) -> int:
    length = len(payload)
    return (cmd + length + sum(payload)) & 0xFF


def make_frame(cmd: int, payload: Optional[List[int]] = None) -> bytes:
    if payload is None:
        payload = []
    frame = list(START_BYTES)
    frame += [cmd, len(payload)]
    frame += payload
    frame.append(_checksum(cmd, payload))
    frame.append(END_BYTE)
    return bytes(frame)


# command frames
MOVE_UP = make_frame(0x01)
MOVE_DOWN = make_frame(0x02)
STOP = make_frame(0x2B)
CONNECT_FRAME = make_frame(0xFE)
QUERY_HEIGHT = make_frame(0x07)

# helper: blank/zero frame appears to prefix most commands in official app
ZERO_FRAME = make_frame(0x00)

# Newly reverse-engineered frames (see packets.txt capture)
#  – cmd 0x1B, payload = [memory_slot, magic] where
#    slot 0x02 → sitting height, magic 0xDA
#    slot 0x03 → standing height, magic 0x06
SIT_PRESET = make_frame(0x1B, [0x02, 0xDA])
STAND_PRESET = make_frame(0x1B, [0x03, 0x06])

# Desk lock / unlock (cmd 0x1F, payload 0x01)
LOCK_FRAME = make_frame(0x1F, [0x01])
UNLOCK_FRAME = LOCK_FRAME  # same frame toggles state, kept for clarity


def decode_height(packet: bytes) -> Optional[int]:
    """Parse height from incoming notification frame.

    Known variants:
      • Desk reply header = F1F1, cmd 0x07 or 0x15, len 0x02, payload = low, high
      • Desk reply header = F2F2, cmd 0x01, len 0x03, payload = high, low, status?
    All frames end with checksum + 0x7E terminator.
    """

    if len(packet) < 7 or packet[-1] != END_BYTE:
        return None

    header1, header2, cmd, length = packet[0], packet[1], packet[2], packet[3]

    # Variant A (original): F1F1 07/15 02 low high … 7E
    if header1 == 0xF1 and header2 == 0xF1 and length >= 0x02 and cmd in (0x07, 0x15):
        low, high = packet[4], packet[5]
        height_mm = (high << 8) + low  # little-endian cm
        return height_mm * 10  # convert cm → mm

    # Variant B (observed): F2F2 01 03 high low x … 7E
    if header1 == 0xF2 and header2 == 0xF2 and cmd == 0x01 and length >= 0x03:
        high, low = packet[4], packet[5]
        height_mm = (high << 8) + low  # already in mm? verify scale
        # If value seems like cm (<300), convert to mm
        if height_mm < 300:
            height_mm *= 10
        return height_mm

    return None


class EliotDeskClient:
    """Async BLE client wrapper."""

    def __init__(self, hass: HomeAssistant, address: str):
        self._hass = hass
        self._address = address
        self._client: Optional[BleakClient] = None
        self._height_mm: Optional[int] = None
        self._locked: Optional[bool] = None
        self._height_callback: Optional[Callable[[int], None]] = None
        self._lock_callback: Optional[Callable[[bool], None]] = None

    # ---------------------------------------------------------------------
    async def connect(self):
        if self._client and self._client.is_connected:
            return

        # Fetch latest BLEDevice (could change if the desk is roaming)
        ble_device = bluetooth.async_ble_device_from_address(
            self._hass, self._address, connectable=True
        )
        if ble_device is None:
            raise BleakError("BLE device not found or not currently advertising")

        last_err: Optional[Exception] = None
        for attempt in range(1, 4):
            _LOGGER.debug(
                "Connecting to desk %s (attempt %d/3)", self._address, attempt
            )
            try:
                self._client = BleakClient(ble_device)
                await self._client.connect()

                # Subscribe before handshake so we capture the height packet
                await self._client.start_notify(NOTIFY_CHAR_UUID, self._handle_notify)

                # handshake
                await self._client.write_gatt_char(
                    WRITE_CHAR_UUID, CONNECT_FRAME, response=False
                )
                _LOGGER.debug("Connected and handshake complete")
                return
            except (BleakError, TimeoutError) as err:
                last_err = err
                _LOGGER.debug("BLE connect attempt %d failed: %s", attempt, err)
                # Small delay before retrying
                await asyncio.sleep(2 * attempt)

        # If we get here all retries failed
        raise BleakError(f"Failed to connect after retries: {last_err}")

    async def disconnect(self):
        if self._client and self._client.is_connected:
            await self._client.disconnect()
            _LOGGER.debug("Disconnected")

    # ------------------------------------------------------------------
    async def ensure_connected(self):
        try:
            await self.connect()
        except BleakError as exc:
            _LOGGER.error("BLE connection failed: %s", exc)
            raise

    # ------------------------------------------------------------------
    async def update_height(self):
        await self.get_height()

    # ------------------------------------------------------------------
    async def get_height(self, timeout: float = 3.0) -> Optional[int]:
        """Query the desk for its current height and wait for response."""
        await self.ensure_connected()

        # Clear previous wait event
        loop = asyncio.get_running_loop()
        self._height_event = getattr(self, "_height_event", None)
        if self._height_event is None or self._height_event.is_set():
            self._height_event = asyncio.Event()

        await self._client.write_gatt_char(
            WRITE_CHAR_UUID, QUERY_HEIGHT, response=False
        )

        try:
            await asyncio.wait_for(self._height_event.wait(), timeout)
        except asyncio.TimeoutError:
            _LOGGER.debug("Timeout waiting for height response")
        return self._height_mm

    # ------------------------------------------------------------------
    async def set_height_mm(self, target_mm: int, tolerance: int = 5):
        """Direct-set desk height using 0x1B command (iOS behaviour)."""
        await self.ensure_connected()

        # iOS sequence: send a zero frame first, then 0x1B length-2 with big-endian mm.
        high = (target_mm >> 8) & 0xFF
        low = target_mm & 0xFF

        frame = make_frame(0x1B, [high, low])

        _LOGGER.debug("Setting desk height to %s mm – frame=%s", target_mm, frame.hex())

        # zero frame then actual command
        await self._client.write_gatt_char(WRITE_CHAR_UUID, ZERO_FRAME, response=False)
        await self._client.write_gatt_char(WRITE_CHAR_UUID, frame, response=False)

        # Optionally update cached height after a short delay
        await asyncio.sleep(0.2)
        await self.get_height()

    # ------------------------------------------------------------------
    # control methods
    async def move_up(self):
        await self.ensure_connected()
        await self._client.write_gatt_char(WRITE_CHAR_UUID, MOVE_UP, response=False)

    async def move_down(self):
        await self.ensure_connected()
        await self._client.write_gatt_char(WRITE_CHAR_UUID, MOVE_DOWN, response=False)

    async def stop(self):
        await self.ensure_connected()
        await self._client.write_gatt_char(WRITE_CHAR_UUID, STOP, response=False)

    # ------------------------------------------------------------------
    # New preset / utility controls
    async def move_sit(self):
        """Move desk to memorised sitting height preset."""
        await self.ensure_connected()
        await self._client.write_gatt_char(WRITE_CHAR_UUID, SIT_PRESET, response=False)

    async def move_stand(self):
        """Move desk to memorised standing height preset."""
        await self.ensure_connected()
        await self._client.write_gatt_char(
            WRITE_CHAR_UUID, STAND_PRESET, response=False
        )

    async def lock(self):
        """Lock the desk control panel (child lock)."""
        await self.ensure_connected()
        await self._client.write_gatt_char(WRITE_CHAR_UUID, LOCK_FRAME, response=False)

    async def unlock(self):
        """Unlock the desk control panel."""
        await self.ensure_connected()
        await self._client.write_gatt_char(
            WRITE_CHAR_UUID, UNLOCK_FRAME, response=False
        )

    # ------------------------------------------------------------------
    # Preset save (overwrite) controls – requires leading ZERO_FRAME
    async def save_sit_preset(self):
        """Save current height as the sitting memory preset (slot 0x02)."""
        await self.ensure_connected()
        # Send zero-frame then cmd 0x02 (same opcode as MOVE_DOWN)
        await self._client.write_gatt_char(WRITE_CHAR_UUID, ZERO_FRAME, response=False)
        await self._client.write_gatt_char(
            WRITE_CHAR_UUID, make_frame(0x02), response=False
        )

    async def save_stand_preset(self):
        """Save current height as the standing memory preset (slot 0x03)."""
        await self.ensure_connected()
        # Zero-frame then cmd 0x2B (same bytes as STOP but prefixed causes save)
        await self._client.write_gatt_char(WRITE_CHAR_UUID, ZERO_FRAME, response=False)
        await self._client.write_gatt_char(WRITE_CHAR_UUID, STOP, response=False)

    # ------------------------------------------------------------------
    # Notification handler
    def _handle_notify(self, _char: int, data: bytes):
        height = decode_height(data)
        if height is not None:
            self._height_mm = height
            # signal waiting get_height()
            height_event = getattr(self, "_height_event", None)
            if height_event and not height_event.is_set():
                height_event.set()
            if self._height_callback:
                # schedule callback async to avoid sync call in Bleak thread
                asyncio.get_running_loop().call_soon_threadsafe(
                    self._height_callback, height
                )
        else:
            _LOGGER.debug("Unhandled notification: %s", data.hex())

        # Detect lock status frames: F2F2 1F 01 {0|1} xx 7E
        if (
            len(data) >= 6
            and data[0] == 0xF2
            and data[1] == 0xF2
            and data[2] == 0x1F
            and data[3] == 0x01
        ):
            locked_flag = data[4] == 0x01
            if self._locked != locked_flag:
                self._locked = locked_flag
                if self._lock_callback:
                    asyncio.get_running_loop().call_soon_threadsafe(
                        self._lock_callback, locked_flag
                    )

    # properties
    @property
    def height_mm(self) -> Optional[int]:
        return self._height_mm

    def set_height_callback(self, cb: Callable[[int], None]):
        self._height_callback = cb

    def set_lock_callback(self, cb: Callable[[bool], None]):
        self._lock_callback = cb

    @property
    def is_locked(self) -> Optional[bool]:
        return self._locked
