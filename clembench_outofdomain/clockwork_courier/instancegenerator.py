"""Instance generator for Clockwork Courier.

Procedurally generates worlds per experiment tier by rejection sampling: walls are
scattered and made connected, gates are placed on corridor cells with periodic
schedules, guards get ping-pong routes, parcels get distinct pickup/delivery cells.
Every accepted instance is verified solvable by the engine's time-expanded BFS, and
instances that a dynamics-ignoring "static" optimal plan would solve unimpeded are
rejected (the clockwork must matter). Fully reproducible from the seed.

Run from this directory:  python3 instancegenerator.py
"""

import os
import random
import string
from math import ceil

from clemcore.clemgame import GameInstanceGenerator

import courier_engine as eng

DEFAULT_SEED = 73
INSTANCES_PER_EXPERIMENT = 10
MAX_ATTEMPTS_PER_INSTANCE = 2000
MAX_SCHEDULE_LCM = 24

GATE_PERIODS = [2, 4, 6]
PATROL_PATH_LENGTHS = [3, 4, 5]  # ping-pong cycle lengths 4, 6, 8

TIERS = [
    dict(name="standard", width=9, height=9, wall_density=0.18, num_gates=2, num_patrols=2,
         num_parcels=2, action_mode="cardinal", plan_length=5, feedback_mode="rich",
         slack=1.7, tick_cap=50, parcels_off_routes=False, template="initial_cardinal"),
    dict(name="deadreckon", width=9, height=9, wall_density=0.18, num_gates=2, num_patrols=2,
         num_parcels=2, action_mode="cardinal", plan_length=5, feedback_mode="minimal",
         slack=1.8, tick_cap=50, parcels_off_routes=False, template="initial_cardinal"),
    dict(name="egocentric", width=8, height=8, wall_density=0.15, num_gates=1, num_patrols=2,
         num_parcels=2, action_mode="egocentric", plan_length=6, feedback_mode="rich",
         slack=1.8, tick_cap=48, parcels_off_routes=False, template="initial_egocentric"),
]


def neighbors(cell):
    x, y = cell
    return [(x, y - 1), (x, y + 1), (x - 1, y), (x + 1, y)]


def floor_cells(width, height, walls):
    return [(x, y) for x in range(1, width + 1) for y in range(1, height + 1)
            if (x, y) not in walls]


def connected_component(start, floors):
    floors = set(floors)
    seen = {start}
    queue = [start]
    while queue:
        cell = queue.pop()
        for nbr in neighbors(cell):
            if nbr in floors and nbr not in seen:
                seen.add(nbr)
                queue.append(nbr)
    return seen


def sample_connected_walls(width, height, density):
    """Scatter walls, then knock down walls adjacent to the main floor component
    until all floor cells are connected. Returns a set of wall cells or None."""
    cells = [(x, y) for x in range(1, width + 1) for y in range(1, height + 1)]
    walls = {cell for cell in cells if random.random() < density}
    for _ in range(width * height):
        floors = floor_cells(width, height, walls)
        if len(floors) < width * height // 2:
            return None
        component = connected_component(floors[0], floors)
        if len(component) == len(floors):
            return walls
        candidates = sorted(wall for wall in walls
                            if any(nbr in component for nbr in neighbors(wall)))
        if not candidates:
            return None
        walls.discard(random.choice(candidates))
    return None


def corridor_cells(width, height, walls):
    """Floor cells with exactly two floor neighbours that lie on opposite sides."""
    result = []
    for cell in floor_cells(width, height, walls):
        x, y = cell
        open_nbrs = [nbr for nbr in neighbors(cell)
                     if 1 <= nbr[0] <= width and 1 <= nbr[1] <= height and nbr not in walls]
        if len(open_nbrs) != 2:
            continue
        (x1, y1), (x2, y2) = open_nbrs
        if x1 == x2 == x or y1 == y2 == y:
            result.append(cell)
    return sorted(result)


def sample_gate(gate_id, cell):
    period = random.choice(GATE_PERIODS)
    offset = random.randrange(period)
    open_phases = frozenset((offset + i) % period for i in range(period // 2))
    return eng.Gate(id=gate_id, cell=cell, period=period, open_phases=open_phases)


def sample_patrol_route(width, height, walls, forbidden):
    """Random simple path of 3-5 floor cells avoiding `forbidden`, as a ping-pong cycle."""
    floors = [cell for cell in floor_cells(width, height, walls) if cell not in forbidden]
    if not floors:
        return None
    target_length = random.choice(PATROL_PATH_LENGTHS)
    for _ in range(50):
        path = [random.choice(sorted(floors))]
        while len(path) < target_length:
            options = sorted(nbr for nbr in neighbors(path[-1])
                             if nbr in set(floors) and nbr not in path)
            if not options:
                break
            path.append(random.choice(options))
        if len(path) == target_length:
            return tuple(path) + tuple(reversed(path[1:-1]))
    return None


def try_generate_world(tier):
    walls = sample_connected_walls(tier["width"], tier["height"], tier["wall_density"])
    if walls is None:
        return None
    width, height = tier["width"], tier["height"]

    corridors = corridor_cells(width, height, walls)
    if len(corridors) < tier["num_gates"]:
        return None
    gate_cells = random.sample(corridors, tier["num_gates"])
    gates = tuple(sample_gate(string.ascii_uppercase[i], cell)
                  for i, cell in enumerate(gate_cells))

    occupied = set(gate_cells)
    open_floor = sorted(cell for cell in floor_cells(width, height, walls)
                        if cell not in occupied)
    if not open_floor:
        return None
    start = random.choice(open_floor)
    occupied.add(start)

    patrols = []
    for i in range(tier["num_patrols"]):
        route = sample_patrol_route(width, height, walls, forbidden=set(gate_cells) | {start})
        if route is None:
            return None
        patrols.append(eng.Patrol(id=string.ascii_uppercase[15 + i], route=route))  # P, Q
    route_cells = {cell for patrol in patrols for cell in patrol.route}

    parcel_forbidden = set(occupied)
    if tier["parcels_off_routes"]:
        parcel_forbidden |= route_cells
    parcel_candidates = sorted(cell for cell in floor_cells(width, height, walls)
                               if cell not in parcel_forbidden)
    if len(parcel_candidates) < 2 * tier["num_parcels"]:
        return None
    chosen = random.sample(parcel_candidates, 2 * tier["num_parcels"])
    parcels = tuple(eng.Parcel(id=i + 1, pickup=chosen[2 * i], dropoff=chosen[2 * i + 1])
                    for i in range(tier["num_parcels"]))

    world = eng.World(width=width, height=height, walls=frozenset(walls), start=start,
                      gates=gates, patrols=tuple(patrols), parcels=parcels,
                      action_mode=tier["action_mode"], initial_heading="N")
    if world.schedule_period() > MAX_SCHEDULE_LCM:
        return None
    return world


def is_trivially_easy(world, static_ticks, static_moves):
    """True iff the dynamics-ignoring optimal plan also works unimpeded dynamically."""
    sim = eng.SimState.initial(world)
    _, capture = eng.run_plan(world, sim, list(static_moves), round_end_tick=len(static_moves))
    return (capture is None and len(sim.delivered) == len(world.parcels)
            and sim.t == static_ticks)


def generate_instance(tier):
    """Rejection-sample one valid, non-trivial instance for the tier. Returns a dict."""
    plan_length = tier["plan_length"]
    for _ in range(MAX_ATTEMPTS_PER_INSTANCE):
        world = try_generate_world(tier)
        if world is None:
            continue
        solved = eng.solve_optimal(world)
        if solved is None:
            continue
        optimal_ticks, _ = solved
        if optimal_ticks < 2 * plan_length:
            continue  # too short to be interesting
        tick_budget = ceil(tier["slack"] * optimal_ticks / plan_length) * plan_length
        if tick_budget > tier["tick_cap"]:
            continue
        static = eng.solve_static(world)
        assert static is not None, "static relaxation must be solvable"
        static_ticks, static_moves = static
        if is_trivially_easy(world, static_ticks, static_moves):
            continue
        instance = world.to_instance_dict()
        instance.update({
            "plan_length": plan_length,
            "tick_budget": tick_budget,
            "max_rounds": tick_budget // plan_length,
            "optimal_ticks": optimal_ticks,
            "static_optimal_ticks": static_ticks,
            # pre-rendered views, for human inspection of this file only;
            # the game master re-renders identically from the structured fields
            "map_render": eng.render_map(world),
            "schedules_text": eng.render_schedules(world),
            "parcels_text": eng.render_parcels(world),
        })
        return instance
    raise RuntimeError(f"could not generate a valid instance for tier '{tier['name']}' "
                       f"within {MAX_ATTEMPTS_PER_INSTANCE} attempts")


class ClockworkCourierInstanceGenerator(GameInstanceGenerator):

    def __init__(self):
        super().__init__(os.path.dirname(os.path.abspath(__file__)))

    def on_generate(self, seed: int, **kwargs):
        for tier in TIERS:
            experiment = self.add_experiment(tier["name"])
            experiment["feedback_mode"] = tier["feedback_mode"]
            experiment["action_mode"] = tier["action_mode"]
            experiment["plan_length"] = tier["plan_length"]
            experiment["initial_prompt"] = self.load_template(
                f"resources/initial_prompts/{tier['template']}")
            for game_id in range(INSTANCES_PER_EXPERIMENT):
                instance_data = generate_instance(tier)
                game_instance = self.add_game_instance(experiment, game_id)
                game_instance.update(instance_data)


if __name__ == "__main__":
    ClockworkCourierInstanceGenerator().generate(seed=DEFAULT_SEED)
