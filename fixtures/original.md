# Idempotent webhook receivers without a database lock

Payment providers retry a webhook until they see a success status, and they
retry aggressively when a response is slow. A receiver that does real work on
every delivery will eventually charge a customer twice, ship an order twice, or
credit a balance twice. The usual advice is to take a row lock on the event
identifier, but a lock held across a network call turns a slow downstream
service into a queue of blocked workers.

The approach described here avoids the lock entirely. It relies on two facts
that hold for every major provider we checked: each event carries a stable
identifier, and the provider treats any status in the two hundred range as final.

## Record the intent before the effect

When a delivery arrives, the receiver first inserts a row keyed by the event
identifier with a status of pending and a hash of the payload. The insert uses
a unique constraint, so a second concurrent delivery fails fast instead of
waiting. The failing worker answers with a success status immediately, because
the first worker now owns the event.

Only after the insert commits does the receiver perform the side effect. When
the effect completes it updates the row to done and stores the provider response.

## Recover the stragglers

A worker can crash between the insert and the effect. A periodic sweep looks
for rows that have stayed pending for longer than the provider retry window and
replays the effect using the stored payload. Because the effect itself is keyed
by the event identifier on the downstream side, a replay after a partial success
cannot double the result.

## What this does not solve

The pattern assumes the downstream service accepts an idempotency key. When it
does not, the receiver must keep its own ledger of completed effects and check
it before every replay, which brings back a read before write and the race it
invites. It also assumes the payload hash is stable; a provider that reorders
JSON keys between retries will look like a different event unless the hash is
taken over a canonical form.

Measured on a queue of forty thousand replayed deliveries, the receiver produced
zero duplicate effects and held no lock for longer than a single insert.
