import logging

from app.utils.logging import RedactingFilter


def _rec(msg, *args):
    return logging.LogRecord("t", logging.INFO, __file__, 1, msg, args, None)


def test_secrets_and_patterns_are_redacted():
    token = "123456789:AAH_fakeTokenValue_abcdefghijklmnopqrstuv"
    f = RedactingFilter(["supersecretpw", token])
    cases = [
        f"password is supersecretpw",
        f"url https://api.telegram.org/bot{token}/getMe",
        "mongodb://ria_admin:hunter22@127.0.0.1:27018/?authSource=admin",
        "Authorization: Bearer abcdefghijklmnop12345",
        "key sk-or-v1-abcdefghijklmnopqrstuvwxyz",
    ]
    for c in cases:
        r = _rec(c)
        f.filter(r)
        out = r.getMessage()
        for leak in ("supersecretpw", token, "hunter22", "abcdefghijklmnop12345", "abcdefghijklmnopqrstuvwxyz"):
            assert leak not in out, (c, out)


def test_args_formatting_is_redacted():
    f = RedactingFilter(["topsecret1"])
    r = _rec("value=%s", "topsecret1")
    f.filter(r)
    assert "topsecret1" not in r.getMessage()
