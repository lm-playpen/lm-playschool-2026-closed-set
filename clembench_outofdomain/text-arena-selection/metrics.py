from clemcore.clemgame import GameScorer
from typing import Dict
from clemcore.clemgame.metrics import METRIC_ABORTED, METRIC_SUCCESS, METRIC_LOSE, BENCH_SCORE
import numpy as np
import logging
import abc

module_logger = logging.getLogger(__name__)
module_logger.setLevel(logging.DEBUG)


def init_metrics(numeric_reward=None) -> Dict[str, float]:
        """
        Returns default values for the metrics.
        """
        metrics = {
            METRIC_ABORTED: 0,
            METRIC_SUCCESS: 0,
            METRIC_LOSE: 0,
            BENCH_SCORE: np.nan
        }
        if numeric_reward is not None:
            if numeric_reward == -1:
                metrics[METRIC_ABORTED] = 1
            elif numeric_reward == 1:
                metrics[METRIC_SUCCESS] = 1
                metrics[BENCH_SCORE] = 100
            else:
                metrics[BENCH_SCORE] = numeric_reward * 100
        return metrics

class TextArenaScorer(GameScorer):
    """
    Default scorer for the TextArena environment.
    """
    def __init__(self, game_name: str, experiment: Dict, game_instance: Dict):
        super().__init__(game_name, experiment, game_instance)
        # Interaction keys to extract from episode interactions to compute scores
        self.interaction_keys = []

    def get_auxiliaries(self, episode_interactions: Dict) -> Dict[str, float]:
        """
        Extracts auxiliary information from the episode interactions.
        """
        auxiliaries = {key: episode_interactions[key] for key in self.interaction_keys if key in episode_interactions}
        return auxiliaries

    def compute_episode_scores(self, episode_interactions: Dict):
        auxiliaries = self.get_auxiliaries(episode_interactions)
        bench_score = self.compute_bench_score(auxiliaries=auxiliaries)
        self.log_episode_score(BENCH_SCORE, bench_score)

    @abc.abstractmethod
    def compute_bench_score(self, auxiliaries: Dict):
        pass

class SinglePlayerScorer(TextArenaScorer):
    """
    Scorer for single-player games in TextArena.
    """
    def __init__(self, game_name: str, experiment: Dict, game_instance: Dict):
        super().__init__(game_name, experiment, game_instance)
        self.interaction_keys = [METRIC_SUCCESS, METRIC_ABORTED, METRIC_LOSE, "numeric_reward", "ta_reward"]

    def compute_bench_score(self, auxiliaries: Dict):
        """
        Computes basic benchmark score based on numeric_reward. Can be extended in subclasses.
        """
        self.log_episode_score("Numeric Reward", auxiliaries['numeric_reward'])
        self.log_episode_score("ta_reward", auxiliaries['ta_reward'])
        if auxiliaries[METRIC_ABORTED] == 1 or auxiliaries[METRIC_LOSE] == 1:
            return np.nan
        else:
            return auxiliaries['numeric_reward'] * 100
