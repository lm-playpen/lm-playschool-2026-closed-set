"""Clockwork Courier: a single-player, dynamic-world navigation game.

The full map, the gate schedules and the guard routes are disclosed upfront; nothing
is hidden and nothing is random. The challenge is forward simulation through time:
the player commits to plans of exactly L moves per round, must time gate openings,
avoid guards walking published routes, and predict its own position after each plan
(a state-tracking probe the GM measures but never comments on).
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

from clemcore.backends import Model
from clemcore.clemgame import (GameBenchmark, GameScorer, GameSpec, ParseError, Player)
from clemcore.clemgame.master import DialogueGameMaster, GameState, Outcome
from clemcore.clemgame.metrics import METRIC_ABORTED, METRIC_LOSE, METRIC_SUCCESS, BENCH_SCORE

import courier_engine as eng

logger = logging.getLogger(__name__)

GAME_NAME = "clockwork_courier"

POSITION_RE = re.compile(
    r"^[ \t]*POSITION:\s*\(?\s*(\d{1,2})\s*,\s*(\d{1,2})\s*\)?\s*(?:FACING\s+([NSEW]))?[ \t]*$",
    re.IGNORECASE | re.MULTILINE)
PLAN_RE = re.compile(r"^[ \t]*PLAN:[ \t]*(.+?)[ \t]*$", re.IGNORECASE | re.MULTILINE)

MAX_REPROMPTS_PER_ROUND = 1
MAX_REPROMPTS_PER_EPISODE = 3


@dataclass
class CourierGameState(GameState):
    world: eng.World = None
    sim: eng.SimState = None
    plan_length: int = 0
    tick_budget: int = 0
    max_rounds: int = 0
    feedback_mode: str = "rich"
    optimal_ticks: int = 0
    round_committed: bool = False
    reprompts_round: int = 0
    reprompts_total: int = 0
    pending: Optional[tuple] = None  # (predicted_pos, predicted_heading, moves)
    predictions_correct: int = 0
    predictions_total: int = 0

    def __post_init__(self):
        super().__init__()


class Courier(Player):
    """The single player. The custom response implements a deterministic oracle that
    plays the precomputed optimal route (used by mock runs for end-to-end testing).
    On its second call it deliberately sends one malformed plan to exercise the
    GM's re-prompt path, then resumes the oracle."""

    def __init__(self, model: Model, world: eng.World, plan_length: int):
        super().__init__(model, game_role="Courier")
        self._world = world
        self._plan_length = plan_length
        self._oracle_moves: Optional[List[str]] = None
        self._oracle_sim: Optional[eng.SimState] = None
        self._calls = 0

    def _custom_response(self, context: Dict) -> str:
        self._calls += 1
        if self._oracle_moves is None:
            solved = eng.solve_optimal(self._world)
            assert solved is not None, "mock oracle requires a solvable world"
            self._oracle_moves = solved[1]
            self._oracle_sim = eng.SimState.initial(self._world)
        if self._calls == 2:  # one malformed plan to exercise the re-prompt path
            too_long = " ".join(["WAIT"] * (self._plan_length + 1))
            return f"THOUGHTS: probing the referee.\nPOSITION: (1,1)\nPLAN: {too_long}"
        chunk = self._oracle_moves[self._oracle_sim.t: self._oracle_sim.t + self._plan_length]
        chunk += ["WAIT"] * (self._plan_length - len(chunk))
        preview = self._oracle_sim.clone()
        eng.run_plan(self._world, preview, chunk, round_end_tick=preview.t + self._plan_length)
        self._oracle_sim = preview
        position = eng.cell_str(preview.pos)
        if self._world.action_mode == "egocentric":
            position += f" FACING {preview.heading}"
        return (f"THOUGHTS: following the precomputed optimal route.\n"
                f"POSITION: {position}\nPLAN: {' '.join(chunk)}")


class ClockworkCourier(DialogueGameMaster):

    def __init__(self, game_spec: GameSpec, experiment: Dict, player_models: List[Model]):
        super().__init__(game_spec, experiment, player_models)

    def _on_setup(self, **game_instance):
        self.game_instance = game_instance
        world = eng.World.from_instance(game_instance)
        self.state = CourierGameState(
            world=world,
            sim=eng.SimState.initial(world),
            plan_length=game_instance["plan_length"],
            tick_budget=game_instance["tick_budget"],
            max_rounds=game_instance["max_rounds"],
            feedback_mode=self.experiment["feedback_mode"],
            optimal_ticks=game_instance["optimal_ticks"],
        )
        self.courier = Courier(self.player_models[0], world, self.state.plan_length)
        self.add_player(self.courier, initial_context=self._build_initial_prompt())

    def _build_initial_prompt(self) -> str:
        world = self.state.world
        if self.state.feedback_mode == "rich":
            feedback_note = ("After each plan you receive a per-tick log of what happened, "
                             "including your resulting position.")
        else:
            feedback_note = ("After each plan you receive only a per-tick log of "
                             "OK/BUMP/CAUGHT/PICKED UP/DELIVERED. You are NEVER told where "
                             "you are or why you bumped - track your position yourself.")
        prompt = self.experiment["initial_prompt"]
        replacements = {
            "$MAP$": eng.render_map(world),
            "$LEGEND$": eng.render_legend(world),
            "$SCHEDULES$": eng.render_schedules(world),
            "$PARCELS$": eng.render_parcels(world),
            "$START$": eng.cell_str(world.start),
            "$HEADING$": world.initial_heading,
            "$TICK_BUDGET$": str(self.state.tick_budget),
            "$PLAN_LENGTH$": str(self.state.plan_length),
            "$MAX_ROUNDS$": str(self.state.max_rounds),
            "$FEEDBACK_NOTE$": feedback_note,
        }
        for placeholder, value in replacements.items():
            prompt = prompt.replace(placeholder, value)
        return prompt

    def _parse_response(self, player: Player, response: str) -> str:
        state = self.state
        position_matches = list(POSITION_RE.finditer(response))
        if not position_matches:
            raise ParseError("missing or malformed POSITION line", response=response,
                             key="missing_position")
        plan_matches = list(PLAN_RE.finditer(response))
        if not plan_matches:
            raise ParseError("missing PLAN line", response=response, key="missing_plan")
        position_match = position_matches[-1]
        predicted_pos = (int(position_match.group(1)), int(position_match.group(2)))
        predicted_heading = position_match.group(3).upper() if position_match.group(3) else None
        if state.world.action_mode == "egocentric" and predicted_heading is None:
            raise ParseError("the POSITION line must include 'FACING <N|S|E|W>'",
                             response=response, key="missing_facing")
        tokens = [token.upper() for token in re.split(r"[\s,;]+", plan_matches[-1].group(1))
                  if token]
        moveset = state.world.moveset
        unknown = [token for token in tokens if token not in moveset]
        if unknown:
            raise ParseError(f"unknown move token(s): {', '.join(unknown[:5])} "
                             f"(allowed: {', '.join(moveset)})",
                             response=response, key="unknown_move")
        if len(tokens) != state.plan_length:
            raise ParseError(f"the PLAN must contain exactly {state.plan_length} moves, "
                             f"but {len(tokens)} were given",
                             response=response, key="wrong_plan_length")
        state.pending = (predicted_pos, predicted_heading, tokens)
        canonical = f"POSITION: {eng.cell_str(predicted_pos)}"
        if predicted_heading:
            canonical += f" FACING {predicted_heading}"
        return canonical + f"\nPLAN: {' '.join(tokens)}"

    def _advance_game(self, player: Player, parsed_response: str):
        state = self.state
        predicted_pos, predicted_heading, moves = state.pending
        round_idx = self.current_round
        start_tick = state.sim.t
        round_end_tick = start_tick + state.plan_length
        events, capture = eng.run_plan(state.world, state.sim, moves, round_end_tick)

        position_correct = predicted_pos == state.sim.pos
        heading_applicable = state.world.action_mode == "egocentric"
        heading_correct = (predicted_heading == state.sim.heading) if heading_applicable else None
        prediction_correct = position_correct and (heading_correct is not False)
        state.predictions_total += 1
        state.predictions_correct += int(prediction_correct)

        self.log_to_self("round_result", {
            "round": round_idx,
            "start_tick": start_tick,
            "end_tick": state.sim.t,
            "plan": moves,
            "events": [{"t": e.t_to, "move": e.move, "result": e.result,
                        "pos": list(e.pos_after), "heading": e.heading_after,
                        "pickups": e.pickups, "deliveries": e.deliveries,
                        "caught_by": e.caught_by, "gate": e.bump_gate} for e in events],
            "predicted_pos": list(predicted_pos),
            "predicted_heading": predicted_heading,
            "actual_pos": list(state.sim.pos),
            "actual_heading": state.sim.heading,
            "prediction_correct": int(prediction_correct),
            "bumps": sum(1 for e in events if e.bumped),
            "caught": int(capture is not None),
            "forfeited_ticks": capture["forfeited"] if capture else 0,
            "deliveries_this_round": sum(len(e.deliveries) for e in events),
            "delivered_total": len(state.sim.delivered),
            "carrying": sorted(state.sim.carried),
        })
        state.round_committed = True

        if len(state.sim.delivered) == len(state.world.parcels):
            self.log_to_self("all parcels delivered", state.sim.t)
            state.succeed()
        elif round_idx + 1 >= state.max_rounds:
            self.log_to_self("tick budget exhausted", state.sim.t)
            state.failed()
        else:
            rounds_left = state.max_rounds - (round_idx + 1)
            feedback = eng.format_round_feedback(
                events, capture, state.sim, state.world, state.feedback_mode,
                round_idx, start_tick, round_end_tick, state.tick_budget,
                state.plan_length, rounds_left)
            self.set_context_for(player, feedback)

    def _on_parse_error(self, error: ParseError):
        state = self.state
        state.reprompts_round += 1
        state.reprompts_total += 1
        if state.reprompts_round > MAX_REPROMPTS_PER_ROUND \
                or state.reprompts_total > MAX_REPROMPTS_PER_EPISODE:
            self.log_to_self("invalid format", error.reason)
            state.abort()
            return
        self.log_to_self("reprompt", error.reason)
        moveset = ", ".join(state.world.moveset)
        facing = " FACING <N|S|E|W>" if state.world.action_mode == "egocentric" else ""
        self.set_context_for(self.current_player, (
            f"Your last response could not be processed: {error.reason}.\n"
            f"Answer again, using exactly this format (and nothing after the PLAN line):\n"
            f"THOUGHTS: <your reasoning>\n"
            f"POSITION: (x,y){facing}\n"
            f"PLAN: <exactly {state.plan_length} moves from {{{moveset}}}, "
            f"separated by spaces>"))

    def _on_before_round(self):
        self.state.round_committed = False
        self.state.reprompts_round = 0

    def _start_next_round(self) -> bool:
        return self.state.round_committed

    def _does_game_proceed(self) -> bool:
        # defensive round cap; outcomes are normally set in _advance_game/_on_parse_error
        return not self.state.outcome.is_terminal and self.current_round < self.state.max_rounds

    def _on_after_game(self):
        state = self.state
        self.log_key(METRIC_ABORTED, int(state.outcome == Outcome.ABORTED))
        self.log_key(METRIC_LOSE, int(state.outcome == Outcome.FAILURE))
        self.log_key(METRIC_SUCCESS, int(state.outcome == Outcome.SUCCESS))
        self.log_key("episode_result", {
            "outcome": state.outcome.value,
            "delivered": len(state.sim.delivered),
            "num_parcels": len(state.world.parcels),
            "used_ticks": state.sim.t,
            "tick_budget": state.tick_budget,
            "optimal_ticks": state.optimal_ticks,
            "rounds_played": state.predictions_total,
            "bumps": state.sim.bumps,
            "captures": state.sim.captures,
            "forfeited_ticks": state.sim.forfeited_ticks,
            "predictions_correct": state.predictions_correct,
            "predictions_total": state.predictions_total,
            "reprompts": state.reprompts_total,
        })


class ClockworkCourierScorer(GameScorer):
    """All scores are computed from the interactions log (and the instance data);
    fully programmatic, no judge of any kind."""

    DIAGNOSTIC_SCORES = ("Delivery Rate", "Ticks Used", "Optimal Ticks", "Efficiency",
                         "Prediction Accuracy", "Bump Count", "Capture Count",
                         "Forfeited Ticks")

    def __init__(self, game_name: str, experiment: Dict, game_instance: Dict):
        super().__init__(game_name, experiment, game_instance)

    def compute_round_score(self, round_idx, round_events: List[Dict]) -> None:
        record = None
        for event in round_events:
            if event["action"]["type"] == "round_result":
                record = event["action"]["content"]
        if record is None:  # round without a committed plan (abort round)
            return
        self.log_round_score(round_idx, "Prediction Correct", record["prediction_correct"])
        self.log_round_score(round_idx, "Bumps", record["bumps"])
        self.log_round_score(round_idx, "Caught", record["caught"])
        self.log_round_score(round_idx, "Deliveries", record["deliveries_this_round"])
        self.log_round_score(round_idx, "Wasted Ticks",
                             record["bumps"] + record["forfeited_ticks"])

    def compute_episode_scores(self, interactions: Dict) -> None:
        episode = interactions["episode_result"]
        if interactions[METRIC_ABORTED]:
            self.log_episode_score(BENCH_SCORE, np.nan)
            for score_name in self.DIAGNOSTIC_SCORES:
                self.log_episode_score(score_name, np.nan)
            return
        success = bool(interactions[METRIC_SUCCESS])
        delivery_rate = episode["delivered"] / episode["num_parcels"]
        efficiency = min(1.0, episode["optimal_ticks"] / episode["used_ticks"]) if success else 0.0
        self.log_episode_score(BENCH_SCORE, 100 * (0.7 * delivery_rate + 0.3 * efficiency))
        self.log_episode_score("Delivery Rate", delivery_rate)
        self.log_episode_score("Ticks Used", episode["used_ticks"])
        self.log_episode_score("Optimal Ticks", episode["optimal_ticks"])
        self.log_episode_score("Efficiency", efficiency if success else np.nan)
        predictions_total = episode["predictions_total"]
        self.log_episode_score("Prediction Accuracy",
                               episode["predictions_correct"] / predictions_total
                               if predictions_total else np.nan)
        self.log_episode_score("Bump Count", episode["bumps"])
        self.log_episode_score("Capture Count", episode["captures"])
        self.log_episode_score("Forfeited Ticks", episode["forfeited_ticks"])


class ClockworkCourierBenchmark(GameBenchmark):

    def __init__(self, game_spec: GameSpec):
        super().__init__(game_spec)

    def create_game_master(self, experiment: Dict, player_models: List[Model]) -> DialogueGameMaster:
        return ClockworkCourier(self.game_spec, experiment, player_models)

    def create_game_scorer(self, experiment: Dict, game_instance: Dict) -> GameScorer:
        return ClockworkCourierScorer(GAME_NAME, experiment, game_instance)
