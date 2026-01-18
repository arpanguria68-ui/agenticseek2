import requests
import sys


def test_connection():
    url = "http://host.docker.internal:1234/v1/models"
    print(f"Testing connection to: {url}")
    try:
        response = requests.get(url, timeout=5)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text[:500]}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    test_connection()
