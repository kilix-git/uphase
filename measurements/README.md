# Measurements

- `raw/` - data exactly as recorded. Never edit a raw file after recording;
  correct or filter it in `analysis/`.
- `analysis/` - scripts, notebooks and results derived from raw data.

File naming: `YYYY-MM-DD_<what>_<setup>.<ext>`, for example
`2026-11-20_transformer-tr1_linearity.csv`.

Every raw file should have a journal entry for the same day describing the
setup: instruments, reference meter, load, wiring, and ambient temperature.

Licence: Beerware (see [LICENSE](../LICENSE)).
