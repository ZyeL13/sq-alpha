# schedulers/square_media.py — Binance Square media upload (V3 Phase 1)
#
# Implements the official upload flow from binance/binance-skills-hub,
# skills/binance/square-post/scripts/lib.mjs (read in Phase 0):
#   1. POST {V2}/image/presignedUrl {"imageName": basename}
#      -> {presignedUrl, fileTicket}
#   2. PUT <presignedUrl> with raw bytes, Content-Type: image/<ext>
#   3. Poll POST {V2}/image/imageStatus {"fileTicket"} every 3 s,
#      max 10 attempts; status 1 -> imageUrl (processed Square-hosted
#      URL), status 2 -> failed (failedReason).
# Publish itself lives in schedulers/poster.py; this module only
# uploads and returns the processed URL (or None on any failure —
# the caller falls back to text-only, never blocks a slot).
import os
import time

import requests

from config import BINANCE_SQUARE_KEY

BASE_URL_V2 = "https://www.binance.com/bapi/composite/v2/public/pgc/openApi"
PRESIGN_ENDPOINT = "/image/presignedUrl"
STATUS_ENDPOINT = "/image/imageStatus"

POLL_INTERVAL_SECONDS = 3
MAX_POLL_ATTEMPTS = 10

# Image formats the official helper accepts (lib.mjs CONTENT_TYPE_MAP).
# Anything else is rejected here instead of sent as
# application/octet-stream — an upload that Square cannot process
# would fail the poll anyway.
IMAGE_CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
}

# Max file size is NOT published in lib.mjs / SKILL.md (Phase 0).
# No client-side size cap is enforced; a too-large file fails at the
# presign/PUT/poll stage and falls back to text-only. The probe step
# will pin the real limit.


def _api_headers(api_key: str) -> dict:
    return {
        "X-Square-OpenAPI-Key": api_key,
        "Content-Type": "application/json",
        "clienttype": "binanceSkill",
    }


def _api_post(endpoint: str, api_key: str, body: dict, timeout: int = 15):
    """POST one V2 endpoint. Returns the data dict or raises."""
    r = requests.post(
        f"{BASE_URL_V2}{endpoint}",
        headers=_api_headers(api_key),
        json=body,
        timeout=timeout,
    )
    r.raise_for_status()
    result = r.json()
    # Official envelope: {"code": "000000", "data": {...}}.
    if isinstance(result, dict) and result.get("code") is not None:
        if result.get("code") != "000000":
            raise ValueError(
                f"API error [{result.get('code')}]: {result.get('message')}"
            )
        return result.get("data") or {}
    # Tolerate the success-flag envelope the v1 publish endpoint uses.
    if isinstance(result, dict) and result.get("success"):
        return result.get("data") or {}
    raise ValueError(f"Unexpected API response: {str(result)[:200]}")


def _poll_image_status(api_key: str, file_ticket: str) -> str:
    """Poll until the image is processed. Returns the processed URL."""
    last_status = None
    for attempt in range(1, MAX_POLL_ATTEMPTS + 1):
        data = _api_post(STATUS_ENDPOINT, api_key, {"fileTicket": file_ticket})
        status = data.get("status")
        last_status = status
        if status == 1:
            url = data.get("imageUrl")
            if not url:
                raise ValueError("imageStatus ready but no imageUrl returned")
            return url
        if status == 2:
            raise ValueError(
                f"Image processing failed: {data.get('failedReason')}"
            )
        if attempt < MAX_POLL_ATTEMPTS:
            time.sleep(POLL_INTERVAL_SECONDS)
    raise ValueError(f"Image status poll timed out after {MAX_POLL_ATTEMPTS} attempts (last status={last_status})")


def upload_image(path: str, api_key: str | None = None) -> str | None:
    """Upload one image file to Square. Returns the processed image
    URL, or None on ANY failure (caller falls back to text-only).

    Never raises for expected failures; unexpected exceptions are
    caught and logged the same way so a bad render can never kill
    the poster loop.
    """
    key = api_key or BINANCE_SQUARE_KEY
    if not key:
        print("  ⚠️ Square media: no API key configured")
        return None
    if not path or not os.path.isfile(path):
        print(f"  ⚠️ Square media: file not found: {path}")
        return None

    ext = os.path.splitext(path)[1].lstrip(".").lower()
    content_type = IMAGE_CONTENT_TYPES.get(ext)
    if not content_type:
        print(f"  ⚠️ Square media: unsupported image format: .{ext}")
        return None

    try:
        image_name = os.path.basename(path)
        data = _api_post(
            PRESIGN_ENDPOINT, key, {"imageName": image_name}
        )
        presigned_url = data.get("presignedUrl")
        file_ticket = data.get("fileTicket")
        if not presigned_url or not file_ticket:
            print("  ⚠️ Square media: presign returned no URL/ticket")
            return None

        with open(path, "rb") as f:
            file_bytes = f.read()
        r = requests.put(
            presigned_url,
            headers={"Content-Type": content_type},
            data=file_bytes,
            timeout=30,
        )
        if not r.ok:
            print(f"  ⚠️ Square media: upload PUT failed: HTTP {r.status_code}")
            return None

        url = _poll_image_status(key, file_ticket)
        print(f"  ✅ Square media uploaded: {url[:60]}...")
        return url
    except Exception as e:
        print(f"  ⚠️ Square media upload failed ({os.path.basename(path)}): {e}")
        return None
