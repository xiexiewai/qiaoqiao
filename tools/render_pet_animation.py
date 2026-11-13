"""Make review GIFs from the exported atlas. Requires Pillow in the authoring environment."""

import json
import os
import hashlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets" / "pet" / "qiaoqiao-v2"
OUTPUT = ROOT / "docs" / "pet-animation-v1"
SCALE = 3


def current_frame(action: dict, elapsed: int) -> int:
    duration = action["duration_ms"]
    if action["loop"]:
        elapsed %= duration
    else:
        elapsed %= duration + 1800
        elapsed = min(elapsed, duration - 1)
    for index, frame in enumerate(action["frames"]):
        if elapsed < frame["duration_ms"]:
            return index
        elapsed -= frame["duration_ms"]
    return len(action["frames"]) - 1


def sprite_frames(atlas: Image.Image, action: dict) -> list[Image.Image]:
    images = []
    for frame in action["frames"]:
        x, y, w, h = frame["rect"]
        images.append(atlas.crop((x, y, x + w, y + h)).resize((w * SCALE, h * SCALE), Image.Resampling.NEAREST))
    return images


def palette(manifest: dict) -> Image.Image:
    colors = list(manifest["palette"].values()) + ["#171522", "#D6D9E0", "#8A8994", "#F2EBF4", "#A49AB4"]
    values = [int(color[index:index + 2], 16) for color in colors for index in (1, 3, 5)]
    values.extend([0] * (768 - len(values)))
    image = Image.new("P", (1, 1))
    image.putpalette(values)
    return image


def draw_boundary(image: Image.Image, action: dict, x: int, y: int) -> None:
    boundary = action["boundary"]
    if boundary is None:
        return
    draw = ImageDraw.Draw(image)
    value = boundary["value"] * SCALE
    if boundary["axis"] == "x":
        draw.line((x + value, y + 4 * SCALE, x + value, y + 60 * SCALE), fill="#8A8994")
    else:
        draw.line((x + 8 * SCALE, y + value, x + 56 * SCALE, y + value), fill="#8A8994")


def save_gif(frames: list[Image.Image], durations: list[int], path: Path, colors: Image.Image) -> None:
    indexed = [frame.convert("RGB").quantize(palette=colors, dither=Image.Dither.NONE) for frame in frames]
    indexed[0].save(path, save_all=True, append_images=indexed[1:], duration=durations,
                    loop=0, disposal=1, optimize=False)


def action_board(action: dict, sprite: Image.Image) -> Image.Image:
    board = Image.new("RGB", (448, 240), "#171522")
    ImageDraw.Draw(board).rectangle((224, 0, 448, 240), fill="#D6D9E0")
    for x in (16, 240):
        draw_boundary(board, action, x, 24)
        board.paste(sprite, (x, 24), sprite)
    return board


def action_preview(action: dict, sprites: list[Image.Image], colors: Image.Image, name: str) -> None:
    frames = [action_board(action, sprite) for sprite in sprites]
    durations = [f["duration_ms"] for f in action["frames"]]
    if not action["loop"]:
        durations[-1] += 1800
    save_gif(frames, durations, OUTPUT / f"{name}.gif", colors)


def overview(manifest: dict, sprites: dict[str, list[Image.Image]], colors: Image.Image) -> None:
    board = Image.new("RGB", (1024, 600), "#171522")
    draw = ImageDraw.Draw(board)
    font_path = Path(os.environ["WINDIR"]) / "Fonts" / "msyh.ttc"
    title_font = ImageFont.truetype(str(font_path), 23)
    label_font = ImageFont.truetype(str(font_path), 17)
    small_font = ImageFont.truetype(str(font_path), 13)
    draw.text((28, 15), "敲敲 / 第一版动作预览", fill="#F2EBF4", font=title_font)
    entries = list(manifest["actions"].items())
    for index, (name, action) in enumerate(entries):
        col, row = index % 4, index // 4
        x, y = col * 256, 60 + row * 270
        light = (col + row) % 2 == 1
        if light:
            draw.rectangle((x, y, x + 255, y + 269), fill="#D6D9E0")
        ink = "#171522" if light else "#F2EBF4"
        draw.text((x + 24, y + 8), action["label"], font=label_font, fill=ink)
        draw.text((x + 24, y + 242), "循环" if action["loop"] else "单次动作 / 预览重复",
                  font=small_font, fill=ink)
        draw_boundary(board, action, x + 32, y + 42)
    # Render only when a sprite changes, preserving even the short blink timings.
    end = 13800
    changes = {0, end}
    for _, action in entries:
        period = action["duration_ms"] + (0 if action["loop"] else 1800)
        for start in range(0, end, period):
            elapsed = start
            for frame in action["frames"]:
                if elapsed < end:
                    changes.add(elapsed)
                elapsed += frame["duration_ms"]
    times = sorted(changes)
    frames = []
    for elapsed in times[:-1]:
        image = board.copy()
        for index, (name, action) in enumerate(entries):
            x, y = (index % 4) * 256 + 32, 102 + (index // 4) * 270
            sprite = sprites[name][current_frame(action, elapsed)]
            image.paste(sprite, (x, y), sprite)
        frames.append(image)
    save_gif(frames, [b - a for a, b in zip(times, times[1:])], OUTPUT / "overview.gif", colors)
    frames[0].save(OUTPUT / "overview.png")


def validate_previews(manifest: dict, sprites: dict[str, list[Image.Image]], colors: Image.Image) -> None:
    report = {
        "atlas_sha256": hashlib.sha256((ASSETS / manifest["image"]).read_bytes()).hexdigest(),
        "gif_checks": {},
        "visual_review": "Contact sheet and decoded keyframes; browser playback unavailable.",
    }
    if report["atlas_sha256"] != manifest["sha256"]:
        raise ValueError("The atlas and manifest do not match.")
    proof = Image.new("RGB", (448 * 3, 240 * 3))
    for row, name in enumerate(("left", "top", "settle")):
        with Image.open(OUTPUT / f"{name}.gif") as gif:
            for col, index in enumerate((0, 2, 4)):
                gif.seek(index)
                proof.paste(gif.convert("RGB"), (col * 448, row * 240))
    work = ROOT / "work" / "pet-atlas-check"
    work.mkdir(parents=True, exist_ok=True)
    proof.save(work / "decoded-keyframes.png")
    for name, action in manifest["actions"].items():
        elapsed = 0
        unique = set()
        with Image.open(OUTPUT / f"{name}.gif") as gif:
            if gif.info.get("loop") != 0:
                raise ValueError(f"Missing preview repeat: {name}")
            for index in range(gif.n_frames):
                gif.seek(index)
                duration = gif.info["duration"]
                decoded = gif.convert("RGB")
                expected_index = current_frame(action, elapsed)
                expected = action_board(action, sprites[name][expected_index]).quantize(
                    palette=colors, dither=Image.Dither.NONE,
                ).convert("RGB")
                if decoded.tobytes() != expected.tobytes():
                    raise ValueError(f"Decoded GIF differs from source frame: {name}/{index}")
                unique.add(hashlib.sha256(decoded.tobytes()).hexdigest())
                elapsed += duration
            expected_duration = action["duration_ms"] + (0 if action["loop"] else 1800)
            if elapsed != expected_duration or len(unique) < 2:
                raise ValueError(f"Invalid motion or duration: {name}")
            report["gif_checks"][name] = {
                "decoded_frames": gif.n_frames, "distinct_frames": len(unique),
                "duration_ms": elapsed, "pixels_match_atlas": True,
            }
    with Image.open(OUTPUT / "overview.gif") as gif:
        duration = 0
        for index in range(gif.n_frames):
            gif.seek(index)
            duration += gif.info["duration"]
        if duration != 13800 or gif.n_frames < 2:
            raise ValueError("Invalid overview duration or motion.")
        report["gif_checks"]["overview"] = {"decoded_frames": gif.n_frames, "duration_ms": duration}
    report["ok"] = True
    (OUTPUT / "qa.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"GIF decode validation: passed ({len(report['gif_checks'])} files)")


def main() -> None:
    manifest = json.loads((ASSETS / "atlas.json").read_text(encoding="utf-8"))
    # Keep the original eight-motion review; new behaviors have a separate v2 preview.
    manifest["actions"] = {
        name: manifest["actions"][name]
        for name in ("idle", "blink", "drag", "left", "right", "bottom", "top", "settle")
    }
    atlas = Image.open(ASSETS / manifest["image"]).convert("RGBA")
    colors = palette(manifest)
    sprites = {name: sprite_frames(atlas, action) for name, action in manifest["actions"].items()}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, action in manifest["actions"].items():
        action_preview(action, sprites[name], colors, name)
    overview(manifest, sprites, colors)
    validate_previews(manifest, sprites, colors)
    print(f"Motion previews: {OUTPUT}")


if __name__ == "__main__":
    main()
