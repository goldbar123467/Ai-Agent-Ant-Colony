"""
Worker Manager - Runs all 21 workers in a single process.

This allows running all workers efficiently without 21 separate containers.
"""

import asyncio
import signal
from typing import List

import structlog

from ..shared.config import DOMAINS
from .agent import WorkerAgent

logger = structlog.get_logger()


class WorkerManager:
    """Manages all 21 workers in parallel."""

    def __init__(self, domain: str = None):
        """
        Initialize worker manager.

        Args:
            domain: Optional domain filter. If None, runs all 21 workers.
        """
        self.domain = domain
        self.workers: List[WorkerAgent] = []
        self._shutdown_event = asyncio.Event()

    def _get_worker_ids(self) -> List[int]:
        """Get worker IDs to manage."""
        if self.domain:
            return DOMAINS[self.domain].worker_ids
        # All workers
        return list(range(1, 22))

    async def start(self):
        """Start all workers."""
        worker_ids = self._get_worker_ids()
        logger.info("Starting worker manager", workers=len(worker_ids), domain=self.domain)

        # Create workers
        for worker_id in worker_ids:
            worker = WorkerAgent(worker_id)
            self.workers.append(worker)

        # Register all workers first
        register_tasks = []
        for worker in self.workers:
            register_tasks.append(self._register_worker(worker))
        await asyncio.gather(*register_tasks)

        # Start polling for all workers
        poll_tasks = []
        for worker in self.workers:
            poll_tasks.append(worker.mail.start_polling(interval=2.0))
        await asyncio.gather(*poll_tasks)

        logger.info("All workers started", count=len(self.workers))

        # Wait for shutdown
        await self._shutdown_event.wait()

    async def _register_worker(self, worker: WorkerAgent):
        """Register a single worker."""
        await worker.mail.register(program="kyzlo-swarm", model=worker.model)
        await worker._setup_handlers()
        logger.debug("Worker registered", worker_id=worker.worker_id)

    async def stop(self):
        """Stop all workers."""
        logger.info("Stopping worker manager")
        self._shutdown_event.set()

        # Stop all workers
        for worker in self.workers:
            await worker.mail.stop_polling()
            await worker.mail.close()
            await worker.llm.close()

        logger.info("All workers stopped")


def main():
    """Run the worker manager."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--domain",
        choices=["web", "ai", "quant"],
        help="Run only workers for a specific domain",
    )
    args = parser.parse_args()

    manager = WorkerManager(domain=args.domain)

    async def run():
        loop = asyncio.get_running_loop()

        def handle_signal():
            asyncio.create_task(manager.stop())

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, handle_signal)

        await manager.start()

    asyncio.run(run())


if __name__ == "__main__":
    main()
