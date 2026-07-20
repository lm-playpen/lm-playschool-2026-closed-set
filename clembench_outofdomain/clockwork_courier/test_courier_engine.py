"""Unit tests for the Clockwork Courier engine and instance generator.

Run from the repo root:  .venv/bin/python -m pytest clockwork_courier/ -q
"""

import random

import pytest

import courier_engine as eng
import instancegenerator as gen


def corridor_world(width=4, gates=(), patrols=(), parcels=None, action_mode="cardinal"):
    """A 1-row corridor: start at (1,1), default parcel pickup (3,1) -> dropoff (4,1)."""
    if parcels is None:
        parcels = (eng.Parcel(1, (3, 1), (4, 1)),)
    return eng.World(width=width, height=1, walls=frozenset(), start=(1, 1),
                     gates=tuple(gates), patrols=tuple(patrols), parcels=tuple(parcels),
                     action_mode=action_mode, initial_heading="N")


# ---------------------------------------------------------------- gates


def test_gate_phase_math():
    gate = eng.Gate("A", (2, 1), period=4, open_phases=frozenset({0, 1}))
    assert [t for t in range(8) if gate.is_open(t)] == [0, 1, 4, 5]


def test_gate_arrival_time_rule():
    # gate at (2,1) open only at odd ticks; moving onto it at t->t+1 needs open at t+1
    gate = eng.Gate("A", (2, 1), period=2, open_phases=frozenset({1}))
    world = corridor_world(gates=(gate,))
    state = eng.SimState.initial(world)
    event = eng.step(world, state, "E")  # arrives at t=1, open -> OK
    assert event.result == "OK" and state.pos == (2, 1)

    state = eng.SimState.initial(world)
    state.t = 1  # moving now arrives at t=2, closed -> BUMP
    event = eng.step(world, state, "E")
    assert event.result == "BUMP_GATE" and event.bump_gate == "A"
    assert state.pos == (1, 1) and state.t == 2 and state.bumps == 1


def test_standing_on_gate_when_it_closes_is_safe():
    gate = eng.Gate("A", (2, 1), period=2, open_phases=frozenset({1}))
    world = corridor_world(gates=(gate,))
    state = eng.SimState.initial(world)
    eng.step(world, state, "E")  # on the gate at t=1
    event = eng.step(world, state, "E")  # leaving while the gate is closed at t=2: fine
    assert event.result == "OK" and state.pos == (3, 1)


# ---------------------------------------------------------------- bumps


def test_bump_wall_and_border():
    world = eng.World(width=3, height=3, walls=frozenset({(2, 2)}), start=(1, 2),
                      gates=(), patrols=(), parcels=(eng.Parcel(1, (3, 1), (3, 3)),))
    state = eng.SimState.initial(world)
    event = eng.step(world, state, "E")
    assert event.result == "BUMP_WALL" and state.pos == (1, 2)
    event = eng.step(world, state, "W")
    assert event.result == "BUMP_BORDER" and state.pos == (1, 2)
    assert state.bumps == 2 and state.t == 2  # bumps still consume ticks


# ---------------------------------------------------------------- guards


def test_patrol_cycling_and_end_of_tick_capture():
    patrol = eng.Patrol("P", ((3, 1), (4, 1)))  # at (3,1) on even t, (4,1) on odd t
    world = corridor_world(width=5, patrols=(patrol,),
                           parcels=(eng.Parcel(1, (5, 1), (1, 1)),))
    state = eng.SimState(pos=(2, 1), heading="N")
    event = eng.step(world, state, "E")  # to (3,1) at t=1; guard then at (4,1): safe
    assert event.result == "OK"
    event = eng.step(world, state, "E")  # to (4,1) at t=2; guard moves to (3,1): SWAP, safe
    assert event.result == "OK" and state.pos == (4, 1)
    event = eng.step(world, state, "WAIT")  # t=3: guard arrives at (4,1) -> CAUGHT
    assert event.result == "CAUGHT" and event.caught_by == "P"


def test_capture_reset_and_forfeit_in_run_plan():
    patrol = eng.Patrol("P", ((4, 1), (3, 1)))  # at (3,1) on odd t
    world = corridor_world(width=5, patrols=(patrol,),
                           parcels=(eng.Parcel(1, (5, 1), (1, 1)),))
    state = eng.SimState(pos=(2, 1), heading="N")
    events, capture = eng.run_plan(world, state, ["E", "E", "E", "E"], round_end_tick=4)
    # first move arrives at (3,1) at t=1 where the guard also arrives -> caught immediately
    assert len(events) == 1 and events[0].result == "CAUGHT"
    assert capture == {"caught_by": "P", "at": (3, 1), "tick": 1,
                       "forfeited": 3, "cancelled_moves": 3}
    assert state.pos == (1, 1) and state.t == 4  # reset to start, clock at round end
    assert state.captures == 1 and state.forfeited_ticks == 3


def test_no_pickup_on_capture_tick():
    patrol = eng.Patrol("P", ((4, 1), (3, 1)))  # at (3,1) on odd t
    world = corridor_world(width=5, patrols=(patrol,),
                           parcels=(eng.Parcel(1, (3, 1), (5, 1)),))  # pickup on capture cell
    state = eng.SimState(pos=(2, 1), heading="N")
    event = eng.step(world, state, "E")  # arrive (3,1) at t=1 together with the guard
    assert event.result == "CAUGHT" and event.pickups == []
    assert state.carried == set()


# ---------------------------------------------------------------- parcels


def test_automatic_pickup_and_delivery_and_early_stop():
    world = corridor_world()
    state = eng.SimState.initial(world)
    events, capture = eng.run_plan(world, state, ["E", "E", "E", "WAIT", "WAIT"],
                                   round_end_tick=5)
    assert capture is None
    assert [e.result for e in events] == ["OK", "OK", "OK"]  # stops early on success
    assert events[1].pickups == [1] and events[2].deliveries == [1]
    assert state.delivered == {1} and state.carried == set()
    assert state.t == 3  # success tick, the padded WAITs were never executed


# ---------------------------------------------------------------- egocentric mode


def test_ego_rotation_and_forward():
    world = corridor_world(action_mode="egocentric")
    state = eng.SimState.initial(world)  # facing N
    event = eng.step(world, state, "F")  # forward = N = off the border
    assert event.result == "BUMP_BORDER"
    event = eng.step(world, state, "R")  # rotate in place, consumes the tick
    assert event.result == "OK" and state.heading == "E" and state.pos == (1, 1)
    event = eng.step(world, state, "F")
    assert event.result == "OK" and state.pos == (2, 1)
    event = eng.step(world, state, "L")
    assert state.heading == "N"
    assert state.t == 4


# ---------------------------------------------------------------- BFS solver


def test_solver_forced_wait_through_gate():
    # gate open at phases {2,3} of period 4: direct E at t=0 arrives t=1 (closed),
    # so the optimum is WAIT once: WAIT, E(t=2), E(t=3, pickup), E(t=4, deliver)
    gate = eng.Gate("A", (2, 1), period=4, open_phases=frozenset({2, 3}))
    world = corridor_world(gates=(gate,))
    optimal_ticks, moves = eng.solve_optimal(world)
    assert optimal_ticks == 4
    static_ticks, _ = eng.solve_static(world)
    assert static_ticks == 3

    # replaying the optimal moves reproduces the optimum exactly
    state = eng.SimState.initial(world)
    eng.run_plan(world, state, moves, round_end_tick=len(moves))
    assert state.delivered == {1} and state.t == optimal_ticks and state.bumps == 0


def test_solver_ego_pays_rotation_cost():
    gate = eng.Gate("A", (2, 1), period=4, open_phases=frozenset({2, 3}))
    world = corridor_world(gates=(gate,), action_mode="egocentric")
    optimal_ticks, moves = eng.solve_optimal(world)
    assert optimal_ticks == 4  # R replaces the WAIT: R, F(t=2), F, F
    state = eng.SimState.initial(world)
    eng.run_plan(world, state, moves, round_end_tick=len(moves))
    assert state.delivered == {1} and state.t == 4


def test_solver_avoids_capture():
    # single corridor blocked by a guard oscillating on it: passable only by timing
    patrol = eng.Patrol("P", ((3, 1), (2, 1)))
    world = corridor_world(width=5, patrols=(patrol,),
                           parcels=(eng.Parcel(1, (4, 1), (5, 1)),))
    solved = eng.solve_optimal(world)
    assert solved is not None
    optimal_ticks, moves = solved
    state = eng.SimState.initial(world)
    _, capture = eng.run_plan(world, state, moves, round_end_tick=len(moves))
    assert capture is None and state.delivered == {1} and state.t == optimal_ticks


def test_solver_unsolvable_returns_none():
    walls = frozenset({(2, 3), (3, 2)})  # pickup (3,3) sealed in the corner
    world = eng.World(width=3, height=3, walls=walls, start=(1, 1), gates=(), patrols=(),
                      parcels=(eng.Parcel(1, (3, 3), (1, 3)),))
    assert eng.solve_optimal(world) is None


# ---------------------------------------------------------------- serialization


def test_world_instance_round_trip():
    gate = eng.Gate("A", (2, 1), period=4, open_phases=frozenset({2, 3}))
    patrol = eng.Patrol("P", ((3, 1), (4, 1)))
    world = corridor_world(width=5, gates=(gate,), patrols=(patrol,))
    rebuilt = eng.World.from_instance(world.to_instance_dict())
    assert rebuilt.to_instance_dict() == world.to_instance_dict()
    assert rebuilt.gates[0].is_open(2) and not rebuilt.gates[0].is_open(0)
    assert rebuilt.patrols[0].pos_at(3) == (4, 1)


# ---------------------------------------------------------------- generator


@pytest.mark.parametrize("tier", gen.TIERS, ids=[t["name"] for t in gen.TIERS])
def test_generator_produces_valid_instances(tier):
    random.seed(5)
    for _ in range(2):
        instance = gen.generate_instance(tier)
        world = eng.World.from_instance(instance)
        assert world.schedule_period() <= gen.MAX_SCHEDULE_LCM
        assert instance["tick_budget"] % instance["plan_length"] == 0
        assert instance["max_rounds"] * instance["plan_length"] == instance["tick_budget"]
        assert instance["optimal_ticks"] >= 2 * instance["plan_length"]
        assert instance["tick_budget"] >= instance["optimal_ticks"]
        # special cells are pairwise distinct and off gate cells
        special = [world.start] + [g.cell for g in world.gates] \
            + [p.pickup for p in world.parcels] + [p.dropoff for p in world.parcels]
        assert len(special) == len(set(special))
        # guard routes avoid gates and start
        for patrol in world.patrols:
            assert world.start not in patrol.route
            assert not set(patrol.route) & {g.cell for g in world.gates}
        # stored optimum is correct and replayable
        optimal_ticks, moves = eng.solve_optimal(world)
        assert optimal_ticks == instance["optimal_ticks"]
        state = eng.SimState.initial(world)
        _, capture = eng.run_plan(world, state, moves, round_end_tick=len(moves))
        assert capture is None and len(state.delivered) == len(world.parcels)
        assert state.t == optimal_ticks
        # the dynamics-ignoring plan must NOT solve the instance unimpeded
        assert not gen.is_trivially_easy(world, instance["static_optimal_ticks"],
                                         eng.solve_static(world)[1])


def test_generator_is_deterministic():
    random.seed(11)
    first = gen.generate_instance(gen.TIERS[0])
    random.seed(11)
    second = gen.generate_instance(gen.TIERS[0])
    assert first == second
