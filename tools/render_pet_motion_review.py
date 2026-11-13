"""Render and check review artifacts using Pillow in the authoring environment."""

import base64
import hashlib
import json
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "pet-animation-v2"
DARK, LIGHT, WHITE, MUTED = "#171522", "#D6D9E0", "#F2EBF4", "#A49AB4"
FONT = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"
LABELS = {size: ImageFont.truetype(str(FONT), size) for size in (13, 15, 17, 20, 24)}
INTERACTIONS = ["tap", "typing", "celebrate", "celebrate_big", "hover", "click"]
IDLE = ["look", "stretch", "play", "doze", "sleep", "wake"]
SHEET_ACTIONS = INTERACTIONS + IDLE + ["hover_hold", "hover_leave"]


def components(pixels: set[tuple[int, int]]) -> int:
    remaining = set(pixels)
    count = 0
    while remaining:
        pending = [remaining.pop()]
        count += 1
        while pending:
            x, y = pending.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    point = (x + dx, y + dy)
                    if point in remaining:
                        remaining.remove(point)
                        pending.append(point)
    return count


def load() -> tuple[dict, dict[str, list[Image.Image]]]:
    manifest = json.loads((OUTPUT / "atlas.json").read_text(encoding="utf-8"))
    atlas = Image.open(OUTPUT / "atlas.png").convert("RGBA")
    frames = {}
    for name, action in manifest["actions"].items():
        frames[name] = []
        for frame in action["frames"]:
            x, y, w, h = frame["rect"]
            frames[name].append(atlas.crop((x, y, x + w, y + h)))
    return manifest, frames


def validate(manifest: dict, frames: dict[str, list[Image.Image]]) -> dict:
    errors = []
    allowed = {tuple(bytes.fromhex(color[1:])) for color in manifest["palette"].values()}
    eye_colors = {tuple(bytes.fromhex(manifest["palette"][name][1:]))
                  for name in ("MINT", "EYE_LIGHT")}
    patches = {"left": [(24, 42, 29, 50)], "right": [(35, 42, 40, 50)],
               "top": [(18, 15, 25, 19), (41, 15, 48, 19)],
               "bottom": [(17, 46, 27, 51), (39, 46, 49, 51)]}
    check_count = 0
    for name, action in manifest["actions"].items():
        pose = action["pose"]
        if action["next"] not in manifest["actions"]:
            errors.append(f"{name}: missing next clip")
        if action["duration_ms"] != sum(f["duration_ms"] for f in action["frames"]):
            errors.append(f"{name}: bad duration")
        distinct = set()
        for index, image in enumerate(frames[name]):
            key = f"{name}/{index}"
            check_count += 1
            distinct.add(image.tobytes())
            opaque, eyes = set(), set()
            for y in range(64):
                for x in range(64):
                    rgba = image.getpixel((x, y))
                    if rgba[3] not in (0, 255) or (rgba[3] and rgba[:3] not in allowed):
                        errors.append(f"{key}: invalid alpha/palette at {x},{y}")
                    if rgba[3]:
                        opaque.add((x, y))
                        if rgba[:3] in eye_colors:
                            eyes.add((x, y))
            if components(opaque) != 1:
                errors.append(f"{key}: disconnected body ({components(opaque)})")
            if components(eyes) != 2:
                errors.append(f"{key}: missing/merged eyes ({components(eyes)})")
            bbox = image.getbbox()
            if not bbox or min(bbox[:2]) <= 0 or max(bbox[2:]) >= 64:
                errors.append(f"{key}: clipped canvas")
            if bbox and list((bbox[0], bbox[1], bbox[2] - bbox[0], bbox[3] - bbox[1])) != action["frames"][index]["bounds"]:
                errors.append(f"{key}: incorrect bounds")
            if pose in patches:
                rest = frames[f"{pose}.rest"][0]
                for patch in patches[pose]:
                    if image.crop(patch).tobytes() != rest.crop(patch).tobytes():
                        errors.append(f"{key}: moving support patch {patch}")
                leak = any(
                    (pose == "left" and x < 24) or (pose == "right" and x >= 40) or
                    (pose == "top" and y < 15) or (pose == "bottom" and y >= 51)
                    for x, y in opaque
                )
                if leak:
                    errors.append(f"{key}: screen boundary leak")
            duration = action["frames"][index]["duration_ms"]
            if duration <= 0 or duration % 10:
                errors.append(f"{key}: duration not representable in GIF")
        if action["behavior"] != "rest" and len(distinct) < 2:
            errors.append(f"{name}: no motion")
        if not action["loop"] and action["next"].endswith(".rest"):
            if frames[name][-1].tobytes() != frames[action["next"]][0].tobytes():
                errors.append(f"{name}: last frame does not match resting pose")
    old = ROOT / "assets" / "pet" / "qiaoqiao-v2"
    old_manifest = json.loads((old / "atlas.json").read_text(encoding="utf-8"))
    old_atlas = Image.open(old / "atlas.png").convert("RGBA")
    for pose in ("free", "left", "right", "top", "bottom"):
        action = old_manifest["actions"]["idle" if pose == "free" else pose]
        x, y, w, h = action["frames"][0]["rect"]
        if old_atlas.crop((x, y, x + w, y + h)).tobytes() != frames[f"{pose}.rest"][0].tobytes():
            errors.append(f"{pose}: reference differs from current runtime")
    digest = hashlib.sha256((OUTPUT / "atlas.png").read_bytes()).hexdigest()
    if digest != manifest["sha256"]:
        errors.append("Atlas hash mismatch")
    for name in manifest["actions"]:
        if name.startswith("left.") and not any(part in name for part in ("hover", "look")):
            right = name.replace("left.", "right.", 1)
            for index, frame in enumerate(frames[name]):
                if frame.transpose(Image.Transpose.FLIP_LEFT_RIGHT).tobytes() != frames[right][index].tobytes():
                    errors.append(f"{name}/{index}: asymmetric mirror")
    report = {
        "ok": not errors, "clips": len(frames), "frames_checked": check_count,
        "atlas_sha256": digest,
        "runtime_atlas_sha256": hashlib.sha256((old / "atlas.png").read_bytes()).hexdigest(),
        "checks": ["binary alpha", "existing palette", "connected body", "two visible eyes",
                   "canvas bounds", "fixed support patches", "no edge leaks", "timing",
                   "resting-pose transitions", "current runtime reference",
                   "left/right mirrors excluding directional gaze"],
        "errors": errors, "runtime_integration_tested": False,
    }
    (OUTPUT / "qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Asset checks: {check_count} frames, {len(errors)} errors")
    if errors:
        print("\n".join(errors[:60]))
    return report


def guide(board: Image.Image, action: dict, x: int, y: int, scale: int) -> None:
    boundary = action["boundary"]
    if not boundary:
        return
    draw = ImageDraw.Draw(board)
    axis, value = boundary
    if axis == "x":
        draw.line((x + value * scale, y + 3 * scale,
                   x + value * scale, y + 60 * scale), fill="#8A8994")
    else:
        draw.line((x + 5 * scale, y + value * scale,
                   x + 59 * scale, y + value * scale), fill="#8A8994")


def paste(board: Image.Image, sprite: Image.Image, xy: tuple[int, int], scale: int) -> None:
    enlarged = sprite.resize((64 * scale, 64 * scale), Image.Resampling.NEAREST)
    board.paste(enlarged, xy, enlarged)


def indexed_palette(manifest: dict) -> Image.Image:
    colors = list(manifest["palette"].values()) + [
        DARK, LIGHT, WHITE, MUTED, "#8A8994", "#D5D7DE", "#E8E9EE", "#596071",
    ]
    values = [int(c[i:i + 2], 16) for c in colors for i in (1, 3, 5)]
    # Extra neutral levels keep antialiased review labels readable.
    values += [v for gray in range(24, 241, 8) for v in (gray, gray, gray)]
    values += [0] * (768 - len(values))
    image = Image.new("P", (1, 1))
    image.putpalette(values)
    return image


def save_gif(boards: list[Image.Image], durations: list[int], name: str,
             palette: Image.Image) -> dict:
    quantized = [board.quantize(palette=palette, dither=Image.Dither.NONE) for board in boards]
    path = OUTPUT / f"{name}.gif"
    quantized[0].save(path, save_all=True, append_images=quantized[1:], duration=durations,
                      loop=0, optimize=False, disposal=1)
    elapsed, expected_at, expected_index, count = 0, durations[0], 0, 0
    with Image.open(path) as gif:
        for index in range(gif.n_frames):
            gif.seek(index)
            while elapsed >= expected_at and expected_index < len(durations) - 1:
                expected_index += 1
                expected_at += durations[expected_index]
            if gif.convert("RGB").tobytes() != quantized[expected_index].convert("RGB").tobytes():
                raise ValueError(f"Decoded GIF pixels differ: {name}/{index}")
            elapsed += gif.info["duration"]
            count += 1
        if elapsed != sum(durations):
            raise ValueError(f"Decoded GIF duration differs: {name}")
    return {"decoded_frames": count, "duration_ms": elapsed, "decoded_pixels_match": True}


def timeline(manifest: dict, name: str, *, padding: bool = True) -> list[tuple[str, int, int]]:
    action = manifest["actions"][name]
    result = [(name, i, frame["duration_ms"]) for i, frame in enumerate(action["frames"])]
    if padding and not action["loop"]:
        next_name = action["next"]
        if next_name.endswith("hover_hold"):
            result.append((next_name, 0, 1200))
            pose = action["pose"]
            result.extend(timeline(manifest, f"{pose}.hover_leave", padding=False))
            result.append((f"{pose}.rest", 0, 900))
        elif next_name == "drag.struggle":
            result.extend(timeline(manifest, next_name, padding=False) * 2)
            result.extend(timeline(manifest, "drag.release", padding=False))
            result.append(("free.rest", 0, 1200))
        else:
            result.append((next_name, 0, 1400))
    return result


def sample(timing: list[tuple[str, int, int]], elapsed: int) -> tuple[str, int]:
    elapsed %= sum(step[2] for step in timing)
    for name, frame, duration in timing:
        if elapsed < duration:
            return name, frame
        elapsed -= duration
    return timing[-1][:2]


def action_board(manifest: dict, frames: dict, name: str, index: int) -> Image.Image:
    board = Image.new("RGB", (448, 216), DARK)
    draw = ImageDraw.Draw(board)
    draw.rectangle((224, 0, 447, 215), fill=LIGHT)
    action = manifest["actions"][name]
    for x, color in ((48, WHITE), (272, DARK)):
        guide(board, action, x, 24, 2)
        paste(board, frames[name][index], (x, 24), 2)
        draw.text((x - 22, 170), "128 × 128 · 实际逻辑画布", font=LABELS[13], fill=color)
    return board


def export_individual(manifest: dict, frames: dict, palette: Image.Image) -> dict:
    results = {}
    names = [f"free.{n}" for n in SHEET_ACTIONS] + ["drag.pickup", "drag.struggle", "drag.release"]
    for name in names:
        timing = timeline(manifest, name)
        boards = [action_board(manifest, frames, key, index) for key, index, _ in timing]
        results[name] = save_gif(boards, [t[2] for t in timing], name, palette)
    return results


def overview(manifest: dict, frames: dict, names: list[str],
             title: str, filename: str, palette: Image.Image) -> dict:
    width, cell_w, cell_h = 960, 320, 240
    rows = (len(names) + 2) // 3
    board = Image.new("RGB", (width, 78 + rows * cell_h), DARK)
    draw = ImageDraw.Draw(board)
    draw.text((24, 13), title, font=LABELS[24], fill=WHITE)
    draw.text((24, 48), "动作评审稿 · 128 × 128 逻辑画布 · 单次动作间歇重复", font=LABELS[13], fill=MUTED)
    timings = []
    for i, name in enumerate(names):
        x, y = (i % 3) * cell_w, 78 + (i // 3) * cell_h
        light = i % 2 == 1
        fill, ink = (LIGHT, DARK) if light else (DARK, WHITE)
        draw.rectangle((x, y, x + cell_w - 1, y + cell_h - 1), fill=fill)
        action = manifest["actions"][name]
        draw.text((x + 20, y + 12), action["label"], font=LABELS[17], fill=ink)
        draw.text((x + 20, y + 208), f'{action["duration_ms"]} ms / {"循环" if action["loop"] else "单次"}',
                  font=LABELS[13], fill=ink)
        guide(board, action, x + 96, y + 53, 2)
        timings.append(timeline(manifest, name))
    end, changes = 8400, {0, 8400}
    for timing in timings:
        period = sum(t[2] for t in timing)
        for start in range(0, end, period):
            at = start
            for _, _, duration in timing:
                if at < end:
                    changes.add(at)
                at += duration
    times = sorted(changes)
    boards = []
    for elapsed in times[:-1]:
        frame = board.copy()
        for i, timing in enumerate(timings):
            key, index = sample(timing, elapsed)
            xy = ((i % 3) * cell_w + 96, 131 + (i // 3) * cell_h)
            paste(frame, frames[key][index], xy, 2)
        boards.append(frame)
    # A meaningful poster shows the middle of each action, not six resting frames.
    poster = board.copy()
    for i, name in enumerate(names):
        index = min(3, len(frames[name]) - 1)
        paste(poster, frames[name][index],
              ((i % 3) * cell_w + 96, 131 + (i // 3) * cell_h), 2)
    poster.save(OUTPUT / f"{filename}.png")
    return save_gif(boards, [b - a for a, b in zip(times, times[1:])], filename, palette)


def contact_sheets(manifest: dict, frames: dict) -> None:
    for pose in ("free", "left", "right", "top", "bottom", "drag"):
        names = [f"{pose}.{n}" for n in SHEET_ACTIONS] if pose != "drag" else [
            "drag.pickup", "drag.struggle", "drag.release"]
        # Split twelve-frame celebrations across two rows instead of shrinking.
        rows = [(name, start) for name in names for start in range(0, len(frames[name]), 6)]
        board = Image.new("RGB", (1056, 90 + len(rows) * 164), LIGHT)
        draw = ImageDraw.Draw(board)
        draw.text((24, 14), f'敲敲 / {manifest["poses"][pose]} / 逐帧对照',
                  font=LABELS[24], fill=DARK)
        draw.text((24, 52), "每格为 128 × 128 逻辑画布；下方显示原始帧停留时长。", font=LABELS[15], fill="#596071")
        for row, (name, start) in enumerate(rows):
            y = 90 + row * 164
            if row % 2:
                draw.rectangle((0, y, 1055, y + 163), fill="#E8E9EE")
            action = manifest["actions"][name]
            draw.text((20, y + 40), action["label"], font=LABELS[17], fill=DARK)
            draw.text((20, y + 70), f"{start + 1}–{min(start + 6, len(frames[name]))} 帧", font=LABELS[13], fill="#596071")
            for i, sprite in enumerate(frames[name][start:start + 6]):
                x = 180 + i * 144
                guide(board, action, x, y, 2)
                paste(board, sprite, (x, y), 2)
                duration = action["frames"][start + i]["duration_ms"]
                draw.text((x + 36, y + 134), f"{duration} ms", font=LABELS[13], fill="#596071")
        board.save(OUTPUT / f"contact-{pose}.png")


def main() -> None:
    manifest, frames = load()
    report = validate(manifest, frames)
    contact_sheets(manifest, frames)
    # This local script avoids fetch() restrictions when opening the review as file://.
    (OUTPUT / "review-data.js").write_text(
        "window.PET_REVIEW = " + json.dumps(manifest, ensure_ascii=False) + ";\n"
        + 'window.PET_REVIEW_IMAGE = "data:image/png;base64,'
        + base64.b64encode((OUTPUT / "atlas.png").read_bytes()).decode("ascii") + '";\n',
        encoding="utf-8",
    )
    if not report["ok"]:
        raise SystemExit(1)
    palette = indexed_palette(manifest)
    results = export_individual(manifest, frames, palette)
    groups = [
        ("overview", "敲敲 / 六类新增动作", [
            "free.typing", "free.celebrate_big", "drag.struggle",
            "free.play", "free.hover", "free.click"]),
        ("interactions", "敲敲 / 敲击、庆祝与鼠标", [f"free.{n}" for n in INTERACTIONS]),
        ("idle", "敲敲 / 玩耍与休息", [f"free.{n}" for n in IDLE]),
        ("drag", "敲敲 / 提起、挣扎与放下", ["drag.pickup", "drag.struggle", "drag.release"]),
    ]
    for pose in ("left", "right", "top", "bottom"):
        groups.append((f"edge-{pose}", f'敲敲 / {manifest["poses"][pose]}',
                       [f"{pose}.{n}" for n in ("typing", "celebrate", "hover", "click", "play", "sleep")]))
    for filename, title, names in groups:
        results[filename] = overview(manifest, frames, names, title, filename, palette)
    report["gif_checks"] = results
    report["visual_review"] = "Visual appearance awaits user approval; automated checks do not constitute approval."
    (OUTPUT / "qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"GIF decode checks: {len(results)} passed")


if __name__ == "__main__":
    main()
