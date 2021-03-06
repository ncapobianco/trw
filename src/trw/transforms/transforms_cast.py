from typing import Sequence

import numpy as np
import torch
import functools
from trw.transforms import transforms, criteria_feature_name
from trw.basic_typing import Batch

NUMPY_CONVERSION = {
    'float': np.float32,
    'long': np.long,
    'byte': np.int8,
}

TORCH_CONVERSION = {
    'float': torch.float32,
    'long': torch.long,
    'byte': torch.int8,
}


def cast_np(tensor: np.ndarray, cast_type: str) -> np.ndarray:
    t = NUMPY_CONVERSION.get(cast_type)
    if t is None:
        raise NotImplementedError(f'type={cast_type} is not recognized! Expected one of: {list(NUMPY_CONVERSION.keys())}')
    return tensor.astype(t)


def cast_torch(tensor: torch.Tensor, cast_type: str) -> torch.Tensor:
    t = TORCH_CONVERSION.get(cast_type)
    if t is None:
        raise NotImplementedError(
            f'type={cast_type} is not recognized! Expected one of: {list(TORCH_CONVERSION.keys())}')
    return tensor.type(t)


def cast(feature_names: Sequence[str], batch: Batch, cast_type: str) -> Batch:
    for name in feature_names:
        t = batch[name]
        if isinstance(t, np.ndarray):
            batch[name] = cast_np(t, cast_type)
        elif isinstance(t, torch.Tensor):
            batch[name] = cast_torch(t, cast_type)
        else:
            raise NotImplementedError(f'type={type(t)} is not handled!')

    return batch


class TransformCast(transforms.TransformBatchWithCriteria):
    """
    Cast tensors to a specified type
    """
    def __init__(self, feature_names: Sequence[str], cast_type: str):
        """

        Args:
            feature_names:
            cast_type: must be one of `float`, `long`, `byte`
        """
        super().__init__(
            criteria_fn=functools.partial(criteria_feature_name, feature_names=feature_names),
            transform_fn=functools.partial(cast, cast_type=cast_type)
        )
