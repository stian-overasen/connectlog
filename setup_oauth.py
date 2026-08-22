#!/usr/bin/env python3
"""
Garmin Connect OAuth Setup
Authenticates with Garmin Connect and saves session token to OS keychain
"""

from getpass import getpass

from garminconnect import Garmin

from credentials import GarminSessionStorageError, save_garmin_session_token


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
        client = Garmin(email, password)
        client.login()

        # Get OAuth session token
        session_token = client.garth.dumps()

        # Save token in OS keychain
        save_garmin_session_token(session_token)

        print("\n✓ Authentication successful!")
        print("✓ Session token saved to OS keychain (service: connectlog, account: garmin_session)")
        print("\nYou can now run the MCP server with: uv run app.py")

    except GarminSessionStorageError as e:
        print(f"\n✗ Authentication succeeded, but failed to store token: {e}")
        print("\nPlease ensure your OS keychain is available and try again.")
        return False

    except Exception as e:
        print(f"\n✗ Authentication failed: {e}")
        print("\nPlease check your credentials and try again.")
        return False

    return True


if __name__ == "__main__":
    setup_oauth()
