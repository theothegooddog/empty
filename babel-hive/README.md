# Babel Hive

A honeycomb word puzzle where every word counts in **any of 16 languages**:
English, Español, Français, Deutsch, Italiano, Português, Nederlands, Svenska,
Norsk, Dansk, Polski, Čeština, Türkçe, Română, Català and Magyar.

Open `index.html` in a browser; it is fully self-contained.

## Rules
- Make words of 4+ letters from the seven letters; every word must use the center letter. Letters can repeat.
- Accents are ignored (`über` is typed `UBER`, `ação` is `ACAO`).
- 4-letter words score 1; longer words score their length. A pangram (all seven letters) adds +7.
- **Polyglot bonus:** +1 for each extra language a word exists in (max +5).
- The language ledger shows how many words hide in each language.
- "Today" picks a daily hive; "New hive" picks a random one out of 500. Progress saves in your browser.

## Rebuilding the puzzles
`tools/build_puzzles.py` builds `tools/puzzles.json` from the
[wordfreq](https://pypi.org/project/wordfreq/) frequency lists, keeping only words that
the matching Hunspell dictionary (npm `dictionary-xx` packages, unpacked into `dicts/`)
accepts in lowercase, which filters out most proper names. `tools/assemble.py` inlines
the data into `index.html`.
