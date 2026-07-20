"""Make the game's sibling modules (courier_engine, instancegenerator) importable
when pytest is run from the repo root. clemcore does the same at game-load time by
putting the game directory on sys.path before importing master.py."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
