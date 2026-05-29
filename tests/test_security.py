from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    make_opaque_token,
    verify_password,
)


def test_access_token_round_trip_contains_labby_claims() -> None:
    token = create_access_token(
        user_id="11111111-1111-1111-1111-111111111111",
        tenant_id="22222222-2222-2222-2222-222222222222",
        membership_id="33333333-3333-3333-3333-333333333333",
        role="owner",
        modules=["sales", "social_media"],
        jti="jti-1",
    )

    payload = decode_access_token(token)

    assert payload is not None
    assert payload["type"] == "labby_access"
    assert payload["membership_id"] == "33333333-3333-3333-3333-333333333333"
    assert payload["modules"] == ["sales", "social_media"]


def test_opaque_tokens_are_unique() -> None:
    assert make_opaque_token() != make_opaque_token()


def test_password_hash_round_trip_handles_long_passwords() -> None:
    password = "a" * 128

    password_hash = hash_password(password)

    assert verify_password(password, password_hash)
    assert not verify_password("wrong", password_hash)
