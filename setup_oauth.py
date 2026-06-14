#!/usr/bin/env python3
"""
Garmin Connect OAuth Setup
Authenticates with Garmin Connect and saves session token to .env file
"""

import os
from getpass import getpass

from garminconnect import Garmin


def prompt_mfa() -> str:
    """Prompt for Garmin Connect MFA verification code."""
    return input("Enter your Garmin MFA code: ").strip()


def setup_oauth():
    """Authenticate with Garmin Connect and save session token."""
    print("Garmin Connect OAuth Setup")
    print("=" * 50)
    print()

    # Get credentials
    email = input("Enter your Garmin Connect email: ").strip()
    password = getpass("Enter your Garmin Connect password: ")

    print("\nAuthenticating with Garmin Connect...")
    print("(If MFA is enabled on your account, you will be prompted for a verification code.)")

    try:
        # Create Garmin client and login
        client = Garmin(email, password, prompt_mfa=prompt_mfa)
        client.login()

        # Get OAuth session token
        session_token = client.garth.dumps()

        # Save to .env file
        env_path = os.path.join(os.path.dirname(__file__), ".env")

        with open(env_path, "w") as f:
            f.write("# Garmin Connect OAuth session token\n")
            f.write(f"# Generated: {os.popen('date').read().strip()}\n")
            f.write(f"GARMIN_SESSION={session_token}\n")

        print("\n✓ Authentication successful!")
        print(f"✓ Session token saved to: {env_path}")
        print("\nYou can now run the Flask app with: uv run app.py")

    except Exception as e:
        print(f"\n✗ Authentication failed: {e}")
        print("\nPlease check your credentials (and MFA code, if applicable) and try again.")
        return False

    return True


if __name__ == "__main__":
    setup_oauth()
