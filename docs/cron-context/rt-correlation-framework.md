# Rotten Tomatoes correlation framework (creative priors, non-actionable)

Updated: 2026-05-27

## Goal
Create a structured feature framework that can generate **calibrated prior probabilities** for RT threshold markets before/directly alongside live review-wave data.

This is research-only and remains non-actionable until normal gates pass (direct source freshness, cutoff/rules, independent calibration, CLOB depth/spread, sizing).

---

## 1) Feature families to test

### A) Creator-track features (historical quality priors)
- Director critic-history: median RT, p25 RT, std-dev RT
- Writer critic-history
- Producer critic-history (weighted by producer role depth)
- Studio/distributor priors by genre (A24 horror, Paramount broad comedy, etc.)

### B) Cast and collaboration graph features
- Top-billed cast weighted RT prior (lead-role weighted)
- Pairwise collaboration effect (actor A + actor B together vs apart)
- Director + lead-actor interaction term
- Franchise-return effect (legacy cast reunion uplift/drag)

### C) Genre and format priors
- Genre baseline by year window (horror, parody comedy, international black comedy)
- Sequel/reboot tax or premium
- Runtime effect by genre bucket
- Rating bucket effect (R vs PG-13 by genre)

### D) Pre-release signal velocity
- Trailer sentiment/engagement deltas
- Press-tour intensity (count + quality score)
- Festival selection / embargo pattern / early-screening signal
- Critic review velocity in first 24h/48h after embargo lift

### E) Market microstructure quality controls
- Spread and top-of-book depth penalty
- Time-to-cutoff decay
- Boundary-risk amplification (scores near threshold)

### F) Data quality and settlement confidence
- Direct-source confidence score
- Source staleness hours
- Rule precision confidence (exact threshold interpretation)

---

## 2) Model shape (recommended)

Use a two-stage approach:

1. **Prior model** (pre-review):
   - Inputs: A + B + C + part of D
   - Output: prior probability for threshold outcome

2. **Update model** (live-review wave):
   - Inputs: prior + current RT score + review count + review velocity + critic mix + timing risk
   - Output: posterior probability + confidence band

Calibration target:
- Brier
- Log loss
- CLV vs available executable ask

---

## 3) Initial creator-prior read on current watchlist (from public RT metadata snippets)

## Scary Movie (2026)
- RT page metadata indicates director **Mike/Michael Tiddes**.
- RT celebrity page snippets indicate past directed films with low critic scores (examples shown: 0%, 4%, 8%, 10%, 21%).
- Working prior impact: **negative creator prior** for high-threshold RT outcomes (e.g., 60%+).
- Counter-signal to test: legacy cast-return effect (Anna Faris + Regina Hall + Wayans reunion) may partially offset.

## The Death of Robin Hood (2026)
- Directed/written by **Michael Sarnoski**.
- RT snippets show prior directed titles: **Pig 97%**, **A Quiet Place: Day One 86%**.
- Working prior impact: **strong positive director prior** for higher thresholds.
- Additional cast prior likely positive (Hugh Jackman / Jodie Comer cluster), pending structured extraction.

## Backrooms (2026)
- Directed by **Kane Parsons** (feature directorial debut), heavy producer bench (James Wan, Shawn Levy, etc.).
- Debut-director uncertainty + analog-horror IP upside.
- Working prior impact: **high-variance prior** (wide confidence interval), not directional without stronger collaboration comps.

## The Last Viking (Den sidste viking)
- Directed/written by **Anders Thomas Jensen**.
- RT snippets show strong director track record (e.g., Riders of Justice 96%, Men & Chicken 84%, and listing indicating The Last Viking in high range).
- Working prior impact: **positive creator prior** for mid/high thresholds, but with market/locale/release-window translation risk.

---

## 4) Concrete correlation hypotheses to test next

H1: Director prior dominates pre-release probability when review_count < 30.

H2: Legacy cast reunion in parody franchises reduces downside tail vs pure reboot casts.

H3: Director+lead actor repeat pairings have measurable uplift vs independent priors.

H4: Producer-stack quality only helps when coupled with proven director history; producer names alone are weak predictors.

H5: Early review velocity slope (reviews/hour) is predictive of final threshold crossing beyond static score snapshot.

H6: Boundary markets (e.g., 59/60) require uncertainty inflation even when point estimate is strong.

---

## 5) Data schema extension (recommended)

Add movie-level research table (or JSON artifact) with:
- movie_slug
- director_ids, writer_ids, producer_ids
- top_cast_ids
- collaboration_edges (pair counts)
- creator_prior_mean, creator_prior_std
- genre_prior_mean
- pre_release_signal_score
- prior_probability
- posterior_probability
- calibration_bucket

---

## 6) Guardrails

- Never flip to paper-actionable from correlation features alone.
- Require independent direct-source refresh + rule/cutoff validation + executable depth/spread + sizing gate.
- Keep these priors explicitly labeled as **research diagnostics**.
