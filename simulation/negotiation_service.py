import json
import requests
import time
import threading

class NegotiationService:
    def __init__(self):
        self.url = "http://localhost:11434/api/generate"
        self.model = "mistral"
        self.negotiation_logs = []

    def resolve_deadlock(self, robot1_id, robot2_id, cell_x, cell_y, callback=None):
        """
        Runs the deadlock resolution asynchronously. 
        Calls callback(winner_id, reason) when done.
        """
        def task():
            prompt = (
                f"Two warehouse robots, R{robot1_id} and R{robot2_id}, are deadlocked trying to enter cell ({cell_x}, {cell_y}). "
                "Output JSON strictly with exactly two fields: 'winner_id' (integer, either {robot1_id} or {robot2_id}) and 'reason' (string) indicating who should yield and why."
            )
            
            payload = {
                "model": self.model,
                "prompt": prompt,
                "format": "json",
                "stream": False
            }

            try:
                start_time = time.time()
                response = requests.post(self.url, json=payload, timeout=5.0)
                response.raise_for_status()
                data = response.json()
                raw_response = data.get("response", "{}")
                print(f"LLM Raw Response: {raw_response}")
                
                result = json.loads(raw_response)
                winner = result.get("winner_id")
                reason = result.get("reason", "No reason provided")
                
                if winner not in [robot1_id, robot2_id]:
                    print(f"Warning: LLM returned invalid winner {winner}, defaulting to {robot1_id}")
                    winner = robot1_id
                    
            except Exception as e:
                print(f"Negotiation API failed/unreachable: {e}. Defaulting to R{robot1_id}.")
                winner = robot1_id
                reason = f"Fallback due to LLM error: {e}"
                
            log_entry = {
                "robot1": robot1_id,
                "robot2": robot2_id,
                "cell": (cell_x, cell_y),
                "winner": winner,
                "reason": reason
            }
            self.negotiation_logs.append(log_entry)
            
            if callback:
                callback(winner, reason)
                
        # Start in background thread so simulation doesn't block waiting for Ollama
        threading.Thread(target=task, daemon=True).start()

negotiation_service = NegotiationService()
