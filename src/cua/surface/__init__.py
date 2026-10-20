"""Surface layer: perceive (accessibility tree) and act (click/type/read) on a target app."""
from .base import ActResult, LocatorError, Perception, Surface
from .playwright_web import PlaywrightWebSurface

__all__ = ["Surface", "Perception", "ActResult", "LocatorError", "PlaywrightWebSurface"]
