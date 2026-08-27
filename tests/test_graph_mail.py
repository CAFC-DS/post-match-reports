import json

from post_match_reports.graph_mail import send_report_bundle


class Response:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.headers = {}

    def json(self):
        return self._payload


class Session:
    def __init__(self):
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if method == "POST" and url.endswith("/messages"):
            return Response(201, {"id": "draft-1"})
        if url.endswith("createUploadSession"):
            return Response(200, {"uploadUrl": "https://upload.example/session"})
        if url == "https://upload.example/session":
            return Response(201)
        if url.endswith("/send"):
            return Response(202)
        return Response(201, {"id": "attachment"})


def test_graph_mail_creates_draft_attaches_and_sends(tmp_path):
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"pdf")
    session = Session()

    message_id = send_report_bundle(
        sender="analytics@example.com",
        recipients=["list@example.com"],
        subject="Reports",
        html_body="<p>Ready</p>",
        attachments=[pdf],
        access_token="token",
        session=session,
    )

    assert message_id == "draft-1"
    draft = session.calls[0][2]["json"]
    assert draft["toRecipients"][0]["emailAddress"]["address"] == "list@example.com"
    assert any(url.endswith("/attachments") for _, url, _ in session.calls)
    assert session.calls[-1][1].endswith("/send")


def test_large_attachment_uses_upload_session(tmp_path):
    pdf = tmp_path / "large.pdf"
    pdf.write_bytes(b"x" * (3 * 1024 * 1024))
    session = Session()

    send_report_bundle(
        sender="analytics@example.com",
        recipients=["list@example.com"],
        subject="Reports",
        html_body="Ready",
        attachments=[pdf],
        access_token="token",
        session=session,
    )

    assert any(url.endswith("createUploadSession") for _, url, _ in session.calls)
    upload = next(call for call in session.calls if call[1] == "https://upload.example/session")
    assert upload[2]["headers"]["Content-Range"].startswith("bytes 0-")
