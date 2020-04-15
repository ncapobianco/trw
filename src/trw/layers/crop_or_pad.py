import torch.nn.functional as F
import numpy as np
from trw.transforms import batch_crop


def crop_or_pad_fun(x, shape, padding_default_value=0):
    """
    Crop or pad a tensor to the specified shape (``N`` and ``C`` excluded)

    Args:
        x: the tensor shape
        shape: the shape of x to be returned. ``N`` and ``C`` channels must not be specified
        padding_default_value: the padding value to be used

    Returns:
        torch.Tensor
    """
    assert len(shape) + 2 == len(x.shape), f'Expected dim={len(x.shape) - 2} got={len(shape)}. ' \
                                           f'`N` and `C components should not be included!`'

    shape_x = np.asarray(x.shape[2:])
    shape_difference = np.asarray(shape) - shape_x
    assert (shape_difference >= 0).all() or (shape_difference <= 0).all(), \
        f'Not implemented. Expected the decoded shape to ' \
        f'be smaller than x! Shape difference={shape_difference}'

    if np.abs(shape_difference).max() == 0:
        # x has already the right shape!
        return x

    if shape_difference.max() > 0:
        # here we need to add padding
        left_padding = shape_difference // 2
        right_padding = shape_difference - left_padding

        # padding must remove N, C channels & reversed order
        padding = []
        for left, right in zip(left_padding, right_padding):
            padding += [right, left]
        padding = list(padding[::-1])
        padded_decoded_x = F.pad(x, padding, mode='constant', value=padding_default_value)
        return padded_decoded_x
    else:
        # we need to crop the image
        shape_difference = - shape_difference
        left_crop = shape_difference // 2
        right_crop = shape_x - (shape_difference - left_crop)
        cropped_decoded_x = batch_crop(x, [0] + list(left_crop), [x.shape[1]] + list(right_crop))
        return cropped_decoded_x
