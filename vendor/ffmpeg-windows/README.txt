FFmpeg 9.0.2 - x264-only static Windows x86_64 build

Built locally on 2026-11-01 from FFmpeg n9.0.2 and x264 commit
0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee (API 164).
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
ffmpeg.exe  0a47a1e8d711501ff6f81fcab3c8b2f6df388c66c6b1c8acc658545c5667639b
ffprobe.exe da192769f8b80915fa90af3b681c3689ebb2308cac93e3310170ab7c1d7b553f

Repository-relative build and verification records:
  build/ffmpeg-x264-0480cb05/audit/
Corresponding source archives:
  build/ffmpeg-x264-0480cb05/audit/ffmpeg-source.tar.gz
  build/ffmpeg-x264-0480cb05/audit/x264-source.tar.gz
Archive containing binaries, licenses, sources and audit records:
  build/ffmpeg-x264-0480cb05/ffmpeg-x264-0480cb05.zip
Rebuild script:
  scripts/build_ffmpeg_x264.sh
Distribution review:
  Documentation/ffmpeg-distribution-audit.md

This exact build is approved for redistribution with the corresponding source
archives and notices in the same GitHub Release. Approval is limited to the
build identified by Documentation/ffmpeg-x264-only-manifest.json; it is not
legal advice or a warranty of third-party rights.
