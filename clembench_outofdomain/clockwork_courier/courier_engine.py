"""Simulation engine for the Clockwork Courier game.

Pure-stdlib module shared by master.py, instancegenerator.py and the unit tests.
It knows nothing about clemcore: it models the world, executes move plans tick by
tick, solves instances optimally via BFS over the time-expanded state space, and
renders the textual artifacts (map, schedules, round feedback) so that the game
master and the tests share the exact same wording.

World rules (also documented verbatim in the player prompt):
- Coordinates are (col, row), 1-based, (1,1) is top-left. Moving N decreases row.
- Time advances in integer ticks. Move i of an episode is the transition t=i -> t=i+1.
- Gates are floor cells that are open iff (t mod period) is in open_phases. A move
  onto a gate cell during t -> t+1 requires the gate to be open at the ARRIVAL time
  t+1; otherwise the move bumps (tick wasted). Standing on a gate is always safe.
- Guards follow published cyclic routes: position at time t is route[t mod len].
  Capture = sharing a cell with a guard at the END of a tick. Mid-tick swaps are safe.
- Per-tick resolution order: (1) courier move resolves (bump check), (2) guards
  advance to their t+1 cells, (3) capture check, (4) automatic pickup/delivery.
- On capture the courier keeps parcels, returns to start (heading reset), the rest
  of the current plan is cancelled and its remaining ticks are forfeited.
"""

from dataclasses import dataclass, field
from math import lcm
from collections import deque
from typing import Dict, List, Optional, Set, Tuple

Cell = Tuple[int, int]

HEADING_ORDER = ["N", "E", "S", "W"]  # clockwise

CARDINAL_DELTAS = {"N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0), "WAIT": (0, 0)}

CARDINAL_MOVES = ("N", "S", "E", "W", "WAIT")
EGO_MOVES = ("F", "L", "R", "WAIT")

DROPOFF_GLYPHS = "xyz"  # parcel id 1 -> 'x', 2 -> 'y', 3 -> 'z'


def rotate(heading: str, move: str) -> str:
    idx = HEADING_ORDER.index(heading)
    if move == "L":
        return HEADING_ORDER[(idx - 1) % 4]
    if move == "R":
        return HEADING_ORDER[(idx + 1) % 4]
    return heading


@dataclass(frozen=True)
class Gate:
    id: str  # single uppercase letter, e.g. "A"
    cell: Cell
    period: int
    open_phases: frozenset

    def is_open(self, t: int) -> bool:
        return (t % self.period) in self.open_phases


@dataclass(frozen=True)
class Patrol:
    id: str  # single uppercase letter, e.g. "P"
    route: Tuple[Cell, ...]  # full cycle; position at t is route[t % len(route)]

    def pos_at(self, t: int) -> Cell:
        return self.route[t % len(self.route)]


@dataclass(frozen=True)
class Parcel:
    id: int  # 1-based
    pickup: Cell
    dropoff: Cell

    @property
    def dropoff_glyph(self) -> str:
        return DROPOFF_GLYPHS[self.id - 1]


@dataclass
class World:
    width: int
    height: int
    walls: frozenset  # set of interior wall cells; the outer border is implicit
    start: Cell
    gates: Tuple[Gate, ...]
    patrols: Tuple[Patrol, ...]
    parcels: Tuple[Parcel, ...]
    action_mode: str = "cardinal"  # "cardinal" | "egocentric"
    initial_heading: str = "N"

    def __post_init__(self):
        self.gate_by_cell: Dict[Cell, Gate] = {g.cell: g for g in self.gates}

    @property
    def moveset(self) -> Tuple[str, ...]:
        return EGO_MOVES if self.action_mode == "egocentric" else CARDINAL_MOVES

    def in_bounds(self, cell: Cell) -> bool:
        return 1 <= cell[0] <= self.width and 1 <= cell[1] <= self.height

    def is_floor(self, cell: Cell) -> bool:
        return self.in_bounds(cell) and cell not in self.walls

    def schedule_period(self) -> int:
        periods = [g.period for g in self.gates] + [len(p.route) for p in self.patrols]
        return lcm(*periods) if periods else 1

    @classmethod
    def from_instance(cls, d: dict) -> "World":
        return cls(
            width=d["width"],
            height=d["height"],
            walls=frozenset(tuple(c) for c in d["walls"]),
            start=tuple(d["start"]),
            gates=tuple(Gate(g["id"], tuple(g["cell"]), g["period"], frozenset(g["open_phases"]))
                        for g in d["gates"]),
            patrols=tuple(Patrol(p["id"], tuple(tuple(c) for c in p["route"]))
                          for p in d["patrols"]),
            parcels=tuple(Parcel(p["id"], tuple(p["pickup"]), tuple(p["dropoff"]))
                          for p in d["parcels"]),
            action_mode=d.get("action_mode", "cardinal"),
            initial_heading=d.get("initial_heading", "N"),
        )

    def to_instance_dict(self) -> dict:
        return {
            "width": self.width,
            "height": self.height,
            "walls": sorted([list(c) for c in self.walls]),
            "start": list(self.start),
            "gates": [{"id": g.id, "cell": list(g.cell), "period": g.period,
                       "open_phases": sorted(g.open_phases)} for g in self.gates],
            "patrols": [{"id": p.id, "route": [list(c) for c in p.route]} for p in self.patrols],
            "parcels": [{"id": p.id, "pickup": list(p.pickup), "dropoff": list(p.dropoff)}
                        for p in self.parcels],
            "action_mode": self.action_mode,
            "initial_heading": self.initial_heading,
        }


@dataclass
class SimState:
    pos: Cell
    heading: str
    t: int = 0
    carried: Set[int] = field(default_factory=set)
    delivered: Set[int] = field(default_factory=set)
    bumps: int = 0
    captures: int = 0
    forfeited_ticks: int = 0

    @classmethod
    def initial(cls, world: World) -> "SimState":
        return cls(pos=world.start, heading=world.initial_heading)

    def clone(self) -> "SimState":
        return SimState(pos=self.pos, heading=self.heading, t=self.t,
                        carried=set(self.carried), delivered=set(self.delivered),
                        bumps=self.bumps, captures=self.captures,
                        forfeited_ticks=self.forfeited_ticks)


@dataclass
class TickEvent:
    t_from: int
    t_to: int
    move: str
    result: str  # "OK" | "BUMP_WALL" | "BUMP_BORDER" | "BUMP_GATE" | "CAUGHT"
    pos_after: Cell  # cell at end of tick, before any capture reset
    heading_after: str
    caught_by: Optional[str] = None
    bump_gate: Optional[str] = None  # gate id when result == "BUMP_GATE"
    pickups: List[int] = field(default_factory=list)
    deliveries: List[int] = field(default_factory=list)

    @property
    def bumped(self) -> bool:
        return self.result.startswith("BUMP")


def _resolve_move(world: World, pos: Cell, heading: str, move: str,
                  t_to: int, ignore_gates: bool = False) -> Tuple[Cell, str, str, Optional[str]]:
    """Resolve the courier's move only (no guards). Returns (pos, heading, result, gate_id)."""
    if world.action_mode == "egocentric":
        if move in ("L", "R"):
            return pos, rotate(heading, move), "OK", None
        delta = (0, 0) if move == "WAIT" else CARDINAL_DELTAS[heading]
    else:
        delta = CARDINAL_DELTAS[move]
    if delta == (0, 0):
        return pos, heading, "OK", None
    target = (pos[0] + delta[0], pos[1] + delta[1])
    if not world.in_bounds(target):
        return pos, heading, "BUMP_BORDER", None
    if target in world.walls:
        return pos, heading, "BUMP_WALL", None
    gate = world.gate_by_cell.get(target)
    if gate is not None and not ignore_gates and not gate.is_open(t_to):
        return pos, heading, "BUMP_GATE", gate.id
    return target, heading, "OK", None


def step(world: World, state: SimState, move: str) -> TickEvent:
    """Execute one tick (resolution order: move, guards, capture, pickup/delivery).

    Mutates `state` except for the capture consequences (reset/forfeit), which are
    applied by run_plan because they depend on the plan's round boundary.
    """
    t_from, t_to = state.t, state.t + 1
    pos, heading, result, gate_id = _resolve_move(world, state.pos, state.heading, move, t_to)
    state.pos, state.heading = pos, heading
    if result.startswith("BUMP"):
        state.bumps += 1
    event = TickEvent(t_from=t_from, t_to=t_to, move=move, result=result,
                      pos_after=pos, heading_after=heading, bump_gate=gate_id)
    state.t = t_to
    # guards advance to their t+1 cells, then the capture check
    for patrol in world.patrols:
        if patrol.pos_at(t_to) == pos:
            event.result = "CAUGHT"
            event.caught_by = patrol.id
            return event
    # automatic pickup / delivery (deliveries first; all special cells are distinct anyway)
    for parcel in world.parcels:
        if parcel.id in state.carried and pos == parcel.dropoff:
            state.carried.discard(parcel.id)
            state.delivered.add(parcel.id)
            event.deliveries.append(parcel.id)
    for parcel in world.parcels:
        if parcel.id not in state.carried and parcel.id not in state.delivered \
                and pos == parcel.pickup:
            state.carried.add(parcel.id)
            event.pickups.append(parcel.id)
    return event


def run_plan(world: World, state: SimState, moves: List[str],
             round_end_tick: int) -> Tuple[List[TickEvent], Optional[dict]]:
    """Execute a plan tick by tick, stopping early on success or capture.

    On capture: courier returns to start, heading resets, and the remaining ticks of
    the round (up to round_end_tick) are forfeited; state.t jumps to round_end_tick.
    Returns (events, capture_info) where capture_info is None if not caught.
    """
    events: List[TickEvent] = []
    capture_info = None
    for move in moves:
        event = step(world, state, move)
        events.append(event)
        if event.result == "CAUGHT":
            state.captures += 1
            forfeited = round_end_tick - state.t
            state.forfeited_ticks += forfeited
            state.pos = world.start
            state.heading = world.initial_heading
            state.t = round_end_tick
            capture_info = {"caught_by": event.caught_by, "at": event.pos_after,
                            "tick": event.t_to, "forfeited": forfeited,
                            "cancelled_moves": len(moves) - len(events)}
            break
        if len(state.delivered) == len(world.parcels):
            break  # success: episode ends immediately at this tick
    return events, capture_info


# ---------------------------------------------------------------- BFS solver


def _parcel_code(carried: Set[int], delivered: Set[int], num_parcels: int) -> int:
    """Base-3 encoding per parcel: 0 = waiting, 1 = carried, 2 = delivered."""
    code = 0
    for parcel_id in range(num_parcels, 0, -1):
        digit = 2 if parcel_id in delivered else (1 if parcel_id in carried else 0)
        code = code * 3 + digit
    return code


def _bfs(world: World, dynamic: bool, t_cap: int) -> Optional[Tuple[int, List[str]]]:
    """BFS over the time-expanded state space (pos, heading?, t mod P, parcel code).

    With dynamic=False, gates are treated as always open and guards are ignored
    (the static lower bound used by the generator's triviality filter).
    Capture states are never entered, so the returned plan is capture-free.
    """
    num_parcels = len(world.parcels)
    goal_code = _parcel_code(set(), set(range(1, num_parcels + 1)), num_parcels)
    period = world.schedule_period() if dynamic else 1
    ego = world.action_mode == "egocentric"
    pickup_of = {p.pickup: p.id for p in world.parcels}
    dropoff_of = {p.dropoff: p.id for p in world.parcels}

    def code_after(pos: Cell, code: int) -> int:
        parcel_id = pickup_of.get(pos)
        if parcel_id is not None and (code // 3 ** (parcel_id - 1)) % 3 == 0:
            code += 3 ** (parcel_id - 1)  # waiting -> carried
        parcel_id = dropoff_of.get(pos)
        if parcel_id is not None and (code // 3 ** (parcel_id - 1)) % 3 == 1:
            code += 3 ** (parcel_id - 1)  # carried -> delivered
        return code

    start_key = (world.start, world.initial_heading if ego else None, 0, 0)
    prev: Dict[tuple, Tuple[Optional[tuple], Optional[str]]] = {start_key: (None, None)}
    frontier = deque([(start_key, 0)])
    while frontier:
        key, t = frontier.popleft()
        if t >= t_cap:
            return None
        pos, heading, _, code = key
        t_to = t + 1
        for move in world.moveset:
            new_pos, new_heading, result, _ = _resolve_move(
                world, pos, heading or "N", move, t_to, ignore_gates=not dynamic)
            if result != "OK":
                continue  # bumping is never useful for the solver; WAIT is always available
            if dynamic and any(p.pos_at(t_to) == new_pos for p in world.patrols):
                continue  # never enter capture states
            new_code = code_after(new_pos, code)
            new_key = (new_pos, new_heading if ego else None, t_to % period, new_code)
            if new_key in prev:
                continue
            prev[new_key] = (key, move)
            if new_code == goal_code:
                moves: List[str] = []
                walk = new_key
                while True:
                    parent, move_taken = prev[walk]
                    if move_taken is None:
                        break
                    moves.append(move_taken)
                    walk = parent
                moves.reverse()
                return t_to, moves
            frontier.append((new_key, t_to))
    return None


def solve_optimal(world: World, t_cap: int = 400) -> Optional[Tuple[int, List[str]]]:
    """Minimum ticks (and one optimal move sequence) to deliver all parcels."""
    return _bfs(world, dynamic=True, t_cap=t_cap)


def solve_static(world: World, t_cap: int = 400) -> Optional[Tuple[int, List[str]]]:
    """Optimum if gates were always open and there were no guards (lower bound)."""
    return _bfs(world, dynamic=False, t_cap=t_cap)


# ---------------------------------------------------------------- rendering


def cell_str(cell: Cell) -> str:
    return f"({cell[0]},{cell[1]})"


def render_map(world: World) -> str:
    glyphs = {}
    for patrol in world.patrols:  # lowest precedence: guards at their t=0 cells
        glyphs.setdefault(patrol.pos_at(0), patrol.id.lower())
    for parcel in world.parcels:
        glyphs[parcel.dropoff] = parcel.dropoff_glyph
        glyphs[parcel.pickup] = str(parcel.id)
    for gate in world.gates:
        glyphs[gate.cell] = gate.id
    glyphs[world.start] = "S"
    header = "   " + "".join(str(col % 10) for col in range(1, world.width + 1))
    lines = [header, "  +" + "-" * world.width + "+"]
    for row in range(1, world.height + 1):
        cells = []
        for col in range(1, world.width + 1):
            cell = (col, row)
            if cell in world.walls:
                cells.append("#")
            else:
                cells.append(glyphs.get(cell, "."))
        lines.append(f"{row:2d}|" + "".join(cells) + "|")
    lines.append("  +" + "-" * world.width + "+")
    return "\n".join(lines)


def render_legend(world: World) -> str:
    lines = [
        "S = your start cell (you are here at t=0)",
        "# = wall (the border is also impassable)",
        ". = open floor",
    ]
    if world.gates:
        gate_ids = ", ".join(g.id for g in world.gates)
        lines.append(f"{gate_ids} = gate cell(s); passable only while open (schedules below)")
    for parcel in world.parcels:
        lines.append(f"{parcel.id} = pickup cell of parcel {parcel.id}; "
                     f"{parcel.dropoff_glyph} = its delivery cell")
    if world.patrols:
        guard_ids = ", ".join(p.id.lower() for p in world.patrols)
        lines.append(f"{guard_ids} = guard(s) drawn at their t=0 cell - THE GUARDS MOVE "
                     f"every tick along the routes listed below")
    return "\n".join(lines)


def render_schedules(world: World) -> str:
    lines = []
    for gate in world.gates:
        phases = sorted(gate.open_phases)
        open_ticks = [t for t in range(2 * gate.period) if gate.is_open(t)]
        closed_ticks = [t for t in range(2 * gate.period) if not gate.is_open(t)]
        lines.append(
            f"Gate {gate.id} at {cell_str(gate.cell)}: open exactly when (t mod {gate.period}) "
            f"is in {{{', '.join(map(str, phases))}}}. "
            f"So it is open at t={','.join(map(str, open_ticks))},... "
            f"and closed at t={','.join(map(str, closed_ticks))},... "
            f"You can only step ONTO it at a tick t+1 where it is open.")
    for patrol in world.patrols:
        n = len(patrol.route)
        route_listing = "; ".join(f"t mod {n}={i}: {cell_str(c)}" for i, c in enumerate(patrol.route))
        lines.append(
            f"Guard {patrol.id}: walks a fixed cycle of length {n}. "
            f"Its position at tick t is determined by (t mod {n}) as follows: {route_listing}. "
            f"This repeats forever.")
    if not lines:
        lines.append("(none)")
    return "\n".join(lines)


def render_parcels(world: World) -> str:
    lines = []
    for parcel in world.parcels:
        lines.append(f"Parcel {parcel.id}: pick it up at {cell_str(parcel.pickup)} "
                     f"(map glyph '{parcel.id}'), deliver it to {cell_str(parcel.dropoff)} "
                     f"(map glyph '{parcel.dropoff_glyph}'). "
                     f"Pickup and delivery happen automatically when you end a tick on the cell.")
    return "\n".join(lines)


def _tick_line(event: TickEvent, world: World, mode: str) -> str:
    extras = ""
    if event.deliveries:
        extras += "".join(f" DELIVERED parcel {i}!" for i in event.deliveries)
    if event.pickups:
        extras += "".join(f" PICKED UP parcel {i}." for i in event.pickups)
    if mode == "rich":
        if event.result == "OK":
            body = f"OK, now at {cell_str(event.pos_after)}"
        elif event.result == "BUMP_GATE":
            body = (f"BUMP (gate {event.bump_gate} is closed at t={event.t_to}), "
                    f"still at {cell_str(event.pos_after)}")
        elif event.result in ("BUMP_WALL", "BUMP_BORDER"):
            cause = "a wall" if event.result == "BUMP_WALL" else "the border"
            body = f"BUMP (you ran into {cause}), still at {cell_str(event.pos_after)}"
        else:  # CAUGHT
            body = (f"CAUGHT by guard {event.caught_by} at {cell_str(event.pos_after)}! "
                    f"Returned to start {cell_str(world.start)}")
    else:  # minimal
        if event.result == "OK":
            body = "OK"
        elif event.bumped:
            body = "BUMP"
        else:
            body = "CAUGHT! Returned to start"
    return f"t={event.t_to}: {event.move} -> {body}.{extras}"


def format_round_feedback(events: List[TickEvent], capture_info: Optional[dict],
                          state: SimState, world: World, mode: str, round_idx: int,
                          start_tick: int, round_end_tick: int, tick_budget: int,
                          plan_length: int, rounds_left: int) -> str:
    """The GM message sent back to the player after a committed plan was executed."""
    lines = [f"ROUND {round_idx + 1} RESULT (ticks {start_tick} -> {state.t}):"]
    for event in events:
        lines.append(_tick_line(event, world, mode))
    if capture_info is not None:
        lines.append(f"Capture penalty: the remaining {capture_info['cancelled_moves']} move(s) "
                     f"of your plan were cancelled and the round's leftover ticks were forfeited; "
                     f"the clock jumped to t={round_end_tick}.")
    delivered = sorted(state.delivered)
    if mode == "rich":
        carrying = sorted(state.carried)
        facing = f", facing {state.heading}" if world.action_mode == "egocentric" else ""
        status = (f"STATUS: tick {state.t} of {tick_budget}. You are at {cell_str(state.pos)}{facing}. "
                  f"Carrying: {_parcel_list(carrying)}. Delivered: {_parcel_list(delivered)}. "
                  f"Rounds left: {rounds_left}.")
    else:
        status = (f"STATUS: tick {state.t} of {tick_budget}. "
                  f"Delivered {len(delivered)} of {len(world.parcels)} parcel(s). "
                  f"Rounds left: {rounds_left}. "
                  f"(You are never told your position - track it yourself.)")
    lines.append(status)
    lines.append(f"Respond now in the required format: a POSITION line predicting your cell "
                 f"after your next plan, then a PLAN line with exactly {plan_length} moves.")
    return "\n".join(lines)


def _parcel_list(ids: List[int]) -> str:
    if not ids:
        return "nothing"
    return ", ".join(f"parcel {i}" for i in ids)
