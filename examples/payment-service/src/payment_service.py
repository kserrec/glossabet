"""Minimal payment flow used by Glossarize's release walkthrough."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PaymentAttempt:
    order_id: str
    amount_cents: int


class GatewayClient:
    def authorize(self, attempt: PaymentAttempt) -> str:
        return f"authorization:{attempt.order_id}"


def authorize_payment(
    attempt: PaymentAttempt, gateway: GatewayClient
) -> str:
    return gateway.authorize(attempt)
