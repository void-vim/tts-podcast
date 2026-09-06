# tts-podcast

Generate a two-person podcast dialogue script using local TTS.

## Setup

```bash
nix develop
```

## Usage

```bash
# Generate video with random background from input/
python tts_podcast.py

# With reference voices
python tts_podcast.py --ref-a host.wav --ref-b guest.wav
```

## Script format

File: `input/script.txt`

```
HOOK: Sleep is a scam

HOST: Today we are discussing sleep. Most of you do it wrong.
GUEST: Wait, what's wrong with sleep? It's basic biology.
HOST: You lie down in a bed. You close your eyes.
GUEST: That's literally the point of resting.
```

- The `HOOK:` line is optional and is used as the video headline and output filename.
- Only `HOST:` and `GUEST:` lines are spoken.
- Blank lines and unparsed lines are ignored.

## Output

- Audio: `output/<name>.mp3`
- Video: `output/<name>.mp4`
- If no `HOOK:` is provided, the default name is `podcast`.

## Input assets

Place background videos in `input/`. Example files:

- `input/minecraft.mp4`
- `input/subwaysurf.mp4`
