from typing import Sequence, Union, Dict, Any, List
from typing_extensions import Protocol  # backward compatibility for python 3.6-3.7
import numpy as np
import torch

"""Generic numeric type"""
Numeric = Union[int, float]

"""Generic Shape"""
Shape = Sequence[int]

"""Shape expressed as [N, C, D, H, W, ...] components"""
ShapeNCX = Sequence[int]

"""Shape expressed as [C, D, H, W, ...] components"""
ShapeCX = Sequence[int]

"""Shape expressed as [D, H, W, ...] components"""
ShapeX = Sequence[int]

"""Generic Tensor as numpy or torch"""
Tensor = Union[np.ndarray, torch.Tensor]

"""Generic Tensor as numpy or torch. Must be shaped as [N, C, D, H, W, ...]"""
TensorNCX = Union[np.ndarray, torch.Tensor]

"""Generic Tensor as numpy or torch. Must be shaped as 2D array [N, X]"""
TensorNX = Union[np.ndarray, torch.Tensor]

"""Generic Tensor with th `N` and `C` components removed"""
TensorX = Union[np.ndarray, torch.Tensor]


"""Torch Tensor. Must be shaped as [N, C, D, H, W, ...]"""
TorchTensorNCX = torch.Tensor

"""Torch Tensor. Must be shaped as 2D array [N, X]"""
TorchTensorNX = torch.Tensor

"""Torch Tensor with th `N` and `C` components removed"""
TorchTensorX = torch.Tensor


"""Numpy Tensor. Must be shaped as [N, C, D, H, W, ...]"""
NumpyTensorNCX = np.ndarray

"""Numpy Tensor. Must be shaped as 2D array [N, X]"""
NumpyTensorNX = np.ndarray

"""Numpy Tensor with th `N` and `C` components removed"""
NumpyTensorX = np.ndarray

"""Represent a dictionary of (key, value)"""
Batch = Dict[str, Any]

"""Length shaped as D, H, W, ..."""
Length = Sequence[float]

"""Represent a data split, a dictionary of any value"""
Split = Dict[str, Any]

"""Represent a dataset which is composed of named data splits"""
Dataset = Dict[str, Split]

"""Represent a collection of datasets"""
Datasets = Dict[str, Dataset]
DatasetsInfo = Datasets


Activation = Any


NestedIntSequence = List[Sequence[int]]

ConvKernels = Union[int, List[int], NestedIntSequence]
ConvStrides = ConvKernels
PoolingSizes = ConvKernels

Stride = Union[int, Sequence[int]]
KernelSize = Union[int, Sequence[int]]
Padding = Union[int, str, Sequence[int]]
Paddings = Union[str, int, List[int], List[str], NestedIntSequence]
