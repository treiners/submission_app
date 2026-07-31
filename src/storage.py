"""
Storage backends for uploaded submission files.

Each backend implements upload_file(local_path, dest_folder, filename) and
returns a dict describing where the file ended up:
    {"backend": "local"|"dropbox"|"onedrive", "location": <path or URL>}

The app always saves the incoming upload to a local temp path first, then
hands it to the configured backend. If the configured cloud backend fails
(e.g. missing/invalid credentials, network issue), the app falls back to
local storage automatically so a submission is never lost.
"""
import os
import shutil
from pathlib import Path


class StorageError(Exception):
    pass


class LocalStorage:
    """Stores files on the server's local disk under LOCAL_UPLOAD_ROOT."""

    name = "local"

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def upload_file(self, local_path, dest_folder, filename):
        target_dir = self.root / dest_folder
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / filename
        shutil.copy2(local_path, target_path)
        return {"backend": "local", "location": str(target_path)}


class DropboxStorage:
    """
    Stores files in a Dropbox account/team folder using a long-lived refresh
    token (so the app keeps working without re-authenticating every few hours).

    Setup (see README for full walkthrough):
      1. Create an app at https://www.dropbox.com/developers/apps
      2. Enable the files.content.write permission
      3. Run the helper script get_dropbox_refresh_token.py to obtain a
         refresh token, and put APP_KEY / APP_SECRET / REFRESH_TOKEN in .env
    """

    name = "dropbox"

    def __init__(self, app_key, app_secret, refresh_token, root_folder="/Submissions"):
        if not (app_key and app_secret and refresh_token):
            raise StorageError("Dropbox credentials are not configured (see .env.example).")
        try:
            import dropbox
        except ImportError as e:
            raise StorageError("The 'dropbox' package is not installed (pip install dropbox).") from e

        self._dropbox = dropbox
        self.client = dropbox.Dropbox(
            app_key=app_key,
            app_secret=app_secret,
            oauth2_refresh_token=refresh_token,
        )
        self.root_folder = root_folder.rstrip("/")

    def upload_file(self, local_path, dest_folder, filename):
        remote_path = f"{self.root_folder}/{dest_folder}/{filename}"
        with open(local_path, "rb") as f:
            data = f.read()
        try:
            self.client.files_upload(
                data, remote_path, mode=self._dropbox.files.WriteMode.overwrite
            )
        except Exception as e:
            raise StorageError(f"Dropbox upload failed: {e}") from e
        return {"backend": "dropbox", "location": remote_path}


class OneDriveStorage:
    """
    Stores files in a OneDrive/SharePoint drive via Microsoft Graph API, using
    an Azure AD app registration (client-credentials flow, no user login needed).

    NOT YET WIRED UP — fill in once you have an Azure AD app registration with
    Files.ReadWrite.All (application permission, admin-consented).

    Implementation sketch (uncomment/complete when ready):

        import msal, requests

        authority = f"https://login.microsoftonline.com/{tenant_id}"
        app = msal.ConfidentialClientApplication(
            client_id, authority=authority, client_credential=client_secret
        )
        token = app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )["access_token"]

        # PUT small files directly:
        url = (f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:"
               f"/{root_folder}/{dest_folder}/{filename}:/content")
        requests.put(url, headers={"Authorization": f"Bearer {token}"}, data=file_bytes)

        # For files > 4MB, use an upload session instead of a single PUT.
    """

    name = "onedrive"

    def __init__(self, tenant_id, client_id, client_secret, drive_id, root_folder="/Submissions"):
        if not (tenant_id and client_id and client_secret and drive_id):
            raise StorageError("OneDrive credentials are not configured yet (see .env.example).")
        raise StorageError("OneDrive backend is not implemented yet — see storage.py for the sketch.")

    def upload_file(self, local_path, dest_folder, filename):
        raise StorageError("OneDrive backend is not implemented yet.")


def get_storage_backend(app_config):
    """Build the configured primary backend, and always return a LocalStorage
    fallback alongside it, e.g. (primary, fallback)."""
    backend_name = app_config.get("STORAGE_BACKEND", "local").lower()
    fallback = LocalStorage(app_config["LOCAL_UPLOAD_ROOT"])

    if backend_name == "local":
        return fallback, fallback

    if backend_name == "dropbox":
        try:
            primary = DropboxStorage(
                app_config.get("DROPBOX_APP_KEY"),
                app_config.get("DROPBOX_APP_SECRET"),
                app_config.get("DROPBOX_REFRESH_TOKEN"),
                app_config.get("DROPBOX_ROOT_FOLDER", "/Submissions"),
            )
            return primary, fallback
        except StorageError:
            return fallback, fallback

    if backend_name == "onedrive":
        try:
            primary = OneDriveStorage(
                app_config.get("ONEDRIVE_TENANT_ID"),
                app_config.get("ONEDRIVE_CLIENT_ID"),
                app_config.get("ONEDRIVE_CLIENT_SECRET"),
                app_config.get("ONEDRIVE_DRIVE_ID"),
                app_config.get("ONEDRIVE_ROOT_FOLDER", "/Submissions"),
            )
            return primary, fallback
        except StorageError:
            return fallback, fallback

    return fallback, fallback
