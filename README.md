# OR Scheduling Instance Generator

A synthetic instance generator for the elective operating-room (OR) scheduling
problem — surgeries × operating rooms × surgeons — used to benchmark exact
(integrated) and two-stage MIP formulations under realistic, controllable
conditions.

The generator does **not** use, embed, or redistribute any private hospital
dataset. Every distributional assumption below is calibrated from published,
publicly available sources, cited inline. Where a parameter is a modeling
choice rather than a hard empirical figure, this is stated explicitly.

## What it generates

For a given number of operating rooms, the generator produces three tables:

- **Rooms** (`Pabellones`): room ID, assigned specialty for the day, and
  available minutes (9h shift, 08:00–17:00).
- **Candidate surgeries** (`Cirugias`): ID, specialty, duration in minutes.
- **Surgeons** (`Medicos`): ID, specialty, and an availability block
  (start/end minute).

## Assumptions and their sources

### 1. Specialty taxonomy

Surgical specialties are drawn from the official Chilean specialty
classification (REM-07), as defined in MINSAL's *Norma de Listas de Espera*
(2011), which lists surgical specialties including Cirugía Adulto, Cirugía
Infantil, Traumatología, Obstetricia, Ginecología, Oftalmología, and others.
This generator uses a subset of six of these, restricted to elective major
surgery.

### 2. One specialty per operating room per day ("block scheduling")

Each room is assigned exactly one specialty for the planning day; no room
serves more than one specialty in the same session. This mirrors the
**dedicated block / block-scheduling policy**, the dominant OR allocation
strategy documented in the operating-room-scheduling literature:

- Cardoen, B., Demeulemeester, E., & Beliën, J. (2010). *Operating room
  planning and scheduling: A literature review.* European Journal of
  Operational Research, 201(3), 921–932.
- Guerriero, F., & Guido, R. (2011). *Operational research in the management
  of the operating theatre: A survey.* Health Care Management Science.

Under this policy, an OR is allocated to a single surgical service for a
block of time (normally a half-day or a full day); switching a room between
specialties mid-session is avoided because of the reconfiguration/turnover
cost it imposes.

### 3. Realistic room counts per instance

Instance sizes (default: 4, 8, 12, 16, 20 rooms) are grounded in the actual
distribution of OR capacity across Chilean public hospitals:

- IPSUSS – Universidad San Sebastián (2022), *¿Cómo se usan los pabellones
  quirúrgicos en Chile? Radiografía al sector estatal de salud*, reports a
  national stock of 659 operating rooms across 88 MINSAL-dependent hospitals
  (~7.5 rooms/hospital on average), with strong heterogeneity by hospital
  complexity tier (low/medium-complexity hospitals typically have 2–6 rooms;
  high-complexity referral hospitals can have 10–20+).

Instances are not generated beyond ~20–24 rooms, since that would no longer
represent a single hospital's daily OR-scheduling problem.

### 4. Surgeon availability as standard work blocks

Surgeon availability windows are drawn from three standard block types
(full-day, morning half-day, afternoon half-day), not arbitrary continuous
windows. This follows standard perioperative block-time management practice,
under which OR block time is granted in half-day or full-day increments, and
blocks shorter than roughly four hours are considered operationally
inefficient and are generally avoided:

- Riise, A., Mannino, C., & Burke, E. K. (2016). *Modelling and solving
  generalised operational surgery scheduling problems.* Computers &
  Operations Research.
- Cardoen et al. (2010); Guerriero & Guido (2011), as above.

Full-day blocks are weighted slightly higher than half-day blocks, reflecting
the operational preference for full-day blocks noted in perioperative
management practice (fewer turnovers, more consistent utilization).

### 5. Specialty mix (rooms and surgeon pool)

The relative weight of each specialty (used both for assigning rooms to
specialties and for populating the surgeon pool) is calibrated to be
order-of-magnitude consistent with the national 2024 distribution of
specialist physicians by specialty reported in:

- Arancibia-Luna, M.J., Riedemann González, J.P., Castillo Mora, J.A., &
  Huaiquilaf-Jorquera, S. (2026). *Médicos especialistas en Chile: Análisis
  de la situación 2024.* Revista Médica de Chile, 154(3), 313–324.

This is a national physician-count proxy, not hospital-specific staffing
data, and is treated as a calibration assumption rather than a precise
figure — Cirugía General and Traumatología y Ortopedia (mapped here to
`Cirugia_Adulto` and `Traumatologia`) are the largest surgical specialties
nationally, followed by Obstetricia/Ginecología, then smaller specialties
such as Oftalmología and Cirugía Infantil (Pediátrica).

### 6. Surgery duration distribution

Surgery durations are drawn from a Gamma distribution fitted (by moment
matching) to a mean of 136.2 minutes and a standard deviation of 58.0
minutes, matching the empirical, right-skewed duration distribution reported
over 78 real elective procedures in:

- Meza-Vásquez, K., Moyano, M., Arrey, E., Cabrera-Guerrero, G., Salas, R., &
  Arriola, A. (2025). *A Two-Stage Hybrid Optimisation Approach for Elective
  Surgery Scheduling in Operating Rooms.* CLEI 2025.

Durations are clipped to a clinically plausible range (45–400 minutes) and
rounded to the nearest 5 minutes.

### 7. Demand oversupply (`factor_sobredemanda`)

For each specialty, the generator produces candidate surgeries until their
total duration reaches a configurable multiple (default 1.5×) of that
specialty's total room capacity for the day. This reflects the well-known
gap between elective-surgery demand and available OR capacity in the
Chilean public system (see e.g. Comisión Nacional de Evaluación y
Productividad, 2020, *Uso Eficiente de Quirófanos Electivos y Gestión de
Lista de Espera Quirúrgica No GES*), and ensures the scheduling problem is a
genuine selection problem rather than a trivial assignment.

## Usage

```python
from generar_instancia import generar_instancia, guardar_instancia
from pathlib import Path

instancia = generar_instancia(n_pabellones=12, seed=42, factor_sobredemanda=1.5)
guardar_instancia(instancia, Path("instancias"), prefijo="12_pab")

print(instancia["reporte_cobertura"])  # coverage fraction per active specialty
```

Key parameters of `generar_instancia`:

| Parameter | Default | Meaning |
|---|---|---|
| `n_pabellones` | — | Number of operating rooms in the instance |
| `factor_sobredemanda` | 1.5 | Ratio of candidate surgery minutes to room capacity, per specialty |
| `medicos_por_pabellon` | 1.0 | Base surgeon pool size per room, before coverage reinforcement |
| `cobertura_minima` | 0.8 | Minimum fraction of the day that must be covered by at least one surgeon of each active specialty |
| `max_medicos_extra_por_especialidad` | 8 | Safety cap on reinforcement surgeons added per specialty |

## Using your own data

All the assumptions above are defaults calibrated for the Chilean public
system. If you have your own real surgery records (from a different
hospital, country, or specialty mix), you can plug them in directly instead
of relying on the built-in calibration:

```python
from generar_instancia import generar_instancia

# Your own data: a CSV/xlsx with columns 'Especialidad' and 'Duracion' (minutes)
# — 'Tiempo' is also accepted as the duration column name — one row per
# observed surgery. See plantilla_datos_propios.csv for the format.
instancia = generar_instancia(
    n_pabellones=10,
    datos_cirugias_propios="mis_cirugias.csv",
)
```

Behaviour:

- Passing a surgery-level list is already handing the generator your own
  prior: **by default, the specialty mix (for both rooms and surgeons) is
  derived automatically from the frequency of each specialty in
  `datos_cirugias_propios`** — your own specialty names/codes are used as-is,
  they do not need to match the six Chile-specific categories. This is what
  `pesos_especialidad_desde_datos` does under the hood; you no longer need
  to call it yourself.
- `datos_cirugias_propios` also changes how `generar_cirugias` produces
  durations, per specialty, controlled by `modo_duracion_propia`:
    - `"bootstrap"` (default): candidate surgeries only ever use durations
      that appear in your data for that specialty (resampled with
      replacement). It never invents a duration outside what you observed.
    - `"bootstrap_gamma"`: on top of the durations that are there, it also
      adds surgeries with durations drawn from a Gamma distribution fitted
      (by moment matching) to that specialty's *own* observed mean/sd —
      not the Chile-wide default — rounded to the nearest 5 minutes. The
      split between "observed" and "gamma" surgeries is controlled by
      `prop_gamma_en_mixto` (default 0.5). This is useful when a specialty
      only has a handful of distinct observed durations and you want more
      continuous variation around that distribution rather than exact
      repeats.
    - `"auto"` (previous behaviour): bootstrap if the specialty has at least
      5 observations, otherwise the Chile-wide default Gamma.
  If a specialty has zero observations in your data, the generator warns and
  falls back to the Chile-wide default Gamma for that specialty only.
- If you want to *keep* the default Chile-calibrated mix while still
  bootstrapping durations from your data (or impose some other target mix),
  pass `pesos_especialidad` explicitly — but then its keys must match the
  `Especialidad` labels used in `datos_cirugias_propios`, or the bootstrap
  will never find a matching pool and will silently fall back to the Gamma
  distribution for every specialty. The generator checks for this and raises
  a `UserWarning` if `pesos_especialidad` and `datos_cirugias_propios` share
  no specialty labels at all. Pass `usar_mezcla_de_datos_propios=False` to
  explicitly opt out of the auto-derived mix and fall back to the
  Chile-calibrated weights even when `datos_cirugias_propios` is given.
- Room-count tiers, block-time structure (full-day/half-day), oversupply
  factor, and coverage-reinforcement logic are unaffected — they apply
  regardless of which specialty mix or duration data you use.

## Editing the generated files by hand

Instead of (or in addition to) changing generation parameters, you can start
from the three `.xlsx` files already produced for an instance and edit them
directly — e.g., to add/remove surgeons or surgeries by hand. To keep the
instance internally consistent with the rest of the generator's assumptions:

**Adding or removing surgeons (`*_Medicos.xlsx`)**

- Columns: `Medico_ID` (unique integer), `Especialidad`, `Inicio`, `Fin`
  (minutes since midnight).
- `Especialidad` must match one of the specialties actually present in that
  same instance's `*_Pabellones.xlsx`. Each room is restricted to one
  specialty per day, and each surgery can only be done by a surgeon of the
  matching specialty, so a surgeon with a specialty that has no room that
  day can never be assigned to anything.
- Keep `Inicio`/`Fin` within the 08:00–17:00 working day (480–1020 in
  minutes) and, if you want to preserve the block-scheduling assumption this
  generator is built on (see Assumption 4), pick one of the three standard
  blocks rather than an arbitrary window: full day (480–1020), AM half-day
  (480–750), or PM half-day (750–1020).
- The instance was generated to reach a *minimum* coverage
  (`cobertura_minima`, 80% of the day by default) per active specialty —
  that's a floor, not a ceiling. Adding surgeons only increases coverage, so
  it's always safe; removing surgeons can drop a specialty's coverage
  below what the candidate surgeries of that specialty actually need,
  making some of them impossible to schedule at all rather than just
  harder to fit in.

**Adding or removing surgeries (`*_Cirugias.xlsx`)**

- Columns: `ID_IQ` (unique integer), `Especialidad`, `Tiempo` (minutes).
- `Especialidad` must again match a specialty present in that instance's
  `*_Pabellones.xlsx`, or the added surgery can never be assigned to any
  room.
- If you want added rows to look like the rest of the data, keep `Tiempo`
  within the same clinically-plausible range used elsewhere (45–400
  minutes) and rounded to the nearest 5 minutes.
- The instance was generated so that each specialty's total candidate
  surgery-minutes equal `factor_sobredemanda` (1.5× by default) times that
  specialty's total room-minutes for the day — this oversupply is what
  makes the scheduling problem a real selection problem rather than a
  trivial assignment (see Assumption 7). Adding or removing surgeries by
  hand changes that ratio for the specialties you touch; worth deciding
  whether you want to preserve it (for comparable difficulty across
  instances) or deliberately move it to see how each model degrades as the
  backlog grows or shrinks.

## Reproducibility

All randomness is controlled via a single `seed` argument (NumPy
`Generator`). If you don't pass one, the generator draws a concrete seed
itself instead of leaving the run unseeded — so an instance is always
reproducible, even if you forgot to set a seed.

`generar_instancia` returns an `instancia["metadata"]` dict with every
parameter needed to reproduce that exact instance (seed, room count,
oversupply factor, the specialty weights actually used, duration mode,
etc.). `guardar_instancia` writes this alongside the three `.xlsx` files as
`{prefijo}_metadata.json`, and `regenerar_desde_metadata(ruta_metadata)`
rebuilds the identical instance from that file alone:

```python
from generar_instancia import generar_instancia, guardar_instancia, regenerar_desde_metadata
from pathlib import Path

instancia = generar_instancia(n_pabellones=12, factor_sobredemanda=1.5)  # no seed passed
guardar_instancia(instancia, Path("instancias"), prefijo="12_pab")

# Later, from just the saved files:
misma_instancia = regenerar_desde_metadata("instancias/12_pab_metadata.json")
```

If `datos_cirugias_propios` was passed as an in-memory DataFrame (rather
than a file path), the metadata only stores a summary (row count, specialty
labels) — not the raw durations, to avoid ever embedding real surgery data
in a versioned `.json` artifact. In that case, reproduce the instance by
calling `generar_instancia` directly with the same DataFrame and the other
parameters listed in the metadata.

## Citation

If you use this generator, please cite the accompanying paper (citation to be
added on publication) together with the sources listed above for the
specific assumptions you rely on.
