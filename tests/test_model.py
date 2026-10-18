import numpy as np
import pandas as pd

from gridrisk import model


def test_captura_top():
    y = pd.Series([100, 0, 0, 0, 0, 0, 0, 0, 0, 0], index=list("abcdefghij"))
    perfeito = y.astype(float)
    assert model.captura_top(y, perfeito, 0.1) == 1.0
    invertido = -perfeito
    assert model.captura_top(y, invertido, 0.1) == 0.0


def test_poisson_deviance_zero_quando_perfeito():
    y = np.array([0, 1, 5])
    assert model.poisson_deviance(y, y.astype(float)) < 1e-6
    assert model.poisson_deviance(y, np.array([2.0, 2.0, 2.0])) > 0
