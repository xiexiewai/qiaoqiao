"""Set-1 physical key identities and a standard ANSI 104-key layout."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PhysicalEvent:
    device: int
    key_id: str
    is_down: bool
    pulse: bool = False


def scan_id(code: int, prefix: str = "") -> str:
    return f"{prefix}{code:02x}"


def normalize(device: int, make_code: int, flags: int, vkey: int) -> PhysicalEvent | None:
    if make_code in (0, 0xFF) or vkey >= 0xFF:
        return None
    code = make_code & 0x7F
    is_down = not bool(flags & 1)
    e0, e1 = bool(flags & 2), bool(flags & 4)
    # Ignore the synthetic shift/control prefixes in extended key sequences.
    if e0 and code in (0x2A, 0x36):
        return None
    if e1 and code == 0x1D:
        return None
    if vkey in (0x13, 0x03):
        # Pause has no reliable break event; hardware emits one make per press.
        return PhysicalEvent(device, "e1_45", is_down, pulse=True)
    if vkey == 0x2C:
        return PhysicalEvent(device, "e0_37", is_down)
    if vkey == 0x90:
        return PhysicalEvent(device, "45", is_down)
    prefix = "e0_" if e0 else "e1_" if e1 else ""
    return PhysicalEvent(device, scan_id(code, prefix), is_down)


@dataclass(frozen=True)
class Key:
    key_id: str | None
    label: str
    x: float
    y: float
    width: float = 1
    height: float = 1


def _layout() -> tuple[Key, ...]:
    keys: list[Key] = []

    def add(code, label, x, y, width=1, height=1, prefix=""):
        keys.append(Key(scan_id(code, prefix), label, x, y, width, height))

    add(0x01, "Esc", 0, 0)
    for index in range(12):
        code = 0x3B + index if index < 10 else 0x57 + index - 10
        add(code, f"F{index + 1}", 2 + index + (index // 4) * 0.5, 0)
    for code, label, x, prefix in (
        (0x37, "PrtSc", 15.5, "e0_"), (0x46, "ScrLk", 16.5, ""),
        (0x45, "Pause", 17.5, "e1_"),
    ):
        add(code, label, x, 0, prefix=prefix)

    for index, label in enumerate(("`", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-", "=")):
        add(0x29 if index == 0 else index + 1, label, index, 1.5)
    add(0x0E, "Backspace", 13, 1.5, 2)

    add(0x0F, "Tab", 0, 2.5, 1.5)
    for index, label in enumerate(("Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P", "[", "]")):
        add(0x10 + index, label, 1.5 + index, 2.5)
    add(0x2B, "\\", 13.5, 2.5, 1.5)

    add(0x3A, "Caps", 0, 3.5, 1.75)
    for index, label in enumerate(("A", "S", "D", "F", "G", "H", "J", "K", "L", ";", "'")):
        add(0x1E + index, label, 1.75 + index, 3.5)
    add(0x1C, "Enter", 12.75, 3.5, 2.25)

    add(0x2A, "Shift L", 0, 4.5, 2.25)
    for index, label in enumerate(("Z", "X", "C", "V", "B", "N", "M", ",", ".", "/")):
        add(0x2C + index, label, 2.25 + index, 4.5)
    add(0x36, "Shift R", 12.25, 4.5, 2.75)

    for code, label, x, width, prefix in (
        (0x1D, "Ctrl L", 0, 1.25, ""), (0x5B, "Win L", 1.25, 1.25, "e0_"),
        (0x38, "Alt L", 2.5, 1.25, ""), (0x39, "Space", 3.75, 6.25, ""),
        (0x38, "Alt R", 10, 1.25, "e0_"), (0x5C, "Win R", 11.25, 1.25, "e0_"),
        (0x5D, "Menu", 12.5, 1.25, "e0_"), (0x1D, "Ctrl R", 13.75, 1.25, "e0_"),
    ):
        add(code, label, x, 5.5, width, prefix=prefix)

    for code, label, x, y in (
        (0x52, "Ins", 15.5, 1.5), (0x47, "Home", 16.5, 1.5),
        (0x49, "PgUp", 17.5, 1.5), (0x53, "Del", 15.5, 2.5),
        (0x4F, "End", 16.5, 2.5), (0x51, "PgDn", 17.5, 2.5),
        (0x48, "Up", 16.5, 4.5), (0x4B, "Left", 15.5, 5.5),
        (0x50, "Down", 16.5, 5.5), (0x4D, "Right", 17.5, 5.5),
    ):
        add(code, label, x, y, prefix="e0_")

    for code, label, x, y, width, height, prefix in (
        (0x45, "Num", 19, 1.5, 1, 1, ""),
        (0x35, "/", 20, 1.5, 1, 1, "e0_"),
        (0x37, "*", 21, 1.5, 1, 1, ""),
        (0x4A, "-", 22, 1.5, 1, 1, ""),
        (0x47, "7", 19, 2.5, 1, 1, ""), (0x48, "8", 20, 2.5, 1, 1, ""),
        (0x49, "9", 21, 2.5, 1, 1, ""), (0x4E, "+", 22, 2.5, 1, 2, ""),
        (0x4B, "4", 19, 3.5, 1, 1, ""), (0x4C, "5", 20, 3.5, 1, 1, ""),
        (0x4D, "6", 21, 3.5, 1, 1, ""), (0x4F, "1", 19, 4.5, 1, 1, ""),
        (0x50, "2", 20, 4.5, 1, 1, ""), (0x51, "3", 21, 4.5, 1, 1, ""),
        (0x1C, "Enter", 22, 4.5, 1, 2, "e0_"),
        (0x52, "0", 19, 5.5, 2, 1, ""), (0x53, ".", 21, 5.5, 1, 1, ""),
    ):
        add(code, label, x, y, width, height, prefix)
    return tuple(keys)


KEYS = _layout()
KEY_BY_ID = {key.key_id: key for key in KEYS}


def key_name(key_id: str) -> str:
    key = KEY_BY_ID.get(key_id)
    if key is None:
        return f"Scan {key_id.upper()}"
    return f"Num {key.label}" if key.x >= 19 else key.label
