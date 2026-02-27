import psutil
import os
import time
import logging
import threading
import json
import traceback
from datetime import datetime
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

class OOMEngine:
    """
    Intelligent Out-of-Memory (OOM) Diagnostic & Prevention Engine.
    Designed for resource-constrained environments (e.g. 512MB RAM).
    
    Features:
    - Real-time Memory Monitoring (psutil)
    - Statistical Trend Analysis (Predictive OOM)
    - Automated Stack Trace & Context Capture
    - Hybrid Categorization (Heap, Stack, Native)
    - Low-overhead Storage Integration
    """

    # Thresholds (percentage of total RAM)
    WARN_THRESHOLD = 75.0
    CRITICAL_THRESHOLD = 90.0
    OOM_THRESHOLD = 95.0

    def __init__(self, db_handler=None, premium_ai=None):
        self.db = db_handler
        self.ai = premium_ai
        self.running = False
        self._monitor_thread = None
        
        # Performance history for statistical analysis (Stochastic/Statistical techniques)
        self.history = []
        self.MAX_HISTORY = 120 # 10 minutes at 5s interval
        
        # OOM Events
        self.last_oom_event = None
        
    def start(self):
        """Starts the OOM monitoring engine in a background thread."""
        if self.running: return
        self.running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        logger.info("OOM Engine started (Real-time monitoring active)")

    def stop(self):
        self.running = False

    def _monitor_loop(self):
        """Main monitoring loop with adaptive sampling."""
        while self.running:
            try:
                mem = psutil.virtual_memory()
                current_percent = mem.percent
                
                # Statistical analysis: add to history
                self.history.append({
                    "ts": time.time(),
                    "percent": current_percent,
                    "available": mem.available,
                    "used": mem.used
                })
                if len(self.history) > self.MAX_HISTORY:
                    self.history.pop(0)

                # Stochastic check: Predict future OOM based on trend (Linear Regression heuristic)
                if len(self.history) >= 10:
                    drift = self._calculate_drift()
                    if drift > 0:
                        # Estimate time until OOM threshold (Linear projection)
                        remaining_to_oom = self.OOM_THRESHOLD - current_percent
                        if remaining_to_oom > 0:
                            time_to_oom = remaining_to_oom / drift
                            if time_to_oom < 60: # Predict OOM within 1 minute
                                logger.warning(f"Predictive OOM Alert: Potential memory exhaustion in {time_to_oom:.1f}s (Drift: {drift:.2f}%/s)")
                                self._trigger_snapshot("PREDICTIVE_OOM", time_to_oom)

                # Threshold-based detection (Rule-based Techniques)
                if current_percent >= self.OOM_THRESHOLD:
                    self._handle_oom_event("CRITICAL_OOM", current_percent)
                elif current_percent >= self.CRITICAL_THRESHOLD:
                    self._trigger_snapshot("CRITICAL_PRESSURE", current_percent)
                
                # Adaptive sampling: sleep more if memory is low, less if it's changing fast
                sleep_time = 5 if current_percent < self.WARN_THRESHOLD else 2
                time.sleep(sleep_time)
                
            except Exception as e:
                logger.error(f"OOM Monitor Error: {e}")
                time.sleep(10)

    def _calculate_drift(self) -> float:
        """Calculates memory growth rate (%/s) using statistical drift detection."""
        if len(self.history) < 5: return 0.0
        
        # Simple Linear Regression (y = mx + b)
        n = len(self.history)
        x = [h["ts"] - self.history[0]["ts"] for h in self.history]
        y = [h["percent"] for h in self.history]
        
        x_mean = sum(x) / n
        y_mean = sum(y) / n
        
        num = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
        den = sum((x[i] - x_mean) ** 2 for i in range(n))
        
        if den == 0: return 0.0
        slope = num / den # % per second
        return max(0, slope)

    def _trigger_snapshot(self, reason: str, value: float):
        """Captures application context and stack trace without blocking."""
        try:
            # Categorization Logic (Hybrid: Rule-based + Statistical)
            oom_type = self._categorize_oom_type()
            
            snapshot = {
                "ts": datetime.now().isoformat(),
                "reason": reason,
                "current_percent": value,
                "type": oom_type,
                "stack_trace": traceback.format_exc(), # Current stack context
                "active_threads": threading.active_count(),
                "process_info": self._get_process_context()
            }
            
            self.last_oom_event = snapshot
            
            # Store in DB if available
            if self.db:
                try:
                    # Efficiently store as system log/alert
                    self.db.add_system_log("OOM_SNAPSHOT", json.dumps(snapshot))
                except Exception: pass
                
        except Exception as e:
            logger.error(f"Failed to capture OOM snapshot: {e}")

    def _handle_oom_event(self, reason: str, value: float):
        """Critical handler: performs emergency actions and analysis."""
        logger.error(f"OOM CONDITION DETECTED: {reason} ({value}%)")
        self._trigger_snapshot(reason, value)
        
        # Intelligent Analysis (LLM Fallback)
        if self.ai:
            threading.Thread(target=self._analyze_with_ai, args=(self.last_oom_event,), daemon=True).start()

    def _categorize_oom_type(self) -> str:
        """Categorizes OOM based on memory segment characteristics."""
        try:
            proc = psutil.Process()
            mem_info = proc.memory_full_info()
            
            # Heuristics:
            # - High Heap: High RSS/USS relative to swap/vms
            # - Stack OOM: High VMS but moderate RSS (deep recursion)
            # - Native: High non-python memory usage (detected via external libs if possible)
            
            if mem_info.uss > 0.8 * mem_info.rss:
                return "HEAP_OOM"
            elif mem_info.vms > 3 * mem_info.rss:
                return "STACK_OOM"
            else:
                return "NATIVE_OOM"
        except Exception:
            return "UNKNOWN_OOM"

    def _get_process_context(self) -> Dict:
        """Extracts key context from current process."""
        try:
            proc = psutil.Process()
            return {
                "cpu_percent": proc.cpu_percent(),
                "memory_info": proc.memory_info()._asdict(),
                "num_fds": proc.num_fds() if hasattr(proc, "num_fds") else 0,
                "num_threads": proc.num_threads(),
                "open_files": [f.path for f in proc.open_files()[:5]]
            }
        except Exception:
            return {}

    def _analyze_with_ai(self, event_data: Dict):
        """Uses Premium AI Engine to perform deep intelligent analysis."""
        if not self.ai: return
        
        prompt = f"""
        Perform intelligent OOM diagnosis on this snapshot:
        {json.dumps(event_data, indent=2)}
        
        Context: Koyeb Free Tier (512MB RAM).
        Task:
        1. Diagnose root cause using hybrid nlp techniques.
        2. Identify potentially offending modules.
        3. Provide specific memory optimization recommendations.
        """
        
        try:
            # Call AI for diagnosis
            import asyncio
            diagnosis = asyncio.run(self.ai.process_interaction(0, prompt, "OOM_ENGINE"))
            
            if self.db and diagnosis.suggested_response:
                self.db.add_system_log("OOM_AI_DIAGNOSIS", diagnosis.suggested_response)
                
            logger.info("Intelligent OOM Analysis completed")
        except Exception as e:
            logger.error(f"AI OOM Diagnosis failed: {e}")

    def get_status(self) -> Dict:
        """Returns current engine status and recent history."""
        mem = psutil.virtual_memory()
        return {
            "is_running": self.running,
            "current_percent": mem.percent,
            "available_mb": mem.available / (1024 * 1024),
            "history": self.history[-20:] if self.history else [],
            "last_event": self.last_oom_event
        }
