from setuptools import setup, find_packages

setup(
    name="ras_commander",  # Your package name
    version="0.1.0",  # Initial release version
    author="William Katzenmeyer, P.E., C.F.M.",  
    author_email="heccommander@gmail.com",  
    description="A library for automating HEC-RAS operations using python functions.",
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url="https://github.com/yourusername/ras_commander",  # Project's URL, e.g., GitHub repository
    packages=find_packages(),  # Automatically finds all sub-packages
    include_package_data=True,  # To include non-Python files specified in MANIFEST.in
    install_requires=[  # List the libraries your package depends on
        "pandas",
        # Add any other dependencies here
    ],
    classifiers=[  # Classifiers help users find your package
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.6',  # Specify the Python versions your package supports
)
