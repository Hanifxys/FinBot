#!/usr/bin/env python3
"""Test script to check for circular imports"""

try:
    import core
    print("✓ Core module imports successfully")
    
    # Test that monitor can be imported without circular imports
    from modules.monitor import init_dependencies
    print("✓ Monitor module imports successfully")
    
    # Test that core can initialize components
    core.init_components()
    print("✓ Core components initialize successfully")
    
    print("All imports successful - no circular imports detected!")
    
except ImportError as e:
    print(f"✗ ImportError: {e}")
    print("This indicates a circular import issue")
    
except Exception as e:
    print(f"✗ Other error: {e}")
    print("This may be a different issue")