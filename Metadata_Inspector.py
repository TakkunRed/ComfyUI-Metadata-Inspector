import json
import os
import datetime
import re
from PIL import Image, ExifTags
import numpy as np
from nodes import LoadImage
from folder_paths import get_annotated_filepath

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

    def extract(self, image_name):
        if os.path.isabs(image_name):
            image_path = image_name
        else:
            image_path = get_annotated_filepath(image_name)

        all_metadata = {}
        
        def json_serializable(obj):
            try:
                if isinstance(obj, (datetime.date, datetime.datetime)):
                    return obj.isoformat()
                if isinstance(obj, bytes):
                    try:
                        s = obj.decode('utf-8', errors="replace").strip('\x00')
                    except:
                        s = obj.decode('cp932', errors="replace").strip('\x00')
                    return re.sub(r'^(ASCII|UNICODE|JIS|UNDEFINED)\x00*', '', s).strip()
                return str(obj)
            except:
                return f"<Unserializable>"

        def try_parse_json(value):
            val_str = value if isinstance(value, str) else json_serializable(value)
            
            stripped = val_str.strip()
            json_match = re.search(r'(\{.*\}|\[.*\])', stripped, re.DOTALL)
            if json_match:
                try:
                    parsed = json.loads(json_match.group(0))
                    if isinstance(parsed, str):
                        return try_parse_json(parsed)
                    return parsed
                except:
                    pass
            
            if "Steps:" in stripped and "Seed:" in stripped:
                return [line.strip() for line in stripped.split('\n') if line.strip()]
                
            return val_str

        if os.path.exists(image_path):
            stat = os.stat(image_path)
            all_metadata["fileinfo"] = {
                "filename": os.path.basename(image_path),
                "date": datetime.datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                "size": f"{stat.st_size / 1024:.2f} KB",
            }

            with Image.open(image_path) as img:
                all_metadata["fileinfo"]["resolution"] = f"{img.width}x{img.height}"

                for key, value in img.info.items():
                    if key == "exif": continue
                    all_metadata[key] = try_parse_json(value)

                try:
                    exif_obj = img.getexif()
                    if exif_obj:
                        exif_results = {}
                        
                        for tag, value in exif_obj.items():
                            tag_name = ExifTags.TAGS.get(tag, f"Tag_{tag}")
                            exif_results[f"{tag_name} (ID: {tag})"] = try_parse_json(value)
                        
                        exif_ifd = exif_obj.get_ifd(0x8769)
                        if exif_ifd:
                            for tag, value in exif_ifd.items():
                                tag_name = ExifTags.TAGS.get(tag, f"ExifIFD_Tag_{tag}")
                                exif_results[f"{tag_name} (ID: {tag})"] = try_parse_json(value)
                        
                        all_metadata["EXIF_Full_Data"] = exif_results
                except Exception as e:
                    all_metadata["EXIF_Error"] = f"EXIF Deep Scan failed: {str(e)}"
        else:
            all_metadata = {"error": "File not found"}

        return (json.dumps(all_metadata, default=json_serializable),)

class JsonVisualizer:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {"json_string": ("STRING", {"forceInput": True})}}

    RETURN_TYPES = ("STRING",)
    FUNCTION = "visualize"
    CATEGORY = "ui/visualizer"
    OUTPUT_NODE = True

    def visualize(self, json_string):
        import json
        try:
            data = json.loads(json_string)
        except:
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