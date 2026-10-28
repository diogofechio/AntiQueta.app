import io
import struct
import unittest

from metaclean import clean, inspect
from metaclean.parsers import tiff_orientation

try:
    from PIL import Image
except ImportError:  # Pillow só é usado nos testes
    Image = None

XMP = (b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
       b'<rdf:Description rdf:about="" xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/" '
       b'xmlns:dc="http://purl.org/dc/elements/1.1/" '
       b'Iptc4xmpExt:DigitalSourceType="http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia">'
       b'<dc:creator><rdf:Seq><rdf:li>Fulano de Tal</rdf:li></rdf:Seq></dc:creator>'
       b'</rdf:Description></rdf:RDF></x:xmpmeta>')
C2PA = (b"JP\x00\x01\x00\x00\x00\x01" + b"\x00\x00\x00\x40jumb" + b"c2pa"
        + b"\x6fclaim_generator" + b"\x6aOpenAI-API" + b"c2pa.actions"
        + b"http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia")


def seg(marker, payload):
    return bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload


def iptc_app13():
    ds = b"\x1c\x02\x50" + struct.pack(">H", 5) + b"Autor" + b"\x1c\x02\x5a" + struct.pack(">H", 9) + b"Sao Paulo"
    res = b"8BIM\x04\x04\x00\x00" + struct.pack(">I", len(ds)) + ds + (b"\0" if len(ds) % 2 else b"")
    return seg(0xED, b"Photoshop 3.0\0" + res)


def pixels(data):
    with Image.open(io.BytesIO(data)) as im:
        return im.convert("RGBA").tobytes()


def make_exif():
    exif = Image.Exif()
    exif[0x010F] = "Apple"
    exif[0x0110] = "iPhone 15 Pro"
    exif[0x0131] = "Adobe Firefly"
    exif[0x0112] = 6
    gps = {1: "S", 2: (23.0, 33.0, 1.2), 3: "W", 4: (46.0, 37.0, 59.0)}
    exif[0x8825] = gps
    return exif


@unittest.skipIf(Image is None, "Pillow não instalado")
class JpegTest(unittest.TestCase):
    def build(self, progressive=False):
        buf = io.BytesIO()
        img = Image.radial_gradient("L").convert("RGB").resize((300, 200))
        img.save(buf, "JPEG", quality=90, exif=make_exif(), progressive=progressive)
        raw = buf.getvalue()
        extra = (seg(0xE1, b"http://ns.adobe.com/xap/1.0/\0" + XMP) + iptc_app13()
                 + seg(0xEB, C2PA) + seg(0xFE, b"comentario secreto"))
        return raw[:2] + extra + raw[2:] + b"TRAILER-DATA"

    def test_inspect_finds_everything(self):
        info = inspect(self.build())
        names = {t["name"]: t for t in info["tags"]}
        self.assertEqual(info["format"], "jpeg")
        self.assertEqual(names["Make"]["flag"], "device")
        self.assertEqual(names["Coordenadas"]["value"], "-23.550333, -46.633056")
        self.assertEqual(names["Coordenadas"]["flag"], "location")
        self.assertEqual(names["Iptc4xmpExt:DigitalSourceType"]["flag"], "ai")
        self.assertEqual(names["dc:creator"]["value"], "Fulano de Tal")
        self.assertEqual(names["By-line"]["value"], "Autor")
        self.assertEqual(names["claim_generator"]["value"], "OpenAI-API")
        self.assertEqual(names["Software"]["flag"], "ai")
        self.assertIn("Comment", names)
        self.assertIn("Dados após o fim da imagem", names)
        self.assertTrue(names["Orientation"]["kept"])
        self.assertGreaterEqual(info["summary"]["ai"], 4)

    def test_clean_keeps_pixels_and_orientation(self):
        for progressive in (False, True):
            src = self.build(progressive)
            out = clean(src)
            self.assertEqual(pixels(src), pixels(out))
            after = inspect(out)
            self.assertEqual(after["summary"]["removable"], 0, after["tags"])
            self.assertNotIn(b"Apple", out)
            self.assertNotIn(b"OpenAI", out)
            self.assertNotIn(b"TRAILER", out)
            with Image.open(io.BytesIO(out)) as im:
                self.assertEqual(im.getexif().get(0x0112), 6)

    def test_clean_without_orientation(self):
        out = clean(self.build(), keep_orientation=False)
        self.assertEqual(inspect(out)["tags"], [])


@unittest.skipIf(Image is None, "Pillow não instalado")
class PngTest(unittest.TestCase):
    def test_png_text_and_exif(self):
        from PIL.PngImagePlugin import PngInfo
        meta = PngInfo()
        meta.add_text("parameters", "a cat, Steps: 30, Sampler: Euler a, Model: sdxl")
        meta.add_itxt("XML:com.adobe.xmp", XMP.decode())
        meta.add_text("Author", "Fulano")
        buf = io.BytesIO()
        Image.linear_gradient("L").save(buf, "PNG", pnginfo=meta, exif=make_exif())
        src = buf.getvalue()
        info = inspect(src)
        names = {t["name"]: t for t in info["tags"]}
        self.assertEqual(names["parameters"]["flag"], "ai")
        self.assertEqual(names["Iptc4xmpExt:DigitalSourceType"]["flag"], "ai")
        self.assertIn("GPSLatitude", names)
        out = clean(src)
        self.assertEqual(pixels(src), pixels(out))
        self.assertEqual(inspect(out)["summary"]["removable"], 0)


@unittest.skipIf(Image is None, "Pillow não instalado")
class WebpTest(unittest.TestCase):
    def test_webp(self):
        buf = io.BytesIO()
        Image.radial_gradient("L").convert("RGB").save(buf, "WEBP", lossless=True, exif=make_exif(), xmp=XMP)
        src = buf.getvalue()
        info = inspect(src)
        self.assertGreater(info["summary"]["ai"], 0)
        out = clean(src)
        self.assertEqual(pixels(src), pixels(out))
        self.assertEqual(inspect(out)["summary"]["removable"], 0)
        with Image.open(io.BytesIO(out)) as im:
            self.assertEqual(im.getexif().get(0x0112), 6)


class OrientationTest(unittest.TestCase):
    def test_roundtrip(self):
        from metaclean.parsers import orientation_tiff
        self.assertEqual(tiff_orientation(orientation_tiff(8)), 8)


if __name__ == "__main__":
    unittest.main()
