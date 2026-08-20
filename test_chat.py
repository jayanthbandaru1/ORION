"""
Quick manual sanity check against the running FastAPI server.

Usage (with the server already running in another terminal):
    python test_chat.py
"""

import httpx

QUESTIONS = [
    "What files are in your sandbox directory?",
    "Read welcome.txt and tell me in one sentence what it says.",
]


def main():
    with httpx.Client(base_url="http://localhost:8000", timeout=60) as client:
        health = client.get("/health").json()
        print(f"health check: {health}\n")

        for question in QUESTIONS:
            print(f"> {question}")
            response = client.post("/chat", json={"message": question})
            print(f"{response.json()['reply']}\n")


if __name__ == "__main__":
    main()
