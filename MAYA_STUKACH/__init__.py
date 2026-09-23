# -*- coding: utf-8 -*-
"""
STUKACH for Maya — Pipeline asset validation system.

Usage (Maya Script Editor or shelf button):
    import MAYA_STUKACH
    MAYA_STUKACH.launch()
"""
from .ui import launch, close

__all__ = ["launch", "close"]
__version__ = "1.2.0"
__author__  = "Maksim Kovalev"
