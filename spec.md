# TTS CLI — Multi-Voice Podcast Spec (kokoro-onnx)

## 1. Format File Teks (`script.txt`)
Setiap baris: `<SPEAKER>: <teks>`. Prefix kapital + titik dua. Bahasa Inggris (voices English only).

```
RIAN: Welcome to the podcast. Today we explore natural text to speech.
BOB: Glad to be here. Kokoro sounds far more human than older engines.
```

## 2. Environment (`shell.nix`)
- `uv` + `python312` + `portaudio` + `stdenv.cc.cc.lib` (runtime libs untuk wheel manylinux) + `espeak-ng` + `ffmpeg`.
- `shellHook`: bikin `.venv` (sekali) lalu `uv pip install` wheel prebuilt: `kokoro-onnx espeakng-loader sounddevice soundfile numpy onnxruntime phonemizer`. Nol compile (download aja). Jalan cepat.
- `KOKORO_ESPEAK_LIB`/`KOKORO_ESPEAK_DATA`/`PHONEMIZER_ESPEAK_LIBRARY` -> espeak-ng sistem (offline, tanpa download runtime).
- Catatan: nixpkgs over-specify `csvw->frictionless->aiokafka->cramjam` (Rust) + `scipy` (Fortran); pip install dep asli kokoro yang bersih, jadi hindari compile berat itu.

## 3. Pemetaan Suara (English Only)
- Speaker A (`RIAN`, `BOB`) -> `am_michael` (atau `bm_george`). Default `--voice-a am_michael`.
- Speaker B (`DINA`, `ALICE`) -> `af_sarah` (atau `bf_emma`). Default `--voice-b af_sarah`.
- Prefix lain / tanpa prefix -> `[WARN]` skip baris.

## 4. Logika Wrapper (`tts_podcast.py`)
- Parse `script.txt` baris demi baris.
- Deteksi speaker via prefix, map ke voice kokoro.
- Load `Kokoro(model, voices, espeak_config)` sekali; `kokoro.create(text, voice, speed, lang="en-us")` -> `(samples, rate)`.
- Tulis `.wav` temporary per baris via `soundfile`.
- Concat semua segmen -> 1 file `.mp3` via `ffmpeg -f concat -safe 0 -c:a libmp3lame`.
- Hapus direktori temporary via `finally`/`shutil.rmtree`.

## 5. Aset Model (wajib, download sekali)
```
wget https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.onnx
wget https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin
```

## 6. Ketentuan
- Jalankan: `nix-shell --run 'python3 tts_podcast.py script.txt podcast.mp3'`.
- Log strictly `[LEVEL] message`; level: `INFO` `WARN` `ERROR` `DEBUG`.
- Validasi input + aset di boundary. Baris kosong di-skip.
- Tanpa fluff/tutorial/joke/komentar tak perlu.
