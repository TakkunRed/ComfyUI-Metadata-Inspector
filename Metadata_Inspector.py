import json
import math
import os
import datetime
from PIL import Image, ExifTags
from nodes import LoadImage
from folder_paths import get_annotated_filepath

# Windows Explorer が書き込む UTF-16LE のタグ (XPTitle, XPComment, XPAuthor, XPKeywords, XPSubject)
_XP_TAGS = {0x9C9B, 0x9C9C, 0x9C9D, 0x9C9E, 0x9C9F}
# 中身が文字列ではないバイナリなので出力に含めない img.info のキー
_SKIP_INFO_KEYS = {"exif", "icc_profile"}


class LoadImageWithFileName(LoadImage):
    @classmethod
    def INPUT_TYPES(s):
        return super().INPUT_TYPES()

    RETURN_TYPES = ("IMAGE", "MASK", "STRING")
    RETURN_NAMES = ("image", "mask", "image_name")
    FUNCTION = "load_image_info"
    CATEGORY = "image"

    def load_image_info(self, image):
        img, mask = super().load_image(image)
        return (img, mask, image)


def _looks_like_text(s):
    """制御文字や置換文字が多い文字列はバイナリとみなす"""
    if not s:
        return False
    bad = sum(1 for c in s if c == "�" or (ord(c) < 32 and c not in "\n\r\t"))
    return bad / len(s) < 0.1


def _plausibility(s):
    """ASCII・かな/漢字・全角・ラテン文字など、ふつうの文章に出てくる文字の割合"""
    if not s:
        return 0.0
    ok = sum(1 for c in s if 0x20 <= ord(c) <= 0x7E or c in "\n\r\t"
             or 0xA0 <= ord(c) <= 0x24F or 0x3000 <= ord(c) <= 0x30FF
             or 0x4E00 <= ord(c) <= 0x9FFF or 0xFF00 <= ord(c) <= 0xFFEF)
    return ok / len(s)


def _decode_utf16(payload):
    if payload[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return payload.decode("utf-16", errors="replace")
    # BOM なし: Exif の規定は BE だが LE で書く実装もあるため、両方で復号して自然な方を採る
    be = payload.decode("utf-16-be", errors="replace")
    le = payload.decode("utf-16-le", errors="replace")
    return le if _plausibility(le) > _plausibility(be) else be


def _decode_bytes(data, tag=None):
    """バイト列を文字列にする。文字列と判断できないバイナリは None"""
    if tag in _XP_TAGS:
        text = data.decode("utf-16-le", errors="replace")
    else:
        header, payload = data[:8], data[8:]
        if header == b"UNICODE\x00":  # UserComment の文字コード指定 (UTF-16)
            text = _decode_utf16(payload)
        else:
            if header in (b"ASCII\x00\x00\x00", b"JIS\x00\x00\x00\x00\x00", b"\x00" * 8):
                data = payload
            text = None
            for enc in ("utf-8", "cp932"):
                try:
                    text = data.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            if text is None:
                text = data.decode("utf-8", errors="replace")
    text = text.strip("\x00").strip()
    return text if _looks_like_text(text) else None


def _parse_constant(name):
    # NaN / Infinity は JSON として不正なので文字列にしておく
    return name


def _try_parse_json(text):
    """文字列全体が JSON のときだけパースする。文中の JSON を切り出して本文を失うことはしない"""
    stripped = text.strip()
    for _ in range(2):  # JSON 文字列の中にさらに JSON が入っている場合に備えて2段まで
        if not (stripped[:1] in ("{", "[") and stripped[-1:] in ("}", "]")):
            return text
        try:
            parsed = json.loads(stripped, parse_constant=_parse_constant)
        except (json.JSONDecodeError, RecursionError):
            return text
        if isinstance(parsed, str):
            stripped = parsed.strip()
            continue
        return parsed
    return text


def _convert_value(value, tag=None):
    """任意の値を JSON にできる形へ。数値は数値のまま保持する"""
    if isinstance(value, str):
        parsed = _try_parse_json(value)
        if parsed is value and "Steps:" in value and "Seed:" in value:
            return [line.strip() for line in value.split("\n") if line.strip()]
        return parsed
    if isinstance(value, bytes):
        text = _decode_bytes(value, tag)
        if text is None:
            return f"<binary {len(value)} bytes>"
        return _convert_value(text)
    if isinstance(value, bool) or value is None or isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_convert_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _convert_value(v) for k, v in value.items()}
    try:  # PIL の IFDRational など
        f = float(value)
        return f if math.isfinite(f) else str(value)
    except (TypeError, ValueError):
        return str(value)


def _resolve_path(image_name):
    image_name = image_name.strip()
    if len(image_name) >= 2 and image_name[0] == '"' and image_name[-1] == '"':
        image_name = image_name[1:-1].strip()
    if not image_name:
        return None
    if os.path.isabs(image_name):
        return image_name
    try:
        return get_annotated_filepath(image_name)
    except Exception:
        return None


class ExtractPngMetadata:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image_name": ("STRING", {"default": "example.png"}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("metadata_json",)
    FUNCTION = "extract"
    CATEGORY = "image/metadata"

    @classmethod
    def IS_CHANGED(s, image_name):
        # 同じパスのファイルが差し替えられたときに、キャッシュされた結果を使わない
        path = _resolve_path(image_name)
        try:
            st = os.stat(path)
            return f"{st.st_mtime_ns}:{st.st_size}"
        except (OSError, TypeError):
            return ""

    def extract(self, image_name):
        image_path = _resolve_path(image_name)
        if not image_path or not os.path.isfile(image_path):
            return (json.dumps({"error": "File not found"}),)

        all_metadata = {}
        stat = os.stat(image_path)
        all_metadata["fileinfo"] = {
            "filename": os.path.basename(image_path),
            "date": datetime.datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
            "size": f"{stat.st_size / 1024:.2f} KB",
        }

        try:
            with Image.open(image_path) as img:
                all_metadata["fileinfo"]["resolution"] = f"{img.width}x{img.height}"

                for key, value in img.info.items():
                    if key in _SKIP_INFO_KEYS:
                        continue
                    all_metadata[str(key)] = _convert_value(value)

                try:
                    exif_obj = img.getexif()
                    if exif_obj:
                        exif_results = {}

                        for tag, value in exif_obj.items():
                            tag_name = ExifTags.TAGS.get(tag, f"Tag_{tag}")
                            exif_results[f"{tag_name} (ID: {tag})"] = _convert_value(value, tag)

                        exif_ifd = exif_obj.get_ifd(0x8769)
                        if exif_ifd:
                            for tag, value in exif_ifd.items():
                                tag_name = ExifTags.TAGS.get(tag, f"ExifIFD_Tag_{tag}")
                                exif_results[f"{tag_name} (ID: {tag})"] = _convert_value(value, tag)

                        all_metadata["EXIF_Full_Data"] = exif_results
                except Exception as e:
                    all_metadata["EXIF_Error"] = f"EXIF Deep Scan failed: {str(e)}"
        except Exception as e:
            # 画像として開けないファイル・壊れたファイル: ワークフローを止めずにエラー内容を返す
            all_metadata["error"] = f"Cannot read image: {type(e).__name__}: {e}"

        return (json.dumps(all_metadata, ensure_ascii=False, default=str),)


class JsonVisualizer:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {"json_string": ("STRING", {"forceInput": True})}}

    RETURN_TYPES = ("STRING",)
    FUNCTION = "visualize"
    CATEGORY = "ui/visualizer"
    OUTPUT_NODE = True

    def visualize(self, json_string):
        try:
            data = json.loads(json_string)
        except (json.JSONDecodeError, TypeError):
            data = {"error": "Invalid JSON"}

        return {"ui": {"json_data": [data]}, "result": (json_string,)}

NODE_CLASS_MAPPINGS = {
    "LoadImageWithFileName": LoadImageWithFileName,
    "ExtractPngMetadata": ExtractPngMetadata,
    "JsonVisualizer": JsonVisualizer
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LoadImageWithFileName": "Load Image w/ Name",
    "ExtractPngMetadata": "Extract PNG Metadata",
    "JsonVisualizer": "JSON Tree Viewer"
}
