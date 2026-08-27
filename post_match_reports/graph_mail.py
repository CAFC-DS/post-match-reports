from __future__ import annotations

import base64
import json
import mimetypes
import os
import time
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

import requests


GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
DIRECT_ATTACHMENT_LIMIT = 3 * 1024 * 1024
UPLOAD_CHUNK_SIZE = 10 * 320 * 1024


class GraphMailError(RuntimeError):
    pass


class GraphClient:
    def __init__(self, access_token: str, session=None, max_attempts: int = 4):
        self.session = session or requests.Session()
        self.max_attempts = max_attempts
        self.headers = {"Authorization": f"Bearer {access_token}"}

    def request(self, method: str, url: str, **kwargs):
        headers = dict(self.headers)
        headers.update(kwargs.pop("headers", {}))
        for attempt in range(self.max_attempts):
            response = self.session.request(method, url, headers=headers, **kwargs)
            if response.status_code not in {429, 500, 502, 503, 504}:
                break
            if attempt + 1 == self.max_attempts:
                break
            delay = int(response.headers.get("Retry-After", 2 ** attempt))
            time.sleep(min(delay, 30))
        if not 200 <= response.status_code < 300:
            raise GraphMailError(
                f"Graph {method} {url} failed ({response.status_code}): {response.text[:500]}"
            )
        return response


def _recipients(addresses: Iterable[str]) -> list[dict]:
    return [
        {"emailAddress": {"address": address.strip()}}
        for address in addresses
        if address.strip()
    ]


def _attach(client: GraphClient, sender: str, message_id: str, path: Path) -> None:
    messages = f"{GRAPH_ROOT}/users/{quote(sender)}/messages/{message_id}"
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    size = path.stat().st_size
    if size < DIRECT_ATTACHMENT_LIMIT:
        client.request(
            "POST",
            f"{messages}/attachments",
            json={
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": path.name,
                "contentType": mime,
                "contentBytes": base64.b64encode(path.read_bytes()).decode("ascii"),
            },
        )
        return

    session = client.request(
        "POST",
        f"{messages}/attachments/createUploadSession",
        json={"AttachmentItem": {"attachmentType": "file", "name": path.name, "size": size}},
    ).json()
    upload_url = session["uploadUrl"]
    with path.open("rb") as handle:
        start = 0
        while chunk := handle.read(UPLOAD_CHUNK_SIZE):
            end = start + len(chunk) - 1
            # The pre-authorised upload URL must not receive the Graph bearer token.
            response = client.session.request(
                "PUT",
                upload_url,
                headers={
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {start}-{end}/{size}",
                },
                data=chunk,
            )
            if response.status_code not in {200, 201, 202}:
                raise GraphMailError(
                    f"Attachment upload failed ({response.status_code}): {response.text[:500]}"
                )
            start = end + 1


def send_report_bundle(
    *,
    sender: str,
    recipients: Iterable[str],
    subject: str,
    html_body: str,
    attachments: Iterable[Path],
    access_token: str,
    session=None,
) -> str:
    """Create a draft, attach each PDF safely, send it, and return its draft id."""
    client = GraphClient(access_token, session=session)
    draft = client.request(
        "POST",
        f"{GRAPH_ROOT}/users/{quote(sender)}/messages",
        json={
            "subject": subject,
            "body": {"contentType": "HTML", "content": html_body},
            "toRecipients": _recipients(recipients),
        },
    ).json()
    message_id = draft["id"]
    for attachment in attachments:
        _attach(client, sender, message_id, Path(attachment))
    client.request("POST", f"{GRAPH_ROOT}/users/{quote(sender)}/messages/{message_id}/send")
    return message_id


def send_from_manifest(manifest_path: Path) -> str:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    fixture = manifest["fixture"]
    sender = os.environ["MAIL_SENDER"]
    recipients = [value for value in os.environ["MAIL_RECIPIENT"].replace(";", ",").split(",") if value]
    token = os.environ["GRAPH_ACCESS_TOKEN"]
    score = f"{fixture['home_goals']}-{fixture['away_goals']}"
    subject = (
        f"Post-match reports | {fixture['home_team']} {score} "
        f"{fixture['away_team']} | {fixture['kickoff_utc'][:10]}"
    )
    body = (
        f"<p>Attached are the post-match reports for "
        f"<strong>{fixture['home_team']} {score} {fixture['away_team']}</strong>.</p>"
        "<ul><li>Expanded analyst report</li><li>Board report</li>"
        "<li>Set-piece report</li></ul>"
    )
    attachments = [Path(item["path"]) for item in manifest["reports"]]
    return send_report_bundle(
        sender=sender,
        recipients=recipients,
        subject=subject,
        html_body=body,
        attachments=attachments,
        access_token=token,
    )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Email a generated report manifest")
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    message_id = send_from_manifest(args.manifest)
    print(message_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
