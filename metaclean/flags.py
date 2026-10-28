"""Classifica cada tag: IA, localização, dispositivo ou identidade.

As regras de IA cobrem o que plataformas como Instagram e Facebook usam para
aplicar o rótulo "Informações de IA": C2PA, DigitalSourceType do IPTC e
assinaturas de geradores conhecidos.
"""

import re

AI_NAME = re.compile(
    r"DigitalSourceType|^C2PA|claim_generator|^parameters$|^prompt$|^workflow$|"
    r"sd-metadata|^Dream$|invokeai|AIGC|ai_generated|GenAI|provenance", re.I)

AI_VALUE = [
    (r"trainedAlgorithmicMedia", "Marcado como gerado por IA (IPTC trainedAlgorithmicMedia)"),
    (r"compositeWithTrainedAlgorithmicMedia", "Marcado como editado com IA (IPTC)"),
    (r"algorithmicMedia", "Marcado como mídia algorítmica (IPTC)"),
    (r"Made with AI|AI[- ]generated|Generated (with|by) AI|Gerad[oa] (com|por) IA", "Texto declara uso de IA"),
    (r"DALL[-·\s]?E|OpenAI|ChatGPT|\bSora\b", "Assinatura da OpenAI"),
    (r"Midjourney", "Assinatura do Midjourney"),
    (r"Firefly|Generative (Fill|Expand)", "Assinatura do Adobe Firefly"),
    (r"Stable ?Diffusion|SDXL|Negative prompt:|Steps: \d+|ComfyUI|Automatic1111|InvokeAI|NovelAI",
     "Parâmetros de Stable Diffusion/ComfyUI"),
    (r"\bImagen\b|\bGemini\b|SynthID|Nano ?Banana", "Assinatura do Google"),
    (r"Bing Image Creator|Microsoft Designer|\bCopilot\b", "Assinatura da Microsoft"),
    (r"Meta AI|Imagine with Meta", "Assinatura da Meta"),
    (r"\bClaude\b|Anthropic", "Assinatura da Anthropic (Claude)"),
    (r"\bGrok\b|Leonardo\.?ai|Ideogram|FLUX\.?1|\bRunway\b|\bKling\b|Recraft", "Assinatura de gerador de imagens"),
    (r"Galaxy AI|Generative Edit|Magic Editor|Photo Assist", "Edição com IA no celular"),
]
AI_VALUE = [(re.compile(p, re.I), reason) for p, reason in AI_VALUE]

DEVICE = re.compile(
    r"^(Make|Model|Software|HostComputer|SerialNumber|LensMake|LensModel|LensSerialNumber|"
    r"LensInfo|MakerNote|ImageUniqueID|.*:(Make|Model|SerialNumber|Lens|LensModel|"
    r"CreatorTool|ImageUniqueID|DocumentID|OriginalDocumentID|InstanceID))$", re.I)
IDENTITY = re.compile(
    r"^(Artist|Copyright|OwnerName|XPAuthor|By-line|Writer-Editor|Contact|Credit|"
    r"CopyrightNotice|.*:(creator|rights|Owner|CameraOwnerName|AuthorsPosition|"
    r"CaptionWriter|Credit|CreatorContactInfo|CiEmailWork|CiTelWork|CiAdrExtadr))$", re.I)
LOCATION = re.compile(
    r"^(City|Sub-location|Province-State|Country|Country-Code|.*:(City|State|Country|"
    r"Location|GPS\w*|LocationShown|LocationCreated|Sublocation))$", re.I)


def classify(t):
    name, value = t["name"], t["value"]
    if t.get("warning"):
        return _set(t, "ai", "Marca d'água nos pixels: remover metadados não apaga")
    for pattern, reason in AI_VALUE:
        if pattern.search(value):
            return _set(t, "ai", reason)
    if t["group"] == "C2PA" or name.startswith("C2PA"):
        return _set(t, "ai", "Credencial de conteúdo C2PA: usada pelas redes para rotular IA")
    if AI_NAME.search(name):
        if name.lower() in ("parameters", "prompt", "workflow"):
            return _set(t, "ai", "Prompt/parâmetros de geração gravados na imagem")
        return _set(t, "ai", "Campo usado para declarar origem por IA")
    if t["group"] == "GPS" or LOCATION.match(name):
        return _set(t, "location", "Revela onde a foto foi tirada")
    if DEVICE.match(name):
        return _set(t, "device", "Identifica o aparelho ou software")
    if IDENTITY.match(name):
        return _set(t, "identity", "Pode identificar o autor")
    return t


def _set(t, flag, reason):
    t["flag"], t["reason"] = flag, reason
    return t
