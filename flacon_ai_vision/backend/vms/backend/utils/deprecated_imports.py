"""
Utility module for handling deprecated imports like pkg_resources

This module provides compatibility layer for deprecated Python packaging APIs.
When pkg_resources is removed (Setuptools 85+), code should migrate to importlib.metadata.
"""

import sys
import warnings
from typing import Optional

# Suppress pkg_resources deprecation warnings
warnings.filterwarnings("ignore", category=UserWarning, module=".*pkg_resources.*")
warnings.filterwarnings("ignore", message=".*pkg_resources is deprecated.*")


def get_resource_filename(package_name: str, resource_path: str) -> str:
    """
    Get the absolute path to a resource file.
    
    This is a wrapper that provides compatibility between pkg_resources and importlib.metadata.
    
    Args:
        package_name: The package name (e.g., 'face_recognition_models')
        resource_path: Path to the resource within the package
        
    Returns:
        Absolute path to the resource
        
    Example:
        >>> path = get_resource_filename('face_recognition_models', 'models/shape_predictor.dat')
    """
    try:
        # Try modern importlib.resources (Python 3.9+)
        if sys.version_info >= (3, 9):
            from importlib.resources import files
            try:
                package = files(package_name)
                resource = package.joinpath(resource_path)
                # Ensure it's extracted/available on disk
                if hasattr(resource, 'as_file'):
                    from contextlib import contextmanager
                    @contextmanager
                    def managed_resource():
                        from importlib.resources import as_file
                        with as_file(resource) as path:
                            yield str(path)
                    # Return the path - this is a simplified version
                    return str(resource)
            except Exception:
                pass
    except ImportError:
        pass
    
    # Fallback to pkg_resources (deprecated but still works with Setuptools <85)
    try:
        from pkg_resources import resource_filename
        return resource_filename(package_name, resource_path)
    except ImportError:
        raise ImportError(
            f"Cannot load resource {resource_path} from {package_name}. "
            "Install setuptools or use importlib.resources instead."
        )


def get_package_version(package_name: str) -> Optional[str]:
    """
    Get the version of an installed package.
    
    Prefers importlib.metadata over the deprecated pkg_resources.
    
    Args:
        package_name: The package name (e.g., 'face-recognition')
        
    Returns:
        Version string or None if not found
        
    Example:
        >>> version = get_package_version('fastapi')
        >>> print(version)
        '0.104.1'
    """
    try:
        # Modern approach (Python 3.8+)
        from importlib.metadata import version, PackageNotFoundError
        try:
            return version(package_name)
        except PackageNotFoundError:
            return None
    except ImportError:
        pass
    
    # Fallback to pkg_resources (deprecated)
    try:
        import pkg_resources
        try:
            return pkg_resources.get_distribution(package_name).version
        except:
            return None
    except ImportError:
        return None


__all__ = [
    'get_resource_filename',
    'get_package_version',
]
