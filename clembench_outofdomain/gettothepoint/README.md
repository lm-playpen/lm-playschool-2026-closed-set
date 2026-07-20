# Get to the Point

A previously closed-source game, now publicly available and up-to-date with current clemcore (3.7.2).


---

  *(Original README with minor factual corrections below)*

  ---


# Get to the Point
# Developed by Shahrukh Mohiuddin & Uday Bhaskar

**Get to the Point** is a cooperative word-association game inspired by the Clembench framework. Helper players take turns guiding the _Seeker_ in getting from a _starting_ word to a **target** word by giving a fixed number of clues. Obviously, without mentioning the **target** word directly!

This repo contains the code for playing the game (human-human, model-human and model-model), including customizable game-master logic, player strategies, and evaluation.

---

## 🧩 Game Overview

* **Goal**: Help your teammate guess the *target* word starting from a *start* word by giving indirect but meaningful clues.
* **Players**: 2 (can be played with humans or bots).
* **Levels**: Pairs are categorized by conceptual similarity (easy (similarity ~0.60–0.65) and hard (similarity ~0.51–0.55)).
* **Framework**: Built on top of Clembench’s dialogue-game architecture for easy extensibility.

---

## 🚀 How to Play

1. Choose a **start** and **target** word.
2. The *Seeker* must reach the target by giving intermediate words.
3. The *Helper* gives clues after each guess, but can't say the target directly.
4. The round ends when the target is guessed (success) or the maximum number of turns runs out (failure).
5. Scoring rewards fewer hints and closer semantic moves.

Example:

 
- Start: desert
- Target: arid

  - Guide: CLUE: desert very dry
  - Seeker: GUESS: dry
  - Guide: CLUE: desert parched barren land
  - Seeker: GUESS: arid ✅

---

## 📦 Features

* Predefined word pairs with similarity scores
* Low and high conceptual link categories
* Modular game-master and player architecture
* Supports human-human and model-human modes
* Easily extensible with new clue strategies

---

## 🗂️ Repository Structure

```
.
├── master.py     # GameMaster logic
├── player.py         # Player (Seeker / Guide) logic
├── resources/             # Word-pair datasets
├── README.md         # You're reading it!
└── requirements.txt  # Dependencies
```

---

## ⚙️ Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/YOUR_USERNAME/get-to-the-point.git
   cd get-to-the-point
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

---

## 💻 Usage

Run a basic game: Read -> [Clembench framework](https://github.com/clembench/clembench)
---

## 🛠️ Customization

You can:

* Add your own word pairs to `/resources`.
* Implement new Guide/Seeker strategies in `player.py`.
* Tweak turn limits and scoring in `gamemaster.py`.

---

## 🌐 Credits

* Inspired by the [Clembench framework](https://github.com/clembench/clembench).
* Developed by Shahrukh und Uday.

---

## 📜 License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

---
