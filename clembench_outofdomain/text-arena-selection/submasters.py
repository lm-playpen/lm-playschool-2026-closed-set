"""
Subclasses of TextArena's GameMaster to handle scoring
and functionalities to ensure deterministic behavior for specific games
"""
from ta_master import TextArenaGameMaster
from clemcore.clemgame.metrics import METRIC_ABORTED, METRIC_SUCCESS, METRIC_LOSE
from typing import Dict
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

def reward_for_player(rewards: list[Dict], player_id: int=0) -> float:
    """
    Args:
        rewards: list of dicts as passed by ta_env.close()
        player_id: ID of the player for which to extract the reward
    Returns: 
        numeric_reward for the player
    """
    assert player_id in rewards[0], f"Player ID {player_id} not found in rewards! {rewards[0].keys()}"
    assert player_id in rewards[1], f"Player ID {player_id} not found in other_rewards! {rewards[1].keys()}"
    numeric_reward = rewards[0][player_id]
    invalid_move = rewards[1][player_id]['invalid_move']
    if invalid_move:
        numeric_reward = -1  # Bypass the float reward and sets it to -1, as described on TA website
    return numeric_reward

class SinglePlayerMaster(TextArenaGameMaster):
    """
    Master class for single-player games in TextArena.
    It handles basic scoring and logging functionalities.
    """
    def _on_after_game(self, **kwargs):
        rewards = kwargs.get('rewards', {})
        numeric_reward = reward_for_player(rewards, player_id=0)
        self.log_key('numeric_reward', numeric_reward)
        metrics = self.prepare_metrics(numeric_reward)
        for key, value in metrics.items():
            self.log_key(key, value)

    def prepare_metrics(self, numeric_reward=None) -> Dict[str, float]:
        """
        Returns default values for the metrics.
        """
        metrics = super().prepare_metrics()
        if numeric_reward:
            if numeric_reward == -1:
                metrics[METRIC_ABORTED] = 1
            elif numeric_reward == 1:
                metrics[METRIC_SUCCESS] = 1
        return metrics
