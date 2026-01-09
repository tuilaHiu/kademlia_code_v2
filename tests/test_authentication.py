"""Tests for authentication helpers."""

from __future__ import annotations

import unittest

from authentication import DEFAULT_AUTH_CODE, create_peer_id, verify_auth_code


class AuthenticationTests(unittest.TestCase):
    """Unit tests for authentication helper functions."""

    def test_create_peer_id_deterministic(self: "AuthenticationTests") -> None:
        """Ensure peer IDs are deterministic for a given username."""
        expected = "3x9az88Dkbxa6tkKByxqEn7jBTJCJCD4dVvou49L24ET"
        self.assertEqual(create_peer_id("alice"), expected)

    def test_verify_auth_code(self: "AuthenticationTests") -> None:
        """Ensure auth code verification works for valid and invalid inputs."""
        self.assertTrue(verify_auth_code(DEFAULT_AUTH_CODE))
        self.assertFalse(verify_auth_code("wrong-code"))


if __name__ == "__main__":
    unittest.main()
