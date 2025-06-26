"""Rate limiting functionality for API requests."""

import time
from concurrent.futures import ThreadPoolExecutor


class RateLimitedThreadPoolExecutor(ThreadPoolExecutor):
    """ThreadPoolExecutor with rate limiting capabilities."""
    
    def __init__(self, max_workers, requests_per_second):
        """
        Initialize rate-limited thread pool executor.
        
        Args:
            max_workers: Maximum number of worker threads
            requests_per_second: Maximum requests per second
        """
        super().__init__(max_workers=max_workers)
        self.requests_per_second = requests_per_second
        self.last_request_time = time.time()
        self.request_count = 0

    def submit(self, fn, *args, **kwargs):
        """
        Submit a function to be executed with rate limiting.
        
        Args:
            fn: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            Future object
        """
        current_time = time.time()
        time_diff = current_time - self.last_request_time

        if time_diff >= 1:  # Reset counter every second
            self.request_count = 0
            self.last_request_time = current_time
        elif self.request_count >= self.requests_per_second:
            sleep_time = 1 - time_diff
            time.sleep(sleep_time)
            self.request_count = 0
            self.last_request_time = time.time()

        self.request_count += 1
        return super().submit(fn, *args, **kwargs)
