import os
import re
from urllib.parse import parse_qs, urlparse

from flask import Flask, jsonify, request
from youtube_transcript_api import YouTubeTranscriptApi

app = Flask(__name__)


@app.after_request
def allow_trace_note_origin(response):
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


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/transcripts")
def transcripts():
    identifier = video_id(request.args.get("url", ""))
    if not identifier:
        return jsonify(error="请输入有效的 YouTube 视频链接。"), 400

    preferred = request.args.get("lang", "").strip()
    try:
        api = YouTubeTranscriptApi()
        transcript_list = api.list(identifier)
        available = list(transcript_list)
        if not available:
            return jsonify(error="该视频没有可用字幕。"), 422

        selected = None
        if preferred:
            try:
                selected = transcript_list.find_transcript([preferred])
            except Exception:
                selected = None
        selected = selected or available[0]
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
                "language": selected.language_code,
                "count": len(segments),
                "segments": segments,
            },
        )
    except Exception as exc:
        message = str(exc)
        status = 422 if "transcript" in message.lower() or "caption" in message.lower() else 502
        return jsonify(error="暂时无法获取该视频字幕。", detail=message[:300]), status


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "10000")))
