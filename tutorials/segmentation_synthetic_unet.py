import trw
import torch.nn as nn


class Net(nn.Module):
    def __init__(self):
        super(Net, self).__init__()
        self.unet = trw.layers.UNetBase(2, input_channels=3, output_channels=2, channels=[4, 8, 16])

    def forward(self, batch):
        x = self.unet(batch['image'])

        return {
            'segmentation': trw.train.OutputSegmentation2(output=x, output_truth=batch['mask']),
            'segmentation_output': trw.train.OutputEmbedding(x.argmax(dim=1, keepdim=True))
        }


def per_epoch_callbacks():
    return [
        trw.train.CallbackReportingExportSamples(max_samples=5),
        trw.train.CallbackEpochSummary(),
    ]


trainer = trw.train.Trainer(callbacks_per_epoch_fn=per_epoch_callbacks)

model, results = trainer.fit(
    trw.train.create_default_options(num_epochs=15),
    inputs_fn=lambda: trw.datasets.create_fake_symbols_2d_dataset(nb_samples=1000, image_shape=[256, 256], nb_classes_at_once=1, batch_size=50),
    run_prefix='synthetic_segmentation_unet',
    model_fn=lambda options: Net(),
    optimizers_fn=lambda datasets, model: trw.train.create_sgd_optimizers_scheduler_step_lr_fn(datasets=datasets, model=model, learning_rate=0.05, step_size=50, gamma=0.3))
