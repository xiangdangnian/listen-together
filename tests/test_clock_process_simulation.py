import multiprocessing
import time
import unittest

from listen_together.sync.clock import ClockSynchronizer


HOST_OFFSET_US = 5_000_000


def _host_clock_process(connection) -> None:
    try:
        for _ in range(7):
            connection.recv()
            time.sleep(0.004)
            t1_us = time.monotonic_ns() // 1_000 + HOST_OFFSET_US
            time.sleep(0.002)
            t2_us = time.monotonic_ns() // 1_000 + HOST_OFFSET_US
            connection.send((t1_us, t2_us))
    finally:
        connection.close()


class ClockProcessSimulationTests(unittest.TestCase):
    def test_clock_estimate_from_separate_process(self) -> None:
        context = multiprocessing.get_context("spawn")
        parent_connection, child_connection = context.Pipe()
        process = context.Process(
            target=_host_clock_process,
            args=(child_connection,),
        )
        process.start()
        child_connection.close()
        synchronizer = ClockSynchronizer()

        try:
            for _ in range(7):
                t0_us = time.monotonic_ns() // 1_000
                parent_connection.send(t0_us)
                t1_us, t2_us = parent_connection.recv()
                t3_us = time.monotonic_ns() // 1_000
                synchronizer.add_sample(
                    t0_us=t0_us,
                    t1_us=t1_us,
                    t2_us=t2_us,
                    t3_us=t3_us,
                )
        finally:
            parent_connection.close()
            process.join(timeout=5)
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)

        estimate = synchronizer.estimate()
        self.assertLess(abs(estimate.offset_us - HOST_OFFSET_US), 2_000)


if __name__ == "__main__":
    unittest.main()
