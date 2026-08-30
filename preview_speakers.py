#!/usr/bin/env python3
"""Generate short preview clips for XTTS v2 built-in speakers."""

import argparse
import os

import soundfile as sf
from TTS.api import TTS

MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"
SAMPLE = "Hi, I am a built-in XTTS voice. Use me for your podcast if you like how I sound."
DEFAULTS = [
    "Damien Black", "Andrew Chipper", "Craig Gutsy", "Royston Min",
    "Viktor Eka", "Luis Moray", "Marcos Rudaski", "Claribel Dervla",
    "Gracie Wise", "Ana Florence", "Alison Dietlinde", "Sofia Hellen",
]


def log(level: str, msg: str) -> None:
    print(f"[{level}] {msg}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="XTTS speaker preview generator")
    p.add_argument("--out", default="previews")
    p.add_argument("--text", default=SAMPLE)
    p.add_argument("--speakers", nargs="*", default=DEFAULTS)
    p.add_argument("--device", default="cpu")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    os.makedirs(args.out, exist_ok=True)
    model = TTS(MODEL_NAME).to(args.device)
    available = set(model.speakers or [])
    sr = model.synthesizer.output_sample_rate

    for name in args.speakers:
        if name not in available:
            log("WARN", f"Skipping unknown speaker: {name}")
            continue
        wav = model.tts(text=args.text, speaker=name, language="en")
        path = os.path.join(args.out, f"{name.replace(' ', '_')}.wav")
        sf.write(path, wav, sr)
        log("INFO", f"Preview written: {path}")


if __name__ == "__main__":
    main()
