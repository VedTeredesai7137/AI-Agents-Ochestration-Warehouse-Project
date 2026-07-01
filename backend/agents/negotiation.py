import json
import requests
import time
import threading

class NegotiationService:
    def __init__(self):
        self.url = "http://localhost:11434/api/generate"
        self.model = "mistral"
        self.negotiation_logs = []
        self.social_logs = []

    def resolve_deadlock(self, robot1_id, robot2_id, cell_x, cell_y, callback=None):
        """
        Runs the deadlock resolution asynchronously. 
        Calls callback(winner_id, reason) when done.
        """
        print("DEBUG: NegotiationService triggered!")
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
            print(f"DEBUG: LLM Prompt:\n{prompt}")

            try:
                start_time = time.time()
                print(f"DEBUG: Sending request to {self.url}")
                response = requests.post(self.url, json=payload, timeout=60.0)
                response.raise_for_status()
                data = response.json()
                raw_response = data.get("response", "{}")
                print(f"LLM Raw Response: {raw_response}")
                
                result = json.loads(raw_response)
                winner = result.get("winner_id")
                reason = result.get("reason", "No reason provided")
                
                print(f"FINAL LLM DEADLOCK RESPONSE - Winner: R{winner}, Reason: {reason}")
                
                if winner not in [robot1_id, robot2_id]:
                    print(f"Warning: LLM returned invalid winner {winner}, defaulting to lowest ID")
                    winner = min(robot1_id, robot2_id)
                    
            except requests.exceptions.Timeout:
                print("Warning: LLM Negotiation Timeout (60s).")
                winner = min(robot1_id, robot2_id)
                reason = f"Fallback due to LLM timeout."
            except Exception as e:
                print(f"DEBUG: Network/API Exception: Connection failed at {self.url} - {e}")
                print(f"Negotiation API failed/unreachable: {e}. Defaulting to lowest ID.")
                winner = min(robot1_id, robot2_id)
                reason = f"Fallback due to LLM error: {e}"
                
            log_entry = {
                "robot1": robot1_id,
                "robot2": robot2_id,
                "cell": (cell_x, cell_y),
                "winner": winner,
                "reason": reason,
                "event": f"Deadlock: R{robot1_id} vs R{robot2_id}",
                "timestamp": time.time(),
                "reasoning": reason,
                "decision": f"R{winner} passes"
            }
            self.negotiation_logs.append(log_entry)
            
            if callback:
                callback(winner, reason)
                
        # Start in background thread so simulation doesn't block waiting for Ollama
        threading.Thread(target=task, daemon=True).start()

    def explain_auction_winner(self, task_id, winner_id, bids):
        print("LLM Negotiation Service Called")
        def task():
            prompt = (
                f"Warehouse Task {task_id} had these bids (lower is better): {bids}. "
                f"Robot R{winner_id} won. Give a short 1-sentence reason why. "
                "Output JSON strictly with exactly one field: 'reason' (string)."
            )
            
            payload = {
                "model": self.model,
                "prompt": prompt,
                "format": "json",
                "stream": False
            }

            try:
                response = requests.post(self.url, json=payload, timeout=60.0)
                response.raise_for_status()
                data = response.json()
                raw_response = data.get("response", "{}")
                
                result = json.loads(raw_response)
                reason = result.get("reason", "No reason provided")
                print(f"FINAL LLM AUCTION REASON: {reason}")
                    
            except requests.exceptions.Timeout:
                print("Warning: LLM Auction Timeout (60s).")
                reason = "LLM timeout"
            except Exception as e:
                print(e)
                reason = f"LLM error: {e}"
                
            log_entry = {
                "robot1": "Auction",
                "robot2": f"T{task_id}",
                "cell": (0, 0),
                "winner": winner_id,
                "reason": reason,
                "event": f"Auction Task {task_id}",
                "timestamp": time.time(),
                "reasoning": reason,
                "decision": f"R{winner_id} won"
            }
            self.negotiation_logs.append(log_entry)
            
        threading.Thread(target=task, daemon=True).start()

    def generate_greeting(self, robot_id, target_id):
        def task():
            prompt = "You are a warehouse robot. You are passing by another robot. Generate a short, friendly, one-sentence greeting in character for a robot. Output JSON strictly with exactly one field: 'greeting' (string)."
            
            payload = {
                "model": self.model,
                "prompt": prompt,
                "format": "json",
                "stream": False
            }
            try:
                response = requests.post(self.url, json=payload, timeout=60.0)
                response.raise_for_status()
                data = response.json()
                raw_response = data.get("response", "{}")
                
                result = json.loads(raw_response)
                greeting = result.get("greeting", "Beep boop, hello!")
                print(f"[SOCIAL] Robot {robot_id} says to Robot {target_id}: '{greeting}'")
                
                log_entry = {
                    "robot1": f"R{robot_id}",
                    "robot2": f"R{target_id}",
                    "greeting": greeting,
                    "event": f"Greeting: R{robot_id} to R{target_id}",
                    "timestamp": time.time(),
                    "reasoning": "Passing by each other",
                    "decision": greeting
                }
                self.social_logs.append(log_entry)
                self.negotiation_logs.append(log_entry)
            except Exception as e:
                err_msg = f"LLM Error: {e}"
                print(f"[SOCIAL GREETING ERROR] {err_msg}")
                fallback_greeting = "Beep boop, hello! (LLM Offline)"
                log_entry = {
                    "robot1": f"R{robot_id}",
                    "robot2": f"R{target_id}",
                    "greeting": fallback_greeting,
                    "event": f"Greeting: R{robot_id} to R{target_id}",
                    "timestamp": time.time(),
                    "reasoning": err_msg,
                    "decision": fallback_greeting
                }
                self.social_logs.append(log_entry)
                self.negotiation_logs.append(log_entry)
                
        threading.Thread(target=task, daemon=True).start()

    def generate_initial_greeting(self, robot_id):
        def task():
            prompt = "You are a warehouse robot. Greet the other robots in the swarm for the first time. Keep it brief and robotic. Output JSON strictly with exactly one field: 'greeting' (string)."
            
            payload = {
                "model": self.model,
                "prompt": prompt,
                "format": "json",
                "stream": False
            }
            try:
                response = requests.post(self.url, json=payload, timeout=60.0)
                response.raise_for_status()
                data = response.json()
                raw_response = data.get("response", "{}")
                
                result = json.loads(raw_response)
                greeting = result.get("greeting", "Beep boop. Swarm activated.")
                print(f"[GREETING] Robot {robot_id} says: '{greeting}'")
                
                log_entry = {
                    "robot1": "System",
                    "robot2": f"R{robot_id}",
                    "cell": (0, 0),
                    "winner": robot_id,
                    "reason": greeting,
                    "event": f"Initial Greeting R{robot_id}",
                    "timestamp": time.time(),
                    "reasoning": greeting,
                    "decision": "Greeting generated"
                }
                self.negotiation_logs.append(log_entry)
            except Exception as e:
                err_msg = f"LLM Error: {e}. Ensure Ollama is running on localhost:11434 and model '{self.model}' is pulled."
                print(f"[GREETING ERROR] {err_msg}")
                fallback_greeting = "Beep boop. Swarm activated. (LLM Offline)"
                log_entry = {
                    "robot1": "System",
                    "robot2": f"R{robot_id}",
                    "cell": (0, 0),
                    "winner": robot_id,
                    "reason": fallback_greeting,
                    "event": f"Initial Greeting R{robot_id}",
                    "timestamp": time.time(),
                    "reasoning": err_msg,
                    "decision": fallback_greeting
                }
                self.negotiation_logs.append(log_entry)
                
        threading.Thread(target=task, daemon=True).start()

negotiation_service = NegotiationService()
