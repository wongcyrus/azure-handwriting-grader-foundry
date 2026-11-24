import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from handwriting_grader_cloud.auth import DevelopmentAuthenticator, EntraAuthenticator
from handwriting_grader_cloud.errors import ApplicationError

TENANT = "00000000-0000-0000-0000-000000000001"
OBJECT = "00000000-0000-0000-0000-000000000002"


@pytest.fixture
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def authenticator(signing_key):
    result = EntraAuthenticator(TENANT, "api://synthetic-test-api")
    result.keys = SimpleNamespace(
        get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=signing_key.public_key())
    )
    return result


def token(key, **changes):
    claims = {
        "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0",
        "aud": "api://synthetic-test-api",
        "tid": TENANT,
        "oid": OBJECT,
        "exp": int(time.time()) + 600,
        "scp": "Exam.Access",
        "roles": ["Teacher"],
    }
    claims.update(changes)
    return jwt.encode(claims, key, algorithm="RS256")


def test_valid_delegated_token(authenticator, signing_key):
    principal = authenticator.authenticate(token(signing_key))
    assert principal.tenant_id == TENANT
    assert principal.object_id == OBJECT
    assert principal.roles == frozenset({"Teacher"})


@pytest.mark.parametrize(
    "changes",
    [
        {"aud": "wrong-api"},
        {"iss": "https://wrong.example"},
        {"tid": "00000000-0000-0000-0000-000000000003"},
        {"oid": "not-an-object-id"},
        {"tid": 1},
        {"exp": 1},
        {"idtyp": "app"},
        {"scp": ""},
        {"scp": ["Exam.Access"]},
        {"roles": "Teacher"},
        {"roles": [1]},
    ],
)
def test_invalid_tokens_fail_closed(authenticator, signing_key, changes):
    with pytest.raises(ApplicationError) as error:
        authenticator.authenticate(token(signing_key, **changes))
    assert error.value.status == 401


def test_wrong_signature_and_missing_token(authenticator):
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    for value in (None, "invalid", token(other_key)):
        with pytest.raises(ApplicationError):
            authenticator.authenticate(value)


def test_development_authentication_requires_explicit_long_token():
    with pytest.raises(ValueError):
        DevelopmentAuthenticator("short")
    authenticator = DevelopmentAuthenticator("x" * 32)
    with pytest.raises(ApplicationError):
        authenticator.authenticate("y" * 32)
    assert authenticator.authenticate("x" * 32).roles == frozenset({"Teacher"})
