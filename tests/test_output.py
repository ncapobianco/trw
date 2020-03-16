from unittest import TestCase
import trw.train
import numpy as np
import torch
import functools


class TestOutput(TestCase):
    def test_regression_0_loss(self):
        input_values = torch.from_numpy(np.asarray([[1, 2], [3, 4]], dtype=float))
        target_values = torch.from_numpy(np.asarray([[1, 2], [3, 4]], dtype=float))

        o = trw.train.OutputRegression(input_values, target_name='target')
        batch = {'target': target_values}
        r = o.evaluate_batch(batch, False)

        loss = r['loss'].data.numpy()
        self.assertTrue(len(loss.shape) == 0)
        self.assertTrue(loss == 0.0)

    def test_regression_error(self):
        input_values = torch.from_numpy(np.asarray([[1, 2], [3, 4]], dtype=float))
        target_values = torch.from_numpy(np.asarray([[0, 0], [0, 0]], dtype=float))

        o = trw.train.OutputRegression(input_values, target_name='target')
        batch = {'target': target_values}
        r = o.evaluate_batch(batch, False)

        loss = r['loss'].data.numpy()
        self.assertTrue(len(loss.shape) == 0)
        self.assertTrue(loss == (1+2*2+3*3+4*4) / 4)

    def test_regression_scaling(self):
        input_values = torch.from_numpy(np.asarray([[1, 2], [3, 4]], dtype=float))
        target_values = torch.from_numpy(np.asarray([[0, 0], [0, 0]], dtype=float))

        o = trw.train.OutputRegression(input_values, target_name='target', loss_scaling=2.0)
        batch = {'target': target_values}
        r = o.evaluate_batch(batch, False)

        loss = r['loss'].data.numpy()
        self.assertTrue(len(loss.shape) == 0)
        self.assertTrue(loss == (1+2*2+3*3+4*4) / 4 * 2)

    def test_regression_weight(self):
        input_values = torch.from_numpy(np.asarray([[1, 2], [3, 4]], dtype=float))
        target_values = torch.from_numpy(np.asarray([[0, 0], [0, 0]], dtype=float))
        weights = torch.from_numpy(np.asarray([1, 0], dtype=float))

        o = trw.train.OutputRegression(input_values, target_name='target', weight_name='weights')
        batch = {'target': target_values, 'weights': weights}
        r = o.evaluate_batch(batch, False)

        loss = r['loss'].data.numpy()
        self.assertTrue(len(loss.shape) == 0)
        self.assertTrue(loss == (1+2*2+3*3*0+4*4*0) / 4 * 2)

    def test_classification_0_loss(self):
        input_values = torch.from_numpy(np.asarray([[0.0, 100.0], [100.0, 0.0]], dtype=float))
        target_values = torch.from_numpy(np.asarray([1, 0], dtype=np.int64))

        o = trw.train.OutputClassification(input_values, classes_name='target')
        batch = {'target': target_values}
        r = o.evaluate_batch(batch, False)

        loss = r['loss'].data.numpy()
        self.assertTrue(len(loss.shape) == 0)
        self.assertTrue(loss < 1e-6)

        assert r.get('output') is not None
        self.assertTrue((trw.train.to_value(r['output']) == [1, 0]).all())

    def test_classification_weight(self):
        input_values = torch.from_numpy(np.asarray([[0.0, 100.0], [100.0, 0.0]], dtype=float))
        target_values = torch.from_numpy(np.asarray([1, 1], dtype=np.int64))
        weights = torch.from_numpy(np.asarray([1, 0], dtype=float))

        o = trw.train.OutputClassification(input_values, classes_name='target', weight_name='weights')
        batch = {'target': target_values, 'weights': weights}
        r = o.evaluate_batch(batch, False)

        loss = r['loss'].data.numpy()
        self.assertTrue(len(loss.shape) == 0)
        self.assertTrue(loss < 1e-6)

    def test_output_record(self):
        input_values = torch.from_numpy(np.asarray([[0.0, 100.0], [100.0, 0.0]], dtype=float))
        o = trw.train.OutputRecord(input_values)

        batch = {'i': input_values}
        loss_term = o.evaluate_batch(batch, is_training=False)
        assert loss_term['loss'] == 0.0
        assert (loss_term['output'] == input_values.numpy()).all()

    def test_output_segmentation(self):
        mask_scores = torch.zeros(10, 4, 32, 32, dtype=torch.float32)  # 10 samples, 4 classes, 2D 32x32 grid
        mask_scores[:, 1, :, :] = 100.0
        expected_map = torch.ones(10, 32, 32, dtype=torch.int64)

        o = trw.train.OutputSegmentation(
            output=mask_scores,
            target_name='target',
            weight_name='weights',
            criterion_fn=lambda: functools.partial(trw.train.segmentation_criteria_ce_dice, ce_weight=0.9999999))
        batch = {
            'target': expected_map,
            'weights': torch.ones(10, dtype=torch.float32)
        }
        loss_term = o.evaluate_batch(batch, is_training=False)
        assert trw.train.to_value(loss_term['loss']) < 1e-5
        assert (trw.train.to_value(loss_term['output']) == 1).all()

    def test_output_segmentation_weight(self):
        """
        Make sure the loss can be weighted with a per-voxel mask
        """
        torch.manual_seed(0)
        mask_scores = torch.randn([10, 4, 32, 40], dtype=torch.float32)  # 10 samples, 4 classes, 2D 32x32 grid
        expected_map = torch.ones(10, 32, 40, dtype=torch.int64)

        mask_weight = torch.zeros_like(expected_map, dtype=torch.float32)
        mask_weight[:, 4:21, 8:38] = 1

        def loss(found, expected, per_voxel_weight):
            l = per_voxel_weight.view(10, 1, 32, 40) * found
            return l.sum([1, 2, 3])

        o = trw.train.OutputSegmentation(
            output=mask_scores,
            target_name='target',
            weight_name='weights',
            criterion_fn=lambda: loss)

        batch = {
            'target': expected_map,
            'weights': mask_weight
        }

        loss_term = o.evaluate_batch(batch, is_training=False)
        expected_loss = mask_scores[:, :, 4:21, 8:38].sum([1, 2, 3])

        losses = loss_term['losses']
        assert torch.max(torch.abs(losses - expected_loss)) < 1e-3

    def test_output_triplets(self):
        samples = torch.tensor(
            [
                [[[1, 2]]],  # make sure it works for N-d features
                [[[1, 3]]],
                [[[1, 4]]],
            ])

        samples_p = torch.tensor(
            [
                [[[1, 2.1]]],
                [[[1, 3.1]]],
                [[[1, 4.1]]],
            ])

        samples_n = torch.tensor(
            [
                [[[1, 20.1]]],  # far from the samples_p and margin, should be 0 loss
                [[[1, 3.1]]],  # not satisfying the margin
                [[[1, 40.1]]],  # far from the samples_p and margin, should be 0 loss
            ])

        weights = torch.tensor([1.0, 3.0, 1.0])
        o = trw.train.OutputTriplets(samples, samples_p, samples_n, weight_name='weights')
        loss_term = o.evaluate_batch({'weights': weights}, is_training=False)

        assert loss_term['loss'] == 1.0
        assert loss_term['output_raw'] is samples
        assert isinstance(loss_term['output_ref'], trw.train.OutputTriplets)
