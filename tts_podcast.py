#!/usr/bin/env python3
"""Multi-voice podcast generator using kokoro-onnx + ffmpeg."""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

import soundfile as sf
from kokoro_onnx import EspeakConfig, Kokoro

# Hardcoded two-person conversation: exactly these speakers.
SPEAKER_A = "RIAN"
SPEAKER_B = "BOB"
LINE_RE = re.compile(r"^([A-Za-z]+):[ \t]*(.*)$")


def log(level: str, msg: str) -> None:
    print(f"[{level}] {msg}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Kokoro-onnx multi-voice podcast TTS")
    p.add_argument("input", nargs="?", default="script.txt")
    p.add_argument("output", nargs="?", default="podcast.mp3")
    p.add_argument("--model", default="kokoro-v1.0.onnx")
    p.add_argument("--voices", default="voices-v1.0.bin")
    p.add_argument("--voice-a", default="am_adam")
    p.add_argument("--voice-b", default="af_heart")
    p.add_argument("--speed", type=float, default=1.0)
    return p.parse_args()


def resolve_voice(speaker: str, voice_a: str, voice_b: str) -> str | None:
    if speaker == SPEAKER_A:
        return voice_a
    if speaker == SPEAKER_B:
        return voice_b
    return None


def build_espeak_config() -> EspeakConfig | None:
    lib = os.environ.get("KOKORO_ESPEAK_LIB")
    data = os.environ.get("KOKORO_ESPEAK_DATA")
    if lib or data:
        return EspeakConfig(lib_path=lib, data_path=data)
    return None


def write_wav(path: str, samples, rate: int) -> None:
    sf.write(path, samples, rate)


def concat_segments(list_file: str, output: str) -> None:
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", list_file, "-c:a", "libmp3lame", "-q:a", "2", output,
    ]
    if not shutil.which("ffmpeg"):
        log("ERROR", "ffmpeg not found in PATH")
        raise SystemExit(1)
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if res.returncode != 0:
        log("ERROR", "ffmpeg concat failed")
        raise SystemExit(1)


def validate_assets(model: str, voices: str) -> None:
    for path in (model, voices):
        if not os.path.isfile(path):
            log("ERROR", f"Asset not found: {path}")
            raise SystemExit(1)


def main() -> None:
    args = parse_args()
    validate_assets(args.model, args.voices)

    if not os.path.isfile(args.input):
        log("ERROR", f"Input file not found: {args.input}")
        raise SystemExit(1)

    tmp = tempfile.mkdtemp(prefix="tts-podcast-")
    list_file = os.path.join(tmp, "concat.txt")

    try:
        kokoro = Kokoro(args.model, args.voices, espeak_config=build_espeak_config())
        log("INFO", f"Loaded model={args.model} voices={args.voices}")

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
                voice = resolve_voice(speaker, args.voice_a, args.voice_b)
                if voice is None:
                    log("WARN", f"Unknown speaker '{speaker}', skipping line")
                    skipped += 1
                    continue
                if not text.strip():
                    continue
                samples, rate = kokoro.create(
                    text, voice=voice, speed=args.speed, lang="en-us"
                )
                idx += 1
                seg = os.path.join(tmp, f"{idx:04d}.wav")
                write_wav(seg, samples, rate)
                with open(list_file, "a", encoding="utf-8") as lf:
                    lf.write(f"file '{seg}'\n")
                log("INFO", f"Segment {idx} ({speaker}/{voice}) written")

        if idx == 0:
            log("ERROR", f"No valid dialogue segments found in {args.input}")
            raise SystemExit(1)

        concat_segments(list_file, args.output)
        log("INFO", f"Output ready: {args.output} (segments={idx}, skipped={skipped})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
