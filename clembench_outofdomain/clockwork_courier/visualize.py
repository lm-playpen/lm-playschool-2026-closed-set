"""Visualize Clockwork Courier instances and episodes.

Draws the grid (walls, gates, parcels, guard routes), the BFS-optimal route, and -
when an episode is given - the route the model actually took, with bumps and
captures marked. Optionally renders an animated GIF where guards move, gates
blink open/closed, and the actual courier (orange) races the optimal ghost (blue).

Episode visuals are saved INTO the episode directory, right next to
transcript.html, as visualization.png (or .gif with --animate). The episode's own
instance.json is used, so visuals stay correct even if in/instances.json is later
regenerated with a different seed.

Examples (run from the repo root or the game directory):

  # one recorded episode -> <episode dir>/visualization.png
  .venv/bin/python clockwork_courier/visualize.py \
      --episode results/mock/clockwork_courier/standard/instance_00000

  # every clockwork_courier episode under a results folder, one PNG each
  .venv/bin/python clockwork_courier/visualize.py --results results/mock

  # animated GIF instead of a static PNG
  .venv/bin/python clockwork_courier/visualize.py \
      --episode results/mock/clockwork_courier/standard/instance_00000 --animate

  # instance only (no episode): grid + guard routes + optimal route -> viz/standard_0.png
  .venv/bin/python clockwork_courier/visualize.py -e standard -i 0
"""

import argparse
import json
import os
import sys
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import animation, patches

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import courier_engine as eng  # noqa: E402

GUARD_COLORS = ["#c0392b", "#8e44ad", "#b9770e"]
PARCEL_COLORS = ["#1a7a4a", "#1f618d", "#7d6608"]
OPTIMAL_COLOR = "#2e6fb7"
ACTUAL_COLOR = "#e67e22"


def load_instance(instances_path, experiment_name, game_id):
    data = json.load(open(instances_path))
    for experiment in data["experiments"]:
        if experiment["name"] == experiment_name:
            for instance in experiment["game_instances"]:
                if instance["game_id"] == game_id:
                    return instance
            raise SystemExit(f"game_id {game_id} not found in experiment '{experiment_name}'")
    names = [e["name"] for e in data["experiments"]]
    raise SystemExit(f"experiment '{experiment_name}' not found; available: {names}")


def optimal_trajectory(world):
    """Tick-indexed positions [pos at t=0, t=1, ...] of one optimal solution."""
    solved = eng.solve_optimal(world)
    if solved is None:
        raise SystemExit("instance is unsolvable?!")
    _, moves = solved
    state = eng.SimState.initial(world)
    trajectory = [world.start]
    for move in moves:
        eng.step(world, state, move)
        trajectory.append(state.pos)
    return trajectory


def actual_trajectory(world, interactions):
    """Reconstruct the model's tick-indexed positions from a recorded episode,
    plus bump and capture markers. Detained-after-capture ticks sit on start."""
    positions = {0: world.start}
    bumps, captures = [], []
    for turn in interactions["turns"]:
        for event in turn:
            if event["action"]["type"] != "round_result":
                continue
            record = event["action"]["content"]
            for tick_event in record["events"]:
                pos = tuple(tick_event["pos"])
                positions[tick_event["t"]] = pos
                if tick_event["result"].startswith("BUMP"):
                    bumps.append((tick_event["t"], pos))
                elif tick_event["result"] == "CAUGHT":
                    captures.append((tick_event["t"], pos))
            if record["caught"]:  # courier detained at start until the round boundary
                caught_tick = record["events"][-1]["t"]
                for t in range(caught_tick, record["end_tick"] + 1):
                    positions[t] = world.start
    trajectory = [positions[t] for t in range(max(positions) + 1)]
    return trajectory, bumps, captures


def draw_board(ax, world):
    """Static board: walls, start, gates, parcels, guard routes (no time dimension)."""
    ax.set_xlim(0.5, world.width + 0.5)
    ax.set_ylim(world.height + 0.5, 0.5)  # row 1 on top, like the ASCII map
    ax.set_xticks(range(1, world.width + 1))
    ax.set_yticks(range(1, world.height + 1))
    ax.set_aspect("equal")
    ax.grid(True, color="0.85", lw=0.5)
    ax.tick_params(length=0, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("0.3")

    for (x, y) in world.walls:
        ax.add_patch(patches.Rectangle((x - .5, y - .5), 1, 1, color="0.25", zorder=2))

    ax.add_patch(patches.Rectangle((world.start[0] - .45, world.start[1] - .45), .9, .9,
                                   facecolor="white", edgecolor="black", lw=1.6, zorder=3))
    ax.text(*world.start, "S", ha="center", va="center", fontsize=11,
            fontweight="bold", zorder=4)

    for gate in world.gates:
        x, y = gate.cell
        ax.add_patch(patches.Rectangle((x - .45, y - .45), .9, .9, facecolor="#f5e6a9",
                                       edgecolor="#8a6d00", lw=1.4, hatch="//", zorder=3))
        ax.text(x, y, gate.id, ha="center", va="center", fontsize=10,
                fontweight="bold", color="#6b5400", zorder=4)

    for parcel in world.parcels:
        color = PARCEL_COLORS[(parcel.id - 1) % len(PARCEL_COLORS)]
        px, py = parcel.pickup
        ax.add_patch(patches.Circle((px, py), .32, facecolor="white",
                                    edgecolor=color, lw=2, zorder=3))
        ax.text(px, py, str(parcel.id), ha="center", va="center", fontsize=9,
                color=color, fontweight="bold", zorder=4)
        dx, dy = parcel.dropoff
        ax.add_patch(patches.Polygon([(dx - .3, dy + .25), (dx + .3, dy + .25), (dx, dy - .3)],
                                     facecolor="white", edgecolor=color, lw=2, zorder=3))
        ax.text(dx, dy + .04, parcel.dropoff_glyph, ha="center", va="center", fontsize=8,
                color=color, fontweight="bold", zorder=4)

    for index, patrol in enumerate(world.patrols):
        color = GUARD_COLORS[index % len(GUARD_COLORS)]
        cycle = list(patrol.route) + [patrol.route[0]]
        xs = [c[0] for c in cycle]
        ys = [c[1] for c in cycle]
        ax.plot(xs, ys, ls=":", lw=1.6, color=color, alpha=.7, zorder=2.5)
        gx, gy = patrol.pos_at(0)
        ax.add_patch(patches.Circle((gx, gy), .22, facecolor=color, alpha=.85, zorder=3))
        ax.text(gx, gy, patrol.id, ha="center", va="center", fontsize=8,
                color="white", fontweight="bold", zorder=4)


def draw_route(ax, trajectory, color, label, offset):
    xs = [pos[0] + offset for pos in trajectory]
    ys = [pos[1] + offset for pos in trajectory]
    ax.plot(xs, ys, "-", color=color, lw=2.2, alpha=.85, zorder=5,
            label=label, solid_capstyle="round")
    ax.scatter(xs, ys, s=12, color=color, zorder=5)
    for t, (x, y) in enumerate(zip(xs, ys)):
        ax.annotate(str(t), (x, y), textcoords="offset points",
                    xytext=(4, -7 if offset > 0 else 7),
                    fontsize=5.5, color=color, zorder=6)


def schedule_caption(world):
    lines = []
    for gate in world.gates:
        phases = ",".join(map(str, sorted(gate.open_phases)))
        lines.append(f"Gate {gate.id} {eng.cell_str(gate.cell)}: open iff t mod {gate.period} in {{{phases}}}")
    for patrol in world.patrols:
        route = " > ".join(eng.cell_str(c) for c in patrol.route)
        lines.append(f"Guard {patrol.id} (cycle {len(patrol.route)}): {route} > repeat")
    return "\n".join(textwrap.fill(line, 110) for line in lines)


def render_static(world, instance, optimal, actual, bumps, captures, episode_meta, out_path):
    caption = ("small numbers along the routes are ticks\n" + schedule_caption(world))
    caption_lines = caption.count("\n") + 1
    fig, ax = plt.subplots(figsize=(max(6, world.width * .85),
                                    max(6, world.height * .85) + 1.0 + 0.18 * caption_lines))
    draw_board(ax, world)
    draw_route(ax, optimal, OPTIMAL_COLOR, f"optimal route ({len(optimal) - 1} ticks)",
               offset=-0.13)
    if actual is not None:
        used = len(actual) - 1
        draw_route(ax, actual, ACTUAL_COLOR, f"model route ({used} ticks, {episode_meta})",
                   offset=+0.13)
        for _, pos in bumps:
            ax.scatter(pos[0] + .13, pos[1] + .13, marker="x", s=70, color="black",
                       lw=2, zorder=7)
        for _, pos in captures:
            ax.scatter(pos[0] + .13, pos[1] + .13, marker="X", s=140, color="red",
                       edgecolor="black", lw=.6, zorder=7)
        ax.scatter([], [], marker="x", color="black", label="bump")
        ax.scatter([], [], marker="X", color="red", label="caught")
    ax.legend(loc="upper left", bbox_to_anchor=(0, -0.04), fontsize=8, ncol=2,
              frameon=False)
    fig.suptitle(f"{instance['experiment_label']} (optimal {instance['optimal_ticks']} ticks, "
                 f"budget {instance['tick_budget']})", fontsize=12, y=.985)
    fig.text(0.02, 0.005, caption, fontsize=6.5, family="monospace", va="bottom")
    bottom_margin = min(0.3, 0.075 + 0.020 * caption_lines)
    fig.tight_layout(rect=(0, bottom_margin, 1, 0.96))
    fig.savefig(out_path, dpi=160)
    plt.close(fig)
    return out_path


def render_animation(world, instance, optimal, actual, out_path, fps):
    total_ticks = max(len(optimal), len(actual) if actual else 0) - 1
    fig, ax = plt.subplots(figsize=(max(6, world.width * .85), max(6, world.height * .85)))
    draw_board(ax, world)

    gate_fills = {}
    for gate in world.gates:
        x, y = gate.cell
        gate_fills[gate.id] = ax.add_patch(
            patches.Rectangle((x - .45, y - .45), .9, .9, facecolor="none",
                              edgecolor="none", alpha=.55, zorder=2.8))
    guard_dots = []
    for index, patrol in enumerate(world.patrols):
        color = GUARD_COLORS[index % len(GUARD_COLORS)]
        dot = patches.Circle(patrol.pos_at(0), .26, facecolor=color, zorder=6)
        ax.add_patch(dot)
        guard_dots.append((patrol, dot))

    ghost = patches.Circle(optimal[0], .3, facecolor=OPTIMAL_COLOR, alpha=.45, zorder=6)
    ax.add_patch(ghost)
    ghost_trail, = ax.plot([], [], "-", color=OPTIMAL_COLOR, lw=2, alpha=.4, zorder=5)
    courier = None
    courier_trail = None
    if actual:
        courier = patches.Circle(actual[0], .3, facecolor=ACTUAL_COLOR,
                                 edgecolor="black", lw=1, zorder=7)
        ax.add_patch(courier)
        courier_trail, = ax.plot([], [], "-", color=ACTUAL_COLOR, lw=2, alpha=.6, zorder=5)
    title = ax.set_title("", fontsize=11)

    def frame(t):
        for gate in world.gates:
            gate_fills[gate.id].set_facecolor("#7dd87d" if gate.is_open(t) else "#e57373")
        for patrol, dot in guard_dots:
            dot.set_center(patrol.pos_at(t))
        ghost.set_center(optimal[min(t, len(optimal) - 1)])
        trail = optimal[:t + 1]
        ghost_trail.set_data([p[0] for p in trail], [p[1] for p in trail])
        artists = [ghost, ghost_trail, title, *gate_fills.values(),
                   *(dot for _, dot in guard_dots)]
        if actual:
            courier.set_center(actual[min(t, len(actual) - 1)])
            trail = actual[:t + 1]
            courier_trail.set_data([p[0] for p in trail], [p[1] for p in trail])
            artists += [courier, courier_trail]
        title.set_text(f"{instance['experiment_label']}   t={t}/{total_ticks}   "
                       f"(blue ghost = optimal{', orange = model' if actual else ''})")
        return artists

    anim = animation.FuncAnimation(fig, frame, frames=total_ticks + 1, blit=False)
    anim.save(out_path, writer=animation.PillowWriter(fps=fps))
    plt.close(fig)
    return out_path


def render_episode(episode_dir, animate, fps, out_path=None):
    """Render one recorded episode into its own directory (next to transcript.html).
    Uses the episode's instance.json, so it works regardless of the current
    in/instances.json contents."""
    instance = json.load(open(os.path.join(episode_dir, "instance.json")))
    interactions = json.load(open(os.path.join(episode_dir, "interactions.json")))
    meta = interactions["meta"]
    instance["experiment_label"] = (f"{meta.get('results_folder', '?')} - "
                                    f"{meta['experiment_name']}/instance {meta['game_id']}")
    world = eng.World.from_instance(instance)
    optimal = optimal_trajectory(world)
    actual, bumps, captures = actual_trajectory(world, interactions)
    episode_meta = interactions.get("episode_result", {}).get("outcome", "?")
    if out_path is None:
        out_path = os.path.join(episode_dir, "visualization.gif" if animate
                                else "visualization.png")
    if animate:
        render_animation(world, instance, optimal, actual, out_path, fps)
    else:
        render_static(world, instance, optimal, actual, bumps, captures,
                      episode_meta, out_path)
    return out_path


def render_instance_only(instances_path, experiment, game_id, animate, fps,
                         out_path=None, game_dir="."):
    instance = load_instance(instances_path, experiment, game_id)
    instance["experiment_label"] = f"{experiment}/instance {game_id}"
    world = eng.World.from_instance(instance)
    optimal = optimal_trajectory(world)
    if out_path is None:
        out_dir = os.path.join(game_dir, "viz")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{experiment}_{game_id}."
                                         f"{'gif' if animate else 'png'}")
    if animate:
        render_animation(world, instance, optimal, None, out_path, fps)
    else:
        render_static(world, instance, optimal, None, [], [], "", out_path)
    return out_path


def find_episodes(results_dir):
    episodes = []
    for root, _, files in os.walk(results_dir):
        if "interactions.json" in files and "instance.json" in files \
                and f"{os.sep}clockwork_courier{os.sep}" in root + os.sep:
            episodes.append(root)
    return sorted(episodes)


def main():
    game_dir = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--episode", default=None,
                        help="episode dir (with interactions.json); the visual is saved "
                             "there as visualization.png/.gif, next to transcript.html")
    parser.add_argument("--results", default=None,
                        help="render EVERY clockwork_courier episode under this results "
                             "dir, each into its own episode folder")
    parser.add_argument("-e", "--experiment", default=None,
                        help="instance-only mode: experiment name "
                             "(standard / deadreckon / egocentric)")
    parser.add_argument("-i", "--game-id", type=int, default=0,
                        help="instance-only mode: instance id (default 0)")
    parser.add_argument("--instances", default=os.path.join(game_dir, "in", "instances.json"))
    parser.add_argument("--animate", action="store_true", help="render a GIF instead of a PNG")
    parser.add_argument("--fps", type=int, default=2)
    parser.add_argument("--out", default=None,
                        help="output file path (single renders only)")
    args = parser.parse_args()

    if sum(bool(x) for x in (args.episode, args.results, args.experiment)) != 1:
        parser.error("choose exactly one mode: --episode <dir>, --results <dir>, "
                     "or -e <experiment> [-i <id>]")

    if args.results:
        episodes = find_episodes(args.results)
        if not episodes:
            raise SystemExit(f"no clockwork_courier episodes found under {args.results}")
        for episode_dir in episodes:
            print(render_episode(episode_dir, args.animate, args.fps))
    elif args.episode:
        print(render_episode(args.episode, args.animate, args.fps, args.out))
    else:
        print(render_instance_only(args.instances, args.experiment, args.game_id,
                                   args.animate, args.fps, args.out, game_dir))


if __name__ == "__main__":
    main()
