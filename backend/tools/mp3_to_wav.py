import pydub
import os
import sys

# フォルダの中のmp3ファイルをまとめてwavに変換するスクリプト
def convert_mp3_to_wav(input_folder, output_folder):
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    for filename in os.listdir(input_folder):
        if filename.endswith('.mp3'):
            mp3_path = os.path.join(input_folder, filename)
            wav_filename = os.path.splitext(filename)[0] + '.wav'
            wav_path = os.path.join(output_folder, wav_filename)

            # mp3ファイルを読み込み、wav形式で保存
            audio = pydub.AudioSegment.from_mp3(mp3_path)
            audio.export(wav_path, format='wav')
            print(f'Converted: {mp3_path} to {wav_path}')

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python mp3_to_wav.py <input_folder> <output_folder>")
        sys.exit(1)

    input_folder = sys.argv[1]
    output_folder = sys.argv[2]

    convert_mp3_to_wav(input_folder, output_folder)