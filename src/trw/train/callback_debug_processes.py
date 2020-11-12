import collections
import datetime
import io
import os
import sys
import threading
import multiprocessing as mp
import logging
import time
import traceback
from numbers import Number
from pprint import PrettyPrinter

from trw.utils import optional_import

psutil = optional_import('psutil')

from trw.train import callback


def bytes2human(n):
    # http://code.activestate.com/recipes/578019
    # >>> bytes2human(10000)
    # '9.8K'
    # >>> bytes2human(100001221)
    # '95.4M'
    symbols = ('K', 'M', 'G', 'T', 'P', 'E', 'Z', 'Y')
    prefix = {}
    for i, s in enumerate(symbols):
        prefix[s] = 1 << (i + 1) * 10
    for s in reversed(symbols):
        if n >= prefix[s]:
            value = float(n) / prefix[s]
            return '%.1f%s' % (value, s)
    return "%sB" % n


def log_process(process):
    proc_infos = collections.OrderedDict()
    try:
        file_descriptors = process.num_fds()
    except AttributeError:
        file_descriptors = 0
    except psutil.AccessDenied:
        file_descriptors = 'psutil.AccessDenied'

    try:
        handles = process.num_handles()
    except AttributeError:
        handles = 0
    except psutil.AccessDenied:
        handles = 'psutil.AccessDenied'

    memory_info = collections.OrderedDict()
    for name, value_bytes in process.memory_full_info()._asdict().items():
        memory_info[name] = bytes2human(value_bytes)

    proc_infos['pid'] = process.pid
    proc_infos['handles'] = handles
    proc_infos['file_descriptors'] = file_descriptors

    proc_infos['threads'] = [threadid for threadid in process.threads()]
    proc_infos['memory'] = memory_info

    resources = [
        ('RLIMIT_AS', psutil.RLIMIT_AS),
        ('RLIMIT_CORE', psutil.RLIMIT_CORE),
        ('RLIMIT_CPU', psutil.RLIMIT_CPU),
        ('RLIMIT_DATA', psutil.RLIMIT_DATA),
        ('RLIMIT_FSIZE', psutil.RLIMIT_FSIZE),
        ('RLIMIT_MEMLOCK', psutil.RLIMIT_MEMLOCK),
        ('RLIMIT_NOFILE', psutil.RLIMIT_NOFILE),
        ('RLIMIT_NPROC', psutil.RLIMIT_NPROC),
        ('RLIMIT_RSS', psutil.RLIMIT_RSS),
        ('RLIMIT_STACK', psutil.RLIMIT_STACK),
    ]

    resource_soft_hard_limits = collections.OrderedDict()
    for resource_name, resource in resources:
        try:
            l = process.rlimit(resource)
            resource_soft_hard_limits[resource_name] = l
        except OSError:
            pass

    proc_infos['rlimits'] = resource_soft_hard_limits
    proc_infos['status'] = process.status()

    return proc_infos


def log_all_tree(pid=None):
    parent = psutil.Process(pid=pid)

    all_processes = [parent] + parent.children(recursive=True)
    process_logs = []
    for child in all_processes:
        logs = log_process(child)
        process_logs.append(logs)

    stack_traces = []
    for th in threading.enumerate():
        stack_traces.append(str(th) + f' ID={th.ident}')
        try:
            str_io = io.StringIO()
            traceback.print_stack(sys._current_frames()[th.ident], file=str_io)
            stack_traces.append(str_io.getvalue())
        except Exception as e:
            stack_traces.append(f'<traceback failed, exception={e}>')

    logs = collections.OrderedDict()
    virtual_mem = collections.OrderedDict()
    for name, value in psutil.virtual_memory()._asdict().items():
        if isinstance(value, int):
            virtual_mem[name] = bytes2human(value)
    logs['virtual_memory'] = virtual_mem
    logs['processes'] = process_logs
    logs['stack_traces'] = stack_traces
    return logs


def _collect_data(main_process, filename, frequency_seconds, abort_event):
    while True:
        try:
            if abort_event.is_set():
                return

            # here we MUST collect stats on the MAIN process, the one that
            # instantiated the callback
            logs = log_all_tree(main_process)
            with open(filename, 'w') as f:
                f.write(f'Time={datetime.datetime.now()}\n')
                f.write(f'Logging from Process={os.getpid()}\n')
                pp = PrettyPrinter(width=200, stream=f)
                pp.pprint(logs)
            time.sleep(frequency_seconds)

        except KeyboardInterrupt:
            abort_event.set()
            print(f'CollectDataThread={threading.get_ident()} Stopped (KeyboardInterrupt)!!')
            return
        except Exception as e:
            # exception is intercepted and skip to next job
            print(f'CollectDataThread={threading.get_ident()} Exception in background worker thread_id={os.getpid()}, E={e}')
            continue


logger = logging.getLogger(__name__)


class CallbackDebugProcesses(callback.Callback):
    def __init__(self, filename='process_stack_dumps', frequency_seconds=10.0, timeout=10, delayed_init=True):
        super().__init__()

        self.main_process = os.getpid()
        self.filename = filename + f'_{self.main_process}.txt'
        self.abort_event = mp.Event()
        self.frequency_seconds = frequency_seconds
        self.timeout = timeout
        self.thread = None
        self.initialized = False

        if delayed_init:
            self._init()

    def _init(self, root=''):
        self.initialized = True
        self.filename = os.path.join(root, self.filename)
        logger.info(f'initializing new process..., file={self.filename}')

        # here we use a thread and not a process. The reason is that we want
        # to collect the stack trace of the threads in the main process!
        self.thread = threading.Thread(
            name='CollectDebugInfo',
            target=_collect_data,
            args=(
                self.main_process,
                self.filename,
                self.frequency_seconds,
                self.abort_event)
        )

        self.thread.daemon = True
        self.thread.start()
        logger.info(f'process to collect data started! PID={self.thread.ident}, main_process={self.main_process}')

    def __call__(self, options, history, model, losses, outputs, datasets, datasets_infos, callbacks_per_batch, **kwargs):
        # everything is done in the child process
        if not self.initialized:
            self._init()

    def close(self):
        logger.info('shutting down processes!')
        self.abort_event.set()

        if self.thread is None:
            return

        if os.getpid() != self.main_process:
            logging.error(f'attempting to close the process from a '
                          f'process={os.getpid()} that did not create it! ({self.main_process})')
            return

        # give some time to the process to shutdown normally
        shutdown_time_start = time.perf_counter()
        while True:
            if not self.thread.is_alive():
                # normal shutdown
                break
            shutdown_time = time.perf_counter() - shutdown_time_start
            if shutdown_time < self.timeout:
                time.sleep(0.1)
                continue
            else:
                logging.error('a job (_collect_data) did not respond to the shutdown request in the allotted time. '
                              'It could be that it needs a longer timeout or a deadlock. The processes'
                              'will now be forced to shutdown!')
                # error!
                break

        if self.thread.is_alive:
            logger.info('Process is still alive, terminating!')
            self.thread.terminate()

        self.thread.join_thread()
        self.thread = None

    def __del__(self):
        self.close()
