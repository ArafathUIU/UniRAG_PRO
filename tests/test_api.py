import unittest
from django.test import Client

class TestAPIEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = Client()

    def test_status_endpoint(self):
        response = self.client.get("/status/")
        self.assertEqual(response.status_code, 200)

if __name__ == "__main__":
    unittest.main()
