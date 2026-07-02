"""Google Cloud Storage utilities for uploading backtest results and logs."""

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

try:
    from google.cloud import storage
    from google.oauth2 import service_account
    HAS_GCS = True
except ImportError:
    HAS_GCS = False


def get_gcs_client():
    """Get authenticated Google Cloud Storage client."""
    if not HAS_GCS:
        return None

    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not credentials_path:
        credentials_path = Path(__file__).parent.parent / "gcp-key.json"

    if isinstance(credentials_path, str):
        credentials_path = Path(credentials_path)

    if not credentials_path.exists():
        return None

    try:
        credentials = service_account.Credentials.from_service_account_file(
            str(credentials_path)
        )
        return storage.Client(credentials=credentials, project=credentials.project_id)
    except Exception as e:
        print(f"[GCS] Warning: Could not initialize GCS client: {e}")
        return None


def upload_to_gcs(
    local_path: Optional[str],
    bucket_name: str,
    remote_path: str,
    data_dict: Optional[dict] = None,
) -> bool:
    """
    Upload a file to Google Cloud Storage.

    Args:
        local_path: Path to local file to upload (or None if using data_dict)
        bucket_name: GCS bucket name
        remote_path: Remote path in bucket (e.g., "optimizer/NVDA/2026-01-15T10:30:00/results.json")
        data_dict: Optional dict to serialize as JSON instead of uploading file

    Returns:
        True if upload succeeded, False otherwise
    """
    if not HAS_GCS:
        print("[GCS] google-cloud-storage not installed. Skipping cloud upload.")
        return False

    client = get_gcs_client()
    if not client:
        print("[GCS] Cloud credentials not configured. Logs will be stored locally only.")
        return False

    try:
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(remote_path)

        if data_dict is not None:
            # Upload from dict (serialize to JSON)
            content = json.dumps(data_dict, indent=2, default=str)
            blob.upload_from_string(content, content_type="application/json")
            print(f"[GCS] ✓ Uploaded results to gs://{bucket_name}/{remote_path}")
        elif local_path and Path(local_path).exists():
            # Upload from file
            blob.upload_from_filename(local_path)
            print(f"[GCS] ✓ Uploaded logs to gs://{bucket_name}/{remote_path}")
        else:
            print(f"[GCS] Warning: local_path not found: {local_path}")
            return False

        return True
    except Exception as e:
        print(f"[GCS] Warning: Upload failed: {e}. Results stored locally.")
        return False


def upload_dataframe_as_json(
    df,
    bucket_name: str,
    remote_path: str,
) -> bool:
    """Upload pandas DataFrame as JSON to GCS."""
    if not HAS_GCS:
        return False

    try:
        data_dict = df.to_dict(orient="records")
        return upload_to_gcs(
            local_path=None,
            bucket_name=bucket_name,
            remote_path=remote_path,
            data_dict=data_dict,
        )
    except Exception as e:
        print(f"[GCS] Warning: DataFrame upload failed: {e}")
        return False


def upload_file_to_gcs(
    local_file_path: str,
    bucket_name: str,
    remote_file_path: str,
) -> bool:
    """Upload a file to GCS with error handling."""
    return upload_to_gcs(
        local_path=local_file_path,
        bucket_name=bucket_name,
        remote_path=remote_file_path,
    )
