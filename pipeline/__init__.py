"""Build-time data pipeline for MC-FastWiki.

The pipeline runs on a developer machine or in CI. It reads upstream JSON,
and it writes static files into /data/dist. The web app never imports it.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
