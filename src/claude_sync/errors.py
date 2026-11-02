class ClaudeSyncError(Exception):
    """A failure to report to the user without a traceback."""


class ConfirmationRequired(ClaudeSyncError):
    """A confirmation is needed but cannot be asked (no --yes, no TTY)."""
