"""AEGIS forensic analysis methods.

Each method declares what kind of evidence it produces (statistical inference, verified watermark,
cryptographic provenance, media-forensic observation, ...) and whether it is operational in the
current environment. A method that cannot run returns an explicit ``unavailable`` result; it never
returns a fabricated score.
"""

__version__ = "0.1.0"
