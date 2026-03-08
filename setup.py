"""Setup configuration for shellai."""

from setuptools import setup, find_packages
from pathlib import Path

long_description = (Path(__file__).parent / "README.md").read_text(encoding="utf-8")

setup(
    name="shellai",
    version="0.1.0",
    description="Natural language Linux terminal assistant powered by Ollama",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Your Name",
    author_email="you@example.com",
    url="https://github.com/yourusername/shellai",
    license="MIT",
    python_requires=">=3.10",
    packages=find_packages(exclude=["tests*"]),
    install_requires=[],      # Zero runtime deps — stdlib only
    extras_require={
        "dev": [
            "pytest>=7",
            "pytest-cov",
            "ruff",
            "mypy",
            "build",
            "twine",
        ]
    },
    entry_points={
        "console_scripts": [
            "ai = shellai.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: System :: Shells",
        "Topic :: Utilities",
    ],
    keywords="ollama llm cli shell natural-language linux terminal ai assistant",
    project_urls={
        "Bug Tracker": "https://github.com/yourusername/shellai/issues",
        "Documentation": "https://github.com/yourusername/shellai#readme",
        "Source": "https://github.com/yourusername/shellai",
    },
)
