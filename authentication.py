"""Authentication helpers for generating and verifying peer identities."""

from __future__ import annotations

import hashlib
from typing import Final

import base58

DEFAULT_AUTH_CODE: Final[str] = "123456789"


def create_peer_id(username: str) -> str:
    """Create a peer ID from a username.

    Args:
        username: Username to hash.

    Returns:
        Base58-encoded SHA-256 digest of the username.
    """
    hashed = hashlib.sha256(username.encode("utf-8")).digest()
    return base58.b58encode(hashed).decode("utf-8")


def verify_auth_code(input_code: str, expected_code: str = DEFAULT_AUTH_CODE) -> bool:
    """Verify an authentication code.

    Args:
        input_code: Code provided by the user.
        expected_code: Expected code to match.

    Returns:
        True if the code matches; otherwise False.
    """
    return input_code == expected_code
