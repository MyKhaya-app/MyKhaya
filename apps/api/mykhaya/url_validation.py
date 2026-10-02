from urllib.parse import urlsplit


# The one http(s)-URL-shape check in the codebase — used both by Settings'
# own startup validation of deployment URLs (admin_url/status_url/etc., see
# config.py's validate_admin_and_status_url_configuration) and by
# platform_settings.py's validation of administrator-typed URLs (e.g.
# service_status_url). Deliberately just the shape check; anything specific
# to one caller (e.g. rejecting embedded credentials on admin-typed input)
# stays in that caller rather than being folded in here.
def is_valid_http_url(value: str) -> bool:
    parts = urlsplit(value)
    return parts.scheme in ("http", "https") and bool(parts.hostname)
