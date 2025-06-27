"""Utility to load package data files."""

import os
from pathlib import Path
from typing import Optional
import pandas as pd
import logging

logger = logging.getLogger(__name__)

def get_package_data_path(filename: str) -> Path:
    """
    Get path to data file in package.
    
    Args:
        filename: Name of the data file
        
    Returns:
        Path to the data file
    """
    # Get the directory where this module is located
    current_dir = Path(__file__).parent
    data_dir = current_dir / "data"
    return data_dir / filename

def load_instrument_data(filename: Optional[str] = None) -> pd.DataFrame:
    """
    Load instrument data CSV from package data directory.
    
    Args:
        filename: Optional filename, defaults to bundled instrument file
        
    Returns:
        DataFrame with instrument data
        
    Raises:
        FileNotFoundError: If data file not found
    """
    if filename is None:
        filename = "Kite_Instrument_ID.csv"  # Default bundled file
    
    try:
        # First try to load from package data
        file_path = get_package_data_path(filename)
        if file_path.exists():
            logger.debug(f"Loading instrument data from package: {file_path}")
            return pd.read_csv(file_path)
    except Exception as e:
        logger.warning(f"Failed to load from package data: {e}")
    
    # Fallback: try to load from current directory or absolute path
    if os.path.exists(filename):
        logger.debug(f"Loading instrument data from: {filename}")
        return pd.read_csv(filename)
    
    raise FileNotFoundError(f"Instrument data file not found: {filename}")

def get_default_instrument_path() -> str:
    """Get the default path to the bundled instrument data file."""
    return str(get_package_data_path("Kite_Instrument_ID.csv"))
