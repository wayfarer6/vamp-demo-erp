"""Capture two VirtualBox guest framebuffers and render a localized QHD panel."""
import argparse
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import time
from textwrap import wrap
from uuid import UUID

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

FHD = (1920, 1080)
QHD = (2560, 1440)
VBOX = Path("C:/Program Files/Oracle/VirtualBox/VBoxManage.exe")
LABELS = {
    "en": ("ERP target guest", "Isolated repair guest", "Native guest capture · 1920 × 1080"),
    "ko": ("ERP 대상 게스트", "격리 복구 게스트", "게스트 원본 해상도 · 1920 × 1080"),
}


def capture(vm, path):
    subprocess.run([VBOX, "controlvm", vm, "screenshotpng", path],
                   check=True, capture_output=True, timeout=10)
    with Image.open(path) as shot:
        if shot.size != FHD:
            raise ValueError(f"VM {vm} has framebuffer {shot.size}; expected {FHD}.")
        return shot.convert("RGB")


def transcript_lines(path):
    if not path.is_file():
        return []
    data = path.read_bytes()
    if len(data) > 2 * 1024 * 1024:
        raise ValueError("The dedicated Codex transcript exceeds 2 MiB.")
    encoding = "utf-16" if data.startswith((bytes.fromhex("fffe"), bytes.fromhex("feff"))) else "utf-8-sig"
    messages = []
    for line in data.decode(encoding, errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item", {})
        if event.get("type") == "item.completed" and item.get("type") == "agent_message":
            messages.append(item.get("text", ""))
    return [piece for line in "\n".join(messages).splitlines()
            for piece in wrap(line, width=66, replace_whitespace=False, drop_whitespace=False) or [""]]


def paint_transcript(frame, paths, language):
    draw = ImageDraw.Draw(frame)
    draw.rectangle((1250, 0, 2559, 1439), fill="#172431")
    title = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 42)
    mono = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 28)
    caption = "Codex \uc2e4\ud589 \uae30\ub85d" if language == "ko" else "Codex execution transcript"
    waiting = "Codex \ucd9c\ub825 \ub300\uae30 \uc911" if language == "ko" else "Waiting for Codex output"
    draw.text((1310, 53), caption, font=title, fill="#ffffff")
    messages = [line for path in paths for line in transcript_lines(path)]
    for index, line in enumerate((messages or [waiting])[-36:]):
        draw.text((1310, 132 + index * 33), line, font=mono, fill="#e6edf3")


def record(target, scratch, seconds, fps, language, output, transcripts=(), stop_file=None):
    if target == scratch:
        raise ValueError("Choose two distinct guest UUIDs.")
    if output.exists():
        raise FileExistsError(output)
    if stop_file and stop_file.exists():
        raise FileExistsError(stop_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    labels = LABELS[language]
    title = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 43)
    footer = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 32)
    frame = Image.new("RGB", QHD, "#101922")
    draw = ImageDraw.Draw(frame)
    if transcripts:
        positions = ((32, 76), (32, 780))
        panel = (1120, 630)
        for label, (x, y) in zip(labels, positions):
            draw.text((x, y - 48), label, font=footer, fill="#ffffff")
    else:
        positions = ((48, 387), (1328, 387))
        panel = (1184, 666)
        draw.text((48, 318), labels[0], font=title, fill="#ffffff")
        draw.text((1328, 318), labels[1], font=title, fill="#ffffff")
        draw.text((48, 1102), labels[2], font=footer, fill="#b8c9da")
    writer = imageio_ffmpeg.write_frames(str(output), QHD, fps=fps, codec="libx264",
                                         output_params=["-preset", "ultrafast", "-movflags", "+faststart"])
    writer.send(None)
    frame_count = 0
    started = time.monotonic()
    try:
        with TemporaryDirectory(prefix="vamp-showcase-frame-") as temp:
            temp = Path(temp)
            while frame_count < seconds * fps:
                if frame_count and stop_file and stop_file.exists():
                    break
                for index, vm in enumerate((target, scratch)):
                    shot = capture(vm, temp / f"guest-{index}.png")
                    frame.paste(shot.resize(panel, Image.Resampling.LANCZOS), positions[index])
                if transcripts:
                    paint_transcript(frame, transcripts, language)
                data = frame.tobytes()
                elapsed = int((time.monotonic() - started) * fps)
                next_frame = min(seconds * fps, max(frame_count + 1, elapsed + 1))
                while frame_count < next_frame:
                    writer.send(data)
                    frame_count += 1
                time.sleep(max(0, started + frame_count / fps - time.monotonic()))
    finally:
        writer.close()
    info = {"framebuffer": FHD, "output_resolution": QHD, "frames": frame_count,
            "fps": fps, "seconds": frame_count / fps, "language": language,
            "stopped_by_operator": frame_count < seconds * fps}
    output.with_suffix(".json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(json.dumps(info))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=UUID)
    parser.add_argument("scratch", type=UUID)
    parser.add_argument("output", type=Path)
    parser.add_argument("--seconds", type=int, default=480)
    parser.add_argument("--fps", type=int, default=4)
    parser.add_argument("--language", choices=LABELS, required=True)
    parser.add_argument("--transcript", type=Path, action="append", default=[],
                        help="Dedicated Codex exec JSONL event file. Repeat in show order.")
    parser.add_argument("--stop-file", type=Path, help="Stop cleanly when a new marker file appears.")
    args = parser.parse_args()
    if args.seconds < 1 or not 1 <= args.fps <= 30:
        parser.error("Specify a positive duration and 1–30 frames per second.")
    record(str(args.target), str(args.scratch), args.seconds, args.fps, args.language, args.output, args.transcript, args.stop_file)


if __name__ == "__main__":
    main()
