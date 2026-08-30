import math
import re
from collections import Counter

class BM25Okapi:
    def __init__(self, corpus: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus = corpus
        self.doc_tokens = [self._tokenize(doc) for doc in corpus]
        self.doc_lens = [len(tokens) for tokens in self.doc_tokens]
        self.avgdl = sum(self.doc_lens) / len(self.doc_lens) if self.doc_lens else 1.0
        self.doc_freqs = []
        self.idf = {}
        self.nd = len(corpus)
        self._calc_idf()

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"\w+", text.lower())

    def _calc_idf(self):
        df = Counter()
        for tokens in self.doc_tokens:
            for token in set(tokens):
                df[token] += 1
        for token, freq in df.items():
            self.idf[token] = math.log((self.nd - freq + 0.5) / (freq + 0.5) + 1.0)

    def get_scores(self, query: str) -> list[float]:
        query_tokens = self._tokenize(query)
        scores = [0.0] * self.nd
        for q_token in query_tokens:
            if q_token not in self.idf:
                continue
            idf_val = self.idf[q_token]
            for doc_idx, tokens in enumerate(self.doc_tokens):
                tf = tokens.count(q_token)
                if tf == 0:
                    continue
                denom = tf + self.k1 * (1.0 - self.b + self.b * (self.doc_lens[doc_idx] / self.avgdl))
                scores[doc_idx] += idf_val * (tf * (self.k1 + 1.0)) / denom
        return scores
