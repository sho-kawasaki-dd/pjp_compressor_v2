FFmpeg 9.0.2 - x264-only static Windows x86_64 build

Built locally on 2026-11-01 from FFmpeg n9.0.2 and x264-master (API 164).
The optional external media library is x264 only. General built-in codecs,
filters and containers remain enabled; this is not a minimum-size build.
H.264 (libx264/libx264rgb) and built-in AAC encoding are enabled.
HEVC encoders, decoders, parsers and HEVC-specific bitstream filters and raw
containers are disabled. Container metadata may still identify HEVC streams.
Network, ffplay, avdevice and hardware acceleration are disabled.

License: GNU GPL version 3 or later. See LICENSE and licenses/.
The supplied FFmpeg and x264 sources were built without source patches.
This software is based in part on the work of the Independent JPEG Group.

SHA256:
ffmpeg.exe  dd8bb87fbd05be31c17c37ce2fa2e8b910ceacd4ed5bccdccb8f43e4fd8bfa7d
ffprobe.exe df293436b81eda08b3b4101a9d18a2659f50d8d0bf7c8f1637e5765c378e1a89

Repository-relative build and verification records:
  build/ffmpeg-x264-only/audit/
Corresponding source archives:
  build/ffmpeg-x264-only/audit/ffmpeg-source.tar.gz
  build/ffmpeg-x264-only/audit/x264-source.tar.gz
Archive containing binaries, licenses, sources and audit records:
  build/ffmpeg-x264-only/ffmpeg-x264-only.zip
Rebuild script:
  scripts/build_ffmpeg_x264.sh
Distribution review:
  Documentation/ffmpeg-distribution-audit.md

Local replacement does not constitute approval for redistribution.
Runtime bundled fallback and packaging exclusions remain unchanged.
