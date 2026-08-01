# YouTube Transcript Service

Small HTTP service for fetching public YouTube captions without downloading video files.

## Endpoints

- `GET /health`
- `GET /api/transcripts?url=<youtube-url>&lang=en`

The service returns available caption languages and timestamped segments.
