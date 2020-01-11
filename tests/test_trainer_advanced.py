from unittest import TestCase
import torch.nn as nn
import torch
import trw
import collections
import numpy as np
import functools
import utils
import os


class ModelSimpleRegression(nn.Module):
    def __init__(self):
        super().__init__()
        self.w = nn.Parameter(torch.zeros(1, dtype=torch.float32), requires_grad=True)

    def forward(self, batch):
        x = self.w * batch['input']
        return x


class ComposedModel(nn.ModuleDict):
    def __init__(self):
        super().__init__()
        self['dataset_1'] = ModelSimpleRegression()
        self['dataset_2'] = ModelSimpleRegression()
        self.record = collections.defaultdict(list)

    def forward(self, batch):
        # here we expect to only modify `dataset_2` model parameters when we have `dataset_2` dataset
        # and leave `dataset_1` model parameters constant. Then, the opposite when using `dataset_1` dataset
        dataset_name = batch.get('dataset_name')
        x_1 = self['dataset_1'](batch)
        x_2 = self['dataset_2'](batch)

        w1 = trw.train.to_value(self['dataset_1'].w)
        w2 = trw.train.to_value(self['dataset_2'].w)
        self.record[dataset_name].append({'w1': w1, 'w2': w2})

        o = trw.train.OutputRegression(output=x_1 + x_2, target_name='output')
        return {'regression': o}


class PartNotTrainedModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.model1 = ModelSimpleRegression()
        self.model2 = ModelSimpleRegression()

    def forward(self, batch):
        # make sure model1 is not trained
        with torch.no_grad():
            x_1 = self.model1(batch)
        x_2 = self.model2(batch)

        o = trw.train.OutputRegression(output=x_1 + x_2, target_name='output')
        return {'regression': o}


def create_regression_double_dataset():
    """
    Create a simple dataset where output = input_1 * 2.0
    """
    split = trw.train.SequenceArray({
        'input': np.array([[1.0], [2.0], [3.0], [4.0], [5.0]], dtype=np.float32),
        'output': np.array([[2.0], [4.0], [6.0], [8.0], [10.0]], dtype=np.float32)
    })
    datasets = collections.OrderedDict()
    datasets['dataset_1'] = {
        'train': split,
    }
    datasets['dataset_2'] = {
        'train': split,
    }
    return datasets


def create_regression_single():
    """
    Create a simple dataset where output = input_1 * 2.0
    """
    split = trw.train.SequenceArray({
        'input': np.array([[1.0], [2.0], [3.0], [4.0], [5.0]], dtype=np.float32),
        'output': np.array([[2.0], [4.0], [6.0], [8.0], [10.0]], dtype=np.float32)
    })
    datasets = collections.OrderedDict()
    datasets['dataset_1'] = {
        'train': split,
    }
    return datasets


class TestTrainerAdvanced(TestCase):
    def test_model_dict(self):
        """
        Test model dict. Here we expect to have a composed model (e.g., to train GAN), where
        each part of the model is trained on different datasets.

        We expect to have the parameters of model[datasetname] trained only for datasetname dataset,
        leaving the other parameters unchanged
        """
        options = trw.train.create_default_options(num_epochs=100)
        trainer = trw.train.Trainer(
            callbacks_per_epoch_fn=None,
            callbacks_per_batch_loss_terms_fn=None,
            callbacks_post_training_fn=None,
            callbacks_per_batch_fn=None
        )

        composed_model = ComposedModel()
        optimizer_fn = functools.partial(trw.train.create_sgd_optimizers_fn, learning_rate=0.01)
        model, results = trainer.fit(
            options,
            inputs_fn=create_regression_double_dataset,
            model_fn=lambda options: composed_model,
            optimizers_fn=optimizer_fn)

        # first make sure the model was trained perfectly
        loss_1 = float(trw.train.to_value(results['outputs']['dataset_1']['train']['overall_loss']['loss']))
        loss_2 = float(trw.train.to_value(results['outputs']['dataset_2']['train']['overall_loss']['loss']))
        assert loss_1 < 1e-3
        assert loss_2 < 1e-3

        # we iterate one sample at a time with gradient update. So we expect that for dataset_1, the model 2 parameters
        # will be repeated N times then for dataset_2, the mdoel 1 parameters will be repeated N times. N being the
        # dataset size
        print(len(composed_model.record['dataset_1']))
        print(len(composed_model.record['dataset_2']))
        r_1 = composed_model.record['dataset_1'][11:-1]  # realign the 2 sequences for easy comparison
        r_2 = composed_model.record['dataset_2'][10:-1]
        print(len(r_1))
        print(len(r_2))
        assert len(r_1) == len(r_2)

        dataset_size = 5
        for n in range(2, len(r_1) // dataset_size - 1):
            for nn in range(dataset_size):
                assert r_1[n * dataset_size]['w2'] == r_1[nn + n * dataset_size]['w2']
                assert r_2[n * dataset_size]['w1'] == r_2[nn + n * dataset_size]['w1']

        # make sure we can save a model
        path = os.path.join(utils.root_output, 'model_pytorch.pkl')
        trw.train.Trainer.save_model(model, path=path, result=results)

        # reload the model and compare the parameters
        device = torch.device('cpu')
        loaded_model, loaded_result = trw.train.Trainer.load_model(path=path, with_result=True, device=device)
        w_loaded = trw.train.to_value(loaded_model['dataset_1'].w)
        w = trw.train.to_value(model['dataset_1'].w)
        assert w == w_loaded

        r_loaded = loaded_result['outputs']['dataset_1']['train']['regression']
        r = results['outputs']['dataset_1']['train']['regression']
        assert (r_loaded['output_raw'] == r['output_raw']).all()

    def test_independent_sub_models(self):
        """
        Make sure we can block the training of sub-models using standard torch
        """
        options = trw.train.create_default_options(num_epochs=100)
        trainer = trw.train.Trainer(
            callbacks_per_epoch_fn=None,
            callbacks_per_batch_loss_terms_fn=None,
            callbacks_post_training_fn=None,
            callbacks_per_batch_fn=None
        )
        model = PartNotTrainedModel()

        optimizer_fn = functools.partial(trw.train.create_sgd_optimizers_fn, learning_rate=0.01)
        final_model, results = trainer.fit(
            options,
            inputs_fn=create_regression_double_dataset,
            model_fn=lambda options: model,
            optimizers_fn=optimizer_fn)

        print('Done!')
        # first make sure the model was trained perfectly
        loss = float(trw.train.to_value(results['outputs']['dataset_1']['train']['overall_loss']['loss']))
        assert loss < 1e-3

        # we expect `model1` to not be trained (w=0)
        w_1 = trw.train.to_value(final_model.model1.w)[0]
        assert abs(w_1) < 1e-5