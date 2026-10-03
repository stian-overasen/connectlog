#!/usr/bin/env python3
"""
Garmin Connect OAuth Setup
Authenticates with Garmin Connect and saves session token to OS keychain
"""

import sys
from getpass import getpass

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from credentials import GarminSessionStorageError, save_garmin_session_token


def verify_session_token(session_token):
    """Log in with only the session token to confirm it authenticates.

    The credential login can appear to succeed with an unauthenticated session
    (e.g. when Garmin rate-limits the IP), so check before storing the token.

    Returns:
        The account's full name.
    """
    client = Garmin()
    client.login(session_token)
    full_name = client.get_full_name()
    if not full_name:
        raise GarminConnectAuthenticationError("session is not authenticated (no profile returned)")
    return full_name


def setup_oauth():
    """Authenticate with Garmin Connect and save session token to keychain."""
    print("Garmin Connect OAuth Setup")
    print("=" * 50)
    print()

    # Get credentials
    email = input("Enter your Garmin Connect email: ").strip()
    password = getpass("Enter your Garmin Connect password: ")

    print("\nAuthenticating with Garmin Connect...")

    try:
        # Create Garmin client and login
        client = Garmin(email, password, prompt_mfa=lambda: input("Enter MFA code (sent via SMS/email): ").strip())
        client.login()

        # Get OAuth session token
        session_token = client.client.dumps()

        print("Verifying session token...")
        full_name = verify_session_token(session_token)

        # Save token in OS keychain
        save_garmin_session_token(session_token)

        print("\n✓ Authentication successful!")
        print(f"✓ Logged in as: {full_name}")
        print("✓ Session token saved to OS keychain (service: connectlog, account: garmin_session)")
        print("\nYou can now start the MCP server from your MCP client.")

    except GarminSessionStorageError as e:
        print(f"\n✗ Authentication succeeded, but failed to store token: {e}")
        print("\nPlease ensure your OS keychain is available and try again.")
        return False

    except GarminConnectTooManyRequestsError:
        print("\n✗ Too many requests. Garmin is rate-limiting your IP.")
        print("\nPlease wait a few minutes and try again.")
        return False

    except GarminConnectAuthenticationError as e:
        print(f"\n✗ Authentication failed: {e}")
        print("\nPlease check your credentials and MFA code, then try again.")
        print("If this keeps happening, Garmin may be rate-limiting your IP; wait a few minutes.")
        return False

    except GarminConnectConnectionError as e:
        print(f"\n✗ Could not connect to Garmin Connect: {e}")
        print("\nPlease check your internet connection and try again.")
        return False

    except Exception as e:
        print(f"\n✗ Authentication failed: {e}")
        print("\nPlease check your credentials and try again.")
        return False

    return True


def main():
    """Console script entry point."""
    sys.exit(0 if setup_oauth() else 1)


if __name__ == "__main__":
    main()
