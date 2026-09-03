import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

import unittest
from rag.bm25 import BM25Okapi
from rag.router import _fast_reply

class TestRAGComponents(unittest.TestCase):
    def test_fast_reply_greeting(self):
        reply = _fast_reply("hello")
        self.assertIsNotNone(reply)
        self.assertIn("UniRAG", reply)

    def test_fast_reply_thanks(self):
        reply = _fast_reply("thank you")
        self.assertIsNotNone(reply)

    def test_bm25_retrieval(self):
        corpus = [
            "BUET requires a minimum GPA of 5.0 in SSC and HSC exams for admission.",
            "North South University tuition fees for CSE program is approximately 10 lakh BDT.",
        ]
        bm25 = BM25Okapi(corpus)
        scores = bm25.get_scores("BUET GPA requirement")
        self.assertGreater(scores[0], scores[1])

if __name__ == "__main__":
    unittest.main()
