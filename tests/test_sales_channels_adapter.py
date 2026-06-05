from app.integrations.sales_channels import (
    _evolution_remote_jid,
    _extract_message_collection,
    _extract_outbound_external_id,
    _message_matches_outbound,
)


def test_reconciliation_helpers_find_evolution_message_by_metadata() -> None:
    payload = {
        "messages": [
            {
                "key": {"id": "other", "fromMe": True},
                "message": {"conversation": "Outro texto"},
            },
            {
                "key": {"id": "evo-1", "fromMe": True},
                "metadata": {"labby_idempotency_key": "sales.message:1:evolution:v1"},
                "message": {"conversation": "Ola"},
            },
        ]
    }

    messages = _extract_message_collection(payload)

    assert messages is not None
    match = [
        message
        for message in messages
        if _message_matches_outbound(
            message,
            idempotency_key="sales.message:1:evolution:v1",
            content="Ola",
            media_url=None,
        )
    ][0]
    assert _extract_outbound_external_id(match) == "evo-1"


def test_reconciliation_helpers_accept_evolution_list_response_and_remote_jid() -> None:
    payload = [{"key": {"id": "evo-2"}, "message": {"conversation": "Ola"}}]

    assert _extract_message_collection(payload) == payload
    assert _evolution_remote_jid("5511999990000") == "5511999990000@s.whatsapp.net"
    assert (
        _evolution_remote_jid("5511999990000@s.whatsapp.net")
        == "5511999990000@s.whatsapp.net"
    )
