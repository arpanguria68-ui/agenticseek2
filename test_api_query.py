import requests
import json
import time


def test_query():
    url = "http://127.0.0.1:7777/query"
    payload = {
        "query": "can you create a travel plan to japan and itentinary",
        "tts_enabled": False,
    }

    print(f"Sending query to {url}...")
    try:
        start_time = time.time()
        # Increased timeout to accommodate the long thinking time of reasoning models
        response = requests.post(url, json=payload, timeout=600)
        elapsed = time.time() - start_time

        print(f"Request finished in {elapsed:.2f} seconds.")
        print(f"Status Code: {response.status_code}")

        try:
            data = response.json()
            print("Response JSON keys:", data.keys())
            if "answer" in data:
                print("\n--- ANSWER START ---\n")
                print(data["answer"][:1000])  # Print first 1000 chars
                print("\n--- ANSWER END ---\n")
            if "reasoning" in data:
                print("\n--- REASONING START ---\n")
                print(data["reasoning"][:500])
                print("\n--- REASONING END ---\n")
        except Exception as e:
            print(f"Failed to parse JSON: {e}")
            print("Raw text:", response.text[:1000])

    except Exception as e:
        print(f"Request failed: {e}")


if __name__ == "__main__":
    test_query()
