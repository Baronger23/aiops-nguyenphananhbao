import time
import requests
import threading

request_count = 0
counter_lock = threading.Lock()

def send_requests(url):
    global request_count
    while True:
        try:
            requests.get(url, timeout=2)
            with counter_lock:
                request_count += 1
        except Exception:
            pass
        time.sleep(0.1) # 10 requests per second

urls = [
    "http://localhost:8080",
    "http://localhost:8081",
    "http://localhost:8082",
    "http://localhost:8083",
    "http://localhost:8084"
]

threads = []
for url in urls:
    t = threading.Thread(target=send_requests, args=(url,))
    t.daemon = True
    t.start()
    threads.append(t)

print("Traffic generator is running. Press Ctrl+C to stop.")

try:
    while True:
        time.sleep(5)
        with counter_lock:
            print(f"[traffic_generator] Sent {request_count} requests successfully.")
except KeyboardInterrupt:
    print("\nTraffic generator stopped gracefully.")
