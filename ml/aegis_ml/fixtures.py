"""Synthetic demo/test fixtures generated at runtime (never committed as evidence).

Every generated file is plainly synthetic (test patterns, tones, pseudo-word text) and is labelled
"DEMO FIXTURE" wherever AEGIS displays it. The C2PA signing certificate is a throwaway test CA
created on the fly; it is not trusted by anything outside the test that created it.
"""

from __future__ import annotations

import datetime
import io
import json
import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path

import numpy as np
from PIL import Image, PngImagePlugin

HUMAN_STYLE_SAMPLE = (
    "Field notes, 14 March. The river was higher than last week, brown and quick under the footbridge. "
    "We counted eleven herons on the gravel bar before the rain started, then gave up and sheltered under "
    "the alders. Ravi thinks the new culvert upstream is changing how silt settles near the bend; I am not "
    "convinced yet, because the same pattern showed up in 2019 before any construction. Next visit we "
    "should bring the turbidity meter and take readings at both ends of the bar, morning and late afternoon."
)


def make_jpeg(
    path: Path, size: tuple[int, int] = (640, 480), quality: int = 88, exif_software: str | None = None
) -> Path:
    w, h = size
    yy, xx = np.mgrid[0:h, 0:w]
    rng = np.random.default_rng(1)
    arr = np.stack([(xx / w * 255), (yy / h * 255), ((xx + yy) % 64) * 4], axis=-1)
    arr = np.clip(arr + rng.normal(0, 6, arr.shape), 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)
    exif = Image.Exif()
    if exif_software:
        exif[0x0131] = exif_software
    img.save(path, "JPEG", quality=quality, exif=exif.tobytes() if exif_software else b"")
    return path


def make_png_with_declaration(path: Path) -> Path:
    img = Image.fromarray(np.full((256, 256, 3), (40, 80, 160), np.uint8))
    meta = PngImagePlugin.PngInfo()
    meta.add_text(
        "parameters", "DEMO FIXTURE: a test pattern, Steps: 20, Sampler: Euler, Model: stable diffusion (declared)"
    )
    img.save(path, "PNG", pnginfo=meta)
    return path


def make_wav(path: Path, seconds: float = 3.0, sr: int = 16000) -> Path:
    t = np.arange(int(seconds * sr)) / sr
    x = 0.3 * np.sin(2 * math.pi * 220 * t) * (0.5 + 0.5 * np.sin(2 * math.pi * 1.5 * t))
    x[int(sr * 1.2) : int(sr * 1.6)] = 0
    pcm = (x * 32767).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return path


def make_mp4(path: Path, seconds: int = 4) -> Path:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg is required to generate the video fixture")
    subprocess.run(  # noqa: S603
        [
            exe,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=320x240:rate=25:duration={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            "-metadata",
            "comment=DEMO FIXTURE test pattern",
            str(path),
        ],
        check=True,
        timeout=120,
    )
    return path


def make_pdf(path: Path, text: str) -> Path:
    """Minimal single-page PDF with embedded text (no third-party writer needed)."""
    safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    lines, line = [], ""
    for word in safe.split():
        if len(line) + len(word) > 90:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    lines.append(line)
    content = "BT /F1 10 Tf 50 780 Td 13 TL " + " ".join(f"({ln}) '" for ln in lines) + " ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 "
        "0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1"))
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    path.write_bytes(out.getvalue())
    return path


def make_docx(path: Path, paragraphs: list[str]) -> Path:
    import docx

    d = docx.Document()
    for p in paragraphs:
        d.add_paragraph(p)
    d.save(str(path))
    return path


def make_zip_bomb_like(path: Path) -> Path:
    """A ZIP whose single entry has an extreme compression ratio (for rejection tests)."""
    import zipfile

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "x")
        z.writestr("word/document.xml", b"\0" * (20 * 1024 * 1024))
    return path


def make_test_ca(directory: Path):
    """Throwaway ECDSA CA + leaf for C2PA signing in tests and demos."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = datetime.datetime.now(datetime.UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "AEGIS Demo Test CA (untrusted)"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AEGIS Demo"),
        ]
    )
    ku = dict(
        content_commitment=False,
        key_encipherment=False,
        data_encipherment=False,
        key_agreement=False,
        encipher_only=False,
        decipher_only=False,
    )
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=False, key_cert_sign=True, crl_sign=True, **ku), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    leaf = (
        x509.CertificateBuilder()
        .subject_name(
            x509.Name(
                [
                    x509.NameAttribute(NameOID.COMMON_NAME, "AEGIS Demo Signer"),
                    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AEGIS Demo"),
                ]
            )
        )
        .issuer_name(ca_name)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=False, crl_sign=False, **ku), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    pem = serialization.Encoding.PEM
    ca_path = directory / "demo-ca.pem"
    ca_path.write_bytes(ca.public_bytes(pem))
    chain = leaf.public_bytes(pem) + ca.public_bytes(pem)
    key = leaf_key.private_bytes(pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return chain, key, ca_path


def make_c2pa_signed_jpeg(path: Path, workdir: Path, source_type: str = "trainedAlgorithmicMedia") -> Path:
    """Sign a synthetic JPEG with a C2PA manifest using a throwaway CA; returns the CA PEM path."""
    import c2pa

    chain, key, ca_path = make_test_ca(workdir)
    src = io.BytesIO()
    Image.fromarray(np.full((120, 160, 3), (30, 60, 120), np.uint8)).save(src, "JPEG", quality=90)
    src.seek(0)
    manifest = {
        "claim_generator_info": [{"name": "aegis-demo-fixture", "version": "1.0"}],
        "title": path.name,
        "format": "image/jpeg",
        "assertions": [
            {
                "label": "c2pa.actions",
                "data": {
                    "actions": [
                        {
                            "action": "c2pa.created",
                            "digitalSourceType": f"http://cv.iptc.org/newscodes/digitalsourcetype/{source_type}",
                        }
                    ]
                },
            }
        ],
    }
    signer = c2pa.Signer.from_info(c2pa.C2paSignerInfo(c2pa.C2paSigningAlg.ES256, chain, key, None))
    out = io.BytesIO()
    c2pa.Builder(json.dumps(manifest)).sign(signer, "image/jpeg", src, out)
    path.write_bytes(out.getvalue())
    return ca_path


def tamper(path: Path, dest: Path, offset_from_end: int = 200) -> Path:
    data = bytearray(path.read_bytes())
    data[-offset_from_end] ^= 0xFF
    dest.write_bytes(bytes(data))
    return dest


def wav_header_only(path: Path) -> Path:
    """Corrupted WAV: valid RIFF header that claims data which is absent."""
    path.write_bytes(
        b"RIFF" + struct.pack("<I", 1_000_000) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
    )
    return path
