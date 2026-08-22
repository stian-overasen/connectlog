#!/usr/bin/env python3
"""Keychain-backed Garmin session token storage helpers."""

import keyring
from keyring.errors import KeyringError

KEYCHAIN_SERVICE = "connectlog"
KEYCHAIN_ACCOUNT = "garmin_session"


class GarminSessionStorageError(Exception):
    """Base exception for Garmin session storage failures."""


class MissingGarminSessionError(GarminSessionStorageError):
    """Raised when no Garmin session token exists in keychain."""


def load_garmin_session_token():
    """Load GARMIN_SESSION from OS keychain."""
    try:
        token = keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
    except KeyringError as exc:
        raise GarminSessionStorageError(f"Unable to access OS keychain: {exc}") from exc

    if not token:
        raise MissingGarminSessionError("No GARMIN_SESSION token found in OS keychain.")

    return token


def save_garmin_session_token(session_token):
    """Save GARMIN_SESSION to OS keychain."""
    if not session_token:
        raise GarminSessionStorageError("Refusing to store empty Garmin session token.")

    try:
        keyring.set_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT, session_token)
    except KeyringError as exc:
        raise GarminSessionStorageError(f"Unable to write GARMIN_SESSION to OS keychain: {exc}") from exc


def delete_garmin_session_token():
    """Delete GARMIN_SESSION from OS keychain if present."""
    try:
        keyring.delete_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
    except keyring.errors.PasswordDeleteError:
        return
    except KeyringError as exc:
        raise GarminSessionStorageError(f"Unable to delete GARMIN_SESSION from OS keychain: {exc}") from exc
