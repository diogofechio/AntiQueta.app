"""Inspeção e limpeza de metadados sem tocar nos pixels.

JPEG, PNG e WebP são tratados aqui, copiando byte a byte os blocos de imagem
e descartando os blocos de metadados. TIFF e HEIC usam o exiftool, se instalado.
"""

import hashlib
import struct
import zlib

from . import exiftool
from .flags import classify
from .parsers import (orientation_tiff, parse_c2pa, parse_iptc, parse_photoshop, parse_png_text,
                      parse_tiff, parse_xmp, tag, tiff_orientation)

MAX_BYTES = 100 * 1024 * 1024
EXT = {"jpeg": ".jpg", "png": ".png", "webp": ".webp", "tiff": ".tiff", "heic": ".heic"}


class FormatError(ValueError):
    pass


def detect(data):
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"hevc", b"heim", b"heis",
                                                b"mif1", b"msf1", b"avif"):
        return "heic"
    return None


def inspect(data):
    fmt = detect(data)
    if fmt is None:
        raise FormatError("Formato não reconhecido. Use JPEG, PNG, WebP, TIFF ou HEIC.")
    if fmt in ("tiff", "heic"):
        tags = exiftool.inspect(data)
    else:
        tags = {"jpeg": _jpeg_tags, "png": _png_tags, "webp": _webp_tags}[fmt](data)
    tags = [classify(t) for t in tags]
    order = {"ai": 0, "location": 1, "identity": 2, "device": 3}
    generic = "Credencial de conteúdo"  # resumo e sinais específicos de IA aparecem antes
    tags.sort(key=lambda t: (t.get("kept", False), order.get(t.get("flag"), 9),
                             not t.get("summary"), t.get("reason", "").startswith(generic)))
    return {"format": fmt, "size": len(data), "tags": tags, "summary": summarize(tags),
            "file": file_info(data, fmt)}


def summarize(tags):
    removable = [t for t in tags if not t.get("kept")]
    s = {"removable": len(removable), "kept": len(tags) - len(removable)}
    for flag in ("ai", "location", "device", "identity"):
        s[flag] = sum(1 for t in removable if t.get("flag") == flag)
    return s


def clean(data, keep_orientation=True, keep_icc=True):
    """Remove os metadados. keep_icc=False é a remoção máxima: tira também o
    perfil de cor, que pode identificar o aparelho ou o software."""
    fmt = detect(data)
    if fmt == "jpeg":
        return _jpeg_clean(data, keep_orientation, keep_icc)
    if fmt == "png":
        return _png_clean(data, keep_icc)
    if fmt == "webp":
        return _webp_clean(data, keep_orientation, keep_icc)
    if fmt in ("tiff", "heic"):
        return exiftool.clean(data)
    raise FormatError("Formato não reconhecido.")


COLOR_TYPES = {0: "tons de cinza", 2: "RGB", 3: "paleta de cores", 4: "cinza + transparência",
               6: "RGBA (com transparência)"}


def file_info(data, fmt):
    """Propriedades da imagem (não são metadados removíveis) e o hash do arquivo."""
    info = []
    try:
        if fmt == "png":
            w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", data[16:29])
            info += [("Dimensões", f"{w} × {h} px"), ("Profundidade", f"{depth} bits por canal"),
                     ("Cores", COLOR_TYPES.get(ctype, str(ctype))),
                     ("Entrelaçado", "sim (Adam7)" if interlace else "não")]
        elif fmt == "jpeg":
            for m, s, _ in _jpeg_walk(data):
                if isinstance(m, int) and 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
                    depth, h, w, comps = struct.unpack(">BHHB", data[s + 4:s + 10])
                    kind = {0xC0: "baseline", 0xC1: "sequencial estendido", 0xC2: "progressivo"}.get(m, f"SOF{m - 0xC0}")
                    info += [("Dimensões", f"{w} × {h} px"), ("Profundidade", f"{depth} bits"),
                             ("Componentes", {1: "cinza", 3: "YCbCr (cor)", 4: "CMYK"}.get(comps, str(comps))),
                             ("Codificação", kind)]
                    break
        elif fmt == "webp":
            for fourcc, body in _webp_walk(data):
                if fourcc == b"VP8X":
                    w = int.from_bytes(body[4:7], "little") + 1
                    h = int.from_bytes(body[7:10], "little") + 1
                    info.append(("Dimensões", f"{w} × {h} px"))
                    break
                if fourcc == b"VP8L":
                    bits = int.from_bytes(body[1:5], "little")
                    info += [("Dimensões", f"{(bits & 0x3FFF) + 1} × {((bits >> 14) & 0x3FFF) + 1} px"),
                             ("Compressão", "sem perdas")]
                    break
                if fourcc == b"VP8 ":
                    w = int.from_bytes(body[6:8], "little") & 0x3FFF
                    h = int.from_bytes(body[8:10], "little") & 0x3FFF
                    info += [("Dimensões", f"{w} × {h} px"), ("Compressão", "com perdas")]
                    break
    except (struct.error, FormatError, IndexError):
        pass
    info.append(("SHA-256", hashlib.sha256(data).hexdigest()))
    return [{"name": k, "value": v} for k, v in info]


def icc_description(icc):
    """Nome do perfil ICC (tag 'desc') e fabricante, quando houver."""
    desc = ""
    try:
        count = struct.unpack(">I", icc[128:132])[0]
        for k in range(min(count, 200)):
            sig, off, size = struct.unpack(">4sII", icc[132 + 12 * k:144 + 12 * k])
            if sig != b"desc":
                continue
            d = icc[off:off + size]
            if d[:4] == b"desc":
                n = struct.unpack(">I", d[8:12])[0]
                desc = d[12:12 + n].rstrip(b"\0").decode("latin-1")
            elif d[:4] == b"mluc":
                length, offset = struct.unpack(">II", d[20:28])
                desc = d[offset:offset + length].decode("utf-16-be", "replace").rstrip("\0")
            break
    except struct.error:
        pass
    maker = icc[48:52].strip(b"\0 ").decode("latin-1", "replace") if len(icc) > 52 else ""
    creator = icc[80:84].strip(b"\0 ").decode("latin-1", "replace") if len(icc) > 84 else ""
    extra = ", ".join(x for x in (f"fabricante {maker}" if maker else "",
                                    f"criado por {creator}" if creator else "") if x)
    return f"{desc or 'sem nome'} ({len(icc)} bytes{', ' + extra if extra else ''})"


# ---------------------------------------------------------------- JPEG

def _jpeg_walk(data):
    """Divide o JPEG em (marcador, início, fim). Marcadores especiais:
    'SCAN' para dados comprimidos e 'TRAILER' para bytes após o EOI."""
    if data[:2] != b"\xff\xd8":
        raise FormatError("JPEG inválido")
    parts, i, n = [(0xD8, 0, 2)], 2, len(data)
    while i < n:
        if data[i] != 0xFF:
            raise FormatError(f"JPEG corrompido perto do byte {i}")
        while i + 1 < n and data[i + 1] == 0xFF:
            i += 1
        if i + 1 >= n:
            break
        m = data[i + 1]
        if m == 0xD9:
            parts.append((m, i, i + 2))
            i += 2
            break
        if 0xD0 <= m <= 0xD7 or m == 0x01:
            parts.append((m, i, i + 2))
            i += 2
            continue
        end = i + 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
        if end > n:
            raise FormatError("JPEG truncado")
        parts.append((m, i, end))
        i = end
        if m == 0xDA:
            j = i
            while True:
                j = data.find(b"\xff", j)
                if j < 0 or j + 1 >= n:
                    j = n
                    break
                nb = data[j + 1]
                if nb == 0 or 0xD0 <= nb <= 0xD7 or nb == 0xFF:
                    j += 1
                    continue
                break
            parts.append(("SCAN", i, j))
            i = j
    if i < n:
        parts.append(("TRAILER", i, n))
    return parts


def _jpeg_keep(m, payload, keep_icc=True):
    if m == 0xE0:
        return payload.startswith(b"JFIF\0")
    if m == 0xE2:
        return keep_icc and payload.startswith(b"ICC_PROFILE\0")
    if m == 0xEE:
        return payload.startswith(b"Adobe")  # define a conversão de cores
    return not (0xE0 <= m <= 0xEF or m == 0xFE)


def _jpeg_tags(data):
    tags, c2pa, ext_xmp, icc = [], b"", {}, {}
    for m, s, e in _jpeg_walk(data):
        if m == "TRAILER":
            tags.append(tag("Arquivo", "Dados após o fim da imagem",
                            f"{e - s} bytes (imagens extras, mapas HDR ou dados ocultos)"))
            continue
        if not isinstance(m, int) or not (0xE0 <= m <= 0xEF or m == 0xFE):
            continue
        p = data[s + 4:e]
        if m == 0xE1 and p.startswith(b"Exif\0"):
            tags += parse_tiff(p[6:])
        elif m == 0xE1 and p.startswith(b"http://ns.adobe.com/xap/1.0/\0"):
            tags += parse_xmp(p[29:])
        elif m == 0xE1 and p.startswith(b"http://ns.adobe.com/xmp/extension/\0"):
            body = p[35:]
            guid, offset = body[:32], struct.unpack(">I", body[36:40])[0]
            ext_xmp.setdefault(guid, []).append((offset, body[40:]))
        elif m == 0xED and p.startswith(b"Photoshop 3.0\0"):
            tags += parse_photoshop(p[14:])
        elif m == 0xEB and p.startswith(b"JP"):
            # Segmentos seguintes repetem o cabeçalho da caixa (8 bytes).
            c2pa += p[8:] if not c2pa else p[16:]
        elif m == 0xE2 and p.startswith(b"ICC_PROFILE\0"):
            icc[p[12]] = p[14:]  # pedaços numerados do perfil
        elif m == 0xE2 and p.startswith(b"MPF\0"):
            tags.append(tag("Arquivo", "MPF (várias imagens no arquivo)", f"{len(p)} bytes"))
        elif m == 0xFE:
            tags.append(tag("Comentário", "Comment", p.decode("utf-8", "replace").strip("\0")))
        elif not _jpeg_keep(m, p):
            ident = p[:24].split(b"\0", 1)[0].decode("latin-1", "replace")
            tags.append(tag("Arquivo", f"APP{m - 0xE0}", f"{ident or '?'} ({len(p)} bytes)"))
    for chunks in ext_xmp.values():
        tags += parse_xmp(b"".join(c for _, c in sorted(chunks)))
    if c2pa:
        tags += parse_c2pa(c2pa)
    _mark_kept(tags, b"".join(icc[k] for k in sorted(icc)))
    return tags


def _mark_kept(tags, icc):
    for t in tags:
        if t["group"] == "EXIF" and t["name"] == "Orientation":
            t["kept"] = True
            t["reason"] = "Mantido para a foto não aparecer girada"
    if icc:
        tags.append(tag("Cor", "Perfil ICC", icc_description(icc), kept=True,
                        reason="Mantido para as cores não mudarem (a remoção máxima tira)"))


def _jpeg_clean(data, keep_orientation, keep_icc=True):
    parts = _jpeg_walk(data)
    orientation = None
    for m, s, e in parts:
        if m == 0xE1 and data[s + 4:s + 10] == b"Exif\0\0":
            orientation = tiff_orientation(data[s + 10:e])
            break
    kept = [(m, s, e) for m, s, e in parts[1:] if m != "TRAILER" and not (
        isinstance(m, int) and (0xE0 <= m <= 0xEF or m == 0xFE) and not _jpeg_keep(m, data[s + 4:e], keep_icc))]
    out = bytearray(b"\xff\xd8")
    if kept and kept[0][0] == 0xE0:  # o JFIF continua sendo o primeiro bloco
        out += data[kept[0][1]:kept[0][2]]
        kept = kept[1:]
    if keep_orientation and orientation and orientation != 1:
        payload = b"Exif\0\0" + orientation_tiff(orientation)
        out += b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    for _, s, e in kept:
        out += data[s:e]
    return bytes(out)


# ---------------------------------------------------------------- PNG

PNG_KEEP = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"cHRM", b"gAMA", b"iCCP",
            b"sBIT", b"sRGB", b"cICP", b"mDCV", b"cLLI", b"bKGD", b"hIST", b"pHYs",
            b"sPLT", b"acTL", b"fcTL", b"fdAT"}


def _png_walk(data):
    i, parts = 8, []
    while i + 12 <= len(data):
        size = struct.unpack(">I", data[i:i + 4])[0]
        ctype = data[i + 4:i + 8]
        end = i + 12 + size
        if end > len(data):
            raise FormatError("PNG truncado")
        parts.append((ctype, i, end))
        i = end
        if ctype == b"IEND":
            break
    return parts, i


def _png_tags(data):
    tags, icc = [], b""
    parts, end = _png_walk(data)
    for ctype, s, e in parts:
        body = data[s + 8:e - 4]
        if ctype in (b"tEXt", b"zTXt", b"iTXt"):
            key, text = parse_png_text(ctype, body)
            if key == "XML:com.adobe.xmp":
                tags += parse_xmp(text)
            elif key.lower().startswith("raw profile type"):
                tags += _raw_profile(key, text)
            else:
                tags.append(tag("PNG", key, text))
        elif ctype == b"eXIf":
            tags += parse_tiff(body)
        elif ctype == b"caBX":
            tags += parse_c2pa(body)
        elif ctype == b"tIME":
            y, mo, d, h, mi, se = struct.unpack(">HBBBBB", body[:7])
            tags.append(tag("PNG", "ModifyDate", f"{y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{se:02d}"))
        elif ctype == b"iCCP":
            try:
                icc = zlib.decompress(body.split(b"\0", 1)[1][1:])
            except (zlib.error, IndexError):
                icc = body
        elif ctype not in PNG_KEEP:
            tags.append(tag("PNG", f"Bloco {ctype.decode('latin-1')}", f"{len(body)} bytes"))
    if end < len(data):
        tags.append(tag("Arquivo", "Dados após o fim da imagem", f"{len(data) - end} bytes"))
    _mark_kept(tags, icc)
    return tags


def _raw_profile(key, text):
    """Perfis em hexadecimal gravados pelo ImageMagick ("Raw profile type exif" etc.)."""
    kind = key.lower().rsplit(" ", 1)[-1]
    lines = text.strip().split("\n")
    try:
        raw = bytes.fromhex("".join(lines[2:]))
    except ValueError:
        return [tag("PNG", key, f"({len(text)} caracteres em hex)")]
    if kind in ("exif", "app1"):
        return parse_tiff(raw[6:] if raw.startswith(b"Exif\0") else raw)
    if kind == "xmp":
        return parse_xmp(raw)
    if kind in ("iptc", "8bim"):
        return parse_photoshop(raw) if raw.startswith(b"8BIM") else parse_iptc(raw)
    if kind in ("icc", "icm"):
        return [tag("PNG", key, icc_description(raw))]
    return [tag("PNG", key, f"({len(raw)} bytes)")]


def _png_clean(data, keep_icc=True):
    parts, _ = _png_walk(data)
    keep = PNG_KEEP if keep_icc else PNG_KEEP - {b"iCCP"}
    return data[:8] + b"".join(data[s:e] for ctype, s, e in parts if ctype in keep)


# ---------------------------------------------------------------- WebP

WEBP_KEEP = {b"VP8X", b"ICCP", b"ANIM", b"ANMF", b"ALPH", b"VP8 ", b"VP8L"}


def _webp_walk(data):
    i, parts = 12, []
    limit = min(len(data), 8 + struct.unpack("<I", data[4:8])[0])
    while i + 8 <= limit:
        fourcc = data[i:i + 4]
        size = struct.unpack("<I", data[i + 4:i + 8])[0]
        parts.append((fourcc, data[i + 8:i + 8 + size]))
        i += 8 + size + (size & 1)
    return parts


def _webp_tags(data):
    tags, icc = [], b""
    for fourcc, body in _webp_walk(data):
        if fourcc == b"EXIF":
            tags += parse_tiff(body[6:] if body.startswith(b"Exif\0\0") else body)
        elif fourcc == b"XMP ":
            tags += parse_xmp(body)
        elif fourcc == b"C2PA":
            tags += parse_c2pa(body)
        elif fourcc == b"ICCP":
            icc = body
        elif fourcc not in WEBP_KEEP:
            tags.append(tag("WebP", f"Bloco {fourcc.decode('latin-1').strip()}", f"{len(body)} bytes"))
    _mark_kept(tags, icc)
    return tags


def _chunk(fourcc, body):
    return fourcc + struct.pack("<I", len(body)) + body + (b"\0" if len(body) & 1 else b"")


def _webp_clean(data, keep_orientation, keep_icc=True):
    parts = _webp_walk(data)
    orientation = None
    for fourcc, body in parts:
        if fourcc == b"EXIF":
            orientation = tiff_orientation(body[6:] if body.startswith(b"Exif\0\0") else body)
    add_exif = keep_orientation and orientation and orientation != 1
    out = []
    has_vp8x = any(f == b"VP8X" for f, _ in parts)
    keep = WEBP_KEEP if keep_icc else WEBP_KEEP - {b"ICCP"}
    for fourcc, body in parts:
        if fourcc not in keep:
            continue
        if fourcc == b"VP8X":
            flags = body[0] & ~(0x0C if keep_icc else 0x2C)
            if add_exif:
                flags |= 0x08
            body = bytes([flags]) + body[1:]
        out.append(_chunk(fourcc, body))
    if add_exif and has_vp8x:
        out.append(_chunk(b"EXIF", orientation_tiff(orientation)))
    payload = b"WEBP" + b"".join(out)
    return b"RIFF" + struct.pack("<I", len(payload)) + payload


def cleaned_name(filename, fmt):
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    ext = "." + filename.rsplit(".", 1)[1] if "." in filename else EXT.get(fmt, "")
    return f"{stem}_limpo{ext}"
