"""フォルダ内の MP3 を一括で WAV へ変換する小さな補助スクリプト。

本体アプリの圧縮パイプラインには入っておらず、配布用サウンド素材の前処理を
手早く行うための開発補助ツールとして置いている。
"""

import pydub
import sys
from pathlib import Path

def convert_mp3_to_wav(input_folder, output_folder):
    """入力フォルダ直下の MP3 を走査し、同名 WAV を出力フォルダへ生成する。

    サウンド素材の数が少ない前提なので、再帰探索や並列化よりも、失敗箇所が追いやすい
    単純な逐次変換を優先する。
    """
    input_dir = Path(input_folder)
    output_dir = Path(output_folder)
    output_dir.mkdir(parents=True, exist_ok=True)

    for mp3_path in input_dir.iterdir():
        if mp3_path.is_file() and mp3_path.suffix.lower() == '.mp3':
            wav_path = output_dir / f"{mp3_path.stem}.wav"

            # 変換はファイル単位で独立しているため、失敗時の影響範囲が小さい単純ループにしている。
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