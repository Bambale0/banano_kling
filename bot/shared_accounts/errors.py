class AuthenticationError(ValueError):
    """Untrusted, expired, or revoked credentials."""


class PreviewConflict(ValueError):
    """The caller must reload the current revision."""
