"""Synthetic Apple/Google OAuth provider for the disposable E2E network only."""

from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

PORT = int(os.environ.get("PORT", "8081"))
APPLE_ISSUER = "https://appleid.apple.com"
GOOGLE_ISSUER = "https://accounts.google.com"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
KEY_ID = "synthetic-e2e-key"
CODES: dict[str, dict[str, str]] = {}
AUTHORIZATION_COUNTS = {"apple": 0, "google": 0}
PROFILES = {
    "google": [
        ("synthetic-google-user", "google.synthetic@e2e.mykhaya.dev"),
        ("synthetic-google-user", "google.synthetic@e2e.mykhaya.dev"),
        ("synthetic-beta-google-user", "beta.google@e2e.mykhaya.dev"),
    ],
    "apple": [
        ("synthetic-apple-user", "apple.synthetic@privaterelay.appleid.com"),
        ("synthetic-apple-user", "apple.synthetic@privaterelay.appleid.com"),
        ("synthetic-beta-apple-user", "beta.apple@e2e.mykhaya.dev"),
    ],
}


def b64(value: int) -> str:
    return base64.urlsafe_b64encode(value.to_bytes((value.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()


numbers = KEY.public_key().public_numbers()
JWKS = {"keys": [{"kty": "RSA", "kid": KEY_ID, "use": "sig", "alg": "RS256", "n": b64(numbers.n), "e": b64(numbers.e)}]}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        return

    def send_json(self, payload: dict[str, object], status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path)
        if path.path.endswith("/jwks") or path.path.endswith("/certs"):
            if self.headers.get("Host") != "oauth-provider:8081":
                self.send_json({"error": "internal_only"}, 404)
                return
            self.send_json(JWKS)
            return
        if path.path.endswith("/authorize"):
            query = parse_qs(path.query)
            provider = "apple" if "/apple/" in path.path else "google"
            profile_index = min(AUTHORIZATION_COUNTS[provider], len(PROFILES[provider]) - 1)
            subject, email = PROFILES[provider][profile_index]
            AUTHORIZATION_COUNTS[provider] += 1
            code = secrets.token_urlsafe(24)
            CODES[code] = {key: values[0] for key, values in query.items()}
            CODES[code]["provider"] = provider
            CODES[code]["subject"] = subject
            CODES[code]["email"] = email
            redirect_uri = CODES[code].get("redirect_uri")
            state = CODES[code].get("state")
            if not redirect_uri or not state:
                self.send_json({"error": "invalid_request"}, 400)
                return
            target = f"{redirect_uri}?{urlencode({'code': code, 'state': state})}"
            if query.get("response_mode", [""])[0] == "form_post":
                fields = "".join(
                    f'<input type="hidden" name="{html.escape(name)}" '
                    f'value="{html.escape(value)}">'
                    for name, value in (("code", code), ("state", state))
                )
                body = (
                    "<!doctype html><html><body>"
                    f'<form method="post" action="{html.escape(redirect_uri)}">{fields}</form>'
                    "<script>document.forms[0].submit()</script></body></html>"
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(302)
            self.send_header("Location", target)
            self.end_headers()
            return
        self.send_json({"status": "ok"})

    def do_POST(self) -> None:  # noqa: N802
        if self.headers.get("Host") != "oauth-provider:8081":
            self.send_json({"error": "internal_only"}, 404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        form = parse_qs(self.rfile.read(length).decode())
        code = form.get("code", [""])[0]
        data = CODES.pop(code, None)
        if data is None:
            self.send_json({"error": "invalid_grant"}, 400)
            return
        client_id = form.get("client_id", [""])[0]
        redirect_uri = form.get("redirect_uri", [""])[0]
        if client_id != data.get("client_id") or redirect_uri != data.get("redirect_uri"):
            self.send_json({"error": "invalid_grant"}, 400)
            return
        provider = data["provider"]
        if provider == "google":
            verifier = form.get("code_verifier", [""])[0]
            challenge = base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode("ascii")).digest()
            ).rstrip(b"=").decode("ascii")
            if not verifier or challenge != data.get("code_challenge"):
                self.send_json({"error": "invalid_grant"}, 400)
                return
        issuer = APPLE_ISSUER if provider == "apple" else GOOGLE_ISSUER
        claims: dict[str, object] = {
            "iss": issuer,
            "aud": data.get("client_id", "synthetic-client"),
            "sub": data.get("subject", f"synthetic-{provider}-user"),
            "nonce": data.get("nonce", ""),
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            "email": data.get("email", f"{provider}.synthetic@e2e.mykhaya.dev"),
            "email_verified": True,
        }
        if provider == "apple":
            claims["is_private_email"] = str(claims["email"]).endswith("@privaterelay.test")
        token = jwt.encode(claims, KEY, algorithm="RS256", headers={"kid": KEY_ID})
        self.send_json({"access_token": "synthetic-access-token", "id_token": token, "token_type": "Bearer"})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
