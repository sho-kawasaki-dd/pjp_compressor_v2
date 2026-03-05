import pydub
import sys
from pathlib import Path

# フォルダの中のmp3ファイルをまとめてwavに変換するスクリプト
def convert_mp3_to_wav(input_folder, output_folder):
    input_dir = Path(input_folder)
    output_dir = Path(output_folder)
    output_dir.mkdir(parents=True, exist_ok=True)

    for mp3_path in input_dir.iterdir():
        if mp3_path.is_file() and mp3_path.suffix.lower() == '.mp3':
            wav_path = output_dir / f"{mp3_path.stem}.wav"

            # mp3ファイルを読み込み、wav形式で保存
            audio = pydub.AudioSegment.from_mp3(str(mp3_path))
            audio.export(str(wav_path), format='wav')
            print(f'Converted: {mp3_path} to {wav_path}')

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python mp3_to_wav.py <input_folder> <output_folder>")
        sys.exit(1)

    input_folder = sys.argv[1]
    output_folder = sys.argv[2]

    convert_mp3_to_wav(input_folder, output_folder)