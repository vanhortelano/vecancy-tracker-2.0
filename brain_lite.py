"""Backup intent matcher for the Dorm Assistant. Used ONLY when scikit-learn cannot load (for
example on a PC whose security policy blocks compiled Python packages). Same intents.json, same
Brain interface, pure Python, no dependencies. brain.py (scikit-learn) stays the main model."""
import json
import math
import random
import re
from collections import Counter
from pathlib import Path

DATA_FILE = Path(__file__).parent / "intents.json"
CONFIDENCE_THRESHOLD = 0.30
SHARPNESS = 14.0           # turns similarity scores into probabilities (tuned against brain.py)


def clean(text):
    text = str(text).lower().strip()
    text = re.sub(r"[^a-z0-9\s']", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def features(text):
    words = text.split()
    f = Counter()
    for n in (1, 2):
        for i in range(len(words) - n + 1):
            f["w:" + " ".join(words[i:i + n])] += 1
    for w in words:
        p = " " + w + " "
        for n in (2, 3, 4):
            for i in range(len(p) - n + 1):
                f["c:" + p[i:i + n]] += 1
    return f


class Brain:
    def __init__(self):
        with open(DATA_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        self.responses = {i["tag"]: i["responses"] for i in data["intents"]}
        self.fallback = data["fallback_responses"]
        docs = []
        for intent in data["intents"]:
            for pattern in intent["patterns"]:
                docs.append((intent["tag"], features(clean(pattern))))
        df = Counter()
        for _tag, f in docs:
            df.update(f.keys())
        n = len(docs)
        self.idf = {k: math.log((1 + n) / (1 + c)) + 1 for k, c in df.items()}
        self.docs = [(tag, self._vec(f)) for tag, f in docs]
        self.tags = sorted(self.responses)

    def _vec(self, f):
        v = {k: (1 + math.log(c)) * self.idf[k] for k, c in f.items() if k in self.idf}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {k: x / norm for k, x in v.items()}

    def predict(self, message):
        text = clean(message)
        if not text or not re.search(r"[a-z]", text):
            return None, 0.0
        f = features(text)
        if not any(k.startswith("w:") and k in self.idf for k in f):
            return None, 0.0                       # not one known word: gibberish, ask to rephrase
        q = self._vec(f)
        if not q:
            return None, 0.0
        best = {}
        for tag, d in self.docs:
            s = sum(w * d[k] for k, w in q.items() if k in d)
            if s > best.get(tag, 0.0):
                best[tag] = s
        top = sorted(best.items(), key=lambda kv: -kv[1])[:6]
        scores = [s for _t, s in top]
        z = [math.exp(SHARPNESS * (s - scores[0])) for s in scores]
        return top[0][0], z[0] / sum(z) * min(1.0, scores[0] / 0.5)

    def answer(self, message):
        tag, conf = self.predict(message)
        if tag is None or conf < CONFIDENCE_THRESHOLD:
            return "unknown", conf, random.choice(self.fallback)
        return tag, conf, random.choice(self.responses[tag])
