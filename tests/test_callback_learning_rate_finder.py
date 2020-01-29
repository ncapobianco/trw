import unittest
import collections
import trw
import torch.nn as nn
import torch
import numpy as np
import functools


def create_simple_regression(factor, nb_samples=100):
    i = np.random.randn(nb_samples, 1).astype(np.float32)
    o = i * np.float32(factor)

    datasets = collections.OrderedDict()
    sampler = trw.train.SamplerRandom(batch_size=256)
    datasets['simple'] = {
        'train': trw.train.SequenceArray({
                'input': i,
                'output': o}, sampler=sampler)
    }
    return datasets


class ModelSimpleRegression(nn.Module):
    def __init__(self):
        super().__init__()
        with torch.no_grad():
            p = torch.ones(1, dtype=torch.float32) * 0.0001
        self.w = nn.Parameter(p, requires_grad=True)

    def forward(self, batch):
        x = self.w * batch['input']
        o = trw.train.OutputRegression(output=x, target_name='output')
        return {'regression': o}


optimizer_fn = functools.partial(trw.train.create_sgd_optimizers_fn, learning_rate=10.0, momentum=0)


class TestCallbackLearningRateFinder(unittest.TestCase):
    def test_always_find_good_LR(self):
        """
        Here we always try to find a good LR for random models. Make sure we also plot the LR search

        Initial learning rate is too high and wont converge. Use the LR finder to set this automatically
        """
        torch.manual_seed(0)
        np.random.seed(0)
        options = trw.train.create_default_options(device=torch.device('cpu'), num_epochs=200)
        trainer = trw.train.Trainer(
            callbacks_post_training_fn=None,
            callbacks_pre_training_fn=lambda: [trw.train.CallbackLearningRateFinder(set_new_learning_rate=True)]
        )
        model, results = trainer.fit(
            options,
            inputs_fn=functools.partial(create_simple_regression, factor=10.0),
            model_fn=lambda _: ModelSimpleRegression(),
            optimizers_fn=optimizer_fn,
            run_prefix='LR_finder',
            eval_every_X_epoch=2)

        assert float(results['history'][-1]['simple']['train']['overall_loss']['loss']) < 1e-6


if __name__ == '__main__':
    unittest.main()
