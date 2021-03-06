import copy
import io
import os
import threading
import traceback

from time import sleep, perf_counter

from threadpoolctl import threadpool_limits
from typing import Callable, List, Optional

from trw.basic_typing import Batch
import logging
import numpy as np
from queue import Queue as ThreadQueue, Empty

# Make sure we start a new process in an empty state so
# that Windows/Linux environment behave the similarly
import multiprocessing
multiprocessing = multiprocessing.get_context("spawn")
#multiprocessing = multiprocessing.get_context("fork")
from multiprocessing import Event, Process, Queue, Value

# timeout used for the queues
default_queue_timeout = 0.1


def worker(
        input_queue: Queue,
        output_queue: Queue,
        transform: Callable[[Batch], Batch],
        abort_event: Event,
        wait_time: float,
        seed: int) -> None:
    """
    Worker that will execute a transform on a process.

    Args:
        input_queue: the queue to listen to
        output_queue:  the queue to output the results
        transform: the transform to be applied on each data queued
        abort_event: specify when the jobs need to shutdown
        wait_time: process will sleep this amount of time when input queue is empty
        seed: an int to seed random generators

    Returns:
        None
    """

    np.random.seed(seed)
    item = None
    job_session_id = None
    print(f'Worker={os.getpid()} Started!!')
    while True:
        try:
            #print('Worker: Retrieving job')
            if not abort_event.is_set():
                if item is None:
                    if not input_queue.empty():
                        job_session_id, item = input_queue.get()
                    else:
                        sleep(wait_time)
                        continue

                    if transform is not None:
                        try:
                            item = transform(item)
                            #print('Worker: processing=', item)
                        except Exception as e:
                            # exception is intercepted and skip to next job
                            # here we send the `None` result anyway to specify the
                            # job failed. we MUST send the `None` so that jobs queued
                            # and jobs processed match.
                            print('-------------- ERROR in worker function --------------')
                            print(f'Exception in background worker PID={os.getpid()}, E={e}')
                            print('-------------- first job will be aborted --------------')
                            string_io = io.StringIO()
                            traceback.print_exc(file=string_io)
                            print(string_io.getvalue())
                            print('-------------------------------------------------------')
                            item = None

                output_queue.put((job_session_id, item))
                item = None

            else:
                print(f'Worker={os.getpid()} Stopped (abort_event SET)!!')
                return

        except KeyboardInterrupt:
            abort_event.set()
            print(f'Worker={os.getpid()} Stopped (KeyboardInterrupt)!!')
            return

        except Exception as e:
            # exception is intercepted and skip to next job
            print(f'Exception in background worker thread_id={os.getpid()}, E={e}')
            continue


def collect_results_to_main_process(
        job_session_id: Value,
        jobs_queued: Value,
        worker_output_queues: List[Queue],
        output_queue: ThreadQueue,
        abort_event: Event,
        wait_time: float) -> None:

    assert output_queue is not None
    nb_workers = len(worker_output_queues)
    item = None
    item_job_session_id = None
    queue_ctr = 0
    nb_try = 0
    while True:
        try:
            if abort_event.is_set():
                print(f'Thread={threading.get_ident()}, shutdown!')
                return

            # if we don't have an item we need to fetch it first. If the queue we want to get it from it empty, try
            # again later
            if item is None and item_job_session_id is None:
                nb_try += 1
                queue_ctr = (queue_ctr + 1) % nb_workers
                current_queue = worker_output_queues[queue_ctr]

                if not current_queue.empty():

                    try:
                        time_queue_start = perf_counter()
                        item_job_session_id, item = current_queue.get(timeout=wait_time)
                        time_queue_end = perf_counter()
                    except Empty:
                        # even if the `current_queue` was not empty, another thread might have stolen
                        # the job result already. Just continue to the next queue
                        continue

                    #print('PINNING item_job_session_id=', item_job_session_id, ' current=', job_session_id.value, 'ITEM=', item)

                    if item is None:
                        # this job FAILED so there is no result to queue. Yet, we increment the
                        # job counter since this is used to monitor if the executor is
                        # idle
                        with jobs_queued.get_lock():
                            jobs_queued.value += 1
                            #print(f'PUSH NONE ---- jobs_queued={jobs_queued.value}')

                        # fetch a new job result!
                        item_job_session_id = None
                        continue

                else:
                    # check the other queues
                    if nb_try >= nb_workers + 1:
                        # we have tried too many times and there was
                        # no job to process. Sleep for a while
                        sleep(wait_time)
                        nb_try = 0
                    continue

            if item is None and item_job_session_id is None:
                continue

            if item_job_session_id != job_session_id.value:
                # this is an old result belonging to the previous
                # job session. Discard it and process a new one
                item = None
                item_job_session_id = None
                with jobs_queued.get_lock():
                    jobs_queued.value += 1
                continue

            if not output_queue.full():
                #print(f'Pinning thread output queue filled! item={item}')
                output_queue.put(item)

                item_job_session_id = None
                with jobs_queued.get_lock():
                    jobs_queued.value += 1
                    #print(f'PUSH JOB={item} ---- jobs_queued={jobs_queued.value}')

                item = None
            else:
                sleep(wait_time)
                continue
        except KeyboardInterrupt:
            print(f'Thread={threading.get_ident()}, thread shut down (KeyboardInterrupt)')
            abort_event.set()
            raise KeyboardInterrupt
        except Exception as e:
            print(f'Thread={threading.get_ident()}, thread shut down (Exception)')
            abort_event.set()
            raise e


class JobExecutor2:
    """
    Execute jobs on multiple processes.

    At a high level, we have worker executing on multiple processes. Each worker will be fed
    by an input queue and results of the processing pushed to an output queue.

    Pushing data on a queue is very fast BUT retrieving it from a different process takes time.
    Even if PyTorch claims to have memory shared arrays, retrieving a large array from a queue
    has a linear runtime complexity. To limit this copy penalty, we can use threads that copy
    from the worker process to the main process (`pinning` threads. Here, sharing data between
    threads is almost free).

    Notes:
        This class was designed for maximum speed and not reproducibility in mind.
        The processed of jobs will not keep their ordering.
    """
    def __init__(
            self,
            nb_workers: int,
            function_to_run: Callable[[Batch], Batch],
            max_queue_size_per_worker: int = 2,
            max_queue_size_pin_thread_per_worker: int = 3,
            nb_pin_threads: Optional[int] = None,
            wait_time: float = 0.02,
            wait_until_processes_start: bool = True):
        """

        Args:
            nb_workers: the number of workers (processes) to execute the jobs
            function_to_run: the job to be executed
            max_queue_size_per_worker: define the maximum number of job results that can be stored
                before a process is blocked (i.e., larger queue size will improve performance but will
                require more memory to store the results). the pin_thread need to process the result before
                the blocked process can continue its processing.
            max_queue_size_pin_thread_per_worker: define the maximum number of results available on the main
                process (i.e., larger queue size will improve performance but will require more memory
                to store the results).
            nb_pin_threads: the number of threads dedicated to collect the jobs processed by different processes.
                Data copy from the worker process to main process takes time, in particular for large data. It
                is advantageous to have multiple threads that copy these results to the main process. If `None`,
                nb_workers // 2 threads will be used
            wait_time: the default wait time for a process or thread to sleep if no job is available
            wait_until_processes_start: if True, the main process will wait until the worker processes and
                pin threads are fully running
        """
        print(f'JobExecutor2 started on process={os.getpid()}')
        self.wait_until_processes_start = wait_until_processes_start
        self.wait_time = wait_time
        self.max_queue_size_pin_thread_per_worker = max_queue_size_pin_thread_per_worker
        self.max_queue_size_per_worker = max_queue_size_per_worker
        self.function_to_run = function_to_run
        self.nb_workers = nb_workers

        self.abort_event = Event()
        self.main_process = os.getpid()

        if nb_pin_threads is None:
            self.nb_pin_threads = max(1, nb_workers // 2)
        else:
            self.nb_pin_threads = nb_pin_threads
        assert self.nb_pin_threads >= 1, 'must have at least one thread to collect the processed jobs!'

        self.worker_control = 0
        self.worker_input_queues = []
        self.worker_output_queues = []
        self.processes = []

        self.jobs_processed = Value('i', 0)
        self.jobs_queued = 0

        self.pin_memory_threads = []
        self.pin_memory_queue = None

        # we can't cancel jobs, so instead record a session ID. If session of
        # the worker and current session ID do not match
        # it means the results of these tasks should be discarded
        self.job_session_id = Value('i', 0)

        self.start()

    def start(self, timeout: float = 10.0) -> None:
        """
        Start the processes and queues.

        Args:
            timeout:

        Returns:

        """
        if self.pin_memory_queue is None:
            self.pin_memory_queue = ThreadQueue(self.max_queue_size_pin_thread_per_worker * self.nb_workers)

        if self.nb_workers == 0:
            # nothing to do, this will be executed synchronously on
            # the main process
            return

        if len(self.processes) != self.nb_workers:
            logging.debug(f'Starting jobExecutor={self}, on process={os.getpid()} nb_workers={self.nb_workers}')
            self.close()
            self.abort_event.clear()

            with threadpool_limits(limits=1, user_api='blas'):
                for i in range(self.nb_workers): #maxsize = 0
                    self.worker_input_queues.append(Queue(maxsize=self.max_queue_size_per_worker))
                    self.worker_output_queues.append(Queue(self.max_queue_size_per_worker))

                    p = Process(
                        target=worker,
                        name=f'JobExecutorWorker-{i}',
                        args=(
                            self.worker_input_queues[i],
                            self.worker_output_queues[i],
                            self.function_to_run,
                            self.abort_event,
                            self.wait_time, i
                        ))
                    p.daemon = True
                    p.start()
                    self.processes.append(p)
                    logging.debug(f'Child process={p.pid} for jobExecutor={self}')

            self.pin_memory_threads = []
            for i in range(self.nb_pin_threads):
                pin_memory_thread = threading.Thread(
                    name=f'JobExecutorThreadResultCollector-{i}',
                    target=collect_results_to_main_process,
                    args=(
                        self.job_session_id,
                        self.jobs_processed,
                        self.worker_output_queues,
                        self.pin_memory_queue,
                        self.abort_event,
                        self.wait_time
                    ))
                self.pin_memory_threads.append(pin_memory_thread)
                pin_memory_thread.daemon = True
                pin_memory_thread.start()

            self.worker_control = 0

        if self.wait_until_processes_start:
            # wait until all the processes and threads are alive
            waiting_started = perf_counter()
            while True:
                wait_more = False
                for p in self.processes:
                    if not p.is_alive():
                        wait_more = True
                        continue
                for t in self.pin_memory_threads:
                    if not t.is_alive():
                        wait_more = True
                        continue

                if wait_more:
                    waiting_time = perf_counter() - waiting_started
                    if waiting_time < timeout:
                        sleep(self.wait_time)
                    else:
                        logging.error('the worker processes/pin threads were too slow to start!')

                break
        logging.debug(f'jobExecutor ready={self}')

    def close(self, timeout: float = 10) -> None:
        """
        Stops the processes and threads.

        Args:
            timeout: time allowed for the threads and processes to shutdown cleanly
                before using `terminate()`

        """
        # notify all the threads and processes to be shut down
        print('Setting `abort_event` to interrupt Processes and threads!')
        self.abort_event.set()

        if os.getpid() != self.main_process:
            logging.error(f'attempting to close the executor from a '
                          f'process={os.getpid()} that did not create it! ({self.main_process})')
            return

        # give some time to the threads/processes to shutdown normally
        shutdown_time_start = perf_counter()
        while True:
            wait_more = False
            if len(self.processes) != 0:
                for p in self.processes:
                    if p.is_alive():
                        wait_more = True
                        break
            if len(self.pin_memory_threads):
                for t in self.pin_memory_threads:
                    if t.is_alive():
                        wait_more = True
                        break

            shutdown_time = perf_counter() - shutdown_time_start
            if wait_more:
                if shutdown_time < timeout:
                    sleep(0.1)
                    continue
                else:
                    logging.error('a job did not respond to the shutdown request in the allotted time. '
                                  'It could be that it needs a longer timeout or a deadlock. The processes'
                                  'will now be forced to shutdown!')

            # done normal shutdown or timeout
            break

        if len(self.processes) != 0:
            #logging.debug(f'JobExecutor={self}: shutting down workers...')
            [i.terminate() for i in self.processes]

            for i, p in enumerate(self.processes):
                self.worker_input_queues[i].close()
                self.worker_input_queues[i].join_thread()

                self.worker_output_queues[i].close()
                self.worker_output_queues[i].join_thread()

            self.worker_input_queues = []
            self.worker_output_queues = []
            self.processes = []

        if len(self.pin_memory_threads) > 0:
            for thread in self.pin_memory_threads:
                thread.join()
                del thread
            self.pin_memory_threads = []

            del self.pin_memory_queue
            self.pin_memory_queue = None

    def is_full(self) -> bool:
        """
        Check if the worker input queues are full.

        Returns:
            True if full, False otherwise
        """
        if self.nb_workers == 0:
            return False

        for i in range(self.nb_workers):
            queue = self.worker_input_queues[self.worker_control]
            if not queue.full():
                return False
            self.worker_control = (self.worker_control + 1) % self.nb_workers

        return True

    def put(self, data: Batch) -> bool:
        """
        Queue a batch of data to be processed.

        Warnings:
            if the queues are full, the batch will NOT be appended

        Args:
            data: a batch of data to process

        Returns:
            True if the batch was successfully appended, False otherwise.
        """
        if self.nb_workers == 0:
            batch_in = copy.deepcopy(data)
            batch_out = self.function_to_run(batch_in)
            self.pin_memory_queue.put(batch_out)
            self.jobs_queued += 1
            return True
        else:
            for i in range(self.nb_workers):
                queue = self.worker_input_queues[self.worker_control]
                if not queue.full():
                    queue.put((self.job_session_id.value, data))
                    self.worker_control = (self.worker_control + 1) % self.nb_workers
                    self.jobs_queued += 1
                    return True

            # all queues are full, we have to wait
            return False

    def is_idle(self) -> bool:
        """
        Returns:
            True if the executor is not currently processing jobs
        """
        with self.jobs_processed.get_lock():
            return self.jobs_processed.value == self.jobs_queued

    def reset(self):
        """
        Reset the input and output queues as well as job session IDs.

        The results of the jobs that have not yet been calculated will be discarded
        """

        # here we could clear the queues for a faster implementation.
        # Unfortunately, this is not an easy task to properly
        # counts all the jobs processed or discarded due to the
        # multi-threading. Instead, all tasks queued are executed
        # and we use a `job_session_id` to figure out the jobs to be
        # discarded
        """
        # empty the various queues
        try:
            for input_queue in self.worker_input_queues:
                while not input_queue.empty():
                    input_queue.get()
        except EOFError:  # in case the other process was already terminated
            pass

        try:
            for output_queue in self.worker_output_queues:
                while not output_queue.empty():
                    output_queue.get()
        except EOFError:  # in case the other process was already terminated
            pass
            
        with self.jobs_processed.get_lock():
            self.jobs_processed.value = 0
        self.jobs_queued = 0
        """

        # empty the current queue results, they are not valid anymore!
        try:
            while not self.pin_memory_queue.empty():
                self.pin_memory_queue.get()
        except EOFError:  # in case the other process was already terminated
            pass
        # discard the results of the jobs that will not have the
        # current `job_session_id`
        with self.job_session_id.get_lock():
            self.job_session_id.value += 1

    def __del__(self):
        #logging.debug(f'JobExecutor={self}: destructor called')
        self.close()
