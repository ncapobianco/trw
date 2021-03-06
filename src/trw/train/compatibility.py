import torch.nn.functional


def grid_sample(input, grid, mode='bilinear', padding_mode='zeros', align_corners=None):
    """
    Compatibility layer for argument change between pytorch <= 1.2 and pytorch > 1.2

    See :func:`torch.nn.functional.grid_sample`
    """
    version = torch.__version__[:3]
    if version == '1.0' or version == '1.1' or version == '1.2':
        return torch.nn.functional.grid_sample(
            input=input,
            grid=grid,
            mode=mode,
            padding_mode=padding_mode)
    else:
        return torch.nn.functional.grid_sample(
            input=input,
            grid=grid,
            mode=mode,
            padding_mode=padding_mode,
            align_corners=align_corners)
