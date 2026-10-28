"""Leitores dos blocos de metadados: EXIF/TIFF, XMP, IPTC, C2PA e textos PNG.

Cada leitor devolve uma lista de tags no formato
{"group": ..., "name": ..., "value": ...}. A classificação (IA, localização,
dispositivo, identidade) é feita depois, em flags.py.
"""

import re
import struct
import zlib
import xml.etree.ElementTree as ET

MAX_VALUE = 4000

EXIF_NAMES = {
    0x0100: "ImageWidth", 0x0101: "ImageHeight", 0x0103: "Compression",
    0x010E: "ImageDescription", 0x010F: "Make", 0x0110: "Model",
    0x0112: "Orientation", 0x011A: "XResolution", 0x011B: "YResolution",
    0x0128: "ResolutionUnit", 0x0131: "Software", 0x0132: "ModifyDate",
    0x013B: "Artist", 0x013C: "HostComputer", 0x0201: "ThumbnailOffset",
    0x0202: "ThumbnailLength", 0x0213: "YCbCrPositioning", 0x8298: "Copyright",
    0x829A: "ExposureTime", 0x829D: "FNumber", 0x8822: "ExposureProgram",
    0x8827: "ISO", 0x8830: "SensitivityType", 0x9000: "ExifVersion",
    0x9003: "DateTimeOriginal", 0x9004: "CreateDate", 0x9010: "OffsetTime",
    0x9011: "OffsetTimeOriginal", 0x9012: "OffsetTimeDigitized",
    0x9101: "ComponentsConfiguration", 0x9201: "ShutterSpeedValue",
    0x9202: "ApertureValue", 0x9203: "BrightnessValue",
    0x9204: "ExposureCompensation", 0x9205: "MaxApertureValue",
    0x9207: "MeteringMode", 0x9208: "LightSource", 0x9209: "Flash",
    0x920A: "FocalLength", 0x927C: "MakerNote", 0x9286: "UserComment",
    0x9290: "SubSecTime", 0x9291: "SubSecTimeOriginal",
    0x9292: "SubSecTimeDigitized", 0x9C9B: "XPTitle", 0x9C9C: "XPComment",
    0x9C9D: "XPAuthor", 0x9C9E: "XPKeywords", 0x9C9F: "XPSubject",
    0xA000: "FlashpixVersion", 0xA001: "ColorSpace", 0xA002: "ExifImageWidth",
    0xA003: "ExifImageHeight", 0xA217: "SensingMethod", 0xA300: "FileSource",
    0xA301: "SceneType", 0xA401: "CustomRendered", 0xA402: "ExposureMode",
    0xA403: "WhiteBalance", 0xA404: "DigitalZoomRatio",
    0xA405: "FocalLengthIn35mmFormat", 0xA406: "SceneCaptureType",
    0xA420: "ImageUniqueID", 0xA430: "OwnerName", 0xA431: "SerialNumber",
    0xA432: "LensInfo", 0xA433: "LensMake", 0xA434: "LensModel",
    0xA435: "LensSerialNumber",
}

GPS_NAMES = {
    0x00: "GPSVersionID", 0x01: "GPSLatitudeRef", 0x02: "GPSLatitude",
    0x03: "GPSLongitudeRef", 0x04: "GPSLongitude", 0x05: "GPSAltitudeRef",
    0x06: "GPSAltitude", 0x07: "GPSTimeStamp", 0x08: "GPSSatellites",
    0x09: "GPSStatus", 0x0A: "GPSMeasureMode", 0x0B: "GPSDOP", 0x0C: "GPSSpeedRef",
    0x0D: "GPSSpeed", 0x0E: "GPSTrackRef", 0x0F: "GPSTrack", 0x10: "GPSImgDirectionRef", 0x11: "GPSImgDirection",
    0x12: "GPSMapDatum", 0x13: "GPSDestLatitudeRef",
    0x14: "GPSDestLatitude", 0x15: "GPSDestLongitudeRef", 0x16: "GPSDestLongitude", 0x17: "GPSDestBearingRef", 0x18: "GPSDestBearing",
    0x1B: "GPSProcessingMethod", 0x1D: "GPSDateStamp", 0x1E: "GPSDifferential",
    0x1F: "GPSHPositioningError",
}

POINTERS = {0x8769: ("EXIF", EXIF_NAMES), 0x8825: ("GPS", GPS_NAMES),
            0xA005: ("Interop", {})}
TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8,
              11: 4, 12: 8}
XP_TAGS = {0x9C9B, 0x9C9C, 0x9C9D, 0x9C9E, 0x9C9F}


def tag(group, name, value, **extra):
    value = str(value)
    if len(value) > MAX_VALUE:
        value = value[:MAX_VALUE] + "…"
    return {"group": group, "name": name, "value": value, **extra}


def _clean_text(raw):
    return raw.split(b"\0", 1)[0].decode("utf-8", "replace").strip()


def _decode_value(e, typ, cnt, raw, tag_id):
    if tag_id in XP_TAGS:
        return raw.decode("utf-16-le", "replace").rstrip("\0")
    if tag_id == 0x9286:  # UserComment: 8 bytes de charset + texto
        body = raw[8:]
        if raw[:8].startswith(b"UNICODE"):
            return body.decode("utf-16-le" if e == "<" else "utf-16-be", "replace").rstrip("\0 ")
        return body.decode("utf-8", "replace").rstrip("\0 ")
    if typ == 2:
        return _clean_text(raw)
    if typ == 7:
        if tag_id in (0x9000, 0xA000, 0x1B) and all(32 <= b < 127 for b in raw.rstrip(b"\0")):
            return raw.decode("ascii").rstrip("\0")
        return f"({len(raw)} bytes)"
    size = TYPE_SIZES.get(typ, 1)
    fmt = {1: "B", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i", 11: "f", 12: "d"}
    vals = []
    for k in range(min(cnt, 16)):
        chunk = raw[k * size:(k + 1) * size]
        if len(chunk) < size:
            break
        if typ in (5, 10):
            num, den = struct.unpack(e + ("II" if typ == 5 else "ii"), chunk)
            vals.append(round(num / den, 6) if den else 0)
        else:
            vals.append(struct.unpack(e + fmt.get(typ, "B"), chunk)[0])
    text = ", ".join(str(v) for v in vals)
    return text + (", …" if cnt > 16 else "")


def _rationals(e, raw, count):
    out = []
    for k in range(count):
        num, den = struct.unpack(e + "II", raw[k * 8:k * 8 + 8])
        out.append(num / den if den else 0)
    return out


def parse_tiff(data, base_group="EXIF"):
    """Lê uma estrutura TIFF (o conteúdo de um bloco EXIF)."""
    if len(data) < 8 or data[:2] not in (b"II", b"MM"):
        return []
    e = "<" if data[:2] == b"II" else ">"
    tags, seen, gps_raw = [], set(), {}

    def read_ifd(off, group, names, depth):
        if off in seen or off <= 0 or off + 2 > len(data) or depth > 4:
            return 0
        seen.add(off)
        count = struct.unpack(e + "H", data[off:off + 2])[0]
        for k in range(min(count, 1000)):
            p = off + 2 + 12 * k
            if p + 12 > len(data):
                return 0
            tag_id, typ, cnt = struct.unpack(e + "HHI", data[p:p + 8])
            size = TYPE_SIZES.get(typ, 1) * cnt
            if size <= 4:
                raw = data[p + 8:p + 8 + size]
            else:
                vo = struct.unpack(e + "I", data[p + 8:p + 12])[0]
                if vo + size > len(data):
                    continue
                raw = data[vo:vo + size]
            if tag_id in POINTERS and group in ("IFD0", "EXIF") and len(raw) >= 4:
                sub_group, sub_names = POINTERS[tag_id]
                read_ifd(struct.unpack(e + "I", raw[:4])[0], sub_group, sub_names, depth + 1)
                continue
            if group == "GPS" and tag_id in (1, 2, 3, 4):
                gps_raw[tag_id] = (typ, cnt, raw)
            name = names.get(tag_id, f"Tag 0x{tag_id:04X}")
            if tag_id == 0x927C:
                value = f"Dados proprietários do fabricante ({len(raw)} bytes)"
            else:
                value = _decode_value(e, typ, cnt, raw, tag_id)
            shown_group = base_group if group in ("IFD0", "EXIF") else group
            if group == "IFD1":
                shown_group = "Miniatura"
            tags.append(tag(shown_group, name, value))
        end = off + 2 + 12 * count
        if end + 4 <= len(data):
            return struct.unpack(e + "I", data[end:end + 4])[0]
        return 0

    first = struct.unpack(e + "I", data[4:8])[0]
    nxt = read_ifd(first, "IFD0", EXIF_NAMES, 0)
    if nxt:
        read_ifd(nxt, "IFD1", EXIF_NAMES, 0)

    try:
        if 2 in gps_raw and 4 in gps_raw:
            lat = _rationals(e, gps_raw[2][2], 3)
            lon = _rationals(e, gps_raw[4][2], 3)
            lat_v = lat[0] + lat[1] / 60 + lat[2] / 3600
            lon_v = lon[0] + lon[1] / 60 + lon[2] / 3600
            if 1 in gps_raw and _clean_text(gps_raw[1][2]) == "S":
                lat_v = -lat_v
            if 3 in gps_raw and _clean_text(gps_raw[3][2]) == "W":
                lon_v = -lon_v
            tags.append(tag("GPS", "Coordenadas", f"{lat_v:.6f}, {lon_v:.6f}",
                            map=f"https://www.openstreetmap.org/?mlat={lat_v:.6f}&mlon={lon_v:.6f}#map=16/{lat_v:.6f}/{lon_v:.6f}"))
    except (struct.error, IndexError):
        pass
    return tags


def tiff_orientation(data):
    """Devolve o valor de Orientation do IFD0, ou None."""
    if len(data) < 8 or data[:2] not in (b"II", b"MM"):
        return None
    e = "<" if data[:2] == b"II" else ">"
    try:
        off = struct.unpack(e + "I", data[4:8])[0]
        count = struct.unpack(e + "H", data[off:off + 2])[0]
        for k in range(count):
            p = off + 2 + 12 * k
            tag_id, typ = struct.unpack(e + "HH", data[p:p + 4])
            if tag_id == 0x0112 and typ == 3:
                return struct.unpack(e + "H", data[p + 8:p + 10])[0]
    except struct.error:
        pass
    return None


def orientation_tiff(value):
    """Monta um bloco TIFF mínimo contendo só a tag Orientation."""
    return (b"MM\x00\x2a\x00\x00\x00\x08" + struct.pack(">H", 1)
            + struct.pack(">HHIH", 0x0112, 3, 1, value) + b"\x00\x00"
            + b"\x00\x00\x00\x00")


# ---------------------------------------------------------------- XMP

RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
SKIP_ATTRS = {f"{{{RDF}}}about", f"{{{RDF}}}parseType",
              "{http://www.w3.org/XML/1998/namespace}lang"}


def parse_xmp(raw):
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    raw = raw.strip("\0 \r\n\t")
    prefixes = {uri: p for p, uri in re.findall(r'xmlns:([\w.-]+)\s*=\s*["\']([^"\']+)["\']', raw)}

    def qname(name):
        if name.startswith("{"):
            uri, local = name[1:].split("}", 1)
            return f"{prefixes.get(uri, uri.rstrip('/#').rsplit('/', 1)[-1])}:{local}"
        return name

    start = raw.find("<x:xmpmeta")
    if start < 0:
        start = raw.find("<rdf:RDF")
    end_tag = "</x:xmpmeta>" if raw.find("</x:xmpmeta>") >= 0 else "</rdf:RDF>"
    end = raw.find(end_tag)
    body = raw[start:end + len(end_tag)] if start >= 0 and end >= 0 else raw
    tags = []
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        for name, value in re.findall(r'\s([\w-]+:[\w-]+)="([^"]*)"', body):
            if not name.startswith(("xmlns:", "rdf:", "xml:")):
                tags.append(tag("XMP", name, value))
        return tags

    parents = {child: parent for parent in root.iter() for child in parent}
    for el in root.iter():
        for k, v in el.attrib.items():
            if k not in SKIP_ATTRS and not k.startswith(f"{{{RDF}}}"):
                tags.append(tag("XMP", qname(k), v))
        text = (el.text or "").strip()
        if not text or len(el):
            continue
        if el.tag == f"{{{RDF}}}li":
            container = parents.get(el)
            prop = parents.get(container) if container is not None else None
            if prop is not None:
                tags.append(tag("XMP", qname(prop.tag), text))
        elif not el.tag.startswith(f"{{{RDF}}}"):
            tags.append(tag("XMP", qname(el.tag), text))
    return tags


# ---------------------------------------------------------------- IPTC

IPTC_NAMES = {
    5: "ObjectName", 15: "Category", 25: "Keywords", 40: "SpecialInstructions",
    55: "DateCreated", 60: "TimeCreated", 62: "DigitalCreationDate",
    65: "OriginatingProgram", 70: "ProgramVersion", 80: "By-line",
    85: "By-lineTitle", 90: "City", 92: "Sub-location", 95: "Province-State",
    100: "Country-Code", 101: "Country", 103: "OriginalTransmissionReference",
    105: "Headline", 110: "Credit", 115: "Source", 116: "CopyrightNotice",
    118: "Contact", 120: "Caption-Abstract", 122: "Writer-Editor",
}


def parse_photoshop(payload):
    """Lê os recursos 8BIM de um bloco Photoshop (APP13) e extrai o IPTC."""
    tags, i = [], 0
    while i + 12 <= len(payload) and payload[i:i + 4] == b"8BIM":
        res_id = struct.unpack(">H", payload[i + 4:i + 6])[0]
        name_len = payload[i + 6]
        j = i + 7 + name_len
        if (1 + name_len) % 2:  # nome Pascal com padding para tamanho par
            j += 1
        size = struct.unpack(">I", payload[j:j + 4])[0]
        data = payload[j + 4:j + 4 + size]
        if res_id == 0x0404:
            tags += parse_iptc(data)
        elif res_id not in (0x0425,):
            tags.append(tag("Photoshop", f"Recurso 0x{res_id:04X}", f"({size} bytes)"))
        i = j + 4 + size + (size % 2)
    return tags


def parse_iptc(data):
    tags, i = [], 0
    while i + 5 <= len(data) and data[i] == 0x1C:
        record, dataset = data[i + 1], data[i + 2]
        size = struct.unpack(">H", data[i + 3:i + 5])[0]
        value = data[i + 5:i + 5 + size]
        i += 5 + size
        if record == 2 and dataset == 0:
            continue
        if record == 2:
            name = IPTC_NAMES.get(dataset, f"2:{dataset}")
            tags.append(tag("IPTC", name, value.decode("utf-8", "replace")))
        elif record != 1:
            tags.append(tag("IPTC", f"{record}:{dataset}", f"({size} bytes)"))
    return tags


# ---------------------------------------------------------------- C2PA

SOURCE_TYPE = re.compile(rb"https?://cv\.iptc\.org/newscodes/digitalsourcetype/(\w+)")
AI_VENDORS = re.compile(
    rb"[\x20-\x7e]*(OpenAI|DALL[-\xb7 ]?E|ChatGPT|Firefly|Midjourney|Stable ?Diffusion|"
    rb"Gemini|Imagen|Image Creator|Meta AI|Grok|Sora|Leonardo|Ideogram|FLUX|"
    rb"Generative (Fill|Expand|Edit)|Galaxy AI|Magic Editor)[\x20-\x7e]*", re.I)
CERT_NOISE = re.compile(r"https?:|crl|pki|ocsp|Root|\bCA\b|Trust|Certif", re.I)


def _cbor_text_after(blob, key):
    pos = blob.find(key)
    if pos < 0:
        return None
    p = pos + len(key)
    if p >= len(blob):
        return None
    head = blob[p]
    if head >> 5 != 3:
        return None
    n = head & 0x1F
    p += 1
    if n == 24:
        n, p = blob[p], p + 1
    elif n == 25:
        n, p = struct.unpack(">H", blob[p:p + 2])[0], p + 2
    elif n > 25:
        return None
    return blob[p:p + n].decode("utf-8", "replace")


def parse_c2pa(blob):
    tags = [tag("C2PA", "Manifesto C2PA (Content Credentials)", f"{len(blob)} bytes")]
    gen = _cbor_text_after(blob, b"\x6fclaim_generator")
    if gen:
        tags.append(tag("C2PA", "claim_generator", gen))
    info = blob.find(b"claim_generator_info")
    if info >= 0:
        name = _cbor_text_after(blob[info:info + 400], b"\x64name")
        if name:
            tags.append(tag("C2PA", "claim_generator_info.name", name))
    for st in sorted(set(SOURCE_TYPE.findall(blob))):
        tags.append(tag("C2PA", "digitalSourceType", st.decode()))
    vendors = sorted({m.group(0).decode("ascii", "replace").strip()
                      for m in AI_VENDORS.finditer(blob) if len(m.group(0)) < 120})
    vendors = [v for v in vendors if not CERT_NOISE.search(v)]
    for v in vendors[:8]:
        if v and v != gen:
            tags.append(tag("C2PA", "Texto no manifesto", v))
    return tags


# ---------------------------------------------------------------- PNG texto

def parse_png_text(ctype, data):
    """tEXt, zTXt e iTXt. Devolve (chave, texto)."""
    key, _, rest = data.partition(b"\0")
    key = key.decode("latin-1")
    try:
        if ctype == b"tEXt":
            return key, rest.decode("latin-1")
        if ctype == b"zTXt":
            return key, zlib.decompress(rest[1:]).decode("latin-1")
        flag, _method = rest[0], rest[1]
        rest = rest[2:]
        _lang, _, rest = rest.partition(b"\0")
        _trans, _, text = rest.partition(b"\0")
        if flag:
            text = zlib.decompress(text)
        return key, text.decode("utf-8", "replace")
    except (zlib.error, IndexError):
        return key, f"({len(data)} bytes ilegíveis)"
