#!/usr/bin/env python3
"""Two-person podcast generator using Chatterbox TTS (local, free, natural).

Chatterbox has a single built-in expressive voice. To get two distinct speakers,
pass --ref-a / --ref-b with short reference clips to clone each voice. With no
references, both speakers use the built-in default voice.

Video mode (--bg): composites the generated audio over a background video with
karaoke-style ASS subtitles and an optional hook banner.
"""

import argparse
import os
import re
import shutil
import subprocess

import torch
import torchaudio

import perth
from chatterbox.tts import ChatterboxTTS

from video_renderer import build_word_data, render_video


class _NoWatermarker:
    """Fallback when perth's implicit watermarker is unavailable (e.g. no pkg_resources)."""

    def apply_watermark(self, wav, sample_rate=None, **kwargs):
        return wav


if getattr(perth, "PerthImplicitWatermarker", None) is None:
    perth.PerthImplicitWatermarker = _NoWatermarker


# Hardcoded two-person conversation: exactly these speakers.
SPEAKER_A = "HOST"
SPEAKER_B = "GUEST"
LINE_RE = re.compile(r"^([A-Za-z]+):[ \t]*(.*)$")
HOOK_RE = re.compile(r"^HOOK:[ \t]*(.*)$")

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


def log(level: str, msg: str) -> None:
    print(f"[{level}] {msg}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Chatterbox-TTS two-person podcast generator")
    p.add_argument("--ref-a", default=None, help="Reference wav to clone HOST's voice")
    p.add_argument("--ref-b", default=None, help="Reference wav to clone GUEST's voice")
    p.add_argument("--device", default="cpu")
    p.add_argument("--exaggeration", type=float, default=0.5)
    p.add_argument("--temperature", type=float, default=0.8)
    p.add_argument("--bg", default=None, help="Background video path for video rendering")
    p.add_argument("--font-dir", default=None, help="Directory with custom font files")
    return p.parse_args()


def resolve_ref(speaker: str, ref_a: str | None, ref_b: str | None) -> str | None:
    if speaker == SPEAKER_A:
        return ref_a
    if speaker == SPEAKER_B:
        return ref_b
    return None


def validate_assets(ref_a: str | None, ref_b: str | None) -> None:
    for path in (ref_a, ref_b):
        if path and not os.path.isfile(path):
            log("ERROR", f"Reference audio not found: {path}")
            raise SystemExit(1)


def pick_random_bg() -> str:
    input_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "input")
    if not os.path.isdir(input_dir):
        log("ERROR", f"Input directory not found: {input_dir}")
        raise SystemExit(1)
    mp4s = [f for f in os.listdir(input_dir) if f.lower().endswith(".mp4")]
    if not mp4s:
        log("ERROR", "No .mp4 files found in input/ folder. Add a background video or pass --bg.")
        raise SystemExit(1)
    import random
    choice = random.choice(mp4s)
    path = os.path.join(input_dir, choice)
    log("INFO", f"Auto-selected background video: {choice}")
    return path


def to_mp3(wav_path: str, output: str) -> None:
    if not shutil.which("ffmpeg"):
        log("ERROR", "ffmpeg not found in PATH")
        raise SystemExit(1)
    cmd = [
        "ffmpeg", "-y", "-i", wav_path,
        "-c:a", "libmp3lame", "-q:a", "2", output,
    ]
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if res.returncode != 0:
        log("ERROR", "ffmpeg mp3 encode failed")
        raise SystemExit(1)


def main() -> None:
    args = parse_args()
    validate_assets(args.ref_a, args.ref_b)

    script_path = os.path.join("input", "script.txt")
    if not os.path.isfile(script_path):
        log("ERROR", f"Input file not found: {script_path}")
        raise SystemExit(1)

    if not args.ref_a and not args.ref_b:
        log("WARN", "No reference clips given: both speakers will use the default voice")

    video_mode = True
    if not args.bg:
        args.bg = pick_random_bg()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    script_hook = None

    log("INFO", f"Loading Chatterbox on device={args.device}")
    model = ChatterboxTTS.from_pretrained(device=args.device)
    sr = model.sr

    segs: list[torch.Tensor] = []
    gap = torch.zeros(int(sr * 0.35)).unsqueeze(0)
    idx = 0
    skipped = 0
    segments: list[dict] = []
    current_time = 0.0

    with open(script_path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line.strip():
                continue
            hook_m = HOOK_RE.match(line)
            if hook_m:
                script_hook = hook_m.group(1).strip()
                continue
            m = LINE_RE.match(line)
            if not m:
                log("WARN", f"Skipping unparsed line: {line}")
                skipped += 1
                continue
            speaker, text = m.group(1), m.group(2)
            if speaker not in (SPEAKER_A, SPEAKER_B):
                log("WARN", f"Unknown speaker '{speaker}', skipping line")
                skipped += 1
                continue
            if not text.strip():
                continue

            ref = resolve_ref(speaker, args.ref_a, args.ref_b)
            wav = model.generate(
                text,
                audio_prompt_path=ref,
                exaggeration=args.exaggeration,
                temperature=args.temperature,
            )
            seg_duration = wav.shape[1] / sr
            seg_start = current_time
            seg_end = current_time + seg_duration

            if segs:
                segs.append(gap)
                current_time += gap.shape[1] / sr
                seg_start = current_time
                seg_end = current_time + seg_duration

            segs.append(wav)
            segments.append({
                "text": text,
                "speaker": speaker,
                "start": seg_start,
                "end": seg_end,
            })
            current_time = seg_end
            idx += 1
            label = os.path.basename(ref) if ref else "default"
            log("INFO", f"Segment {idx} ({speaker}/{label}) written")

    if idx == 0:
        log("ERROR", f"No valid dialogue segments found in {script_path}")
        raise SystemExit(1)

    base_name = sanitize_filename(script_hook) if script_hook else "podcast"
    video_output = os.path.join(OUTPUT_DIR, f"{base_name}.mp4")
    audio_output = os.path.join(OUTPUT_DIR, f"{base_name}.mp3")

    combined = torch.cat(segs, dim=1)
    tmp_wav = os.path.join(OUTPUT_DIR, f"{base_name}.tmp.wav")
    torchaudio.save(tmp_wav, combined.cpu(), sr)

    word_data = build_word_data(segments)
    hook = script_hook
    render_video(
        audio_path=tmp_wav,
        bg_video=args.bg,
        output_path=video_output,
        word_data=word_data,
        start_time=0.0,
        end_time=current_time,
        hook_text=hook,
        font_dir=args.font_dir,
    )
    to_mp3(tmp_wav, audio_output)
    os.remove(tmp_wav)
    log("INFO", f"Video ready: {video_output} (segments={idx}, skipped={skipped})")
    log("INFO", f"Audio ready: {audio_output}")


if __name__ == "__main__":
    main()
