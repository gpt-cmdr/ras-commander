#!/usr/bin/env python3
"""Extract the verified official HEC-RAS 7.0.1 combined installer, without running it.

Python 3.11+; standard library only. Output must be a new directory outside Git.
The ISSetupStream v4 archive decoding follows ISx by YX Hao/lifenjoiner:
https://github.com/Coldblackice/InstallShield-installer-extractor-ISx/tree/098e866fa5341db4424d3831d40943c01b88aefe

MIT License
Copyright (c) 2017 lifenjoiner

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import argparse
import hashlib
import json
import mmap
from pathlib import Path, PureWindowsPath
import shutil
import struct
import tempfile
import zlib


INSTALLER_SHA256 = "f3d28695bd98cbc7a1bcb5bdaea073c5c512a071a22a9d3bfd90a3309f405003"
MSI_SHA256 = "0aad915440bb8826386dfaa93b026c662ab6d5a0a73399a6efb90b452fb65e43"
MSI_NAME = "HEC-RAS 7.0.1.msi"
CHUNK = 1024 * 1024
MAX_MEMBER_BYTES = 512 * 1024 * 1024


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _members(data):
    """Read bounded PE and ISSetupStream metadata; return flat archive members."""
    _require(data[:2] == b"MZ", "Installer is not a PE file")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    _require(pe + 24 <= len(data) and data[pe:pe + 4] == b"PE\0\0", "Invalid PE header")
    count = struct.unpack_from("<H", data, pe + 6)[0]
    optional_size = struct.unpack_from("<H", data, pe + 20)[0]
    sections = pe + 24 + optional_size
    _require(0 < count <= 96 and sections + count * 40 <= len(data), "Invalid PE sections")
    payload = max(sum(struct.unpack_from("<II", data, sections + i * 40 + 16))
                  for i in range(count))
    _require(payload + 46 <= len(data), "Missing installer payload")
    signature, count, kind = struct.unpack_from("<14sHI", data, payload)
    _require(signature == b"ISSetupStream\0" and count == 10 and kind == 4,
             "Expected the official 7.0.1 ISSetupStream v4 archive")
    offset = payload + 46
    members = []
    names = set()
    for _ in range(count):
        _require(offset + 48 <= len(data), "Truncated archive member header")
        name_bytes, flags, _, length, _, compressed = struct.unpack_from("<II2sI8sH", data, offset)
        offset += 48  # v4 adds 24 reserved bytes to the 24-byte attributes
        _require(0 < name_bytes < 520 and name_bytes % 2 == 0 and flags == 6 and compressed == 1,
                 "Unsupported member encoding")
        _require(offset + name_bytes + length <= len(data), "Truncated archive member")
        name = data[offset:offset + name_bytes].decode("utf-16-le").rstrip("\0")
        offset += name_bytes
        path = PureWindowsPath(name)
        _require(name and path.name == name and not path.is_absolute()
                 and not any(c in name for c in ':<>"|?*\0') and name not in {".", ".."}
                 and name.casefold() not in names, "Unsafe or duplicate archive member name")
        names.add(name.casefold())
        members.append((name, offset, length))
        offset += length
    return members


def _extract_member(data, name, offset, length, target):
    seed = name.encode("utf-8")
    key = bytes(value ^ (0x13, 0x35, 0x86, 0x07)[i % 4] for i, value in enumerate(seed))
    block_key = bytes(key[i % len(key)] for i in range(1024))
    chunk_key = block_key * (CHUNK // 1024)
    translation = bytes((~((value << 4) | (value >> 4))) & 255 for value in range(256))
    decoder = zlib.decompressobj()
    digest = hashlib.sha256()
    size = crc = 0
    with target.open("xb") as stream:
        for position in range(0, length, CHUNK):
            block = data[offset + position:offset + min(position + CHUNK, length)].translate(translation)
            decoded = (int.from_bytes(block, "little")
                       ^ int.from_bytes(chunk_key[:len(block)], "little")).to_bytes(len(block), "little")
            plain = decoder.decompress(decoded, MAX_MEMBER_BYTES - size + 1)
            _require(size + len(plain) <= MAX_MEMBER_BYTES, "Extracted member exceeds size limit")
            stream.write(plain)
            digest.update(plain)
            crc = zlib.crc32(plain, crc)
            size += len(plain)
        tail = decoder.flush()
        _require(size + len(tail) <= MAX_MEMBER_BYTES, "Extracted member exceeds size limit")
        stream.write(tail)
        digest.update(tail)
        crc = zlib.crc32(tail, crc)
        size += len(tail)
    _require(decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail,
             "Incomplete or invalid compressed archive member")
    return {"name": name, "payload_offset": offset, "compressed_bytes": length,
            "size_bytes": size, "sha256": digest.hexdigest(), "crc32": f"{crc:08x}"}


def extract_installer(installer, output):
    installer = Path(installer).resolve(strict=True)
    output = Path(output).absolute()
    _require(not output.exists(), "Output must be a new directory")
    checkout = Path(__file__).resolve().parents[2]
    _require(not output.resolve().is_relative_to(checkout), "Keep vendor files outside the source checkout")
    with installer.open("rb") as stream:
        _require(hashlib.file_digest(stream, "sha256").hexdigest() == INSTALLER_SHA256,
                 "Installer checksum differs from the verified official 7.0.1 combined release")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="." + output.name + "-", dir=output.parent))
    try:
        with installer.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
            records = [_extract_member(data, name, offset, length, temporary / name)
                       for name, offset, length in _members(data)]
        msi = next((record for record in records if record["name"] == MSI_NAME), None)
        _require(msi and msi["sha256"] == MSI_SHA256, "Extracted MSI checksum mismatch")
        receipt = {"installer_sha256": INSTALLER_SHA256, "format": "ISSetupStream v4",
                   "operation": "archive extraction only", "members": records}
        (temporary / "extraction.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        temporary.rename(output)
    except BaseException:
        _require(temporary.resolve().parent == output.parent.resolve(), "Unexpected temporary directory")
        shutil.rmtree(temporary)
        raise
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    print(extract_installer(**vars(parser.parse_args())))


if __name__ == "__main__":
    main()
