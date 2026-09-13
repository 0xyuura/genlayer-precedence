# Precedence design

## Claim

Validators never disagree about which registered work a new submission
duplicates or derives from, and a model never decides anything that the
deterministic sweep did not first put in front of it.

## Constants and why

| Constant | Value | Reason |
| --- | --- | --- |
| `MAX_BODY_BYTES` | 16,384 | Bounds fetch, normalisation and prompt size. Checked before hashing, so appended bytes can never go unjudged |
| `SHINGLE_WORDS` | 5 | Long enough that shared vocabulary on one topic does not look like copying, short enough that light rewording still leaves overlap |
| `MIN_SHINGLES` | 20 | Below this, ratios swing on a handful of words |
| `DUPLICATE_JACCARD_BP` | 8,000 | The renamed copy fixture scores 8,914; unrelated writing scores 0 |
| `BAND_CONTAINMENT_BP` | 2,000 | Containment, not Jaccard, so lifting two sections from a long work still counts. The derivative fixture scores 4,556 |
| `MAX_BAND` | 2 | Bounds model calls to two per registration; a larger band is refused, never trimmed |
| `MAX_WORKS` | 32 | Keeps a full sweep inside one call; a full corpus refuses |

All ratios are integer basis points with floor division. There is no floating
point anywhere a validator compares.

## Result shape

`digest`, `refused`, `verdict`, `target`, `bits`, `text`. Every field is either
a pure function of the fetched bytes and the stored corpus, or one of the
model's bits. `text` is present only when the work will be stored, so the
agreed result is exactly what storage receives.

## Refusals

| Code | When | Model called |
| --- | --- | --- |
| `BODY_TOO_LARGE` | body over the limit, before hashing | no |
| `HTTP_STATUS` | status outside 2xx | no |
| `DIGEST_MISMATCH` | sha256 of the whole body differs from the promise | no |
| `TOO_SHORT` | fewer than 20 shingles | no |
| `AMBIGUOUS_OVERFLOW` | more than two band candidates | no |
| `ADDRESSED_THE_JUDGE` | any candidate call answers `addressed` yes | yes |
| `SHA256_SHAPE`, `URL_SCHEME`, `CORPUS_FULL` | input checks, raised before the nondeterministic block | no |

## Model contract

One call per band candidate, in registration order. The reply must be a JSON
object with `addressed`, `same` and `uncredited`, each exactly `YES` or `NO`
after trimming and upper casing. Anything else raises, which fails that
validator's execution rather than being guessed at.

## Rejected alternatives

- **MinHash or embeddings.** Both estimate similarity. An estimate invites the
  question of which near threshold pair it misjudged, and two validators could
  estimate differently. Exact sets over a bounded corpus answer that question
  with arithmetic.
- **Top k band.** Cheaper, but a duplicate of candidate k plus one would never
  be examined. Refusing an overflowing band keeps the guarantee.
- **Separate calls per question.** Tried on chain first and hit
  `LEADER_TIMEOUT`. One call with three fields keeps the same bits and fits the
  leader budget.
