# BLOCKER — Task 8: LumiBot cannot be installed into the shared runtime

**Status:** RESOLVED 2026-08-28 — LumiBot dropped; the runtime uses alpaca-py directly.
See the resolution at the end of this document. The measurement below is retained because it
is the evidence the decision rests on.
**Raised by:** dependency resolution + `pip-audit`, per Task 8 Step 5 ("Any vulnerability must
be triaged and resolved or documented as a blocker before continuing; do not suppress it
silently").
**Impact:** Task 8 only. Task 9 is unaffected and proceeds — its adapter takes an injected
`client_factory` and its tests use a fake client with no network and no credentials.

## What was done
- Tooling installed into the Archives env per Step 1: pip-tools 7.6.1, pip-audit 2.10.1,
  bandit 1.9.4. `pip check` clean; full suite still 880 passed.
- `requirements-trading.in` written and compiled to `requirements-trading.txt` with real
  resolved versions (no guessing): **lumibot==4.5.86**, alpaca-py==0.44.0, pandas==2.3.3,
  numpy==2.4.6 — 310 pins.
- **The install itself was NOT run.** Impact was measured first.

## Why it is blocked

### 1. It would rewrite the application stack (19 existing packages)
    numpy      1.26.3 -> 2.4.6     (breaking major)
    fastapi    0.109.0 -> 0.141.1
    pydantic   2.5.3  -> 2.12.5
    starlette  0.35.1 -> 0.52.1
    pandas     2.1.4  -> 2.3.3     scipy 1.12.0 -> 1.17.1
and DOWNGRADES, including the CA bundle:
    certifi    2026.7.22 -> 2025.11.12
    websockets 17.0.1 -> 15.0.1    click 8.4.2 -> 8.1.8    jiter 0.16.0 -> 0.14.0

### 2. 25 known vulnerabilities
aiohttp (5), chromadb (4, incl. CVE-2026-45830/45831/45833), starlette (7), litellm (3),
langgraph, json-repair, click, setuptools.

### 3. It drags an entire LLM stack into a trading dependency
`chromadb`, `langgraph`, `litellm`, `openai`, `tiktoken`. This sits badly against the standing
constraint that research/LLM components may propose only and must never hold credentials,
authorize, submit, cancel, or bypass risk.

### 4. The only coexisting version is unusably old
Compiling against the current stack as constraints resolves to **lumibot==1.5.5** (97 pins,
zero disruption) — but it carries `urllib3==1.24.3` with 9 CVEs including PYSEC-2020-148, and
is three major versions behind the Alpaca broker surface Task 9 is meant to wrap.

## Options recorded (user chose to defer)
1. **DEFER (chosen)** — keep the pinned resolution as evidence, skip the install, proceed to
   Task 9. Revisit when a real broker client is genuinely required (Task 16, credential gate).
2. Replace LumiBot with `alpaca-py` for the adapter — far lighter, no LLM stack, no numpy 2
   upgrade; needs a design-doc amendment since LumiBot is the recorded "selected foundation".
3. Install 4.5.86 anyway and absorb the breakage and CVEs.
4. Pin 1.5.5 and absorb the urllib3 CVEs.

## To resume
`tests/test_lumibot_runtime.py` uses `pytest.importorskip("lumibot")`, so all five checks
(import, no network I/O on import, no credentials required, pins present, README version
recorded) activate automatically once the dependency decision is made and LumiBot is installed.

## Unrelated environment finding
The Mac internal disk is FULL: 189Gi used of 228Gi, 167Mi free at the time of this work, which
caused two resolver runs to die with `OSError: [Errno 28] No space left on device`. 553MB of pip
cache was purged (freeing to ~699Mi) and pip cache/tmp were redirected to
`/Volumes/Archives/Hermes-Offload/2026-08-24/pip-workspace`. The underlying disk pressure is a
pre-existing system condition and remains unresolved.

---

# RESOLUTION — 2026-08-28: LumiBot dropped, alpaca-py adopted

User decision after reviewing the measurement above: **drop LumiBot, use alpaca-py directly.**

The deciding argument was that LumiBot's purpose — "the common strategy and broker-abstraction
layer" — is already served by code this project owns and has independently reviewed
(domain contracts, deterministic risk gate, append-only ledger, execution service, broker
protocol). LumiBot would have been a second abstraction beneath a closed one. Confirmed by
inspection: **no task after Task 9 references LumiBot at all**, and the Alpaca adapter was written
against an injected client factory, so it already worked with LumiBot absent.

## Outcome, measured

                      LumiBot 4.5.86        alpaca-py 0.44.0
    pins              310                   19
    new packages      256                   5
    existing changed  19                    0
    certifi           DOWNGRADED            unchanged
    numpy             1.26.3 -> 2.4.6       unchanged
    known vulns       25                    0
    LLM stack pulled  chromadb, langgraph,  none
                      litellm, openai

`pip check`: no broken requirements. `pip-audit`: **No known vulnerabilities found.**
Full suite unchanged at 948 passed.

## How the zero-disruption result is held
The trading pins are compiled against `requirements.txt` (the app's pinned stack) plus
`constraints-runtime.txt` (transitive versions the app relies on that requirements.txt does not
pin directly — notably certifi, the CA trust bundle). Without those constraints the resolver
opportunistically upgraded six packages it did not actually require, including the breaking
numpy 1 -> 2 jump. `tests/test_trading_runtime.py` asserts the invariant directly, so a future
bump cannot silently move an app-pinned version.

## Robinhood was considered and rejected as an alternative venue
Robinhood's official Agentic Trading MCP has **no paper or sandbox environment**, so every order
would be real money in a paper-only system. It is additionally not a member of the `Venue` enum,
so the deterministic risk gate would reject any proposal naming it, and the design already lists
the connector as disabled precisely because it exposes real-money actions. Read-only holdings
mirroring remains on the deferred roadmap as a separate, non-executing track.

## Status of the original blocker
CLOSED. Task 8's deliverables are satisfied by the alpaca-py tree: pinned, installed, `pip check`
clean, audited with zero vulnerabilities, and covered by tests/test_trading_runtime.py.
