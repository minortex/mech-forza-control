# Backward compatibility shim — tools/*.py  continue to import ec_io unchanged.
from ec.io import *  # noqa: F401, F403
