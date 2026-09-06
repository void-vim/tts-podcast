#!/usr/bin/env python3
"""Two-person podcast generator using Chatterbox TTS (local, free, natural).

Chatterbox has a single built-in expressive voice. To get two distinct speakers,
pass --ref-a / --ref-b with short reference clips to clone each voice. With no
references, both speakers use the built-in default voice.
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


def log(level: str, msg: str) -> None:
    print(f"[{level}] {msg}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Chatterbox-TTS two-person podcast generator")
    p.add_argument("input", nargs="?", default="script.txt")
    p.add_argument("output", nargs="?", default="podcast.mp3")
    p.add_argument("--device", default="cpu")
    p.add_argument("--ref-a", default=None, help="Reference wav to clone HOST's voice")
    p.add_argument("--ref-b", default=None, help="Reference wav to clone GUEST's voice"))
    p.add_argument("--exaggeration", type=float, default=0.5)
    p.add_argument("--temperature", type=float, default=0.8)
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

    if not os.path.isfile(args.input):
        log("ERROR", f"Input file not found: {args.input}")
        raise SystemExit(1)

    if not args.ref_a and not args.ref_b:
        log("WARN", "No reference clips given: both speakers will use the default voice")

    log("INFO", f"Loading Chatterbox on device={args.device}")
    model = ChatterboxTTS.from_pretrained(device=args.device)
    sr = model.sr

    segs: list[torch.Tensor] = []
    gap = torch.zeros(int(sr * 0.35)).unsqueeze(0)  # short pause between turns
    idx = 0
    skipped = 0

    with open(args.input, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if not line.strip():
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
            if segs:
                segs.append(gap)
            segs.append(wav)
            idx += 1
            label = os.path.basename(ref) if ref else "default"
            log("INFO", f"Segment {idx} ({speaker}/{label}) written")

    if idx == 0:
        log("ERROR", f"No valid dialogue segments found in {args.input}")
        raise SystemExit(1)

    combined = torch.cat(segs, dim=1)
    tmp_wav = args.output.rsplit(".", 1)[0] + ".tmp.wav"
    torchaudio.save(tmp_wav, combined.cpu(), sr)
    to_mp3(tmp_wav, args.output)
    os.remove(tmp_wav)
    log("INFO", f"Output ready: {args.output} (segments={idx}, skipped={skipped})")


if __name__ == "__main__":
    main()
