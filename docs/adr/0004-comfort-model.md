# ADR 0004: Personal comfort model and suggestions

- Status: Accepted
- Date: 2026-11-18

## Context

Milestone 6 adds an "AI" that suggests the AC setting. Constraints that shaped the design:

- **No AC in the room where the node is installed**, so manual AC adjustments cannot be used as labels. Labels come from comfort votes on the dashboard (ADR 0003): "want it cooler / comfortable / want it warmer", stored with the readings at that moment.
- **Few labels.** A person gives perhaps 5–10 votes a day, so after two weeks there are roughly 70–140. A model that needs thousands of samples is out of the question.
- **Runs on the Pi**, next to the Safety Layer, with no extra heavy dependencies.
- **Honesty of evaluation.** Results must not be inflated by synthetic data or by testing on the data used for training.

## Decision

### Model: ordinal logistic regression with a population prior

The three answers are ordered (warmer < no change < cooler), so the model is a proportional-odds (ordinal logistic) regression: a latent score grows with air temperature (and humidity), and two thresholds split it into the three answers.

1. **Population model** fitted offline (`ml/train_prior.py`) on the ASHRAE Global Thermal Comfort Database II v2.1.0 (DOI 10.6078/D1F671): about 20,000 thermal-preference votes with air temperature and humidity from tropical and monsoon-influenced subtropical climates. Only four numbers are committed (`gateway/comfort_prior.json`); the raw data is downloaded by the script from the authors' repository at a pinned commit and is not redistributed.
2. **Personalisation** on the Pi from the user's own votes, two parameters only:
   - `shift` (°C): how much warmer or cooler this person likes it than the population (prior N(0, 2²));
   - `scale`: how consistently this person answers compared with a crowd (prior log-normal around 1).

   MAP estimate; with few votes the model stays close to the population model, with more votes it moves to the person. Older votes are down-weighted (half-life 30 days) so the model follows seasonal changes. Pure Python, no numpy.

### From prediction to advice

- **Comfort band:** temperatures where the predicted probability of wanting a change in each direction is at most 30 %.
- **Suggested setpoint:** the *warmest* integer temperature inside the band (comfort first, then energy), clamped to the automatic window of the Safety Layer (24–29 °C).
- **Rules** (`comfort.advise`): suggest turning on only when P(want cooler) ≥ 60 % and someone is (or may be) present; between the band edge (30 %) and 60 % the dashboard says the room is warmer than the band and *offers* turning on, but the automatic mode does nothing (a gap between the two thresholds avoids switching on for marginal discomfort); move the setpoint by one degree towards the target; suggest turning off only after the room has been empty for 15 minutes (the LD2420 alone flips to "empty" after about 15 s); never act in heat or fan mode.

### Two ways to use it

- **Suggestion (default):** the dashboard shows the advice and the reason; "Áp dụng" sends it as a normal *app* command.
- **Automatic (opt-in, `ADVISOR_AUTO=1`):** every 60 s the gateway applies the advice with source `ai`. It asks the Safety Layer first without logging (`CommandService.preview`) so the decision log is not flooded by repeated refusals; the command itself goes through `submit()` and all Safety Layer rules (auto-hold after a human action, uncertain state, 1 °C steps, one automatic command per 10 min, no power-on in an empty room).

### Evaluation

- Population model: 5-fold cross-validation **grouped by building**, against "always the most common answer" and a fixed 23–26 °C rule (`docs/ml/population-model.md`).
- Personal model: **prequential** evaluation (`ml/evaluate_personal.py`): every vote is predicted by a model trained only on earlier votes, exactly as the system works in use. Compared with the population model, the person's most frequent answer, and the fixed rule.
- Primary metric: **log-loss** (quality of probabilities, which drive the 30 % / 60 % thresholds). Accuracy and macro-F1 are reported as well.
- `ml/simulate_votes.py` creates a *copy* of the database with simulated votes to test the pipeline; reports generated from it are labelled as simulated and are not evidence about real users.

## Alternatives considered

- **Generic classifier (random forest, neural network) trained only on personal votes.** Needs far more labels than a person gives; no principled way to start from population knowledge.
- **PMV/PPD (ISO 7730, ASHRAE 55).** Needs clothing, metabolic rate, air speed and radiant temperature, which the node does not measure, and does not learn the individual.
- **Learn from manual AC adjustments.** Not possible in this room; the code path remains possible later because every vote also stores the expected AC state.

## Consequences and known limitations

- With few votes, suggestions are essentially the population model (setpoint about 25 °C at 60 % RH). The dashboard says so until there are 10 votes.
- Votes are voluntary and may over-represent uncomfortable moments; the evaluation reports the class balance.
- Only air temperature and humidity are inputs; air speed, radiant temperature, clothing and activity are unknown. Humidity has almost no effect in the population data.
- The `scale` grid ends at about 4; a person even more consistent than that is modelled as scale 4.
- In simulation the fixed 23–26 °C rule can reach a higher accuracy than the model while having worse log-loss. Whether personalisation is worth it must be decided on real votes, and the report must show the comparison either way.
