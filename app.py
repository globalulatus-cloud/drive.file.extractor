import streamlit as st
import csv
import re
from io import StringIO

from google.oauth2 import service_account
from googleapiclient.discovery import build

st.set_page_config(page_title="Drive Audio Link Extractor", layout="centered")
st.title("Google Drive Audio Link Extractor (Streamlit Cloud Safe)")

folder_url = st.text_input("Google Drive Folder URL (Regular or Shared Drive)")

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def is_audio_file(name: str) -> bool:
    name = name.lower()
    return any(name.endswith(ext) for ext in AUDIO_EXTENSIONS)


def extract_folder_id(url: str):
    patterns = [
        r"/folders/([a-zA-Z0-9_-]+)",
        r"/drive/folders/([a-zA-Z0-9_-]+)",
        r"id=([a-zA-Z0-9_-]+)",
        r"^([a-zA-Z0-9_-]{25,})$",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


@st.cache_resource
def get_drive_service():
    """
    Streamlit Cloud safe: uses a service account stored in st.secrets.
    No token.json, no local browser OAuth, no credentials.json file.
    """
    if "gcp_service_account" not in st.secrets:
        st.error("Missing Streamlit secret: gcp_service_account")
        st.stop()

    creds = service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=SCOPES,
    )

    return build("drive", "v3", credentials=creds)


def list_children(service, folder_id):
    """
    Handles pagination and Shared Drive support.
    """
    all_items = []
    page_token = None

    while True:
        resp = (
            service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="nextPageToken, files(id,name,mimeType,createdTime,webViewLink)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                corpora="allDrives",
                pageToken=page_token,
                pageSize=1000,
            )
            .execute()
        )

        all_items.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")

        if not page_token:
            break

    return all_items


def scan_folder_recursive(service, folder_id, path=""):
    """
    Recursively scan folder for audio files.
    Returns rows for CSV.
    """
    results = []
    items = list_children(service, folder_id)

    for item in items:
        mime = item.get("mimeType", "")
        name = item.get("name", "")
        file_id = item.get("id", "")
        created = item.get("createdTime", "")
        webview = item.get("webViewLink", "")

        if mime == "application/vnd.google-apps.folder":
            new_path = f"{path}/{name}" if path else name
            results.extend(scan_folder_recursive(service, file_id, new_path))
        else:
            if is_audio_file(name):
                share_link = f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
                direct_link = f"https://drive.google.com/uc?id={file_id}"

                results.append(
                    [
                        name,
                        path,
                        webview,
                        share_link,
                        direct_link,
                        created,
                        file_id,
                    ]
                )

    return results


def run_extraction():
    folder_id = extract_folder_id(folder_url)
    if not folder_id:
        st.error("Invalid folder URL / ID")
        return

    service = get_drive_service()

    with st.spinner("Scanning Drive folder recursively..."):
        results = scan_folder_recursive(service, folder_id)

    st.success(f"Done. Found {len(results)} audio files.")

    if not results:
        st.warning("No audio files found, or the folder isn't shared with the service account.")
        return

    csv_buffer = StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerow(
        [
            "File Name",
            "Folder Path",
            "View Link",
            "Share Link",
            "Direct Download Link",
            "Uploaded Date",
            "File ID",
        ]
    )
    writer.writerows(results)

    st.download_button(
        label="Download CSV",
        data=csv_buffer.getvalue(),
        file_name="audio_links.csv",
        mime="text/csv",
    )


if st.button("Start Extraction"):
    run_extraction()
