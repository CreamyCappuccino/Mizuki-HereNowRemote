import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from here_now_remote.oauth_resource import OAuthConfig, verified_claims
from here_now_remote.site_models import HereNowError


@pytest.fixture(scope="module")
def keys():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key, key.public_key()


def token(keys, **overrides):
    now = int(time.time())
    claims = {"iss": "https://auth.example.com", "aud": "https://mcp.example.com/mcp",
        "sub": "owner", "client_id": "test", "scope": "herenow:read", "iat": now, "exp": now + 300, "jti": "one"}
    claims.update(overrides)
    return jwt.encode(claims, keys[0], algorithm="RS256", headers={"typ": "at+jwt", "kid": "test"})


def config():
    return OAuthConfig("https://auth.example.com", "https://mcp.example.com/mcp", "https://auth.example.com/jwks")


def test_correct_token(keys):
    assert verified_claims(token(keys), config(), lambda _: keys[1])["sub"] == "owner"


@pytest.mark.parametrize("overrides", [{"aud": "https://other.example/mcp"}, {"aud": ["https://mcp.example.com/mcp", "https://other.example/mcp"]},
    {"iss": "https://other.example"}, {"exp": 1}, {"scope": ""}, {"sub": ""}])
def test_wrong_resource_issuer_expiry_or_identity(keys, overrides):
    assert verified_claims(token(keys, **overrides), config(), lambda _: keys[1]) is None


def test_partial_oauth_configuration_is_an_error():
    with pytest.raises(HereNowError):
        OAuthConfig.from_env({"HERENOW_OAUTH_ISSUER": "https://auth.example.com"})
