from . import sampler
from . import sequence
from . import sequence_map

import collections
from queue import Empty
import copy


class SequenceAsyncReservoir(sequence.Sequence):
    """
    This sequence will asynchronously process data and keep a reserve of loaded samples

    The idea is to have long loading processes work in the background while still using as efficiently as possible
    the data that is currently loaded. The data is slowly being replaced by freshly loaded data over time.

    This sequence can be interrupted (e.g., after a certain number of batches have been returned). When the sequence
    is restarted, the reservoir will not be emptied.
    """
    def __init__(
            self,
            source_split,
            max_reservoir_samples,
            function_to_run,
            min_reservoir_samples=1,
            nb_workers=1,
            max_jobs_at_once=None,
            reservoir_sampler=sampler.SamplerSequential(),
            collate_fn=None,
            maximum_number_of_samples_per_epoch=None):
        """
        Args:
            source_split: the source split to iterate
            max_reservoir_samples: the maximum number of samples of the reservoir
            function_to_run: the function to run asynchronously
            min_reservoir_samples: the minimum of samples of the reservoir needed before an output sequence can be created
            nb_workers: the number of workers that will process `function_to_run`
            max_jobs_at_once: the maximum number of jobs that can be pushed in the result list at once. If 0, no limit. If None: set to the number of workers
            reservoir_sampler: a sampler that will be used to sample the reservoir or None if no sampling needed
            collate_fn: a function to post-process the samples into a single batch, or None if not to be collated
            maximum_number_of_samples_per_epoch: the maximum number of samples per epoch to generate.
                If we reach this maximum, this will not empty the reservoir but simply interrupt the sequence so
                that we can restart.
        """
        super().__init__(source_split)
        self.max_reservoir_samples = max_reservoir_samples
        self.min_reservoir_samples = min_reservoir_samples
        self.function_to_run = function_to_run
        self.nb_workers = nb_workers
        self.collate_fn = collate_fn
        self.max_jobs_at_once = max_jobs_at_once
        if max_jobs_at_once is None:
            self.max_jobs_at_once = nb_workers
        self.reservoir_sampler = reservoir_sampler
        assert min_reservoir_samples <= max_reservoir_samples
        assert min_reservoir_samples >= 1

        # this is where we store
        self.reservoir = collections.deque(maxlen=max_reservoir_samples)
        self.iter_source = None
        self.iter_reservoir = None

        self.job_executer = None
        assert nb_workers != 0, 'must have background workers'

        if max_jobs_at_once is None:
            # default: each worker can push at least one item
            # before blocking
            max_jobs_at_once = nb_workers

        self.job_executer = sequence_map.JobExecutor(
            nb_workers=nb_workers,
            function_to_run=self.function_to_run,
            max_jobs_at_once=max_jobs_at_once,
            worker_post_process_results_fun=None)

        self.maximum_number_of_samples_per_epoch = maximum_number_of_samples_per_epoch
        self.number_samples_generated = 0

    def subsample(self, nb_samples):
        subsampled_source = self.source_split.subsample(nb_samples)
        return SequenceAsyncReservoir(
            subsampled_source,
            nb_samples,
            self.function_to_run,
            min_reservoir_samples=nb_samples,
            nb_workers=1,
            max_jobs_at_once=self.max_jobs_at_once,
            reservoir_sampler=copy.deepcopy(self.reservoir_sampler),
            collate_fn=self.collate_fn,
            maximum_number_of_samples_per_epoch=None
        )

    def initializer(self):
        if self.iter_source is None:
            self.iter_source = self.source_split.__iter__()

        self.fill_queue()
        self._retrieve_results()
        if len(self.reservoir) < self.min_reservoir_samples:
            # before we can iterate on sample, we must have enough samples in the reservoir!
            self._wait_for_job_completion()
        self._reset_iter_reservoir()
        self.number_samples_generated = 0

    def _reset_iter_reservoir(self):
        """
        Restart the reservoir iterator
        """

        # make sure the reservoir is not changed during iteration, so take a copy
        # when the iterator is created
        self.reservoir_copy = list(self.reservoir)

        if self.reservoir_sampler is not None:
            # take into account the sampler. If no sampler, we can make it faster
            self.reservoir_sampler.initializer(self.reservoir_copy)
            self.iter_reservoir = iter(self.reservoir_sampler)
        else:
            self.iter_reservoir = self.reservoir_copy.__iter__()

    def fill_queue(self):
        """
        Fill the input queue of jobs to be completed
        """
        # print('fill_queue', os.getpid(), 'NOW=', datetime.datetime.now().time(), self.function_to_run)
        try:
            while not self.job_executer.input_queue.full():
                i = self.iter_source.next_item(blocking=False)
                self.job_executer.input_queue.put(i)
        except StopIteration:
            # we are done! Reset the input iterator
            self.iter_source = self.source_split.__iter__()

    def _retrieve_results(self):
        """
        Retrieve results from the output queue
        """
        # first make sure we can't be `starved`, so fill the input queue
        self.fill_queue()

        # retrieve the results from the output queue and fill the reservoir
        while not self.job_executer.output_queue.empty():
            try:
                # time_blocked_start = time.time()
                items = self.job_executer.output_queue.get()
                # time_blocked_end = time.time()
                # self.time_spent_in_blocked_state += time_blocked_end - time_blocked_start
                self.reservoir.append(items)
            except Empty:
                break

    def _wait_for_job_completion(self):
        """
        Block the processing until we have enough result in the reservoir
        """
        while len(self.reservoir) < self.min_reservoir_samples:
            self._retrieve_results()

    def _get_next(self):
        """
        Returns:
            the next batch of samples
        """
        if self.maximum_number_of_samples_per_epoch is not None and self.number_samples_generated >= self.maximum_number_of_samples_per_epoch:
            # we have reached the maximum number of samples, stop the sequence
            raise StopIteration()

        self._retrieve_results()

        if self.reservoir_sampler is not None:
            # items are actually a list of indices!
            indices = self.iter_reservoir.__next__()
            if isinstance(indices, collections.Iterable):
                items = [self.reservoir[index] for index in indices]
                self.number_samples_generated += len(items)
            else:
                self.number_samples_generated += 1
                items = [self.reservoir[indices]]
        else:
            self.number_samples_generated += 1
            items = [self.iter_reservoir.__next__()]

        if self.collate_fn is not None:
            return self.collate_fn(items)

        return items

    def __next__(self):
        return self._get_next()

    def __iter__(self):
        self.initializer()
        return self

    def __len__(self):
        return len(self.reservoir)