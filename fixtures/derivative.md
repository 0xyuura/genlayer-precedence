# Deduplicating notification emails from an event stream

Our notification service consumes order events and sends one email per state
change. The stream guarantees at least once delivery, so the same event can
arrive several times after a consumer restart, and customers noticed the
duplicate emails long before our dashboards did.

We needed a guard that works without a distributed lock, because the email
provider sometimes takes seconds to answer and a lock held that long stalled
the whole consumer group.

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

## Applying it to email

Email providers accept an idempotency header, so the replay path is safe as long
as the header is the event identifier and not a fresh request id. We learned
that the hard way when a retry library generated its own id per attempt.

Templates are rendered before the insert, so a replay sends exactly the message
the customer would have received the first time, even if the template changed
in between. After two weeks in production the duplicate email rate fell from
roughly one in four hundred messages to none that we could find.
