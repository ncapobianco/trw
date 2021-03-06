from unittest import TestCase
import trw.train
import collections
import torch
import numpy as np
import trw.utils
import torch.nn as nn
import torch.nn.functional as F


class Cnn(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv1 = nn.Conv2d(1, 10, 5, 2, padding=1)
        self.conv2 = nn.Conv2d(10, 20, 5, 1, padding=1)
        self.fc1 = nn.Linear(500, 400)
        self.fc2 = nn.Linear(400, 10)

    def forward(self, batch):
        # a batch should be a dictionary of features
        x = batch['images'] / 255.0

        x = F.relu(self.conv1(x))
        x = F.relu(self.conv2(x))
        x = F.max_pool2d(x, 2, 2)
        x = trw.utils.flatten(x)
        x = F.relu(self.fc1(x))
        x = self.fc2(x)

        # here we create a softmax output that will use
        # the `targets` feature as classification target
        return {
            'softmax': trw.train.OutputClassification2(x, batch['targets'])
        }


class TestUtilities(TestCase):
    def test_find_default_dataset_and_split(self):
        datasets = {
            'dataset': {
                'split1': {
                    'feature1': []
                }
            }
        }

        dataset_name, split_name = trw.train.find_default_dataset_and_split_names(datasets)
        assert dataset_name == 'dataset'
        assert split_name == 'split1'

    def test_find_default_dataset_and_split_with_datasetname(self):
        datasets = {
            'dataset': {
                'split1': {
                    'feature1': []
                }
            }
        }

        dataset_name, split_name = trw.train.find_default_dataset_and_split_names(datasets, default_dataset_name='dataset')
        assert dataset_name == 'dataset'
        assert split_name == 'split1'

    def test_find_default_dataset_and_split_with_splitname(self):
        datasets = {
            'dataset': {
                'split1': {
                    'feature1': []
                }
            }
        }

        dataset_name, split_name = trw.train.find_default_dataset_and_split_names(datasets, default_split_name='split1')
        assert dataset_name == 'dataset'
        assert split_name == 'split1'

    def test_find_default_dataset_and_split_with_wrongdatasetname(self):
        datasets = {
            'dataset': {
                'split1': {
                    'feature1': []
                }
            }
        }

        dataset_name, split_name = trw.train.find_default_dataset_and_split_names(
            datasets,
            default_dataset_name='doesntexist')
        assert dataset_name is None
        assert split_name is None

    def test_find_default_dataset_and_split_with_wrongsplitname(self):
        datasets = {
            'dataset': {
                'split1': {
                    'feature1': []
                }
            }
        }

        dataset_name, split_name = trw.train.find_default_dataset_and_split_names(
            datasets,
            default_split_name='doesntexist')
        assert dataset_name is None
        assert split_name is None

    def test_classification_mapping(self):
        datasets_infos = {
            'dataset1': {
                'split1': {
                    'output_mappings': {
                        'output_name': {
                            'mappinginv': {
                                0: 'class_0'
                            }
                        }
                    }
                }
            }
        }

        mapping = trw.train.get_classification_mapping(datasets_infos, 'dataset1', 'split1', 'output_name')
        assert mapping is not None

        class_name = trw.train.get_class_name(mapping, 0)
        assert class_name == 'class_0'

    def test_classification_mapping_none(self):
        mapping = trw.train.get_classification_mapping(None, 'dataset1', 'split1', 'output_name')
        assert mapping is None

        mapping = trw.train.get_classification_mapping({}, 'dataset1', 'split1', 'output_name')
        assert mapping is None

        mapping = trw.train.get_classification_mapping({'dataset1': {}}, 'dataset1', 'split1', 'output_name')
        assert mapping is None

    def test_flatten_dictionaries(self):
        d = collections.OrderedDict()
        d['key1'] = 'v1'
        d['key2'] = {'key3': 'v2'}
        d['key4'] = {'key5': {'key6': 'v3'}}
        flattened_d = trw.utils.flatten_nested_dictionaries(d)
        assert len(flattened_d) == 3
        assert flattened_d['key1'] == 'v1'
        assert flattened_d['key2-key3'] == 'v2'
        assert flattened_d['key4-key5-key6'] == 'v3'

    def test_clamp_n(self):
        t = torch.LongTensor([[1, 2, 3], [4, 5, 6]])
        min = torch.LongTensor([3, 2, 4])
        max = torch.LongTensor([3, 4, 8])
        clamped_t = trw.utils.clamp_n(t, min, max)

        assert (clamped_t == torch.LongTensor([[3, 2, 4], [3, 4, 6]])).all()

    def test_triplets(self):
        targets = [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 4, 4, 5, 5, 5]

        anchors, positives, negatives = trw.train.make_triplet_indices(targets)

        assert len(anchors) == len(positives)
        assert len(anchors) == len(negatives)
        assert len(anchors) == len(targets)

        targets = np.asarray(targets)
        assert (targets[anchors] == targets[positives]).all()
        assert np.max(targets[anchors] == targets[negatives]) == 0

    def test_pairs(self):
        targets = [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 4, 4, 5, 5, 5]

        samples_0, samples_1, same_target = trw.train.make_pair_indices(targets)

        assert len(samples_0) == len(samples_1)
        assert len(samples_0) == len(same_target)

        targets = np.asarray(targets)

        same = targets[samples_0] == targets[samples_1]

        assert (same == same_target).all()

    def test_sub_tensor(self):
        t = torch.randn([5, 10])
        sub_t = trw.utils.sub_tensor(t, [2, 3], [4, 8])
        sub_t2 = t[2:4, 3:8]
        assert sub_t.shape == sub_t2.shape
        assert (sub_t == sub_t2).all()

        # make sure we reference the same underlying tensor
        sub_t[0, 0] = 42
        assert sub_t2[0, 0] == 42

    def test_global_pooling_2d(self):
        t = torch.randn([2, 3, 10, 10])
        t[0, 0, 3, 4] = 42
        t[0, 1, 2, 0] = 43
        t[0, 2, 1, 1] = 44

        t[1, 0, 3, 4] = 142
        t[1, 1, 2, 0] = 143
        t[1, 2, 1, 1] = 144
        g_t = trw.utils.global_max_pooling_2d(t)
        assert g_t.shape == (2, 3)
        assert (g_t - torch.tensor([[42.0, 43.0, 44.0], [142.0, 143.0, 144.0]])).abs().max() <= 1e-5

    def test_global_average_2d(self):
        t = torch.randn([2, 3, 10, 10])
        g_t = trw.utils.global_average_pooling_2d(t)
        assert g_t.shape == (2, 3)

        assert (g_t[0, 0] - trw.utils.flatten(t[0, 0]).mean()).abs().max() <= 1e-5
        assert (g_t[0, 1] - trw.utils.flatten(t[0, 1]).mean()).abs().max() <= 1e-5
        assert (g_t[0, 2] - trw.utils.flatten(t[0, 2]).mean()).abs().max() <= 1e-5
        assert (g_t[1, 0] - trw.utils.flatten(t[1, 0]).mean()).abs().max() <= 1e-5
        assert (g_t[1, 1] - trw.utils.flatten(t[1, 1]).mean()).abs().max() <= 1e-5
        assert (g_t[1, 2] - trw.utils.flatten(t[1, 2]).mean()).abs().max() <= 1e-5

    def test_global_pooling_3d(self):
        t = torch.randn([2, 3, 10, 11, 12])
        t[0, 0, 3, 4, 3] = 42
        t[0, 1, 2, 0, 11] = 43
        t[0, 2, 1, 1, 10] = 44

        t[1, 0, 3, 4, 2] = 142
        t[1, 1, 2, 0, 11] = 143
        t[1, 2, 1, 1, 0] = 144
        g_t = trw.utils.global_max_pooling_3d(t)
        assert g_t.shape == (2, 3)
        assert (g_t - torch.tensor([[42.0, 43.0, 44.0], [142.0, 143.0, 144.0]])).abs().max() <= 1e-5

    def test_global_average_3d(self):
        t = torch.randn([2, 3, 10, 10, 5])
        g_t = trw.utils.global_average_pooling_3d(t)
        assert g_t.shape == (2, 3)

        assert (g_t[0, 0] - trw.utils.flatten(t[0, 0]).mean()).abs().max() <= 1e-5
        assert (g_t[0, 1] - trw.utils.flatten(t[0, 1]).mean()).abs().max() <= 1e-5
        assert (g_t[0, 2] - trw.utils.flatten(t[0, 2]).mean()).abs().max() <= 1e-5
        assert (g_t[1, 0] - trw.utils.flatten(t[1, 0]).mean()).abs().max() <= 1e-5
        assert (g_t[1, 1] - trw.utils.flatten(t[1, 1]).mean()).abs().max() <= 1e-5
        assert (g_t[1, 2] - trw.utils.flatten(t[1, 2]).mean()).abs().max() <= 1e-5

    def test_safe_filename(self):
        filename = 'test/1\\2#3.bin'
        filename_safe = trw.utils.safe_filename(filename, replace_with='?')
        assert filename_safe == 'test?1?2?3.bin'

    def test_clipping(self):
        """
        Make sure the gradient is appropriately clipped
        """

        model = Cnn()
        batch = {
            'images': torch.full([100, 1, 28, 28], 1000, dtype=torch.float32),
            'targets': torch.full([100], 1, dtype=torch.long),
        }
        trw.train.apply_gradient_clipping(model, 0.01)
        output = model(batch)
        loss_terms = output['softmax'].evaluate_batch(batch, is_training=True)
        loss_terms['loss'].backward()

        assert model.fc1.weight.grad.max() <= 0.01
        assert model.fc2.weight.grad.max() <= 0.01
        assert model.conv1.weight.grad.max() <= 0.01
        assert model.conv2.weight.grad.max() <= 0.01

        assert model.fc1.weight.grad.min() >= -0.01
        assert model.fc2.weight.grad.min() >= -0.01
        assert model.conv1.weight.grad.min() >= -0.01
        assert model.conv2.weight.grad.min() >= -0.01

    def test_optional_import(self):
        # import a module, this should be found
        m = trw.utils.optional_import('torch.nn')
        assert m.ReLU is not None

    def test_optional_import_failed(self):
        # import a module that doesn't exist. Error should not be raised
        # until the module is being used (but not imported)
        m = trw.utils.optional_import('module.doesnot.exist')
        assert m is not None

        exception_raised = False
        try:
            m.function_call()
        except Exception:
            exception_raised = True
        assert exception_raised
