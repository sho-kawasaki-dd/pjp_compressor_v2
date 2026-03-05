from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from PIL import Image


def compress_image_pillow(input_path, output_path, quality, resize_cfg=None):
    """Pillow を用いて JPEG/PNG を品質指定で保存。必要に応じてリサイズも行う。"""
    input_file = Path(input_path)
    output_file = Path(output_path)

    try:
        img = Image.open(str(input_file))
        if resize_cfg and resize_cfg.get('enabled'):
            mode = resize_cfg.get('mode', 'manual')
            orig_w, orig_h = img.size
            if mode == 'long_edge':
                target = int(resize_cfg.get('long_edge', 0) or 0)
                if target > 0:
                    long = max(orig_w, orig_h)
                    scale = target / long
                    new_w = max(1, int(orig_w * scale))
                    new_h = max(1, int(orig_h * scale))
                    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            else:
                w = int(resize_cfg.get('width', 0) or 0)
                h = int(resize_cfg.get('height', 0) or 0)
                keep = bool(resize_cfg.get('keep_aspect', True))
                if w > 0 or h > 0:
                    if keep:
                        if w > 0 and h > 0:
                            scale = min(w / orig_w, h / orig_h)
                            new_w = max(1, int(orig_w * scale))
                            new_h = max(1, int(orig_h * scale))
                        elif w > 0:
                            scale = w / orig_w
                            new_w = w
                            new_h = max(1, int(orig_h * scale))
                        else:
                            scale = h / orig_h
                            new_h = h
                            new_w = max(1, int(orig_w * scale))
                    else:
                        new_w = w if w > 0 else orig_w
                        new_h = h if h > 0 else orig_h
                    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        img.save(str(output_file), optimize=True, quality=quality)
        msg_extra = ""
        if resize_cfg and resize_cfg.get('enabled'):
            msg_extra = f", resize={img.size[0]}x{img.size[1]}"
        return True, f"画像圧縮(Pillow): {input_file.name} → OK (quality={quality}{msg_extra})"
    except Exception as e:
        return False, f"画像失敗: {input_file.name} ({e})"


def compress_png_pngquant(input_path, output_path, quality_min, quality_max, speed=3, resize_cfg=None):
    """pngquant が利用可能ならパレット量子化で高圧縮、無ければ Pillow にフォールバック。"""
    input_file = Path(input_path)
    output_file = Path(output_path)

    pngquant_exe = shutil.which("pngquant")
    if not pngquant_exe:
        return compress_image_pillow(str(input_file), str(output_file), quality_max, resize_cfg=resize_cfg)
    tmp_path = None
    try:
        qarg = f"{quality_min}-{quality_max}"
        src_path = input_file
        resized_wh = None
        if resize_cfg and resize_cfg.get('enabled'):
            try:
                tmp_path = output_file.with_suffix(output_file.suffix + ".tmp_resize.png")
                img = Image.open(str(input_file))
                mode = resize_cfg.get('mode', 'manual')
                orig_w, orig_h = img.size
                if mode == 'long_edge':
                    target = int(resize_cfg.get('long_edge', 0) or 0)
                    if target > 0:
                        long = max(orig_w, orig_h)
                        scale = target / long
                        new_w = max(1, int(orig_w * scale))
                        new_h = max(1, int(orig_h * scale))
                        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                        resized_wh = (new_w, new_h)
                else:
                    w = int(resize_cfg.get('width', 0) or 0)
                    h = int(resize_cfg.get('height', 0) or 0)
                    keep = bool(resize_cfg.get('keep_aspect', True))
                    if w > 0 or h > 0:
                        if keep:
                            if w > 0 and h > 0:
                                scale = min(w / orig_w, h / orig_h)
                                new_w = max(1, int(orig_w * scale))
                                new_h = max(1, int(orig_h * scale))
                            elif w > 0:
                                scale = w / orig_w
                                new_w = w
                                new_h = max(1, int(orig_h * scale))
                            else:
                                scale = h / orig_h
                                new_h = h
                                new_w = max(1, int(orig_w * scale))
                        else:
                            new_w = w if w > 0 else orig_w
                            new_h = h if h > 0 else orig_h
                        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                        resized_wh = (new_w, new_h)
                img.save(str(tmp_path), optimize=True)
                src_path = tmp_path
            except Exception:
                src_path = input_file

        cmd = [
            pngquant_exe,
            f"--quality={qarg}",
            f"--speed={speed}",
            "--force",
            "--output", str(output_file),
            str(src_path),
        ]
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            text=True,
            encoding='utf-8',
            errors='replace',
        )
        if result.returncode == 0 and output_file.exists():
            msg = f"PNG圧縮(pngquant): {input_file.name} → OK (quality={qarg})"
            if resized_wh and resize_cfg and resize_cfg.get('enabled'):
                msg += f", resize={resized_wh[0]}x{resized_wh[1]}"
            return True, msg
        return compress_image_pillow(str(input_file), str(output_file), quality_max, resize_cfg=resize_cfg)
    except Exception:
        return compress_image_pillow(str(input_file), str(output_file), quality_max, resize_cfg=resize_cfg)
    finally:
        try:
            if tmp_path and tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
