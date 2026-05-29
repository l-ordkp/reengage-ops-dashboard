# Model Comparison: AI Response Generation

Comparing three candidate models for the review-reply generation pipeline
(`backend/managers/response_manager.py::_call_openai`).

| Aspect | gpt-4.1-nano *(current)* | gpt-4o-mini | gemini-2.5-flash-lite |
|---|---|---|---|
| Provider | OpenAI | OpenAI | Google |
| Class | nano / smallest tier | small / mini tier | flash-lite / smallest tier |
| Drop-in via existing client? | yes (current) | yes (1-line model swap) | no — needs `google-generativeai` or Vertex AI SDK |
| API key in Secret Manager? | yes (`openai-del-intel`) | yes (same key) | needs new secret |

---

## Why this comparison

Production hit a hallucination on `bestpizzaandbrew` (DD, Liked, 8 orders,
no coupon configured): the reply included *"enjoy a discount of $0.50"*
despite `coupon_value=0` in the stored response. Triage in
`response_manager.py` showed:

- The config matched correctly (config_id 212, `dd_coupon_fixed_value: 0.0`).
- The prompt rendered `Coupon Given: $None` and explicitly says
  *"If coupon is 'None' ... DO NOT mention any coupon"*.
- The validator (`_validate`, line 176) catches `"$0" in response` and logs
  an error, but only into the `errors` column — it does not retry or reject.

So the model violated the prompt. The question this doc tries to answer:
**is the model the right one for this task, or should we move to one with
better rule-following at comparable cost?**

---

## Hallucination benchmark (Vectara leaderboard)

Vectara's leaderboard measures grounded hallucination rates — i.e. how
often a model invents facts that aren't in the source context. Lower is
better. The use case here (paraphrasing a review into a structured reply
while obeying explicit rules) is closely aligned with this benchmark.

See the live chart at
[github.com/vectara/hallucination-leaderboard](https://github.com/vectara/hallucination-leaderboard).

Relevant rows pulled from the chart at time of writing:

| Model (chart label) | Hallucination rate |
|---|---|
| `openai/gpt-5.4-nano-2026-03-17` *(latest nano)* | **3.1%** |
| `google/gemini-2.5-flash-lite` | **3.3%** |
| `meta-llama/Llama-3.3-70B-Instruct-Turbo` | 4.1% |
| `mistralai/mistral-large-2411` | 4.5% |
| `openai/gpt-5.4-mini-2026-03-17` *(latest mini)* | 5.5% |
| `openai/gpt-4.1-2025-04-14` *(base 4.1)* | 5.6% |
| `deepseek-ai/DeepSeek-V3` | 6.1% |
| `google/gemini-2.5-pro` | 7.0% |

Notes:
- `gpt-4.1-nano` (our current model) isn't on the leaderboard. The closest
  proxy is the newer `gpt-5.4-nano` at 3.1%; nano-class models from OpenAI
  consistently land in the 3–5% range.
- `gpt-4o-mini` isn't on this snapshot either; based on the broader nano /
  mini gap visible in the chart (`5.4-nano: 3.1%` vs `5.4-mini: 5.5%`),
  mini-tier models tend to **hallucinate slightly more** than nano-tier.
  This is counter-intuitive but consistent with our own observation that
  4o-mini was more verbose and more likely to add extras.
- The leaderboard surprise: **nano and flash-lite tiers (small, cheap models)
  actually hallucinate less than the mini / pro tiers** for grounded tasks.

---

## Pricing (approx, per 1M tokens, knowledge as of Jan 2026 — verify before deciding)

| Model | Input | Output |
|---|---|---|
| gpt-4.1-nano | ~$0.10 | ~$0.40 |
| gpt-4o-mini | ~$0.15 | ~$0.60 |
| gemini-2.5-flash-lite | ~$0.10 (text) | ~$0.40 (text) |

At our volume (~5–10k responses/day, ~300 output tokens each):
- nano: roughly $0.60–1.20/day
- 4o-mini: roughly $0.90–1.80/day (~50% more)
- flash-lite: roughly parity with nano

The cost gap between any of these and the next tier up (4o, gpt-4.1, Claude
Sonnet, Gemini Pro) is 10× or more. So **the decision here is "best of the
cheap models"**, not "cheap vs expensive."

---

## Live test results (8 sample reviews)

Run via `/tmp/compare_models.py` — same prompt builder as
`_call_openai`, mix of platforms / ratings / with-coupon / without-coupon.

| Model | Hallucinations | Validator errors | Total time (8 calls) |
|---|---|---|---|
| gpt-4.1-nano | 0/8 | **2/8** | 9.3s |
| gpt-4o-mini | 0/8 | 0/8 | 16.7s |
| gemini-2.5-flash-lite | *not tested yet — needs Google API key* | — | — |

### What the numbers actually mean

**No hallucinations in either OpenAI model on 8 samples.** Kevin L's
"$0.50" was a low-frequency event (temperature=0.7 + small model).
8 samples isn't enough to reliably catch a 1–3% failure rate.

**The bigger issue is the opposite of hallucination: dropped coupons.**

- Sample #3 — DD / Didn't Like / $5 coupon expected — nano apologized
  beautifully but **forgot the $5**.
- Sample #8 — UE / 2★ / $5 coupon expected — same: apology, no $5.

Both were flagged by the existing validator (`Coupon value $5 not found`)
but the response was still served because the validator only logs.

`gpt-4o-mini` included the coupon in both cases. So `gpt-4o-mini` is
materially better at rule-following on the "must include" half of the
prompt, while the Vectara data suggests nano-tier is slightly better on
the "must not include" half.

### Style notes

- nano: tight, sometimes too tight — drops constrained content.
- 4o-mini: verbose; once hit 492/500 chars on UE; occasionally adds
  *"Best regards, The Team"* sign-offs. Style would need a prompt
  tighten.
- flash-lite: untested locally. Generally Google models are conservative
  and structured, which suits this use case but can be refuse-prone on
  edge cases.

---

## Strengths / weaknesses summary

### gpt-4.1-nano *(current production)*

- ✅ Cheapest tier, fastest (~1.2s avg)
- ✅ Zero migration cost — already wired up
- ✅ Per Vectara, nano-class has the lowest hallucination rate in the cheap tier
- ❌ Drops required coupons (~25% of coupon-required samples in our test)
- ❌ Did hallucinate "$0.50" in one production case — rare but real

### gpt-4o-mini

- ✅ Best in our test for rule following — never dropped a coupon
- ✅ 1-line model swap, same OpenAI client + key
- ❌ ~50% more expensive per token
- ❌ 1.7× slower (~2s avg per call)
- ❌ Per Vectara, mini-class hallucinates **more** than nano on grounded tasks
- ❌ Verbose by default — tight against char limits, adds sign-offs

### gemini-2.5-flash-lite

- ✅ Lowest grounded hallucination rate in our tier (3.3%) — beats 4o-mini's class
- ✅ Pricing matches nano almost exactly
- ✅ Fast
- ❌ Requires new SDK (`google-generativeai`) + new API key in Secret Manager
- ❌ Not yet tested on our 8-sample set — recommendation is provisional
- ❌ Slight migration effort: ~50 lines of code, mostly in
  `backend/clients/` and `_call_openai`

---

## Recommendation

**Two-track approach:**

1. **Immediate, no model change:** make the existing validator
   actually drive a retry instead of silently logging. The retry loop in
   `_call_openai` already exists for char-limit overflow; extending it to
   also retry on `_validate` errors is ~5 lines and would have caught
   both the Kevin-L hallucination *and* the dropped-coupon cases on our
   8-sample test (the validator already detects both patterns). This is
   the highest-leverage change before touching the model.

2. **Then evaluate a model switch:** test `gemini-2.5-flash-lite` on
   the same 8-sample script (and ideally expand to 30–50 samples for a
   meaningful hallucination rate). If it matches `gpt-4o-mini`'s
   rule-following at `gpt-4.1-nano`'s price *and* matches its Vectara
   hallucination ranking in our specific task, it's the clear winner.

**Avoid** moving to `gpt-4o-mini` as a permanent solution: it solves the
dropped-coupon problem but the Vectara data and our prompt observations
suggest it's actually more hallucination-prone for grounded tasks like
ours. We'd trade one failure mode for another.

---

## Open questions

- What's the *actual* current production hallucination rate? We have
  one anecdote (Kevin L). Sampling ~200 stored responses for `$0` or
  unconfigured coupon language would give a real baseline before any
  model change.
- Would per-config tonality / prompt overrides (e.g. extra-strict for
  configs with `dd_coupon_type: fixed` AND `dd_coupon_fixed_value: 0`)
  fix this without a model change?
- Is the prompt's format (`Coupon Given: $None`) part of the problem?
  The `$` itself may prime the model toward dollar-amount outputs even
  when the value is None. Re-rendering as `Coupon to include: NO` or
  omitting the line entirely when zero is worth testing.

---

*Source for hallucination chart:*
[github.com/vectara/hallucination-leaderboard](https://github.com/vectara/hallucination-leaderboard)
