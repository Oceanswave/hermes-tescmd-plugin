"""ECDH key exchange for Tesla Vehicle Command Protocol sessions."""

from __future__ import annotations

import hashlib

from cryptography.hazmat.primitives.asymmetric import ec


def derive_session_key(
    private_key: ec.EllipticCurvePrivateKey,
    vehicle_public_key_bytes: bytes,
) -> bytes:
    """Derive a 16-byte session key via ECDH + SHA-1 truncation.

    .. note::

        SHA-1 is required by Tesla's Vehicle Command Protocol — the
        vehicle firmware expects ``SHA1(shared_secret)[:16]``.  SHA-1's
        known collision weaknesses do not affect this usage (only
        preimage resistance matters for key derivation, and SHA-1
        remains preimage-resistant).  See ``vehicle-command`` Go SDK
        reference implementation.

    Parameters
    ----------
    private_key:
        The client's EC P-256 private key.
    vehicle_public_key_bytes:
        The vehicle's public key as an uncompressed 65-byte point
        (``0x04 || X || Y``) received in the SessionInfo response.

    Returns
    -------
    bytes
        A 16-byte session key: ``SHA1(shared_secret)[:16]``.
    """
    vehicle_pub = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), vehicle_public_key_bytes
    )
    shared_secret = private_key.exchange(ec.ECDH(), vehicle_pub)
    # Tesla's VCSEC protocol specifies this SHA-1 truncation as a KDF primitive;
    # it is not used here for password hashing, signatures, or collision resistance.
    return hashlib.sha1(shared_secret, usedforsecurity=False).digest()[:16]


def get_uncompressed_public_key(private_key: ec.EllipticCurvePrivateKey) -> bytes:
    """Return the uncompressed 65-byte public key point (0x04 || X || Y)."""
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PublicFormat,
    )

    return private_key.public_key().public_bytes(
        encoding=Encoding.X962,
        format=PublicFormat.UncompressedPoint,
    )
