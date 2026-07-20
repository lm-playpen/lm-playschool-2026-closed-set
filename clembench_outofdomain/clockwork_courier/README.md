# Clockwork Courier

## What is this game?

You are a bicycle courier in a small clockwork city. The city is a grid of streets
and walls. Somewhere on that grid lie one or more **parcels**; each parcel has a
pickup point and a delivery address. Your job: **pick up every parcel and deliver it
to its address before the clock runs out.**

Two things make the city tricky:

- **Gates** — some street cells are blocked by gates that open and close forever on a
  fixed timer (for example: "open for 3 ticks, closed for 3 ticks"). You can only
  enter a gate cell while it is open; otherwise you bounce off and lose the time.
- **Guards** — guards walk fixed loops through the streets, one step per tick. If you
  end up on the same cell as a guard, you are caught and dragged back to your
  starting point, losing precious time.

The twist that defines the game: **nothing is hidden and nothing is random.** You are
given the complete map, every gate's exact timetable, and every guard's exact route
before you make your first move. A perfect player could compute the entire future of
the city. The whole challenge is *thinking ahead in time*: "if I head down this
street now, where will guard P be when I get there? Will gate A be open when I
arrive, or should I leave two ticks later?"

You don't move one step at a time. Each turn you must commit to a **plan of several
moves at once** (e.g. exactly 4 moves), and the city executes the whole plan before
you hear back. A mistake in the middle of a plan cannot be taken back — the clock
keeps ticking. And with every plan you must also state where you *predict* you will
end up, which the referee grades silently — a test of whether your mental picture of
the city matches reality.

## The environment, piece by piece

Here is a small example city:

```
   1234567
  +-------+
 1|S#1....|
 2|.......|
 3|.....#.|
 4|x..p.#A|
 5|.......|
 6|..#....|
 7|.#..##.|
  +-------+
```

- The grid is addressed as **(column,row)**; `(1,1)` is the top-left cell. The numbers
  printed along the top and left edges are the column and row indices.
- `S` — your start cell. Here: `(1,1)`.
- `#` — walls. You cannot enter them; the outer border is also impassable.
- `.` — open street.
- `1` — the pickup cell of parcel 1 (at `(3,1)`); `x` — its delivery address (at
  `(1,4)`). With more parcels you would also see `2`/`y`, `3`/`z`.
- `A` — a gate cell (at `(7,4)`).
- `p` — guard P, drawn where it stands at time t=0. **Guards move!** The map only
  shows their starting spot; their full routes are listed in the prompt as text.

Alongside the map the player receives the exact timetables:

> Gate A at (7,4): open exactly when (t mod 6) is in {2, 3, 4}. So it is open at
> t=2,3,4,8,9,10,... and closed at t=0,1,5,6,7,11,...
>
> Guard P: walks a fixed cycle of length 8. Its position at tick t is determined by
> (t mod 8) as follows: t mod 8=0: (4,4); t mod 8=1: (3,4); t mod 8=2: (2,4);
> t mod 8=3: (2,3); t mod 8=4: (3,3); t mod 8=5: (2,3); t mod 8=6: (2,4);
> t mod 8=7: (3,4). This repeats forever.
>
> Parcel 1: pick it up at (3,1), deliver it to (1,4).
> Deliver every parcel within 20 ticks. You submit plans of exactly 4 moves; you
> have at most 5 plans in total.

### How time works

Time advances in **ticks**: t=0, 1, 2, ... You start at t=0 and make exactly one
move per tick: `N` (up), `S` (down), `E` (right), `W` (left), or `WAIT`. One tick
resolves in this fixed order:

1. **Your move resolves.** Walking into a wall, the border, or a gate that is closed
   at your *arrival* time is a **BUMP**: you stay where you are and the tick is
   wasted anyway.
2. **Every guard takes its step** to its position for the new time.
3. **Capture check.** If you now share a cell with a guard, you are **CAUGHT**:
   you keep your parcels, but you are put back on `S`, the rest of your current plan
   is cancelled, and those cancelled ticks are lost. (Passing a guard mid-move —
   you stepping into its old cell while it steps into yours — is explicitly safe;
   only *ending* a tick on a guard's cell counts.)
4. **Pickup/delivery happens automatically** if you ended the tick on a parcel's
   pickup cell (you take it) or on the address of a parcel you carry (you deliver).

## How a game is played, turn by turn

The model receives one big initial prompt: the map, the legend, the timetables, the
rules above, and the required answer format. Then the game loops:

**1. The model answers in exactly this format:**

```
THOUGHTS: Pickup is at (3,1) but the wall at (2,1) blocks the direct path, so I go
around: down, two steps east, then up. I'll reach (3,1) at t=4 and auto-pick-up.
Guard P is over at (3,4)/(2,3) area, nowhere near me in the first 4 ticks.
POSITION: (3,1)
PLAN: S E E N
```

- `THOUGHTS:` — free-form reasoning, any length. The referee ignores it.
- `POSITION:` — the cell the model **predicts it will occupy after the plan runs**.
  The referee records whether the prediction was right but never says so — it is a
  pure measurement of the model's internal tracking.
- `PLAN:` — exactly L moves (here 4). Wrong length or unknown tokens get one
  corrective re-prompt; repeated violations abort the episode.

**2. The referee simulates the plan tick by tick and reports back** (real output):

```
ROUND 1 RESULT (ticks 0 -> 4):
t=1: S -> OK, now at (1,2).
t=2: E -> OK, now at (2,2).
t=3: E -> OK, now at (3,2).
t=4: N -> OK, now at (3,1). PICKED UP parcel 1.
STATUS: tick 4 of 20. You are at (3,1). Carrying: parcel 1. Delivered: nothing. Rounds left: 4.
```

**3. Repeat** until every parcel is delivered (**win** — the game ends the instant
the last parcel arrives, even mid-plan), the tick budget runs out (**loss**), or the
model keeps breaking the response format (**abort**).

### What going wrong looks like

Suppose the model had instead headed straight for the delivery address without
checking the guard's timetable, with `PLAN: S S E E`:

```
ROUND 1 RESULT (ticks 0 -> 4):
t=1: S -> OK, now at (1,2).
t=2: S -> OK, now at (1,3).
t=3: E -> CAUGHT by guard P at (2,3)! Returned to start (1,1).
Capture penalty: the remaining 1 move(s) of your plan were cancelled and the round's
leftover ticks were forfeited; the clock jumped to t=4.
STATUS: tick 4 of 20. You are at (1,1). Carrying: nothing. Delivered: nothing. Rounds left: 4.
```

Guard P stands on (2,3) exactly when t mod 8 = 3 — the timetable said so, and the
model walked right into it. Four of twenty ticks are gone and the courier is back
where it started. (The optimal solution of this instance needs 9 ticks: around the
wall to the pickup, then down and across to `x`, threading between P's positions.)

## Objectives, in order of importance

1. **Deliver every parcel before the tick budget runs out.** This is the win
   condition and dominates the score.
2. **Be fast.** Wins are graded by `optimal_ticks / used_ticks` — finishing in the
   provably minimal number of ticks scores 100.
3. **Don't get caught, don't bump.** Captures and bumps cost ticks (and are logged
   as diagnostic metrics).
4. **Know where you are.** Every round's POSITION prediction is graded into a
   Prediction Accuracy metric.

## The three experiments

Each experiment varies what makes the game hard. 10 instances each, 30 episodes total.

| name | grid | gates | guards | parcels | moves | plan length | what the feedback tells you |
|---|---|---|---|---|---|---|---|
| `standard` | 9×9 | 2 | 2 | 2 | N/S/E/W/WAIT | 5 | everything |
| `deadreckon` | 9×9 | 2 | 2 | 2 | N/S/E/W/WAIT | 5 | **only OK/BUMP/CAUGHT/PICKED UP/DELIVERED — never your position, never why you bumped. You must track where you are entirely in your head.** |
| `egocentric` | 8×8 | 1 | 2 | 2 | **F/L/R/WAIT** | 6 | everything, but there are no compass moves: `F` steps forward in the direction you are facing, `L`/`R` turn 90° in place (costing a tick). You must track your own heading. |

## Scoring (fully programmatic, no judge)

```
Main Score = 100 * (0.7 * parcels_delivered/K  +  0.3 * efficiency)
efficiency = optimal_ticks / used_ticks   if won, else 0
```

- Aborted episodes score NaN. Any win scores ≥ 70; a tick-perfect win scores 100;
  losses keep partial credit per delivered parcel (e.g. 1 of 2 delivered = 35).
- `optimal_ticks` is computed per instance by breadth-first search over the
  time-expanded state space `(position, heading, t mod schedule-period, parcel
  states)` and shipped inside the instance — so "optimal" is exact, not heuristic.
- Diagnostics logged alongside: Delivery Rate, Ticks Used, Efficiency, Prediction
  Accuracy, Bump Count, Capture Count, Forfeited Ticks; per-round: prediction
  correctness, bumps, captures, deliveries, wasted ticks.

## Files

- `courier_engine.py` — pure-python world model: tick simulation, BFS optimal solver,
  and all text rendering (map, schedules, feedback)
- `master.py` — GameMaster / Player / Scorer / Benchmark (modern clemcore API)
- `instancegenerator.py` — seeded procedural generation; every instance is verified
  solvable, and instances that a dynamics-ignoring shortest path solves unimpeded
  are rejected (the clockwork must matter)
- `in/instances.json` — 3 experiments × 10 instances (seed 73)
- `test_courier_engine.py` — engine + generator unit tests
- `visualize.py` — plots an instance and its routes (see below)
- `requirements.txt` — game-specific extras beyond clemcore (only needed for
  visualization and tests; playing/scoring the game needs clemcore alone)

## Visualizing instances and episodes

`visualize.py` draws the board (walls, gates, parcels, guard routes), the
BFS-optimal route, and — given a recorded episode — the route the model actually
took, with bumps (`x`) and captures (red `X`) marked. One-time setup:

```bash
pip install -r clockwork_courier/requirements.txt   # matplotlib
```

All commands below run from the repo root. Episode visuals are saved **into the
episode folder, next to transcript.html** (override with `--out`); episode mode
reads the episode's own `instance.json`, so old runs stay visualizable even after
`in/instances.json` is regenerated with a new seed. Instance-only renders go to
`clockwork_courier/viz/`.

### Static route plots (PNG)

Tick numbers along the routes show *when* the courier was where, so you can line
them up against the gate/guard timetables printed under the plot. In egocentric
plots, two consecutive ticks on the same cell are a turn in place.

```bash
# one recorded episode: model route (orange) vs optimal (blue)
#   -> results/<model>/clockwork_courier/standard/instance_00000/visualization.png
.venv/bin/python clockwork_courier/visualize.py \
    --episode results/<model>/clockwork_courier/standard/instance_00000

# every clockwork_courier episode under a results folder, one PNG each
.venv/bin/python clockwork_courier/visualize.py --results results/<model>

# just an instance, no episode (board + guard routes + optimal route)
#   -> clockwork_courier/viz/standard_0.png
.venv/bin/python clockwork_courier/visualize.py -e standard -i 0
```

### Animated GIFs

Add `--animate` to any of the commands above to render a GIF instead: the world
plays out tick by tick — **guards walk their routes, gates blink green (open) /
red (closed), and the model's courier (orange) races the optimal ghost
(semi-transparent blue)**, both leaving trails. This is the easiest way to *see*
why a route bumped into a closed gate or walked into a guard.

```bash
# one episode as a GIF -> .../instance_00000/visualization.gif
.venv/bin/python clockwork_courier/visualize.py \
    --episode results/<model>/clockwork_courier/standard/instance_00000 --animate

# GIFs for every episode of a run (slower: one GIF per episode)
.venv/bin/python clockwork_courier/visualize.py --results results/<model> --animate

# animate just an instance's optimal route -> clockwork_courier/viz/standard_3.gif
.venv/bin/python clockwork_courier/visualize.py -e standard -i 3 --animate

# playback speed: ticks per second (default 2)
.venv/bin/python clockwork_courier/visualize.py \
    --episode results/<model>/clockwork_courier/standard/instance_00000 --animate --fps 4
```

## Running

```bash
# from the repo root
.venv/bin/python -m pytest clockwork_courier/ -q   # unit tests
clem run -g clockwork_courier -m <model>           # -m mock plays a built-in optimal oracle
clem score -g clockwork_courier
clem transcribe -g clockwork_courier
```

A mock run doubles as a regression test: the mock player solves each instance with
the BFS oracle and plays it out (expect 30/30 wins, Main Score 100, Efficiency 1.0),
deliberately malforming one response per episode to exercise the re-prompt path.
