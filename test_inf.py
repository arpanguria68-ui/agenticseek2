import requests
import json
import time


def test_inference():
    url = "http://host.docker.internal:1234/v1/chat/completions"
    payload = {
        "messages": [
            {
                "role": "user",
                "content": "can you create a travel plan to japan and itentinary",
            }
        ],
        "temperature": 0.7,
        "max_tokens": 4096,
        "model": "qwen3-vl-8b-thinking-heretic",
    }

    print(f"Sending request to {url}...")
    start_time = time.time()
    try:
        response = requests.post(
            url, json=payload, timeout=60
        )  # Increased timeout for test
        elapsed = time.time() - start_time
        print(f"Request took {elapsed:.2f} seconds")

        if response.status_code == 200:
            print("Success!")
            print(f"Content length: {len(response.text)}")
        else:
            print(f"Failed with status {response.status_code}")
            print(response.text)

    except Exception as e:
        elapsed = time.time() - start_time
        print(f"Error after {elapsed:.2f} seconds: {e}")


if __name__ == "__main__":
    test_inference()
