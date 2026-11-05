"""Create a local Kite session for read-only testing without displaying the access token."""

from __future__ import annotations

import os
from getpass import getpass
from pathlib import Path

from dotenv import load_dotenv, set_key
from kiteconnect import KiteConnect


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    env_path = project_root / ".env"
    load_dotenv(dotenv_path=env_path)

    api_key = os.environ.get("ZERODHA_API_KEY")
    api_secret = os.environ.get("ZERODHA_API_SECRET")
    if not api_key or not api_secret:
        print("Missing ZERODHA_API_KEY or ZERODHA_API_SECRET in the local .env file.")
        return 1

    kite = KiteConnect(api_key=api_key)
    print("Open this URL and complete Kite login:")
    print(kite.login_url())
    request_token = getpass("Paste the redirected request_token (input hidden): ").strip()
    if not request_token:
        print("No request token supplied.")
        return 1

    try:
        session = kite.generate_session(request_token, api_secret=api_secret)
        access_token = session.get("access_token")
        if not access_token:
            print("Kite did not return an access token.")
            return 1

        set_key(str(env_path), "KITE_API_KEY", api_key)
        set_key(str(env_path), "KITE_ACCESS_TOKEN", access_token)
    except Exception as exc:
        print(f"Kite authentication failed ({type(exc).__name__}). No credential was displayed.")
        return 1

    print("Kite session created and saved to the local, Git-ignored .env file.")
    print("The access token was not displayed. Run the read-only smoke test next.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
