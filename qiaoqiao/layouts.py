"""Display presets sharing the existing physical scan-code identities."""

from dataclasses import dataclass, replace

from .keys import KEYS, KEY_BY_ID, Key


@dataclass(frozen=True)
class KeyboardLayout:
    layout_id: str
    name: str
    keys: tuple[Key, ...]

    @property
    def width(self) -> float:
        return max(key.x + key.width for key in self.keys)

    @property
    def height(self) -> float:
        return max(key.y + key.height for key in self.keys)

    @property
    def key_ids(self) -> frozenset[str]:
        return frozenset(key.key_id for key in self.keys if key.key_id is not None)


def _at(key_id, x, y, width=None, height=1):
    key = KEY_BY_ID[key_id]
    return replace(key, x=x, y=y, width=key.width if width is None else width, height=height)


def _main_rows(top):
    return [
        replace(key, y=key.y - 1.5 + top)
        for key in KEYS if key.x < 15 and 1.5 <= key.y < 5.5
    ]


def _compact(function_row):
    top = 1.25 if function_row else 0
    keys = _main_rows(top)
    if not function_row:
        keys[0] = _at("01", 0, top)
    keys = [replace(key, width=1.75) if key.key_id == "36" else key for key in keys]
    keys.append(_at("e0_48", 14, top + 3, 1))
    navigation = ("e0_47", "e0_49", "e0_51", "e0_4f") if function_row else (
        "e0_53", "e0_47", "e0_49", "e0_51",
    )
    keys.extend(_at(key_id, 15, top + row, 1) for row, key_id in enumerate(navigation))
    for key_id, x, width in (
        ("1d", 0, 1.25), ("e0_5b", 1.25, 1.25), ("38", 2.5, 1.25),
        ("39", 3.75, 6.25), ("e0_38", 10, 1), ("e0_1d", 12, 1),
        ("e0_4b", 13, 1), ("e0_50", 14, 1), ("e0_4d", 15, 1),
    ):
        keys.append(_at(key_id, x, top + 4, width))
    # Fn is a visual position only; it must never alias a captured physical key.
    keys.append(Key(None, "Fn", 11, top + 4))
    if function_row:
        keys.append(_at("01", 0, 0))
        functions = [key for key in KEYS if key.label.startswith("F") and key.y == 0]
        keys.extend(replace(key, x=index + 1) for index, key in enumerate(functions))
        keys.extend(_at(key_id, x, 0, 1) for x, key_id in enumerate(
            ("e0_37", "e0_52", "e0_53"), start=13,
        ))
    return tuple(keys)


def _sixty():
    keys = _main_rows(0)
    keys[0] = _at("01", 0, 0)
    for key in KEYS:
        if key.x < 15 and key.y == 5.5:
            keys.append(
                Key(None, "Fn", key.x, 4, key.width)
                if key.key_id == "e0_5c" else replace(key, y=4)
            )
    return tuple(keys)


def _laptop():
    keys = _main_rows(1.25)
    keys.append(_at("01", 0, 0))
    functions = [key for key in KEYS if key.label.startswith("F") and key.y == 0]
    keys.extend(replace(key, x=index + 1.25) for index, key in enumerate(functions))
    keys.append(_at("e0_53", 13.25, 0, 1.75))
    for key_id, x, width in (
        ("1d", 0, 1.25), ("e0_5b", 2.25, 1), ("38", 3.25, 1.25),
        ("39", 4.5, 5.5), ("e0_38", 10, 1), ("e0_1d", 11, 1),
        ("e0_4b", 12, 1), ("e0_4d", 14, 1),
    ):
        keys.append(_at(key_id, x, 5.25, width))
    keys.append(Key(None, "Fn", 1.25, 5.25))
    keys.append(_at("e0_48", 13, 5.25, 1, 0.5))
    keys.append(_at("e0_50", 13, 5.75, 1, 0.5))
    return tuple(keys)


LAYOUTS = (
    KeyboardLayout("full", "\u5168\u5c3a\u5bf8 104 \u952e", KEYS),
    KeyboardLayout("tkl", "\u65e0\u6570\u5b57\u533a 87 \u952e", tuple(key for key in KEYS if key.x < 19)),
    KeyboardLayout("75", "75% \u7d27\u51d1 84 \u952e", _compact(True)),
    KeyboardLayout("65", "65% \u7d27\u51d1 68 \u952e", _compact(False)),
    KeyboardLayout("60", "60% \u8ff7\u4f60 61 \u952e", _sixty()),
    KeyboardLayout("laptop", "\u7b14\u8bb0\u672c\uff08\u901a\u7528\u7d27\u51d1\uff09", _laptop()),
)
LAYOUT_BY_ID = {layout.layout_id: layout for layout in LAYOUTS}
DEFAULT_LAYOUT = LAYOUTS[0]
