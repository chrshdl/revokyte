"""Verification helpers for signed artifact installs.

Used by the telemetry-feed installer (:mod:`.installer`): SHA-256 hashing,
raw Ed25519 detached-signature verification against a base64 public key,
and safe tarball extraction.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import tarfile
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def sha256_file(path: Path | str) -> str:
    """Streaming SHA-256 of a file, lowercase hex."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest().lower()


def verify_signature(data: bytes, signature: bytes, pubkey_b64: str) -> bool:
    """Return True iff ``signature`` is a valid Ed25519 signature over ``data``
    for the given base64-encoded public key."""
    public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(pubkey_b64))
    try:
        public_key.verify(signature, data)
        return True
    except InvalidSignature:
        return False


def flatten_extract(tar: tarfile.TarFile, dest_dir: Path):
    """
    Extracts tarball. If all files are in a single top-level dir,
    strips that dir to avoid <dest_dir>/<pkg>-v0.3.4/ structure.
    """
    members = tar.getmembers()
    if not members:
        return

    first_part = members[0].name.split("/")[0]
    is_nested = all(m.name.startswith(first_part + "/") for m in members)

    def _filter(member: tarfile.TarInfo, dest_path: str):
        if is_nested:
            if member.name == first_part:
                return None  # skip the bare top-level directory entry
            member = copy.copy(member)
            member.name = member.name.split("/", 1)[1]
        # data_filter blocks absolute paths, path traversal, symlink attacks,
        # and special files (devices, fifos). Requires Python 3.12+.
        return tarfile.data_filter(member, dest_path)

    tar.extractall(path=dest_dir, filter=_filter)
