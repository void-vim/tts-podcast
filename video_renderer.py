"""Video renderer: ASS subtitles, background video composition.

Generates word-level timestamps from TTS segments, builds a karaoke-style
ASS file, and composites it over a looping 9:16 background video via ffmpeg.
"""

import os
import subprocess


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def log(level: str, msg: str) -> None:
    print(f"[{level}] {msg}")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
HOOK_FONTSIZE = 80
WORDS_PER_CHUNK = 1
FONT_NAME = "Coolvetica"
WATERMARK_TEXT = "uncookedtakes"

# Default font dir sits next to this file under input/font/
MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FONT_DIR = os.path.join(MODULE_DIR, "input", "font")

OUTPUT_DIR = os.path.join(MODULE_DIR, "output")


# ---------------------------------------------------------------------------
# Utils
# ---------------------------------------------------------------------------
def escape_ass_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def format_ass_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def escape_filter_path(path: str) -> str:
    path = path.replace("\\", "/")
    path = path.replace(":", "\\:")
    return path


def sanitize_filename(text: str) -> str:
    text = text.strip().replace(" ", "-")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
    return "".join(c for c in text if c in allowed)


def wrap_hook_text(text: str, max_chars_per_line: int = 22) -> str:
    if len(text) <= max_chars_per_line:
        return text
    words = text.split()
    line1, line2 = [], []
    current = line1
    length = 0
    for w in words:
        if current is line1 and length + len(w) + 1 > max_chars_per_line and line1:
            current = line2
            length = 0
        current.append(w)
        length += len(w) + 1
    return " ".join(line1) + "\n" + " ".join(line2)


# ---------------------------------------------------------------------------
# Word-level timestamps (uniform distribution per segment)
# ---------------------------------------------------------------------------
def build_word_data(segments: list[dict]) -> list[dict]:
    """Evenly distribute words across each segment's actual duration."""
    word_data: list[dict] = []
    for seg in segments:
        words = seg["text"].split()
        if not words:
            continue
        seg_duration = seg["end"] - seg["start"]
        word_duration = seg_duration / len(words)
        for i, word in enumerate(words):
            word_start = seg["start"] + i * word_duration
            word_end = word_start + word_duration
            word_data.append({
                "start": word_start,
                "end": word_end,
                "text": word,
            })
    return word_data


# ---------------------------------------------------------------------------
# ASS generation
# ---------------------------------------------------------------------------
ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,{font},100,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,3,0,5,10,10,10,1
Style: HookText,{font},{hook_fontsize},&H000000,&H000000,&HFFFFFF,&H00000000,-1,0,0,0,100,100,0,0,1,25,0,8,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def create_ass_file(
    word_data: list[dict],
    start_time: float,
    end_time: float,
    ass_path: str,
    hook_text: str | None = None,
) -> None:
    log("INFO", f"Writing karaoke ASS subtitle file to: {ass_path}")

    words_in_range = [w for w in word_data if w["end"] > start_time and w["start"] < end_time]
    duration = end_time - start_time
    header = ASS_HEADER.format(font=FONT_NAME, hook_fontsize=HOOK_FONTSIZE)
    events = _build_hook_events(hook_text, duration) if hook_text else []
    events.extend(_build_karaoke_events(word_data, start_time, end_time, words_in_range))

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(header)
        f.write("\n".join(events))
        f.write("\n")


def _build_hook_events(hook_text: str | None, duration: float) -> list[str]:
    if not hook_text:
        return []
    events: list[str] = []
    hook_end = format_ass_timestamp(duration)
    wrapped = wrap_hook_text(hook_text)
    lines = wrapped.split("\n")
    line_count = len(lines)
    fontsize = HOOK_FONTSIZE
    char_width_ratio = 0.56
    longest_line = max(lines, key=len)
    text_w_est = len(longest_line) * fontsize * char_width_ratio
    padding_x = 50
    padding_y = 45
    box_w = min(1080 - 80, text_w_est + padding_x * 2)
    line_height = fontsize * 1.4
    box_h = line_height * line_count + padding_y * 2
    box_x = (1080 - box_w) / 2
    box_y = 90

    ass_text = escape_ass_text(wrapped).replace("\n", "\\N")
    text_x = 1080 / 2
    text_y = box_y + padding_y
    events.append(
        f"Dialogue: 1,0:00:00.00,{hook_end},HookText,,0,0,0,,"
        f"{{\\an8\\pos({text_x:.0f},{text_y:.0f})}}{ass_text}"
    )
    return events


def _build_karaoke_events(
    word_data: list[dict],
    start_time: float,
    end_time: float,
    words_in_range: list[dict],
) -> list[str]:
    events: list[str] = []
    for i in range(0, len(words_in_range), WORDS_PER_CHUNK):
        chunk = words_in_range[i : i + WORDS_PER_CHUNK]
        if not chunk:
            continue
        for j, active_word in enumerate(chunk):
            rel_start = max(0.0, active_word["start"] - start_time)
            next_start = chunk[j + 1]["start"] if j + 1 < len(chunk) else active_word["end"]
            rel_end = max(rel_start, min(end_time - start_time, next_start - start_time))

            parts: list[str] = []
            for k, w in enumerate(chunk):
                word_text = escape_ass_text(w["text"])
                if k == j:
                    parts.append(f"{{\\c&H0000FFFF&\\fs72}}{word_text}{{\\r}}")
                else:
                    parts.append(word_text)
            line_text = " ".join(parts)

            events.append(
                f"Dialogue: 0,{format_ass_timestamp(rel_start)},{format_ass_timestamp(rel_end)},"
                f"Karaoke,,0,0,0,,{line_text}"
            )
    return events


# ---------------------------------------------------------------------------
# FFmpeg render
# ---------------------------------------------------------------------------
def execute_ffmpeg(
    audio_path: str,
    bg_video: str,
    start: float,
    duration: float,
    ass_file: str,
    out_file: str,
    fonts_dir: str | None = None,
) -> None:
    log("INFO", "Executing FFmpeg render pipeline...")

    if ass_file:
        escaped_ass = escape_filter_path(ass_file)
        if fonts_dir and os.path.isdir(fonts_dir):
            escaped_fonts_dir = escape_filter_path(fonts_dir)
            chain = f"[1:v]crop=ih*(9/16):ih,scale=1080:1920,ass={escaped_ass}:fontsdir={escaped_fonts_dir}"
        else:
            if fonts_dir:
                log("WARN", f"fonts_dir '{fonts_dir}' not found, falling back to system fonts.")
            chain = f"[1:v]crop=ih*(9/16):ih,scale=1080:1920,ass={escaped_ass}"
    else:
        chain = "[1:v]crop=ih*(9/16):ih,scale=1080:1920"

    if WATERMARK_TEXT:
        escaped_wm = escape_filter_path(WATERMARK_TEXT)
        chain += (
            f",drawtext=text='{escaped_wm}':fontcolor=white@0.6:fontsize=32:"
            "borderw=1:bordercolor=black@0.5:x=(w-tw)/2:y=(h-th)/2+100"
        )

    filter_complex = chain + "[v]"

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-t", str(duration),
        "-i", audio_path,
        "-stream_loop", "-1",
        "-ss", "0",
        "-t", str(duration),
        "-i", bg_video,
        "-filter_complex",
        filter_complex,
        "-map", "[v]",
        "-map", "0:a",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-shortest",
        out_file,
    ]

    log("DEBUG", f"FFmpeg command: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log("ERROR", f"FFmpeg failed with exit code {result.returncode}")
        log("ERROR", result.stderr[-3000:])
        raise RuntimeError("FFmpeg render failed")
    else:
        stderr_lower = result.stderr.lower()
        if any(k in stderr_lower for k in ["fontselect", "glyph not found", "cannot find font"]):
            log("WARN", "FFmpeg reported possible font issues - check stderr:")
            for line in result.stderr.splitlines():
                if any(k in line.lower() for k in ["fontselect", "glyph", "font"]):
                    log("WARN", line)


# ---------------------------------------------------------------------------
# High-level render entrypoint
# ---------------------------------------------------------------------------
def render_video(
    audio_path: str,
    bg_video: str,
    output_path: str,
    word_data: list[dict],
    start_time: float,
    end_time: float,
    hook_text: str | None = None,
    font_dir: str | None = None,
) -> str:
    duration = end_time - start_time
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

    temp_ass_file = output_path.rsplit(".", 1)[0] + ".ass"
    create_ass_file(word_data, start_time, end_time, temp_ass_file, hook_text=hook_text)

    with open(temp_ass_file, "r", encoding="utf-8") as f:
        ass_content = f.read()
    event_count = ass_content.count("Dialogue:")
    log("INFO", f"ASS file contains {event_count} dialogue events.")

    execute_ffmpeg(
        audio_path, bg_video, start_time, duration,
        temp_ass_file, output_path, fonts_dir=font_dir or DEFAULT_FONT_DIR,
    )

    if os.path.exists(temp_ass_file):
        os.remove(temp_ass_file)
        log("INFO", f"Removed temp subtitle file: {temp_ass_file}")

    log("INFO", f"Video processing completed successfully: {output_path}")
    return output_path
