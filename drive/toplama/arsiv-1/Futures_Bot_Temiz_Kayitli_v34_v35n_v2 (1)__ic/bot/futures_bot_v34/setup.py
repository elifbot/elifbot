"""Kurulum betiği (paper-only araştırma botu)."""
from setuptools import find_packages, setup

setup(
    name="futures_bot",
    version="18.0.0",
    description="Paper-only multi-indicator futures research bot (Binance/OKX public data)",
    python_requires=">=3.10",
    packages=find_packages(exclude=("tests", "tests.*")),
    install_requires=[
        "requests>=2.32.4",
        "pandas>=2.2.3",
        "numpy>=2.0.0",
        "tabulate>=0.9.0",
        "aiohttp>=3.9.0",
    ],
    entry_points={"console_scripts": ["futures-bot=main:main"]},
)
