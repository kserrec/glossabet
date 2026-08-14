# Payment service glossary

House register: plain, descriptive two-word compounds for domain objects and
their external boundary.

| Term | What it is | Notes |
|---|---|---|
| Payment Attempt | One request to collect an order's amount | Distinct from the gateway authorization returned for that request. |
| Gateway Client | The boundary object that submits an attempt to the payment provider | “Processor” is discouraged because it blurs the local boundary with the external provider. |
| Authorization | The gateway's approval result | The operation is `authorize_payment`; it does not imply settlement. |

## Primary decision

“Payment Attempt” names the local business event; “Authorization” names the
provider result. Keeping those terms separate prevents an approval from being
mistaken for completed money movement.

Load-bearing rule: an attempt is ours; an authorization is the gateway's
answer.
