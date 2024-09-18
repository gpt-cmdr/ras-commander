from setuptools import setup, find_packages

setup(
    name="ras-commander",
    packages=['ras_commander'],  # Explicitly specify the package
    packages=find_packages(),
    install_requires=[
        "pandas>=1.0.0",
        "requests>=2.25.0",
        "pathlib>=1.0.1",
        "numpy>=1.18.0",
        "h5py>=3.1.0",
        "matplotlib>=3.3.0",
    ],
    extras_require={
        "dev": [
            "pytest>=6.2.0",
            "flake8>=3.9.0",
            "black>=21.5b1",
            "sphinx>=3.5.0",
            "sphinx-rtd-theme>=0.5.0",
        ],
    },
    python_requires=">=3.9",
    author="William Katzenmeyer, P.E., C.F.M.",
    author_email="heccommander@gmail.com",
    description="A library for automating HEC-RAS operations using python functions.",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/billk-FM/ras-commander",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    use_scm_version=True,
    setup_requires=['setuptools_scm'],
)