"""
Watch mode for x-digest.

Implements interval-based digest execution without requiring cron setup.
Useful for development, testing, and users who prefer foreground execution.
"""

import time
import signal
import sys
from datetime import datetime, UTC, timedelta
from typing import Dict, Any, Callable, Optional

from .status import load_status, should_run


class WatchMode:
    """Watch mode manager for interval-based digest execution."""
    
    def __init__(self, list_name: str, interval_seconds: int, digest_function: Callable):
        """
        Initialize watch mode.
        
        Args:
            list_name: Name of the list to watch
            interval_seconds: Interval between runs
            digest_function: Function to call for digest execution
        """
        self.list_name = list_name
        self.interval_seconds = interval_seconds
        self.digest_function = digest_function
        self.running = False
        
        # Set up signal handlers for clean shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def start(self, status_path: Optional[str] = None) -> None:
        """
        Start watch mode loop.
        
        Args:
            status_path: Path to status file for idempotency checks
        """
        print(f"Starting watch mode for list '{self.list_name}'")
        print(f"Interval: {self.interval_seconds} seconds ({self._format_interval()})")
        print("Press Ctrl+C to stop")
        print()
        
        self.running = True
        
        while self.running:
            try:
                result = self._watch_tick(status_path)
                next_run = self._calculate_next_run()
                
                if result == "executed":
                    print(f"✓ Digest executed at {datetime.now().strftime('%H:%M:%S')}")
                elif result == "skipped":
                    print(f"⏭ Skipped (recent run) at {datetime.now().strftime('%H:%M:%S')}")
                
                print(f"  Next run: {next_run.strftime('%H:%M:%S')}")
                print()
                
                # Wait for next interval
                self._wait_for_next_run()
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"❌ Error during watch tick: {e}")
                print(f"   Will retry in {self.interval_seconds} seconds")
                time.sleep(self.interval_seconds)
        
        print("Watch mode stopped")
    
    def stop(self) -> None:
        """Stop watch mode loop."""
        self.running = False
    
    def _watch_tick(self, status_path: Optional[str]) -> str:
        """
        Execute one watch cycle.
        
        Returns:
            "executed" | "skipped" | "error"
        """
        try:
            # Check if we should run based on status
            status = load_status(status_path)
            if not should_run(self.list_name, status):
                return "skipped"
            
            # Execute digest function
            self.digest_function(self.list_name)
            return "executed"
            
        except Exception:
            return "error"
    
    def _calculate_next_run(self) -> datetime:
        """Calculate next run timestamp."""
        return datetime.now(UTC) + timedelta(seconds=self.interval_seconds)
    
    def _wait_for_next_run(self) -> None:
        """Wait for next run interval with early exit on signal."""
        start_time = time.time()
        end_time = start_time + self.interval_seconds
        
        while time.time() < end_time and self.running:
            time.sleep(1)  # Check every second for early exit
    
    def _format_interval(self) -> str:
        """Format interval as human-readable string."""
        if self.interval_seconds < 60:
            return f"{self.interval_seconds}s"
        elif self.interval_seconds < 3600:
            minutes = self.interval_seconds // 60
            return f"{minutes}m"
        else:
            hours = self.interval_seconds // 3600
            minutes = (self.interval_seconds % 3600) // 60
            if minutes == 0:
                return f"{hours}h"
            else:
                return f"{hours}h{minutes}m"
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        print("\nShutdown signal received, stopping...")
        self.stop()


def parse_interval(interval_str: str) -> int:
    """
    Parse interval string like '12h', '30m', '1h30m' to seconds.
    
    Args:
        interval_str: Interval string (e.g., "12h", "30m", "1h30m")
        
    Returns:
        Interval in seconds
        
    Raises:
        ValueError: If format is invalid
    """
    import re
    
    # Pattern to match time components
    pattern = r'(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$'
    match = re.match(pattern, interval_str.strip().lower())
    
    if not match:
        raise ValueError(f"Invalid interval format: {interval_str}")
    
    hours, minutes, seconds = match.groups()
    
    total_seconds = 0
    if hours:
        total_seconds += int(hours) * 3600
    if minutes:
        total_seconds += int(minutes) * 60
    if seconds:
        total_seconds += int(seconds)
    
    if total_seconds == 0:
        raise ValueError("Interval must be greater than 0")
    
    return total_seconds