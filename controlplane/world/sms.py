"""SMS simulator. Messages are `message` spans; no real SMS is sent or received."""

from __future__ import annotations

from typing import Optional

from agentreplay.guard import emit_span


class SmsGateway:
    def receive(self, sender: str, body: str) -> Optional[str]:
        return emit_span(
            "message",
            "sms.inbound",
            {"from": sender},
            {"direction": "inbound", "body": body, "simulated": True},
        )

    def send(self, recipient: str, body: str) -> Optional[str]:
        return emit_span(
            "message",
            "sms.outbound",
            {"to": recipient},
            {"direction": "outbound", "body": body, "simulated": True},
        )
