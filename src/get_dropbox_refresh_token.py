"""
One-time helper to obtain a Dropbox refresh token for this app.

Usage:
    1. Create an app at https://www.dropbox.com/developers/apps
       - Choose "Scoped access", "Full Dropbox" or "App folder"
       - Under Permissions, enable files.content.write and files.content.read
    2. Copy the App key and App secret from the app's Settings tab
    3. Run: python get_dropbox_refresh_token.py
    4. Follow the printed URL, approve access, paste the code back in
    5. Copy the printed refresh token into .env as DROPBOX_REFRESH_TOKEN
       (and the app key/secret as DROPBOX_APP_KEY / DROPBOX_APP_SECRET)
"""
import dropbox
from dropbox import DropboxOAuth2FlowNoRedirect

APP_KEY = input("Dropbox App key: ").strip()
APP_SECRET = input("Dropbox App secret: ").strip()

auth_flow = DropboxOAuth2FlowNoRedirect(APP_KEY, APP_SECRET, token_access_type="offline")

authorize_url = auth_flow.start()
print("\n1. Go to this URL in your browser:")
print(authorize_url)
print("\n2. Click 'Allow' (you may need to log in first).")
print("3. Copy the authorization code shown.\n")

auth_code = input("Paste the authorization code here: ").strip()

try:
    result = auth_flow.finish(auth_code)
except Exception as e:
    print(f"Error: {e}")
    raise SystemExit(1)

print("\nSuccess! Add these to your .env file:\n")
print(f"DROPBOX_APP_KEY={APP_KEY}")
print(f"DROPBOX_APP_SECRET={APP_SECRET}")
print(f"DROPBOX_REFRESH_TOKEN={result.refresh_token}")
