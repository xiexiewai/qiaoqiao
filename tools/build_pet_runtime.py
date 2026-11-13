"""Assemble the approved motions with the original breathing and edge loops."""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import build_pet_atlas as base
from tools import build_pet_motion_review as review


def runtime_actions() -> list[base.Action]:
    items = base.actions()
    entries = [(pose, clip) for pose in review.POSES for clip in review.clips() if clip.name != "rest"]
    entries.extend(("drag", clip) for clip in review.drag_clips())
    for pose, clip in entries:
        images = []
        for index, state in enumerate(clip.states):
            if pose == "drag":
                image = review.draw_frame("free", state, lifted=clip.name != "release")
                if clip.name == "pickup" and index == 0:
                    image = review.draw_frame("free", review.REST)
            else:
                image = review.draw_frame(pose, state)
            images.append(image)
        placement = review.placement(pose)
        anchor = (32, 55) if pose == "drag" and clip.name == "release" else tuple(placement["anchor"])
        contacts = placement["contacts"]
        if pose == "free" and clip.name in ("celebrate", "celebrate_big", "play"):
            contacts = []
        next_action = None
        if not clip.loop:
            if clip.next_action == "rest":
                next_action = pose if pose in ("left", "right", "top", "bottom") else "idle"
            else:
                next_action = f"{pose}.{clip.next_action}"
        items.append(base.Action(
            f"{pose}.{clip.name}", clip.label, images, clip.durations, clip.loop,
            anchor, contacts, tuple(placement["boundary"]) if placement["boundary"] else None,
            next_action,
        ))
    return items


def main() -> None:
    app = QApplication([])
    items = runtime_actions()
    manifest = base.write_atlas(items, columns=12, schema_version=2)
    print(f"Runtime atlas: {len(items)} actions, {sum(len(a.images) for a in items)} frames")
    print(f"SHA256: {manifest['sha256']}")
    app.quit()


if __name__ == "__main__":
    main()
