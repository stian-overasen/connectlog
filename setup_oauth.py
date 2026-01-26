#!/usr/bin/env python3
"""
Garmin Connect OAuth Setup
Authenticates with Garmin Connect and saves session token to .env file
"""

import os
from getpass import getpass
from garminconnect import Garmin


def setup_oauth():
    """Authenticate with Garmin Connect and save session token."""
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
        
        # Save to .env file
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        
        with open(env_path, "w") as f:
            f.write(f"# Garmin Connect OAuth session token\n")
            f.write(f"# Generated: {os.popen('date').read().strip()}\n")
            f.write(f"GARMIN_SESSION={session_token}\n")
        
        print(f"\n✓ Authentication successful!")
        print(f"✓ Session token saved to: {env_path}")
        print(f"\nYou can now run the Flask app with: python app.py")
        
    except Exception as e:
        print(f"\n✗ Authentication failed: {e}")
        print("\nPlease check your credentials and try again.")
        return False
    
    return True


if __name__ == "__main__":
    setup_oauth()
