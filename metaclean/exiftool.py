"""Suporte opcional a TIFF e HEIC via exiftool (https://exiftool.org)."""

import json
import shutil
import subprocess

from .parsers import tag

SKIP_GROUPS = {"ExifTool", "System", "File", "Composite"}
# Tags estruturais que o exiftool não remove porque a imagem depende delas.
STRUCTURAL = {"ImageWidth", "ImageHeight", "BitsPerSample", "Compression",
              "PhotometricInterpretation", "StripOffsets", "SamplesPerPixel",
              "RowsPerStrip", "StripByteCounts", "PlanarConfiguration",
              "TileWidth", "TileLength", "TileOffsets", "TileByteCounts",
              "ExtraSamples", "SampleFormat", "Predictor", "FillOrder",
              "ImageSize", "ImageSpatialExtent", "HEVCConfigurationVersion",
              "PrimaryItemReference", "MajorBrand", "MinorVersion",
              "CompatibleBrands", "HandlerType", "Orientation", "ProfileCMMType",
              "Rotation", "ImagePixelDepth", "MediaDataSize", "MediaDataOffset"}


class ExiftoolMissing(RuntimeError):
    pass


def _run(args, data):
    exe = shutil.which("exiftool")
    if not exe:
        raise ExiftoolMissing(
            "TIFF e HEIC precisam do exiftool instalado (brew install exiftool, "
            "sudo apt install libimage-exiftool-perl ou exiftool.org).")
    res = subprocess.run([exe, *args, "-"], input=data, capture_output=True, timeout=60)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.decode("utf-8", "replace").strip() or "exiftool falhou")
    return res.stdout


def inspect(data):
    out = json.loads(_run(["-j", "-G1", "-a", "-s", "-struct"], data) or b"[{}]")[0]
    tags = []
    for key, value in out.items():
        if ":" not in key:
            continue
        group, name = key.split(":", 1)
        if group in SKIP_GROUPS:
            continue
        group_main = "GPS" if group == "GPS" else group
        t = tag(group_main, name, value if not isinstance(value, (dict, list)) else json.dumps(value, ensure_ascii=False))
        if name in STRUCTURAL or group.startswith("ICC"):
            t["kept"] = True
            t["reason"] = "Estrutural: necessário para abrir a imagem"
        tags.append(t)
    return tags


def clean(data):
    return _run(["-all=", "-tagsfromfile", "@", "-icc_profile", "-orientation",
                 "-o", "-"], data)
