""" Register all game environments """ 

from textarena.envs.registration import register_with_versions

# Blackjack (1 Player)
register_with_versions(id="Blackjack-v0",       entry_point="textarena.envs.Blackjack.env:BlackjackEnv", num_hands=5   )
register_with_versions(id="Blackjack-v0-long",  entry_point="textarena.envs.Blackjack.env:BlackjackEnv", num_hands=15  )

# FrozenLake [1 Player]
register_with_versions(id="FrozenLake-v0",          entry_point="textarena.envs.FrozenLake.env:FrozenLakeEnv", size=4, num_holes=3, randomize_start_goal=False  )
register_with_versions(id="FrozenLake-v0-random",   entry_point="textarena.envs.FrozenLake.env:FrozenLakeEnv", size=4, num_holes=3, randomize_start_goal=True   )
register_with_versions(id="FrozenLake-v0-hardcore", entry_point="textarena.envs.FrozenLake.env:FrozenLakeEnv", size=5, num_holes=6, randomize_start_goal=False  )

# Mastermind [1 Player]
register_with_versions(id="Mastermind-v0",          entry_point="textarena.envs.Mastermind.env:MastermindEnv", code_length=4, num_numbers=6, max_turns=20, duplicate_numbers=False)
register_with_versions(id="Mastermind-v0-hard",     entry_point="textarena.envs.Mastermind.env:MastermindEnv", code_length=4, num_numbers=8, max_turns=30, duplicate_numbers=False)    
# register_with_versions(id="Mastermind-v0-extreme",  entry_point="textarena.envs.Mastermind.env:MastermindEnv", code_length=6, num_numbers=12, max_turns=50, duplicate_numbers=True)

# Sokoban [1 Player]
register_with_versions(id="Sokoban-v0",         entry_point="textarena.envs.Sokoban.env:SokobanEnv", dim_room=(6,6), max_turns=30, num_boxes=3)
# register_with_versions(id="Sokoban-v0-medium",  entry_point="textarena.envs.Sokoban.env:SokobanEnv", dim_room=(8,8), max_turns=50, num_boxes=5)