"""Leitura detalhada de manifestos C2PA: caixas JUMBF com conteúdo CBOR/JSON.

Abre cada asserção (ações, ferramenta, origem digital, assinatura) e devolve
os campos um a um, como "c2pa.actions.v2 › actions[0].action".
"""

import json
import re
import struct

MAX_FIELDS = 300
SKIP_KEYS = {"pad", "pad1", "pad2"}


class CborError(ValueError):
    pass


def _cbor(buf, p, depth=0):
    if depth > 40 or p >= len(buf):
        raise CborError("cbor")
    head = buf[p]
    major, info = head >> 5, head & 0x1F
    p += 1
    if info < 24:
        arg = info
    elif info in (24, 25, 26, 27):
        size = 1 << (info - 24)
        if major == 7 and info in (25, 26, 27):
            raw = buf[p:p + size]
            if size == 2:
                return struct.unpack(">e", raw)[0], p + size
            return struct.unpack(">f" if size == 4 else ">d", raw)[0], p + size
        arg = int.from_bytes(buf[p:p + size], "big")
        p += size
    elif info == 31 and major in (2, 3, 4, 5):
        arg = None
    else:
        raise CborError("cbor")

    if major == 0:
        return arg, p
    if major == 1:
        return -1 - arg, p
    if major in (2, 3):
        if arg is None:
            parts = []
            while buf[p] != 0xFF:
                v, p = _cbor(buf, p, depth + 1)
                parts.append(v)
            joined = (b"" if major == 2 else "").join(parts)
            return joined, p + 1
        raw = buf[p:p + arg]
        if len(raw) < arg:
            raise CborError("cbor")
        return (raw if major == 2 else raw.decode("utf-8", "replace")), p + arg
    if major == 4:
        out = []
        while (arg is None and buf[p] != 0xFF) or (arg is not None and len(out) < arg):
            v, p = _cbor(buf, p, depth + 1)
            out.append(v)
        return out, (p + 1 if arg is None else p)
    if major == 5:
        out = {}
        while (arg is None and buf[p] != 0xFF) or (arg is not None and len(out) < arg):
            k, p = _cbor(buf, p, depth + 1)
            v, p = _cbor(buf, p, depth + 1)
            out[str(k)] = v
        return out, (p + 1 if arg is None else p)
    if major == 6:
        return _cbor(buf, p, depth + 1)
    return {20: False, 21: True, 22: None}.get(arg), p


def cbor_loads(buf):
    return _cbor(buf, 0)[0]


def _boxes(buf):
    i = 0
    while i + 8 <= len(buf):
        size, kind = struct.unpack(">I4s", buf[i:i + 8])
        head = 8
        if size == 1:
            size, head = struct.unpack(">Q", buf[i + 8:i + 16])[0], 16
        elif size == 0:
            size = len(buf) - i
        if size < head or i + size > len(buf):
            return
        yield kind, buf[i + head:i + size]
        i += size


def _label(jumd):
    # jumd: 16 bytes de tipo UUID, 1 byte de flags e, se flags & 2, o rótulo.
    if len(jumd) > 17 and jumd[16] & 0x02:
        return jumd[17:].split(b"\0", 1)[0].decode("utf-8", "replace")
    return ""


def _walk(buf, path, out):
    """Percorre superboxes 'jumb' e devolve (rótulo, tipo, conteúdo)."""
    for kind, body in _boxes(buf):
        if kind != b"jumb":
            continue
        label, children = "", []
        for ck, cb in _boxes(body):
            if ck == b"jumd":
                label = _label(cb)
            else:
                children.append((ck, cb))
        here = path + [label] if label else path
        for ck, cb in children:
            if ck == b"jumb":
                _walk(_box(ck, cb), here, out)
            else:
                out.append((here, ck, cb))


def _box(kind, body):
    return struct.pack(">I", len(body) + 8) + kind + body


def _flatten(value, prefix, out):
    if len(out) >= MAX_FIELDS:
        return
    if isinstance(value, dict):
        for k, v in value.items():
            if k not in SKIP_KEYS:
                _flatten(v, f"{prefix}.{k}" if prefix else k, out)
    elif isinstance(value, list) and len(value) > 8 and all(isinstance(v, int) for v in value):
        out.append((prefix, f"({len(value)} bytes)"))  # hash gravado como lista de números
    elif isinstance(value, list):
        for n, v in enumerate(value):
            _flatten(v, f"{prefix}[{n}]", out)
    elif isinstance(value, (bytes, bytearray)):
        out.append((prefix, f"({len(value)} bytes)"))
    else:
        out.append((prefix, value))


CERT_NAME = re.compile(rb"\x06\x03\x55\x04(\x03|\x0a)[\x0c\x13\x14\x16](.)", re.S)
NAME_OIDS = {b"\x55\x04\x03": "CN", b"\x55\x04\x0a": "O", b"\x55\x04\x0b": "OU",
             b"\x55\x04\x06": "C", b"\x55\x04\x07": "L", b"\x55\x04\x08": "ST"}
COSE_ALGS = {-7: "ES256", -35: "ES384", -36: "ES512", -37: "PS256", -38: "PS384",
             -39: "PS512", -8: "Ed25519"}
GEN_TIME = re.compile(rb"\x18[\x0f-\x17](\d{14}(?:\.\d+)?Z)")
ACTIONS = {
    "c2pa.created": "criado", "c2pa.opened": "aberto", "c2pa.edited": "editado",
    "c2pa.placed": "elemento inserido", "c2pa.color_adjustments": "ajuste de cor",
    "c2pa.cropped": "recortado", "c2pa.resized": "redimensionado",
    "c2pa.converted": "convertido", "c2pa.published": "publicado",
    "c2pa.filtered": "filtro aplicado", "c2pa.drawing": "desenho",
    "c2pa.removed": "elemento removido", "c2pa.transcoded": "recodificado",
    "c2pa.repackaged": "reempacotado", "c2pa.watermarked": "marca d'água aplicada",
    "c2pa.edited.metadata": "metadados editados", "c2pa.orientation": "girado",
}
SOURCE_TYPES = {
    "trainedAlgorithmicMedia": "gerado por IA",
    "compositeWithTrainedAlgorithmicMedia": "editado com IA",
    "algorithmicMedia": "gerado por algoritmo",
    "compositeSynthetic": "composição sintética",
    "digitalCapture": "foto de câmera",
    "digitalArt": "arte digital",
    "minorHumanEdits": "pequenas edições humanas",
    "screenCapture": "captura de tela",
}


def _der(buf, p):
    tag, length = buf[p], buf[p + 1]
    p += 2
    if length & 0x80:
        n = length & 0x7F
        length = int.from_bytes(buf[p:p + n], "big")
        p += n
    return tag, buf[p:p + length], p + length


def _der_items(buf):
    p = 0
    while p < len(buf):
        tag, value, p = _der(buf, p)
        yield tag, value


def _der_name(value):
    parts = []
    for _, rdn in _der_items(value):
        for _, atv in _der_items(rdn):
            pair = list(_der_items(atv))
            key = NAME_OIDS.get(pair[0][1]) if len(pair) == 2 else None
            if key:
                parts.append(f"{key}={pair[1][1].decode('utf-8', 'replace')}")
    return ", ".join(parts)


def _der_time(tag, value):
    s = value.decode("ascii", "replace")
    if tag == 0x17:  # UTCTime AAMMDDhhmmssZ
        year = int(s[:2])
        s = str(year + (2000 if year < 50 else 1900)) + s[2:]
    return f"{s[:4]}-{s[4:6]}-{s[6:8]} {s[8:10]}:{s[10:12]} UTC"


def cert_info(der):
    """Emissor, titular, validade e número de série de um certificado X.509."""
    _, cert, _ = _der(der, 0)
    tbs = list(_der_items(list(_der_items(cert))[0][1]))
    if tbs[0][0] == 0xA0:  # versão explícita
        tbs = tbs[1:]
    validity = list(_der_items(tbs[3][1]))
    return {
        "serial": tbs[0][1].hex(),
        "issuer": _der_name(tbs[2][1]),
        "subject": _der_name(tbs[4][1]),
        "not_before": _der_time(*validity[0]),
        "not_after": _der_time(*validity[1]),
    }


def _cert_names(blob):
    names = []
    for m in CERT_NAME.finditer(blob):
        n = m.group(2)[0]
        value = blob[m.end():m.end() + n].decode("utf-8", "replace")
        field = "CN" if m.group(1) == b"\x03" else "O"
        if f"{field}={value}" not in names:
            names.append(f"{field}={value}")
    return names


def _signature_fields(label, body):
    out = []
    try:
        sig = cbor_loads(body)
        protected = cbor_loads(sig[0]) if sig[0] else {}
        headers = {**protected, **(sig[1] if isinstance(sig[1], dict) else {})}
        alg = headers.get("1")
        if alg is not None:
            out.append((f"{label} › algoritmo", COSE_ALGS.get(alg, str(alg))))
        chain = headers.get("33") or headers.get("x5chain") or []
        if isinstance(chain, (bytes, bytearray)):
            chain = [chain]
        for n, der in enumerate(chain):
            info = cert_info(der)
            who = "assinante" if n == 0 else f"cadeia[{n}]"
            out.append((f"{label} › {who}", info["subject"]))
            out.append((f"{label} › {who}.emissor", info["issuer"]))
            out.append((f"{label} › {who}.validade", f"{info['not_before']} até {info['not_after']}"))
            out.append((f"{label} › {who}.serial", info["serial"]))
        for key in ("sigTst", "sigTst2"):
            if key in headers:
                stamp = GEN_TIME.search(cbor_dump_bytes(headers[key]))
                if stamp:
                    t = stamp.group(1).decode()
                    out.append((f"{label} › data da assinatura",
                                f"{t[:4]}-{t[4:6]}-{t[6:8]} {t[8:10]}:{t[10:12]}:{t[12:14]} UTC"))
    except (CborError, IndexError, KeyError, TypeError, ValueError, struct.error):
        pass
    if not out:
        out = [(f"{label} › certificado", name) for name in _cert_names(body)]
    stamp = GEN_TIME.search(body)
    if stamp and not any("data da assinatura" in k for k, _ in out):
        t = stamp.group(1).decode()
        out.append((f"{label} › data da assinatura",
                    f"{t[:4]}-{t[4:6]}-{t[6:8]} {t[8:10]}:{t[10:12]}:{t[12:14]} UTC"))
    return out


def cbor_dump_bytes(value):
    """Junta todos os bytes de uma estrutura CBOR já decodificada (para busca)."""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, dict):
        return b"".join(cbor_dump_bytes(v) for v in value.values())
    if isinstance(value, list):
        return b"".join(cbor_dump_bytes(v) for v in value)
    return b""


def _agent(value):
    if isinstance(value, dict):
        return " ".join(str(value[k]) for k in ("name", "version") if k in value)
    return str(value) if value else ""


def _summary(decoded, signature):
    """Frases em português com o que o manifesto declara."""
    out, warnings = [], []
    gens, actions, sources = [], [], []
    for label, data in decoded:
        if not isinstance(data, dict):
            continue
        if label.startswith("c2pa.claim"):
            info = data.get("claim_generator_info")
            for item in info if isinstance(info, list) else [info]:
                if isinstance(item, dict) and item.get("name"):
                    gens.append(_agent(item))
            if not gens and data.get("claim_generator"):
                gens.append(str(data["claim_generator"]))
        if label.startswith("c2pa.actions"):
            for act in data.get("actions", []):
                if not isinstance(act, dict):
                    continue
                name = str(act.get("action", "?"))
                text = ACTIONS.get(name, name)
                agent = _agent(act.get("softwareAgent"))
                if agent:
                    text += f" por {agent}"
                actions.append(text)
                st = str(act.get("digitalSourceType", "")).rsplit("/", 1)[-1]
                if st:
                    sources.append(SOURCE_TYPES.get(st, st))
                if name == "c2pa.watermarked":
                    warnings.append("O manifesto registra que uma marca d'água foi aplicada nos pixels.")
                if act.get("description"):
                    out.append(("Descrição da ação", str(act["description"])))
        if "soft-binding" in label or "watermark" in label.lower():
            alg = data.get("alg", "")
            warnings.append(f"O manifesto declara uma marca d'água invisível nos pixels ({alg or label}).")
    if gens:
        out.insert(0, ("Gerado com", ", ".join(dict.fromkeys(gens))))
    if sources:
        out.insert(0, ("Origem declarada", ", ".join(dict.fromkeys(sources))))
    if actions:
        out.append(("Histórico de ações", "; ".join(actions)))
    for key, value in signature:
        if key.endswith("› assinante"):
            out.append(("Assinado por", value))
        elif key.endswith("› data da assinatura"):
            out.append(("Data da assinatura", value))
    return [{"name": k, "value": v, "summary": True} for k, v in out] + \
           [{"name": "Marca d'água invisível", "value": w, "warning": True} for w in dict.fromkeys(warnings)]


def parse(blob):
    """Campos do manifesto como dicts {name, value}; resumo em português primeiro."""
    items = []
    _walk(blob, [], items)
    fields, decoded, signature, mime = [], [], [], ""
    manifests = sum(1 for path, _, _ in items if path and path[-1].startswith("c2pa.claim"))
    for path, kind, body in items:
        label = path[-1] if path else "?"
        if label.startswith("urn:"):
            continue
        try:
            if kind == b"cbor":
                data = cbor_loads(body)
            elif kind == b"json":
                data = json.loads(body.decode("utf-8", "replace"))
            elif kind == b"bfdb":  # 1 byte de flags + tipo MIME
                mime = body[1:].split(b"\0", 1)[0].decode("ascii", "replace")
                continue
            elif kind == b"bidb":
                name = "miniatura embutida" if "thumbnail" in label else "dados embutidos"
                fields.append((label, f"{name} ({mime + ', ' if mime else ''}{len(body)} bytes)"))
                mime = ""
                continue
            else:
                continue
        except (CborError, ValueError, IndexError, struct.error, RecursionError):
            fields.append((label, f"({len(body)} bytes)"))
            continue
        if label.startswith("c2pa.signature"):
            sig = _signature_fields(label, body)
            signature += sig
            fields += sig
            continue
        decoded.append((label, data))
        flat = []
        _flatten(data, "", flat)
        for key, value in flat:
            fields.append((f"{label} › {key}" if key else label, value))
        if len(fields) >= MAX_FIELDS:
            break
    if not fields:
        return []
    head = _summary(decoded, signature)
    if manifests > 1:
        head.append({"name": "Manifestos encadeados", "value": f"{manifests} (histórico de edições anteriores)", "summary": True})
    return head + [{"name": k, "value": v} for k, v in fields]
