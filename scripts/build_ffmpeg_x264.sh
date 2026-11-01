#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 3 ]]; then
    echo "Usage: bash build_ffmpeg_x264.sh <ffmpeg-source> <x264-source> <new-output-directory>" >&2
    exit 2
fi

ffmpeg_source=$(cygpath -au "$1")
x264_source=$(cygpath -au "$2")
output=$(cygpath -au "$3")
jobs=${JOBS:-4}
script=$(cygpath -au "${BASH_SOURCE[0]}")

for tool in gcc make nasm pkg-config ar ranlib windres tar sha256sum diff; do
    command -v "$tool" >/dev/null || { echo "Missing build tool: $tool" >&2; exit 1; }
done
for source in "$ffmpeg_source" "$x264_source"; do
    [[ -f "$source/configure" && -f "$source/Makefile" ]] || {
        echo "Incomplete source directory: $source" >&2
        exit 1
    }
done
if [[ -e "$output" ]]; then
    [[ "${RESUME:-0}" == 1 ]] || {
        echo "Output directory already exists; set RESUME=1 to continue this build: $output" >&2
        exit 1
    }
    diff -qr "$ffmpeg_source" "$output/sources/ffmpeg"
    diff -qr "$x264_source" "$output/sources/x264"
else
    mkdir -p "$output"/{sources,work/x264,work/ffmpeg,package,audit}
    cp -a "$ffmpeg_source" "$output/sources/ffmpeg"
    cp -a "$x264_source" "$output/sources/x264"
    tar -czf "$output/audit/ffmpeg-source.tar.gz" -C "$output/sources" ffmpeg
    tar -czf "$output/audit/x264-source.tar.gz" -C "$output/sources" x264
fi

cp "$script" "$output/audit/build_ffmpeg_x264.sh"
prefix=$(cygpath -am "$output/package")
export PKG_CONFIG_PATH="$output/package/lib/pkgconfig"

{
    printf 'PATH=%s\nJOBS=%s\n' "$PATH" "$jobs"
    gcc --version
    make --version
    nasm --version
    pkg-config --version
    gcc -dumpmachine
} > "$output/audit/toolchain.txt"

cd "$output/work/x264"
x264_options=(
    "--prefix=$prefix" --enable-static --disable-cli --disable-opencl
    --disable-lavf --disable-ffms --disable-gpac
)
printf '%q ' "${x264_options[@]}" > "$output/audit/x264-configure.txt"
if [[ ! -f config.mak ]]; then
    bash "$output/sources/x264/configure" "${x264_options[@]}"
fi
make -j"$jobs"
make install

cd "$output/work/ffmpeg"
ffmpeg_options=(
    --target-os=mingw32 --arch=x86_64
    "--prefix=$prefix" --enable-static --disable-shared
    --disable-autodetect --disable-ffplay --disable-doc --disable-debug
    --disable-network --disable-avdevice --disable-hwaccels
    --disable-bsf=dovi_split
    --enable-gpl --enable-version3 --enable-libx264
    --pkg-config-flags=--static --extra-ldflags=-static
)
for kind in encoders decoders parsers bsfs demuxers muxers; do
    list=$(bash "$output/sources/ffmpeg/configure" "--list-$kind")
    for component in $list; do
        if [[ "$component" == *hevc* || "$component" == libx265 ]]; then
            ffmpeg_options+=("--disable-${kind%s}=$component")
        fi
    done
done
printf '%q ' "${ffmpeg_options[@]}" > "$output/audit/ffmpeg-configure.txt"
bash "$output/sources/ffmpeg/configure" "${ffmpeg_options[@]}"
make -j"$jobs"
make install

for tool in ffmpeg ffprobe; do
    "$output/package/bin/$tool.exe" -version > "$output/audit/$tool-version.txt"
done
for mode in buildconf encoders decoders; do
    "$output/package/bin/ffmpeg.exe" -hide_banner "-$mode" > "$output/audit/$mode.txt" 2>&1
done
# FFmpeg exposes parsers through configure's generated component list, not a CLI -parsers option.
cp config_components.h "$output/audit/config_components.h"
cp config.h "$output/audit/config.h"
cp ffbuild/config.log "$output/audit/ffmpeg-config.log"
cp ffbuild/config.mak "$output/audit/ffmpeg-config.mak"
cp "$output/work/x264/config.log" "$output/audit/x264-config.log"
cp "$output/work/x264/config.mak" "$output/audit/x264-config.mak"
if grep -E '^[[:space:]]*[A-Z.]{6}[[:space:]]+[^[:space:]]*(hevc|x265)' \
    "$output/audit/encoders.txt" "$output/audit/decoders.txt"; then
    echo "Forbidden HEVC encoder/decoder found" >&2
    exit 1
fi
if grep -E '^#define CONFIG_(HEVC.*|LIBX265)_.* 1$' "$output/audit/config_components.h"; then
    echo "Forbidden HEVC component found" >&2
    exit 1
fi
grep -Eq '^[[:space:]]*V[.A-Z]{5}[[:space:]]+libx264[[:space:]]' "$output/audit/encoders.txt"
grep -Eq '^[[:space:]]*A[.A-Z]{5}[[:space:]]+aac[[:space:]]' "$output/audit/encoders.txt"
mkdir -p "$output/package/licenses"
cp "$output/sources/ffmpeg/COPYING.GPLv3" "$output/package/licenses/FFmpeg-COPYING.GPLv3"
cp "$output/sources/ffmpeg/LICENSE.md" "$output/package/licenses/FFmpeg-LICENSE.md"
cp "$output/sources/ffmpeg/CREDITS" "$output/package/licenses/FFmpeg-CREDITS"
cp "$output/sources/x264/COPYING" "$output/package/licenses/x264-COPYING"
printf '%s\n' \
    'This software is based in part on the work of the Independent JPEG Group.' \
    'For the FFmpeg n9.0.2 source used in this build, no changes, additions, or deletions were made to libavcodec/jfdctfst.c, libavcodec/jfdctint_template.c, or libavcodec/jrevdct.c.' \
    > "$output/package/licenses/NOTICE.txt"
cp "$output/sources/x264/x264.h" "$output/audit/x264.h"
cd "$output"
sha256sum package/bin/*.exe audit/*source.tar.gz audit/build_ffmpeg_x264.sh > audit/SHA256SUMS
echo "Built and audited: $output/package/bin"
