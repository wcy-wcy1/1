import base64
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from flask import Flask, jsonify, request
from youtube_transcript_api import YouTubeTranscriptApi

app = Flask(__name__)


@app.after_request
def allow_trace_note_origin(response):
    # This service is intentionally local-only in the free MVP. Allow the
    # published Trace Note page to call localhost, but do not open it to every
    # origin.
    if request.headers.get("Origin") == "https://trace-note-youtube-ai.hif790.chatgpt.site":
        response.headers["Access-Control-Allow-Origin"] = "https://trace-note-youtube-ai.hif790.chatgpt.site"
    response.headers["Vary"] = "Origin"
    return response


def video_id(value: str) -> str | None:
    value = (value or "").strip()
    if re.fullmatch(r"[\w-]{11}", value):
        return value
    try:
        parsed = urlparse(value)
        if parsed.netloc in {"youtu.be", "www.youtu.be"}:
            candidate = parsed.path.strip("/").split("/")[0]
        else:
            candidate = parse_qs(parsed.query).get("v", [None])[0]
            if not candidate:
                match = re.search(r"/(?:shorts|embed)/([\w-]{11})", parsed.path)
                candidate = match.group(1) if match else None
        return candidate if candidate and re.fullmatch(r"[\w-]{11}", candidate) else None
    except ValueError:
        return None


def deep_mode_status() -> dict:
    missing = []
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        missing.append("yt-dlp")
    try:
        from faster_whisper import WhisperModel  # noqa: F401
    except ImportError:
        missing.append("faster-whisper")
    try:
        import imageio_ffmpeg  # noqa: F401
    except ImportError:
        missing.append("imageio-ffmpeg")
    return {"available": not missing, "missing": missing}


def transcribe_with_whisper(source_url: str) -> tuple[list[dict], str]:
    status = deep_mode_status()
    if not status["available"]:
        raise RuntimeError("深度模式尚未安装：" + "、".join(status["missing"]))
    import imageio_ffmpeg
    import yt_dlp
    from faster_whisper import WhisperModel
    workdir = Path(tempfile.mkdtemp(prefix="trace-note-"))
    try:
        # Some YouTube uploads do not expose an audio-only format to all
        # clients. Falling back to the best available stream is more robust;
        # ffmpeg can still hand its audio track to Whisper.
        options = {"format": "bestaudio/best", "outtmpl": str(workdir / "media.%(ext)s"), "noplaylist": True, "quiet": True, "no_warnings": True, "ffmpeg_location": imageio_ffmpeg.get_ffmpeg_exe()}
        with yt_dlp.YoutubeDL(options) as downloader:
            downloader.extract_info(source_url, download=True)
        audio_files = [path for path in workdir.iterdir() if path.is_file()]
        if not audio_files:
            raise RuntimeError("未能获取可转写的音频。")
        model = WhisperModel(os.environ.get("WHISPER_MODEL", "base"), compute_type="int8")
        segments, info = model.transcribe(str(audio_files[0]), vad_filter=True)
        result = [{"start": round(segment.start, 2), "duration": round(segment.end - segment.start, 2), "text": segment.text.strip()} for segment in segments if segment.text.strip()]
        if not result:
            raise RuntimeError("Whisper 未返回可用文字稿。")
        return result, info.language or "unknown"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def extract_keyframes(source_url: str, timestamps: list[float]) -> list[dict]:
    status = deep_mode_status()
    if not status["available"]:
        raise RuntimeError("关键帧模式尚未安装：" + "、".join(status["missing"]))
    import imageio_ffmpeg
    import yt_dlp
    workdir = Path(tempfile.mkdtemp(prefix="trace-note-frames-"))
    try:
        options = {"format": "bestvideo[height<=480]/best[height<=480]/worst", "outtmpl": str(workdir / "video.%(ext)s"), "noplaylist": True, "quiet": True, "no_warnings": True, "ffmpeg_location": imageio_ffmpeg.get_ffmpeg_exe()}
        with yt_dlp.YoutubeDL(options) as downloader:
            downloader.extract_info(source_url, download=True)
        media_files = [path for path in workdir.iterdir() if path.is_file() and path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}]
        if not media_files:
            raise RuntimeError("未能获取可提取画面的媒体文件。")
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        frames = []
        for index, timestamp in enumerate(timestamps):
            output = workdir / f"frame-{index}.jpg"
            completed = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-ss", str(timestamp), "-i", str(media_files[0]), "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "4", "-y", str(output)], capture_output=True, text=True, timeout=90)
            if completed.returncode == 0 and output.exists():
                encoded = base64.b64encode(output.read_bytes()).decode("ascii")
                frames.append({"time": round(timestamp, 2), "image": "data:image/jpeg;base64," + encoded})
        if not frames:
            raise RuntimeError("视频已下载，但没有成功提取关键画面。")
        return frames
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/capabilities")
def capabilities():
    return {"transcript": True, "keyframes": True, "deepMode": deep_mode_status()}



@app.get("/api/keyframes")
def keyframes():
    identifier = video_id(request.args.get("url", ""))
    if not identifier:
        return jsonify(error="请输入有效的 YouTube 视频链接。"), 400
    raw_times = request.args.get("times", "").split(",")
    try:
        timestamps = sorted({max(0.0, float(value)) for value in raw_times if value.strip()})[:6]
    except ValueError:
        return jsonify(error="关键帧时间点格式不正确。"), 400
    if not timestamps:
        return jsonify(error="请至少提供一个关键帧时间点。"), 400
    try:
        frames = extract_keyframes(request.args.get("url", ""), timestamps)
        return jsonify(video={"id": identifier}, count=len(frames), frames=frames)
    except RuntimeError as exc:
        return jsonify(error=str(exc)), 422
    except Exception as exc:
        return jsonify(error="暂时无法提取关键画面：" + str(exc)[:180]), 502
def whisper_response(identifier: str, source_url: str):
    segments, detected_language = transcribe_with_whisper(source_url)
    return jsonify(video={"id": identifier, "sourceUrl": f"https://www.youtube.com/watch?v={identifier}"}, captions={"languages": [{"code": detected_language, "name": detected_language, "generated": True}], "language": detected_language, "source": "whisper", "count": len(segments), "segments": segments})


@app.get("/api/transcripts")
def transcripts():
    identifier = video_id(request.args.get("url", ""))
    if not identifier:
        return jsonify(error="请输入有效的 YouTube 视频链接。"), 400

    preferred = request.args.get("lang", "").strip()
    use_whisper_fallback = request.args.get("fallback", "") == "whisper"
    try:
        api = YouTubeTranscriptApi()
        try:
            transcript_list = api.list(identifier)
            available = list(transcript_list)
        except Exception:
            if use_whisper_fallback:
                return whisper_response(identifier, request.args.get("url", ""))
            raise
        if not available:
            if not use_whisper_fallback:
                return jsonify(error="该视频没有可用字幕。可选择深度模式进行本地 Whisper 转写。"), 422
            return whisper_response(identifier, request.args.get("url", ""))

        # A creator-provided transcript is usually more accurate than YouTube's
        # automatic captions. Prefer it globally and within the requested
        # language, falling back to generated captions only when necessary.
        manual = [item for item in available if not item.is_generated]
        selected = None
        if preferred:
            for item in manual + available:
                if item.language_code == preferred:
                    selected = item
                    break
        selected = selected or (manual or available)[0]
        fetched = selected.fetch()
        segments = [
            {"start": round(item.start, 2), "duration": round(item.duration, 2), "text": item.text.replace("\n", " ").strip()}
            for item in fetched
            if item.text.strip()
        ]
        return jsonify(
            video={"id": identifier, "sourceUrl": f"https://www.youtube.com/watch?v={identifier}"},
            captions={
                "languages": [
                    {"code": item.language_code, "name": item.language, "generated": item.is_generated}
                    for item in available
                ],
                "language": selected.language_code, "source": "manual" if not selected.is_generated else "auto",
                "count": len(segments),
                "segments": segments,
            },
        )
    except RuntimeError as exc:
        return jsonify(error=str(exc)), 422
    except Exception as exc:
        message = str(exc)
        if use_whisper_fallback:
            return jsonify(error="本地 Whisper 暂时无法下载这个视频的媒体流：" + message[:180]), 502
        status = 422 if "transcript" in message.lower() or "caption" in message.lower() else 502
        return jsonify(error="暂时无法获取该视频字幕。", detail=message[:300]), status


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8765")))

