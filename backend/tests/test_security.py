from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("a-secure-password")
    assert hashed != "a-secure-password"
    assert verify_password("a-secure-password", hashed)
    assert not verify_password("wrong-password", hashed)


def test_access_token_roundtrip() -> None:
    token = create_access_token("f1634434-1285-4c66-bf57-e8b77394c77c")
    assert decode_access_token(token) == "f1634434-1285-4c66-bf57-e8b77394c77c"
    assert decode_access_token(f"{token}tampered") is None
