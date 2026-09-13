# Precedence

**A registry that decides whether new work duplicates, derives from, or is
independent of what was registered first, and agrees on it by consensus.**

Live on Testnet Bradbury at
[`0xE490824F37cBBD328F4a849E940Ec32D7203AF35`](https://explorer-bradbury.genlayer.com/address/0xE490824F37cBBD328F4a849E940Ec32D7203AF35),
deployed from `contracts/precedence.py` at commit `761013f`. The code stored on
chain is byte identical to that file (sha256 `ed882188076a98d6...`).

Call it without a local setup: [open it in GenLayer Studio](https://studio.genlayer.com/?import-contract=0xE490824F37cBBD328F4a849E940Ec32D7203AF35)

## The problem

Every program that pays for submissions eventually pays twice for the same
work. A hackathon receives last year's winner under a new title. A grant
program receives a write up that lifts half of someone else's post. A bounty
board receives the same fix from two accounts. The GenLayer Portal alone has
taken in more than twenty thousand contributions, and every reviewer there is,
among other things, a duplicate detector.

The question "was this already submitted?" has a deterministic half and a
judgement half. Byte equality and heavy textual overlap are facts anyone can
compute. Whether a partial overlap is an uncredited copy or a legitimate
continuation is a judgement. Precedence keeps the two halves apart, and it
never lets the judgement half widen what the deterministic half decided.

## How it works

There is one write method, `register(url, sha256)`.

1. **Content addressed fetch.** Validators fetch the URL. A body over 16,384
   bytes is refused as `BODY_TOO_LARGE` before it is hashed. A non 2xx status is
   `HTTP_STATUS`. The sha256 of the whole body must equal the promised one, or
   the result is `DIGEST_MISMATCH`.
2. **Deterministic normalisation.** Lowercase, keep letters and digits, collapse
   everything else to single spaces, then take every five word window as a
   shingle. Fewer than 20 shingles is `TOO_SHORT`.
3. **A sweep over the whole corpus.** Against every registered work, in
   registration order, with integer basis points and no floating point:
   - equal sha256, or Jaccard at or above 8,000 bp, is `DUPLICATE` of the
     earliest such work, decided with no model call;
   - containment at or above 2,000 bp (the share of the new work's shingles
     already present in the old one) puts that work in the **ambiguous band**;
   - everything else is independent of it.
4. **The band is judged in full or not at all.** More than two candidates is
   `AMBIGUOUS_OVERFLOW`, a refusal. Otherwise each candidate gets exactly one
   model call that returns three strict one bit fields: `addressed` (the new
   work talks to the evaluator), `same` (the same work with cosmetic changes),
   `uncredited` (substantial reuse without credit).
5. **The verdict is a function of the bits.** Any `addressed` refuses the
   registration as `ADDRESSED_THE_JUDGE`. Otherwise the first candidate with
   `same` makes it `DUPLICATE`, else the first with `uncredited` makes it
   `DERIVATIVE`, else `INDEPENDENT`.

`INDEPENDENT` and `DERIVATIVE` works are stored with their normalised text and
become part of the corpus. `DUPLICATE` and every refusal store only a ruling.
Every call, stored or not, leaves a ruling with its verdict, target, bits and
refusal reason.

## Why the consensus is sound

Validators run the same leader function and compare the whole result
(`digest`, `refused`, `verdict`, `target`, `bits`, `text`) by exact equality.
There is no tolerance, no similarity between answers, and no sampling.

- **Nothing is sampled.** The sweep compares the new work with every registered
  work. The corpus is capped at 32 so the sweep stays affordable, and a full
  corpus refuses new registrations rather than skipping comparisons. A test
  plants the duplicate at position 30 of 30, and a mutation that sweeps only the
  first ten works fails the suite.
- **The band is never truncated.** Two candidates are judged, or the call is
  refused. There is no "top k" that a duplicate of the third candidate could
  slip past.
- **The deterministic half is recomputed, not trusted.** A leader that claims a
  different digest, a different band, or different stored text disagrees with
  every honest validator, because those fields are pure functions of the bytes
  that match the promised hash.
- **Agreement fixes the storage decision.** `stores_work` depends only on
  agreed fields. A test walks every agreed result shape and checks that two
  agreeing results can never store different outcomes.
- **The model cannot widen a decision.** It is never asked about a work outside
  the band, it cannot name a target that is not a band candidate, and its only
  outputs are bits.

## Containment

The registrant writes the evidence, so the evidence is hostile by default.

- **Prompt injection** is a correlated fault: text that steers the leader steers
  every validator the same way. The prompt fences both documents with a tag
  derived from the sha256 of both texts, so a document cannot contain its own
  fence, and the guard still refuses if one ever did. Text aimed at the
  evaluator is itself a question the model answers (`addressed`), and a yes
  refuses the registration instead of scoring it.
- **Near copies never reach the model.** A renamed copy scores well above the
  duplicate threshold and is decided by arithmetic, so injected text inside it
  has nothing to steer.
- **Refusal is the cheap failure.** A wrongly refused registrant can register a
  clean document again. A wrongly accepted duplicate would take precedence away
  from the real author, so every uncertain path refuses.

## Honest limitations

1. **Paraphrase below the band is invisible.** A copy reworded so thoroughly
   that under 20% of its shingles survive is never sent to the model. The claim
   is scoped to reuse that leaves lexical evidence.
2. **Lexical, not semantic.** Two independent works on the same narrow topic can
   share phrasing and land in the band; the model then decides, and a false
   `DERIVATIVE` is possible.
3. **Precedence means first registered, not first written.** The contract
   cannot know who wrote something first off chain.
4. **Small documents only.** 16 KB bodies and a 32 work corpus keep one call
   affordable. A production registry would shard the corpus.
5. **The model can be wrong inside the band.** Consensus makes validators agree
   on its answer; it does not make the answer true. The asymmetry above is what
   limits the damage.

## Tests

```bash
python -m unittest discover -s tests     # 40 tests, offline, no model
genvm-lint check contracts/precedence.py
```

Everything that votes is a module level function, so all of it runs under
plain CPython with a stubbed SDK. The suite pins the normaliser, the integer
similarity arithmetic and its boundaries, the full corpus sweep, every refusal
(including size refused before any hashing, proven with a `hashlib` spy), the
single model call per candidate, an exhaustive truth table of verdicts over
every bit string for one and two candidates, and the exact agreement rule.

Two deliberate mutations were run against the suite before deploying: sampling
the first ten works of the corpus, and hashing before the size check. Both
fail it.

## Exercised on chain

Against `0xE490824F37cBBD328F4a849E940Ec32D7203AF35`, each fixture registered from
a raw URL pinned to commit `835b8af`, in this order.

| Ruling | Fixture | Result | Transaction |
| --- | --- | --- | --- |
| `r1` | `original.md`, first registration | `INDEPENDENT`, stored as `w1`, no model call | `0xbdbd030c...` |
| `r2` | `copy-renamed.md`, new title and three words changed | `DUPLICATE` of `w1`, Jaccard 8,914 bp, not stored, no model call | `0x2ec8e1b1...` |
| `r3` | `derivative.md`, two sections lifted without credit | band (containment 4,556 bp), one model call, bits `01`: `DERIVATIVE` of `w1`, stored as `w2` | `0x141fe74c...` |
| `r4` | `independent.md`, unrelated topic | `INDEPENDENT`, stored as `w3`, no model call | `0x9fc78d2c...` |
| `r5` | `original.md` promised with a wrong sha256 | `DIGEST_MISMATCH`, nothing stored | `0x5cfd611f...` |

Every one reached `AGREE / FINISHED_WITH_RETURN`. Read them back with:

```bash
genlayer call 0xE490824F37cBBD328F4a849E940Ec32D7203AF35 counts
genlayer call 0xE490824F37cBBD328F4a849E940Ec32D7203AF35 get_ruling --args r3
```

**What the chain taught.** The first deployment,
`0x64B77C7FAB96EB85C26bF3f6f91b058F6e8114f6`, asked the band three separate
questions: a screen call and one call per bit. The derivative registration
there ended in `LEADER_TIMEOUT` after four rounds, even though the leader's
output in the receipt already carried the right bits. The work fitted, the time
budget did not. Folding the three questions into one call with three strict
fields fixed it without touching agreement. Two smaller notes: Bradbury drops
any transaction declaring more than 16,777,216 gas, so this contract is kept
near 12 KB; and the CLI parses an all digit argument as a number, so an all zero
test digest arrives as `0` and is refused as `SHA256_SHAPE`.

## Layout

```
contracts/precedence.py   the contract, and every rule that votes
tests/test_precedence.py  the suite
tests/_stub.py            a minimal genlayer SDK stub for CPython
fixtures/                 original, renamed copy, derivative, independent
docs/DESIGN.md            thresholds, refusals, and why each exists
```

## Licence

MIT, see [LICENSE](LICENSE).
