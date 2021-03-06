import trw
import numpy as np

import torch
import torch.nn as nn
import torch.nn.functional as F


class Block(nn.Module):
    '''expand + depthwise + pointwise + squeeze-excitation'''

    def __init__(self, in_planes, out_planes, expansion, stride):
        super(Block, self).__init__()
        self.stride = stride

        planes = expansion * in_planes
        self.conv1 = nn.Conv2d(
            in_planes, planes, kernel_size=1, stride=1, padding=0, bias=False)
        self.bn1 = nn.BatchNorm2d(planes)
        self.conv2 = nn.Conv2d(planes, planes, kernel_size=3,
                               stride=stride, padding=1, groups=planes, bias=False)
        self.bn2 = nn.BatchNorm2d(planes)
        self.conv3 = nn.Conv2d(
            planes, out_planes, kernel_size=1, stride=1, padding=0, bias=False)
        self.bn3 = nn.BatchNorm2d(out_planes)

        self.shortcut = nn.Sequential()
        if stride == 1 and in_planes != out_planes:
            self.shortcut = nn.Sequential(
                nn.Conv2d(in_planes, out_planes, kernel_size=1,
                          stride=1, padding=0, bias=False),
                nn.BatchNorm2d(out_planes),
            )

        # SE layers
        self.fc1 = nn.Conv2d(out_planes, out_planes//16, kernel_size=1)
        self.fc2 = nn.Conv2d(out_planes//16, out_planes, kernel_size=1)

    def forward(self, x):
        out = F.relu(self.bn1(self.conv1(x)))
        out = F.relu(self.bn2(self.conv2(out)))
        out = self.bn3(self.conv3(out))
        shortcut = self.shortcut(x) if self.stride == 1 else out
        # Squeeze-Excitation
        w = F.avg_pool2d(out, out.size(2))
        w = F.relu(self.fc1(w))
        w = self.fc2(w).sigmoid()
        out = out * w + shortcut
        return out


class EfficientNet(nn.Module):
    def __init__(self, cfg, num_classes=10):
        super(EfficientNet, self).__init__()
        self.cfg = cfg
        self.conv1 = nn.Conv2d(3, 32, kernel_size=3,
                               stride=1, padding=1, bias=False)
        self.bn1 = nn.BatchNorm2d(32)
        self.layers = self._make_layers(in_planes=32)
        self.linear = nn.Linear(cfg[-1][1], num_classes)

    def _make_layers(self, in_planes):
        layers = []
        for expansion, out_planes, num_blocks, stride in self.cfg:
            strides = [stride] + [1]*(num_blocks-1)
            for stride in strides:
                layers.append(Block(in_planes, out_planes, expansion, stride))
                in_planes = out_planes
        return nn.Sequential(*layers)

    def forward(self, x):
        out = F.relu(self.bn1(self.conv1(x)))
        out = self.layers(out)
        out = out.view(out.size(0), -1)
        out = self.linear(out)
        return out


def EfficientNetB0():
    # (expansion, out_planes, num_blocks, stride)
    cfg = [(1,  16, 1, 2),
           (6,  24, 2, 1),
           (6,  40, 2, 2),
           (6,  80, 3, 2),
           (6, 112, 3, 1),
           (6, 192, 4, 2),
           (6, 320, 1, 2)]
    return EfficientNet(cfg)


class Net(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = EfficientNetB0()

    def forward(self, batch):
        # a batch should be a dictionary of features
        x = batch['images']
        x = self.net(x)

        return {
            'softmax': trw.train.OutputClassification(x, 'targets')
        }


def create_model(options):
    model = Net()
    model = trw.train.DataParallelExtended(model)
    return model


if __name__ == '__main__':
    # configure and run the training/evaluation
    assert torch.cuda.device_count() >= 2, 'not enough CUDA devices for this multi-GPU tutorial!'
    options = trw.train.create_default_options(num_epochs=600)
    trainer = trw.train.Trainer(callbacks_post_training_fn=None)

    mean = np.asarray([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.asarray([0.229, 0.224, 0.225], dtype=np.float32)

    transform_train = [
        trw.transforms.TransformRandomCutout(cutout_size=(3, 16, 16)),
        trw.transforms.TransformRandomCropPad(padding=[0, 4, 4]),
        trw.transforms.TransformRandomFlip(axis=3),
        trw.transforms.TransformNormalizeIntensity(mean=mean, std=std)
    ]

    transform_valid = [
        trw.transforms.TransformNormalizeIntensity(mean=mean, std=std)
    ]

    model, results = trainer.fit(
        options,
        inputs_fn=lambda: trw.datasets.create_cifar10_dataset(transform_train=transform_train,
                                                              transform_valid=transform_valid, nb_workers=0,
                                                              batch_size=400, data_processing_batch_size=None),
        run_prefix='cifar10_resnet50_multigpu',
        model_fn=create_model,
        optimizers_fn=lambda datasets, model: trw.train.create_sgd_optimizers_scheduler_step_lr_fn(
            datasets=datasets, model=model, learning_rate=0.1, momentum=0.9, weight_decay=5e-4, step_size=100,
            gamma=0.3))
