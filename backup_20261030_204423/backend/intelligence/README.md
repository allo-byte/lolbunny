# BunnyLoL Intelligence Engine (experimental)

This package is deliberately isolated from `recommend.py` and `draft.py` in
its first iteration. It establishes a testable contract before production
integration; importing it does not alter current recommendations.

## API

- `evaluate_item(champion, item, game)` returns `viability_pct`, a factor
  breakdown, reasons, limitations, and a separate `data_confidence_pct`.
- `evaluate_build(champion, items, game)` aggregates item compatibility and
  removes duplicate IDs.
- `viability_score(factors)` computes the documented weighted score.

The viability percentage is **not** win probability. It measures contextual
compatibility from the factors currently available. Confidence measures how
complete and current the underlying data is. Unknown ability ratios and
unverified passives are not inferred from descriptive text.

## Data contract

Champion profiles may contain `key`, `tags`, `scalings`, `verified`, and
`patch`. `scalings` is a structured set of compatibility weights (0-100), not
raw ability coefficients. Exact ability simulation will require a separately
verified ability/effect registry with patch-specific formulas.

Items accept Data Dragon stat keys (`FlatPhysicalDamageMod`,
`FlatMagicDamageMod`, `FlatHPPoolMod`, `FlatArmorMod`, `FlatSpellBlockMod`,
`PercentAttackSpeedMod`, etc.) and optional `needs` / `effects_verified`.

Game state accepts patch, game time in seconds, current gold, owned item IDs,
and enemies with actual stats, known damage mix, and situational flags.

## Current limitations

- The evaluator models listed item stats, enemy resistances, economy, phase,
  and explicit situational flags. It does not yet simulate ability rotations,
  runes, item actives, on-hit triggers, shields, healing, or unverified effects.
- Unknown enemy damage mix is neutral and lowers confidence; it is not guessed.
- No production integration has been enabled yet. This is intentional until
  adapters and regression tests are ready.

## Next integration gates

1. Versioned Data Dragon adapter and cache freshness metadata.
2. Patch-specific champion profiles; verified profile registry and validation.
3. Structured item-effect registry with source, patch, and tests per effect.
4. Build-level synergy / redundancy evaluation and economy-aware search.
5. Shadow-mode comparison against existing recommender before enabling UI.
